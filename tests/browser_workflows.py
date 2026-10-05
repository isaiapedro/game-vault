"""Browser contracts against synthetic API fixtures; never forwards API requests."""
import copy
import json

from playwright.sync_api import sync_playwright, expect


GAMES = [
    dict(id=1, title='Quiet Orbit', platform='PS5', ownership='owned', play_state='playing', goal='completionist',
         hltb_main_hours=12, hltb_completionist_hours=20, psn_progress=50, hours_played=2, trophy_count=2, earned_count=1, next_action='Explore the observatory',
         platinum_feasibility='unknown', in_backlog=True),
    dict(id=2, title='Paper Valley', platform='PS4', ownership='owned', play_state='not_started', goal='story',
         hltb_main_hours=6, hltb_completionist_hours=10, psn_progress=0, hours_played=0, trophy_count=0, earned_count=0, platinum_feasibility='unknown', in_backlog=True),
    dict(id=3, title='Tomorrow Harbor', platform='PS5', ownership='wanted', play_state='not_started', goal='platinum',
         hours_played=0, platinum_feasibility='unknown'),
    dict(id=4, title='Closed Roads', platform='PS3', ownership='owned', play_state='not_started', goal='platinum',
         platinum_hours=2, hours_played=0, platinum_feasibility='blocked', platinum_blocker_reason='Servers unavailable'),
    dict(id=5, title='Finished Story', platform='PS5', ownership='owned', play_state='finished', goal='story',
         hltb_main_hours=1, hltb_completionist_hours=5, psn_progress=100, hours_played=1, platinum_feasibility='unknown'),
]
SUMMARY = dict(total_estimated_hours=20, known_estimate_count=3, unknown_estimate_count=0,
               available_count=3, unavailable_count=0, total_count=3, coverage_pct=100)


