import {quote, TAG_SHEET, TIME_SHEET} from './model.mjs';
export const DEFAULT_ID = '';
const scope = 'https://www.googleapis.com/auth/spreadsheets';
export class Sheets {
  constructor(id) { this.id=id; this.token=null; this.sheets=[]; }
  connect(clientId) {
    if (!globalThis.google?.accounts?.oauth2) throw Error('Google認証の読み込みに失敗しました。再読み込みしてください。');
    return new Promise((resolve,reject)=>{
      const client=google.accounts.oauth2.initTokenClient({client_id:clientId,scope,callback:r=>{if(r.error) reject(Error(r.error)); else {this.token=r.access_token;resolve();}},error_callback:e=>reject(Error(e.type))});
      client.requestAccessToken();
    });
  }
  async request(path, options={}) {
    if (!this.token) throw Error('Googleに接続してください。');
    const res=await fetch(`https://sheets.googleapis.com/v4/spreadsheets/${encodeURIComponent(this.id)}${path}`,{...options,headers:{Authorization:`Bearer ${this.token}`,'Content-Type':'application/json',...(options.headers||{})}});
    if (!res.ok) {if(res.status===401)this.token=null;const body=await res.json().catch(()=>({}));throw Error(`Sheets API (${res.status}): ${body.error?.message || '接続または権限を確認してください'}`);}
    return res.json();
  }
  async metadata() { const x=await this.request('?fields=properties(title),sheets(properties(sheetId,title))');this.sheets=x.sheets.map(s=>s.properties);return x; }
  async read(sheet, range, option='FORMATTED_VALUE') {const r=await this.request(`/values/${encodeURIComponent(`${quote(sheet)}!${range}`)}?valueRenderOption=${option}`);return r.values||[];}
  async ensureSheet(title, headers) {
    await this.metadata(); if(this.sheets.some(s=>s.title===title)) return;
    await this.request(':batchUpdate',{method:'POST',body:JSON.stringify({requests:[{addSheet:{properties:{title}}}]})});
    await this.request(`/values/${encodeURIComponent(`${quote(title)}!A1`)}?valueInputOption=RAW`,{method:'PUT',body:JSON.stringify({values:[headers]})});
    await this.metadata();
  }
  async append(title, row) {await this.request(`/values/${encodeURIComponent(`${quote(title)}!A:E`)}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS`,{method:'POST',body:JSON.stringify({values:[row]})});}
  async saveCells(sheet, changes) {
    // Re-read each target and reject formulas or values changed since the editor loaded.
    for(const c of changes){ const now=(await this.read(sheet,c.address,'FORMULA'))[0]?.[0] ?? ''; if(String(now)!==String(c.raw) || String(now).startsWith('=')) throw Error(`${c.address} が変更されたか数式です。再読み込みして確認してください。`); }
    await this.request('/values:batchUpdate',{method:'POST',body:JSON.stringify({valueInputOption:'RAW',data:changes.map(c=>({range:`${quote(sheet)}!${c.address}`,values:[[c.value]]}))})});
  }
  async addTag(row){await this.ensureSheet(TAG_SHEET,['シート','科目','大問','タグ','実施日']);await this.append(TAG_SHEET,row);}
  async addTime(row){await this.ensureSheet(TIME_SHEET,['日付','数学','物理','化学','英語','国語']);await this.request(`/values/${encodeURIComponent(`${quote(TIME_SHEET)}!A:F`)}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS`,{method:'POST',body:JSON.stringify({values:[row]})});}
}
