"""Publish reviewed private prices into the existing snapshot without PostgreSQL.

This command performs no network requests. Restart the static service after it succeeds.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from src.api.price_offers import DEFAULT_OFFER_PATH, project_price_offers
from src.api.static_snapshot import SNAPSHOT_VERSION, content_sha256, load_static_snapshot, validate_static_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = PROJECT_ROOT / ".local" / "game-vault-snapshot.json"


def refresh_price_snapshot(snapshot_path: Path = DEFAULT_SNAPSHOT,
                           offers_path: Path = DEFAULT_OFFER_PATH) -> dict:
    snapshot = load_static_snapshot(snapshot_path)
    payload = json.loads(json.dumps(snapshot.payload))
    wishlist = payload["wishlist"]
    projected = project_price_offers(offers_path, wishlist)
    for game in wishlist:
        game["price_offers"] = projected[int(game["id"])]
    payload["snapshot_version"] = SNAPSHOT_VERSION
    payload["prices_projected_at"] = datetime.now(timezone.utc).isoformat()
    payload["content_sha256"] = content_sha256(payload)
    validate_static_snapshot(payload)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=snapshot_path.parent,
        prefix=f".{snapshot_path.name}.", delete=False,
    ) as temporary:
        json.dump(payload, temporary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(snapshot_path)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--offers-file", type=Path, default=DEFAULT_OFFER_PATH)
    args = parser.parse_args()
    payload = refresh_price_snapshot(args.snapshot, args.offers_file)
    print(f"Published price states for {len(payload['wishlist'])} wishlist games into {args.snapshot}")


if __name__ == "__main__":
    main()
