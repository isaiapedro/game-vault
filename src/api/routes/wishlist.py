from fastapi import APIRouter,HTTPException
from src.api.db import get_conn
from src.api.models.game import GameCreate,GameResponse
from src.api.routes.games import add_game,GAME_SELECT

router=APIRouter(prefix='/wishlist',tags=['wishlist'])


@router.get('',response_model=list[GameResponse])
def get_wishlist():
    with get_conn() as conn,conn.cursor() as cur:
        cur.execute(GAME_SELECT+" WHERE ug.ownership='wanted' ORDER BY ug.added_at DESC")
        return cur.fetchall()


@router.post('',status_code=201,response_model=GameResponse)
async def add_to_wishlist(payload: GameCreate):
    return await add_game(payload.model_copy(update={'ownership':'wanted'}))


@router.delete('/{game_id}',status_code=204)
def remove_from_wishlist(game_id: int):
    with get_conn() as conn,conn.cursor() as cur:
        cur.execute('LOCK TABLE backlog_entries IN SHARE ROW EXCLUSIVE MODE')
        cur.execute("DELETE FROM user_games WHERE game_id=%s AND ownership='wanted' RETURNING id",(game_id,))
        if not cur.fetchone():
            raise HTTPException(404,'Game not in wishlist')
        cur.execute('DELETE FROM backlog_entries WHERE game_id=%s',(game_id,))
        # Retain catalog and session/trophy facts, but remove collection membership.
