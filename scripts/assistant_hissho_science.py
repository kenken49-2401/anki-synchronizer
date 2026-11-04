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
    items=payload.get('items') if isinstance(payload,dict) and payload.get('format')=='study-atlas-hissho-science-v1' else None
    if not isinstance(items,list) or len(items)!=1: raise ValueError('Invalid payload')
    item=items[0]
    if (item.get('name'),item.get('date'),item.get('subject'),item.get('score')) != ('第2回必勝模試','2026-09-27','理科',48): raise ValueError('Invalid record')
    updated=copy.deepcopy(current)
    matches=[i for i,x in enumerate(updated['scores']) if isinstance(x,dict) and x.get('name')==item['name'] and x.get('subject')=='理科' and x.get('date')==item['date']]
    if len(matches)!=1: raise ValueError('Record not uniquely identified')
    index=matches[0]; old=updated['scores'][index]
    if old.get('score')==48 and old.get('sourceKey')==item.get('sourceKey'): return updated,0
    if old.get('score')!=79: raise ValueError('Existing score changed')
    replacement=copy.deepcopy(item); replacement['id']=old['id']; replacement['previousImportedRecord']=copy.deepcopy(old)
    updated['scores'][index]=replacement
    return updated,1

def run():
    if os.environ.get('GITHUB_REPOSITORY')!='kenken49-2401/anki-synchronizer' or not os.environ.get('GITHUB_TOKEN'): raise ValueError('Invalid configuration')
    password,key=os.environ.get('STUDY_ATLAS_PASSWORD',''),os.environ.get('ASSISTANT_IMPORT_KEY','')
    password_bytes(password);password_bytes(key)
    payload=decrypt(json.loads(Path('assistant-import/hissho-science.enc.json').read_bytes()),key)
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
        response=client.put(PATH,json={'message':'Correct encrypted mock science score','branch':BRANCH,'sha':result['sha'],'content':base64.b64encode(encrypted).decode('ascii')});response.raise_for_status()
        print(f'Corrected {count} science record.')
if __name__=='__main__':
    try: run()
    except Exception:
        print('Reference import failed; check secrets, permissions and concurrent changes.',file=sys.stderr)
        raise SystemExit(1) from None
