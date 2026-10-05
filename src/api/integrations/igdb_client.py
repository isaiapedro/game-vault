import asyncio
import os
import json
import time
import httpx
from typing import Optional

_token_cache: dict = {}


async def _get_access_token() -> str:
    if _token_cache.get("token") and _token_cache.get("expires_at", 0) > time.monotonic():
        return _token_cache["token"]

    client_id = os.environ["TWITCH_CLIENT_ID"]
    client_secret = os.environ["TWITCH_CLIENT_SECRET"]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        _token_cache["token"] = data["access_token"]
        _token_cache["expires_at"] = time.monotonic() + max(0, data.get("expires_in", 3600) - 60)
        return _token_cache["token"]


async def search_games(query: str, limit: int = 10) -> list[dict]:
    token = await _get_access_token()
    client_id = os.environ["TWITCH_CLIENT_ID"]

    body = f"""
        fields id, name, cover.url, summary, first_release_date,
               genres.name, involved_companies.company.name,
               involved_companies.developer, involved_companies.publisher,
               platforms.name, game_engines.name, alternative_names.name,
               version_parent, category;
        search {json.dumps(query)};
        limit {max(1, min(50, int(limit)))};
    """

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.igdb.com/v4/games",
            headers={
                "Client-ID": client_id,
                "Authorization": f"Bearer {token}",
            },
            content=body,
        )
        resp.raise_for_status()
        results = _normalize_results(resp.json())
        # IGDB's name search covers games, not the alternative_names endpoint.
        # Query exact alternative names separately so an old/local title can
        # still surface its current release as a review candidate.
        await asyncio.sleep(0.3)
        alternate = await client.post(
            "https://api.igdb.com/v4/alternative_names",
            headers={"Client-ID": client_id, "Authorization": f"Bearer {token}"},
            content=f"fields game,name; where name = {json.dumps(query)}; limit {max(1, min(50, int(limit)))};",
        )
        alternate.raise_for_status()
        known = {item["igdb_id"] for item in results}
        ids = sorted({int(item["game"]) for item in alternate.json() if item.get("game") and int(item["game"]) not in known})
        if ids:
            await asyncio.sleep(0.3)
            extra = await client.post(
                "https://api.igdb.com/v4/games",
                headers={"Client-ID": client_id, "Authorization": f"Bearer {token}"},
                content=f"""fields id,name,cover.url,summary,first_release_date,
                    genres.name,involved_companies.company.name,involved_companies.developer,
                    involved_companies.publisher,platforms.name,game_engines.name,
                    alternative_names.name,version_parent,category;
                    where id = ({','.join(str(value) for value in ids)}); limit {len(ids)};""",
            )
            extra.raise_for_status()
            results.extend(_normalize_results(extra.json()))
        return results


async def get_game_by_id(igdb_id: int) -> Optional[dict]:
    if not isinstance(igdb_id, int) or igdb_id <= 0:
        raise ValueError("IGDB ID must be a positive integer")
    token = await _get_access_token()
    client_id = os.environ["TWITCH_CLIENT_ID"]

    body = f"""
        fields id, name, cover.url, summary, first_release_date,
               genres.name, involved_companies.company.name,
               involved_companies.developer, involved_companies.publisher,
               platforms.name, game_engines.name, game_modes.name,
               player_perspectives.name, themes.name, storyline,
               alternative_names.name, version_parent, category,
               rating, rating_count;
        where id = {igdb_id};
        limit 1;
    """

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.igdb.com/v4/games",
            headers={
                "Client-ID": client_id,
                "Authorization": f"Bearer {token}",
            },
            content=body,
        )
        resp.raise_for_status()
        results = _normalize_results(resp.json())
        return results[0] if results else None


