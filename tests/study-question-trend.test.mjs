import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../web/study-atlas.html',import.meta.url),'utf8');
const code=source.slice(source.indexOf('function questionTrendRows('),source.indexOf('function renderQuestionTrend('));
const api=format=>new Function('activeExamFormat',code+';return questionTrendRows')(format);
const record=(subject,questions,extra={})=>({subject,questions,date:'2026-11-01',kind:'模試',name:'サンプル',...extra});
const q=(name,extra={})=>({name,max:20,score:0,selfscore:10,...extra});

test('preserves zero, missing scores, unknown allocations and partial subject records',()=>{
 const rows=[record('数学',[q('1'),q('2',{score:null,selfscore:0}),q('3',{score:undefined,selfscore:undefined}),q('4',{max:null,score:7,selfscore:8})],{scoreComplete:false})];
 const before=JSON.stringify(rows),result=api('secondary')(rows,'数学');
 assert.deepEqual(result.map(x=>[x.score,x.selfscore,x.max]),[[0,10,20],[null,0,20],[null,null,20],[7,8,null]]);
 assert.equal(JSON.stringify(rows),before,'read-only series never changes source records');
 assert.deepEqual(api('secondary')([record('数学',[],{parts:[0,null,12]})],'数学').map(x=>[x.part,x.score,x.max]),[['大問1',0,null],['大問2',null,null],['大問3',12,null]]);
});

test('science subsets and split English/chemistry keep saved names without double counting',()=>{
 const rows=[record('理科',[q('物理1'),q('化学1'),q('化学2Ⅰ'),q('化学2Ⅱ')]),record('化学',[q('化学1')]),record('英語',[q('1A'),q('1B'),q('1')])];
 assert.deepEqual(api('secondary')(rows,'化学').map(x=>x.part),['化学1','化学2Ⅰ','化学2Ⅱ','化学1']);
 assert.deepEqual(api('secondary')(rows,'物理').map(x=>x.part),['物理1']);
 assert.equal(api('secondary')(rows,'理科').length,4);
 assert.deepEqual(api('secondary')(rows,'英語').map(x=>x.part),['1A','1B','1']);
 assert.deepEqual(api('common')(rows,'化学').map(x=>x.part),['化学1']);
});

test('retains differing allocations, dates, kinds and separate common-test total rows',()=>{
 const rows=[record('数学',[q('1',{max:40})],{date:''}),record('数学',[q('1')],{date:'2026-11-03'}),record('数学',[q('1')],{date:'2026-10-01',kind:'過去問'})];
 assert.deepEqual(api('secondary')(rows,'数学').map(x=>[x.date,x.max,x.kind]),[['2026-10-01',20,'過去問'],['2026-11-03',20,'模試'],['',40,'模試']]);
 assert.deepEqual(api('common')([record('英語R',[q('合計',{max:100})])],'英語R').map(x=>x.part),['合計']);
});

test('invalid numbers cannot become plotted zeros or rates',()=>{
 for(const score of [NaN,Infinity,-1,21,'0',null,undefined]){
  assert.equal(api('secondary')([record('数学',[q('1',{score})])],'数学')[0].score,null);
 }
});
