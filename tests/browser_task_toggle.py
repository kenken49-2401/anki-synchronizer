"""Task disclosure regression with synthetic records. Run with Python + Playwright."""
import functools
import http.server
import shutil
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(
    ('127.0.0.1', 0), functools.partial(Quiet, directory=str(ROOT / 'web')))
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{server.server_port}/study-atlas.html#tasks'

# Resolve transparent surfaces to the enclosing card, then check both label colors.
READABILITY = """e => {
 const rgb=s=>s.match(/[\\d.]+/g).map(Number);
 const luminance=c=>c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
 let p=e,bg;
 do {bg=rgb(getComputedStyle(p).backgroundColor);p=p.parentElement} while(bg[3]===0&&p);
 const contrast=c=>{const a=luminance(rgb(c)),b=luminance(bg);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
 return {background:getComputedStyle(e).backgroundColor,text:contrast(getComputedStyle(e).color),hint:contrast(getComputedStyle(e,'::after').color)};
}"""

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
        for touch in [True, False]:
            context = browser.new_context(viewport={'width': 390 if touch else 1440, 'height': 1000},
                                          is_mobile=touch, has_touch=touch)
            page = context.new_page()
            cdp = context.new_cdp_session(page)
            cdp.send('DOM.enable')
            cdp.send('CSS.enable')
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url, wait_until='networkidle')
            page.evaluate("""() => window.studyBridge.replace({scienceTagVersion:2,studies:[],scores:[],pastPapers:[],tasks:
             ['high','medium','low'].flatMap(priority=>[false,true].map(done=>({id:priority+done,title:'開閉検証 '+priority+' '+done,
              priority,done,date:dateOffset(7),quantity:{mode:'total',start:localDate(),total:20,daily:2,unit:'問',entries:{}}})))})""")
            before = page.evaluate("localStorage.getItem('study-atlas-prototype-v1')")
            for theme in ['dark', 'light']:
                page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                for index in range(6):
                    toggle = page.locator('.task-expand').nth(index)
                    for expanded in ['true', 'false', 'true', 'false']:
                        if touch:
                            toggle.tap()
                        else:
                            toggle.click()
                        assert toggle.get_attribute('aria-expanded') == expanded
                        assert toggle.locator('xpath=ancestor::li').locator('.quantity-card').count() == (expanded == 'true')
                        # Keep the pointer hover after DOM replacement. DevTools forcing
                        # hover also enables hover media queries, so use it only on desktop.
                        if not touch:
                            document = cdp.send('DOM.getDocument')['root']['nodeId']
                            nodes = cdp.send('DOM.querySelectorAll', {'nodeId': document, 'selector': '.task-expand'})['nodeIds']
                            cdp.send('CSS.forcePseudoState', {'nodeId': nodes[index], 'forcedPseudoClasses': ['hover']})
                        toggle.evaluate('e=>{getComputedStyle(e).backgroundColor;return Promise.all(e.getAnimations().map(a=>a.finished))}')
                        colors = toggle.evaluate(READABILITY)
                        assert min(colors['text'], colors['hint']) >= 4.5, (touch, theme, index, expanded, colors)
                        if touch and expanded == 'false':
                            assert colors['background'] == 'rgba(0, 0, 0, 0)', (theme, colors, page.evaluate('matchMedia("(hover:hover) and (pointer:fine)").matches'))
                    if not touch:
                        # Move the pointer away; keyboard activation must retain a visible focus ring.
                        page.mouse.move(0, 0)
                        toggle.focus()
                        for key, expanded in [('Enter', 'true'), ('Space', 'false')]:
                            page.keyboard.press(key)
                            assert toggle.get_attribute('aria-expanded') == expanded
                            assert toggle.evaluate('e=>e===document.activeElement&&e.matches(":focus-visible")')
                            assert toggle.evaluate('e=>getComputedStyle(e).outlineStyle') != 'none'
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=f'/tmp/task-toggle-{theme}-{"touch" if touch else "mouse"}.png', full_page=True)
            assert page.evaluate("localStorage.getItem('study-atlas-prototype-v1')") == before
            assert not errors, errors
            context.close()
        browser.close()
    print('PASS: touch/mouse/keyboard; dark/light; all priorities and completion states; repeated open/close; contrast >= 4.5; records unchanged')
finally:
    server.shutdown()
