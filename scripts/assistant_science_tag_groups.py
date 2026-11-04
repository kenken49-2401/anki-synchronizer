"""Consolidate science tags while retaining original tag names in encrypted data."""
import base64,json,os,re,sys
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pages_crypto import decrypt,encrypt,password_bytes
from scripts.assistant_exam_import import PATH,BRANCH,MAX_BYTES

def science_tag(tag,category):
    rules={'物理':[(r'力学的波動','波動'),(r'光電|量子|物質波|原子|原子核|放射','原子'),(r'力学|二体|単振動|運動|衝突|剛体|万有引力|仕事|振り子|摩擦|浮力|慣性力','力学'),(r'電磁|電場|磁場|電気|電流|回路|荷電|コンデンサ|ローレンツ|交流|変圧器|太陽電池|平行レール|誘導','電磁気'),(r'熱|気体|相変化','熱力学'),(r'波|音|光|干渉|振動|ドップラー|屈折|共振|共鳴','波動'),(r'原子|量子|光電|核|放射','原子')], '化学':[(r'高分子|重合|樹脂|繊維','高分子化学'),(r'有機|構造決定|芳香族|脂肪族|アニリン|アミノ酸|アルケン|エステル|ペプチド|メタノール|油脂|炭化水素|糖類|脂肪酸|異性体|酸無水物','有機化学'),(r'無機|金属|非金属|アルミニウム|ケイ素|ハロゲン|窒素|製鉄|銅|錯イオン|錯体|リン','無機化学'),(r'理論|熱化学|溶液|平衡|電池|電気分解|電気化学|反応速度|結晶|酸|塩基|酸化|還元|化学量|気体|pH|コロイド|中和|凝固点|分子|分離|同位体|水素|沈殿|浸透圧|溶解|滴定|蒸気圧|状態変化|結合|電離|燃焼','理論化学')]}
    return next((value for pattern,value in rules.get(category,[]) if re.search(pattern,tag)), 'その他')

def migrate(data):
    if not isinstance(data,dict) or data.get('schema_version')!=1 or not isinstance(data.get('scores'),list): raise ValueError('Invalid data')
    if data.get('scienceTagVersion')==1:return data,False
    catalog=data.get('tagCatalog') or {};hidden=data.get('hiddenTags') or {}
    if not isinstance(catalog,dict) or not isinstance(hidden,dict):raise ValueError('Invalid catalogs')
    data['scienceTagArchive']={'catalog':{cat:list(catalog.get(cat,[])) for cat in ('物理','化学')},'hidden':{cat:list(hidden.get(cat,[])) for cat in ('物理','化学')}}
    for obj in (catalog,hidden):
        for cat in ('物理','化学'):obj[cat]=[]
    if 'tagCatalog' in data:data['tagCatalog']=catalog
    if 'hiddenTags' in data:data['hiddenTags']=hidden
    def change(obj,field,category):
        old=obj.get(field)
        if not isinstance(old,list):return
        if any(not isinstance(t,str) for t in old):raise ValueError('Invalid tags')
        def convert(tag):
            if category=='理科':
                physical=science_tag(tag,'物理')
                return physical if physical!='その他' else science_tag(tag,'化学')
            return science_tag(tag,category)
        new=list(dict.fromkeys(map(convert,old)))
        if old!=new:
            obj.setdefault('legacyScienceTags',{}).setdefault(field,old[:]);obj[field]=new
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
            holder={'tags':tags};change(holder,'tags',cat)
            if holder.get('legacyScienceTags'):
                row.setdefault('legacyScienceTagsByQuestion',{}).setdefault(name,holder['legacyScienceTags']['tags']);row['tagsByQuestion'][name]=holder['tags']
    data['scienceTagVersion']=1
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
