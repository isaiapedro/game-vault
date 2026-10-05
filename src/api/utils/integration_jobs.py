"""Durable job outcomes. The advisory lock allows one job per provider."""
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from src.api.db import get_conn


def latest(provider):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, state, updated_at FROM integration_jobs WHERE provider=%s ORDER BY id DESC LIMIT 1", (provider,))
        row = cur.fetchone()
    if not row:
        return {"running": False}
    state = dict(row["state"])
    # A killed worker must not leave the UI stuck forever. No automatic retry.
    if state.get("running") and (datetime.now(timezone.utc) - row["updated_at"]).total_seconds() > 900:
        state.update(running=False, phase="interrupted", error="Job interrupted; retry to continue.")
        save(row["id"], state)
    return {**state, "job_id": row["id"]}


def start(provider, state):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("game-vault:" + provider,))
        cur.execute("SELECT state, updated_at FROM integration_jobs WHERE provider=%s ORDER BY id DESC LIMIT 1", (provider,))
        previous = cur.fetchone()
        if previous and previous["state"].get("running") and (datetime.now(timezone.utc) - previous["updated_at"]).total_seconds() < 900:
            raise HTTPException(status_code=409, detail="A job is already running.")
        cur.execute("INSERT INTO integration_jobs(provider,state) VALUES(%s,%s::jsonb) RETURNING id", (provider, json.dumps(state)))
        return cur.fetchone()["id"]


def save(job_id, state):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE integration_jobs SET state=%s::jsonb, updated_at=NOW() WHERE id=%s", (json.dumps(state), job_id))
