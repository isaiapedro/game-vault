"""Export the reviewed local collection into one immutable runtime artifact.

Run this only during release preparation while the PostgreSQL-backed authoring
service is available. The resulting file and cover assets are private `.local`
artifacts and must not be committed or published.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import mimetypes
from pathlib import Path
import re
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi.encoders import jsonable_encoder

from src.api.db import get_conn
from src.api.routes.backlog import get_backlog
from src.api.routes.games import get_game, list_games
from src.api.routes.statistics import get_statistics
from src.api.routes.trophies import _read_trophies
from src.api.routes.wishlist import get_wishlist
from src.api.static_snapshot import SNAPSHOT_VERSION, content_sha256, validate_static_snapshot
from src.api.price_offers import DEFAULT_OFFER_PATH, project_price_offers


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / ".local" / "game-vault-snapshot.json"
DEFAULT_COVERS = PROJECT_ROOT / ".local" / "static" / "covers"
DEFAULT_ARTWORK = PROJECT_ROOT / ".local" / "static" / "artwork"
IGDB_IMAGE = re.compile(r"https://images\.igdb\.com/igdb/image/upload/t_screenshot_big/[A-Za-z0-9]+\.jpg$")


def extension_for(content_type: str | None, url: str) -> str:
    extension = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    if extension in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if extension == ".jpe" else extension
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else ".jpg"


def cache_cover(game: dict, covers_dir: Path) -> str | None:
    url = game.get("cover_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        return cached_cover(game, covers_dir)
    provenance = (game.get("specifications") or {}).get("cover_provenance") or {}
    confirmed_igdb = (provenance.get("provider") == "igdb" and
                      urlparse(url).hostname == "images.igdb.com")
    preferred = sorted(covers_dir.glob(f"igdb-{game['id']}.*"))
    if preferred:
        return f"/covers/{preferred[0].name}"
    if not confirmed_igdb:
        existing = cached_cover(game, covers_dir)
        if existing:
            return existing
    request = Request(url, headers={"User-Agent": "GameVault/1.0 local snapshot preparation"})
    try:
        with urlopen(request, timeout=20) as response:
            content_type = response.headers.get("Content-Type")
            if not (content_type or "").lower().startswith("image/"):
                return None
            body = response.read(5 * 1024 * 1024 + 1)
        if len(body) > 5 * 1024 * 1024:
            return None
        extension = extension_for(content_type, url)
        target = covers_dir / f"{'igdb-' if confirmed_igdb else ''}{game['id']}{extension}"
        target.write_bytes(body)
        return f"/covers/{target.name}"
    except (OSError, ValueError):
        return cached_cover(game, covers_dir)


def cached_cover(game: dict, covers_dir: Path) -> str | None:
    preferred = sorted(covers_dir.glob(f"igdb-{game['id']}.*"))
    if preferred:
        return f"/covers/{preferred[0].name}"
    existing = sorted(covers_dir.glob(f"{game['id']}.*"))
    return f"/covers/{existing[0].name}" if existing else None


def cache_artwork(game: dict, artwork_dir: Path, download: bool) -> list[str]:
    urls = (game.get("specifications") or {}).get("igdb_artwork_urls") or []
    if not isinstance(urls, list):
        return []
    local = []
    for index, url in enumerate(urls[:2], start=1):
        if not isinstance(url, str) or not IGDB_IMAGE.fullmatch(url):
            continue
        target = artwork_dir / f"{game['id']}-{index}.jpg"
        if not target.is_file() and download:
            request = Request(url, headers={"User-Agent": "GameVault/1.0 local snapshot preparation"})
            try:
                with urlopen(request, timeout=20) as response:
                    if not (response.headers.get("Content-Type") or "").lower().startswith("image/"):
                        continue
                    body = response.read(5 * 1024 * 1024 + 1)
                if len(body) > 5 * 1024 * 1024:
                    continue
                target.write_bytes(body)
            except (OSError, ValueError):
                continue
        if target.is_file():
            local.append(f"/artwork/{target.name}")
    return local


def replace_cover_urls(value, covers_by_game: dict[int, str | None]):
    """Keep every API projection same-origin, not only the primary game list."""

    if isinstance(value, list):
        for item in value:
            replace_cover_urls(item, covers_by_game)
    elif isinstance(value, dict):
        if "cover_url" in value:
            game_id = value.get("game_id", value.get("id"))
            value["cover_url"] = covers_by_game.get(game_id)
        for item in value.values():
            replace_cover_urls(item, covers_by_game)


def replace_artwork_urls(value, artwork_by_game: dict[int, list[str]]):
    if isinstance(value, list):
        for item in value:
            replace_artwork_urls(item, artwork_by_game)
    elif isinstance(value, dict):
        specs = value.get("specifications")
        if isinstance(specs, dict) and "igdb_artwork_urls" in specs:
            game_id = value.get("game_id", value.get("id"))
            specs["igdb_artwork_urls"] = artwork_by_game.get(game_id, [])
        for item in value.values():
            replace_artwork_urls(item, artwork_by_game)


def export_snapshot(output: Path, covers_dir: Path, download_covers: bool,
                    artwork_dir: Path = DEFAULT_ARTWORK, download_artwork: bool = False,
                    offers_path: Path = DEFAULT_OFFER_PATH) -> dict:
    games = [dict(game) for game in jsonable_encoder(list_games())]
    detailed = {int(game["id"]): dict(jsonable_encoder(get_game(int(game["id"])))) for game in games}
    trophies: dict[str, list[dict]] = {}
    with get_conn() as conn, conn.cursor() as cursor:
        for game_id in detailed:
            trophies[str(game_id)] = list(jsonable_encoder(_read_trophies(cursor, game_id)))
        cursor.execute("SELECT MAX(observed_at) AS observed_at FROM psn_title_summaries")
        psn_observed_at = jsonable_encoder(cursor.fetchone()["observed_at"])

    covers_dir.mkdir(parents=True, exist_ok=True)
    artwork_dir.mkdir(parents=True, exist_ok=True)
    artwork_by_game = {}
    if download_covers:
        with ThreadPoolExecutor(max_workers=6) as workers:
            results = workers.map(lambda game: cache_cover(game, covers_dir), detailed.values())
            for game, local in zip(detailed.values(), results):
                game["cover_url"] = local
    else:
        for game in detailed.values():
            game["cover_url"] = cached_cover(game, covers_dir)
    if download_artwork:
        with ThreadPoolExecutor(max_workers=6) as workers:
            results = workers.map(lambda game: cache_artwork(game, artwork_dir, True), detailed.values())
            artwork_by_game = {game["id"]: local for game, local in zip(detailed.values(), results)}
    else:
        artwork_by_game = {game["id"]: cache_artwork(game, artwork_dir, False)
                           for game in detailed.values()}

    wishlist = jsonable_encoder(get_wishlist())
    offers_by_game = project_price_offers(offers_path, wishlist)
    for game in wishlist:
        game["price_offers"] = offers_by_game[int(game["id"])]

    payload = {
        "snapshot_version": SNAPSHOT_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "psn_observed_at": psn_observed_at,
        "games": sorted(detailed.values(), key=lambda game: (game["title"].casefold(), game["id"])),
        "backlog": jsonable_encoder(get_backlog()),
        "wishlist": wishlist,
        "statistics": jsonable_encoder(get_statistics()),
        "trophies": trophies,
    }
    covers_by_game = {game_id: game.get("cover_url") for game_id, game in detailed.items()}
    replace_cover_urls(payload, covers_by_game)
    replace_artwork_urls(payload, artwork_by_game)
    payload["content_sha256"] = content_sha256(payload)
    validate_static_snapshot(payload)

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.", delete=False
    ) as temporary:
        json.dump(payload, temporary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(output)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--covers-dir", type=Path, default=DEFAULT_COVERS)
    parser.add_argument("--artwork-dir", type=Path, default=DEFAULT_ARTWORK)
    parser.add_argument("--offers-file", type=Path, default=DEFAULT_OFFER_PATH,
                        help="Private reviewed price observations under .local/.")
    parser.add_argument(
        "--download-covers",
        action="store_true",
        help="Cache current HTTPS cover URLs locally; failed downloads use the built-in fallback.",
    )
    parser.add_argument("--download-artwork", action="store_true",
                        help="Cache confirmed IGDB landscape images locally for this release.")
    arguments = parser.parse_args()
    payload = export_snapshot(arguments.output, arguments.covers_dir, arguments.download_covers,
                              arguments.artwork_dir, arguments.download_artwork, arguments.offers_file)
    print(
        f"Exported {len(payload['games'])} games and "
        f"{sum(len(rows) for rows in payload['trophies'].values())} trophies "
        f"to {arguments.output}"
    )


if __name__ == "__main__":
    main()
