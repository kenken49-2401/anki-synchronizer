"""Check goal card layout and existing save/total flows with synthetic local data.
Run: python tests/browser_goals.py (Playwright and Chromium required).
"""
import functools
import http.server
import shutil
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(
    ('127.0.0.1', 0), functools.partial(Quiet, directory=str(root / 'web')))
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{server.server_port}/study-atlas.html#goals'
fixture = dict(scienceTagVersion=2, studies=[], scores=[], tasks=[], nearGoals=[],
               scoreGoals={subject: dict(zip(['floor', 'target', 'ideal'], values))
                           for subject, values in [('英語', [40, 60, 80]), ('数学', [40, 60, 80]),
                                                   ('国語', [20, 40, 60]), ('物理', [10, 20, 30]),
                                                   ('化学', [10, 20, 30])]},
               commonScoreGoals={'国語': {'target': 100}})
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=shutil.which('chromium'), headless=True,
                                     args=['--no-sandbox'])
        for width in [390, 1440]:
            ctx = browser.new_context(viewport={'width': width, 'height': 1100})
            page = ctx.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base, wait_until='networkidle')
            assert page.evaluate('value=>window.studyBridge.replace(value)', fixture)
            page.reload(wait_until='networkidle')
            assert page.locator('.goals-subject-card').count() == 6
            assert [page.locator('#goalTotal-' + key).input_value()
                    for key in ['floor', 'target', 'ideal']] == ['120', '200', '280']
            before = page.evaluate('JSON.stringify(window.studyBridge.get())')
            for theme in ['light', 'dark']:
                page.evaluate("theme=>{document.documentElement.dataset.theme=theme;render()}", theme)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                for field in page.locator('#goalsForm input').all():
                    assert field.bounding_box()['width'] >= 50
                page.screenshot(path=f'/tmp/goals-{width}-{theme}-secondary.png', full_page=True)
                if theme == 'dark':
                    assert page.locator('#goalsForm').evaluate('(e)=>getComputedStyle(e).backgroundColor') == 'rgb(29, 36, 37)'
                    assert page.locator('.goals-subject-card').first.evaluate('(e)=>getComputedStyle(e).borderTopColor') != 'rgb(48, 57, 52)'
            assert page.evaluate('JSON.stringify(window.studyBridge.get())') == before
            page.locator('[name="理科-target"]').fill('50')
            assert page.locator('#goalTotal-target').input_value() == '210'
            page.locator('#goalTotal-target').fill('220')
            page.locator('[name="数学-target"]').fill('65')
            assert page.locator('#goalTotal-target').input_value() == '220'
            assert '手動' in page.locator('#goalTotalNote-target').inner_text()
            page.locator('#goalTotal-target').fill('')
            assert page.locator('#goalTotal-target').input_value() == '215'
            assert '自動' in page.locator('#goalTotalNote-target').inner_text()
            page.locator('#goalTotal-target').fill('225')
            page.locator('#goalsForm button[type="submit"]').click()
            assert '端末に保存しました' in page.locator('#goalsStatus').inner_text()
            secondary = page.evaluate('window.studyBridge.get().scoreGoals')
            assert secondary['合計'] == {'target': 225}
            assert secondary['数学']['target'] == 65
            page.reload(wait_until='networkidle')
            assert page.locator('#goalTotal-target').input_value() == '225'
            assert '手動' in page.locator('#goalTotalNote-target').inner_text()
            page.locator('#goals [data-exam-format-choice="common"]').click()
            assert page.locator('.goals-subject-card').count() == 9
            assert page.locator('#goalsScienceHint').is_hidden()
            assert page.locator('#goalTotalMax').inner_text() == '/ 1000点'
            assert page.locator('[name="国語-target"]').input_value() == '100'
            for field in page.locator('#goalSubjectInputs input').all():
                key = field.get_attribute('name').split('-')[-1]
                field.fill(str({'floor': 1, 'target': 2, 'ideal': 3}[key]))
            assert [page.locator('#goalTotal-' + key).input_value()
                    for key in ['floor', 'target', 'ideal']] == ['9', '18', '27']
            for theme in ['light', 'dark']:
                page.evaluate("theme=>{document.documentElement.dataset.theme=theme;render()}", theme)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=f'/tmp/goals-{width}-{theme}-common.png', full_page=True)
                if theme == 'dark':
                    assert page.locator('#goalsForm').evaluate('(e)=>getComputedStyle(e).backgroundColor') == 'rgb(29, 36, 37)'
            page.locator('#goalsForm button[type="submit"]').click()
            assert '端末に保存しました' in page.locator('#goalsStatus').inner_text()
            saved = page.evaluate('window.studyBridge.get()')
            assert saved['scoreGoals'] == secondary
            assert len(saved['commonScoreGoals']) == 9
            assert '合計' not in saved['commonScoreGoals']
            page.locator('[name="国語-floor"]').fill('4')
            page.locator('#goalsForm button[type="submit"]').click()
            assert '死守・目標・理想の順' in page.locator('#goalsStatus').inner_text()
            assert page.evaluate('window.studyBridge.get()') == saved
            page.once('dialog', lambda d: d.dismiss())
            page.locator('#goals [data-exam-format-choice="secondary"]').click()
            assert page.locator('.goals-subject-card').count() == 9
            assert page.locator('[name="国語-floor"]').input_value() == '4'
            page.once('dialog', lambda d: d.accept())
            page.locator('#goals [data-exam-format-choice="secondary"]').click()
            assert page.locator('.goals-subject-card').count() == 6
            assert page.locator('#goalTotal-target').input_value() == '225'
            assert not errors, errors
            print(f'PASS {width}px: both themes/formats, science precedence, auto/manual totals, '
                  'save/reload, independent stores, order validation, switch confirmation, no overflow/errors')
            ctx.close()
        browser.close()
finally:
    server.shutdown()
