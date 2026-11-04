"""Safely merge an encrypted science past-paper reference into user data."""
from __future__ import annotations
import base64, copy, json, math, os, sys, uuid
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pages_crypto import decrypt, encrypt, password_bytes
from scripts.assistant_exam_import import PATH, BRANCH, MAX_BYTES

def merge_reference(current, payload):
    if not isinstance(current,dict) or current.get('schema_version') != 1 or not isinstance(current.get('scores'),list):
        raise ValueError('Invalid current data')
    if not isinstance(payload,dict) or payload.get('format') != 'study-atlas-science-reference-v1' or not isinstance(payload.get('items'),list) or len(payload['items']) > 150:
        raise ValueError('Invalid payload')
    updated=copy.deepcopy(current)
    reference=updated.setdefault('scienceReference',{})
    papers=updated.setdefault('pastPapers',[])
    if not isinstance(reference,dict) or not isinstance(papers,list): raise ValueError('Invalid existing data')
    science_exams={p.get('exam') for p in papers if p.get('subject')=='理科' and isinstance(p.get('exam'),str)}
    target=next(iter(science_exams)) if len(science_exams)==1 else '理科過去問（スプシ）'
    count=0
    for item in payload['items']:
        year=item.get('year') if isinstance(item,dict) else None
        questions=item.get('questions') if isinstance(item,dict) else None
        if not isinstance(year,str) or len(year)!=4 or not year.isdigit() or not 1900<=int(year)<=2100 or not isinstance(questions,dict): raise ValueError('Invalid year')
        for name, q in questions.items():
            if name not in ('物理1','物理2','物理3','化学1','化学2','化学3') or not isinstance(q,dict): raise ValueError('Invalid question')
            for field in ('score','minutes'):
                v=q.get(field)
                if v is not None and (type(v) not in (int,float) or not math.isfinite(v) or v<0): raise ValueError('Invalid value')
        if year not in reference:
            reference[year]=copy.deepcopy(questions); count+=1
        if not any(p.get('subject')=='理科' and p.get('year')==int(year) for p in papers):
            papers.append({'id':str(uuid.uuid4()),'exam':target,'subject':'理科','year':int(year),'statuses':{}}); count+=1
    return updated,count

def run():
    if os.environ.get('GITHUB_REPOSITORY')!='kenken49-2401/anki-synchronizer' or not os.environ.get('GITHUB_TOKEN'): raise ValueError('Invalid configuration')
    password,key=os.environ.get('STUDY_ATLAS_PASSWORD',''),os.environ.get('ASSISTANT_IMPORT_KEY','')
    password_bytes(password);password_bytes(key)
    payload=decrypt(json.loads(Path('assistant-import/science-reference.enc.json').read_bytes()),key)
    headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    with httpx.Client(base_url='https://api.github.com',headers=headers,follow_redirects=False,timeout=60) as client:
        response=client.get(PATH,params={'ref':BRANCH});response.raise_for_status();result=response.json()
        if result.get('type')!='file' or result.get('encoding')!='base64' or not isinstance(result.get('sha'),str): raise ValueError('Existing data unavailable')
        raw=base64.b64decode(''.join(result['content'].split()),validate=True)
        if len(raw)>MAX_BYTES: raise ValueError('Data exceeds limit')
        updated,count=merge_reference(decrypt(json.loads(raw),password),payload)
        if not count:
            print('No new science reference to add.');return
        encrypted=json.dumps(encrypt(updated,password),separators=(',',':')).encode()
        if len(encrypted)>MAX_BYTES: raise ValueError('Encrypted result exceeds limit')
        response=client.put(PATH,json={'message':'Add encrypted science reference','branch':BRANCH,'sha':result['sha'],'content':base64.b64encode(encrypted).decode('ascii')});response.raise_for_status()
        print(f'Added {count} science reference items and years.')
if __name__=='__main__':
    try: run()
    except Exception:
        print('Reference import failed; check secrets, permissions and concurrent changes.',file=sys.stderr)
        raise SystemExit(1) from None
