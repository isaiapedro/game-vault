import os
from typing import Optional
from psnawp_api import PSNAWP
from psnawp_api.models.trophies.trophy_constants import PlatformType, TrophyType


def _get_psnawp() -> Optional[PSNAWP]:
    npsso = os.environ.get("PSN_NPSSO")
    if not npsso:
        return None
    return PSNAWP(npsso)


def _platform_for_game(platform: str) -> list:
    mapping = {
        "PS3": [PlatformType.PS3],
        "PS4": [PlatformType.PS4],
        "PS5": [PlatformType.PS5],
        "PSVITA": [PlatformType.PS_VITA],
    }
    if platform.upper() not in mapping:
        raise ValueError("Unsupported PSN release platform")
    return mapping[platform.upper()]


def get_all_trophy_titles() -> list[dict]:
    psnawp = _get_psnawp()
    if not psnawp:
        return []
    try:
        me = psnawp.me()
        results = []
        for title in me.trophy_titles(limit=None):
            earned = title.earned_trophies
            defined = title.defined_trophies
            results.append({
                "np_communication_id": title.np_communication_id,
                "title_name": title.title_name,
                "platforms": [getattr(p, "value", str(p)) for p in getattr(title, "title_platform", [])],
                "progress": title.progress,
                "title_icon_url": title.title_icon_url,
                "earned_bronze": earned.bronze if earned else 0,
                "earned_silver": earned.silver if earned else 0,
                "earned_gold": earned.gold if earned else 0,
                "earned_platinum": earned.platinum if earned else 0,
                "total_bronze": defined.bronze if defined else 0,
                "total_silver": defined.silver if defined else 0,
                "total_gold": defined.gold if defined else 0,
                "total_platinum": defined.platinum if defined else 0,
            })
        return results
    except Exception as e:
        raise RuntimeError(f"PSN API error: {e}") from e


def get_trophies_for_game(np_communication_id: str, platform: str = "PS3") -> list[dict]:
    psnawp = _get_psnawp()
    if not psnawp:
        return []
    try:
        me = psnawp.me()
        platforms = _platform_for_game(platform)
        trophies = []

        for p in platforms:
            try:
                for trophy in me.trophies(
                    np_communication_id=np_communication_id,
                    platform=p,
                    include_progress=True,
                    trophy_group_id="all",
                ):
                    t_type = "bronze"
                    if trophy.trophy_type == TrophyType.PLATINUM:
                        t_type = "platinum"
                    elif trophy.trophy_type == TrophyType.GOLD:
                        t_type = "gold"
                    elif trophy.trophy_type == TrophyType.SILVER:
                        t_type = "silver"

                    earned_at = None
                    if hasattr(trophy, "earned_date_time") and trophy.earned_date_time:
                        earned_at = trophy.earned_date_time.isoformat()

                    rarity = None
                    if hasattr(trophy, "trophy_earn_rate") and trophy.trophy_earn_rate is not None:
                        rarity = float(trophy.trophy_earn_rate)

                    trophies.append({
                        "psn_trophy_id": str(trophy.trophy_id),
                        "name": trophy.trophy_name or "Unknown",
                        "description": trophy.trophy_detail,
                        "trophy_type": t_type,
                        "trophy_image_url": trophy.trophy_icon_url,
                        "earned": getattr(trophy, "earned", None),
                        "earned_at": earned_at,
                        "rarity_percentage": rarity,
                        "group_id": str(getattr(trophy, "trophy_group_id", None) or "default"),
                        "is_hidden": bool(getattr(trophy, "trophy_hidden", False)),
                    })
                break
            except Exception as error:
                # Never cache a partially consumed page stream as a complete trophy set.
                raise RuntimeError("PSN trophy request failed") from error

        return trophies
    except Exception as e:
        raise RuntimeError(f"PSN API error fetching trophies: {e}") from e


def is_configured() -> bool:
    return bool(os.environ.get("PSN_NPSSO"))
