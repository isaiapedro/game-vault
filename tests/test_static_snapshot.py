import json
from pathlib import Path
import tempfile
import unittest

from src.api.static_snapshot import (
    SNAPSHOT_VERSION,
    StaticSnapshotError,
    content_sha256,
    load_static_snapshot,
    validate_static_snapshot,
)
from scripts.export_static_snapshot import cached_cover, cache_artwork, replace_artwork_urls
from scripts.refresh_price_snapshot import refresh_price_snapshot


def valid_payload():
    payload = {
        "snapshot_version": SNAPSHOT_VERSION,
        "captured_at": "2026-09-27T12:00:00+00:00",
        "psn_observed_at": "2026-09-27T11:00:00+00:00",
        "games": [{"id": 7, "title": "Example", "platform": "PS3"}],
        "backlog": {"entries": [{"game_id": 7}]},
        "wishlist": [{"id": 7, "platform": "PS3", "price_offers": {
            "mercado_livre": None, "ps3_store": None,
        }}],
        "statistics": {"library": {"total_count": 1}},
        "trophies": {"7": []},
    }
    payload["content_sha256"] = content_sha256(payload)
    return payload


class StaticSnapshotTests(unittest.TestCase):
    def test_existing_cover_survives_data_only_export(self):
        with tempfile.TemporaryDirectory() as directory:
            cover = Path(directory) / "7.jpg"
            cover.write_bytes(b"cached")
            self.assertEqual(cached_cover({"id": 7}, Path(directory)), "/covers/7.jpg")
            (Path(directory) / "igdb-7.jpg").write_bytes(b"portrait")
            self.assertEqual(cached_cover({"id": 7}, Path(directory)), "/covers/igdb-7.jpg")

    def test_artwork_snapshot_only_exposes_cached_same_origin_images(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "7-1.jpg").write_bytes(b"cached")
            game = {"id": 7, "specifications": {"igdb_artwork_urls": [
                "https://images.igdb.com/igdb/image/upload/t_screenshot_big/valid123.jpg",
                "https://invalid.example/unsafe.jpg"]}}
            local = cache_artwork(game, folder, False)
            self.assertEqual(local, ["/artwork/7-1.jpg"])
            replace_artwork_urls(game, {7: local})
            self.assertEqual(game["specifications"]["igdb_artwork_urls"], local)

    def test_valid_snapshot_is_loaded_and_indexed(self):
        snapshot = validate_static_snapshot(valid_payload())
        self.assertEqual(snapshot.games_by_id[7]["title"], "Example")
        self.assertEqual(snapshot.captured_at, "2026-09-27T12:00:00+00:00")

    def test_existing_version_one_snapshot_remains_readable(self):
        payload = valid_payload()
        payload["snapshot_version"] = 1
        del payload["wishlist"][0]["price_offers"]
        payload["content_sha256"] = content_sha256(payload)
        self.assertEqual(validate_static_snapshot(payload).games_by_id[7]["title"], "Example")

    def test_existing_version_two_snapshot_remains_readable(self):
        payload = valid_payload()
        payload["snapshot_version"] = 2
        payload["wishlist"][0]["price_offers"] = {"physical_new": None, "physical_used": None, "ps3_store": None}
        payload["content_sha256"] = content_sha256(payload)
        self.assertEqual(validate_static_snapshot(payload).games_by_id[7]["title"], "Example")

    def test_price_refresh_upgrades_existing_snapshot_without_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "snapshot.json"
            payload = valid_payload()
            payload["snapshot_version"] = 1
            del payload["wishlist"][0]["price_offers"]
            payload["content_sha256"] = content_sha256(payload)
            path.write_text(json.dumps(payload), encoding="utf-8")
            refreshed = refresh_price_snapshot(path, root / "missing-prices.json")
            self.assertEqual(refreshed["snapshot_version"], SNAPSHOT_VERSION)
            self.assertEqual(refreshed["wishlist"][0]["price_offers"], {
                "mercado_livre": None, "ps3_store": None,
            })
            self.assertEqual(load_static_snapshot(path).payload["captured_at"], payload["captured_at"])

    def test_changed_content_is_rejected(self):
        payload = valid_payload()
        payload["games"][0]["title"] = "Changed"
        with self.assertRaisesRegex(StaticSnapshotError, "snapshot_checksum_mismatch"):
            validate_static_snapshot(payload)

    def test_unknown_backlog_reference_is_rejected(self):
        payload = valid_payload()
        payload["backlog"]["entries"][0]["game_id"] = 99
        payload["content_sha256"] = content_sha256(payload)
        with self.assertRaisesRegex(StaticSnapshotError, "snapshot_backlog_game_unknown"):
            validate_static_snapshot(payload)

    def test_wishlist_requires_explicit_price_states(self):
        payload = valid_payload()
        del payload["wishlist"][0]["price_offers"]
        payload["content_sha256"] = content_sha256(payload)
        with self.assertRaisesRegex(StaticSnapshotError, "snapshot_price_offers_required"):
            validate_static_snapshot(payload)

    def test_file_loader_rejects_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaisesRegex(StaticSnapshotError, "snapshot_not_readable"):
                load_static_snapshot(path)


if __name__ == "__main__":
    unittest.main()
