"""Safely merge an encrypted science past-paper reference into user data."""
from __future__ import annotations
import base64, copy, json, math, os, sys, uuid
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pages_crypto import decrypt, encrypt, password_bytes
from scripts.assistant_exam_import import PATH, BRANCH, MAX_BYTES

def merge_reference(current,payload):
    if not isinstance(current,dict) or current.get('schema_version')!=1 or not isinstance(current.get('scores'),list): raise ValueError('Invalid data')
    items=payload.get('items') if isinstance(payload,dict) and payload.get('format')=='study-atlas-hissho-v1' else None
    if not isinstance(items,list) or len(items)>8: raise ValueError('Invalid payload')
    updated=copy.deepcopy(current); count=0; skipped=0
    for item in items:
        matches=[x for x in updated['scores'] if isinstance(x,dict) and x.get('name')==item['name'] and x.get('subject')==item['subject'] and x.get('date')==item['date']]
        if len(matches)>1: skipped+=1; continue
        if not matches:
            row=copy.deepcopy(item); row['id']=str(uuid.uuid4()); updated['scores'].append(row); count+=1; continue
        row=matches[0]; existing=row.get('questions')
        if not isinstance(existing,list) or len(existing)!=len(item['questions']): skipped+=1; continue
        old={q.get('name'):q for q in existing}
        if len(old)!=len(existing) or set(old)!=set(q['name'] for q in item['questions']): skipped+=1; continue
        if any(old[q['name']].get('score') is not None and q['score'] is not None and old[q['name']]['score']!=q['score'] for q in item['questions']): skipped+=1; continue
        before=copy.deepcopy(row)
        for q in item['questions']:
            target=old[q['name']]
            for field in ('score','average','selfscore','feeling','max','subparts'):
                if target.get(field) is None and q.get(field) is not None: target[field]=copy.deepcopy(q[field])
        for field in ('average','selfscore','feeling','reportedScore'):
            if row.get(field) is None and item.get(field) is not None: row[field]=item[field]
        if before.get('average') is None and item.get('average') is not None: row['averageSource']='reported'
        if row!=before: count+=1
    print(f'Skipped {skipped} conflicting or ambiguous records.')
    return updated,count

def run():
    if os.environ.get('GITHUB_REPOSITORY')!='kenken49-2401/anki-synchronizer' or not os.environ.get('GITHUB_TOKEN'): raise ValueError('Invalid configuration')
    password,key=os.environ.get('STUDY_ATLAS_PASSWORD',''),os.environ.get('ASSISTANT_IMPORT_KEY','')
    password_bytes(password);password_bytes(key)
    payload=decrypt(json.loads(Path('assistant-import/hissho-scores.enc.json').read_bytes()),key)
    headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    with httpx.Client(base_url='https://api.github.com',headers=headers,follow_redirects=False,timeout=60) as client:
        response=client.get(PATH,params={'ref':BRANCH});response.raise_for_status();result=response.json()
        if result.get('type')!='file' or result.get('encoding')!='base64' or not isinstance(result.get('sha'),str): raise ValueError('Existing data unavailable')
        raw=base64.b64decode(''.join(result['content'].split()),validate=True)
        if len(raw)>MAX_BYTES: raise ValueError('Data exceeds limit')
        updated,count=merge_reference(decrypt(json.loads(raw),password),payload)
        if not count:
            print('No new subject records to add.');return
        encrypted=json.dumps(encrypt(updated,password),separators=(',',':')).encode()
        if len(encrypted)>MAX_BYTES: raise ValueError('Encrypted result exceeds limit')
        response=client.put(PATH,json={'message':'Import encrypted mock scores','branch':BRANCH,'sha':result['sha'],'content':base64.b64encode(encrypted).decode('ascii')});response.raise_for_status()
        print(f'Imported or supplemented {count} subject records.')
if __name__=='__main__':
    try: run()
    except Exception:
        print('Reference import failed; check secrets, permissions and concurrent changes.',file=sys.stderr)
        raise SystemExit(1) from None
