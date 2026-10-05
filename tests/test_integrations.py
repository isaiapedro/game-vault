import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from howlongtobeatpy import HowLongToBeat
from src.api.integrations import hltb_client, igdb_client, psn_client
from src.api.routes.sync import match_titles, sync_psn, _upsert_trophies, _cache_confirmed_artwork, _store_title_summary, bind_psn, ConfirmPSN
from src.api.routes.trophies import earn_trophy, unearn_trophy, get_trophies
from fastapi import HTTPException
from src.api.models.trophy import TrophyEarn
from src.api.routes import enrich
from src.api.utils.release_identity import split_platform_suffix, normalized_title, same_release_title, release_match_score


class EstimateTests(unittest.IsolatedAsyncioTestCase):
    async def test_alias_candidate_does_not_write_unconfirmed_estimate(self):
        state=dict(running=True,total=1,done=0,skipped=0,failed=0,current=None,outcomes=[])
        candidate=dict(main=8,main_extra=10,completionist=14,match_confidence="alias_needs_review",
                       candidates=[{"id":"12","title":"Original Name"}])
        game={"id":1,"title":"PSN Display Name","specifications":{"catalog_title_before_psn":"Original Name"}}
        with patch.object(enrich.hltb_client,"get_times",new=AsyncMock(return_value=candidate)) as lookup, \
             patch.object(enrich.jobs,"save"), patch.object(enrich.asyncio,"sleep",new=AsyncMock()), \
             patch("src.api.routes.enrich.get_conn") as connection:
            await enrich._run_enrichment([game],7,state)
        lookup.assert_awaited_once_with("PSN Display Name",aliases=("Original Name",))
        connection.assert_not_called()
        self.assertEqual(state["outcomes"][0]["outcome"],"needs_review")

    async def test_durable_job_distinguishes_no_data_and_failure(self):
        state=dict(running=True,total=2,done=0,skipped=0,failed=0,current=None,outcomes=[])
        empty=dict(main=None,main_extra=None,completionist=None,candidates=[])
        with patch.object(enrich.hltb_client,"get_times",new=AsyncMock(side_effect=[empty,RuntimeError("secret")])):
            with patch.object(enrich.jobs,"save") as save,patch.object(enrich.asyncio,"sleep",new=AsyncMock()):
                await enrich._run_enrichment([{"id":1,"title":"First"},{"id":2,"title":"Second"}],7,state)
        self.assertEqual(state["phase"],"partial_success")
        self.assertEqual([row["outcome"] for row in state["outcomes"]],["no_data","failed"])
        self.assertNotIn("secret",str(state))
        self.assertEqual(save.call_count,3)

    async def test_categories_and_no_invented_platinum(self):
        result = SimpleNamespace(game_name="Example",game_id=1,main_story=10,main_extra=20,completionist=30)
        with patch.object(HowLongToBeat,"async_search",new=AsyncMock(return_value=[result])):
            times = await hltb_client.get_times("Example")
        self.assertEqual((times["main"],times["main_extra"],times["completionist"]),(10,20,30))
        self.assertIsNone(times["platinum"])
        self.assertEqual(times["match_confidence"],"exact_title")

    async def test_ambiguous_and_substring_titles_are_not_accepted(self):
        game = SimpleNamespace(game_name="Example 2",game_id=1)
        for results in ([game],[game,game]):
            with patch.object(HowLongToBeat,"async_search",new=AsyncMock(return_value=results)):
                times = await hltb_client.get_times("Example" if len(results)==1 else "Example 2")
            self.assertIsNone(times["main"])
            self.assertTrue(times["candidates"])

    async def test_provider_failure_is_not_no_data(self):
        with patch.object(HowLongToBeat,"async_search",new=AsyncMock(side_effect=RuntimeError("secret"))):
            with self.assertRaises(RuntimeError):
                await hltb_client.get_times("Example")

    async def test_provider_none_is_failure_but_empty_list_is_no_data(self):
        with patch.object(HowLongToBeat,"async_search",new=AsyncMock(return_value=None)):
            with self.assertRaises(RuntimeError):
                await hltb_client.get_times("Example")
        with patch.object(HowLongToBeat,"async_search",new=AsyncMock(return_value=[])):
            self.assertEqual((await hltb_client.get_times("Example"))["candidates"],[])

    async def test_historical_catalog_alias_is_a_review_candidate(self):
        candidate = SimpleNamespace(game_name="Original Name",game_id=12,main_story=8,main_extra=10,completionist=14)
        with patch.object(HowLongToBeat,"async_search",new=AsyncMock(side_effect=[[],[candidate]])) as search:
            times = await hltb_client.get_times("PSN Display Name",aliases=("Original Name",))
        self.assertEqual(search.await_count,2)
        self.assertEqual(times["match_confidence"],"alias_needs_review")
        self.assertEqual(times["source_id"],"12")

    async def test_distinct_exact_alias_matches_are_ambiguous(self):
        first = SimpleNamespace(game_name="Display",game_id=1)
        second = SimpleNamespace(game_name="Catalog",game_id=2)
        with patch.object(HowLongToBeat,"async_search",new=AsyncMock(side_effect=[[first],[second]])):
            times = await hltb_client.get_times("Display",aliases=("Catalog",))
        self.assertEqual(times["match_confidence"],"ambiguous")
        self.assertIsNone(times["source_id"])


