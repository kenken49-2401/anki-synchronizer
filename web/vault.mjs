// Passwords, derived key material and decrypted images stay in this page's memory.
const FORMAT = "anki-atlas-encrypted";
const ITERATIONS = 600000;
const MAX_CLEAR = 32 * 1024 * 1024;
export const MAX_PACKAGE = 45 * 1024 * 1024;
const encoder = new TextEncoder();
const aad = encoder.encode("Anki Atlas snapshot v1");

function decode(value, size) {
  if (
    typeof value !== "string" ||
    value.length > MAX_PACKAGE ||
    value.length % 4 !== 0 ||
    !/^[A-Za-z0-9+/]*={0,2}$/.test(value)
  )
    throw new Error("暗号化ファイルの形式が正しくありません。");
  const bytes = Uint8Array.from(atob(value), (c) => c.charCodeAt(0));
  if (size !== undefined && bytes.length !== size)
    throw new Error("暗号化ファイルの形式が正しくありません。");
  return bytes;
}

export async function importPassword(password) {
  if (!globalThis.crypto?.subtle)
    throw new Error(
      "HTTPSで開いてください。ローカルではlocalhostを使用できます。",
    );
  const bytes = encoder.encode(password);
  if (bytes.length < 16 || bytes.length > 1024)
    throw new Error(
      "設定した閲覧パスワードを入力してください（16バイト以上）。",
    );
  try {
    return await crypto.subtle.importKey("raw", bytes, "PBKDF2", false, [
      "deriveKey",
    ]);
  } finally {
    bytes.fill(0);
  }
}

export async function decryptPackage(pkg, masterKey) {
  if (
    !pkg ||
    pkg.format !== FORMAT ||
    pkg.version !== 1 ||
    pkg.kdf !== "PBKDF2-SHA256" ||
    pkg.iterations !== ITERATIONS
  )
    throw new Error("対応していない暗号化ファイルです。");
  const salt = decode(pkg.salt, 16),
    iv = decode(pkg.iv, 12),
    data = decode(pkg.ciphertext);
  if (data.length < 16 || data.length > MAX_CLEAR + 16)
    throw new Error("暗号化ファイルが大きすぎます。");
  try {
    const key = await crypto.subtle.deriveKey(
      { name: "PBKDF2", salt, iterations: ITERATIONS, hash: "SHA-256" },
      masterKey,
      { name: "AES-GCM", length: 256 },
      false,
      ["decrypt"],
    );
    const clear = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv, additionalData: aad, tagLength: 128 },
      key,
      data,
    );
    try {
      const snapshot = JSON.parse(
        new TextDecoder("utf-8", { fatal: true }).decode(clear),
      );
      if (
        snapshot?.schema_version !== 1 ||
        !Array.isArray(snapshot.cards) ||
        !Array.isArray(snapshot.reviews) ||
        !snapshot.source ||
        snapshot.cards.length > 50000 ||
        snapshot.reviews.length > 1000000
      )
        throw new Error();
      return snapshot;
    } finally {
      new Uint8Array(clear).fill(0);
    }
  } catch {
    throw new Error(
      "復号できません。パスワード、またはファイルの破損を確認してください。",
    );
  }
}

export async function fetchPackage(url = "./snapshot.enc.json") {
  const res = await fetch(url, {
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
  });
  if (res.status === 404)
    throw new Error(
      "データはまだ公開されていません。設定手順に沿って最初の更新を実行してください。",
    );
  if (!res.ok) throw new Error("暗号化データを読み込めませんでした。");
  const reader = res.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > MAX_PACKAGE) throw new Error("暗号化ファイルが大きすぎます。");
      chunks.push(value);
    }
  } catch (error) {
    await reader.cancel();
    throw error;
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new Error("暗号化ファイルの形式が正しくありません。");
  }
}

function validRaster(bytes, mime) {
  if (mime === "image/png")
    return bytes.slice(0, 8).join() === "137,80,78,71,13,10,26,10";
  if (mime === "image/jpeg")
    return bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255;
  const text = (n) => String.fromCharCode(...bytes.slice(0, n));
  if (mime === "image/gif") return ["GIF87a", "GIF89a"].includes(text(6));
  if (mime === "image/webp")
    return (
      text(4) === "RIFF" &&
      String.fromCharCode(...bytes.slice(8, 12)) === "WEBP"
    );
  return false;
}

export async function createMediaURLs(snapshot) {
  const urls = new Map();
  let total = 0;
  try {
    const media = Object.values(snapshot.media || {});
    if (media.length > 500) throw new Error();
    for (const item of media) {
      if (
        !item ||
        !/^[a-f0-9]{64}$/.test(item.id || "") ||
        typeof item.data !== "string" ||
        item.data.length > 2796204
      )
        throw new Error();
      const bytes = decode(item.data);
      total += bytes.length;
      if (
        bytes.length > 2 * 1024 * 1024 ||
        total > 16 * 1024 * 1024 ||
        !validRaster(bytes, item.mime)
      )
        throw new Error();
      const hash = [
        ...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
      ]
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("");
      if (hash !== item.id) throw new Error();
      if (!urls.has(item.id))
        urls.set(
          item.id,
          URL.createObjectURL(new Blob([bytes], { type: item.mime })),
        );
    }
    return urls;
  } catch {
    revokeMediaURLs(urls);
    throw new Error("画像データの形式または容量が正しくありません。");
  }
}

export function revokeMediaURLs(urls) {
  for (const url of urls.values()) URL.revokeObjectURL(url);
  urls.clear();
}
