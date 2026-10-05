"""Readable labels for confirmed releases without changing provider identities."""

import re


def display_title(local_title: str, provider_title: str) -> str:
    local = " ".join(local_title.split())
    provider = " ".join(provider_title.split())
    if not provider:
        return local
    # The IGDB North-American FIFA names are less familiar than the local labels.
    if re.fullmatch(r"FIFA\s+\d{2}", local, re.IGNORECASE) and re.fullmatch(
        r"FIFA Soccer\s+\d{2}", provider, re.IGNORECASE
    ):
        return local
    # A per-game HD edition must not lose its edition marker merely because
    # the provider's record uses the original game's shorter name.
    if re.search(r"\bHD\b", local, re.IGNORECASE) and not re.search(
        r"\bHD\b", provider, re.IGNORECASE
    ):
        return local
    return provider
