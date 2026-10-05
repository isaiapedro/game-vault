import json

from fastapi import APIRouter, HTTPException, Query
from psycopg2 import sql

from src.api.db import get_conn
from src.api.models.game import GameCreate, UserGameStatusUpdate, CollectionUpdate, GameResponse
from src.api.integrations import igdb_client
from src.api.utils.status import auto_update_status

router = APIRouter(prefix='/games', tags=['games'])

GAME_SELECT = """
    SELECT g.*,ug.status,ug.ownership,ug.play_state,ug.goal,ug.next_action,
        ug.purchase_date,ug.purchase_price,ug.notes AS user_notes,
        (SELECT COUNT(*) FROM trophies t WHERE t.game_id=g.id) AS trophy_count,
        (SELECT COUNT(*) FROM trophies t JOIN user_trophies ut ON ut.trophy_id=t.id
            WHERE t.game_id=g.id AND ut.earned) AS earned_count,
        EXISTS(SELECT 1 FROM trophies t JOIN user_trophies ut ON ut.trophy_id=t.id
            WHERE t.game_id=g.id AND t.trophy_type='platinum' AND ut.earned) AS platinum_earned,
        EXISTS(SELECT 1 FROM trophies t JOIN user_trophies ut ON ut.trophy_id=t.id
            WHERE t.game_id=g.id AND t.trophy_type='platinum' AND ut.manual_override) AS platinum_manual_override,
        EXISTS(SELECT 1 FROM backlog_entries be WHERE be.game_id=g.id) AS in_backlog
        ,(SELECT progress FROM psn_title_summaries pts WHERE pts.game_id=g.id) AS psn_progress
        ,(SELECT earned_bronze+earned_silver+earned_gold+earned_platinum
            FROM psn_title_summaries pts WHERE pts.game_id=g.id) AS psn_earned_trophies
        ,(SELECT total_bronze+total_silver+total_gold+total_platinum
            FROM psn_title_summaries pts WHERE pts.game_id=g.id) AS psn_total_trophies
        ,(SELECT observed_at FROM psn_title_summaries pts WHERE pts.game_id=g.id) AS psn_summary_at
        ,(SELECT earned_platinum FROM psn_title_summaries pts WHERE pts.game_id=g.id) AS psn_earned_platinum
    FROM games g JOIN user_games ug ON ug.game_id=g.id
"""


def require_game(cur, game_id):
    cur.execute('SELECT id FROM games WHERE id=%s', (game_id,))
    if not cur.fetchone():
        raise HTTPException(404, 'Game not found')


@router.get('/search')
async def search_igdb(q: str = Query(..., min_length=2)):
    try:
        return await igdb_client.search_games(q)
    except Exception:
        raise HTTPException(502,'Metadata provider unavailable; check local configuration and retry') from None


@router.get('', response_model=list[GameResponse])
def list_games():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(GAME_SELECT + ' ORDER BY g.title')
        return cur.fetchall()


