"""Merge classified Tokyo mathematics tags into encrypted Study Atlas records."""
from __future__ import annotations
import base64,copy,json,os,sys,uuid
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pages_crypto import decrypt,encrypt,password_bytes
from scripts.assistant_exam_import import PATH,BRANCH,MAX_BYTES

def merge_tags(current,payload):
    if not isinstance(current,dict) or current.get('schema_version')!=1 or not isinstance(current.get('scores'),list): raise ValueError('Invalid data')
    items=payload.get('items') if isinstance(payload,dict) and payload.get('format')=='study-math-tag-split-v1' else None
    if not isinstance(items,dict) or len(items)>150: raise ValueError('Invalid classifications')
    for key,tags in items.items():
        if not isinstance(key,str) or not isinstance(tags,list) or not tags or any(t not in ('数と式','関数') for t in tags): raise ValueError('Invalid tags')
    updated=copy.deepcopy(current);papers=updated.get('pastPapers',[])
    if not isinstance(papers,list): raise ValueError('Invalid past papers')
    exams={p.get('exam') for p in papers if isinstance(p,dict) and p.get('subject')=='数学' and isinstance(p.get('exam'),str)}
    explicit={e for e in exams if any(x in e for x in ('東京大学','東大','数学(前期)','数学（前期）'))}
    if len(explicit)==1: exam=next(iter(explicit))
    elif len(explicit)==0 and len(exams)==1: exam=next(iter(exams))
    else: raise ValueError('Mathematics exam is ambiguous')
    if '後期' in exam: raise ValueError('Wrong exam session')
    changed=unresolved=0
    def replace(old,key):
        nonlocal changed,unresolved
        if not isinstance(old,list) or '式と方程式' not in old: return old
        newtags=items.get(key)
        if not newtags: unresolved+=1; return old
        result=[t for t in old if t!='式と方程式']
        for t in newtags:
            if t not in result: result.append(t)
        changed+=1
        return result
    for row in papers:
        if not isinstance(row,dict) or row.get('subject')!='数学' or row.get('exam')!=exam: continue
        year=row.get('year');tagmap=row.get('tagsByQuestion',{})
        if not isinstance(tagmap,dict): raise ValueError('Invalid tags')
        for q,tags in list(tagmap.items()): tagmap[q]=replace(tags,f'{year}-{q}')
    for row in updated['scores']:
        if not isinstance(row,dict) or row.get('subject')!='数学' or row.get('kind')!='過去問': continue
        year=row.get('name')
        if not isinstance(year,str) or len(year)!=4 or not year.isdigit(): continue
        for q in row.get('questions',[]):
            if isinstance(q,dict): q['tags']=replace(q.get('tags',[]),f"{year}-{q.get('name')}")
    catalog=updated.setdefault('tagCatalog',{});tags=catalog.setdefault('数学',[])
    if not isinstance(tags,list): raise ValueError('Invalid catalog')
    for t in ('数と式','関数'):
        if t not in tags: tags.append(t);changed+=1
    hidden=updated.get('hiddenTags',{}).get('数学',[])
    if isinstance(hidden,list):
        for t in ('数と式','関数'):
            if t in hidden: hidden.remove(t);changed+=1
    # Keep the old option while any unresolved past-paper or score tags still need review.
    all_tags=[]
    for p in papers:
        if isinstance(p,dict) and p.get('subject')=='数学': all_tags.extend(v for v in p.get('tagsByQuestion',{}).values() if isinstance(v,list))
    for r in updated['scores']:
        if isinstance(r,dict) and r.get('subject')=='数学':
            all_tags.append(r.get('subjectTags',[]));all_tags.extend(q.get('tags',[]) for q in r.get('questions',[]) if isinstance(q,dict))
    if not any(isinstance(a,list) and '式と方程式' in a for a in all_tags) and '式と方程式' in tags: tags.remove('式と方程式');changed+=1
    print(f'{unresolved} tag references require further review.')
    return updated,changed

def run():
    if os.environ.get('GITHUB_REPOSITORY')!='kenken49-2401/anki-synchronizer' or not os.environ.get('GITHUB_TOKEN'): raise ValueError('Invalid configuration')
    password,key=os.environ.get('STUDY_ATLAS_PASSWORD',''),os.environ.get('ASSISTANT_IMPORT_KEY','');password_bytes(password);password_bytes(key)
    payload=decrypt(json.loads(Path('assistant-import/math-tag-split.enc.json').read_bytes()),key)
    headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    with httpx.Client(base_url='https://api.github.com',headers=headers,follow_redirects=False,timeout=60) as client:
        response=client.get(PATH,params={'ref':BRANCH});response.raise_for_status();result=response.json()
        if result.get('type')!='file' or result.get('encoding')!='base64' or not isinstance(result.get('sha'),str): raise ValueError('Existing data unavailable')
        raw=base64.b64decode(''.join(result['content'].split()),validate=True)
        if len(raw)>MAX_BYTES: raise ValueError('Data exceeds limit')
        updated,count=merge_tags(decrypt(json.loads(raw),password),payload)
        if not count: print('No new tags to add.');return
        encrypted=json.dumps(encrypt(updated,password),separators=(',',':')).encode()
        if len(encrypted)>MAX_BYTES: raise ValueError('Encrypted result exceeds limit')
        response=client.put(PATH,json={'message':'Split encrypted mathematics tags','branch':BRANCH,'sha':result['sha'],'content':base64.b64encode(encrypted).decode('ascii')});response.raise_for_status()
        print(f'Updated {count} mathematics tag references or catalog entries.')
if __name__=='__main__':
    try: run()
    except Exception:
        print('Math tag import failed; check the exam name, secrets, permissions and concurrent changes.',file=sys.stderr)
        raise SystemExit(1) from None
