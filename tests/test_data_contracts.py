import unittest
from decimal import Decimal
from pydantic import ValidationError
from src.api.models.game import CollectionUpdate,GameResponse
from src.api.models.backlog import BacklogAdd,BacklogUpdate
from src.api.utils.queue import estimate_entry,summarize_queue


class CompletionistEstimateTests(unittest.TestCase):
    def test_summary_progress_applies_to_completionist_only(self):
        entry=estimate_entry({'goal':'story','hltb_main_hours':1,'hltb_completionist_hours':Decimal('80'),
            'psn_progress':25,'hours_played':300,'user_remaining_hours':2,'ownership':'owned'})
        self.assertEqual(entry['remaining_hours'],60)
        self.assertEqual(entry['goal'],'completionist')
        self.assertEqual(entry['progress_source'],'psn_summary')
        self.assertNotIn('hours_played',entry)
        self.assertNotIn('user_remaining_hours',entry)

    def test_summary_wins_over_local_trophy_ratio(self):
        entry=estimate_entry({'hltb_completionist_hours':80,'psn_progress':25,'trophy_count':2,'earned_count':2})
        self.assertEqual(entry['remaining_hours'],60)
        self.assertFalse(entry['is_completed'])

    def test_detailed_progress_fallback(self):
        entry=estimate_entry({'hltb_completionist_hours':80,'trophy_count':4,'earned_count':1})
        self.assertEqual(entry['remaining_hours'],60)
        self.assertEqual(entry['progress_source'],'loaded_trophies')

    def test_missing_progress_or_baseline_stays_unknown(self):
        for values in [{'hltb_completionist_hours':80},{'psn_progress':20},
                       {'psn_progress':20,'hltb_completionist_hours':0}]:
            self.assertIsNone(estimate_entry(values)['remaining_hours'])

    def test_zero_progress_is_known_and_complete_is_zero(self):
        entry=estimate_entry({'hltb_completionist_hours':80,'psn_progress':0})
        self.assertEqual(entry['remaining_hours'],80)
        complete=estimate_entry({'psn_progress':100})
        self.assertEqual(complete['remaining_hours'],0)
        self.assertTrue(complete['is_completed'])

    def test_manual_done_and_platinum_complete_without_inflating_trophy_progress(self):
        for evidence,reason in [({'play_state':'finished'},'manual'),({'platinum_earned':True},'platinum'),
                                ({'psn_earned_platinum':1},'platinum')]:
            entry=estimate_entry({**evidence,'psn_progress':75,'hltb_completionist_hours':80})
            self.assertTrue(entry['is_completed'])
            self.assertEqual(entry['remaining_hours'],0)
            self.assertEqual(entry['progress_pct'],75)
            self.assertEqual(entry['completion_reason'],reason)

    def test_progress_and_earned_counts_derive_playing_even_with_rounded_zero(self):
        for evidence in [{'psn_progress':1},{'earned_count':1,'psn_progress':0},
                         {'psn_earned_trophies':1,'psn_progress':0}]:
            entry=estimate_entry({'play_state':'not_started',**evidence})
            self.assertEqual(entry['play_state'],'playing')
            self.assertEqual(entry['manual_play_state'],'not_started')
            self.assertFalse(entry['is_completed'])

    def test_paused_dropped_are_preserved_until_completion(self):
        for state in ['paused','dropped']:
            self.assertEqual(estimate_entry({'play_state':state,'psn_progress':50})['play_state'],state)
            self.assertEqual(estimate_entry({'play_state':state,'platinum_earned':True})['play_state'],'finished')

    def test_derived_completion_does_not_become_manual_and_is_idempotent(self):
        entry=estimate_entry({'play_state':'not_started','psn_earned_platinum':1,'psn_progress':75})
        self.assertEqual(estimate_entry(entry),entry)
        self.assertEqual(entry['manual_play_state'],'not_started')
        self.assertEqual(entry['completion_reason'],'platinum')

    def test_manual_platinum_override_takes_precedence_over_summary_platinum(self):
        entry=estimate_entry({'psn_progress':75,'psn_earned_platinum':1,'platinum_earned':False,'platinum_manual_override':True})
        self.assertFalse(entry['platinum_earned'])
        self.assertFalse(entry['is_completed'])

    def test_mixed_coverage_and_summary(self):
        entries=[estimate_entry({'psn_progress':50,'hltb_completionist_hours':80,'ownership':'owned'}),
                 estimate_entry({'ownership':'wanted'}),estimate_entry({'psn_progress':100,'ownership':'owned'})]
        summary=summarize_queue(entries)
        self.assertEqual(summary['total_estimated_hours'],40)
        self.assertEqual(summary['known_estimate_count'],2)
        self.assertEqual(summary['unknown_estimate_count'],1)

    def test_game_response_uses_shared_calculation(self):
        game=GameResponse(id=1,title='Fixture',platform='PS3',psn_progress=25,hltb_completionist_hours=80)
        self.assertEqual(game.remaining_hours,60)


class RequestValidationTests(unittest.TestCase):
    def test_removed_plan_and_override_fields_are_rejected(self):
        for model,values in [(CollectionUpdate,{'goal':'story'}),(CollectionUpdate,{'goal':'completionist'}),
                             (BacklogAdd,{'game_id':1,'goal':'completionist'}),
                             (BacklogUpdate,{'goal':'platinum'}),(BacklogUpdate,{'user_remaining_hours':0})]:
            with self.assertRaises(ValidationError):
                model(**values)

    def test_collection_states_cannot_be_null_or_unknown(self):
        for field in ['ownership','play_state','platinum_feasibility']:
            for value in [None,'invalid']:
                with self.subTest(field=field,value=value),self.assertRaises(ValidationError):
                    CollectionUpdate(**{field:value})


if __name__=='__main__':
    unittest.main()
