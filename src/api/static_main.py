"""One-process, read-only Game Vault release application."""

from __future__ import annotations

import os
from pathlib import Path
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.static_snapshot import StaticSnapshot, StaticSnapshotError, load_static_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PROJECT_ROOT / "src" / "frontend" / "dist" / "frontend" / "browser"
SNAPSHOT_PATH = Path(
    os.environ.get("GAME_VAULT_SNAPSHOT", PROJECT_ROOT / ".local" / "game-vault-snapshot.json")
)
COVERS_ROOT = Path(
    os.environ.get("GAME_VAULT_COVERS", PROJECT_ROOT / ".local" / "static" / "covers")
)
ARTWORK_ROOT = Path(
    os.environ.get("GAME_VAULT_ARTWORK", PROJECT_ROOT / ".local" / "static" / "artwork")
)

app = FastAPI(
    title="Game Vault static API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

try:
    app.state.snapshot = load_static_snapshot(SNAPSHOT_PATH)
    app.state.snapshot_error = None
except StaticSnapshotError as error:
    app.state.snapshot = None
    app.state.snapshot_error = str(error)

if COVERS_ROOT.is_dir():
    app.mount("/covers", StaticFiles(directory=COVERS_ROOT), name="covers")
if ARTWORK_ROOT.is_dir():
    app.mount("/artwork", StaticFiles(directory=ARTWORK_ROOT), name="artwork")
if FRONTEND_ROOT.is_dir():
    for asset_dir in ("medals",):
        path = FRONTEND_ROOT / asset_dir
        if path.is_dir():
            app.mount(f"/{asset_dir}", StaticFiles(directory=path), name=asset_dir)


@app.middleware("http")
async def local_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    return response


def snapshot(request: Request) -> StaticSnapshot:
    value = request.app.state.snapshot
    if value is None:
        raise HTTPException(status_code=503, detail=request.app.state.snapshot_error)
    return value


def slug_from_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9\s-]", "", title.lower())
    return re.sub(r"-+", "-", re.sub(r"\s+", "-", slug.strip())).strip("-")


@app.get("/health", tags=["operations"])
def health(request: Request):
    current = snapshot(request)
    return {"status": "ok", "mode": "static", "captured_at": current.captured_at}


@app.get("/api/games")
def games(request: Request):
    return list(snapshot(request).games)


@app.get("/api/games/{game_id}")
def game(game_id: int, request: Request):
    result = snapshot(request).games_by_id.get(game_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Game not in snapshot")
    return result


@app.get("/api/backlog")
def backlog(request: Request):
    return snapshot(request).payload["backlog"]


@app.get("/api/wishlist")
def wishlist(request: Request):
    return snapshot(request).payload["wishlist"]


@app.get("/api/statistics")
def statistics(request: Request):
    return snapshot(request).payload["statistics"]


@app.get("/api/trophies/{game_id}")
def trophies(game_id: int, request: Request):
    current = snapshot(request)
    if game_id not in current.games_by_id:
        raise HTTPException(status_code=404, detail="Game not in snapshot")
    return current.payload["trophies"].get(str(game_id), [])


@app.get("/api/trophies/{game_id}/guide")
def trophy_guide(game_id: int, request: Request):
    selected = snapshot(request).games_by_id.get(game_id)
    if selected is None:
        raise HTTPException(status_code=404, detail="Game not in snapshot")
    guide_url = (selected.get("specifications") or {}).get("trophy_guide_url")
    slug = selected.get("psnprofiles_slug")
    return {
        "guide": None,
        "slug": slug,
        "guide_url": guide_url,
        "psnprofiles_url": f"https://psnprofiles.com/guide/{slug}" if slug else None,
        "trophy_list_url": f"https://psnprofiles.com/trophies/{slug}" if slug else None,
        "note": "Reviewed external links only; the Game Vault snapshot itself remains offline.",
    }


@app.get("/api/sync/status")
def sync_status(request: Request):
    current = snapshot(request)
    return {
        "running": False,
        "phase": "static_snapshot",
        "psn_configured": False,
        "last_sync": current.payload.get("psn_observed_at"),
        "captured_at": current.captured_at,
        "message": "PSN data is fixed in this release snapshot.",
    }


@app.get("/api/enrich/igdb/status")
def metadata_status():
    return {"configured": False, "mode": "static_snapshot"}


@app.get("/api/enrich/hltb/status")
def estimate_status(request: Request):
    return {
        "running": False,
        "phase": "static_snapshot",
        "captured_at": snapshot(request).captured_at,
    }


@app.api_route(
    "/api/{path:path}",
    methods=["POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
def immutable_runtime(path: str):
    return JSONResponse(
        status_code=405,
        content={"detail": "This release uses a fixed, read-only Game Vault snapshot."},
    )


def application_shell() -> FileResponse:
    index = FRONTEND_ROOT / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=503, detail="frontend_not_built")
    return FileResponse(index)


@app.get("/", include_in_schema=False)
def home():
    return application_shell()


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    candidate = (FRONTEND_ROOT / path).resolve()
    try:
        candidate.relative_to(FRONTEND_ROOT.resolve())
    except ValueError as error:
        raise HTTPException(status_code=404, detail="page_not_found") from error
    if candidate.is_file():
        return FileResponse(candidate)
    return application_shell()
