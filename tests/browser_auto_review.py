import sys, functools, http.server, threading, tempfile, shutil, json
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path[:0]=[str(root), str(root/'tests'), str(root/'.venv/lib/python3.12/site-packages')]
from playwright.sync_api import sync_playwright
from test_pages import snapshot, PASSWORD
from pages_crypto import decrypt
import pages_site
with tempfile.TemporaryDirectory() as d:
 data=snapshot();data['source'].update(kind='ankiweb',profile='AnkiWeb');card=data['cards'][0];card.update(review_version='a'*64,queue=2)
 site=Path(d)/'site';pages_site.build_site(pages_site.prepare_snapshot(data),PASSWORD,site)
 class Quiet(http.server.SimpleHTTPRequestHandler):
  def log_message(self,*args):pass
 server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(site)));threading.Thread(target=server.serve_forever,daemon=True).start()
 with sync_playwright() as p:
  b=p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox']);ctx=b.new_context(viewport={'width':390,'height':900});calls=[];fail=[False]
  def api(route):
   headers={'access-control-allow-origin':'*','access-control-allow-methods':'GET, POST, OPTIONS','access-control-allow-headers':'authorization, content-type, x-github-api-version, accept'}
   if route.request.method=='OPTIONS':route.fulfill(status=204,headers=headers);return
   calls.append(route.request)
   if route.request.url.endswith('/user'):route.fulfill(status=200,headers=headers,json={'login':'kenken49-2401'})
   elif fail[0]:route.abort()
   else:route.fulfill(status=201,headers=headers,json={'number':1})
  ctx.route('https://api.github.com/**',api);page=ctx.new_page();page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle');page.get_by_label('パスワード',exact=True).fill(PASSWORD);page.get_by_role('button',name='ログイン',exact=True).click();page.locator('.app-layout').wait_for()
  page.get_by_role('button',name='接続・設定',exact=True).click();page.locator('#review-token').fill('github_pat_test_token_1234567890');page.get_by_role('button',name='この端末に設定').click();page.get_by_text('この端末で回答の自動送信を設定しました。').wait_for()
  stored=page.evaluate('JSON.stringify(localStorage)');assert 'github_pat_test_token' not in stored
  page.get_by_role('button',name='タグ別カード',exact=True).click();page.locator('[data-answer]').first.click();page.locator('.review-ratings').first.get_by_role('button',name='正解',exact=True).click();page.get_by_text('回答を送信しました。定時更新でAnkiへの反映を確認します。').wait_for()
  sent=json.loads(calls[-1].post_data); assert sent['title']=='[Anki Atlas] Encrypted review';payload=decrypt(json.loads(sent['body'].split('\n')[2]),PASSWORD);assert payload['rating']=='good';assert payload['card_id']==card['id'];assert 'good' not in sent['body']
  page.locator('.review-ratings').first.get_by_role('button',name='正解',exact=True).click();page.get_by_text('このカードの回答は送信済みか確認待ちです。Ankiの履歴と更新を確認してください。').wait_for();assert len(calls)==2
  fail[0]=True
  result=page.evaluate('''async()=>{const {submitAutomaticReview}=await import('./review-auto.mjs');const {importPassword}=await import('./vault.mjs');const k=await importPassword(%s);const c={id:9999,review_version:'b'.repeat(64)};let errors=[];for(let i=0;i<2;i++){try{await submitAutomaticReview(k,c,'good')}catch(e){errors.push(e.message)}}return errors}''' % json.dumps(PASSWORD))
  assert '送信結果を確認できません' in result[0] and '送信済みか確認待ち' in result[1];assert len(calls)==3
  print('automatic encrypted submission and duplicate guard passed');b.close()
 server.shutdown()
