from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from scripts.prepare_prices import add_offer
from src.api.price_offers import PriceOfferError, project_price_offers
from src.api.static_snapshot import content_sha256


def offer(observed_at, availability="available"):
    return {
        "game_id": 1, "source": "Mercado Livre", "listing_id": "listing-1",
        "url": "https://produto.mercadolivre.com.br/listing-1", "title": "Exact PS3 game",
        "edition": "standard", "platform": "PS3", "region": "BR",
        "format": "physical", "condition": "used", "seller": "Example seller",
        "currency": "BRL", "item_price": 50, "shipping_price": None,
        "availability": availability, "observed_at": observed_at.isoformat(),
        "review_status": "confirmed",
    }


class PriceOfferTests(unittest.TestCase):
    def test_stale_offer_is_not_projected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.json"
            path.write_text(json.dumps({"version": 1, "observations": [
                offer(datetime.now(timezone.utc) - timedelta(days=31))]}))
            self.assertIsNone(project_price_offers(path, [{"id": 1, "platform": "PS3"}])[1]["mercado_livre"])

    def test_unavailable_observation_suppresses_same_listing(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.json"
            path.write_text(json.dumps({"version": 1, "observations": [
                offer(now - timedelta(days=1)), offer(now, "unavailable")]}))
            self.assertIsNone(project_price_offers(path, [{"id": 1, "platform": "PS3"}])[1]["mercado_livre"])

    def test_new_and_used_compete_in_one_mercado_livre_slot(self):
        now = datetime.now(timezone.utc)
        used = offer(now)
        new = {**offer(now), "listing_id": "listing-2", "condition": "new", "item_price": 40}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.json"
            path.write_text(json.dumps({"version": 1, "observations": [used, new]}))
            projected = project_price_offers(path, [{"id": 1, "platform": "PS3"}])[1]
            self.assertEqual(set(projected), {"mercado_livre", "ps3_store"})
            self.assertEqual(projected["mercado_livre"]["condition"], "new")

    def test_manual_console_offer_has_no_web_url(self):
        now = datetime.now(timezone.utc)
        digital = offer(now)
        digital.update(source="PS Store Brazil", url=None, format="digital",
                       condition="new", observation_method="manual_console")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.json"
            path.write_text(json.dumps({"version": 1, "observations": [digital]}))
            projected = project_price_offers(path, [{"id": 1, "platform": "PS3"}])
            self.assertIsNone(projected[1]["ps3_store"]["url"])

    def test_cli_requires_exact_confirmation_and_keeps_private_file(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path = root / "snapshot.json"
            payload = {"snapshot_version": 1, "captured_at": now.isoformat(),
                       "games": [{"id": 1}], "backlog": {"entries": []},
                       "wishlist": [{"id": 1, "platform": "PS3"}],
                       "statistics": {}, "trophies": {}}
            payload["content_sha256"] = content_sha256(payload)
            snapshot_path.write_text(json.dumps(payload))
            input_path = root / "input.json"
            input_path.write_text(json.dumps(offer(now, "unavailable")))
            # The command confines its store to the service's ignored .local directory.
            with self.assertRaises(PriceOfferError):
                add_offer(input_path, snapshot_path, root / "prices.json", "Exact PS3 game", "PS3")
            # The explicit title check happens before an observation can be appended.
            from unittest.mock import patch
            with patch("scripts.prepare_prices.PROJECT_ROOT", root):
                store = root / ".local" / "price-observations.json"
                with self.assertRaises(PriceOfferError):
                    add_offer(input_path, snapshot_path, store, "Another game", "PS3")
                add_offer(input_path, snapshot_path, store, "Exact PS3 game", "PS3")
                self.assertEqual(json.loads(store.read_text())["observations"][0]["availability"], "unavailable")


if __name__ == "__main__":
    unittest.main()
