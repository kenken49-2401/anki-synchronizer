import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../web/study-atlas.html',import.meta.url),'utf8');
const line=key=>{const start=source.indexOf(key);assert(start>=0,key);return source.slice(start,source.indexOf('\n',start))};
function draw(width,labels,values,selfValues){
 const texts=[],marks=[];let captured;
 const context=new Proxy({fillText:(text,x,y)=>texts.push({text,x,y}),arc:(x,y)=>marks.push([x,y])},{get:(o,k)=>k in o?o[k]:()=>{}});
 const render=new Function('canvas','labels','values','selfValues','getComputedStyle','devicePixelRatio','chartColor','drawGoalBands','setupChartTooltip',line('function lineChart(')+`;lineChart(canvas,labels,values,100,labels.map((d,i)=>'official '+i+' '+d),null,0,selfValues,labels.map((d,i)=>'self '+i+' '+d))`);
 render({clientWidth:width,getContext:()=>context},labels,values,selfValues,()=>({getPropertyValue:()=> '#59a875'}),1,l=>l,()=>{},(_,points,details)=>{captured={points,details}});
 return {...captured,texts,marks};
}

test('irregular dates share a true date axis across both series, gaps, zero and duplicate dates',()=>{
 for(const width of [320,390,1440]){
  const labels=['2026-11-01','2026-11-02','2026-11-11','2026-11-11','2026-11-21'];
  const values=[0,null,50,60,70],selfValues=[10,20,50,80,null];
  const before=JSON.stringify({labels,values,selfValues}),result=draw(width,labels,values,selfValues);
  const x=i=>result.points[result.details.indexOf('self '+i+' '+labels[i])][0];
  assert(Math.abs((x(1)-x(0))/(x(2)-x(0))-.1)<1e-10);
  assert.equal(x(2),x(3),'same date never shifts between exams');
  for(const i of [0,2,3])assert.equal(result.points[result.details.indexOf('official '+i+' '+labels[i])][0],x(i));
  assert.equal(result.points.length,8,'missing scores never become zeros or remove the other series');
  assert.equal(result.points[result.details.indexOf('official 0 '+labels[0])][1],185,'zero remains plotted');
  const dates=result.texts.filter(t=>String(t.text).startsWith('26/'));
  assert.equal(dates[0].x,x(0));assert.equal(dates.at(-1).x,result.points[result.details.indexOf('official 4 '+labels[4])][0]);
  assert.equal(new Set(dates.map(d=>d.text)).size,dates.length,'same date gets a single tick');
  for(let i=1;i<dates.length;i++)assert(dates[i].x-dates[i-1].x>=75);
  assert.equal(JSON.stringify({labels,values,selfValues}),before);
 }
});

test('undated and invalid dates cannot acquire a position or distort dated series',()=>{
 const result=draw(390,['','2026-02-30','2026-11-11','2026-11-01','unknown'],[90,90,null,0,90],[90,90,50,null,90]);
 assert.deepEqual(result.details,['self 2 2026-11-11','official 3 2026-11-01']);
 assert.equal(result.points[0][0],355);assert.equal(result.points[1][0],50);
 assert.deepEqual(draw(390,[''],[80],[90]).points,[]);
 const sameDay=draw(390,['2026-11-01','2026-11-01'],[0,20],[10,null]);
 assert(sameDay.points.every(p=>p[0]===202.5),'one date centers all points');
});

test('overlapping points expose every exam and both sources; nearby points remain separate',()=>{
 const code=source.slice(source.indexOf('function setupChartTooltip('),source.indexOf('\nconst presets='));
 const tooltip={hidden:true,style:{},offsetWidth:100,offsetHeight:100};
 const canvas={clientWidth:390,setAttribute(){},getBoundingClientRect:()=>({left:0,top:0,width:390,height:220})};
 const setup=new Function('tooltip','window',`let activeChartTooltip=tooltip;${code};return setupChartTooltip`)(tooltip,{innerWidth:390,innerHeight:900});
 setup(canvas,[[50,100],[50,100],[50,100],[50,140]],['試験A 得点 50','試験A 自己採点 50','試験B 自己採点 50','試験C 得点 20']);
 canvas.onpointerdown({clientX:50,clientY:100});
 assert.equal(tooltip.textContent,'試験A 得点 50\n\n試験A 自己採点 50\n\n試験B 自己採点 50');
 canvas.onpointerdown({clientX:50,clientY:140});assert.equal(tooltip.textContent,'試験C 得点 20');
 canvas.onkeydown({key:'ArrowLeft',preventDefault(){}});assert(tooltip.textContent.includes('試験B'));
});
