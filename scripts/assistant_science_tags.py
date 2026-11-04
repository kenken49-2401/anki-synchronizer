"""Add science subject tags from published entrance exam topic indexes."""
import base64, copy, json, os, sys
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pages_crypto import decrypt, encrypt, password_bytes
from scripts.assistant_exam_import import PATH, BRANCH, MAX_BYTES

ITEMS = json.loads("{\"1999\":{\"化学1\":[\"溶液\",\"蒸気圧降下\"],\"化学2\":[\"無機\",\"結晶\"],\"化学3\":[\"有機\",\"アニリン\"]},\"2000\":{\"物理1\":[\"荷電粒子\",\"円運動\"],\"物理2\":[\"回路\",\"磁場\"],\"物理3\":[\"熱力学\"],\"化学1\":[\"熱化学\",\"製鉄\"],\"化学2\":[\"無機\",\"溶解度積\"],\"化学3\":[\"芳香族\",\"アミノ酸\"]},\"2001\":{\"物理1\":[\"円運動\",\"衝突\"],\"物理2\":[\"電磁誘導\"],\"物理3\":[\"光の干渉\"],\"化学1\":[\"燃焼\",\"気体\"],\"化学2\":[\"無機\",\"銅\"],\"化学3\":[\"脂肪酸\",\"エステル\"]},\"2002\":{\"物理1\":[\"剛体\",\"摩擦\"],\"物理2\":[\"相互誘導\",\"変圧器\"],\"物理3\":[\"熱力学\"],\"化学1\":[\"化学平衡\",\"メタノール\"],\"化学2\":[\"無機\",\"溶解平衡\",\"錯イオン\"],\"化学3\":[\"脂肪酸\",\"構造決定\"]},\"2003\":{\"物理1\":[\"単振動\",\"衝突\"],\"物理2\":[\"電磁誘導\",\"平行レール\"],\"物理3\":[\"波の干渉\"],\"化学1\":[\"熱化学\",\"反応速度\",\"電池\"],\"化学2\":[\"無機\",\"滴定\",\"酸化還元\"],\"化学3\":[\"有機\",\"糖類\",\"異性体\"]},\"2004\":{\"物理1\":[\"二体問題\",\"摩擦\"],\"物理2\":[\"荷電粒子\"],\"物理3\":[\"熱力学\"],\"化学1\":[\"気体\",\"反応速度\"],\"化学2\":[\"結晶\",\"電気化学\",\"無機\"],\"化学3\":[\"高分子\",\"異性体\"]},\"2005\":{\"物理1\":[\"単振動\",\"衝突\"],\"物理2\":[\"電磁誘導\"],\"物理3\":[\"原子\",\"物質波\"],\"化学1\":[\"分子\",\"化学平衡\"],\"化学2\":[\"酸化還元\",\"アルミニウム\"],\"化学3\":[\"エステル\",\"異性体\"]},\"2006\":{\"物理1\":[\"円運動\",\"万有引力\"],\"物理2\":[\"自己誘導\",\"回路\"],\"物理3\":[\"気体分子運動論\"],\"化学1\":[\"燃焼\",\"熱化学\"],\"化学2\":[\"無機\",\"ケイ素\"],\"化学3\":[\"有機\",\"構造決定\"]},\"2007\":{\"物理1\":[\"単振動\",\"摩擦\"],\"物理2\":[\"電磁誘導\"],\"物理3\":[\"波の干渉\"],\"化学1\":[\"電離\",\"溶液\"],\"化学2\":[\"無機\",\"結晶\"],\"化学3\":[\"芳香族\",\"ペプチド\"]},\"2008\":{\"物理1\":[\"仕事とエネルギー\"],\"物理2\":[\"コンデンサー\",\"回路\"],\"物理3\":[\"気体の状態\"],\"化学1\":[\"熱化学\",\"電池\"],\"化学2\":[\"無機\",\"分配平衡\"],\"化学3\":[\"エステル\",\"有機反応\"]},\"2009\":{\"物理1\":[\"単振動\",\"衝突\"],\"物理2\":[\"電磁誘導\"],\"物理3\":[\"熱\",\"相変化\"],\"化学1\":[\"酸化還元\",\"熱化学\"],\"化学2\":[\"無機分析\",\"同位体\"],\"化学3\":[\"エステル\",\"異性体\"]},\"2010\":{\"物理1\":[\"円運動\"],\"物理2\":[\"回路\",\"電磁誘導\"],\"物理3\":[\"共鳴\",\"ドップラー効果\"],\"化学1\":[\"化学平衡\",\"反応速度\"],\"化学2\":[\"電池\",\"錯イオン\"],\"化学3\":[\"有機\",\"構造決定\",\"分離\"]},\"2011\":{\"物理1\":[\"二体問題\"],\"物理2\":[\"コンデンサー\",\"回路\"],\"物理3\":[\"熱力学\"],\"化学1\":[\"結合\",\"電離平衡\"],\"化学2\":[\"無機分析\",\"電気分解\"],\"化学3\":[\"炭化水素\",\"酸無水物\"]},\"2012\":{\"物理1\":[\"衝突\",\"運動量保存\"],\"物理2\":[\"電磁誘導\"],\"物理3\":[\"光の干渉\"],\"化学1\":[\"溶液\",\"凝固点降下\",\"浸透圧\"],\"化学2\":[\"結晶\",\"錯体\"],\"化学3\":[\"有機合成\",\"高分子\"]},\"2013\":{\"物理1\":[\"単振動\",\"衝突\"],\"物理2\":[\"荷電粒子\"],\"物理3\":[\"波の反射\",\"屈折\"],\"化学1\":[\"酸塩基\",\"化学平衡\"],\"化学2\":[\"錯体\",\"電気分解\",\"結合\"],\"化学3\":[\"高分子\",\"アミノ酸\"]},\"2014\":{\"物理1\":[\"単振動\",\"放物運動\"],\"物理2\":[\"回路\",\"太陽電池\"],\"物理3\":[\"光の回折\"],\"化学1\":[\"熱化学\",\"化学平衡\",\"反応速度\"],\"化学2\":[\"酸化還元\",\"無機\",\"溶解\"],\"化学3\":[\"糖類\",\"高分子\"]},\"2015\":{\"物理1\":[\"二体問題\",\"重心運動\"],\"物理2\":[\"電磁誘導\",\"平行レール\"],\"物理3\":[\"熱力学\",\"浮力\"],\"化学1\":[\"気体\",\"電離平衡\"],\"化学2\":[\"酸化還元\",\"ハロゲン\"],\"化学3\":[\"脂肪族\",\"芳香族\"]},\"2016\":{\"物理1\":[\"二体問題\",\"衝突\"],\"物理2\":[\"交流\",\"共振\"],\"物理3\":[\"波の反射\",\"屈折\"],\"化学1\":[\"溶解度\",\"蒸気圧\"],\"化学2\":[\"結晶\",\"酸化還元\",\"無機\"],\"化学3\":[\"芳香族\",\"構造決定\"]},\"2017\":{\"物理1\":[\"単振動\",\"摩擦\"],\"物理2\":[\"電磁誘導\"],\"物理3\":[\"熱力学\"],\"化学1\":[\"エステル\",\"高分子\"],\"化学2\":[\"金属イオン\",\"溶解度積\",\"窒素\"],\"化学3\":[\"電池\",\"電気分解\",\"化学平衡\"]},\"2018\":{\"物理1\":[\"二体問題\",\"振り子\"],\"物理2\":[\"コンデンサー\",\"単振動\"],\"物理3\":[\"熱力学\"],\"化学1\":[\"アミノ酸\",\"ペプチド\"],\"化学2\":[\"金属酸化物\",\"アルミニウム\"],\"化学3\":[\"電離平衡\",\"気体\",\"熱化学\"]},\"2019\":{\"物理1\":[\"単振動\",\"慣性力\"],\"物理2\":[\"交流回路\"],\"物理3\":[\"光の屈折\"],\"化学1\":[\"有機合成\",\"高分子\"],\"化学2\":[\"無機\",\"リン\",\"燃料電池\"],\"化学3\":[\"酸化還元滴定\",\"結晶\"]},\"2020\":{\"物理1\":[\"円運動\",\"万有引力\",\"原子\"],\"物理2\":[\"電磁誘導\",\"平行レール\"],\"物理3\":[\"熱力学\"],\"化学1\":[\"糖類\",\"高分子\"],\"化学2\":[\"無機\",\"分子構造\",\"結晶\"],\"化学3\":[\"中和\",\"pH\",\"無機\"]},\"2021\":{\"物理1\":[\"振り子\",\"円運動\"],\"物理2\":[\"コンデンサー\",\"電気振動\"],\"物理3\":[\"光の屈折\",\"原子\"],\"化学1\":[\"有機\",\"構造決定\",\"アニリン\"],\"化学2\":[\"化学平衡\",\"アミノ酸\",\"反応速度\"],\"化学3\":[\"沈殿滴定\",\"水素\"]},\"2022\":{\"物理1\":[\"万有引力\",\"円運動\"],\"物理2\":[\"電磁誘導\"],\"物理3\":[\"気体分子運動論\",\"熱力学\"],\"化学1\":[\"油脂\",\"アルケン\"],\"化学2\":[\"熱化学\",\"錯イオン\",\"結晶\"],\"化学3\":[\"状態変化\",\"反応速度\"]},\"2023\":{\"物理1\":[\"荷電粒子\",\"原子核\"],\"物理2\":[\"電磁気\",\"量子ホール効果\"],\"物理3\":[\"熱力学\"],\"化学1\":[\"芳香族\",\"異性体\"],\"化学2\":[\"無機\",\"電離平衡\",\"結晶\"],\"化学3\":[\"化学平衡\",\"コロイド\"]}}")

