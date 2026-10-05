from fastapi import APIRouter, HTTPException
from src.api.db import get_conn
from src.api.models.trophy import TrophyEarn
from src.api.integrations import psn_client
from src.api.integrations.psnprofiles_client import slug_from_title
from src.api.utils.status import auto_update_status
from src.api.routes.sync import _upsert_trophies

router = APIRouter(tags=["trophies"])


def _read_trophies(cur,game_id):
    cur.execute("""SELECT t.*,COALESCE(ut.earned,FALSE) AS earned,ut.earned_at,ut.notes AS user_notes,
        ut.source,ut.observed_at,COALESCE(ut.manual_override,FALSE) AS manual_override,
        CASE WHEN tg.is_base_game IS NULL THEN NULL ELSE NOT tg.is_base_game END AS is_dlc,tg.name AS group_name
        FROM trophies t LEFT JOIN user_trophies ut ON ut.trophy_id=t.id
        LEFT JOIN trophy_groups tg ON tg.trophy_set_id=t.trophy_set_id AND tg.external_id=t.group_id
        WHERE t.game_id=%s
        ORDER BY CASE t.trophy_type WHEN 'platinum' THEN 0 WHEN 'gold' THEN 1 WHEN 'silver' THEN 2 ELSE 3 END,t.id""",(game_id,))
    return list(cur.fetchall())


@router.get("/trophies/{game_id}")
def get_trophies(game_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT g.id,g.title,g.platform,g.psn_id,g.trophies_cached_at,EXISTS(
            SELECT 1 FROM provider_mappings pm WHERE pm.game_id=g.id AND pm.provider='psn'
            AND pm.external_id=g.psn_id AND pm.match_state='confirmed') AS psn_confirmed
            FROM games g WHERE g.id=%s""",(game_id,))
        game = cur.fetchone()
        if not game:
            raise HTTPException(404,"Game not found")
        cached = _read_trophies(cur,game_id)
    if cached or game["trophies_cached_at"]:
        return cached
    if game["psn_id"] and not game["psn_confirmed"]:
        raise HTTPException(409,"Review and confirm this release's PSN mapping in Data & sync before fetching trophies.")
    if game["psn_id"] and game["psn_confirmed"] and psn_client.is_configured():
        return _fetch_and_cache_psn(game_id,game["psn_id"],game["platform"])
    return []


def _fetch_and_cache_psn(game_id,np_communication_id,platform):
    try:
        trophies = psn_client.get_trophies_for_game(np_communication_id,platform)
    except Exception:
        raise HTTPException(502,"PSN provider unavailable. Retry from Data & sync.") from None
    with get_conn() as conn:
        _upsert_trophies(game_id,trophies,conn=conn)
        with conn.cursor() as cur:
            result = _read_trophies(cur,game_id)
    return result


@router.get("/trophies/{game_id}/guide")
def get_trophy_guide(game_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT title,psnprofiles_slug FROM games WHERE id=%s",(game_id,))
        game = cur.fetchone()
        if not game:
            raise HTTPException(404,"Game not found")
    slug = game["psnprofiles_slug"] or slug_from_title(game["title"])
    return {"guide":None,"slug":slug,"psnprofiles_url":f"https://psnprofiles.com/guide/{slug}",
            "trophy_list_url":f"https://psnprofiles.com/trophies/{slug}",
            "note":"PSNProfiles requires browser access. These title-based links may require searching for the matching release."}


def _trophy_game(cur,trophy_id):
    cur.execute("SELECT game_id FROM trophies WHERE id=%s",(trophy_id,))
    trophy = cur.fetchone()
    if not trophy:
        raise HTTPException(404,"Trophy not found")
    return trophy["game_id"]


@router.post("/user-trophies/{trophy_id}/earn")
def earn_trophy(trophy_id: int,payload: TrophyEarn):
    with get_conn() as conn, conn.cursor() as cur:
        game_id = _trophy_game(cur,trophy_id)
        cur.execute("""INSERT INTO user_trophies(trophy_id,earned,earned_at,notes,source,observed_at,manual_override)
            VALUES(%s,TRUE,NOW(),%s,'manual',NOW(),TRUE) ON CONFLICT(trophy_id) DO UPDATE SET
            earned=TRUE,earned_at=COALESCE(user_trophies.earned_at,NOW()),notes=EXCLUDED.notes,
            source='manual',observed_at=NOW(),manual_override=TRUE RETURNING *""",(trophy_id,payload.notes))
        result = cur.fetchone()
        auto_update_status(game_id,conn=conn)
    return result


@router.delete("/user-trophies/{trophy_id}/earn",status_code=204)
def unearn_trophy(trophy_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        game_id = _trophy_game(cur,trophy_id)
        cur.execute("""INSERT INTO user_trophies(trophy_id,earned,source,observed_at,manual_override)
            VALUES(%s,FALSE,'manual',NOW(),TRUE) ON CONFLICT(trophy_id) DO UPDATE SET
            earned=FALSE,earned_at=NULL,source='manual',observed_at=NOW(),manual_override=TRUE""",(trophy_id,))
        auto_update_status(game_id,conn=conn)