@router.get('/{game_id}', response_model=GameResponse)
def get_game(game_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(GAME_SELECT + ' WHERE g.id=%s', (game_id,))
        game = cur.fetchone()
        if not game:
            raise HTTPException(404, 'Game not in collection')
        cur.execute('SELECT * FROM game_time_estimates WHERE game_id=%s ORDER BY category,provider', (game_id,))
        game['time_estimates'] = cur.fetchall()
        cur.execute('SELECT * FROM provider_mappings WHERE game_id=%s ORDER BY provider', (game_id,))
        game['provider_mappings'] = cur.fetchall()
        return game


@router.post('', status_code=201, response_model=GameResponse)
async def add_game(payload: GameCreate):
    metadata = {}
    if payload.igdb_id:
        try:
            metadata = await igdb_client.get_game_by_id(payload.igdb_id) or {}
        except Exception:
            raise HTTPException(502,'Metadata provider unavailable; check local configuration and retry') from None
        if not metadata:
            raise HTTPException(422, 'Selected metadata source entry was not found')
        if hasattr(igdb_client, 'supports_platform') and not igdb_client.supports_platform(metadata, payload.platform):
            raise HTTPException(422, 'Selected metadata does not match this platform')
    # External time lookup is an explicit enrichment action, never an unreviewed title match.
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(8020004)')
        cur.execute('SELECT id FROM games WHERE platform=%s AND ((%s IS NOT NULL AND igdb_id=%s) OR LOWER(title)=LOWER(%s))',
                    (payload.platform,payload.igdb_id,payload.igdb_id,payload.title.strip()))
        existing = cur.fetchone()
        if existing:
            game_id = existing['id']
            cur.execute('SELECT id FROM user_games WHERE game_id=%s', (game_id,))
            if cur.fetchone():
                raise HTTPException(409, 'This release is already in your collection')
        else:
            cur.execute("""
                INSERT INTO games(title,platform,igdb_id,psn_id,psnprofiles_slug,cover_url,description,
                    developer,publisher,release_date,genres,specifications,metadata_checked_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,
                    CASE WHEN %s THEN NOW() ELSE NULL END) RETURNING id
            """, (metadata.get('title',payload.title.strip()),payload.platform,payload.igdb_id,payload.psn_id,
                  payload.psnprofiles_slug,metadata.get('cover_url'),metadata.get('description'),metadata.get('developer'),
                  metadata.get('publisher'),metadata.get('release_date'),json.dumps(metadata.get('genres',[])),
                  json.dumps(metadata.get('specifications',{})),bool(metadata)))
            game_id = cur.fetchone()['id']
        cur.execute('INSERT INTO user_games(game_id,status,ownership) VALUES(%s,%s,%s)',
                    (game_id,'wishlist' if payload.ownership=='wanted' else 'owned',payload.ownership))
        for provider, external_id in [('igdb',payload.igdb_id),('psn',payload.psn_id)]:
            if external_id is not None:
                cur.execute("""INSERT INTO provider_mappings(game_id,provider,external_id,match_state)
                    VALUES(%s,%s,%s,'confirmed') ON CONFLICT(provider,external_id,game_id)
                    DO UPDATE SET match_state='confirmed',checked_at=NOW()""", (game_id,provider,str(external_id)))
        cur.execute(GAME_SELECT + ' WHERE g.id=%s', (game_id,))
        return cur.fetchone()


@router.delete('/{game_id}', status_code=204)
def delete_game(game_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute('LOCK TABLE backlog_entries IN SHARE ROW EXCLUSIVE MODE')
        cur.execute('DELETE FROM games WHERE id=%s RETURNING id', (game_id,))
        if not cur.fetchone():
            raise HTTPException(404, 'Game not found')


@router.patch('/{game_id}/collection', response_model=GameResponse)
def update_collection(game_id: int, payload: CollectionUpdate):
    fields = payload.model_dump(exclude_unset=True)
    with get_conn() as conn, conn.cursor() as cur:
        require_game(cur,game_id)
        cur.execute('SELECT play_state FROM user_games WHERE game_id=%s FOR UPDATE', (game_id,))
        entry = cur.fetchone()
        if not entry:
            raise HTTPException(404,'Game not in collection')
        collection = {k:v for k,v in fields.items() if not k.startswith('platinum_')}
        feasibility = {k:v for k,v in fields.items() if k.startswith('platinum_')}
        for table, changes in [('user_games',collection),('games',feasibility)]:
            if changes:
                query = sql.SQL('UPDATE {} SET {} WHERE {}=%s').format(sql.Identifier(table),
                    sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(k)) for k in changes),
                    sql.Identifier('id' if table=='games' else 'game_id'))
                cur.execute(query, [*changes.values(),game_id])
        if feasibility:
            cur.execute('UPDATE games SET platinum_checked_at=NOW() WHERE id=%s',(game_id,))
        if 'play_state' in collection and collection['play_state'] != entry['play_state']:
            cur.execute('INSERT INTO play_state_history(game_id,previous_state,play_state) VALUES(%s,%s,%s)',
                        (game_id,entry['play_state'],collection['play_state']))
        auto_update_status(game_id,conn=conn)
        cur.execute(GAME_SELECT + ' WHERE g.id=%s',(game_id,))
        return cur.fetchone()


@router.patch('/{game_id}/status', response_model=GameResponse)
def update_status(game_id: int, payload: UserGameStatusUpdate):
    mapping = {'owned':{'ownership':'owned'},'wishlist':{'ownership':'wanted'},
               'playing':{'play_state':'playing'},'completed':{'play_state':'finished'}}
    if payload.status == 'platinum':
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""SELECT COUNT(*) AS total,COUNT(*) FILTER(WHERE ut.earned) AS earned
                FROM trophies t LEFT JOIN user_trophies ut ON ut.trophy_id=t.id
                WHERE t.game_id=%s AND t.trophy_type='platinum'""",(game_id,))
            evidence = cur.fetchone()
            if not evidence['total'] or evidence['total'] != evidence['earned']:
                raise HTTPException(422,'Platinum requires earned platinum trophy evidence')
        return update_collection(game_id,CollectionUpdate())
    if payload.status not in mapping:
        raise HTTPException(422,'Invalid status')
    return update_collection(game_id,CollectionUpdate(**mapping[payload.status]))