class IdentityTests(unittest.TestCase):
    def test_platform_suffix_is_separated_from_title(self):
        for raw in ("Example PS3","Example - PS3","Example | PS3","Example (PS3)","Example [PS3]"):
            self.assertEqual(split_platform_suffix(raw),("Example","PS3"))
        self.assertEqual(split_platform_suffix("Example", "PS3"),("Example","PS3"))

    def test_title_decoration_matches_only_on_same_platform(self):
        game={"id":1,"title":"Uncharted 2: Among Thieves - PS3","platform":"PS3","psn_id":None}
        psn={"title_name":"Uncharted 2: Among Thieves™ ","platforms":["PS3"]}
        self.assertTrue(same_release_title(game,psn))
        self.assertEqual(normalized_title(psn["title_name"]),"uncharted 2 among thieves")
        self.assertFalse(same_release_title(game,{**psn,"platforms":["PS4"]}))

    def test_exact_normalized_release_is_suggested_not_automatically_matched(self):
        game={"id":1,"title":"Sleeping Dogs - PS3","platform":"PS3","psn_id":None}
        title={"title_name":"Sleeping Dogs™","np_communication_id":"NP1","platforms":["PS3"]}
        matched,unmatched=match_titles([game],[title])
        self.assertFalse(matched)
        self.assertEqual(unmatched[0]["local_matches"][0]["game_id"],1)
        self.assertEqual(unmatched[0]["local_matches"][0]["match_reason"],"same_normalized_title_and_platform")

    def test_character_matching_keeps_sequels_separate(self):
        provider={"title_name":"LittleBigPlanet 2","platforms":["PS3"]}
        self.assertEqual(release_match_score({"title":"LittleBigPlanet","platform":"PS3"},provider),0)
        self.assertGreaterEqual(release_match_score({"title":"LittleBigPlanet 2 - PS3","platform":"PS3"},provider),.88)
        self.assertEqual(release_match_score({"title":"LittleBigPlanet 2","platform":"PS4"},provider),0)

    def test_account_sync_does_not_fetch_each_trophy_list(self):
        title={"title_name":"Example","np_communication_id":"NP1","platforms":["PS3"],"progress":50}
        game={"id":1,"title":"Example","platform":"PS3","psn_id":"NP1","psn_confirmed":True}
        conn=MagicMock()
        cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value=[game]
        cur.fetchone.return_value={"psn_id":"NP1"}
        with patch("src.api.routes.sync.get_conn") as context, \
             patch("src.api.routes.sync.psn_client.is_configured",return_value=True), \
             patch("src.api.routes.sync.jobs.start",return_value=7), \
             patch("src.api.routes.sync.jobs.save"), \
             patch("src.api.routes.sync.psn_client.get_all_trophy_titles",return_value=[title]) as account, \
             patch("src.api.routes.sync.psn_client.get_trophies_for_game") as details, \
             patch("src.api.routes.sync._store_title_summary") as store:
            context.return_value.__enter__.return_value=conn
            result=sync_psn()
        self.assertEqual(result["done_games"],1)
        self.assertFalse(result["running"])
        details.assert_not_called()
        account.assert_called_once_with()
        store.assert_called_once()

    def test_tied_local_candidates_neither_automatically_match(self):
        games=[{"id":n,"title":"Example","platform":"PS3","psn_id":None} for n in (1,2)]
        title={"title_name":"Example","np_communication_id":"NP1","platforms":["PS3"]}
        _,review=match_titles(games,[title])
        self.assertFalse(any(row["automatic"] for row in review[0]["local_matches"]))

    def test_sync_rollback_does_not_report_successful_outcomes(self):
        games=[{"id":i,"title":f"Example {i}","platform":"PS3","psn_id":f"NP{i}","psn_confirmed":True} for i in (1,2)]
        titles=[{"title_name":g["title"],"np_communication_id":g["psn_id"],"platforms":["PS3"]} for g in games]
        conn=MagicMock()
        cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value=games
        cur.fetchone.side_effect=[{"psn_id":"NP1"},{"psn_id":"NP2"}]
        with patch("src.api.routes.sync.get_conn") as context, \
             patch.object(psn_client,"is_configured",return_value=True), \
             patch("src.api.routes.sync.jobs.start",return_value=7), \
             patch("src.api.routes.sync.jobs.save") as save, \
             patch.object(psn_client,"get_all_trophy_titles",return_value=titles), \
             patch("src.api.routes.sync._store_title_summary",side_effect=[None,RuntimeError("secret")]):
            context.return_value.__enter__.return_value=conn
            with self.assertRaises(HTTPException):
                sync_psn()
        state=save.call_args.args[1]
        self.assertEqual(state["phase"],"failed")
        self.assertEqual(state["outcomes"],[])
        self.assertEqual(state["done_games"],0)
        self.assertNotIn("secret",str(state))

    def test_mapping_changed_during_sync_is_rejected_before_storage(self):
        game={"id":1,"title":"Example","platform":"PS3","psn_id":"NP1","psn_confirmed":True}
        title={"title_name":"Example","np_communication_id":"NP1","platforms":["PS3"]}
        conn=MagicMock()
        cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value=[game]
        cur.fetchone.return_value={"psn_id":"NP2"}
        with patch("src.api.routes.sync.get_conn") as context, \
             patch.object(psn_client,"is_configured",return_value=True), \
             patch("src.api.routes.sync.jobs.start",return_value=7), \
             patch("src.api.routes.sync.jobs.save"), \
             patch.object(psn_client,"get_all_trophy_titles",return_value=[title]), \
             patch("src.api.routes.sync._store_title_summary") as store:
            context.return_value.__enter__.return_value=conn
            with self.assertRaises(HTTPException):
                sync_psn()
        store.assert_not_called()

    def test_regional_provider_ambiguity_never_greedily_chooses_first(self):
        game={"id":1,"title":"Example","platform":"PS3","psn_id":None}
        titles=[{"title_name":"Example","np_communication_id":np_id,"platforms":["PS3"]} for np_id in ("NP1","NP2")]
        _,review=match_titles([game],titles)
        self.assertFalse(any(row["automatic"] for title in review for row in title["local_matches"]))

    def test_confirmed_identity_cannot_be_claimed_by_another_provider_or_game(self):
        game={"id":1,"title":"Example","platform":"PS3","psn_id":"NP1","psn_confirmed":True}
        other={"id":2,"title":"Example","platform":"PS3","psn_id":None}
        title={"title_name":"Example","np_communication_id":"NP1","platforms":["PS3"]}
        matched,review=match_titles([game,other],[title])
        self.assertEqual(len(matched),1)
        self.assertFalse(review)
        matched,review=match_titles([game],[{**title,"np_communication_id":"NP2"}])
        self.assertFalse(matched)
        self.assertFalse(review[0]["local_matches"])

    def test_fuzzy_editions_are_review_only(self):
        game={"id":1,"title":"Dark Souls","platform":"PS4","psn_id":None}
        title={"title_name":"Dark Souls Remastered","np_communication_id":"NP1","platforms":["PS4"]}
        _,review=match_titles([game],[title])
        self.assertTrue(review[0]["local_matches"])
        self.assertFalse(review[0]["local_matches"][0]["automatic"])

    def test_shared_title_summary_preserves_local_release_platform(self):
        cur=MagicMock()
        _store_title_summary(cur,{"id":1,"title":"Example","platform":"PS4"},
            {"title_name":"Example","platforms":["PS3","PS4"],"np_communication_id":"NP1"})
        self.assertEqual(cur.execute.call_args_list[0].args[1][1],"PS4")

    def test_legacy_remapping_cannot_mix_existing_trophy_facts(self):
        conn=MagicMock()
        cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect=[{"id":1,"title":"Example","platform":"PS3","psn_id":"NP1","psn_confirmed":False},{"cached":True}]
        title={"title_name":"Example","np_communication_id":"NP2","platforms":["PS3"]}
        with patch("src.api.routes.sync.get_conn") as context,patch.object(psn_client,"get_all_trophy_titles",return_value=[title]):
            context.return_value.__enter__.return_value=conn
            with self.assertRaises(HTTPException) as error:
                bind_psn(1,ConfirmPSN(np_communication_id="NP2",confirmed=True))
        self.assertEqual(error.exception.status_code,409)
        self.assertFalse(any("UPDATE games" in call.args[0] for call in cur.execute.call_args_list))

    def test_unknown_psn_platform_never_falls_back_to_other_releases(self):
        with self.assertRaises(ValueError):
            psn_client._platform_for_game("Other")

    def test_psn_partial_page_failure_is_not_accepted_as_complete(self):
        trophy=SimpleNamespace(trophy_id=1,trophy_name="First",trophy_detail="Description",
            trophy_type=psn_client.TrophyType.BRONZE,trophy_icon_url=None)
        def interrupted():
            yield trophy
            raise RuntimeError("network interrupted")
        account=MagicMock()
        account.me.return_value.trophies.return_value=interrupted()
        with patch.object(psn_client,"_get_psnawp",return_value=account):
            with self.assertRaises(RuntimeError):
                psn_client.get_trophies_for_game("NP1","PS3")

    def test_title_similarity_does_not_overwrite_identity(self):
        games=[{"id":1,"title":"Example","platform":"PS3","psn_id":None}]
        matched,unmatched=match_titles(games,[{"title_name":"Example","np_communication_id":"NP1"}])
        self.assertFalse(matched)
        self.assertEqual(len(unmatched),1)

    def test_same_provider_id_wrong_platform_not_matched(self):
        game={"id":1,"title":"Example","platform":"PS3","psn_id":"NP1","psn_confirmed":True}
        title={"title_name":"Different display title","np_communication_id":"NP1","platforms":["PS4"]}
        self.assertFalse(match_titles([game],[title])[0])
        title["platforms"]=["PS3"]
        self.assertEqual(match_titles([game],[title])[0][0]["id"],1)

    def test_legacy_mapping_requires_review_even_when_provider_identity_matches(self):
        game={"id":1,"title":"Example","platform":"PS3","psn_id":"NP1","psn_confirmed":False}
        title={"title_name":"Example","np_communication_id":"NP1","platforms":["PS3"]}
        matched,unmatched=match_titles([game],[title])
        self.assertFalse(matched)
        self.assertEqual(unmatched[0]["local_matches"][0]["game_id"],1)

    def test_artwork_update_requires_confirmed_mapping_and_empty_cover(self):
        cur=MagicMock()
        _cache_confirmed_artwork(cur,1,"NP1","https://example.com/cover.png")
        query,params=cur.execute.call_args.args
        self.assertIn("pm.match_state='confirmed'",query)
        self.assertIn("g.cover_url IS NULL",query)
        self.assertIn("cover_provenance",query)
        self.assertEqual(params,("https://example.com/cover.png","NP1",1,"NP1"))
        cur.reset_mock()
        _cache_confirmed_artwork(cur,1,"NP1","javascript:bad")
        cur.execute.assert_not_called()

    def test_igdb_platform_validation(self):
        metadata={"specifications":{"platforms":["PlayStation 4"]}}
        self.assertTrue(igdb_client.supports_platform(metadata,"PS4"))
        self.assertFalse(igdb_client.supports_platform(metadata,"PS3"))


