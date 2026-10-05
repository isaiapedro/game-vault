"""Conservative release-title and platform normalization for provider review."""
import re
import unicodedata
from difflib import SequenceMatcher


_PLATFORM_SUFFIX = re.compile(
    r"\s*(?:(?:[-|/·:])\s*)?(?:\((PS\s*(?:3|4|5|VITA))\)|\[(PS\s*(?:3|4|5|VITA))\]|(PS\s*(?:3|4|5|VITA)))\s*$",
    re.IGNORECASE,
)
_DECORATION = re.compile(r"[™®©]")
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def canonical_platform(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"[^A-Z0-9]", "", value.upper())
    return {"PS3": "PS3", "PS4": "PS4", "PS5": "PS5", "PSVITA": "PSVITA"}.get(compact)


def split_platform_suffix(title: str, fallback_platform: str | None = None) -> tuple[str, str | None]:
    """Split an unambiguous trailing PlayStation system label from a title."""
    # Remove presentation marks before NFKC expands them to textual TM/R tokens.
    text = unicodedata.normalize("NFKC", _DECORATION.sub("", title or "")).strip()
    match = _PLATFORM_SUFFIX.search(text)
    if not match:
        return text, canonical_platform(fallback_platform)
    platform = canonical_platform(next(group for group in match.groups() if group))
    clean_title = text[:match.start()].rstrip(" -|/·:").strip()
    return (clean_title or text), platform


def normalized_title(title: str) -> str:
    clean_title, _ = split_platform_suffix(title)
    return " ".join(_NON_WORD.sub(" ", clean_title.casefold()).split())


def same_release_title(local_game: dict, provider_title: dict) -> bool:
    provider_name, provider_suffix_platform = split_platform_suffix(provider_title.get("title_name", ""))
    provider_platforms = {
        canonical_platform(value) for value in provider_title.get("platforms", [])
    }
    provider_platforms.discard(None)
    if provider_suffix_platform:
        provider_platforms.add(provider_suffix_platform)
    local_name, local_suffix_platform = split_platform_suffix(
        local_game.get("title", ""), local_game.get("platform")
    )
    local_platform = local_suffix_platform or canonical_platform(local_game.get("platform"))
    return (
        bool(local_platform)
        and local_platform in provider_platforms
        and normalized_title(local_name) == normalized_title(provider_name)
    )


def _number_tokens(value: str) -> set[str]:
    return set(re.findall(r"\b\d+\b", value))


def release_match_score(local_game: dict, provider_title: dict) -> float:
    """Score character/token similarity only inside the same platform.

    Sequel-number disagreement is an absolute mismatch. Token containment covers
    provider prefixes/suffixes such as "Call of Duty" and "HD Edition" without
    treating neighboring numbered releases as equivalent.
    """
    provider_name, provider_suffix_platform = split_platform_suffix(provider_title.get("title_name", ""))
    provider_platforms = {canonical_platform(value) for value in provider_title.get("platforms", [])}
    provider_platforms.discard(None)
    if provider_suffix_platform:
        provider_platforms.add(provider_suffix_platform)
    local_name, local_suffix_platform = split_platform_suffix(local_game.get("title", ""), local_game.get("platform"))
    local_platform = local_suffix_platform or canonical_platform(local_game.get("platform"))
    if not local_platform or local_platform not in provider_platforms:
        return 0.0
    local = normalized_title(local_name)
    provider = normalized_title(provider_name)
    if not local or not provider or _number_tokens(local) != _number_tokens(provider):
        return 0.0
    if local == provider:
        return 1.0
    local_tokens, provider_tokens = local.split(), provider.split()
    shorter, longer = (local_tokens, provider_tokens) if len(local_tokens) <= len(provider_tokens) else (provider_tokens, local_tokens)
    contained = len(shorter) >= 2 and any(longer[i:i + len(shorter)] == shorter for i in range(len(longer) - len(shorter) + 1))
    ratio = SequenceMatcher(None, local, provider).ratio()
    if contained:
        return max(0.88, ratio)
    return ratio if ratio >= 0.86 else 0.0