def merge(current):
    if not isinstance(current,dict) or current.get('schema_version') != 1 or not isinstance(current.get('scores'),list):
        raise ValueError('Invalid data')
    result=copy.deepcopy(current)
    papers=result.get('pastPapers',[])
    if not isinstance(papers,list): raise ValueError('Invalid papers')
    exams={p.get('exam') for p in papers if isinstance(p,dict) and p.get('subject')=='理科' and isinstance(p.get('exam'),str)}
    explicit={e for e in exams if any(s in e for s in ('東京大学','東大','理科過去問（スプシ）')) and '後期' not in e}
    if len(explicit)==1: exam=next(iter(explicit))
    elif len(exams)==1 and '後期' not in next(iter(exams)): exam=next(iter(exams))
    else: raise ValueError('Ambiguous science exam')
    catalog=result.setdefault('tagCatalog',{})
    count=0; covered=0
    for year, questions in ITEMS.items():
        matches=[p for p in papers if p.get('subject')=='理科' and p.get('exam')==exam and p.get('year')==int(year)]
        if len(matches)>1: raise ValueError('Duplicate year')
        if not matches: continue
        row=matches[0]; saved=row.setdefault('tagsByQuestion',{})
        if not isinstance(saved,dict): raise ValueError('Invalid tags')
        for question, incoming in questions.items():
            category='物理' if question.startswith('物理') else '化学'
            available=catalog.setdefault(category,[])
            existing=saved.setdefault(question,[])
            if not isinstance(available,list) or not isinstance(existing,list): raise ValueError('Invalid tag list')
            covered+=1
            for tag in incoming:
                if tag not in existing: existing.append(tag); count+=1
                if tag not in available: available.append(tag)
    if covered != sum(len(v) for v in ITEMS.values()): raise ValueError('Missing science years')
    return result,count,covered

