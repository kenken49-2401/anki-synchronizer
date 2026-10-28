import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Sheets} from './sheets.mjs';

test('refuses to overwrite a changed value or a formula',async()=>{
  const api=new Sheets('example'); api.token='test'; const calls=[];
  const original=globalThis.fetch;
  try{
    globalThis.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({values:[['=SUM(A1:A2)']]})}};
    await assert.rejects(api.saveCells('模試',[{address:'C2',raw:3,value:4}]),/変更されたか数式/);
    assert.equal(calls.length,1);assert.equal(calls[0].options.method,undefined);
  }finally{globalThis.fetch=original}
});
test('writes only the changed cells as raw numeric values',async()=>{
  const api=new Sheets('example');api.token='test';const calls=[];const original=globalThis.fetch;
  try{
    globalThis.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>calls.length===1?{values:[[3]]}:{totalUpdatedCells:1}}};
    await api.saveCells('模試',[{address:'C2',raw:3,value:4}]);
    const payload=JSON.parse(calls[1].options.body);assert.equal(payload.valueInputOption,'RAW');assert.deepEqual(payload.data,[{range:"'模試'!C2",values:[[4]]}]);
  }finally{globalThis.fetch=original}
});
