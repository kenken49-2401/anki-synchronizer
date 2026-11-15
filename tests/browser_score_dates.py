"""Check date positions and overlapping score tooltips using synthetic local records."""
import functools,http.server,threading,shutil,json
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
class Quiet(http.server.SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(root/'web')))
threading.Thread(target=server.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{server.server_port}/study-atlas.html#scores'
fixtures=[('A','2026-11-01',0,10),('B','2026-11-02',None,20),('C','2026-11-11',50,50),('D','2026-11-11',60,80),('E','2026-11-11',50,50),('F','2026-11-21',70,None),('UNDATED','',90,95)]
rows=[dict(id=name,name=name,date=date,kind='模試',subject='数学',score=score or 0,scoreComplete=score is not None,max=100,selfscore=selfscore,questions=[dict(name='1',max=100,score=score,selfscore=selfscore)]) for name,date,score,selfscore in fixtures]
with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path=shutil.which('chromium'),headless=True,args=['--no-sandbox'])
 for width in [390,1440]:
  ctx=browser.new_context(viewport={'width':width,'height':1100},is_mobile=width==390,has_touch=width==390)
  page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(base,wait_until='networkidle')
  page.evaluate('''rows=>{const original=setupChartTooltip;window.chartChecks={};setupChartTooltip=(canvas,points,details,...rest)=>{window.chartChecks[canvas.id]={points,details};return original(canvas,points,details,...rest)};window.studyBridge.replace({scienceTagVersion:2,studies:[],scores:rows,tasks:[]})}''',rows)
  saved=page.evaluate("localStorage.getItem('study-atlas-prototype-v1')")
  for theme in ['light','dark']:
   page.evaluate("theme=>{document.documentElement.dataset.theme=theme;render()}",theme)
   for tab,chart,table in [('subject','scoreChart','scoreTable'),('question','questionTrendChart','questionTrendTable')]:
    page.locator('#score-tab-'+tab).click()
    state=page.evaluate('(id)=>window.chartChecks[id]',chart)
    assert state and len(state['points'])==10,(width,tab,state)
    assert all('UNDATED' not in d for d in state['details'])
    assert 'UNDATED' in page.locator('#'+table).inner_text()
    def point(name,source):
     return next(p for p,d in zip(state['points'],state['details']) if d.startswith(name+'\n') and source+' ' in d)
    a,b,c,d,f=point('A','自己採点'),point('B','自己採点'),point('C','得点'),point('D','得点'),point('F','得点')
    assert abs((b[0]-a[0])/(f[0]-a[0])-.05)<1e-10
    assert c[0]==d[0] and c[0]==point('C','自己採点')[0]
    canvas=page.locator('#'+chart);canvas.scroll_into_view_if_needed()
    rect=canvas.bounding_box();cw=canvas.evaluate('(c)=>c.clientWidth')
    x,y=rect['x']+c[0]*rect['width']/cw,rect['y']+c[1]*rect['height']/220
    if width==390:page.touchscreen.tap(x,y)
    else:page.mouse.move(x,y)
    tooltip=page.locator('.chart-tooltip');assert tooltip.is_visible()
    text=tooltip.inner_text();assert all(name+'\n' in text for name in ['C','E']),(width,tab,text)
    assert '自己採点 50' in text and '得点 50' in text
    canvas.focus();page.keyboard.press('ArrowRight');assert tooltip.is_visible()
    page.screenshot(path=f'/tmp/score-dates-{tab}-{width}-{theme}.png',full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,tab)
   assert page.evaluate("localStorage.getItem('study-atlas-prototype-v1')")==saved
  assert not errors,errors
  print(f'PASS {width}px: subject/question true date axis, source alignment, overlapping hover/tap, keyboard, undated table, both themes, no storage writes/errors')
  ctx.close()
 browser.close()
server.shutdown()
