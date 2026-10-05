"""Private, manually reviewed wishlist offer observations.

This module performs no network access. The authoring file is deliberately kept
under .local and only the small, validated projection reaches a release snapshot.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from urllib.parse import urlsplit


DEFAULT_OFFER_PATH = Path(__file__).resolve().parents[2] / ".local" / "price-observations.json"
SLOTS = ("mercado_livre", "ps3_store")
MAX_AGE = timedelta(days=30)
PUBLIC_FIELDS = ("source", "listing_id", "url", "title", "edition", "platform", "region",
                 "format", "condition", "seller", "currency", "item_price", "shipping_price",
                 "availability", "observed_at")


class PriceOfferError(ValueError):
    """A private observation cannot safely be published in a snapshot."""


def _money(value: object, field: str, *, optional: bool = False) -> float | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise PriceOfferError(f"{field}_invalid")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise PriceOfferError(f"{field}_invalid") from error
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise PriceOfferError(f"{field}_invalid")
    return float(amount)


def validate_offer(offer: dict, wishlist_by_id: dict[int, dict], *, allow_unavailable: bool = False) -> dict:
    if not isinstance(offer, dict):
        raise PriceOfferError("offer_must_be_object")
    game_id = offer.get("game_id")
    if isinstance(game_id, bool) or not isinstance(game_id, int) or game_id not in wishlist_by_id:
        raise PriceOfferError("offer_game_not_in_wishlist")
    game = wishlist_by_id[game_id]
    platform = game.get("platform")
    if offer.get("platform") != platform:
        raise PriceOfferError("offer_platform_mismatch")
    if offer.get("review_status") != "confirmed":
        raise PriceOfferError("offer_not_confirmed")
    if offer.get("availability") not in (("available", "unavailable") if allow_unavailable else ("available",)):
        raise PriceOfferError("offer_not_available")
    for field in ("source", "listing_id", "title", "edition", "region", "seller"):
        if not isinstance(offer.get(field), str) or not offer[field].strip():
            raise PriceOfferError(f"{field}_required")
    if offer.get("currency") != "BRL" or offer.get("region") != "BR":
        raise PriceOfferError("offer_must_be_brazilian_brl")
    if offer.get("format") == "physical":
        if offer.get("condition") not in ("new", "used"):
            raise PriceOfferError("physical_condition_invalid")
        if offer.get("source") != "Mercado Livre":
            raise PriceOfferError("physical_source_must_be_mercado_livre")
        slot = "mercado_livre"
    elif offer.get("format") == "digital" and platform == "PS3" and offer.get("source") == "PS Store Brazil":
        if offer.get("condition") != "new" or offer.get("observation_method") != "manual_console":
            raise PriceOfferError("ps3_store_requires_manual_console_observation")
        slot = "ps3_store"
    else:
        raise PriceOfferError("offer_format_or_source_invalid")
    url = offer.get("url")
    if url is not None:
        parts = urlsplit(url if isinstance(url, str) else "")
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise PriceOfferError("offer_url_must_be_https")
    elif slot != "ps3_store":
        raise PriceOfferError("physical_offer_url_required")
    if slot == "mercado_livre" and not (parts.hostname == "mercadolivre.com.br" or parts.hostname.endswith(".mercadolivre.com.br")):
        raise PriceOfferError("physical_url_must_be_mercado_livre")
    observed = offer.get("observed_at")
    if not isinstance(observed, str):
        raise PriceOfferError("observed_at_invalid")
    try:
        instant = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError as error:
        raise PriceOfferError("observed_at_invalid") from error
    if instant.tzinfo is None or instant > datetime.now(timezone.utc):
        raise PriceOfferError("observed_at_invalid")
    item = _money(offer.get("item_price"), "item_price")
    shipping = _money(offer.get("shipping_price"), "shipping_price", optional=True)
    public = {field: offer[field] for field in PUBLIC_FIELDS}
    public["item_price"] = item
    public["shipping_price"] = shipping
    public["price_basis"] = "delivered_total" if shipping is not None else "item_only"
    public["delivered_total"] = round(item + shipping, 2) if shipping is not None else None
    return {"game_id": game_id, "slot": slot,
            "offer": public if offer["availability"] == "available" else None}


def project_price_offers(path: Path, wishlist: list[dict]) -> dict[int, dict]:
    """Project current confirmed offers; missing authoring file means explicit absence.

    The file retains prior observations. For each game and slot, the latest
    observation wins; stale or unavailable latest observations suppress an old
    listing rather than making it appear current.
    """
    wishlist_by_id = {game["id"]: game for game in wishlist}
    result = {game_id: {slot: None for slot in SLOTS} for game_id in wishlist_by_id}
    if not path.exists():
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PriceOfferError("offer_file_unreadable") from error
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("observations"), list):
        raise PriceOfferError("offer_file_invalid")
    seen: dict[tuple[int, str, str, str], tuple[datetime, dict | None]] = {}
    for raw in data["observations"]:
        if not isinstance(raw, dict):
            raise PriceOfferError("offer_must_be_object")
        validated = validate_offer(raw, wishlist_by_id, allow_unavailable=True)
        game_id, slot, public = validated["game_id"], validated["slot"], validated["offer"]
        stamp = raw.get("observed_at")
        if not isinstance(stamp, str):
            raise PriceOfferError("observed_at_invalid")
        try:
            instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise PriceOfferError("observed_at_invalid") from error
        if instant.tzinfo is None or instant > datetime.now(timezone.utc):
            raise PriceOfferError("observed_at_invalid")
        key = (game_id, slot, str(raw.get("source")), str(raw.get("listing_id")))
        if key not in seen or instant > seen[key][0]:
            seen[key] = (instant, public)
    for (game_id, slot, _, _), (instant, public) in seen.items():
        if public is None or datetime.now(timezone.utc) - instant > MAX_AGE:
            continue
        incumbent = result[game_id][slot]
        cost = public["delivered_total"] if public["delivered_total"] is not None else public["item_price"]
        old_cost = (incumbent["delivered_total"] if incumbent["delivered_total"] is not None
                    else incumbent["item_price"]) if incumbent else None
        if (incumbent is None or
                (public["price_basis"] == "delivered_total" and incumbent["price_basis"] == "item_only") or
                (public["price_basis"] == incumbent["price_basis"] and cost < old_cost)):
            result[game_id][slot] = public
    return result
