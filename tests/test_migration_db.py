"""Explicit opt-in, disposable PostgreSQL schema migration and reporting checks."""
import contextlib
import io
import os
from pathlib import Path
from unittest.mock import patch
import unittest
from uuid import uuid4


@unittest.skipUnless(os.environ.get('GAME_VAULT_DB_TESTS')=='1','isolated database test opt-in required')
class MigrationPreservation(unittest.TestCase):
    def test_legacy_upgrade_is_preserving_and_runner_is_idempotent(self):
        import psycopg2
        from psycopg2 import sql
        from psycopg2.extensions import make_dsn
        from dotenv import load_dotenv
        from scripts.migrate import main
        root=Path(__file__).resolve().parents[1]
        load_dotenv(root/'config/.env')
        original=os.environ['DATABASE_URL']
        schema='gv_migration_'+uuid4().hex
        admin=psycopg2.connect(original)
        admin.autocommit=True
        try:
            with admin.cursor() as cur:
                cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            dsn=make_dsn(original,options=f'-c search_path={schema}')
            with psycopg2.connect(dsn) as conn,conn.cursor() as cur:
                cur.execute((root/'migrations/001_initial.sql').read_text())
                cur.execute((root/'migrations/002_trophy_unique_psn_id.sql').read_text())
                cur.execute("""INSERT INTO games(id,title,platform,hltb_main_hours,hltb_complete_hours,hltb_platinum_hours)
                    VALUES(41,'Synthetic legacy - PS3','PS5',12,20,30),(42,'Battlefield 3','PS3',NULL,NULL,NULL)""")
                cur.execute("INSERT INTO user_games(game_id,status,notes) VALUES(41,'wishlist','Keep this note'),(42,'owned',NULL)")
                cur.execute("INSERT INTO backlog_entries(game_id,position,notes) VALUES(41,7,'Keep queue note')")
                cur.execute("INSERT INTO trophies(id,game_id,name,trophy_type) VALUES(91,41,'Synthetic platinum','platinum')")
                cur.execute("INSERT INTO user_trophies(trophy_id,earned,earned_at) VALUES(91,TRUE,'2026-01-01')")
                cur.execute((root/'migrations/003_collection_insights.sql').read_text())
                cur.execute('CREATE TABLE schema_migrations(version TEXT PRIMARY KEY,applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
                for version in ['001_initial.sql','002_trophy_unique_psn_id.sql','003_collection_insights.sql']:
                    cur.execute('INSERT INTO schema_migrations(version) VALUES(%s)',(version,))
                cur.execute("UPDATE user_games SET goal='story' WHERE game_id=41")
                cur.execute("UPDATE backlog_entries SET goal='platinum',user_remaining_hours=9 WHERE game_id=41")
                cur.execute("INSERT INTO play_sessions(game_id,hours_played,notes) VALUES(41,2,'Preserve archived session')")
            with patch.dict(os.environ,{'DATABASE_URL':dsn}),patch('sys.argv',['migrate','--apply']),contextlib.redirect_stdout(io.StringIO()):
                main()
                main()
            with psycopg2.connect(dsn) as conn,conn.cursor() as cur:
                cur.execute('SELECT hltb_extra_hours,hltb_completionist_hours,hltb_platinum_hours,platinum_hours FROM games WHERE id=41')
                self.assertEqual(cur.fetchone(),(20,30,30,None))
                cur.execute('SELECT title,platform FROM games WHERE id=41')
                self.assertEqual(cur.fetchone(),('Synthetic legacy','PS3'))
                cur.execute('SELECT ownership,play_state,notes FROM user_games WHERE game_id=41')
                self.assertEqual(cur.fetchone(),('wanted','not_started','Keep this note'))
                cur.execute('SELECT game_id,position,notes,goal FROM backlog_entries')
                self.assertEqual(cur.fetchone(),(41,7,'Keep queue note','completionist'))
                cur.execute('SELECT collection_goal,queue_goal,user_remaining_hours FROM retired_collection_plans WHERE game_id=41')
                self.assertEqual(cur.fetchone(),('story','platinum',9))
                cur.execute('SELECT user_remaining_hours FROM backlog_entries WHERE game_id=41')
                self.assertIsNone(cur.fetchone()[0])
                cur.execute('SELECT goal FROM user_games WHERE game_id=41')
                self.assertEqual(cur.fetchone()[0],'completionist')
                cur.execute('SELECT hours_played,notes FROM play_sessions WHERE game_id=41')
                self.assertEqual(cur.fetchone(),(2,'Preserve archived session'))
                cur.execute('SELECT earned,source FROM user_trophies WHERE trophy_id=91')
                self.assertEqual(cur.fetchone(),(True,'legacy'))
                cur.execute('SELECT platinum_feasibility,platinum_checked_at FROM games WHERE id=42')
                self.assertEqual(cur.fetchone(),('blocked',None))
                cur.execute('SELECT COUNT(*) FROM schema_migrations')
                self.assertEqual(cur.fetchone()[0],len(list((root/'migrations').glob('*.sql'))))
                cur.execute("SELECT to_regclass('psn_title_summaries')")
                self.assertEqual(cur.fetchone()[0],'psn_title_summaries')
                cur.execute("""INSERT INTO psn_title_summaries(game_id,external_id,official_title,platform)
                    VALUES(41,'SHARED_TEST_ID','Synthetic legacy','PS3'),
                          (42,'SHARED_TEST_ID','Synthetic alternate platform','PS4')""")
                cur.execute("SELECT COUNT(*) FROM psn_title_summaries WHERE external_id='SHARED_TEST_ID'")
                self.assertEqual(cur.fetchone()[0],2)
        finally:
            if schema.startswith('gv_migration_') and len(schema)==45:
                with admin.cursor() as cur:
                    cur.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))
            admin.close()


if __name__=='__main__':
    unittest.main()
