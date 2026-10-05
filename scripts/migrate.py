"""Transactional migrations. Default/check only reports; --apply explicitly mutates."""
import argparse
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    load_dotenv(ROOT / 'config/.env')
    with psycopg2.connect(os.environ['DATABASE_URL']) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(8020003)')
            cur.execute("SELECT to_regclass('schema_migrations'), to_regclass('games')")
            ledger, existing = cur.fetchone()
            applied = set()
            if ledger:
                cur.execute('SELECT version FROM schema_migrations')
                applied = {row[0] for row in cur.fetchall()}
            if existing and not ledger:
                applied.add('001_initial.sql')
                cur.execute("SELECT to_regclass('idx_trophies_game_psn_id')")
                if cur.fetchone()[0]:
                    applied.add('002_trophy_unique_psn_id.sql')
            pending = [p for p in sorted((ROOT / 'migrations').glob('*.sql')) if p.name not in applied]
            print('Pending: ' + (', '.join(p.name for p in pending) or 'none'))
            if not args.apply:
                return
            cur.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
            for version in applied:
                cur.execute('INSERT INTO schema_migrations(version) VALUES(%s) ON CONFLICT DO NOTHING', (version,))
            for path in pending:
                cur.execute(path.read_text())
                cur.execute('INSERT INTO schema_migrations(version) VALUES(%s)', (path.name,))
                print('Applied: ' + path.name)


if __name__ == '__main__':
    main()
