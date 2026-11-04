"""Apply user-provided photo classifications to encrypted Study Atlas data."""
import base64,copy,json,os,re,sys
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pages_crypto import decrypt,encrypt,password_bytes
from scripts.assistant_exam_import import PATH,BRANCH,MAX_BYTES
ALLOWED={'物理':{'単振動','中心力場','力学その他','熱力学','回路','荷電粒子','電磁誘導','交流','原子','光の干渉','ドップラー効果'},'化学':{'構造決定','高分子','有機その他','熱化学','結晶','平衡','反応速度','気体','溶液','電池・電気分解','無機'}}
def merge(current,payload):
    if not isinstance(current,dict) or current.get('schema_version')!=1 or not isinstance(current.get('scores'),list):raise ValueError('Invalid data')
    if not isinstance(payload,dict) or payload.get('format')!='study-atlas-photo-science-tags-v1' or not isinstance(payload.get('items'),list) or len(payload['items'])>1000:raise ValueError('Invalid payload')
    result=copy.deepcopy(current);papers=result.get('pastPapers',[])
    if not isinstance(papers,list):raise ValueError('Invalid papers')
    exams={p.get('exam') for p in papers if isinstance(p,dict) and p.get('subject')=='理科' and isinstance(p.get('exam'),str)}
    explicit={e for e in exams if any(s in e for s in ('東京大学','東大','理科過去問（スプシ）')) and '後期' not in e}
    if len(explicit)==1:exam=next(iter(explicit))
    elif len(exams)==1 and '後期' not in next(iter(exams)):exam=next(iter(exams))
    else:raise ValueError('Ambiguous science exam')
    count=0
    for item in payload['items']:
        if not isinstance(item,dict) or type(item.get('year')) is not int or not 1900<=item['year']<=2100:raise ValueError('Invalid year')
        name=item.get('name');tags=item.get('tags');m=re.fullmatch(r'(物理|化学)[123]',name or '')
        if not m or not isinstance(tags,list) or not tags or any(t not in ALLOWED[m.group(1)] for t in tags):raise ValueError('Invalid tags')
        matches=[p for p in papers if p.get('subject')=='理科' and p.get('exam')==exam and p.get('year')==item['year']]
        if len(matches)!=1:raise ValueError('Missing or duplicate year')
        row=matches[0];saved=row.setdefault('tagsByQuestion',{});old=saved.get(name,[])
        if not isinstance(old,list) or any(not isinstance(t,str) for t in old):raise ValueError('Invalid existing tags')
        # Keep user-created tags, and retain every previous value in an encrypted backup.
        new=list(dict.fromkeys(tags+[t for t in old if t not in ALLOWED[m.group(1)]]))
        if old!=new:
            row.setdefault('prePhotoScienceTags',{}).setdefault(name,old[:]);saved[name]=new;count+=1
    return result,count

def run():
    if os.environ.get('GITHUB_REPOSITORY')!='kenken49-2401/anki-synchronizer' or not os.environ.get('GITHUB_TOKEN'):raise ValueError('Invalid configuration')
    password,key=os.environ.get('STUDY_ATLAS_PASSWORD',''),os.environ.get('ASSISTANT_IMPORT_KEY','');password_bytes(password);password_bytes(key)
    payload=decrypt(json.loads(Path('assistant-import/photo-science-tags.enc.json').read_bytes()),key)
    headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    with httpx.Client(base_url='https://api.github.com',headers=headers,follow_redirects=False,timeout=60) as client:
        response=client.get(PATH,params={'ref':BRANCH});response.raise_for_status();result=response.json()
        if result.get('type')!='file' or result.get('encoding')!='base64' or not isinstance(result.get('sha'),str):raise ValueError('Existing data unavailable')
        raw=base64.b64decode(''.join(result['content'].split()),validate=True)
        if len(raw)>MAX_BYTES:raise ValueError('Data exceeds limit')
        updated,count=merge(decrypt(json.loads(raw),password),payload)
        if not count:print('No new science tags to apply.');return
        encrypted=json.dumps(encrypt(updated,password),separators=(',',':')).encode()
        if len(encrypted)>MAX_BYTES:raise ValueError('Encrypted result exceeds limit')
        response=client.put(PATH,json={'message':'Apply photo-based science problem tags','branch':BRANCH,'sha':result['sha'],'content':base64.b64encode(encrypted).decode('ascii')});response.raise_for_status();print(f'Updated {count} science problems.')
if __name__=='__main__':
    try:run()
    except Exception:
        print('Photo tag update failed; check data, exam matching, secrets, and concurrent changes.',file=sys.stderr)
        raise SystemExit(1) from None
