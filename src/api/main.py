import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from psycopg2 import IntegrityError, OperationalError

load_dotenv(Path(__file__).resolve().parents[2] / "config" / ".env")

from src.api.routes import games, trophies, backlog, wishlist, statistics, sync, enrich

app = FastAPI(title="Game Vault API", version="0.2.0")


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request, exc):
    return JSONResponse(
        status_code=409,
        content={"detail": "This change conflicts with an existing record. Refresh and try again."},
    )


@app.exception_handler(OperationalError)
async def database_unavailable_handler(request, exc):
    return JSONResponse(
        status_code=503,
        content={"detail": "The local database is unavailable. Please try again shortly."},
    )

default_origins = "http://localhost:4200,http://127.0.0.1:4200"
allowed_origins = [
    origin.strip().rstrip("/")
    for origin in os.environ.get("ALLOWED_ORIGINS", default_origins).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(games.router)
app.include_router(trophies.router)
app.include_router(backlog.router)
app.include_router(wishlist.router)
app.include_router(statistics.router)
app.include_router(sync.router)
app.include_router(enrich.router)


@app.get("/health")
def health():
    return {"status": "ok"}
