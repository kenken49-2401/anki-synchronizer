import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseExam,parseTags,parseTime,summarizeTopics,examKey,column} from './model.mjs';

test('separate subject blocks, sparse headers, and formulas remain grounded to cells',()=>{
  const values=[['','英語','','','','配点','','数学','点数','平均','自己採','配点'],['','1',4,'',6,20,'','1',13,8.4,8,20],['','計',4,'',6,20,'','計',13,8.4,8,20]];
  const formulas=structuredClone(values);formulas[1][8]='=1+12';
  const e=parseExam('模試',values,formulas);
  assert.equal(e.length,2);assert.equal(e[0].cells.score.address,'C2');assert.equal(e[0].cells.max.address,'F2');assert.equal(e[1].cells.score.formula,true);assert.equal(e[1].cells.score.address,'I2');
});
test('last tag entry wins and score rate is weighted by points',()=>{
  const e=parseExam('模試',[['','数学','点数','平均','自己採','配点'],['','1',5,8,5,10],['','2',18,10,18,30]]);
  const tags=parseTags([['シート','科目','大問','タグ','実施日'],['模試','数学','1','旧',''],['模試','数学','1','微積','2026-01-01'],['模試','数学','2','微積, 図形','2026-02-01']]);
  assert.deepEqual(tags.get(examKey(e[0])).tags,['微積']);const groups=summarizeTopics(e,tags);assert.equal(groups.find(x=>x.name==='数学 / 微積').rate,23/40);assert.equal(groups.find(x=>x.name==='数学 / 図形').items.length,1);
});
test('legacy dates remain yearless and empty hours are distinct from zero',()=>{let rows=parseTime([[],[],['7/18','',0,3,1.5]],true);assert.equal(rows[0].date,'7/18');assert.deepEqual(rows[0].hours,[null,0,3,1.5,null]);assert.equal(rows[0].row,3);assert.equal(column(26),'AA')});
