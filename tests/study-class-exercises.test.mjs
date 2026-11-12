import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../web/study-atlas.html',import.meta.url),'utf8');
const line=key=>{const i=source.indexOf(key);assert(i>=0,key);return source.slice(i,source.indexOf('\n',i))};
const block=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const helpers=block('const goalMax=','const goalLabels=').replace(/function setExamFormat[\s\S]*/,'');
const code=helpers+'\n'+['const presets=','function sumDecimal(','function completeSum(','const complete=','function chemistryDefinitions(','const resultSubjects=','const resultTotal=','function totalExamPoints('].map(line).join('\n')+'\n'+block('function completeExamSets(','function deleteButton(')+'\n'+block('function submitScore(','function timeSymbols(');
new Function('assert',`let kind='授業内演習',subject='数学',data={scores:[]},scoreEditId=null,form={get:key=>({kind,subject,date:'2026-11-12',name:'授業内演習'}[key])},rows=[],calls=0;
const chemModes=[1,2,3].map(n=>({dataset:{chemMode:String(n)},value:'whole'}));
const $=id=>id==='#classView'?{value:'class'}:id==='#scoreForm'?{elements:{kind:{get value(){return kind}}}}:id==='#examSubject'?{get value(){return subject}}:id==='#chemistryModes'?{querySelectorAll:()=>chemModes}:{};
const document={querySelectorAll:()=>rows},readPicker=()=>[],FormData=function(){return form},checkEditedRecord=()=>true,id=()=>String(data.scores.length),save=()=>{calls++;return true},cancelScoreEdit=()=>{},alert=m=>{throw Error(m)},confirm=()=>true;
${code}
assert.equal(inputPresets().数学.length,3);assert.equal(inputPresets().数学.reduce((a,q)=>a+q[1],0),60);
assert.equal(inputPresets().英語.length,2);assert.equal(inputPresets().英語.reduce((a,q)=>a+q[1],0),200);
subject='化学';assert.equal(chemistryDefinitions().length,3);assert.equal(chemistryDefinitions().reduce((a,q)=>a+q[1],0),60);
function submit(which,defs){subject=which;rows=defs.map(([name,max])=>({dataset:{name},querySelector:selector=>selector==='[data-tag-container]'?{}:{value:String(({max,score:max/2,average:max/3,selfscore:max/2,feeling:max/2})[/data-field="([^"]+)"/.exec(selector)[1]]??'')}}));submitScore({preventDefault(){},target:{}})}
submit('数学',inputPresets().数学);assert.equal(data.scores[0].max,60);assert.equal(data.scores[0].score,30);assert.equal(data.scores[0].kind,'授業内演習');
submit('英語',inputPresets().英語);assert.equal(data.scores[1].max,200);assert.equal(data.scores[1].score,100);
subject='化学';submit('化学',chemistryDefinitions());assert.equal(data.scores[2].max,60);assert.equal(completeExamSets(data.scores).length,1);assert.equal(totalExamPoints(data.scores)[0].values.reduce((a,b)=>a+b,0),160);assert.equal(resultTotal(),320);
kind='模試';assert.equal(inputPresets().数学.length,6);
activeExamFormat='common';assert.equal(inputPresets().数学3C[0][1],100);
assert.equal(calls,3);
`)(assert);
