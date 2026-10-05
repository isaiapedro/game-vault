"""Private, deliberate coverage inventory and one-time provider preparation.

No provider call or database write occurs without an explicit flag. All generated
files stay under the ignored .local directory and are never served by the app.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse
from zipfile import ZipFile, ZIP_DEFLATED

from src.api.static_snapshot import load_static_snapshot
from src.api.utils.release_identity import normalized_title


ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".local"
SNAPSHOT = PRIVATE / "game-vault-snapshot.json"
REPORT = PRIVATE / "coverage-report.json"
IGDB_REVIEW = PRIVATE / "igdb-review.json"
GUIDE_REVIEW = PRIVATE / "guide-review.json"
HLTB_REVIEW = PRIVATE / "hltb-review.json"


def _write_private(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _write_review(path: Path, value: dict) -> None:
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if any(any(entry.get(key) is not None for key in
                   ("selected_igdb_id", "selected_source_id", "selected_guide_url"))
               for entry in previous.get("games", [])):
            raise ValueError(f"Review file already has selections; preserve or apply it before regenerating: {path}")
    _write_private(path, value)


def backup_authoring_database() -> Path:
    from psycopg2 import sql
    from src.api.db import get_conn

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    PRIVATE.mkdir(parents=True, exist_ok=True)
    target = PRIVATE / f"game-vault-before-coverage-{stamp}.zip"
    target.touch(mode=0o600, exist_ok=False)
    counts = {}
    try:
        with get_conn() as conn, conn.cursor() as cursor, ZipFile(target, "w", ZIP_DEFLATED) as archive:
            cursor.execute("""SELECT table_name FROM information_schema.tables
                WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name""")
            tables = [row["table_name"] for row in cursor.fetchall()]
            for name in tables:
                cursor.execute(sql.SQL("SELECT row_to_json(t) AS record FROM {} t").format(sql.Identifier(name)))
                with archive.open(f"tables/{name}.jsonl", "w") as output:
                    count = 0
                    for row in cursor:
                        output.write((json.dumps(row["record"], ensure_ascii=False, default=str) + "\n").encode("utf-8"))
                        count += 1
                counts[name] = count
            archive.writestr("manifest.json", json.dumps({"format": "postgres-public-jsonl-v1",
                "captured_at": datetime.now(timezone.utc).isoformat(), "tables": counts}, sort_keys=True))
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def search_titles(game: dict) -> list[str]:
    specs = game.get("specifications") or {}
    historical = specs.get("catalog_title_before_psn") if isinstance(specs, dict) else None
    return list(dict.fromkeys(title.strip() for title in (game.get("title"), historical)
                              if isinstance(title, str) and title.strip()))


def exact_igdb_candidates(entry: dict) -> list[dict]:
    titles = {normalized_title(title) for title in entry.get("searched", [])}
    return [candidate for candidate in entry.get("candidates", [])
            if any(normalized_title(name) in titles for name in
                   [candidate["title"], *candidate.get("alternative_names", [])])]


def reconcile_igdb_review(path: Path, select_unique: bool = False) -> tuple[int, int]:
    review = json.loads(path.read_text(encoding="utf-8"))
    selected = 0
    unresolved = 0
    for entry in review["games"]:
        exact = exact_igdb_candidates(entry)
        exact_ids = {candidate["igdb_id"] for candidate in exact}
        for candidate in entry["candidates"]:
            candidate["exact_name_or_alias"] = candidate["igdb_id"] in exact_ids
        if select_unique and len(exact) == 1 and not entry.get("errors"):
            if entry.get("selected_igdb_id") not in (None, exact[0]["igdb_id"]):
                raise ValueError(f"Game {entry['game_id']}: existing selection conflicts with exact match")
            entry["selected_igdb_id"] = exact[0]["igdb_id"]
            selected += 1
        elif len(exact) != 1:
            unresolved += 1
    _write_private(path, review)
    return selected, unresolved


def select_reviewed_igdb_ids(path: Path, selections: str) -> int:
    """Record explicit game:provider-ID choices after checking the saved candidates."""
    review = json.loads(path.read_text(encoding="utf-8"))
    entries = {int(entry["game_id"]): entry for entry in review["games"]}
    parsed: dict[int, int] = {}
    for pair in selections.split(","):
        game_id, separator, provider_id = pair.strip().partition(":")
        if not separator or not game_id.isdecimal() or not provider_id.isdecimal():
            raise ValueError("IGDB selections must use game_id:igdb_id pairs")
        game_id, provider_id = int(game_id), int(provider_id)
        if game_id in parsed:
            raise ValueError(f"Duplicate selection for game {game_id}")
        parsed[game_id] = provider_id
    if not parsed:
        raise ValueError("At least one reviewed IGDB selection is required")
    for game_id, provider_id in parsed.items():
        entry = entries.get(game_id)
        if entry is None or provider_id not in {item["igdb_id"] for item in entry["candidates"]}:
            raise ValueError(f"Game {game_id}: selected IGDB ID is not a saved same-platform candidate")
        if entry.get("selected_igdb_id") not in (None, provider_id):
            raise ValueError(f"Game {game_id}: a different IGDB ID is already selected")
    all_ids = [parsed.get(game_id, entry.get("selected_igdb_id")) for game_id, entry in entries.items()]
    selected_ids = [value for value in all_ids if value is not None]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("An IGDB release cannot be selected for two collection games")
    for game_id, provider_id in parsed.items():
        entries[game_id]["selected_igdb_id"] = provider_id
    _write_private(path, review)
    return len(parsed)


def curate_display_titles(path: Path) -> int:
    from src.api.db import get_conn
    from src.api.utils.display_metadata import display_title

    review = json.loads(path.read_text(encoding="utf-8"))
    updated = 0
    with get_conn() as conn, conn.cursor() as cursor:
        for entry in review["games"]:
            selected = entry.get("selected_igdb_id")
            if selected is None:
                continue
            candidate = next((item for item in entry["candidates"] if item["igdb_id"] == selected), None)
            if candidate is None:
                raise ValueError(f"Game {entry['game_id']}: selected IGDB title is unavailable")
            label = display_title(entry["title"], candidate["title"])
            fields = {"igdb_title": candidate["title"], "display_title": label,
                      "display_title_provenance": {"provider": "igdb", "external_id": str(selected)}}
            cursor.execute("""UPDATE games SET specifications=COALESCE(specifications,'{}'::jsonb) || %s::jsonb
                WHERE id=%s AND igdb_id=%s AND title=%s RETURNING id""",
                (json.dumps(fields, ensure_ascii=False), entry["game_id"], selected, entry["title"]))
            if cursor.fetchone() is None:
                raise ValueError(f"Game {entry['game_id']}: confirmed release changed since review")
            updated += 1
    return updated


async def expand_igdb_review(path: Path) -> int:
    from src.api.integrations import igdb_client

    review = json.loads(path.read_text(encoding="utf-8"))
    added = 0
    for entry in review["games"]:
        if entry.get("selected_igdb_id") is not None:
            continue
        candidates = {item["igdb_id"]: item for item in entry["candidates"]}
        queries = list(dict.fromkeys(
            [*entry["searched"], *(re.sub(r"\b(?:HD|Trophies)\b", "", title, flags=re.IGNORECASE).strip(" :-")
                                     for title in entry["searched"])]))
        for query in queries:
            if not query:
                continue
            try:
                for item in await igdb_client.search_games(query, limit=50):
                    if not igdb_client.supports_platform(item, entry["platform"]):
                        continue
                    if item["igdb_id"] in candidates:
                        continue
                    candidates[item["igdb_id"]] = {
                        "igdb_id": item["igdb_id"], "title": item["title"],
                        "platforms": item.get("specifications", {}).get("platforms", []),
                        "alternative_names": item.get("specifications", {}).get("alternative_names", []),
                        "version_parent": item.get("specifications", {}).get("version_parent"),
                        "category": item.get("specifications", {}).get("category"),
                        "exact_name_or_alias": False,
                    }
                    added += 1
            except Exception:
                entry.setdefault("errors", []).append("expanded_search_failed")
            await asyncio.sleep(0.3)
        entry["candidates"] = list(candidates.values())
        exact_ids = {item["igdb_id"] for item in exact_igdb_candidates(entry)}
        for item in entry["candidates"]:
            item["exact_name_or_alias"] = item["igdb_id"] in exact_ids
    _write_private(path, review)
    return added


def coverage_rows(payload: dict) -> list[dict]:
    rows = []
    for game in payload["games"]:
        game_id = int(game["id"])
        trophies = payload["trophies"].get(str(game_id), [])
        mapping = [entry for entry in game.get("provider_mappings", [])
                   if entry.get("provider") == "psn" and entry.get("match_state") == "confirmed"
                   and str(entry.get("external_id")) == str(game.get("psn_id"))]
        has_summary = game.get("psn_summary_at") is not None
        status = {
            "metadata_identity": "confirmed" if game.get("igdb_id") else "missing",
            "cover": "confirmed" if game.get("cover_url") else "missing",
            "genres": "confirmed" if game.get("genres") else "missing",
            "developer": "confirmed" if game.get("developer") else "missing",
            "publisher": "confirmed" if game.get("publisher") else "missing",
            "release_date": "confirmed" if game.get("release_date") else "missing",
            "description": "confirmed" if game.get("description") else "missing",
            "completionist_estimate": "confirmed" if game.get("hltb_completionist_hours") else "missing",
            "psn_identity": "confirmed" if mapping else "missing",
            "trophy_summary": "confirmed" if has_summary else "missing",
            "trophy_details": "confirmed" if trophies else "missing",
            "guide_reference": "confirmed" if (game.get("specifications") or {}).get("trophy_guide_url") else "missing",
        }
        rows.append({
            "game_id": game_id, "title": game["title"], "platform": game["platform"],
            "ownership": game.get("ownership"), "search_titles": search_titles(game),
            "igdb_id": game.get("igdb_id"), "psn_id": game.get("psn_id") if mapping else None,
            "psn_summary_at": game.get("psn_summary_at"),
            "trophy_count": len(trophies), "status": status,
            "needs_review": [field for field, value in status.items() if value == "missing"],
            "price_readiness": {"currency": "BRL", "offer_status": "not_configured",
                                "storefront": None, "product_id": None, "edition": None},
        })
    return rows


def inventory(payload: dict) -> dict:
    rows = coverage_rows(payload)
    fields = rows[0]["status"] if rows else {}
    return {
        "snapshot_captured_at": payload["captured_at"],
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "total_games": len(rows),
        "field_coverage": {field: sum(row["status"][field] == "confirmed" for row in rows)
                           for field in fields},
        "games": rows,
    }


async def igdb_candidates(rows: list[dict]) -> dict:
    from src.api.integrations import igdb_client

    if not os.environ.get("TWITCH_CLIENT_ID") or not os.environ.get("TWITCH_CLIENT_SECRET"):
        raise RuntimeError("IGDB requires TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET in config/.env")
    reviews = []
    for row in rows:
        if row["igdb_id"]:
            continue
        candidates = {}
        errors = []
        for title in row["search_titles"]:
            try:
                for item in await igdb_client.search_games(title):
                    if not igdb_client.supports_platform(item, row["platform"]):
                        continue
                    aliases = item.get("specifications", {}).get("alternative_names", [])
                    exact = normalized_title(title) in {normalized_title(name) for name in [item["title"], *aliases]}
                    candidates[item["igdb_id"]] = {
                        "igdb_id": item["igdb_id"], "title": item["title"],
                        "platforms": item.get("specifications", {}).get("platforms", []),
                        "alternative_names": aliases, "version_parent": item.get("specifications", {}).get("version_parent"),
                        "category": item.get("specifications", {}).get("category"),
                        "exact_name_or_alias": exact,
                    }
            except Exception:
                errors.append("provider_request_failed")
            await asyncio.sleep(0.3)
        reviews.append({"game_id": row["game_id"], "title": row["title"],
                        "platform": row["platform"], "searched": row["search_titles"],
                        "candidates": list(candidates.values()), "errors": errors,
                        "selected_igdb_id": None})
    for entry in reviews:
        exact_ids = {candidate["igdb_id"] for candidate in exact_igdb_candidates(entry)}
        for candidate in entry["candidates"]:
            candidate["exact_name_or_alias"] = candidate["igdb_id"] in exact_ids
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "games": reviews}


async def apply_igdb_reviews(path: Path) -> tuple[int, int]:
    from src.api.routes.enrich import ConfirmMetadata, apply_metadata
    from src.api.db import get_conn

    source = json.loads(path.read_text(encoding="utf-8"))
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT id,igdb_id FROM games")
        existing = {row["id"]: row["igdb_id"] for row in cursor.fetchall()}
    applied = 0
    skipped = 0
    for entry in source["games"]:
        selected = entry.get("selected_igdb_id")
        if selected is None:
            skipped += 1
            continue
        ids = {candidate["igdb_id"] for candidate in entry["candidates"]}
        if not isinstance(selected, int) or selected not in ids:
            raise ValueError(f"Game {entry['game_id']}: selected IGDB ID must be one of its reviewed candidates")
        if existing.get(int(entry["game_id"])) == selected:
            skipped += 1
            continue
        if existing.get(int(entry["game_id"])) is not None:
            raise ValueError(f"Game {entry['game_id']}: existing IGDB identity conflicts with review")
        await apply_metadata(int(entry["game_id"]), ConfirmMetadata(igdb_id=selected, confirmed=True))
        applied += 1
        if applied % 10 == 0:
            print(f"Applied {applied} reviewed IGDB mappings...", flush=True)
        await asyncio.sleep(0.3)
    return applied, skipped


async def refresh_igdb_scores() -> tuple[int, int]:
    """Cache user ratings by confirmed ID; absent IGDB ratings stay unknown."""
    from src.api.db import get_conn
    from src.api.integrations.igdb_client import get_game_scores_by_ids

    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT id,igdb_id FROM games WHERE igdb_id IS NOT NULL ORDER BY id")
        games = list(cursor.fetchall())
    scores = await get_game_scores_by_ids([int(game["igdb_id"]) for game in games])
    updated = missing = 0
    with get_conn() as conn, conn.cursor() as cursor:
        for game in games:
            result = scores.get(int(game["igdb_id"]))
            if result is None:
                missing += 1
                continue
            fields = {**result, "igdb_score_provenance": {
                "provider": "igdb", "external_id": str(game["igdb_id"]),
                "retrieved_at": datetime.now(timezone.utc).isoformat(), "kind": "user_rating"}}
            cursor.execute("""UPDATE games SET specifications=COALESCE(specifications,'{}'::jsonb) || %s::jsonb
                WHERE id=%s AND igdb_id=%s RETURNING id""",
                (json.dumps(fields), game["id"], game["igdb_id"]))
            if cursor.fetchone() is None:
                raise ValueError(f"Game {game['id']}: confirmed IGDB identity changed during score refresh")
            updated += 1
    return updated, missing


async def refresh_igdb_artwork() -> tuple[int, int]:
    """Cache reviewed-release landscape choices, never title-search candidates."""
    from src.api.db import get_conn
    from src.api.integrations.igdb_client import get_game_artwork_by_ids

    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT id,igdb_id FROM games WHERE igdb_id IS NOT NULL ORDER BY id")
        games = list(cursor.fetchall())
    images = await get_game_artwork_by_ids([int(game["igdb_id"]) for game in games])
    updated = missing = 0
    with get_conn() as conn, conn.cursor() as cursor:
        for game in games:
            urls = images.get(int(game["igdb_id"]), [])
            if not urls:
                missing += 1
            fields = {"igdb_artwork_urls": urls, "igdb_artwork_provenance": {
                "provider": "igdb", "external_id": str(game["igdb_id"]),
                "retrieved_at": datetime.now(timezone.utc).isoformat()}}
            cursor.execute("""UPDATE games SET specifications=COALESCE(specifications,'{}'::jsonb) || %s::jsonb
                WHERE id=%s AND igdb_id=%s RETURNING id""",
                (json.dumps(fields), game["id"], game["igdb_id"]))
            if cursor.fetchone() is None:
                raise ValueError(f"Game {game['id']}: confirmed IGDB identity changed during artwork refresh")
            updated += 1
    return updated, missing


def fetch_missing_psn_details(limit: int | None = None) -> tuple[int, int]:
    from src.api.db import get_conn
    from src.api.integrations import psn_client
    from src.api.routes.trophies import _fetch_and_cache_psn

    if not psn_client.is_configured():
        raise RuntimeError("PSN_NPSSO is not configured in config/.env")
    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute("""SELECT g.id,g.psn_id,g.platform FROM games g
            JOIN provider_mappings pm ON pm.game_id=g.id AND pm.provider='psn'
                AND pm.external_id=g.psn_id AND pm.match_state='confirmed'
            WHERE g.trophies_cached_at IS NULL AND NOT EXISTS
                (SELECT 1 FROM trophies t WHERE t.game_id=g.id)
            ORDER BY g.id""")
        games = list(cursor.fetchall())
    if limit is not None:
        games = games[:limit]
    done = failed = 0
    for game in games:
        try:
            _fetch_and_cache_psn(game["id"], game["psn_id"], game["platform"])
            done += 1
        except Exception:
            failed += 1
            print(f"PSN details unavailable for game ID {game['id']}; no partial set accepted")
    return done, failed


async def refresh_missing_estimates() -> dict:
    from src.api.db import get_conn
    from src.api.routes.enrich import _run_enrichment
    from src.api.utils import integration_jobs

    with get_conn() as conn, conn.cursor() as cursor:
        cursor.execute("""SELECT id,title,specifications FROM games
            WHERE hltb_completionist_hours IS NULL ORDER BY title""")
        games = list(cursor.fetchall())
    state = dict(running=True, total=len(games), done=0, skipped=0, failed=0,
                 current=None, outcomes=[], phase="enriching")
    job_id = integration_jobs.start("hltb", state)
    await _run_enrichment(games, job_id, state)
    return state


def hltb_review_template(payload: dict) -> dict:
    from src.api.utils import integration_jobs

    games = {game["id"]: game for game in payload["games"]}
    latest = integration_jobs.latest("hltb")
    entries = []
    for outcome in latest.get("outcomes", []):
        if outcome["outcome"] != "needs_review" or outcome["game_id"] not in games:
            continue
        game = games[outcome["game_id"]]
        entries.append({"game_id": game["id"], "title": game["title"],
                        "platform": game["platform"], "search_titles": search_titles(game),
                        "candidates": outcome["candidates"],
                        "match_confidence": outcome.get("match_confidence"),
                        "selected_source_id": None})
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "games": entries}


async def apply_hltb_reviews(path: Path) -> tuple[int, int]:
    from howlongtobeatpy import HowLongToBeat
    from src.api.db import get_conn
    from src.api.integrations.hltb_client import _hours

    source = json.loads(path.read_text(encoding="utf-8"))
    done = skipped = 0
    provider = HowLongToBeat()
    for entry in source["games"]:
        selected = entry.get("selected_source_id")
        if selected is None:
            skipped += 1
            continue
        selected = str(selected)
        reviewed = {str(row["id"]): row["title"] for row in entry["candidates"]}
        if selected not in reviewed:
            raise ValueError(f"Game {entry['game_id']}: selected HLTB ID was not a review candidate")
        matching = {}
        for title in entry["search_titles"]:
            results = await provider.async_search(title)
            if results is None:
                raise RuntimeError("Estimate provider request failed")
            for result in results:
                if str(result.game_id) == selected and normalized_title(result.game_name) == normalized_title(reviewed[selected]):
                    matching[selected] = result
            await asyncio.sleep(0.5)
        if selected not in matching:
            raise ValueError(f"Game {entry['game_id']}: reviewed HLTB candidate is no longer available")
        result = matching[selected]
        hours = {"main": _hours(result.main_story), "main_extra": _hours(result.main_extra),
                 "completionist": _hours(result.completionist)}
        if not any(value is not None for value in hours.values()):
            raise ValueError(f"Game {entry['game_id']}: reviewed HLTB candidate has no estimates")
        with get_conn() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT title,platform FROM games WHERE id=%s FOR UPDATE", (entry["game_id"],))
            current = cursor.fetchone()
            if not current or current["title"] != entry["title"] or current["platform"] != entry["platform"]:
                raise ValueError(f"Game {entry['game_id']}: title/platform changed since review")
            cursor.execute("""UPDATE games SET hltb_main_hours=COALESCE(%s,hltb_main_hours),
                hltb_extra_hours=COALESCE(%s,hltb_extra_hours),
                hltb_completionist_hours=COALESCE(%s,hltb_completionist_hours) WHERE id=%s""",
                (hours["main"], hours["main_extra"], hours["completionist"], entry["game_id"]))
            for category, value in (("story", hours["main"]), ("main_extra", hours["main_extra"]),
                                    ("completionist", hours["completionist"])):
                if value is not None:
                    cursor.execute("""INSERT INTO game_time_estimates
                        (game_id,category,hours,provider,source_ref,retrieved_at,match_confidence)
                        VALUES(%s,%s,%s,'hltb',%s,NOW(),'reviewed_alias')
                        ON CONFLICT(game_id,category,provider) DO UPDATE SET
                        hours=EXCLUDED.hours,source_ref=EXCLUDED.source_ref,
                        retrieved_at=EXCLUDED.retrieved_at,match_confidence=EXCLUDED.match_confidence""",
                        (entry["game_id"], category, value, selected))
        done += 1
    return done, skipped


def guide_review_template(rows: list[dict]) -> dict:
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "games": [
        {"game_id": row["game_id"], "title": row["title"], "platform": row["platform"],
         "selected_guide_url": None}
        for row in rows if row["status"]["guide_reference"] == "missing"
    ]}


def valid_guide_url(url: str) -> bool:
    parsed = urlparse(url)
    try:
        return (parsed.scheme == "https" and not parsed.username and not parsed.password
                and parsed.port is None and not parsed.query and not parsed.fragment
                and ((parsed.hostname == "psnprofiles.com" and len(parsed.path) > len("/guide/")
                      and parsed.path.startswith("/guide/"))
                     or (parsed.hostname == "www.playstationtrophies.org" and parsed.path.startswith("/game/")
                         and "/guide/" in parsed.path)))
    except ValueError:
        return False


def apply_guide_reviews(path: Path) -> tuple[int, int]:
    from src.api.db import get_conn

    source = json.loads(path.read_text(encoding="utf-8"))
    applied = skipped = 0
    for entry in source["games"]:
        url = entry.get("selected_guide_url")
        if url is None:
            skipped += 1
            continue
        if not isinstance(url, str) or not valid_guide_url(url):
            raise ValueError(f"Game {entry['game_id']}: guide URL must be a supported HTTPS guide page")
        with get_conn() as conn, conn.cursor() as cursor:
            cursor.execute("""UPDATE games SET specifications=jsonb_set(
                COALESCE(specifications,'{}'::jsonb),'{trophy_guide_url}',to_jsonb(%s::text),true)
                WHERE id=%s AND title=%s AND platform=%s RETURNING id""",
                (url, entry["game_id"], entry["title"], entry["platform"]))
            if cursor.fetchone() is None:
                raise ValueError(f"Game {entry['game_id']}: title/platform changed since review")
        applied += 1
    return applied, skipped


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / "config" / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search-igdb", action="store_true", help="Query IGDB and save private candidates; never apply")
    parser.add_argument("--apply-igdb-review", action="store_true", help="Apply only IDs explicitly selected in .local/igdb-review.json")
    parser.add_argument("--reconcile-igdb-review", action="store_true", help="Recalculate exact flags from all searched titles without provider calls")
    parser.add_argument("--select-unique-igdb", action="store_true", help="Select unique exact same-platform candidates in the existing review file")
    parser.add_argument("--select-reviewed-igdb-ids", type=str, help="Record confirmed game_id:igdb_id pairs in the private review file")
    parser.add_argument("--curate-display-titles", action="store_true", help="Save readable labels for confirmed releases without changing PSN titles")
    parser.add_argument("--refresh-igdb-scores", action="store_true", help="Cache IGDB user ratings for confirmed game IDs")
    parser.add_argument("--refresh-igdb-artwork", action="store_true", help="Cache landscape image choices for confirmed IGDB IDs")
    parser.add_argument("--expand-igdb-review", action="store_true", help="Search more broadly for unresolved IGDB review entries")
    parser.add_argument("--fetch-psn-details", action="store_true", help="Fetch missing details for confirmed PSN mappings into authoring DB")
    parser.add_argument("--refresh-hltb", action="store_true", help="Search missing estimates; exact matches apply, aliases require review")
    parser.add_argument("--make-hltb-review", action="store_true", help="Create private review template from latest estimate lookup")
    parser.add_argument("--apply-hltb-review", action="store_true", help="Apply explicitly selected estimate candidates")
    parser.add_argument("--make-guide-review", action="store_true", help="Create private guide-link review template")
    parser.add_argument("--apply-guide-review", action="store_true", help="Apply explicitly selected external guide links")
    parser.add_argument("--psn-limit", type=int, default=None, help="Maximum PSN games this run")
    args = parser.parse_args()
    payload = load_static_snapshot(SNAPSHOT).payload
    report = inventory(payload)
    _write_private(REPORT, report)
    print(f"Coverage: {report['total_games']} games; report: {REPORT}")
    print("Confirmed fields: " + ", ".join(f"{key} {count}/{report['total_games']}"
                                         for key, count in report["field_coverage"].items()))
    if args.search_igdb:
        review = asyncio.run(igdb_candidates(report["games"]))
        _write_review(IGDB_REVIEW, review)
        print(f"IGDB candidates for {len(review['games'])} games: {IGDB_REVIEW}")
    if args.reconcile_igdb_review or args.select_unique_igdb:
        selected, unresolved = reconcile_igdb_review(IGDB_REVIEW, select_unique=args.select_unique_igdb)
        print(f"IGDB review reconciled: {selected} selected, {unresolved} ambiguous or without exact match")
    if args.select_reviewed_igdb_ids:
        selected = select_reviewed_igdb_ids(IGDB_REVIEW, args.select_reviewed_igdb_ids)
        print(f"Recorded {selected} explicitly reviewed IGDB selections")
    if args.expand_igdb_review:
        added = asyncio.run(expand_igdb_review(IGDB_REVIEW))
        print(f"Expanded IGDB review with {added} additional same-platform candidates")
    if args.make_guide_review:
        review = guide_review_template(report["games"])
        _write_review(GUIDE_REVIEW, review)
        print(f"Guide-link review template for {len(review['games'])} games: {GUIDE_REVIEW}")
    if args.apply_igdb_review:
        print(f"Private database backup: {backup_authoring_database()}")
        done, skipped = asyncio.run(apply_igdb_reviews(IGDB_REVIEW))
        print(f"Applied {done} reviewed IGDB mappings; {skipped} unchanged or unselected")
    if args.curate_display_titles:
        print(f"Private database backup: {backup_authoring_database()}")
        updated = curate_display_titles(IGDB_REVIEW)
        print(f"Saved readable display titles for {updated} confirmed releases")
    if args.refresh_igdb_scores:
        print(f"Private database backup: {backup_authoring_database()}")
        updated, missing = asyncio.run(refresh_igdb_scores())
        print(f"IGDB user scores checked for {updated} games; {missing} confirmed IDs not returned")
    if args.refresh_igdb_artwork:
        print(f"Private database backup: {backup_authoring_database()}")
        updated, missing = asyncio.run(refresh_igdb_artwork())
        print(f"IGDB artwork checked for {updated} games; {missing} without landscape images")
    if args.fetch_psn_details:
        if args.psn_limit is not None and args.psn_limit < 1:
            parser.error("--psn-limit must be positive")
        print(f"Private database backup: {backup_authoring_database()}")
        done, failed = fetch_missing_psn_details(args.psn_limit)
        print(f"PSN detail fetch: {done} updated, {failed} failed")
    if args.apply_guide_review:
        print(f"Private database backup: {backup_authoring_database()}")
        done, skipped = apply_guide_reviews(GUIDE_REVIEW)
        print(f"Applied {done} reviewed guide links; {skipped} left unselected")
    if args.refresh_hltb:
        print(f"Private database backup: {backup_authoring_database()}")
        state = asyncio.run(refresh_missing_estimates())
        print(f"HLTB: {state['done']} updated, {state['skipped']} unresolved, {state['failed']} failed")
    if args.make_hltb_review:
        review = hltb_review_template(payload)
        _write_review(HLTB_REVIEW, review)
        print(f"HLTB review template for {len(review['games'])} games: {HLTB_REVIEW}")
    if args.apply_hltb_review:
        print(f"Private database backup: {backup_authoring_database()}")
        done, skipped = asyncio.run(apply_hltb_reviews(HLTB_REVIEW))
        print(f"Applied {done} reviewed estimates; {skipped} left unselected")


if __name__ == "__main__":
    main()
