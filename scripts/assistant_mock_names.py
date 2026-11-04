"""Correct the date of the 2026 autumn Kawai mock exam in encrypted data."""
import base64, json, os, re, sys
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pages_crypto import decrypt, encrypt, password_bytes
from scripts.assistant_exam_import import PATH, BRANCH, MAX_BYTES

def update_date(data):
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('scores'), list):
        raise ValueError('Invalid existing data')
    lookup = {'必勝模試1': ('第1回必勝模試', '2026-06-14'), '必勝1': ('第1回必勝模試', '2026-06-14'), '第1回必勝模試': ('第1回必勝模試', '2026-06-14'), '必勝模試2': ('第2回必勝模試', '2026-09-27'), '必勝2': ('第2回必勝模試', '2026-09-27'), '第2回必勝模試': ('第2回必勝模試', '2026-09-27'), 'OP2026秋': ('OP2026秋', '2026-10-25')}
    matched = changed = 0
    for score in data['scores']:
        if not isinstance(score, dict): continue
        name = score.get('name')
        if not isinstance(name, str): continue
        key = name.translate(str.maketrans('０１２３４５６７８９　', '0123456789 ')).replace(' ', '')
        if key not in lookup: continue
        new_name, date = lookup[key]
        matched += 1
        if (score.get('name'), score.get('date'), score.get('kind')) != (new_name, date, '模試'):
            score.update(name=new_name, date=date, kind='模試')
            changed += 1
    if not matched: raise ValueError('No matching records')
    return data, matched, changed

def run():
    if os.environ.get('GITHUB_REPOSITORY') != 'kenken49-2401/anki-synchronizer' or not os.environ.get('GITHUB_TOKEN'): raise ValueError('Invalid configuration')
    password=os.environ.get('STUDY_ATLAS_PASSWORD',''); password_bytes(password)
    headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    with httpx.Client(base_url='https://api.github.com',headers=headers,follow_redirects=False,timeout=60) as client:
        response=client.get(PATH,params={'ref':BRANCH});response.raise_for_status();result=response.json()
        if result.get('type')!='file' or result.get('encoding')!='base64' or not isinstance(result.get('sha'),str): raise ValueError('Existing data unavailable')
        raw=base64.b64decode(''.join(result['content'].split()),validate=True)
        if len(raw)>MAX_BYTES: raise ValueError('Data exceeds limit')
        updated,matched,changed=update_date(decrypt(json.loads(raw),password))
        if not changed: print(f'All matching records are already up to date.');return
        encrypted=json.dumps(encrypt(updated,password),separators=(',',':')).encode()
        if len(encrypted)>MAX_BYTES: raise ValueError('Encrypted result exceeds limit')
        response=client.put(PATH,json={'message':'Align mock exam names and dates','branch':BRANCH,'sha':result['sha'],'content':base64.b64encode(encrypted).decode('ascii')});response.raise_for_status()
        print(f'Updated names and dates on {changed} matching records.')
if __name__=='__main__':
    try: run()
    except Exception:
        print('Date update failed; check the matching exam, secrets, permissions, and concurrent changes.',file=sys.stderr)
        raise SystemExit(1) from None
