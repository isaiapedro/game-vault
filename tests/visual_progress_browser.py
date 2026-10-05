"""Read-only browser regression for the progress-focused static release.

Run from the project root with the Compose app on its reserved loopback port.
Screenshots stay in the ignored private verification directory.
"""
from pathlib import Path
import os
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get('GAME_VAULT_TEST_BASE', 'http://127.0.0.1:4200').rstrip('/')
OUTPUT = Path('.local/verification/progress-design')


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        errors, external, writes = [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.on('request', lambda request: external.append(request.url) if not request.url.startswith(BASE) else None)
        page.on('request', lambda request: writes.append(request.url) if request.method not in ('GET', 'HEAD') else None)
        games = page.request.get(BASE + '/api/games').json()
        platinum_ids = [g['id'] for g in games if g.get('platinum_earned') or
                        (not g.get('platinum_manual_override') and (g.get('psn_earned_platinum') or 0) > 0)]
        assert platinum_ids, 'Use a collection with at least one earned platinum for this check'
        routes = ['/library', '/backlog', '/wishlist', '/statistics', f'/games/{platinum_ids[0]}']
        for width in (390, 768, 1440):
            page.set_viewport_size({'width': width, 'height': 1000})
            for route in routes:
                response = page.goto(BASE + route, wait_until='networkidle')
                assert response.status == 200
                assert page.locator('h1').count() == 1
                overflow = page.evaluate("""() => [...document.body.querySelectorAll('*')]
                  .filter(node => node.getBoundingClientRect().right > innerWidth + 1)
                  .slice(0, 8).map(node => ({tag: node.tagName, className: String(node.className),
                    right: Math.round(node.getBoundingClientRect().right)}))""")
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, route, overflow)
                assert page.locator('link[rel=stylesheet]').evaluate_all("nodes => nodes.every(n => n.sheet && n.media !== 'print')")
                assert page.locator('.status.error').count() == 0
                if route in ('/library', f'/games/{platinum_ids[0]}'):
                    sizes = page.evaluate("""() => [...document.body.querySelectorAll('*')]
                      .filter(node => [...node.childNodes].some(child => child.nodeType === 3 && child.textContent.trim()))
                      .map(node => getComputedStyle(node).fontSize)""")
                    assert set(sizes) <= {'15px', '25px'}, (width, route, sorted(set(sizes)))
                if route == '/library':
                    assert page.locator('gv-game-card').count() == len(games)
                    assert page.locator('.is-platinum').count() == len(platinum_ids)
                    assert page.locator('.game-card .genre-tags,.game-card .igdb-score,.game-card .badge').count() == 0
                    assert page.locator('.game-card .cover:not(.cover-fallback)').count() == len(games)
                if route.startswith('/games/'):
                    assert page.locator('.detail-hero.is-platinum').count() == 1
                    assert page.get_by_role('button', name='About', exact=True).get_attribute('aria-pressed') == 'true'
                    assert page.locator('.about-tags').count() == 1
                    assert page.locator('.detail-hero.is-platinum').count() == 1
                if width in (390, 1440):
                    page.screenshot(path=str(OUTPUT / f'{route.strip("/").replace("/", "-")}-{width}.png'), full_page=False)
        page.goto(BASE + '/library', wait_until='networkidle')
        page.get_by_role('button', name='✦ Platinum', exact=True).click()
        expect(page.locator('gv-game-card')).to_have_count(len(platinum_ids))
        page.get_by_role('button', name='No PSN progress', exact=True).click()
        expect(page.locator('gv-game-card')).to_have_count(sum(g.get('psn_progress') is None and not g.get('trophy_count') for g in games))
        assert page.locator('gv-game-card').count() > 0
        for node in page.locator('.game-card').all():
            assert node.evaluate("n => n.style.getPropertyValue('--fill')") == '0%'
            assert node.locator('.card-progress strong').inner_text() == '—'
        page.get_by_role('button', name='All', exact=True).click()
        page.get_by_role('button', name='Genre: All genres').click()
        expect(page.get_by_role('listbox', name='Genre')).to_be_visible()
        expect(page.get_by_role('option', name='All genres')).to_have_attribute('aria-selected', 'true')
        page.screenshot(path=str(OUTPUT / 'dropdown-items-1440.png'), full_page=False)
        page.get_by_role('option', name='Racing').click()
        expect(page.locator('gv-game-card')).to_have_count(2)
        assert page.locator('gv-game-card').count() > 0
        page.goto(BASE + '/backlog', wait_until='networkidle')
        picks = page.locator('.picks-section gv-game-card')
        assert picks.count() > 1
        page.get_by_label('Show completed').check()
        expect(page.locator('.list-layout .is-platinum').first).to_be_visible()
        page.get_by_role('button', name='Access: Ready to play').click()
        page.get_by_role('option', name='Not owned').click()
        assert page.locator('.list-layout gv-game-card').count() > 0
        detailed = next(g for g in games if (g.get('trophy_count') or 0) > 0 and (g.get('earned_count') or 0) < g['trophy_count'])
        page.goto(BASE + f'/games/{detailed["id"]}', wait_until='networkidle')
        page.get_by_role('button', name='Trophies', exact=True).click()
        page.get_by_role('button', name='Set: All sets').focus()
        page.keyboard.press('ArrowDown')
        expect(page.get_by_role('listbox', name='Set')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.get_by_role('listbox', name='Set')).to_have_count(0)
        assert page.get_by_role('button', name='To earn', exact=True).get_attribute('aria-pressed') == 'true'
        assert page.locator('.trophy-row.earned').count() == 0
        page.get_by_role('button', name='All', exact=True).click()
        expect(page.locator('.trophy-row')).to_have_count(detailed['trophy_count'])
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.detail-hero').evaluate('n => getComputedStyle(n).transitionDuration') == '0s'
        assert not errors, errors
        assert not external, external
        assert not writes, writes
        print(f'Passed: 5 routes × 3 widths; {len(games)} games; {len(platinum_ids)} platinum cards; genre, access and trophy filters; no external requests or writes.')
        browser.close()


if __name__ == '__main__':
    main()
