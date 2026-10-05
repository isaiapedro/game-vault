"""Completionist-only workflow checks in an isolated PostgreSQL schema."""
import os
import unittest
try:
    from tests import test_workflows_db as fixtures
except ImportError:
    import test_workflows_db as fixtures


@unittest.skipUnless(os.environ.get('GAME_VAULT_DB_TESTS')=='1','isolated database test opt-in required')
class ReportingWorkflows(unittest.TestCase):
    setUpClass=classmethod(fixtures.DatabaseWorkflows.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.DatabaseWorkflows.tearDownClass.__func__)
    setUp=fixtures.DatabaseWorkflows.setUp
    game=fixtures.DatabaseWorkflows.game
    trophy=fixtures.DatabaseWorkflows.trophy

    def test_removed_manual_inputs_are_rejected(self):
        game_id=self.game(hours=20)
        self.client.post('/backlog',json={'game_id':game_id})
        for data in [{'goal':'story'},{'user_remaining_hours':3}]:
            self.assertEqual(self.client.patch(f'/backlog/{game_id}',json=data).status_code,422)
        self.assertEqual(self.client.patch(f'/games/{game_id}/collection',json={'goal':'completionist'}).status_code,422)

    def test_statistics_and_detail_share_remaining_estimate(self):
        owned=self.game('Ready',hours=12)
        wanted=self.game('Wanted',ownership='wanted')
        for game_id in [owned,wanted]:
            self.client.post('/backlog',json={'game_id':game_id})
        self.trophy(owned,'bronze',True)
        self.trophy(owned,'platinum',False)
        self.client.patch(f'/games/{owned}/collection',json={'play_state':'playing'})
        response=self.client.get('/statistics')
        self.assertEqual(response.status_code,200,response.text)
        stats=response.json()
        queue=self.client.get('/backlog').json()
        self.assertEqual(stats['backlog'],queue['summary'])
        self.assertEqual(stats['backlog']['total_estimated_hours'],6)
        self.assertEqual(self.client.get(f'/games/{owned}').json()['remaining_hours'],6)
        self.assertEqual(stats['backlog']['unknown_estimate_count'],1)
        self.assertEqual(stats['trophies']['loaded_game_count'],1)
        self.assertEqual([row['game_id'] for row in stats['insights']['next_up']],[owned])
        for removed in ['monthly_hours','total_hours_played','recent_activity','session_count']:
            self.assertNotIn(removed,stats)

    def test_completion_moves_to_bottom_and_reorder_preserves_group_priority(self):
        first,second,third,fourth=[self.game(name,hours=20) for name in ['First','Second','Third','Fourth']]
        for game_id in [first,second,third,fourth]:
            self.client.post('/backlog',json={'game_id':game_id})
        self.trophy(first,'bronze',True)
        self.trophy(third,'bronze',True)
        initial=[second,fourth,first,third]
        self.assertEqual([g['game_id'] for g in self.client.get('/backlog').json()['entries']],initial)
        response=self.client.put('/backlog/reorder',json={'ordered_game_ids':[third,fourth,first,second],'expected_game_ids':initial})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([g['game_id'] for g in self.client.get('/backlog').json()['entries']],[fourth,second,third,first])
        stats=self.client.get('/statistics').json()
        self.assertEqual(stats['library']['completed_count'],2)
        self.assertTrue(all(not row['is_completed'] for row in stats['insights']['next_up']))

    def test_empty_statistics_preserve_unknown_coverage(self):
        response=self.client.get('/statistics')
        self.assertEqual(response.status_code,200,response.text)
        self.assertIsNone(response.json()['trophies']['completion_rate_pct'])
        self.assertEqual(response.json()['insights']['next_up'],[])

    def test_mark_done_retains_queue_item_and_can_be_undone(self):
        first,second=self.game('First'),self.game('Second')
        for game_id in [first,second]:
            self.client.post('/backlog',json={'game_id':game_id})
        before=self.client.get('/backlog').json()['entries']
        for _ in range(2):
            response=self.client.patch(f'/games/{first}/collection',json={'play_state':'finished'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['completion_reason'],'manual')
            self.assertIsNone(response.json()['progress_pct'])
            self.assertEqual(response.json()['remaining_hours'],0)
        after=self.client.get('/backlog').json()['entries']
        self.assertEqual([g['game_id'] for g in after],[second,first])
        self.assertEqual({g['id']:g['position'] for g in before},{g['id']:g['position'] for g in after})
        self.assertEqual(self.client.get('/statistics').json()['library']['completed_count'],1)
        self.client.patch(f'/games/{first}/collection',json={'play_state':'not_started'})
        self.assertEqual([g['game_id'] for g in self.client.get('/backlog').json()['entries']],[first,second])

    def test_summary_progress_and_platinum_are_consistent_across_views(self):
        started,completed=self.game('Started',hours=20),self.game('Completed',hours=20)
        from src.api.db import get_conn
        with get_conn() as conn,conn.cursor() as cur:
            for game_id,progress,bronze,platinum in [(started,0,1,0),(completed,75,5,1)]:
                cur.execute("""INSERT INTO psn_title_summaries(game_id,external_id,official_title,platform,
                    progress,earned_bronze,earned_platinum) VALUES(%s,%s,'Synthetic','PS3',%s,%s,%s)""",
                    (game_id,f'SYNTHETIC{game_id}',progress,bronze,platinum))
        for game_id in [completed,started]:
            self.client.post('/backlog',json={'game_id':game_id})
        queue=self.client.get('/backlog').json()['entries']
        self.assertEqual([g['game_id'] for g in queue],[started,completed])
        self.assertEqual(queue[0]['play_state'],'playing')
        self.assertEqual(queue[1]['play_state'],'finished')
        self.assertEqual(queue[1]['remaining_hours'],0)
        self.assertEqual(queue[1]['progress_pct'],75)
        for game in self.client.get('/games').json():
            detail=self.client.get(f"/games/{game['id']}").json()
            self.assertEqual(game['play_state'],detail['play_state'])
            self.assertEqual(game['is_completed'],detail['is_completed'])
        stats=self.client.get('/statistics').json()
        self.assertEqual(stats['library']['playing_count'],1)
        self.assertEqual(stats['library']['completed_count'],1)
        self.assertEqual(stats['library']['platinum_count'],1)
        with get_conn() as conn,conn.cursor() as cur:
            cur.execute('SELECT play_state FROM user_games WHERE game_id=%s',(completed,))
            self.assertEqual(cur.fetchone()['play_state'],'not_started')

    def test_unearning_platinum_reverses_derived_completion(self):
        game_id=self.game()
        platinum=self.trophy(game_id,'platinum',True)
        self.trophy(game_id,'bronze',False)
        self.client.post('/backlog',json={'game_id':game_id})
        self.assertTrue(self.client.get(f'/games/{game_id}').json()['is_completed'])
        self.assertEqual(self.client.delete(f'/user-trophies/{platinum}/earn').status_code,204)
        game=self.client.get(f'/games/{game_id}').json()
        self.assertFalse(game['is_completed'])
        self.assertEqual(game['play_state'],'not_started')


if __name__=='__main__':
    unittest.main()
