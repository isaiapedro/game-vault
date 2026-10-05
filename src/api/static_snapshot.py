"""Validated, immutable runtime snapshot for Game Vault.

The snapshot is produced deliberately from the private PostgreSQL workspace.
Normal application startup only reads this file and never opens a database or
contacts a metadata/trophy provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


SNAPSHOT_VERSION = 3


class StaticSnapshotError(ValueError):
    """The release snapshot is missing or violates its fixed-data contract."""


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "content_sha256"}
    return json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def content_sha256(payload: dict[str, Any]) -> str:
    return sha256(_canonical_payload(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class StaticSnapshot:
    payload: dict[str, Any]

    @property
    def games(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.payload["games"])

    @property
    def games_by_id(self) -> dict[int, dict[str, Any]]:
        return {int(game["id"]): game for game in self.games}

    @property
    def captured_at(self) -> str:
        return str(self.payload["captured_at"])


def validate_static_snapshot(payload: dict[str, Any]) -> StaticSnapshot:
    version = payload.get("snapshot_version")
    if version not in (1, 2, SNAPSHOT_VERSION):
        raise StaticSnapshotError("unsupported_snapshot_version")
    if not isinstance(payload.get("captured_at"), str) or not payload["captured_at"]:
        raise StaticSnapshotError("snapshot_capture_time_required")
    games = payload.get("games")
    if not isinstance(games, list) or not games:
        raise StaticSnapshotError("snapshot_games_required")
    ids = [game.get("id") for game in games if isinstance(game, dict)]
    if len(ids) != len(games) or any(not isinstance(game_id, int) for game_id in ids):
        raise StaticSnapshotError("snapshot_game_ids_invalid")
    if len(set(ids)) != len(ids):
        raise StaticSnapshotError("snapshot_game_ids_must_be_unique")

    game_ids = set(ids)
    backlog = payload.get("backlog")
    if not isinstance(backlog, dict) or not isinstance(backlog.get("entries"), list):
        raise StaticSnapshotError("snapshot_backlog_required")
    if any(entry.get("game_id") not in game_ids for entry in backlog["entries"]):
        raise StaticSnapshotError("snapshot_backlog_game_unknown")
    wishlist = payload.get("wishlist")
    if not isinstance(wishlist, list) or any(
        not isinstance(game, dict) or game.get("id") not in game_ids for game in wishlist
    ):
        raise StaticSnapshotError("snapshot_wishlist_game_unknown")
    for game in wishlist:
        if version == 1 and "price_offers" not in game:
            continue
        offers = game.get("price_offers")
        expected_slots = {"mercado_livre", "ps3_store"} if version == 3 else {"physical_new", "physical_used", "ps3_store"}
        if not isinstance(offers, dict) or set(offers) != expected_slots:
            raise StaticSnapshotError("snapshot_price_offers_required")
        for kind, offer in offers.items():
            if offer is None:
                continue
            if not isinstance(offer, dict):
                raise StaticSnapshotError("snapshot_price_offer_invalid")
            required = {"source", "listing_id", "url", "title", "edition", "platform",
                        "region", "format", "condition", "seller", "currency", "item_price",
                        "shipping_price", "availability", "observed_at", "price_basis",
                        "delivered_total"}
            if not required.issubset(offer) or offer["currency"] != "BRL" or offer["platform"] != game.get("platform"):
                raise StaticSnapshotError("snapshot_price_offer_invalid")
            if kind == "ps3_store" and (offer["format"] != "digital" or offer["source"] != "PS Store Brazil"):
                raise StaticSnapshotError("snapshot_price_offer_invalid")
            if kind == "mercado_livre" and (offer["format"] != "physical" or offer["condition"] not in ("new", "used") or offer["source"] != "Mercado Livre"):
                raise StaticSnapshotError("snapshot_price_offer_invalid")
            if kind.startswith("physical_") and (offer["format"] != "physical" or offer["condition"] != kind.removeprefix("physical_")):
                raise StaticSnapshotError("snapshot_price_offer_invalid")
            if kind == "ps3_store" and offer["url"] is not None and not isinstance(offer["url"], str):
                raise StaticSnapshotError("snapshot_price_offer_invalid")
            if kind != "ps3_store" and not isinstance(offer["url"], str):
                raise StaticSnapshotError("snapshot_price_offer_invalid")
    trophies = payload.get("trophies")
    if not isinstance(trophies, dict):
        raise StaticSnapshotError("snapshot_trophies_required")
    if any(not key.isdigit() or int(key) not in game_ids for key in trophies):
        raise StaticSnapshotError("snapshot_trophy_game_unknown")
    if not isinstance(payload.get("statistics"), dict):
        raise StaticSnapshotError("snapshot_statistics_required")

    expected = payload.get("content_sha256")
    if not isinstance(expected, str) or expected != content_sha256(payload):
        raise StaticSnapshotError("snapshot_checksum_mismatch")
    return StaticSnapshot(payload=payload)


def load_static_snapshot(path: Path) -> StaticSnapshot:
    if not path.is_file():
        raise StaticSnapshotError("snapshot_not_available")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StaticSnapshotError("snapshot_not_readable") from error
    if not isinstance(payload, dict):
        raise StaticSnapshotError("snapshot_root_must_be_an_object")
    return validate_static_snapshot(payload)
