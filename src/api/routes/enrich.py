import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field
from src.api.db import get_conn
from src.api.integrations import hltb_client, igdb_client
from src.api.utils import integration_jobs as jobs
from src.api.utils.display_metadata import display_title

router = APIRouter(prefix="/enrich", tags=["enrich"])


class ConfirmMetadata(BaseModel):
    igdb_id: int = Field(gt=0)
    confirmed: Literal[True]


@router.get("/igdb/status")
def metadata_status():
    return {"configured": bool(os.environ.get("TWITCH_CLIENT_ID") and os.environ.get("TWITCH_CLIENT_SECRET"))}


@router.get("/igdb/search")
async def search_metadata(q: str = Query(min_length=2, max_length=200)):
    try:
        return await igdb_client.search_games(q)
    except Exception:
        raise HTTPException(502, "Metadata provider unavailable. Check local configuration and retry.") from None


@router.post("/igdb/{game_id}")
async def apply_metadata(game_id: int, payload: ConfirmMetadata):
    try:
        data = await igdb_client.get_game_by_id(payload.igdb_id)
    except Exception:
        raise HTTPException(502, "Metadata provider unavailable. Retry later.") from None
    if not data:
        raise HTTPException(404, "Provider game not found")
    specifications = dict(data.get("specifications",{}))
    if data.get("cover_url"):
        specifications["cover_provenance"] = {"provider":"igdb","external_id":str(payload.igdb_id),
            "retrieved_at":datetime.now(timezone.utc).isoformat()}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id,platform,title,igdb_id FROM games WHERE id=%s FOR UPDATE", (game_id,))
        game = cur.fetchone()
        if not game:
            raise HTTPException(404, "Game not found")
        if not igdb_client.supports_platform(data, game["platform"]):
            raise HTTPException(422, "Selected release does not list this game's platform.")
        if game["igdb_id"] and game["igdb_id"] != payload.igdb_id:
            raise HTTPException(409, "Game already has a different provider identity.")
        specifications["igdb_title"] = data["title"]
        specifications["display_title"] = display_title(game["title"], data["title"])
        specifications["display_title_provenance"] = {"provider":"igdb","external_id":str(payload.igdb_id)}
        cur.execute("""UPDATE games SET igdb_id=%s, cover_url=COALESCE(%s,cover_url), description=%s,
            developer=%s,publisher=%s,release_date=%s,genres=%s::jsonb,specifications=COALESCE(specifications,'{}'::jsonb) || %s::jsonb,
            metadata_checked_at=NOW() WHERE id=%s""", (payload.igdb_id,data.get("cover_url"),
            data.get("description"),data.get("developer"),data.get("publisher"),data.get("release_date"),
            json.dumps(data.get("genres",[])),json.dumps(specifications),game_id))
        cur.execute("""INSERT INTO provider_mappings(game_id,provider,external_id,match_state,checked_at)
            VALUES(%s,'igdb',%s,'confirmed',NOW()) ON CONFLICT(provider,external_id,game_id)
            DO UPDATE SET match_state='confirmed',checked_at=NOW()""", (game_id,str(payload.igdb_id)))
    return {"game_id":game_id,"igdb_id":payload.igdb_id,"updated":True}


@router.get("/hltb/status")
def hltb_status():
    return jobs.latest("hltb")


@router.post("/hltb")
async def enrich_hltb(background_tasks: BackgroundTasks):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id,title,specifications FROM games WHERE hltb_completionist_hours IS NULL ORDER BY title")
        games = list(cur.fetchall())
    state = dict(running=True,total=len(games),done=0,skipped=0,failed=0,current=None,outcomes=[],phase="enriching")
    job_id = jobs.start("hltb",state)
    background_tasks.add_task(_run_enrichment,games,job_id,state)
    return {"message":f"Started enriching {len(games)} games", "job_id":job_id, **state}


async def _run_enrichment(games,job_id,state):
    for game in games:
        state["current"] = game["title"]
        try:
            original = (game.get("specifications") or {}).get("catalog_title_before_psn")
            aliases = (original,) if isinstance(original,str) and original.strip() != game["title"].strip() else ()
            times = await asyncio.wait_for(hltb_client.get_times(game["title"],aliases=aliases),timeout=60)
            if times.get("match_confidence", "exact_title") == "exact_title" and any(times[k] is not None for k in ("main","main_extra","completionist")):
                with get_conn() as conn, conn.cursor() as cur:
                    cur.execute("""UPDATE games SET hltb_main_hours=COALESCE(%s,hltb_main_hours),
                        hltb_extra_hours=COALESCE(%s,hltb_extra_hours),
                        hltb_completionist_hours=COALESCE(%s,hltb_completionist_hours) WHERE id=%s""",
                        (times["main"],times["main_extra"],times["completionist"],game["id"]))
                    for category,key in (("story","main"),("main_extra","main_extra"),("completionist","completionist")):
                        if times[key] is not None:
                            cur.execute("""INSERT INTO game_time_estimates(game_id,category,hours,provider,source_ref,retrieved_at,match_confidence)
                                VALUES(%s,%s,%s,'hltb',%s,%s,%s) ON CONFLICT(game_id,category,provider)
                                DO UPDATE SET hours=EXCLUDED.hours,source_ref=EXCLUDED.source_ref,
                                retrieved_at=EXCLUDED.retrieved_at,match_confidence=EXCLUDED.match_confidence""",
                                (game["id"],category,times[key],times["source_id"],times["retrieved_at"],times["match_confidence"]))
                state["done"] += 1
                outcome = "updated"
            else:
                state["skipped"] += 1
                outcome = "needs_review" if times["candidates"] else "no_data"
            state["outcomes"].append({"game_id":game["id"],"outcome":outcome,"candidates":times["candidates"] if outcome=="needs_review" else [],"match_confidence":times.get("match_confidence")})
        except Exception:
            state["failed"] += 1
            state["outcomes"].append({"game_id":game["id"],"outcome":"failed","detail":"Estimate provider unavailable; retry later."})
        jobs.save(job_id,state)
        await asyncio.sleep(.5)
    phase = "failed" if state["failed"] and not state["done"] and not state["skipped"] else "partial_success" if state["failed"] else "done"
    state.update(running=False,current=None,phase=phase)
    jobs.save(job_id,state)
