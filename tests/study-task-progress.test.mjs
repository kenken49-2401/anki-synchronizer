import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const html=readFileSync(new URL('../web/study-atlas.html',import.meta.url),'utf8');
const context=vm.createContext({Date,Number,Math});
vm.runInContext(html.slice(html.indexOf('function dayNumber('),html.indexOf('function updateQuantityMode()')),context);
const progress=task=>JSON.parse(JSON.stringify(context.taskProgress(task)));
const quantity={start:'2026-11-01',mode:'total',total:50,daily:7,unit:'問',entries:{'2026-11-01':10,'2026-11-02':15}};

test('total and pace progress sum recorded quantities without changing records',()=>{
 for(const mode of ['total','pace']){
  const task={date:'2026-11-08',quantity:{...quantity,mode}},before=JSON.stringify(task);
  assert.deepEqual(progress(task),{percent:50,note:'記録済み 25 / 50問'});
  assert.equal(JSON.stringify(task),before);
 }
});
test('daily and legacy goals use the entire inclusive period, including leap days',()=>{
 for(const mode of [undefined,'daily'])assert.equal(progress({date:'2028-03-01',quantity:{mode,start:'2028-02-28',daily:5,entries:{'2028-02-28':5}}}).percent,33);
});
test('missing records and explicit zero have distinct labels',()=>{
 assert.deepEqual(progress({date:'2026-11-08',quantity:{...quantity,entries:{}}}),{percent:0,note:'実績未記録'});
 assert.deepEqual(progress({date:'2026-11-08',quantity:{...quantity,entries:{'2026-11-01':0}}}),{percent:0,note:'記録済み 0 / 50問'});
});
test('quantity progress respects manual completion without inventing records',()=>{
 assert.deepEqual(progress({done:true,date:'2026-11-08',quantity}),{percent:50,note:'完了・記録済み 25 / 50問'});
 assert.deepEqual(progress({done:true}),{percent:100,note:'完了・数量目標なし'});
 assert.deepEqual(progress({done:false}),{percent:null,note:'数量目標なし'});
});
test('progress caps excess at 100% and avoids rounding unfinished work to completion',()=>{
 assert.equal(progress({quantity:{...quantity,total:1000,entries:{a:999}}}).percent,99);
 assert.equal(progress({quantity:{...quantity,entries:{a:70}}}).percent,100);
 assert.equal(progress({date:'2026-10-31',quantity:{start:'2026-11-01',daily:5}}).percent,null);
 assert.equal(progress({quantity:{...quantity,total:0}}).percent,null);
});

test('regular and completed tasks without quantity goals keep their original row',()=>{
 const row={querySelector(){assert.fail('a task without a quantity goal must not add a progress summary')}};
 for(const done of [false,true])context.addTaskProgress(row,{done});
});

test('today tasks show progress only when a quantity goal is configured',()=>{
 const node=()=>({children:[],dataset:{},append(...children){this.children.push(...children)},setAttribute(){}});
 const shown=[],today='2026-11-13',root=node();
 const viewContext=vm.createContext({
  el:node,document:{createElement:node,createTextNode:text=>text},
  compareTaskPriority:()=>0,taskPriority:()=> 'medium',taskPriorityBadge:node,
  taskProgressView:task=>{shown.push(task.title);return {progress:true}},
 });
 vm.runInContext(html.slice(html.indexOf('function renderTodayTaskPlan('),html.indexOf('function addTodayTaskChoice(')),viewContext);
 viewContext.renderTodayTaskPlan(root,[
  {title:'目標なし',todayPlan:{date:today}},
  {title:'目標あり',quantity,todayPlan:{date:today}},
  {title:'完了済み',done:true,todayPlan:{date:today}},
 ],today);
 assert.deepEqual(shown,['目標あり']);
 const rows=root.children[1].children;
 assert.equal(rows.length,2);
 assert.equal(rows[0].children.some(child=>child.progress),false);
 assert.equal(rows[1].children.some(child=>child.progress),true);
});
