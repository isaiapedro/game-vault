import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from scripts import prepare_coverage as coverage
from src.api.integrations import igdb_client
from src.api.utils.display_metadata import display_title


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.game = {
            "id": 1, "title": "PSN Name", "platform": "PS3", "ownership": "owned",
            "specifications": {"catalog_title_before_psn": "Catalog Name"},
            "provider_mappings": [], "psn_id": None,
        }

    def test_inventory_marks_unknown_fields_without_inventing_facts(self):
        report = coverage.inventory({"captured_at": "2026-09-27", "games": [self.game], "trophies": {"1": []}})
        row = report["games"][0]
        self.assertEqual(row["search_titles"], ["PSN Name", "Catalog Name"])
        self.assertEqual(row["status"]["trophy_details"], "missing")
        self.assertEqual(row["status"]["metadata_identity"], "missing")
        self.assertEqual(row["price_readiness"]["offer_status"], "not_configured")

    def test_guide_url_restricts_host_and_route(self):
        self.assertTrue(coverage.valid_guide_url("https://psnprofiles.com/guide/example"))
        self.assertTrue(coverage.valid_guide_url("https://www.playstationtrophies.org/game/example/guide/"))
        self.assertFalse(coverage.valid_guide_url("https://psnprofiles.com.evil.test/guide/example"))
        self.assertFalse(coverage.valid_guide_url("http://psnprofiles.com/guide/example"))
        self.assertFalse(coverage.valid_guide_url("https://psnprofiles.com/user/example"))

    def test_display_title_uses_recognizable_release_without_erasing_edition(self):
        self.assertEqual(display_title("God of War Trophies", "God of War"), "God of War")
        self.assertEqual(display_title("FIFA 13", "FIFA Soccer 13"), "FIFA 13")
        self.assertEqual(display_title("Devil May Cry 2 HD", "Devil May Cry 2"), "Devil May Cry 2 HD")
        self.assertEqual(display_title("METAL GEAR RISING: REVENGEANCE", "Metal Gear Rising: Revengeance"),
                         "Metal Gear Rising: Revengeance")

    def test_igdb_alternative_names_and_edition_are_exposed(self):
        rows = igdb_client._normalize_results([{
            "id": 12, "name": "New Name", "alternative_names": [{"name": "Old Name"}],
            "version_parent": 10, "category": 8, "platforms": [{"name": "PlayStation 3"}],
        }])
        self.assertEqual(rows[0]["specifications"]["alternative_names"], ["Old Name"])
        self.assertEqual(rows[0]["specifications"]["version_parent"], 10)

    def test_igdb_user_rating_is_separate_from_critic_rating(self):
        row = igdb_client._normalize_results([{"id": 12, "name": "Example", "rating": 83.4,
            "rating_count": 25, "aggregated_rating": 71.2}])[0]
        self.assertEqual(row["specifications"]["igdb_user_rating"], 83.4)
        self.assertEqual(row["specifications"]["igdb_user_rating_count"], 25)
        self.assertNotIn("aggregated_rating", row["specifications"])

    def test_exact_igdb_match_considers_all_searched_titles(self):
        entry = {"searched": ["Jak II", "Jak 2"], "candidates": [
            {"igdb_id": 12, "title": "Jak II", "alternative_names": [], "exact_name_or_alias": False}]}
        self.assertEqual([item["igdb_id"] for item in coverage.exact_igdb_candidates(entry)], [12])

    def test_explicit_igdb_selection_requires_saved_candidate_and_unique_id(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            path.write_text(json.dumps({"games": [
                {"game_id": 1, "candidates": [{"igdb_id": 12}], "selected_igdb_id": None},
                {"game_id": 2, "candidates": [{"igdb_id": 12}], "selected_igdb_id": None},
            ]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                coverage.select_reviewed_igdb_ids(path, "1:13")
            with self.assertRaises(ValueError):
                coverage.select_reviewed_igdb_ids(path, "1:12,2:12")
            self.assertEqual(coverage.select_reviewed_igdb_ids(path, "1:12"), 1)
            self.assertEqual(json.loads(path.read_text())["games"][0]["selected_igdb_id"], 12)


class CandidateTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmed_id_score_lookup_preserves_missing_ratings(self):
        from unittest.mock import MagicMock

        response = MagicMock()
        response.json.return_value = [{"id": 12, "rating": 88.5, "rating_count": 4}, {"id": 13}]
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        with patch.object(igdb_client, "_get_access_token", new=AsyncMock(return_value="test")), \
             patch.dict("os.environ", {"TWITCH_CLIENT_ID": "test"}), \
             patch.object(igdb_client.httpx, "AsyncClient", return_value=client):
            scores = await igdb_client.get_game_scores_by_ids([13, 12, 12])
        self.assertEqual(scores[12]["igdb_user_rating"], 88.5)
        self.assertIsNone(scores[13]["igdb_user_rating"])
        self.assertIn("where id = (12,13)", client.post.await_args.kwargs["content"])

    async def test_artwork_lookup_only_keeps_landscape_images(self):
        from unittest.mock import MagicMock

        response = MagicMock()
        response.json.return_value = [{"id": 12, "screenshots": [
            {"image_id": "wide1", "width": 1920, "height": 1080},
            {"image_id": "portrait", "width": 500, "height": 900}],
            "artworks": [{"image_id": "wide2", "width": 1280, "height": 720}]}]
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        with patch.object(igdb_client, "_get_access_token", new=AsyncMock(return_value="test")), \
             patch.dict("os.environ", {"TWITCH_CLIENT_ID": "test"}), \
             patch.object(igdb_client.httpx, "AsyncClient", return_value=client):
            art = await igdb_client.get_game_artwork_by_ids([12])
        self.assertEqual(len(art[12]), 2)
        self.assertTrue(art[12][0].endswith("/wide1.jpg"))
        self.assertTrue(art[12][1].endswith("/wide2.jpg"))

    async def test_igdb_exact_alternative_name_finds_current_title(self):
        from unittest.mock import MagicMock

        responses = []
        for payload in ([], [{"game": 12, "name": "Old Name"}],
                        [{"id": 12, "name": "New Name", "platforms": [{"name": "PlayStation 3"}]}]):
            response = MagicMock()
            response.json.return_value = payload
            responses.append(response)
        client = MagicMock()
        client.post = AsyncMock(side_effect=responses)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        with patch.object(igdb_client, "_get_access_token", new=AsyncMock(return_value="test")), \
             patch.dict("os.environ", {"TWITCH_CLIENT_ID": "test"}), \
             patch.object(igdb_client.httpx, "AsyncClient", return_value=client), \
             patch.object(igdb_client.asyncio, "sleep", new=AsyncMock()):
            results = await igdb_client.search_games("Old Name")
        self.assertEqual(results[0]["igdb_id"], 12)
        self.assertEqual(client.post.await_count, 3)

    async def test_candidates_are_preview_only_and_platform_scoped(self):
        row = {"game_id": 1, "title": "PSN Name", "platform": "PS3",
               "search_titles": ["PSN Name", "Catalog Name"], "igdb_id": None}
        candidate = {"igdb_id": 12, "title": "PSN Name", "specifications": {"platforms": ["PlayStation 3"],
                     "alternative_names": ["Catalog Name"], "version_parent": None, "category": 0}}
        wrong = {"igdb_id": 13, "title": "PSN Name", "specifications": {"platforms": ["PlayStation 4"]}}
        with patch.dict("os.environ", {"TWITCH_CLIENT_ID": "test", "TWITCH_CLIENT_SECRET": "test"}), \
             patch.object(igdb_client, "search_games", new=AsyncMock(return_value=[candidate, wrong])), \
             patch.object(coverage.asyncio, "sleep", new=AsyncMock()):
            result = await coverage.igdb_candidates([row])
        entry = result["games"][0]
        self.assertEqual(len(entry["candidates"]), 1)
        self.assertEqual(entry["candidates"][0]["igdb_id"], 12)
        self.assertIsNone(entry["selected_igdb_id"])


if __name__ == "__main__":
    unittest.main()
