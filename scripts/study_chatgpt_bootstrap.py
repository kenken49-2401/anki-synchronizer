"""Create a transient encrypted full study snapshot for the private reminder setup."""
import base64,datetime,json,os,sys
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pages_crypto import decrypt,encrypt,password_bytes
from scripts.assistant_exam_import import PATH,BRANCH,MAX_BYTES

def run():
    if os.environ.get('GITHUB_REPOSITORY')!='kenken49-2401/anki-synchronizer': raise ValueError('Wrong repository')
    password=os.environ.get('STUDY_ATLAS_PASSWORD',''); import_key=os.environ.get('ASSISTANT_IMPORT_KEY','');password_bytes(password);password_bytes(import_key)
    headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    with httpx.Client(base_url='https://api.github.com',headers=headers,timeout=60) as client:
        response=client.get(PATH,params={'ref':BRANCH});response.raise_for_status();body=response.json()
        if body.get('type')!='file' or body.get('encoding')!='base64': raise ValueError('Missing study data')
        source_sha=body['sha'];raw=base64.b64decode(''.join(body['content'].split()),validate=True)
        if len(raw)>MAX_BYTES:raise ValueError('Data too large')
        source=decrypt(json.loads(raw),password)
        if not isinstance(source,dict) or source.get('schema_version')!=1 or not isinstance(source.get('tasks'),list):raise ValueError('Invalid study data')
        snapshot={'format':'study-atlas-chatgpt-v1','status':'ready','generatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sourceRevision':source_sha,'data':source}
        encrypted=json.dumps(encrypt(snapshot,import_key),separators=(',',':')).encode()
        if len(encrypted)>MAX_BYTES:raise ValueError('Snapshot too large')
        outpath='/repos/kenken49-2401/anki-synchronizer/contents/study-data/chatgpt-bootstrap.enc.json'
        prior=client.get(outpath,params={'ref':BRANCH});args={'message':'Prepare encrypted ChatGPT bootstrap','branch':BRANCH,'content':base64.b64encode(encrypted).decode()}
        if prior.status_code==200:args['sha']=prior.json()['sha']
        elif prior.status_code!=404:prior.raise_for_status()
        written=client.put(outpath,json=args);written.raise_for_status()
        print('Encrypted ChatGPT bootstrap prepared.')
if __name__=='__main__':
    try:run()
    except Exception:
        print('ChatGPT bootstrap failed; check secrets, permissions, and concurrent changes.',file=sys.stderr)
        raise SystemExit(1) from None
