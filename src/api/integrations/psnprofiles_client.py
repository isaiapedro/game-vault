import asyncio
import re
import httpx
from bs4 import BeautifulSoup
from typing import Optional

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_DELAY = 1.0


def slug_from_title(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


async def fetch_user_games(username: str) -> list[dict]:
    results = []
    page = 1
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as client:
        while True:
            url = f"https://psnprofiles.com/{username}"
            if page > 1:
                url += f"?page={page}"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except Exception:
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("table#gamesTable tr.game") or soup.select("tr.game")
            if not rows:
                # try alternate selectors
                rows = soup.select("li.game") or soup.select("[id*='game']")

            parsed_any = False
            for row in rows:
                try:
                    entry = _parse_user_game_row(row, username)
                    if entry:
                        results.append(entry)
                        parsed_any = True
                except Exception:
                    continue

            await asyncio.sleep(REQUEST_DELAY)

            # check for next page
            next_link = soup.select_one("a[href*='page=']:last-child") or soup.select_one(".pagination .next")
            if not next_link or not parsed_any:
                break
            page += 1
            if page > 50:  # safety cap
                break

    return results


def _parse_user_game_row(row, username: str) -> Optional[dict]:
    # Try to find link with /trophies/{slug}/{username}
    slug = None
    for a in row.select("a[href]"):
        href = a.get("href", "")
        m = re.match(rf"^/trophies/([^/]+)/{re.escape(username)}", href)
        if m:
            slug = m.group(1)
            title = a.get_text(strip=True) or None
            break
        # also match /trophies/{slug} without username
        m2 = re.match(r"^/trophies/([^/]+)$", href)
        if m2:
            slug = m2.group(1)
            title_el = row.select_one(".title") or row.select_one("a.title") or a
            title = title_el.get_text(strip=True)
            break

    if not slug:
        return None

    title_el = row.select_one(".title") or row.select_one("td.game a")
    if title_el:
        title = title_el.get_text(strip=True)

    earned = 0
    total = 0
    pct = 0.0

    earned_el = row.select_one(".earned-count") or row.select_one(".trophies-earned")
    total_el = row.select_one(".total-trophies") or row.select_one(".trophies-total")
    pct_el = row.select_one(".progress-bar") or row.select_one(".completion")

    if earned_el:
        try:
            earned = int(re.sub(r"[^\d]", "", earned_el.get_text()))
        except Exception:
            pass
    if total_el:
        try:
            total = int(re.sub(r"[^\d]", "", total_el.get_text()))
        except Exception:
            pass
    if pct_el:
        try:
            pct_text = pct_el.get("data-percent") or pct_el.get_text()
            pct = float(re.sub(r"[^\d.]", "", pct_text))
        except Exception:
            pass

    return {"title": title, "slug": slug, "earned": earned, "total": total, "percent": pct}


async def fetch_trophies(slug: str) -> list[dict]:
    url = f"https://psnprofiles.com/trophies/{slug}"
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    await asyncio.sleep(REQUEST_DELAY)
    return _parse_trophy_list(resp.text)


async def fetch_guide(slug: str) -> Optional[str]:
    url = f"https://psnprofiles.com/guide/{slug}"
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
        resp = await client.get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

    await asyncio.sleep(REQUEST_DELAY)
    return _parse_guide(resp.text)


def _parse_trophy_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    trophies = []

    for row in soup.select("ul.list-trophies li"):
        name_el = row.select_one(".title")
        desc_el = row.select_one(".small")
        img_el = row.select_one("img.trophy")
        type_el = row.select_one(".trophy-type")
        rarity_el = row.select_one(".rarity-text")

        if not name_el:
            continue

        trophy_type = "bronze"
        if type_el:
            cls = " ".join(type_el.get("class", []))
            for t in ("platinum", "gold", "silver", "bronze"):
                if t in cls.lower():
                    trophy_type = t
                    break

        rarity = None
        if rarity_el:
            try:
                rarity = float(rarity_el.text.strip().replace("%", ""))
            except ValueError:
                pass

        trophies.append({
            "name": name_el.text.strip(),
            "description": desc_el.text.strip() if desc_el else None,
            "trophy_type": trophy_type,
            "trophy_image_url": img_el["src"] if img_el and img_el.get("src") else None,
            "rarity_percentage": rarity,
        })

    return trophies


def _parse_guide(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one(".guide-content") or soup.select_one("article") or soup.select_one("main")
    if not content:
        return None
    for tag in content.select("script, style, nav, .ad"):
        tag.decompose()
    return content.get_text(separator="\n", strip=True)
