// Private, plaintext Study Atlas storage. Confirm repository privacy before every operation.
const repo = 'https://api.github.com/repos/kenken49-2401/study-atlas-data';
const file = repo + '/contents/study-data/study.json';
const legacy = 'https://api.github.com/repos/kenken49-2401/anki-synchronizer/contents/study-data/study.enc.json?ref=prototype%2Fstudy-data';
const migratedLegacySha = '9c540539d6206131178fbff1d08ed36369c6da38';
async function verifyLegacyUnchanged(token, fetchImpl) {
  const response=await fetchImpl(legacy,{headers:headers(token),cache:'no-store',redirect:'error'});
  if (!response.ok) throw Error('旧保存先を確認できないため同期を停止しました（HTTP '+response.status+'）。');
  if ((await response.json()).sha!==migratedLegacySha) throw Error('旧版の画面から記録が更新されています。新旧の記録を確認するまで同期を停止します。');
}
const valid = value => value && value.schema_version === 1 && ['studies','scores','tasks'].every(k => Array.isArray(value[k]));
const headers = token => {
  if (typeof token !== 'string' || !token.trim() || /[\r\n]/.test(token)) throw Error('GitHubトークンが必要です。');
  return {Authorization:'Bearer '+token,Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'};
};
async function verifyPrivate(token, fetchImpl) {
  const response = await fetchImpl(repo,{headers:headers(token),cache:'no-store',redirect:'error'});
  if (!response.ok) throw Error('非公開リポジトリを確認できません（HTTP '+response.status+'）。トークンの権限を確認してください。');
  const metadata = await response.json();
  if (metadata.private !== true || metadata.full_name !== 'kenken49-2401/study-atlas-data') throw Error('非公開の保存先を確認できないため処理を中止しました。');
}
function decode(value) {
  if (typeof value !== 'string' || value.length > 2*1024*1024) throw Error('学習データの形式が不正です。');
  const raw=atob(value.replace(/\s/g,''));
  const data=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Uint8Array.from(raw,c=>c.charCodeAt(0))));
  if (!valid(data)) throw Error('学習データの形式が正しくありません。');
  return data;
}
export async function readPrivateStudy(token, fetchImpl=fetch) {
  await verifyPrivate(token,fetchImpl);
  await verifyLegacyUnchanged(token,fetchImpl);
  const r=await fetchImpl(file+'?ref=main',{headers:headers(token),cache:'no-store',redirect:'error'});
  if (!r.ok) throw Error('学習データを読み込めません（HTTP '+r.status+'）。');
  const body=await r.json();
  if (body.type!=='file'||body.encoding!=='base64'||!/^[a-f0-9]{40}$/.test(body.sha)) throw Error('学習データの形式が不正です。');
  return {found:true,data:decode(body.content),sha:body.sha};
}
export async function readPrivateStudyBlob(token, sha, fetchImpl=fetch) {
  if (!/^[a-f0-9]{40}$/.test(sha||'')) throw Error('以前の同期情報がありません。');
  await verifyPrivate(token,fetchImpl);
  const r=await fetchImpl(repo+'/git/blobs/'+sha,{headers:headers(token),cache:'no-store',redirect:'error'});
  if (!r.ok) throw Error('以前の同期データを取得できません（HTTP '+r.status+'）。');
  const body=await r.json();
  if (body.sha!==sha||body.encoding!=='base64') throw Error('以前の同期データを確認できません。');
  return decode(body.content);
}
export async function writePrivateStudy(token,data,sha,fetchImpl=fetch) {
  if (!valid(data)||!/^[a-f0-9]{40}$/.test(sha||'')) throw Error('保存前に最新の学習データを読み込んでください。');
  const bytes=new TextEncoder().encode(JSON.stringify(data));
  if (bytes.length>900000) throw Error('学習データが大きすぎます。');
  let raw=''; for(let i=0;i<bytes.length;i+=8192) raw+=String.fromCharCode(...bytes.subarray(i,i+8192));
  await verifyPrivate(token,fetchImpl);
  await verifyLegacyUnchanged(token,fetchImpl);
  const r=await fetchImpl(file,{method:'PUT',headers:{...headers(token),'Content-Type':'application/json'},redirect:'error',body:JSON.stringify({message:'Update Study Atlas data',branch:'main',sha,content:btoa(raw)})});
  if (!r.ok) throw Error('学習データを保存できません（HTTP '+r.status+'）。再読み込みしてください。');
  const result=await r.json(); if(!/^[a-f0-9]{40}$/.test(result.content?.sha||'')) throw Error('保存結果を確認できません。');
  return result.content.sha;
}
