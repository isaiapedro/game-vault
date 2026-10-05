"""Read-only smoke checks against the local app, with private render artifacts."""
import json
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


def main():
    base = "http://localhost:8020"
    def get(path):
        with urlopen(base + path, timeout=15) as response:
            return json.load(response)

    games, backlog, stats = get("/games"), get("/backlog"), get("/statistics")
    assert backlog["summary"] == stats["backlog"], "Queue and statistics disagree"
    assert stats["library"]["platinum_count"] == sum(bool(g["platinum_earned"]) for g in games)
    assert not {"monthly_hours", "total_hours_played", "session_count", "recent_activity"} & stats.keys()
    assert stats["library"]["completed_count"] == sum(bool(g["is_completed"]) for g in games)
    assert all(g["goal"] == "completionist" for g in games)
    completed_flags = [bool(entry["is_completed"]) for entry in backlog["entries"]]
    assert completed_flags == sorted(completed_flags), "Trophy-complete games must be last"
    for game in games:
        if game["is_completed"]:
            assert game["remaining_hours"] == 0
        elif game["progress_pct"] is None:
            assert game["remaining_hours"] is None
    assert stats["trophies"]["collection_game_count"] == len(games)
    print(json.dumps({
        "collection_count": len(games), "queue_count": len(backlog["entries"]),
        "library": stats["library"], "queue_coverage": stats["backlog"]["coverage_pct"],
        "trophy_loaded_games": stats["trophies"]["loaded_game_count"],
        "shared_metrics_consistent": True,
    }))
    root = Path(__file__).resolve().parents[1]
    output = root / ".local" / "verification"
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    routes = ["library", "backlog", "wishlist", "statistics"]
    if games:
        routes.append(f"games/{games[0]['id']}")
    errors = []
    checked = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        def guard(route):
            if route.request.method not in ("GET", "HEAD", "OPTIONS"):
                raise AssertionError("Live smoke test attempted a mutation")
            if "/sessions" in route.request.url:
                raise AssertionError("Session routes must not be used by the current UI")
            if "/trophies/" in route.request.url:
                raise AssertionError("Live trophy cache/provider reads are outside this smoke test")
            route.continue_()
        page.route("http://localhost:8020/**", guard)
        for width in [390, 768, 1440]:
            page.set_viewport_size({"width": width, "height": 1000})
            for path in routes:
                failures = []
                def on_response(response):
                    if response.url.startswith(base) and response.status >= 400:
                        failures.append(response.status)
                page.on("response", on_response)
                page.goto("http://localhost:4200/" + path)
                page.wait_for_load_state("networkidle")
                page.locator("h1").wait_for()
                overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
                assert not overflow, f"Horizontal overflow: {path} at {width}px"
                assert not failures, f"API failure: {path}, status {failures}"
                assert not page.locator(".status.error").count(), f"Visible error: {path}"
                name = path.replace("/", "-")
                page.screenshot(path=str(output / f"{name}-{width}.png"), full_page=False)
                checked.append(f"{path}@{width}")
                page.remove_listener("response", on_response)
        browser.close()
    assert not errors, f"Browser errors: {errors}"
    print(json.dumps({"screens_checked": checked, "browser_errors": 0, "horizontal_overflow": 0}))


if __name__ == "__main__":
    main()
