"""Manual Chromium regression: python tests/browser_rich_notes.py. Requires Playwright and Chromium.
Uses synthetic encrypted cards only; does not access a real Anki account.
"""
import sys,functools,http.server,threading,tempfile,json,copy,os,shutil
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path[:0]=[str(root),str(root/'tests'),str(root/'.venv/lib/python3.12/site-packages')]
from playwright.sync_api import sync_playwright
from test_pages import with_image,PASSWORD
import pages_site
from pages_crypto import decrypt
class Quiet(http.server.SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
with tempfile.TemporaryDirectory(prefix='atlas-rich-') as folder:
 raw=with_image();raw['source'].update(kind='ankiweb',profile='AnkiWeb')
 c=raw['cards'][0];c['fields']={'Front':'<p style="color: rgb(0, 88, 155)">Hello H<sub>2</sub>O<img src="molecule.png" alt="molecule"></p>','Back':'<b>Water</b> {{c1::answer}}'};c['editable_fields']=dict(c['fields']);c['front']=c['fields']['Front'];c['back']=c['fields']['Back']
 site=Path(folder)/'site';pages_site.MEDIA_CHUNK_BYTES=1;data=pages_site.prepare_snapshot(raw);pages_site.build_site(data,PASSWORD,site)
 encrypted=json.loads((site/'snapshot.enc.json').read_text());main=decrypt(encrypted,PASSWORD);assert main['media_names']['molecule.png']==next(iter(main['media_index']))
 server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(site)));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),headless=True,args=['--no-sandbox']);ctx=browser.new_context(viewport={'width':390,'height':900},is_mobile=True,has_touch=True)
   page=ctx.new_page();errors=[];requests=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None);page.on('request',lambda r:requests.append((r.method,r.url,r.post_data)))
   page.goto(base,wait_until='networkidle');page.get_by_label('パスワード',exact=True).fill(PASSWORD);page.get_by_role('button',name='ログイン',exact=True).click();page.locator('.app-layout').wait_for();page.get_by_role('button',name='タグ別カード',exact=True).click();page.locator('[data-edit-note]').first.click();dialog=page.locator('#note-edit-dialog');dialog.wait_for()
   assert dialog.locator('textarea:visible').count()==0
   assert dialog.get_by_role('textbox',name='Front',exact=True).inner_text().startswith('Hello H2O')
   page.wait_for_function('()=>document.querySelector("#note-field-0 img").naturalWidth>0')
   for width in [360,390,1440]:
    page.set_viewport_size({'width':width,'height':900});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');assert dialog.evaluate('(e)=>e.scrollWidth<=e.clientWidth')
   page.set_viewport_size({'width':390,'height':900});page.screenshot(path=str(Path(tempfile.gettempdir())/'atlas-rich-editor-mobile.png'))
   # Opening/switching untouched fields must leave the original source byte-for-byte.
   first=dialog.locator('[data-rich-field="0"]');first.get_by_role('button',name='HTMLを直接編集',exact=True).click();assert page.get_by_label('FrontのHTML',exact=True).input_value()==c['fields']['Front'];first.get_by_role('button',name='文書形式に戻る',exact=True).click();assert dialog.get_attribute('data-dirty')=='false'
   # Select Water; toggle bold off and underline on via visible formatting controls.
   page.evaluate('''()=>{const e=document.querySelector('#note-field-1'),w=document.createTreeWalker(e,NodeFilter.SHOW_TEXT);let n;while(n=w.nextNode()){if(n.data.includes('Water')){const r=document.createRange();r.setStart(n,n.data.indexOf('Water'));r.setEnd(n,n.data.indexOf('Water')+5);getSelection().removeAllRanges();getSelection().addRange(r);e.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));break}}}''')
   page.get_by_role('button',name='Back：下線',exact=True).click();assert dialog.get_attribute('data-dirty')=='true'
   page.evaluate('''()=>{const e=document.querySelector('#note-field-1');e.focus();const r=document.createRange();r.selectNodeContents(e);r.collapse(false);getSelection().removeAllRanges();getSelection().addRange(r)}''');page.keyboard.insert_text(' extra text')
   dialog.get_by_text('保存する変更内容を確認',exact=True).click();dialog.locator('[data-note-diff]').filter(has_text='Water').wait_for();assert '<b>' not in dialog.locator('[data-note-diff]').inner_text();assert 'Water' in dialog.locator('[data-note-diff]').inner_text()
   dialog.get_by_role('button',name='本文の下書きを保存',exact=True).click();dialog.wait_for(state='detached');saved=page.evaluate('localStorage.getItem("atlas-note-draft")');payload=decrypt(json.loads(saved),PASSWORD);change=payload['changes'][0]
   assert set(change['set_fields'])=={'Back'};assert change['fields']['Front']==c['fields']['Front'];assert '{{c1::answer}}' in change['set_fields']['Back'];assert 'extra text' in change['set_fields']['Back'];assert 'underline' in change['set_fields']['Back'] or '<u>' in change['set_fields']['Back'];assert 'data-rich-' not in change['set_fields']['Back'];assert 'blob:' not in change['set_fields']['Back']
   page.reload(wait_until='networkidle');page.locator('.app-layout').wait_for();page.get_by_role('button',name='タグ別カード',exact=True).click();page.locator('[data-edit-note]').first.click();assert 'extra text' in page.get_by_role('textbox',name='Back',exact=True).inner_text();page.get_by_role('button',name='閉じる',exact=True).click()
   # Isolated browser tests exercise the actual module with adversarial note HTML.
   result=page.evaluate(r'''async()=>{
    const {createRichNoteField}=await import('./rich-note-field.mjs');
    const source='<p class="kept" style="color: blue" onclick="window.bad=1">Alpha <b>bold</b><img src="molecule.png"><iframe src="https://evil.invalid/private"></iframe><svg onload="window.bad=1"><text>diagram</text></svg><script>window.bad=1</script></p>';
    const field=createRichNoteField({value:source,label:'Probe',id:'probe',resolveImage:async()=>null});document.body.append(field.element);
    if(field.getValue()!==source)throw Error('untouched raw changed');
    const e=document.querySelector('#probe');if(e.querySelector('iframe,svg,script,[onclick]'))throw Error('active HTML mounted');
    e.append(document.createTextNode(' changed'));e.dispatchEvent(new InputEvent('input',{bubbles:true}));
    const changed=field.getValue();if(!changed.includes('<img src="molecule.png">')||!changed.includes('<svg')||!changed.includes('<iframe')||!changed.includes('class="kept"')||changed.includes('blob:')||changed.includes('data-rich-'))throw Error('preservation failed');
    // Internal clipboard HTML must restore original references, never blob URLs.
    const image=e.querySelector('.rich-note-image'),range=document.createRange();range.selectNode(image);getSelection().removeAllRanges();getSelection().addRange(range);const clip=new DataTransfer();e.dispatchEvent(new ClipboardEvent('copy',{clipboardData:clip,bubbles:true,cancelable:true}));if(clip.getData('text/html')!=='<img src="molecule.png">')throw Error('image copy lost source');
    field.destroy();
    const fresh=createRichNoteField({value:'base',label:'Paste',id:'paste'});document.body.append(fresh.element);const editor=document.querySelector('#paste');editor.focus();const r=document.createRange();r.selectNodeContents(editor);r.collapse(false);getSelection().removeAllRanges();getSelection().addRange(r);
    const data=new DataTransfer();data.setData('text/html','<b>pasted</b><span style="color:red;background-image:url(https://evil.invalid/leak)">red</span><img src="https://evil.invalid/image" onerror="window.bad=1"><script>window.bad=1</script>');editor.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));
    const output=fresh.getValue();if(!output.includes('<b>pasted</b>')||!output.includes('color')||output.includes('evil.invalid')||output.includes('window.bad')||output.includes('data-rich-'))throw Error('unsafe/lossy paste: '+output);
    if(window.bad)throw Error('source executed');fresh.destroy();
    const format=createRichNoteField({value:'<p>Alpha Beta</p>',label:'Format',id:'format'});document.body.append(format.element);
    const select=()=>{const el=document.querySelector('#format');el.focus();const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);let n;while(n=walker.nextNode()){const i=n.data.indexOf('Alpha');if(i>=0){const range=document.createRange();range.setStart(n,i);range.setEnd(n,i+5);getSelection().removeAllRanges();getSelection().addRange(range);return;}}throw Error('selection text missing');};
    const click=name=>format.element.querySelector(`[aria-label="Format：${name}"]`).click();
    select();click('太字');if(!/(font-weight: (bold|700)|<b>|<strong>)/.test(format.getValue()))throw Error('bold toolbar');
    click('元に戻す');if(format.getValue()!=='<p>Alpha Beta</p>')throw Error('undo failed');click('やり直す');if(!/(font-weight: (bold|700)|<b>|<strong>)/.test(format.getValue()))throw Error('redo failed');
    select();click('下付き文字');if(!/(vertical-align: sub|<sub>)/.test(format.getValue()))throw Error('subscript');
    select();click('上付き文字');if(!/(vertical-align: super|<sup>)/.test(format.getValue()))throw Error('superscript');
    select();click('箇条書き');if(!format.getValue().includes('<ul>'))throw Error('unordered list');
    select();click('番号付きリスト');if(!format.getValue().includes('<ol>'))throw Error('ordered list');
    const color=format.element.querySelector('input[type=color]');select();color.value='#ff0000';color.dispatchEvent(new Event('input'));if(!/color: (rgb\(255, 0, 0\)|#ff0000)/.test(format.getValue()))throw Error('color toolbar');format.destroy();
    return 'safe source, opaque preservation, image clipboard, styled paste, bold/undo/redo/lists/sub/sup/color passed';
   }''')
   assert not errors,errors;assert all('evil.invalid' not in url and PASSWORD not in url+(body or '') for _,url,body in requests)
   print('PASS: document UI, bold/underline, text entry, cloze preservation, unchanged raw, formatted diff, chunked images, encrypted save/reload, 360/390/1440px; '+result)
   ctx.close();browser.close()
 finally:server.shutdown()
