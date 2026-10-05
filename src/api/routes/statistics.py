from fastapi import APIRouter
from src.api.db import get_conn
from src.api.routes.games import GAME_SELECT
from src.api.utils.queue import estimate_entry,load_queue,summarize_queue
from src.api.models.statistics import StatisticsResponse

router=APIRouter(prefix='/statistics',tags=['statistics'])


@router.get('',response_model=StatisticsResponse)
def get_statistics():
    with get_conn() as conn,conn.cursor() as cur:
        cur.execute(GAME_SELECT+' ORDER BY g.title')
        collection=[estimate_entry(row) for row in cur.fetchall()]
        counts={
            'owned_count':sum(g['ownership']=='owned' for g in collection),
            'available_count':sum(g['ownership']=='available' for g in collection),
            'wishlist_count':sum(g['ownership']=='wanted' for g in collection),
            'playing_count':sum(g['play_state']=='playing' and not g['is_completed'] for g in collection),
            'completed_count':sum(g['is_completed'] for g in collection),
            'platinum_count':sum(g['platinum_earned'] for g in collection),'total_count':len(collection),
        }
        cur.execute("""
            SELECT COUNT(t.id) AS total_trophies,COUNT(*) FILTER(WHERE ut.earned) AS earned_trophies,
                COUNT(DISTINCT t.game_id) AS loaded_game_count,
                COUNT(*) FILTER(WHERE t.trophy_type='bronze') AS bronze_total,
                COUNT(*) FILTER(WHERE t.trophy_type='bronze' AND ut.earned) AS bronze_earned,
                COUNT(*) FILTER(WHERE t.trophy_type='silver') AS silver_total,
                COUNT(*) FILTER(WHERE t.trophy_type='silver' AND ut.earned) AS silver_earned,
                COUNT(*) FILTER(WHERE t.trophy_type='gold') AS gold_total,
                COUNT(*) FILTER(WHERE t.trophy_type='gold' AND ut.earned) AS gold_earned,
                COUNT(*) FILTER(WHERE t.trophy_type='platinum') AS platinum_trophy_total,
                COUNT(*) FILTER(WHERE t.trophy_type='platinum' AND ut.earned) AS platinum_trophy_earned
            FROM trophies t JOIN user_games ug ON ug.game_id=t.game_id
            LEFT JOIN user_trophies ut ON ut.trophy_id=t.id
        """)
        trophies=dict(cur.fetchone())
        trophies['completion_rate_pct']=round(trophies['earned_trophies']/trophies['total_trophies']*100,1) if trophies['total_trophies'] else None
        trophies['loaded_completion_rate_pct']=trophies['completion_rate_pct']
        trophies['collection_game_count']=counts['total_count']
        trophies['scope']='Loaded trophy sets only; not collection completion'
        entries=load_queue(cur)
        queue=summarize_queue(entries)
        playing=[g for g in collection if g['play_state']=='playing' and not g['is_completed']][:6]
        blocked=[g for g in collection if g['platinum_feasibility'] in ('blocked','not_applicable')]
        ready=[e for e in entries if e['available'] and not e['is_completed'] and e['play_state']!='dropped']
        next_up=[{**e,'reason':'Available to play · next in your completionist queue'} for e in ready[:3]]
        finish_soon=[{**e,'reason':'Approximate remaining time from completionist estimate and trophy progress; trophy effort varies'}
            for e in sorted((e for e in ready if e['remaining_hours'] is not None),key=lambda e:e['remaining_hours'])[:3]]
        cur.execute("""SELECT COUNT(*) AS earned_trophies FROM user_trophies ut
            JOIN trophies t ON t.id=ut.trophy_id JOIN user_games ug ON ug.game_id=t.game_id
            WHERE ut.earned AND ut.earned_at>=date_trunc('month',CURRENT_DATE) AND ut.earned_at<=NOW()""")
        month_activity=cur.fetchone()
        cur.execute("""SELECT t.game_id,g.title,t.name,ut.earned_at FROM user_trophies ut
            JOIN trophies t ON t.id=ut.trophy_id JOIN games g ON g.id=t.game_id
            JOIN user_games ug ON ug.game_id=g.id WHERE ut.earned AND ut.earned_at IS NOT NULL
            AND t.trophy_type='platinum' ORDER BY ut.earned_at DESC LIMIT 5""")
        milestones=cur.fetchall()
        return {'library':counts,'trophies':trophies,'backlog':queue,
                'backlog_estimated_hours':queue['total_estimated_hours'],
                'this_month':month_activity,'milestones':milestones,
                'insights':{'playing':playing,'next_up':next_up,'finish_soon':finish_soon,'blocked':blocked}}
