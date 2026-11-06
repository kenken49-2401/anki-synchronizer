// Encrypted GitHub storage for the study prototype.
// Tokens and passwords are supplied by the caller and are never persisted here.
import { encryptData, decryptData } from "./vault.mjs";

const API = "https://api.github.com";
const MAX_BYTES = 1024 * 1024;
const encoder = new TextEncoder();

function location(owner, repo, branch, path) {
  if (!/^[A-Za-z0-9-]+$/.test(owner) ||
      !/^[A-Za-z0-9_.-]+$/.test(repo) ||
      !/^[A-Za-z0-9._/-]+$/.test(branch) ||
      !/^[-A-Za-z0-9_./]+\.json$/.test(path) ||
      path.split("/").some(part => !part || part === "." || part === ".."))
    throw new Error("保存先の設定が正しくありません。");
  return API + "/repos/" + encodeURIComponent(owner) + "/" + encodeURIComponent(repo) +
    "/contents/" + path.split("/").map(encodeURIComponent).join("/");
}
function headers(token) {
  if (typeof token !== "string" || !token.trim() || /[\r\n]/.test(token))
    throw new Error("GitHubのアクセストークンが必要です。");
  return {Authorization: "Bearer " + token, Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"};
}
function encode(text) {
  const bytes = encoder.encode(text);
  if (bytes.length > MAX_BYTES) throw new Error("保存データが大きすぎます。");
  let result = "";
  for (let i = 0; i < bytes.length; i += 8192)
    result += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(result);
}
function decode(value) {
  if (typeof value !== "string" || value.length > MAX_BYTES * 2)
    throw new Error("保存データが大きすぎます。");
  const raw = atob(value.replace(/\s/g, ""));
  if (raw.length > MAX_BYTES) throw new Error("保存データが大きすぎます。");
  return new TextDecoder("utf-8", {fatal:true}).decode(Uint8Array.from(raw, c => c.charCodeAt(0)));
}
function validate(value) {
  return value && value.schema_version === 1 &&
    ["studies", "scores", "tasks"].every(k => Array.isArray(value[k]));
}
// Read only the remote revision; used for an explicit password reset.
export async function readStudyRevision(config, token) {
  const url = location(config.owner, config.repo, config.branch, config.path);
  const response = await fetch(url + "?ref=" + encodeURIComponent(config.branch),
    {headers:headers(token), cache:"no-store", redirect:"error"});
  if (response.status === 404) return {found:false, sha:null};
  if (!response.ok) throw new Error("GitHubから読み込めませんでした（HTTP " + response.status + "）。");
  const body = await response.json();
  if (body.type !== "file" || !/^[a-f0-9]{40}$/.test(body.sha))
    throw new Error("GitHubの保存データが不正です。");
  return {found:true, sha:body.sha};
}
export async function readStudyData(config, token, key) {
  const url = location(config.owner, config.repo, config.branch, config.path);
  const response = await fetch(url + "?ref=" + encodeURIComponent(config.branch),
    {headers:headers(token), cache:"no-store", redirect:"error"});
  if (response.status === 404) return {found:false, data:null, sha:null};
  if (!response.ok) throw new Error("GitHubから読み込めませんでした（HTTP " + response.status + "）。");
  const body = await response.json();
  if (body.type !== "file" || body.encoding !== "base64" || !/^[a-f0-9]{40}$/.test(body.sha))
    throw new Error("GitHubの保存データが不正です。");
  const data = await decryptData(JSON.parse(decode(body.content)), key);
  if (!validate(data)) throw new Error("学習データの形式が正しくありません。");
  return {found:true, data, sha:body.sha};
}
export async function readStudyBlob(config, token, key, sha) {
  if (!/^[a-f0-9]{40}$/.test(sha || '')) throw new Error('以前の同期情報がありません。');
  const prefix = location(config.owner, config.repo, config.branch, config.path).split('/contents/')[0];
  const response = await fetch(prefix + '/git/blobs/' + sha, {headers:headers(token),cache:'no-store',redirect:'error'});
  if (!response.ok) throw new Error('以前の同期データを取得できませんでした（HTTP ' + response.status + '）。');
  const body = await response.json();
  if (body.sha !== sha || body.encoding !== 'base64') throw new Error('以前の同期データを確認できません。');
  const data = await decryptData(JSON.parse(decode(body.content)), key);
  if (!validate(data)) throw new Error('以前の同期データの形式が正しくありません。');
  return data;
}
export async function writeStudyData(config, token, key, data, sha) {
  if (!validate(data)) throw new Error("学習データの形式が正しくありません。");
  if (sha !== null && !/^[a-f0-9]{40}$/.test(sha || ""))
    throw new Error("保存前に最新データを読み込んでください。");
  const url = location(config.owner, config.repo, config.branch, config.path);
  const encrypted = await encryptData(data, key);
  const body = {message:"Update encrypted study data", branch:config.branch,
    content:encode(JSON.stringify(encrypted))};
  if (sha) body.sha = sha;
  const response = await fetch(url, {method:"PUT", headers:{...headers(token),
    "Content-Type":"application/json"}, body:JSON.stringify(body), redirect:"error"});
  if (response.status === 409 || response.status === 422)
    throw new Error("保存先が変更されたか、設定が正しくありません。最新データと設定を確認してください。");
  if (!response.ok) throw new Error("GitHubに保存できませんでした（HTTP " + response.status + "）。");
  const result = await response.json();
  if (!/^[a-f0-9]{40}$/.test(result.content?.sha || ""))
    throw new Error("保存結果を確認できませんでした。再読み込みしてください。");
  return result.content.sha;
}

// Private, plaintext Study Atlas storage. Confirm repository privacy before every operation.
const repo = 'https://api.github.com/repos/kenken49-2401/study-atlas-data';
const file = repo + '/contents/study-data/study.json';
const legacy = 'https://api.github.com/repos/kenken49-2401/anki-synchronizer/contents/study-data/study.enc.json?ref=prototype%2Fstudy-data';
const migratedLegacySha = '9c540539d6206131178fbff1d08ed36369c6da38';
async function verifyLegacyUnchanged(token, fetchImpl) {
  const response=await fetchImpl(legacy,{headers:privateHeaders(token),cache:'no-store',redirect:'error'});
  if (!response.ok) throw Error('旧保存先を確認できないため同期を停止しました（HTTP '+response.status+'）。');
  if ((await response.json()).sha!==migratedLegacySha) throw Error('旧版の画面から記録が更新されています。新旧の記録を確認するまで同期を停止します。');
}
const privateValid = value => value && value.schema_version === 1 && ['studies','scores','tasks'].every(k => Array.isArray(value[k]));
const privateHeaders = token => {
  if (typeof token !== 'string' || !token.trim() || /[\r\n]/.test(token)) throw Error('GitHubトークンが必要です。');
  return {Authorization:'Bearer '+token,Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'};
};
async function verifyPrivate(token, fetchImpl) {
  const response = await fetchImpl(repo,{headers:privateHeaders(token),cache:'no-store',redirect:'error'});
  if (!response.ok) throw Error('非公開リポジトリを確認できません（HTTP '+response.status+'）。トークンの権限を確認してください。');
  const metadata = await response.json();
  if (metadata.private !== true || metadata.full_name !== 'kenken49-2401/study-atlas-data') throw Error('非公開の保存先を確認できないため処理を中止しました。');
}
function privateDecode(value) {
  if (typeof value !== 'string' || value.length > 2*1024*1024) throw Error('学習データの形式が不正です。');
  const raw=atob(value.replace(/\s/g,''));
  const data=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Uint8Array.from(raw,c=>c.charCodeAt(0))));
  if (!privateValid(data)) throw Error('学習データの形式が正しくありません。');
  return data;
}
export async function readPrivateStudy(token, fetchImpl=fetch) {
  await verifyPrivate(token,fetchImpl);
  await verifyLegacyUnchanged(token,fetchImpl);
  const r=await fetchImpl(file+'?ref=main',{headers:privateHeaders(token),cache:'no-store',redirect:'error'});
  if (!r.ok) throw Error('学習データを読み込めません（HTTP '+r.status+'）。');
  const body=await r.json();
  if (body.type!=='file'||body.encoding!=='base64'||!/^[a-f0-9]{40}$/.test(body.sha)) throw Error('学習データの形式が不正です。');
  return {found:true,data:privateDecode(body.content),sha:body.sha};
}
export async function readPrivateStudyBlob(token, sha, fetchImpl=fetch) {
  if (!/^[a-f0-9]{40}$/.test(sha||'')) throw Error('以前の同期情報がありません。');
  await verifyPrivate(token,fetchImpl);
  const r=await fetchImpl(repo+'/git/blobs/'+sha,{headers:privateHeaders(token),cache:'no-store',redirect:'error'});
  if (!r.ok) throw Error('以前の同期データを取得できません（HTTP '+r.status+'）。');
  const body=await r.json();
  if (body.sha!==sha||body.encoding!=='base64') throw Error('以前の同期データを確認できません。');
  return privateDecode(body.content);
}
export async function writePrivateStudy(token,data,sha,fetchImpl=fetch) {
  if (!privateValid(data)||!/^[a-f0-9]{40}$/.test(sha||'')) throw Error('保存前に最新の学習データを読み込んでください。');
  const bytes=new TextEncoder().encode(JSON.stringify(data));
  if (bytes.length>900000) throw Error('学習データが大きすぎます。');
  let raw=''; for(let i=0;i<bytes.length;i+=8192) raw+=String.fromCharCode(...bytes.subarray(i,i+8192));
  await verifyPrivate(token,fetchImpl);
  await verifyLegacyUnchanged(token,fetchImpl);
  const r=await fetchImpl(file,{method:'PUT',headers:{...privateHeaders(token),'Content-Type':'application/json'},redirect:'error',body:JSON.stringify({message:'Update Study Atlas data',branch:'main',sha,content:btoa(raw)})});
  if (!r.ok) throw Error('学習データを保存できません（HTTP '+r.status+'）。再読み込みしてください。');
  const result=await r.json(); if(!/^[a-f0-9]{40}$/.test(result.content?.sha||'')) throw Error('保存結果を確認できません。');
  return result.content.sha;
}
