from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from src.api.db import get_conn
from src.api.integrations import psn_client
from src.api.utils.status import auto_update_status
from src.api.utils import integration_jobs as jobs
from src.api.utils.release_identity import canonical_platform, release_match_score, split_platform_suffix

router = APIRouter(prefix="/sync", tags=["sync"])


class ConfirmPSN(BaseModel):
    np_communication_id: str = Field(min_length=1,max_length=255,pattern=r"^[A-Za-z0-9_-]+$")
    confirmed: Literal[True]


def match_titles(games,titles):
    """Match confirmed IDs and rank safe character/platform candidates."""
    matched, unmatched = [], []
    for title in titles:
        platforms = [canonical_platform(p) for p in title.get("platforms", [])]
        candidates = [g for g in games if g.get("psn_id") == title.get("np_communication_id") and g.get("psn_id")
                   and (not platforms or canonical_platform(g["platform"]) in platforms)]
        matches = [g for g in candidates if g.get("psn_confirmed")]
        if matches:
            matched.extend({**game,"np_id":title["np_communication_id"],"title_icon_url":title.get("title_icon_url")}
                for game in matches)
            continue  # A claimed provider title is never offered to another release.
        needs_review = [g for g in candidates if not g.get("psn_confirmed")]
        suggestions = []
        for game in needs_review:
            score = release_match_score(game,title)
            suggestions.append({"game_id":game["id"],"title":game["title"],
                "platform":game["platform"],"match_state":"legacy","match_reason":"existing_unconfirmed_id",
                "match_score":score,"automatic":False})
        for game in games:
            if game.get("psn_confirmed"):
                continue
            score = release_match_score(game,title)
            if game not in candidates and score:
                suggestions.append({"game_id":game["id"],"title":game["title"],
                    "platform":game["platform"],"match_state":"suggested",
                    "match_reason":"same_normalized_title_and_platform" if score == 1 else "character_similarity_and_platform",
                    "match_score":score,"automatic":False})
        suggestions.sort(key=lambda row:(-row["match_score"],row["title"]))
        exact = [row for row in suggestions if row["match_score"] == 1]
        if len(exact) == 1:
            game = next(g for g in games if g["id"] == exact[0]["game_id"])
            # Never auto-replace a legacy identity; it may have historical progress.
            exact[0]["automatic"] = not game.get("psn_id") or game["psn_id"] == title["np_communication_id"]
        unmatched.append({**title,"local_matches":suggestions})
    # Regional/provider duplicates must also be unambiguous in the opposite direction.
    exact_ids = {}
    for title in unmatched:
        for row in title["local_matches"]:
            if row["match_score"] == 1:
                exact_ids.setdefault(row["game_id"],set()).add(title["np_communication_id"])
    for title in unmatched:
        for row in title["local_matches"]:
            if len(exact_ids.get(row["game_id"],())) > 1:
                row["automatic"] = False
    return matched, unmatched


def _cache_confirmed_artwork(cur,game_id,external_id,url):
    """Only fill missing artwork for a confirmed release; retain its provenance."""
    if not url or not url.startswith("https://"):
        return
    cur.execute("""UPDATE games g SET cover_url=%s,
        specifications=COALESCE(specifications,'{}'::jsonb) || jsonb_build_object('cover_provenance',
            jsonb_build_object('provider','psn','external_id',%s::text,'retrieved_at',NOW())),
        metadata_checked_at=NOW()
        WHERE g.id=%s AND (g.cover_url IS NULL OR g.cover_url='') AND EXISTS(
            SELECT 1 FROM provider_mappings pm WHERE pm.game_id=g.id AND pm.provider='psn'
            AND pm.external_id=%s AND pm.external_id=g.psn_id AND pm.match_state='confirmed')""",
        (url,external_id,game_id,external_id))


def _store_title_summary(cur,game,title):
    external_id=title["np_communication_id"]
    clean_title,_=split_platform_suffix(title.get("title_name") or game["title"])
    platform=canonical_platform(game["platform"]) or game["platform"]
    cur.execute("""UPDATE games SET title=%s,platform=%s,
        specifications=COALESCE(specifications,'{}'::jsonb) || jsonb_build_object(
            'catalog_title_before_psn',COALESCE(specifications->>'catalog_title_before_psn',title),
            'psn_title_provenance',jsonb_build_object('external_id',%s::text,'observed_at',NOW()))
        WHERE id=%s""",(clean_title,platform,external_id,game["id"]))
    cur.execute("""INSERT INTO psn_title_summaries(game_id,external_id,official_title,platform,progress,
        earned_bronze,earned_silver,earned_gold,earned_platinum,total_bronze,total_silver,total_gold,total_platinum,observed_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        ON CONFLICT(game_id) DO UPDATE SET external_id=EXCLUDED.external_id,official_title=EXCLUDED.official_title,
        platform=EXCLUDED.platform,progress=EXCLUDED.progress,earned_bronze=EXCLUDED.earned_bronze,
        earned_silver=EXCLUDED.earned_silver,earned_gold=EXCLUDED.earned_gold,
        earned_platinum=EXCLUDED.earned_platinum,total_bronze=EXCLUDED.total_bronze,
        total_silver=EXCLUDED.total_silver,total_gold=EXCLUDED.total_gold,
        total_platinum=EXCLUDED.total_platinum,observed_at=NOW()""",(
        game["id"],external_id,title.get("title_name") or clean_title,platform,title.get("progress"),
        title.get("earned_bronze",0),title.get("earned_silver",0),title.get("earned_gold",0),title.get("earned_platinum",0),
        title.get("total_bronze",0),title.get("total_silver",0),title.get("total_gold",0),title.get("total_platinum",0)))
    _cache_confirmed_artwork(cur,game["id"],external_id,title.get("title_icon_url"))