def run():
    games = copy.deepcopy(GAMES)
    fail_games = False
    failed_reorder = False
    api_calls = []
    errors = []

    def intercept(route):
        nonlocal fail_games, failed_reorder
        request = route.request
        path = request.url.split(':8020', 1)[1].split('?', 1)[0]
        method = request.method
        api_calls.append((method, path))
        status = 200
        body = {}
        if method == 'OPTIONS':
            pass
        elif path == '/games' and method == 'GET':
            if fail_games:
                status, body = 503, {'detail': 'Fixture read failure'}
            else:
                body = games
        elif path == '/games' and method == 'POST':
            body = dict(id=6, play_state='not_started', goal='story', **request.post_data_json)
            games.append(body)
        elif path == '/backlog' and method == 'GET':
            body = dict(entries=[dict(g, game_id=g['id'], position=i+1, estimated_hours=0 if g['psn_progress']==100 else g['hltb_completionist_hours']*(1-g['psn_progress']/100),
                                      estimate_kind='trophy_progress_approximation', available=True) for i, g in enumerate([games[4],games[0],games[1]])], **SUMMARY)
        elif path == '/backlog/reorder':
            failed_reorder = True
            assert request.post_data_json == {'ordered_game_ids': [2, 1, 5], 'expected_game_ids': [1, 2, 5]}
            status, body = 409, {'detail': 'Fixture reorder conflict'}
        elif path == '/wishlist':
            body = [g for g in games if g['ownership'] == 'wanted']
        elif path == '/statistics':
            body = dict(library={'total_count': 5, 'platinum_count': 0, 'completed_count': 1},
                        trophies={'loaded_game_count':1,'collection_game_count':5,'earned_trophies':1,'total_trophies':2,'completion_rate_pct':50},
                        backlog=SUMMARY, insights={'finish_soon': [], 'blocked': [games[3]]}, milestones=[])
        elif path in ['/sync/status', '/enrich/hltb/status']:
            body = {'running': False, 'done': 0, 'total': 0, 'unmatched_titles': []}
        elif path == '/games/1/collection' and method == 'PATCH':
            assert request.post_data_json == {'play_state':'finished'}
            games[0].update(play_state='finished',manual_play_state='finished',is_completed=True,completion_reason='manual',remaining_hours=0)
            body=games[0]
        elif path == '/games/1':
            body = games[0]
        elif path == '/trophies/1':
            body = [{'id':1,'name':'A beginning','description':'Start the journey','trophy_type':'bronze','earned':True,'is_dlc':False},
                    {'id':2,'name':'Secret ending','description':'A surprise','trophy_type':'gold','earned':False,'is_dlc':True},
                    {'id':3,'name':'Hidden silver','description':'A silver surprise','trophy_type':'silver','earned':False,'is_dlc':False},
                    {'id':4,'name':'Secret platinum','description':'A platinum surprise','trophy_type':'platinum','earned':False,'is_dlc':False}]
        elif path == '/enrich/igdb/search':
            body = []
        else:
            status, body = 404, {'detail': 'Unimplemented fixture route: '+method+' '+path}
        route.fulfill(status=status, content_type='application/json', body=json.dumps(body), headers={
            'Access-Control-Allow-Origin':'*', 'Access-Control-Allow-Methods':'GET,POST,PATCH,PUT,DELETE,OPTIONS',
            'Access-Control-Allow-Headers':'*'})

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = browser.new_context()
        context.route('http://localhost:8020/**', intercept)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("if(!localStorage.getItem('gv-library-filters')) localStorage.setItem('gv-library-filters', JSON.stringify({query:42, sort:'bad-value', filter:null, loading:null, games:'bad'}))")
        for width in (390, 768, 1440):
            page.set_viewport_size({'width':width,'height':1000})
            for route, heading in [('library','Your library.'),('backlog','Your play queue.'),('wishlist','On your radar.'),('statistics','Time well played.'),('games/1','Quiet Orbit')]:
                page.goto('http://localhost:4200/'+route)
                expect(page.get_by_role('heading',name=heading,exact=True)).to_be_visible()
                page.wait_for_timeout(150)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (route,width,'overflow')
            print(f'PASS: all five routes without overflow at {width}px')

        page.goto('http://localhost:4200/library')
        expect(page.get_by_role('heading',name='Your library.')).to_be_visible()
        suggestions = page.locator('.suggestion')
        expect(suggestions).to_have_count(1)
        expect(suggestions.first).to_contain_text('Paper Valley')
        opener = page.get_by_role('button',name='＋ Add a game',exact=True)
        opener.focus()
        page.keyboard.press('Enter')
        expect(page.locator('dialog')).to_be_visible()
        expect(page.get_by_label('Game title',exact=True)).to_be_focused()
        page.keyboard.press('Escape')
        expect(page.locator('dialog')).not_to_be_visible()
        expect(opener).to_be_focused()
        print('PASS: keyboard add dialog and focus restoration; next choices exclude unavailable/blocked/in-progress/trophy-complete')
        expect(page.get_by_label('Find a game',exact=True)).to_have_value('')
        expect(page.get_by_role('combobox',name='Sort by',exact=True)).to_have_value('title')
        print('PASS: malformed persisted filters cannot overwrite application methods or state')

        page.goto('http://localhost:4200/games/1')
        expect(page.get_by_role('heading',name='~10h remaining',exact=True)).to_be_visible()
        expect(page.get_by_role('button',name='Sessions',exact=True)).to_have_count(0)
        expect(page.get_by_role('button',name='Your plan',exact=True)).to_have_count(0)
        expect(page.get_by_role('button',name='Log a session',exact=True)).to_have_count(0)
        assert not any('/sessions' in path for _,path in api_calls)
        print('PASS: automatic completionist remaining time; no session or plan UI or API reads')
        page.get_by_role('button',name='Trophies',exact=True).click()
        expect(page.locator('.trophy-row')).to_have_count(4)
        expect(page.locator('.tier-stat')).to_have_count(4)
        for tier in ['bronze','silver','gold','platinum']:
            icon = page.locator('.trophy-row img[src="/medals/'+tier+'.svg"]')
            expect(icon).to_have_count(1)
            assert icon.evaluate('(img)=>img.complete && img.naturalWidth>0'), tier+' medal failed to load'
            expect(icon).to_have_attribute('alt','')
            expect(icon).to_have_attribute('aria-hidden','true')
        expect(page.get_by_text('Secret ending',exact=True)).to_have_count(0)
        page.set_viewport_size({'width':390,'height':1000})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Trophy medals overflow'
        expect(page.locator('.trophy-row.earned')).to_have_count(1)
        expect(page.locator('.trophy-row.earned')).to_contain_text('✓ Earned')
        assert page.locator('.trophy-row.earned').evaluate('(row)=>getComputedStyle(row).backgroundColor') == 'rgb(32, 55, 44)'
        expect(page.locator('.trophy-row').filter(has_text='Hidden until you are ready').first).not_to_have_class('earned')
        print('PASS: medal icons remain tier-colored; earned rows are green with explicit checked Earned text')

        page.goto('http://localhost:4200/backlog')
        expect(page.locator('.queue-row')).to_have_count(3)
        expect(page.locator('.queue-row').last).to_contain_text('Finished Story')
        expect(page.get_by_role('button',name='Move Finished Story up',exact=True)).to_be_disabled()
        expect(page.get_by_role('button',name='Move Paper Valley down',exact=True)).to_be_disabled()
        expect(page.locator('.queue-row').last).to_contain_text('~0h approx. remaining')
        expect(page.get_by_role('button',name='Save estimate',exact=True)).to_have_count(0)
        page.get_by_role('button',name='Move Quiet Orbit down',exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('previous order has been restored')
        expect(page.locator('.queue-row').first).to_contain_text('Quiet Orbit')
        assert failed_reorder
        print('PASS: trophy-complete games stay last; reorder conflict rolls back')
        page.get_by_role('button',name='Mark Quiet Orbit done',exact=True).click()
        expect(page.get_by_role('status')).to_contain_text('marked done and moved to the completed section')
        expect(page.locator('.queue-row')).to_have_count(3)
        expect(page.locator('.queue-row').first).to_contain_text('Paper Valley')
        done_row=page.locator('#queue-game-1')
        expect(done_row).to_contain_text('✓ Done')
        expect(done_row).to_contain_text('50% trophies')
        expect(done_row).to_contain_text('~0h approx. remaining')
        expect(done_row).not_to_contain_text('100% trophies')
        expect(done_row).to_be_focused()
        expect(page.get_by_role('button',name='Mark Quiet Orbit done',exact=True)).to_have_count(0)
        expect(page.get_by_role('button',name='Remove Quiet Orbit from queue',exact=True)).to_be_visible()
        assert not any(method=='DELETE' for method,_ in api_calls)
        print('PASS: mark done retains item and actual progress, moves it after active games, restores focus and keeps Remove separate')

        fail_games = True
        page.goto('http://localhost:4200/library')
        expect(page.get_by_role('alert')).to_contain_text('Fixture read failure')
        fail_games = False
        page.get_by_role('button',name='Retry',exact=True).click()
        expect(page.locator('#collection')).to_be_visible()
        expect(page.get_by_role('alert')).to_have_count(0)
        assert not errors, errors
        print('PASS: read failure is explicit and retry recovers; zero page errors')
        games.extend([dict(games[1],id=6,platform='PS3'),dict(games[1],id=7,platform='PS4')])
        page.reload()
        sorter = page.get_by_role('combobox',name='Sort by',exact=True)
        sorter.select_option('title_desc')
        expect(page.locator('#collection .game-row h3').first).to_have_text('Tomorrow Harbor')
        expect(page.locator('#collection .game-row h3').last).to_have_text('Closed Roads')
        page.get_by_label('Find a game',exact=True).fill('Paper')
        expect(page.locator('#collection .game-row')).to_have_count(3)
        assert page.locator('#collection .game-row').evaluate_all('(rows)=>rows.map(row=>row.getAttribute("href"))') == ['/games/6','/games/2','/games/7']
        page.get_by_role('button',name='Cards',exact=True).click()
        page.reload()
        expect(sorter).to_have_value('title_desc')
        expect(page.get_by_label('Find a game',exact=True)).to_have_value('Paper')
        expect(page.locator('.game-list.card-view')).to_be_visible()
        page.get_by_role('button',name='Clear filters',exact=True).click()
        expect(sorter).to_have_value('title_desc')
        expect(page.locator('#collection .game-row h3').first).to_have_text('Tomorrow Harbor')
        assert not errors, errors
        print('PASS: Z–A ordering, deterministic duplicate-title order, filtered card view and saved-sort restoration')
        assert all(path.startswith('/') for _,path in api_calls)
        browser.close()


if __name__ == '__main__':
    run()
