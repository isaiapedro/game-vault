"""Add a manually reviewed price observation to the private authoring file.

Example: python -m scripts.prepare_prices add --input .local/reviewed-offer.json
         --confirm-title 'Exact listing title' --confirm-platform PS3
The input is a single JSON object with every price_offers.validate_offer field.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from src.api.price_offers import DEFAULT_OFFER_PATH, PriceOfferError, validate_offer
from src.api.static_snapshot import load_static_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = PROJECT_ROOT / ".local" / "game-vault-snapshot.json"


def add_offer(input_path: Path, snapshot_path: Path, store_path: Path,
              confirm_title: str, confirm_platform: str) -> None:
    if store_path.resolve().parent != (PROJECT_ROOT / ".local").resolve():
        raise PriceOfferError("offer_store_must_be_under_local")
    snapshot = load_static_snapshot(snapshot_path)
    wishlist = {game["id"]: game for game in snapshot.payload["wishlist"]}
    offer = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(offer, dict) or offer.get("title") != confirm_title or offer.get("platform") != confirm_platform:
        raise PriceOfferError("exact_listing_confirmation_mismatch")
    validate_offer(offer, wishlist, allow_unavailable=True)
    if store_path.exists():
        data = json.loads(store_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("observations"), list):
            raise PriceOfferError("offer_file_invalid")
    else:
        data = {"version": 1, "observations": []}
    data["observations"].append(offer)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".price-observations-", suffix=".json", dir=store_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, store_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("add",))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--store", type=Path, default=DEFAULT_OFFER_PATH)
    parser.add_argument("--confirm-title", required=True)
    parser.add_argument("--confirm-platform", required=True)
    args = parser.parse_args()
    try:
        add_offer(args.input, args.snapshot, args.store, args.confirm_title, args.confirm_platform)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(f"Saved reviewed observation to {args.store}")


if __name__ == "__main__":
    main()