def run():
    token=os.environ['GITHUB_TOKEN']; password=os.environ['STUDY_ATLAS_PASSWORD']
    if os.environ.get('GITHUB_REPOSITORY')!='kenken49-2401/anki-synchronizer': raise ValueError('Wrong repository')
    password_bytes(password)
    headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    with httpx.Client(base_url='https://api.github.com',headers=headers,timeout=60) as client:
        response=client.get(PATH,params={'ref':BRANCH});response.raise_for_status();obj=response.json()
        raw=base64.b64decode(''.join(obj['content'].split()),validate=True)
        if len(raw)>MAX_BYTES: raise ValueError('Data too large')
        updated,count,covered=merge(decrypt(json.loads(raw),password))
        if count:
            encrypted=json.dumps(encrypt(updated,password),separators=(',',':')).encode()
            response=client.put(PATH,json={'message':'Add science past-paper topic tags','branch':BRANCH,'sha':obj['sha'],'content':base64.b64encode(encrypted).decode('ascii')});response.raise_for_status()
        response=client.get(PATH,params={'ref':BRANCH});response.raise_for_status()
        verify=decrypt(json.loads(base64.b64decode(''.join(response.json()['content'].split()),validate=True)),password)
        _,remaining,checked=merge(verify)
        if remaining or checked!=covered: raise ValueError('Verification failed')
        print(f'Verified {checked} science questions; added {count} tags.')
if __name__=='__main__':
    try: run()
    except Exception:
        print('Science tag import failed: verify secrets, exam identity, years, and concurrent changes.',file=sys.stderr)
        raise SystemExit(1) from None
