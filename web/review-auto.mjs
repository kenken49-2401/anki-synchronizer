import { encryptData, decryptData } from "./vault.mjs";
import { reviewRequest, TAG_REPOSITORY, REVIEW_TITLE } from "./tag-queue.mjs";

const SLOT = `atlas-review-auto:v1:${new URL("./", document.baseURI).pathname}`;
const API = `https://api.github.com/repos/${TAG_REPOSITORY}/issues`;
const lockName = SLOT + ":lock";

async function locked(fn) {
  if (!navigator.locks) throw new Error("このブラウザーでは送信の重複防止を利用できません。");
  return navigator.locks.request(lockName, {mode: "exclusive"}, fn);
}
async function read(key) {
  const encoded = localStorage.getItem(SLOT);
  if (!encoded) return {token: null, pending: {}};
  const data = await decryptData(JSON.parse(encoded), key);
  if (data?.format !== "anki-atlas-review-auto" || data.version !== 1 ||
      typeof data.pending !== "object" || !data.pending || Array.isArray(data.pending) ||
      (data.token !== null && typeof data.token !== "string")) throw new Error("送信設定を読み込めません。");
  return data;
}
async function save(key, data) {
  localStorage.setItem(SLOT, JSON.stringify(await encryptData({format: "anki-atlas-review-auto", version: 1, ...data}, key)));
}
function headers(token) {
  return {Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json", "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"};
}
export async function configureReviewToken(key, token) {
  if (typeof token !== 'string' || !/^[\x21-\x7e]{20,255}$/.test(token)) throw new Error("GitHubトークンの形式を確認してください。");
  let response;
  try {
    response = await fetch("https://api.github.com/user", {headers: headers(token), redirect: "error", cache: "no-store"});
  } catch {
    throw new Error("GitHubに接続できません。通信状態を確認してください。");
  }
  if (!response.ok || (await response.json()).login?.toLowerCase() !== TAG_REPOSITORY.split('/')[0].toLowerCase())
    throw new Error("リポジトリ所有者のGitHubトークンを確認してください。");
  await locked(async () => { const data = await read(key); data.token = token; await save(key, data); });
}
export async function removeReviewToken(key) {
  await locked(async () => { const data = await read(key); data.token = null; await save(key, data); });
}
export async function clearReviewGuards(key) {
  await locked(async () => { const data = await read(key); data.pending = {}; await save(key, data); });
}
export async function loadHiddenReviews(key) {
  const data = await read(key);
  return new Map(Object.entries(data.pending)
    .filter(([, entry]) => entry?.hide === true && typeof entry.version === "string")
    .map(([id, entry]) => [Number(id), entry.version]));
}
export async function submitAutomaticReview(key, card, rating) {
  return locked(async () => {
    const data = await read(key), id = String(card.id);
    if (!data.token) throw new Error("接続・設定で回答の自動送信を設定してください。");
    if (data.pending[id]?.version === card.review_version) throw new Error("このカードの回答は送信済みか確認待ちです。Ankiの履歴と更新を確認してください。");
    const payload = {format: "anki-atlas-review", version: 1, request_id: crypto.randomUUID(), card_id: card.id, review_version: card.review_version, rating};
    const encrypted = JSON.stringify(await encryptData(payload, key));
    const request = reviewRequest(encrypted);
    data.pending[id] = {version: card.review_version, request_id: payload.request_id};
    await save(key, data);
    let response;
    try {
      response = await fetch(API, {method: "POST", headers: headers(data.token), redirect: "error", body: JSON.stringify({title: REVIEW_TITLE, body: request.body})});
    } catch {
      throw new Error("送信結果を確認できません。GitHubのIssuesを確認し、自動で再送しないでください。");
    }
    if (!response.ok) {
      // GitHub rejected the request; no issue was created. Retain the guard on
      // server errors, whose outcome can be ambiguous.
      if (response.status >= 400 && response.status < 500 && response.status !== 408 && response.status !== 429) {
        delete data.pending[id]; await save(key, data);
        throw new Error(`GitHubに送信できませんでした（HTTP ${response.status}）。設定を確認してください。`);
      }
      throw new Error("送信結果を確認できません。GitHubのIssuesを確認し、自動で再送しないでください。");
    }
    if (rating === "good" || rating === "easy") {
      data.pending[id].hide = true;
      try { await save(key, data); } catch { return {hiddenSaved: false}; }
    }
    return {hiddenSaved: true};
  });
}