def _normalize_results(raw: list) -> list[dict]:
    out = []
    for g in raw:
        cover = g.get("cover", {})
        cover_url = cover.get("url", "").replace("t_thumb", "t_cover_big") if cover else None
        if cover_url and cover_url.startswith("//"):
            cover_url = "https:" + cover_url

        companies = g.get("involved_companies", [])
        developer = next(
            (c["company"]["name"] for c in companies if c.get("developer")), None
        )
        publisher = next(
            (c["company"]["name"] for c in companies if c.get("publisher")), None
        )

        import datetime
        release_date = None
        if g.get("first_release_date"):
            release_date = datetime.date.fromtimestamp(g["first_release_date"]).isoformat()

        out.append({
            "igdb_id": g["id"],
            "title": g["name"],
            "cover_url": cover_url,
            "description": g.get("summary") or g.get("storyline"),
            "developer": developer,
            "publisher": publisher,
            "release_date": release_date,
            "genres": [genre["name"] for genre in g.get("genres", [])],
            "specifications": {
                "igdb_user_rating": g.get("rating"),
                "igdb_user_rating_count": g.get("rating_count"),
                "platforms": [p["name"] for p in g.get("platforms", [])],
                "engines": [e["name"] for e in g.get("game_engines", [])],
                "modes": [m["name"] for m in g.get("game_modes", [])],
                "themes": [t["name"] for t in g.get("themes", [])],
                "alternative_names": [name["name"] for name in g.get("alternative_names", []) if name.get("name")],
                "version_parent": g.get("version_parent"),
                "category": g.get("category"),
            },
        })
    return out


async def get_game_scores_by_ids(igdb_ids: list[int]) -> dict[int, dict]:
    """Read only IGDB user scores for already-confirmed releases."""
    ids = sorted(set(igdb_ids))
    if any(not isinstance(value, int) or value <= 0 for value in ids):
        raise ValueError("IGDB IDs must be positive integers")
    if not ids:
        return {}
    token = await _get_access_token()
    client_id = os.environ["TWITCH_CLIENT_ID"]
    scores = {}
    async with httpx.AsyncClient() as client:
        for offset in range(0, len(ids), 50):
            batch = ids[offset:offset + 50]
            resp = await client.post(
                "https://api.igdb.com/v4/games",
                headers={"Client-ID": client_id, "Authorization": f"Bearer {token}"},
                content=f"fields id,rating,rating_count; where id = ({','.join(map(str, batch))}); limit {len(batch)};",
            )
            resp.raise_for_status()
            for game in resp.json():
                scores[int(game["id"])] = {
                    "igdb_user_rating": game.get("rating"),
                    "igdb_user_rating_count": game.get("rating_count"),
                }
            if offset + 50 < len(ids):
                await asyncio.sleep(0.3)
    return scores


async def get_game_artwork_by_ids(igdb_ids: list[int]) -> dict[int, list[str]]:
    """Return at most two landscape image URLs per confirmed IGDB release."""
    ids = sorted(set(igdb_ids))
    if any(not isinstance(value, int) or value <= 0 for value in ids):
        raise ValueError("IGDB IDs must be positive integers")
    if not ids:
        return {}
    token = await _get_access_token()
    client_id = os.environ["TWITCH_CLIENT_ID"]
    images = {}
    async with httpx.AsyncClient() as client:
        for offset in range(0, len(ids), 50):
            batch = ids[offset:offset + 50]
            response = await client.post(
                "https://api.igdb.com/v4/games",
                headers={"Client-ID": client_id, "Authorization": f"Bearer {token}"},
                content=("fields id,screenshots.image_id,screenshots.width,screenshots.height,"
                         "artworks.image_id,artworks.width,artworks.height; "
                         f"where id = ({','.join(map(str, batch))}); limit {len(batch)};"),
            )
            response.raise_for_status()
            for game in response.json():
                selected = []
                for item in [*game.get("screenshots", []), *game.get("artworks", [])]:
                    image_id = item.get("image_id")
                    width, height = item.get("width") or 0, item.get("height") or 0
                    if not isinstance(image_id, str) or not image_id.isalnum() or width <= height:
                        continue
                    url = f"https://images.igdb.com/igdb/image/upload/t_screenshot_big/{image_id}.jpg"
                    if url not in selected:
                        selected.append(url)
                    if len(selected) == 2:
                        break
                images[int(game["id"])] = selected
            if offset + 50 < len(ids):
                await asyncio.sleep(0.3)
    return images


def supports_platform(metadata: dict, platform: str) -> bool:
    aliases = {"PS3": "PlayStation 3", "PS4": "PlayStation 4", "PS5": "PlayStation 5",
               "PSVITA": "PlayStation Vita", "PS VITA": "PlayStation Vita"}
    expected = aliases.get(platform.upper(), platform).casefold()
    return expected in [name.casefold() for name in metadata.get("specifications", {}).get("platforms", [])]
