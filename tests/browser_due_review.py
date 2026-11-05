"""Manual browser regression; uses a mocked GitHub API and synthetic cards."""
import copy, functools, http.server, shutil, sys, tempfile, threading
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path[:0]=[str(root),str(root/'tests'),str(root/'.venv/lib/python3.12/site-packages')]
from playwright.sync_api import sync_playwright
from test_pages import snapshot,PASSWORD
import pages_site

with tempfile.TemporaryDirectory() as directory:
 raw=snapshot();raw['source'].update(kind='ankiweb',profile='AnkiWeb');card=raw['cards'][0];card.update(review_version='a'*64,queue=2,type=2,due_date='2000-01-01',front='Card A')
 for ident,front in [(101,'Card B'),(102,'Card C')]:
  c=copy.deepcopy(card);c.update(id=ident,note_id=ident+100,review_version=('b' if ident==101 else 'c')*64,front=front);raw['cards'].append(c)
 site=Path(directory)/'site';pages_site.build_site(pages_site.prepare_snapshot(raw),PASSWORD,site)
 class Quiet(http.server.SimpleHTTPRequestHandler):
  def log_message(self,*args):pass
 server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(site)));threading.Thread(target=server.serve_forever,daemon=True).start()
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox']);ctx=browser.new_context(viewport={'width':390,'height':900});mode=['ok']
  def api(route):
   headers={'access-control-allow-origin':'*','access-control-allow-methods':'GET, POST, OPTIONS','access-control-allow-headers':'authorization, content-type, x-github-api-version, accept'}
   if route.request.method=='OPTIONS':route.fulfill(status=204,headers=headers)
   elif route.request.url.endswith('/user'):route.fulfill(status=200,headers=headers,json={'login':'kenken49-2401'})
   elif mode[0]=='fail':route.fulfill(status=403,headers=headers,json={})
   else:route.fulfill(status=201,headers=headers,json={'number':1})
  ctx.route('https://api.github.com/**',api);page=ctx.new_page();page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle');page.get_by_label('パスワード',exact=True).fill(PASSWORD);page.get_by_role('button',name='ログイン',exact=True).click();page.locator('.app-layout').wait_for();page.get_by_role('button',name='接続・設定',exact=True).click();page.locator('#review-token').fill('github_pat_test_token_1234567890');page.get_by_role('button',name='この端末に設定').click();page.get_by_text('この端末で回答の自動送信を設定しました。').wait_for();page.get_by_role('button',name='タグ別カード',exact=True).click();page.get_by_label('今日までが期限').check()
  def review(front,rating):
   item=page.locator('.study-card').filter(has_text=front);item.get_by_role('button',name='答えを見る').click();item.get_by_role('button',name=rating,exact=True).click()
  review('Card A','正解');page.get_by_text('回答を送信しました。定時更新でAnkiへの反映を確認します。').wait_for();assert page.get_by_text('Card A').count()==0
  mode[0]='fail';review('Card B','簡単');page.get_by_text('GitHubに送信できませんでした（HTTP 403）。設定を確認してください。').wait_for();assert page.get_by_text('Card B').count()==1
  mode[0]='ok';page.locator('.study-card').filter(has_text='Card B').get_by_role('button',name='簡単',exact=True).click();page.get_by_text('Card B').wait_for(state='detached');review('Card C','難しい');page.get_by_text('回答を送信しました。定時更新でAnkiへの反映を確認します。').wait_for();assert page.get_by_text('Card C').count()==1
  page.reload(wait_until='networkidle');page.locator('.app-layout').wait_for();page.get_by_role('button',name='タグ別カード',exact=True).click();page.get_by_label('今日までが期限').check();assert page.get_by_text('Card A').count()==0 and page.get_by_text('Card B').count()==0 and page.get_by_text('Card C').count()==1;page.get_by_label('今日までが期限').uncheck();assert page.get_by_text('Card A').count()==1
  print('due review hiding, failure and reload verified');browser.close()
 server.shutdown()
