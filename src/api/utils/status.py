"""Reconcile the legacy status projection without overwriting saved play intent."""
from src.api.db import get_conn
from src.api.utils.queue import estimate_entry


def auto_update_status(game_id: int,conn=None):
    if conn is None:
        with get_conn() as connection:
            return auto_update_status(game_id,conn=connection)
    with conn.cursor() as cur:
        cur.execute("""SELECT ug.ownership,ug.play_state,pts.progress AS psn_progress,
            pts.earned_platinum AS psn_earned_platinum,
            pts.earned_bronze+pts.earned_silver+pts.earned_gold+pts.earned_platinum AS psn_earned_trophies,
            (SELECT COUNT(*) FROM trophies t WHERE t.game_id=ug.game_id) AS trophy_count,
            (SELECT COUNT(*) FROM trophies t JOIN user_trophies ut ON ut.trophy_id=t.id
                WHERE t.game_id=ug.game_id AND ut.earned) AS earned_count,
            EXISTS(SELECT 1 FROM trophies t JOIN user_trophies ut ON ut.trophy_id=t.id
                WHERE t.game_id=ug.game_id AND t.trophy_type='platinum' AND ut.earned) AS platinum_earned,
            EXISTS(SELECT 1 FROM trophies t JOIN user_trophies ut ON ut.trophy_id=t.id
                WHERE t.game_id=ug.game_id AND t.trophy_type='platinum' AND ut.manual_override) AS platinum_manual_override
            FROM user_games ug LEFT JOIN psn_title_summaries pts ON pts.game_id=ug.game_id
            WHERE ug.game_id=%s""",(game_id,))
        row=cur.fetchone()
        if row:
            cur.execute('UPDATE user_games SET status=%s WHERE game_id=%s',(estimate_entry(row)['status'],game_id))