class TrophyTransactionTests(unittest.TestCase):
    def test_uncached_legacy_trophies_cannot_bypass_confirmation(self):
        conn=MagicMock()
        cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value={"id":1,"title":"Example","platform":"PS3","psn_id":"NP1",
                                   "trophies_cached_at":None,"psn_confirmed":False}
        cur.fetchall.return_value=[]
        with patch("src.api.routes.trophies.get_conn") as context,patch("src.api.routes.trophies._fetch_and_cache_psn") as fetch:
            context.return_value.__enter__.return_value=conn
            with self.assertRaises(HTTPException) as error:
                get_trophies(1)
            self.assertEqual(error.exception.status_code,409)
            fetch.assert_not_called()

    def test_sync_preserves_manual_overrides_and_reconciles_same_transaction(self):
        conn=MagicMock()
        cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect=[{"psn_id":"NP1"},{"id":2},{"id":3}]
        with patch("src.api.routes.sync.auto_update_status") as reconcile:
            _upsert_trophies(1,[{"psn_trophy_id":"0","name":"Platinum","trophy_type":"platinum","earned":True}],conn)
        reconcile.assert_called_once_with(1,conn=conn)
        sql=" ".join(call.args[0] for call in cur.execute.call_args_list)
        self.assertIn("WHERE NOT user_trophies.manual_override",sql)
        self.assertNotIn("UPDATE user_games",sql)

    def test_manual_earn_and_unearn_reconcile_before_commit(self):
        for operation in (lambda:earn_trophy(9,TrophyEarn(notes="test")),lambda:unearn_trophy(9)):
            conn=MagicMock()
            cur=conn.cursor.return_value.__enter__.return_value
            cur.fetchone.return_value={"game_id":1}
            with patch("src.api.routes.trophies.get_conn") as context,patch("src.api.routes.trophies.auto_update_status") as reconcile:
                context.return_value.__enter__.return_value=conn
                operation()
                reconcile.assert_called_once_with(1,conn=conn)


if __name__ == "__main__":
    unittest.main()
