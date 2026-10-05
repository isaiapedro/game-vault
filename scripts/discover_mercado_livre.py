"""Find Mercado Livre listing candidates for explicitly supplied public game titles.

This report is for human review only. It never writes the reviewed offer store or
the published snapshot. Provide titles with repeated --title arguments.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DIR = PROJECT_ROOT / ".local"
API_URL = "https://api.mercadolibre.com/sites/MLB/search"


def discover(titles: list[str], token: str, *, limit: int = 10, delay: float = 1.2,
             opener=urlopen, sleeper=time.sleep) -> dict:
    if not token.strip():
        raise ValueError("MERCADO_LIVRE_ACCESS_TOKEN is required")
    if not titles or any(not title.strip() for title in titles):
        raise ValueError("Supply at least one nonempty --title")
    if len(titles) > 100 or not 1 <= limit <= 50 or delay < 1:
        raise ValueError("At most 100 titles, limit 1–50, and delay at least 1 second are required")
    entries = []
    for index, title in enumerate(titles):
        if index:
            sleeper(delay)
        query = f"{title.strip()} PlayStation 3"
        request = Request(
            f"{API_URL}?{urlencode({'q': query, 'limit': limit})}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        entry = {"title": title.strip(), "source": "mercado_livre", "candidates": [], "error": None}
        try:
            with opener(request, timeout=15) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                raise ValueError("invalid_response")
            for result in payload["results"][:limit]:
                if not isinstance(result, dict):
                    continue
                listing_title = result.get("title")
                entry["candidates"].append({
                    "id": result.get("id"),
                    "title": listing_title,
                    "price": result.get("price"),
                    "currency_id": result.get("currency_id"),
                    "permalink": result.get("permalink"),
                    "condition": result.get("condition"),
                    "platform_mentioned": isinstance(listing_title, str) and any(
                        marker in listing_title.casefold() for marker in ("ps3", "playstation 3")
                    ),
                })
        except HTTPError as error:
            entry["error"] = f"http_{error.code}"
        except URLError:
            entry["error"] = "connection_error"
        except (OSError, ValueError, json.JSONDecodeError):
            entry["error"] = "invalid_response"
        entries.append(entry)
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "mercado_livre",
        "status": "unreviewed_candidates",
        "entries": entries,
    }


def write_report(report: dict, output: Path) -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    if output.resolve().parent != LOCAL_DIR.resolve():
        raise ValueError("Report must be a direct child of services/game-vault/.local")
    descriptor, temp_name = tempfile.mkstemp(prefix=".ml-candidates-", suffix=".json", dir=LOCAL_DIR)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, output)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", action="append", required=True, help="Public game title; repeat for more titles")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--delay", type=float, default=1.2)
    parser.add_argument("--output", type=Path, default=LOCAL_DIR / "mercado-livre-candidates.json")
    args = parser.parse_args()
    try:
        report = discover(args.title, os.getenv("MERCADO_LIVRE_ACCESS_TOKEN", ""),
                          limit=args.limit, delay=args.delay)
        write_report(report, args.output)
    except ValueError as error:
        parser.error(str(error))
    print(f"Saved unreviewed candidates to {args.output}")


if __name__ == "__main__":
    main()
