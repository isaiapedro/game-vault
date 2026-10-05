from typing import Optional
from datetime import datetime, timezone
from math import isfinite


def normalized_title(title: str) -> str:
    return " ".join(title.casefold().split())


async def get_times(title: str, aliases: tuple[str, ...] = ()) -> dict:
    from howlongtobeatpy import HowLongToBeat
    queries = list(dict.fromkeys(name.strip() for name in (title, *aliases) if name and name.strip()))
    provider = HowLongToBeat()
    results = []
    matches = {}
    matched_queries = {}
    duplicate_match = False
    for query in queries:
        found = await provider.async_search(query)
        if found is None:
            raise RuntimeError("Estimate provider request failed")
        results.extend(found)
        for candidate in found:
            if normalized_title(candidate.game_name) == normalized_title(query):
                identity = str(candidate.game_id)
                if identity in matches and query in matched_queries[identity]:
                    duplicate_match = True
                matches[identity] = candidate
                matched_queries.setdefault(identity, set()).add(query)
    result = {
        "main": None, "main_extra": None, "completionist": None,
        "complete": None, "platinum": None, "source_id": None,
        "source_title": None, "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "match_confidence": "ambiguous" if len(matches) > 1 or duplicate_match else "unmatched",
        "candidates": list({str(r.game_id): {"id": str(r.game_id), "title": r.game_name} for r in results}.values()),
    }
    if len(matches) != 1 or duplicate_match:
        return result
    best = next(iter(matches.values()))
    matched_primary = title in matched_queries[str(best.game_id)]
    result.update(main=_hours(best.main_story), main_extra=_hours(best.main_extra),
                  completionist=_hours(best.completionist), complete=_hours(best.completionist),
                  source_id=str(best.game_id), source_title=best.game_name,
                  match_confidence="exact_title" if matched_primary else "alias_needs_review")
    return result


def _hours(value) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    return round(value, 2) if isfinite(value) and value > 0 else None
