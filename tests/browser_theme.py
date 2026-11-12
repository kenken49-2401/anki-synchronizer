"""Chromium appearance regression using local sample data only.
Run: python tests/browser_theme.py (Playwright and Chromium required).
"""
import functools,http.server,threading,json,shutil
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
class Quiet(http.server.SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(root/'web')))
threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path=shutil.which('chromium'),headless=True,args=['--no-sandbox']);ctx=browser.new_context(viewport={'width':1440,'height':1100});page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(base+'/study-atlas.html#data',wait_until='networkidle')
 assert page.locator('nav a[href="#data"]').inner_text().endswith('設定')
 before=page.evaluate('JSON.stringify({...localStorage})');page.select_option('#study-theme','dark');assert page.evaluate('document.documentElement.dataset.theme')=='dark'
 assert page.evaluate('getComputedStyle(document.body).backgroundColor')=='rgb(9, 11, 13)'
 after=page.evaluate('({...localStorage})');after.pop('atlas.theme.v1');assert json.loads(before)==after,(before,after)
 page.reload(wait_until='networkidle');assert page.locator('#study-theme').input_value()=='dark'
 # Fill actual records in the isolated local browser and check they survive theme changes.
 page.evaluate('''() => window.studyBridge.replace({scienceTagVersion:2,studies:[{id:'sample-study',date:localDate(),subject:'数学',minutes:45}],scores:[],tasks:[{id:'sample-task',date:dateOffset(7),title:'テーマ検証用',done:false,priority:'high',quantity:{mode:'total',start:dateOffset(-3),total:20,daily:2,unit:'問',entries:{[localDate()]:3}}}],nearGoals:[{id:'sample-goal',date:dateOffset(7),name:'テーマ検証',target:100,subjectTargets:{数学:100},issue:'検証用の課題',action:'検証用の取り組み'}],scoreGoals:{数学:{floor:40,target:70,ideal:100}}})''')
 before=page.evaluate("localStorage.getItem('study-atlas-prototype-v1')")
 page.select_option('#study-theme','light');page.select_option('#study-theme','dark')
 assert page.evaluate("localStorage.getItem('study-atlas-prototype-v1')")==before

 for width in [1440,390]:
  page.set_viewport_size({'width':width,'height':1100})
  for tab in ['study','scores','near-goals','goals','paper','tasks','tag-settings','data']:
   page.goto(base+'/study-atlas.html#'+tab,wait_until='networkidle')
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,tab)
   if tab=='near-goals':
    assert page.locator('#near-goals textarea').first.evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(14, 18, 21)'
    assert page.locator('#nearGoalFacts .near-fact').first.evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(29, 36, 37)'
   if tab=='tasks':
    if page.locator('.task-expand').first.get_attribute('aria-expanded')!='true':page.locator('.task-expand').first.click()
    assert page.locator('.quantity-card canvas').is_visible()

   if tab in ['study','data','near-goals','scores']:page.screenshot(path=f'/tmp/study-dark-{tab}-{width}.png',full_page=True)
 page.goto(base+'/?demo=1',wait_until='networkidle');page.locator('.app-layout').wait_for()
 assert page.evaluate('document.documentElement.dataset.theme')=='dark'
 for width in [1440,390]:
  page.set_viewport_size({'width':width,'height':1100})
  for view in ['overview','cards','insights','settings']:
   page.locator('nav [data-view="'+view+'"]').click();page.wait_for_timeout(100)
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),('anki',width,view)
   page.screenshot(path=f'/tmp/anki-dark-{view}-{width}.png',full_page=True)
 page.select_option('#anki-theme','light');assert page.evaluate('document.documentElement.dataset.theme')=='light'
 page.goto(base+'/study-atlas.html#data',wait_until='networkidle');assert page.locator('#study-theme').input_value()=='light'
 assert not errors,errors
 print('PASS: all Study/Anki tabs at 1440/390px; persistence; cross-app setting; no study storage changes or JS errors')
 browser.close()
server.shutdown()