@router.get("/status")
def sync_status():
    return {**jobs.latest("psn"),"psn_configured":psn_client.is_configured()}


@router.put("/mappings/{game_id}")
def bind_psn(game_id: int,payload: ConfirmPSN):
    try:
        titles = psn_client.get_all_trophy_titles()
    except Exception:
        raise HTTPException(502,"PSN provider unavailable. Check your local connection and retry.") from None
    candidates = [t for t in titles if t["np_communication_id"] == payload.np_communication_id]
    if not candidates:
        raise HTTPException(422,"Selected trophy set is not present in the connected account.")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT g.id,g.title,g.platform,g.psn_id,EXISTS(
            SELECT 1 FROM provider_mappings pm WHERE pm.game_id=g.id AND pm.provider='psn'
            AND pm.external_id=g.psn_id AND pm.match_state='confirmed') AS psn_confirmed
            FROM games g WHERE g.id=%s FOR UPDATE""",(game_id,))
        game = cur.fetchone()
        if not game:
            raise HTTPException(404,"Game not found")
        if game["psn_id"] and game["psn_id"] != payload.np_communication_id and game["psn_confirmed"]:
            raise HTTPException(409,"Game already has a different trophy set identity.")
        if game["psn_id"] and game["psn_id"] != payload.np_communication_id:
            cur.execute("SELECT EXISTS(SELECT 1 FROM trophies WHERE game_id=%s) AS cached",(game_id,))
            if cur.fetchone()["cached"]:
                raise HTTPException(409,"This release has cached trophy evidence for another identity. Preserve and resolve that evidence before changing its mapping.")
        platforms = candidates[0].get("platforms",[])
        if platforms and canonical_platform(game["platform"]) not in [canonical_platform(p) for p in platforms]:
            raise HTTPException(422,"Selected trophy set does not support this release platform.")
        # The user may explicitly confirm alternate regional/display names; platform must match.
        cur.execute("UPDATE provider_mappings SET match_state='legacy',checked_at=NOW() WHERE game_id=%s AND provider='psn'",(game_id,))
        cur.execute("""UPDATE games SET trophies_cached_at=CASE WHEN psn_id IS DISTINCT FROM %s THEN NULL ELSE trophies_cached_at END,
            psn_id=%s,platform=%s WHERE id=%s""",
            (payload.np_communication_id,payload.np_communication_id,canonical_platform(game["platform"]) or game["platform"],game_id))
        cur.execute("""INSERT INTO provider_mappings(game_id,provider,external_id,match_state,checked_at)
            VALUES(%s,'psn',%s,'confirmed',NOW()) ON CONFLICT(provider,external_id,game_id)
            DO UPDATE SET match_state='confirmed',checked_at=NOW()""",(game_id,payload.np_communication_id))
        _store_title_summary(cur,{**game,"id":game_id},candidates[0])
    return {"game_id":game_id,"psn_id":payload.np_communication_id,"confirmed":True}


@router.post("/psn")
def sync_psn():
    if not psn_client.is_configured():
        raise HTTPException(422,"Connect PSN in the local service configuration before syncing.")
    state = dict(running=True,phase="matching",current_game=None,total_games=0,done_games=0,failed_games=0,outcomes=[])
    job_id = jobs.start("psn",state)
    try:
        titles = psn_client.get_all_trophy_titles()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""SELECT g.id,g.title,g.psn_id,g.platform,EXISTS(
                SELECT 1 FROM provider_mappings pm WHERE pm.game_id=g.id AND pm.provider='psn'
                AND pm.external_id=g.psn_id AND pm.match_state='confirmed') AS psn_confirmed FROM games g""")
            games=list(cur.fetchall())
            matched,unmatched = match_titles(games,titles)
    except Exception:
        state.update(running=False,phase="failed",error="PSN provider unavailable; retry later.")
        jobs.save(job_id,state)
        raise HTTPException(502,state["error"]) from None
    games_by_id={game["id"]:game for game in games}
    used={game["id"] for game in matched}
    remaining=[]
    for title in unmatched:
        candidate=next((row for row in title.get("local_matches",[]) if row.get("automatic") and row["game_id"] not in used),None)
        if not candidate:
            remaining.append(title)
            continue
        game=games_by_id[candidate["game_id"]]
        matched.append({**game,"np_id":title["np_communication_id"],"title_icon_url":title.get("title_icon_url"),
            "provider_title":title,"automatic":True})
        used.add(game["id"])
    try:
        with get_conn() as conn,conn.cursor() as cur:
            for game in matched:
                cur.execute("SELECT psn_id FROM games WHERE id=%s FOR UPDATE",(game["id"],))
                current=cur.fetchone()
                if not current or current["psn_id"] != game["psn_id"]:
                    raise HTTPException(409,"A release mapping changed during sync; retry.")
                provider_title=game.get("provider_title") or next(
                    title for title in titles if title["np_communication_id"]==game["np_id"])
                if game.get("automatic"):
                    cur.execute("UPDATE provider_mappings SET match_state='legacy',checked_at=NOW() WHERE game_id=%s AND provider='psn'",(game["id"],))
                    cur.execute("UPDATE games SET psn_id=%s WHERE id=%s",(game["np_id"],game["id"]))
                    cur.execute("""INSERT INTO provider_mappings(game_id,provider,external_id,match_state,checked_at)
                        VALUES(%s,'psn',%s,'confirmed',NOW()) ON CONFLICT(provider,external_id,game_id)
                        DO UPDATE SET match_state='confirmed',checked_at=NOW()""",(game["id"],game["np_id"]))
                _store_title_summary(cur,game,provider_title)
                state["outcomes"].append({"game_id":game["id"],"outcome":"summary_updated",
                    "match":"automatic" if game.get("automatic") else "confirmed_identity"})
    except Exception:
        state.update(running=False,phase="failed",outcomes=[],done_games=0,
            error="Could not store the PSN account summary; no partial matches were kept.")
        jobs.save(job_id,state)
        raise HTTPException(409,state["error"]) from None
    state.update(running=False,phase="done",total_games=len(matched),done_games=len(matched),failed_games=0,
        unmatched_titles=remaining,current_game=None,last_sync=datetime.now(timezone.utc).isoformat())
    jobs.save(job_id,state)
    return {"message":f"Updated {len(matched)} PSN title summaries in one account pass.","matched":len(matched),
        "job_id":job_id,"unmatched_titles":remaining,**state}


