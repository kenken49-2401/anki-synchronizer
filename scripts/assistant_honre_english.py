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
    matches = [s for s in data['scores'] if isinstance(s, dict) and s.get('name') == '本レ2026-2' and s.get('subject') == '英語' and s.get('date') == '2026-08-30']
    if len(matches) != 1: raise ValueError('Expected exactly one matching record')
    record = matches[0]
    questions = record.get('questions')
    if not isinstance(questions, list): raise ValueError('Missing questions')
    expected = {'1': (7, [('1A', 7), ('1B', 0)]), '2': (21, [('2A', 9), ('2B', 12)]), '3': (12, []), '4': (10, [('4A', 4), ('4B', 6)]), '5': (8, [])}
    if len(questions) != 5 or set(q.get('name') for q in questions) != set(expected): raise ValueError('Unexpected question structure')
    if record.get('score') != 58 or record.get('scoreComplete') is False: raise ValueError('Unexpected total')
    changed = 0
    for q in questions:
        total, subparts = expected[q['name']]
        if q.get('score') != total: raise ValueError('Existing score does not match')
        if subparts:
            desired = [{'name': name, 'score': score} for name, score in subparts]
            if q.get('subparts') and q['subparts'] != desired: raise ValueError('Existing subparts differ')
            if q.get('subparts') != desired: q['subparts'] = desired; changed += 1
    return data, 1, changed

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
        if not changed: print(f'The subquestion scores are already up to date.');return
        encrypted=json.dumps(encrypt(updated,password),separators=(',',':')).encode()
        if len(encrypted)>MAX_BYTES: raise ValueError('Encrypted result exceeds limit')
        response=client.put(PATH,json={'message':'Add English subquestion scores to encrypted mock exam','branch':BRANCH,'sha':result['sha'],'content':base64.b64encode(encrypted).decode('ascii')});response.raise_for_status()
        print(f'Updated subquestion scores for {changed} questions.')
if __name__=='__main__':
    try: run()
    except Exception:
        print('Date update failed; check the matching exam, secrets, permissions, and concurrent changes.',file=sys.stderr)
        raise SystemExit(1) from None
