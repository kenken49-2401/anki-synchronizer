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
    items=payload.get('items') if isinstance(payload,dict) and payload.get('format')=='study-atlas-math-tags-v1' else None
    if not isinstance(items,list) or len(items)>150: raise ValueError('Invalid payload')
    updated=copy.deepcopy(current);papers=updated.setdefault('pastPapers',[])
    if not isinstance(papers,list): raise ValueError('Invalid papers')
    exams={p.get('exam') for p in papers if isinstance(p,dict) and p.get('subject')=='数学' and isinstance(p.get('exam'),str)}
    explicit={e for e in exams if any(x in e for x in ('東京大学','東大','数学(前期)','数学（前期）'))}
    if len(explicit)==1: exam=next(iter(explicit))
    elif len(explicit)==0 and len(exams)==1: exam=next(iter(exams))
    else: raise ValueError('Mathematics exam is ambiguous')
    if '後期' in exam: raise ValueError('Wrong exam session')
    catalog=updated.setdefault('tagCatalog',{});tags=catalog.setdefault('数学',[])
    if not isinstance(catalog,dict) or not isinstance(tags,list): raise ValueError('Invalid catalog')
    count=0
    for item in items:
        year=item.get('year') if isinstance(item,dict) else None;questions=item.get('questions') if isinstance(item,dict) else None
        if not isinstance(year,str) or len(year)!=4 or not year.isdigit() or not isinstance(questions,list) or len(questions)!=6: raise ValueError('Invalid item')
        matches=[p for p in papers if p.get('subject')=='数学' and p.get('exam')==exam and p.get('year')==int(year)]
        if len(matches)>1: raise ValueError('Duplicate year')
        if matches: row=matches[0]
        else:
            row={'id':str(uuid.uuid4()),'exam':exam,'subject':'数学','year':int(year),'statuses':{}};papers.append(row)
        saved=row.setdefault('tagsByQuestion',{})
        if not isinstance(saved,dict): raise ValueError('Invalid saved tags')
        for i,incoming in enumerate(questions,1):
            if not isinstance(incoming,list) or not incoming or any(not isinstance(t,str) or not t or len(t)>50 for t in incoming): raise ValueError('Invalid tags')
            existing=saved.setdefault(str(i),[])
            if not isinstance(existing,list) or any(not isinstance(t,str) for t in existing): raise ValueError('Invalid saved tags')
            for tag in incoming:
                if tag not in existing: existing.append(tag);count+=1
                if tag not in tags: tags.append(tag)
    return updated,count

def run():
    if os.environ.get('GITHUB_REPOSITORY')!='kenken49-2401/anki-synchronizer' or not os.environ.get('GITHUB_TOKEN'): raise ValueError('Invalid configuration')
    password,key=os.environ.get('STUDY_ATLAS_PASSWORD',''),os.environ.get('ASSISTANT_IMPORT_KEY','');password_bytes(password);password_bytes(key)
    payload=decrypt(json.loads(Path('assistant-import/older-math-tags.enc.json').read_bytes()),key)
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
        response=client.put(PATH,json={'message':'Add encrypted mathematics problem tags','branch':BRANCH,'sha':result['sha'],'content':base64.b64encode(encrypted).decode('ascii')});response.raise_for_status()
        print(f'Added {count} mathematics problem tags.')
if __name__=='__main__':
    try: run()
    except Exception:
        print('Math tag import failed; check the exam name, secrets, permissions and concurrent changes.',file=sys.stderr)
        raise SystemExit(1) from None