def _upsert_trophies(game_id,trophies,conn=None):
    if conn is None:
        with get_conn() as transaction:
            return _upsert_trophies(game_id,trophies,transaction)
    with conn.cursor() as cur:
        cur.execute("SELECT psn_id FROM games WHERE id=%s",(game_id,))
        game = cur.fetchone()
        set_id = None
        if game and game["psn_id"]:
            cur.execute("""INSERT INTO trophy_sets(game_id,provider,external_id,has_platinum)
                VALUES(%s,'psn',%s,%s) ON CONFLICT(provider,external_id,game_id)
                DO UPDATE SET has_platinum=EXCLUDED.has_platinum RETURNING id""",
                (game_id,game["psn_id"],any(t["trophy_type"] == "platinum" for t in trophies) if trophies else None))
            set_id = cur.fetchone()["id"]
            for group in {t.get("group_id","default") for t in trophies}:
                cur.execute("""INSERT INTO trophy_groups(trophy_set_id,external_id,name,is_base_game)
                    VALUES(%s,%s,%s,%s) ON CONFLICT(trophy_set_id,external_id) DO NOTHING""",
                    (set_id,group,"Base game" if group == "default" else f"Group {group}",group == "default"))
        for trophy in trophies:
            cur.execute("""INSERT INTO trophies(game_id,psn_trophy_id,name,description,trophy_type,trophy_image_url,rarity_percentage,group_id,is_hidden,trophy_set_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(game_id,psn_trophy_id) WHERE psn_trophy_id IS NOT NULL DO UPDATE SET
                name=EXCLUDED.name,description=EXCLUDED.description,trophy_type=EXCLUDED.trophy_type,
                trophy_image_url=EXCLUDED.trophy_image_url,rarity_percentage=EXCLUDED.rarity_percentage,
                group_id=EXCLUDED.group_id,is_hidden=EXCLUDED.is_hidden,trophy_set_id=EXCLUDED.trophy_set_id RETURNING id""",
                (game_id,trophy["psn_trophy_id"],trophy["name"],trophy.get("description"),trophy["trophy_type"],
                 trophy.get("trophy_image_url"),trophy.get("rarity_percentage"),trophy.get("group_id","default"),trophy.get("is_hidden",False),set_id))
            trophy_id = cur.fetchone()["id"]
            if trophy.get("earned") is None:
                continue  # Missing provider progress is not evidence of an unearned trophy.
            cur.execute("""INSERT INTO user_trophies(trophy_id,earned,earned_at,source,observed_at,manual_override)
                VALUES(%s,%s,%s,'psn',NOW(),FALSE) ON CONFLICT(trophy_id) DO UPDATE SET
                earned=EXCLUDED.earned,earned_at=EXCLUDED.earned_at,source='psn',observed_at=NOW()
                WHERE NOT user_trophies.manual_override""",(trophy_id,bool(trophy.get("earned")),trophy.get("earned_at")))
        cur.execute("UPDATE games SET trophies_cached_at=NOW() WHERE id=%s",(game_id,))
    auto_update_status(game_id,conn=conn)
