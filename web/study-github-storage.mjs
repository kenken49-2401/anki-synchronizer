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
