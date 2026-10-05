from fastapi import APIRouter, HTTPException
from psycopg2 import sql
from src.api.db import get_conn
from src.api.models.backlog import BacklogAdd, BacklogUpdate, BacklogReorder, QueueEntry, QueueResponse
from src.api.utils.queue import load_queue, summarize_queue

router = APIRouter(prefix='/backlog',tags=['backlog'])


def lock_queue(cur):
    # Serializes add/remove/reorder across workers without depending on process memory.
    cur.execute('LOCK TABLE backlog_entries IN SHARE ROW EXCLUSIVE MODE')


@router.get('',response_model=QueueResponse)
def get_backlog():
    with get_conn() as conn,conn.cursor() as cur:
        entries = load_queue(cur)
        summary = summarize_queue(entries)
        return {'entries':entries,'summary':summary,**summary}


@router.post('',status_code=201)
def add_to_backlog(payload: BacklogAdd):
    with get_conn() as conn,conn.cursor() as cur:
        lock_queue(cur)
        cur.execute('SELECT game_id FROM user_games WHERE game_id=%s',(payload.game_id,))
        if not cur.fetchone():
            raise HTTPException(404,'Add this release to your collection first')
        cur.execute("""INSERT INTO backlog_entries(game_id,position,target_date,notes,goal)
            VALUES(%s,(SELECT COALESCE(MAX(position),0)+1 FROM backlog_entries),%s,%s,%s)
            ON CONFLICT(game_id) DO NOTHING RETURNING id,game_id,position,target_date,notes,added_at,goal""",(payload.game_id,payload.target_date,payload.notes,'completionist'))
        row = cur.fetchone()
        if not row:
            raise HTTPException(409,'Game already in backlog')
        return row


@router.patch('/{game_id}',response_model=QueueEntry)
def update_backlog(game_id: int,payload: BacklogUpdate):
    fields = payload.model_dump(exclude_unset=True)
    with get_conn() as conn,conn.cursor() as cur:
        lock_queue(cur)
        cur.execute('SELECT id,goal FROM backlog_entries WHERE game_id=%s',(game_id,))
        existing=cur.fetchone()
        if not existing:
            raise HTTPException(404,'Game not in backlog')
        if fields:
            cur.execute(sql.SQL('UPDATE backlog_entries SET {} WHERE game_id=%s').format(
                sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(k)) for k in fields)),[*fields.values(),game_id])
        return next(entry for entry in load_queue(cur) if entry['game_id']==game_id)


@router.delete('/{game_id}',status_code=204)
def remove_from_backlog(game_id: int):
    with get_conn() as conn,conn.cursor() as cur:
        lock_queue(cur)
        cur.execute('DELETE FROM backlog_entries WHERE game_id=%s RETURNING id',(game_id,))
        if not cur.fetchone():
            raise HTTPException(404,'Game not in backlog')
        # Gaps are harmless; do not rewrite the entire queue during removal.


@router.put('/reorder')
def reorder_backlog(payload: BacklogReorder):
    requested = payload.ordered_game_ids
    if len(requested)!=len(set(requested)):
        raise HTTPException(422,'Each queued game must appear exactly once')
    with get_conn() as conn,conn.cursor() as cur:
        lock_queue(cur)
        current = load_queue(cur)
        ids = [row['game_id'] for row in current]
        if set(ids)!=set(requested):
            raise HTTPException(409,'Queue changed; reload before reordering')
        if payload.expected_game_ids is not None and payload.expected_game_ids!=ids:
            raise HTTPException(409,'Queue order changed; reload before reordering')
        completed={entry['game_id']:entry['is_completed'] for entry in current}
        requested=sorted(requested,key=lambda game_id:completed[game_id])
        # Move above the entire occupied range before assigning final positions.
        if current:
            offset = max(row['position'] for row in current)+len(current)+1
            cur.execute('UPDATE backlog_entries SET position=position+%s',(offset,))
            for position,game_id in enumerate(requested,1):
                cur.execute('UPDATE backlog_entries SET position=%s WHERE game_id=%s',(position,game_id))
    return {'ok':True}
