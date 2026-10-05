"""Completionist time remaining is a transparent trophy-progress approximation."""
import math


def estimate_entry(entry):
    result = dict(entry)
    progress=result.get('psn_progress')
    source='psn_summary' if progress is not None else 'unknown'
    if progress is None and (result.get('trophy_count') or 0)>0:
        progress=100*float(result.get('earned_count') or 0)/float(result['trophy_count'])
        source='loaded_trophies'
    if progress is not None:
        progress=max(0,min(100,float(progress))) if math.isfinite(float(progress)) else None
    # Saved intent remains separate, so inferred completion is reversible after an
    # earned observation is corrected and cannot become a sticky manual finish.
    manual_state=result.get('manual_play_state',result.get('play_state')) or 'not_started'
    platinum=bool(result.get('platinum_earned')) or (
        not result.get('platinum_manual_override') and (result.get('psn_earned_platinum') or 0)>0)
    completion_reason='manual' if manual_state=='finished' else 'platinum' if platinum else 'trophy_progress' if progress is not None and progress>=100 else None
    completed=completion_reason is not None
    started=(progress is not None and progress>0) or (result.get('earned_count') or 0)>0 or (result.get('psn_earned_trophies') or 0)>0
    effective_state='finished' if completed else manual_state if manual_state in ('paused','dropped') else 'playing' if started else manual_state
    baseline=result.get('hltb_completionist_hours')
    baseline=float(baseline) if baseline is not None else None
    valid_baseline=baseline is not None and math.isfinite(baseline) and baseline>0
    remaining=0.0 if completed else round(baseline*(1-progress/100),2) if valid_baseline and progress is not None else None
    result['goal']='completionist'
    result['progress_pct']=round(progress,2) if progress is not None else None
    result['progress_source']=source if progress is not None else 'unknown'
    result['is_completed']=completed
    result['completion_reason']=completion_reason
    result['manual_play_state']=manual_state
    result['play_state']=effective_state
    result['platinum_earned']=platinum
    result['status']='wishlist' if result.get('ownership')=='wanted' else 'platinum' if platinum else 'completed' if completed else 'playing' if effective_state=='playing' else 'owned'
    result['remaining_hours']=remaining
    result['estimated_hours']=remaining
    result['estimate_kind']='completed' if completed else 'trophy_progress_approximation' if remaining is not None else 'unknown'
    for retired in ('user_remaining_hours','hours_played','last_session_date','last_session_notes'):
        result.pop(retired,None)
    result['available'] = result.get('ownership') in ('owned', 'available')
    return result


def summarize_queue(entries):
    known = [e for e in entries if e['estimated_hours'] is not None]
    available = sum(e['available'] for e in entries)
    return {
        'total_estimated_hours': round(sum(e['estimated_hours'] for e in known), 2),
        'known_estimate_count': len(known), 'unknown_estimate_count': len(entries) - len(known),
        'available_count': available, 'unavailable_count': len(entries) - available,
        'total_count': len(entries), 'coverage_pct': round(100 * len(known) / len(entries), 1) if entries else 0,
        'scope': 'Approximate remaining completionist hours = completionist estimate × unearned trophy progress. Trophy progress is not proportional to time. Missing progress or estimates remain unknown; completed games contribute zero.',
    }


def load_queue(cur):
    cur.execute("""
        SELECT be.id,be.game_id,be.position,be.target_date,be.notes,be.added_at,be.goal,
            g.title, g.platform, g.cover_url, g.hltb_main_hours,
            g.hltb_extra_hours,g.hltb_completionist_hours,g.platinum_hours,g.platinum_source,
            g.platinum_feasibility,g.platinum_blocker_reason,g.platinum_checked_at,
            ug.status,ug.ownership,ug.play_state,ug.next_action,
            pts.progress AS psn_progress,
            pts.earned_platinum AS psn_earned_platinum,
            pts.earned_bronze+pts.earned_silver+pts.earned_gold+pts.earned_platinum AS psn_earned_trophies,
            (SELECT COUNT(*) FROM trophies t WHERE t.game_id=g.id) AS trophy_count,
            EXISTS(SELECT 1 FROM trophies t JOIN user_trophies ut ON ut.trophy_id=t.id
                WHERE t.game_id=g.id AND t.trophy_type='platinum' AND ut.earned) AS platinum_earned,
            EXISTS(SELECT 1 FROM trophies t JOIN user_trophies ut ON ut.trophy_id=t.id
                WHERE t.game_id=g.id AND t.trophy_type='platinum' AND ut.manual_override) AS platinum_manual_override,
            (SELECT COUNT(*) FROM trophies t JOIN user_trophies ut ON ut.trophy_id=t.id
                WHERE t.game_id=g.id AND ut.earned) AS earned_count
        FROM backlog_entries be JOIN games g ON g.id=be.game_id
        JOIN user_games ug ON ug.game_id=g.id
        LEFT JOIN psn_title_summaries pts ON pts.game_id=g.id ORDER BY be.position
    """)
    # Stable partition retains saved relative priority inside each completion group.
    return sorted((estimate_entry(row) for row in cur.fetchall()),key=lambda row:row['is_completed'])
