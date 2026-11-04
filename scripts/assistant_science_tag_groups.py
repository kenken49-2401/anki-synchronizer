"""Consolidate science tags while retaining original tag names in encrypted data."""
import base64,json,os,re,sys
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pages_crypto import decrypt,encrypt,password_bytes
from scripts.assistant_exam_import import PATH,BRANCH,MAX_BYTES

def science_tag(tag,category):
    if category=='物理' and '力学的波動' in tag:return None
    rules={'物理':[(r'単振動|振り子','単振動'),(r'中心力場|二体問題|万有引力|惑星|ケプラー','中心力場'),(r'熱|気体|相変化','熱力学'),(r'ドップラー','ドップラー効果'),(r'光の干渉|光の回折|干渉','光の干渉'),(r'量子|物質波|光電|原子|原子核|放射','原子'),(r'交流','交流'),(r'電磁誘導|自己誘導|相互誘導|変圧器|平行レール','電磁誘導'),(r'荷電|ローレンツ|磁場中.*粒子','荷電粒子'),(r'回路|コンデンサ|電池|電流|電気振動','回路'),(r'力学|運動|衝突|剛体|仕事|摩擦|浮力|慣性力','力学その他')], '化学':[(r'構造決定','構造決定'),(r'高分子|重合|樹脂|繊維','高分子'),(r'熱化学|燃焼熱|反応熱','熱化学'),(r'結晶','結晶'),(r'電池|電気分解|電気化学','電池・電気分解'),(r'反応速度','反応速度'),(r'平衡|電離|溶解度積','平衡'),(r'気体|蒸気圧','気体'),(r'溶液|溶解|溶解度|浸透圧|凝固点|滴定|pH|中和','溶液'),(r'有機|芳香族|脂肪族|アニリン|アミノ酸|アルケン|エステル|ペプチド|メタノール|油脂|炭化水素|糖類|脂肪酸|異性体|酸無水物','有機その他')]}
    return next((value for pattern,value in rules.get(category,[]) if re.search(pattern,tag)),None)

def migrate(data):
    if not isinstance(data,dict) or data.get('schema_version')!=1 or not isinstance(data.get('scores'),list): raise ValueError('Invalid data')
    if data.get('scienceTagVersion')==2:return data,False
    catalog=data.get('tagCatalog') or {};hidden=data.get('hiddenTags') or {}
    if not isinstance(catalog,dict) or not isinstance(hidden,dict):raise ValueError('Invalid catalogs')
    data.setdefault('scienceTagArchive',{'catalog':{cat:list(catalog.get(cat,[])) for cat in ('物理','化学')},'hidden':{cat:list(hidden.get(cat,[])) for cat in ('物理','化学')}})
    for obj in (catalog,hidden):
        for cat in ('物理','化学'):obj[cat]=[]
    if 'tagCatalog' in data:data['tagCatalog']=catalog
    if 'hiddenTags' in data:data['hiddenTags']=hidden
    coarse={'力学','電磁気','熱力学','波動','原子','理論化学','無機化学','有機化学','高分子化学','その他'}
    def change(obj,field,category):
        current=obj.get(field)
        if not isinstance(current,list):return
        if any(not isinstance(t,str) for t in current):raise ValueError('Invalid tags')
        legacy=obj.setdefault('legacyScienceTags',{})
        old=legacy.get(field)
        source=current if old is None else old+[t for t in current if t not in coarse]
        legacy.setdefault(field,current[:])
        def convert(tag):
            if category=='理科':return science_tag(tag,'物理') or science_tag(tag,'化学')
            return science_tag(tag,category)
        obj[field]=list(dict.fromkeys(t for t in map(convert,source) if t is not None))
    for score in data['scores']:
        if not isinstance(score,dict):continue
        subject=score.get('subject')
        if subject in ('物理','化学','理科'):change(score,'subjectTags',subject)
        for q in score.get('questions') or []:
            if not isinstance(q,dict):continue
            name=q.get('name','')
            cat=('物理' if name.startswith('物理') else '化学' if name.startswith('化学') else None) if subject=='理科' and isinstance(name,str) else subject
            if cat in ('物理','化学'):change(q,'tags',cat)
    for row in data.get('pastPapers') or []:
        if not isinstance(row,dict):continue
        for name,tags in (row.get('tagsByQuestion') or {}).items():
            subject=row.get('subject');cat=('物理' if name.startswith('物理') else '化学' if name.startswith('化学') else None) if subject=='理科' else subject
            if cat not in ('物理','化学') or not isinstance(tags,list):continue
            previous=(row.get('legacyScienceTagsByQuestion') or {}).get(name)
            holder={'tags':tags,'legacyScienceTags':{'tags':previous} if previous is not None else {}};change(holder,'tags',cat)
            row.setdefault('legacyScienceTagsByQuestion',{}).setdefault(name,holder['legacyScienceTags']['tags']);row['tagsByQuestion'][name]=holder['tags']
    data['scienceTagVersion']=2
    return data,True

def run():
    if os.environ.get('GITHUB_REPOSITORY')!='kenken49-2401/anki-synchronizer' or not os.environ.get('GITHUB_TOKEN'):raise ValueError('Invalid configuration')
    password=os.environ.get('STUDY_ATLAS_PASSWORD','');password_bytes(password)
    headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    with httpx.Client(base_url='https://api.github.com',headers=headers,follow_redirects=False,timeout=60) as client:
        response=client.get(PATH,params={'ref':BRANCH});response.raise_for_status();result=response.json()
        if result.get('type')!='file' or result.get('encoding')!='base64' or not isinstance(result.get('sha'),str):raise ValueError('Existing data unavailable')
        raw=base64.b64decode(''.join(result['content'].split()),validate=True)
        if len(raw)>MAX_BYTES:raise ValueError('Data exceeds limit')
        updated,changed=migrate(decrypt(json.loads(raw),password))
        if not changed:print('Science tags were already consolidated.');return
        encrypted=json.dumps(encrypt(updated,password),separators=(',',':')).encode()
        if len(encrypted)>MAX_BYTES:raise ValueError('Encrypted result exceeds limit')
        response=client.put(PATH,json={'message':'Consolidate encrypted science tags','branch':BRANCH,'sha':result['sha'],'content':base64.b64encode(encrypted).decode('ascii')});response.raise_for_status();print('Science tags consolidated.')
if __name__=='__main__':
    try:run()
    except Exception:
        print('Science tag update failed; check data, secrets, permissions, and concurrent changes.',file=sys.stderr)
        raise SystemExit(1) from None

