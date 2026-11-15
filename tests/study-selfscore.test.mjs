import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../web/study-atlas.html',import.meta.url),'utf8');
const line=key=>{const i=source.indexOf(key);assert(i>=0,key);return source.slice(i,source.indexOf('\n',i))};
const block=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const helpers=block('const goalMax=','const goalLabels=').replace(/function setExamFormat[\s\S]*/,'');
function api(format='secondary',classView=false){return new Function('format','classView',`const $=()=>({value:classView?'class':'standard'});${helpers}\n${['function sumDecimal(','function completeSum(','const complete=','function selfScoreValue(','function subjectScoreSeries(','function questionTotals(','function scienceSubjectView(','const resultSubjects=','const resultTotal=','function totalExamPoints('].map(line).join('\n')}\n${block('function completeExamSets(','function deleteButton(')}\nactiveExamFormat=format;return {selfScoreValue,subjectScoreSeries,scienceSubjectView,completeExamSets,totalExamPoints,subjects:formatSubjects()}`)(format,classView)}
const record=(subject,extra={})=>({id:subject,kind:'模試',name:'テスト模試',date:'2026-11-01',subject,max:100,score:0,scoreComplete:false,selfscore:40,...extra});

test('question self scores are authoritative; missing, invalid and zero stay distinct',()=>{
 const {selfScoreValue}=api();
 assert.equal(selfScoreValue(record('数学',{selfscore:0})),0);
 for(const selfscore of [null,undefined,NaN,Infinity,-1,101,'0'])assert.equal(selfScoreValue(record('数学',{selfscore})),null);
 const questions=[{name:'1',max:50,selfscore:0},{name:'2',max:50,selfscore:12.3}];
 assert.equal(selfScoreValue(record('数学',{selfscore:99,questions})),12.3);
 assert.equal(selfScoreValue(record('数学',{selfscore:99,questions:[questions[0],{...questions[1],selfscore:null}]})),null);
});

test('exam selector accepts all self scores, while official total chart stays official',()=>{
 for(const format of ['secondary','common'])for(const classView of [false,...(format==='secondary'?[true]:[])]){
  const a=api(format,classView),subjects=classView?['数学','英語','化学']:a.subjects;
  const rows=subjects.map(subject=>record(subject,{examFormat:format,kind:classView?'授業内演習':'模試'}));
  const original=JSON.stringify(rows);
  assert.equal(a.completeExamSets(rows).length,1);
  assert.equal(a.completeExamSets(rows)[0].selfComplete,true);
  assert.equal(a.totalExamPoints(rows).length,0);
  assert.equal(a.completeExamSets(rows.slice(1)).length,0);
  assert.equal(a.completeExamSets([...rows,{...rows[0],id:'duplicate'}]).length,0);
  assert.equal(a.completeExamSets(rows.map((r,i)=>i? r:{...r,selfscore:null})).length,0);
  assert.equal(a.completeExamSets(rows.map((r,i)=>i? r:{...r,selfscore:null,score:40,scoreComplete:true})).length,0,'mixed sources cannot produce a full total');
  assert.equal(a.completeExamSets(rows.map(r=>({...r,selfscore:0}))).length,1);
  assert.equal(a.totalExamPoints(rows.map(r=>({...r,score:20,scoreComplete:true}))).length,1);
  assert.equal(JSON.stringify(rows),original,'display does not mutate records');
 }
});

test('dates, kinds, formats and legacy partial exceptions keep their boundaries',()=>{
 const a=api(),rows=a.subjects.map(subject=>record(subject));
 assert.equal(a.completeExamSets(rows.map((r,i)=>i? r:{...r,date:'2026-11-02'})).length,0);
 assert.equal(a.completeExamSets(rows.map((r,i)=>i? r:{...r,kind:'過去問'})).length,0);
 assert.equal(a.completeExamSets(rows.map((r,i)=>i? r:{...r,examFormat:'common'})).length,0);
 assert.equal(a.completeExamSets(rows.map((r,i)=>i? r:{...r,date:''})).length,1,'existing one-date grouping is retained');
 assert.equal(a.completeExamSets([{...rows[0],name:'OP2026秋',selfscore:null}]).length,1);
 const official=rows.map(r=>({...r,selfscore:null,scoreComplete:true,score:0}));
 assert.equal(a.completeExamSets(official).length,1);
 assert.equal(a.totalExamPoints(official)[0].values.reduce((x,y)=>x+y,0),0);
});

test('subject series includes self-only points, gaps and both scores without substituting zero',()=>{
 const a=api(),rows=[record('数学'),record('数学',{selfscore:null}),record('数学',{scoreComplete:true,score:0,selfscore:null}),record('数学',{scoreComplete:true,score:60,selfscore:70})];
 assert.deepEqual(a.subjectScoreSeries(rows).map(({score,selfscore})=>({score,selfscore})),[{score:null,selfscore:40},{score:0,selfscore:null},{score:60,selfscore:70}]);
 const questions=['物理1','物理2','物理3','化学1','化学2Ⅰ','化学2Ⅱ','化学3'].map(name=>({name,max:name.includes('Ⅱ')||name.includes('Ⅰ')?10:20,score:null,selfscore:0}));
 const science=record('理科',{max:120,questions,selfscore:0});
 assert.equal(a.selfScoreValue(a.scienceSubjectView(science,'化学')),0);
 assert.equal(a.selfScoreValue(a.scienceSubjectView({...science,questions:questions.filter(q=>q.name!=='化学2Ⅱ')},'化学')),null);
 assert.equal(a.selfScoreValue(a.scienceSubjectView({...science,questions:questions.map(q=>q.name==='物理2'?{...q,selfscore:null}:q)},'物理')),null);
});

test('chart uses separate dashed diamonds and official points; tooltips identify the source',()=>{
 const drawn=[],dashes=[],arcs=[],strokes=[],tooltips=[];
 const c=new Proxy({measureText:t=>({width:t.length*6}),setLineDash:v=>dashes.push(v),moveTo:(...p)=>drawn.push(p),lineTo:(...p)=>drawn.push(p),arc:(...p)=>arcs.push(p),stroke(){strokes.push(this.lineWidth)}},{get:(o,k)=>k in o?o[k]:()=>{}});
 const draw=new Function('canvas','getComputedStyle','devicePixelRatio','chartColor','drawGoalBands','setupChartTooltip',line('function lineChart(')+`;lineChart(canvas,['2026-11-01','2026-11-02','2026-11-03'],[null,0,50],100,['','得点 0','得点 50'],null,0,[40,null,60],['自己採点 40','','自己採点 60'])`);
 draw({clientWidth:390,getContext:()=>c},()=>({getPropertyValue:()=> '#59a875'}),1,(l)=>l,()=>{},(canvas,points,details)=>tooltips.push({points,details}));
 assert.deepEqual(dashes,[[6,4],[]]);
 assert.equal(arcs.length,2);
 assert(drawn.every(p=>p.every(Number.isFinite)));
 assert.deepEqual(tooltips[0].details,['自己採点 40','自己採点 60','得点 0','得点 50']);
});
