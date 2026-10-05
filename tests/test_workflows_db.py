"""Real PostgreSQL workflow checks in a disposable, isolated schema.

Run explicitly with GAME_VAULT_DB_TESTS=1 venv/bin/python -m unittest
tests.test_workflows_db -v. The configured collection schema is never mutated.
"""
import os
from pathlib import Path
import unittest
from uuid import uuid4


@unittest.skipUnless(os.environ.get("GAME_VAULT_DB_TESTS") == "1", "explicit isolated DB test opt-in required")
class DatabaseWorkflows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        from psycopg2 import sql
        from psycopg2.extensions import make_dsn
        from dotenv import load_dotenv
        from fastapi.testclient import TestClient

        cls.root = Path(__file__).resolve().parents[1]
        load_dotenv(cls.root / "config" / ".env")
        cls.original_dsn = os.environ["DATABASE_URL"]
        cls.schema = "gv_test_" + uuid4().hex
        cls.admin = psycopg2.connect(cls.original_dsn)
        cls.admin.autocommit = True
        with cls.admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        cls.dsn = make_dsn(cls.original_dsn, options=f"-c search_path={cls.schema}")
        os.environ["DATABASE_URL"] = cls.dsn
        try:
            with psycopg2.connect(cls.dsn) as conn:
                with conn.cursor() as cur:
                    for migration in sorted((cls.root / "migrations").glob("*.sql")):
                        cur.execute(migration.read_text())
            from src.api import db
            if db._pool is not None:
                db._pool.closeall()
                db._pool = None
            from src.api.main import app
            cls.client = TestClient(app)
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        from psycopg2 import sql
        from src.api import db
        if getattr(cls, "client", None):
            cls.client.close()
        if db._pool is not None:
            db._pool.closeall()
            db._pool = None
        os.environ["DATABASE_URL"] = cls.original_dsn
        if not cls.schema.startswith("gv_test_") or len(cls.schema) != 40:
            raise RuntimeError("Refusing cleanup outside the generated test schema")
        with cls.admin.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))
        cls.admin.close()

    def setUp(self):
        from src.api.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_schema() AS schema")
                self.assertEqual(cur.fetchone()["schema"], self.schema)
                cur.execute("TRUNCATE games RESTART IDENTITY CASCADE")

    def game(self, title="Fixture", ownership="owned", hours=None):
        from src.api.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO games(title,platform,hltb_completionist_hours) VALUES(%s,'PS3',%s) RETURNING id",
                    (title, hours),
                )
                game_id = cur.fetchone()["id"]
                cur.execute(
                    "INSERT INTO user_games(game_id,status,ownership) VALUES(%s,%s,%s)",
                    (game_id, "wishlist" if ownership == "wanted" else "owned", ownership),
                )
        return game_id

    def trophy(self, game_id, trophy_type="bronze", earned=False):
        from src.api.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO trophies(game_id,name,trophy_type) VALUES(%s,'Fixture trophy',%s) RETURNING id",
                    (game_id, trophy_type),
                )
                trophy_id = cur.fetchone()["id"]
                cur.execute("INSERT INTO user_trophies(trophy_id,earned) VALUES(%s,%s)", (trophy_id, earned))
        return trophy_id

    def test_queue_swap_persists_and_invalid_order_is_atomic(self):
        first, second = self.game("First"), self.game("Second")
        for game_id in [first, second]:
            self.assertEqual(self.client.post("/backlog", json={"game_id": game_id}).status_code, 201)
        response = self.client.put("/backlog/reorder", json={"ordered_game_ids": [second, first]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([g["game_id"] for g in self.client.get("/backlog").json()["entries"]], [second, first])
        for invalid in [[first, first], [first], [first, 99999]]:
            response = self.client.put("/backlog/reorder", json={"ordered_game_ids": invalid})
            self.assertIn(response.status_code, [400, 409, 422], response.text)
            self.assertEqual([g["game_id"] for g in self.client.get("/backlog").json()["entries"]], [second, first])

    def test_play_state_preserves_ownership_and_records_history(self):
        game_id = self.game()
        for state in ["playing", "paused", "finished"]:
            response = self.client.patch(f"/games/{game_id}/collection", json={"play_state": state})
            self.assertEqual(response.status_code, 200, response.text)
            game = self.client.get(f"/games/{game_id}").json()
            self.assertEqual(game["ownership"], "owned")
            self.assertEqual(game["play_state"], state)
        from src.api.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS count FROM play_state_history WHERE game_id=%s", (game_id,))
                self.assertEqual(cur.fetchone()["count"], 3)

    def test_platinum_requires_an_actual_platinum_trophy(self):
        game_id = self.game()
        self.trophy(game_id, "bronze", True)
        response = self.client.patch(f"/games/{game_id}/status", json={"status": "platinum"})
        self.assertIn(response.status_code, [400, 409, 422], response.text)
        self.assertFalse(self.client.get(f"/games/{game_id}").json()["platinum_earned"])
        platinum = self.trophy(game_id, "platinum")
        response = self.client.post(f"/user-trophies/{platinum}/earn", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.client.get(f"/games/{game_id}").json()["platinum_earned"])
        self.client.delete(f"/user-trophies/{platinum}/earn")
        self.assertFalse(self.client.get(f"/games/{game_id}").json()["platinum_earned"])

    def test_manual_session_routes_are_retired_and_history_is_preserved(self):
        game_id = self.game()
        from src.api.db import get_conn
        with get_conn() as conn,conn.cursor() as cur:
            cur.execute('INSERT INTO play_sessions(game_id,hours_played,notes) VALUES(%s,1.5,%s)',(game_id,'Archived checkpoint'))
        self.assertEqual(self.client.post(f'/games/{game_id}/sessions',json={'hours_played':2}).status_code,404)
        self.assertEqual(self.client.get(f'/games/{game_id}/sessions').status_code,404)
        self.assertNotIn('hours_played',self.client.get(f'/games/{game_id}').json())
        with get_conn() as conn,conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n FROM play_sessions WHERE game_id=%s',(game_id,))
            self.assertEqual(cur.fetchone()['n'],1)

    def test_wishlist_removal_does_not_turn_into_owned_game(self):
        game_id = self.game(ownership="wanted")
        self.client.post("/backlog", json={"game_id": game_id})
        response = self.client.delete(f"/wishlist/{game_id}")
        self.assertEqual(response.status_code, 204, response.text)
        self.assertNotIn(game_id, [g["id"] for g in self.client.get("/games").json()])
        self.assertNotIn(game_id, [g["game_id"] for g in self.client.get("/backlog").json()["entries"]])

    def test_unknown_estimates_remain_unknown_after_play(self):
        game_id = self.game(hours=None)
        self.client.post("/backlog", json={"game_id": game_id})
        queue = self.client.get("/backlog").json()
        self.assertGreaterEqual(float(queue["total_estimated_hours"]), 0)
        self.assertIsNone(queue["entries"][0].get("estimated_hours"))


if __name__ == "__main__":
    unittest.main()
