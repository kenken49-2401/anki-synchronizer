import test from "node:test";
import assert from "node:assert/strict";
import {
  importPassword,
  decryptPackage,
  createMediaURLs,
  revokeMediaURLs,
  encryptData,
  decryptData,
} from "../web/vault.mjs";

const password = "random-looking-test-only-password-1732";
test("browser tag drafts encrypt with new nonces, round-trip and cannot be loaded as snapshots", async () => {
  const key = await importPassword(password),
    value = { format: "anki-atlas-tag-changes", private: "PRIVATE_TAG_1292" };
  const one = await encryptData(value, key),
    two = await encryptData(value, key);
  assert.notEqual(one.salt, two.salt);
  assert.notEqual(one.iv, two.iv);
  assert.ok(!JSON.stringify(one).includes(value.private));
  assert.deepEqual(await decryptData(one, key), value);
  await assert.rejects(decryptPackage(one, key));
});
async function packageFor(value) {
  const salt = crypto.getRandomValues(new Uint8Array(16)),
    iv = crypto.getRandomValues(new Uint8Array(12));
  const raw = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations: 600000, hash: "SHA-256" },
    raw,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt"],
  );
  const ciphertext = await crypto.subtle.encrypt(
    {
      name: "AES-GCM",
      iv,
      additionalData: new TextEncoder().encode("Anki Atlas snapshot v1"),
    },
    key,
    new TextEncoder().encode(JSON.stringify(value)),
  );
  return {
    format: "anki-atlas-encrypted",
    version: 1,
    kdf: "PBKDF2-SHA256",
    iterations: 600000,
    salt: Buffer.from(salt).toString("base64"),
    iv: Buffer.from(iv).toString("base64"),
    ciphertext: Buffer.from(ciphertext).toString("base64"),
  };
}
const empty = {
  schema_version: 1,
  source: { kind: "ankiweb", profile: "Test" },
  cards: [],
  reviews: [],
};
test("password stays in non-extractable CryptoKey; wrong password and tampering fail", async () => {
  const pkg = await packageFor(empty),
    key = await importPassword(password);
  assert.equal(key.extractable, false);
  assert.deepEqual(await decryptPackage(pkg, key), empty);
  await assert.rejects(
    decryptPackage(pkg, await importPassword("wrong-password-12345678")),
  );
  const modified = {
    ...pkg,
    ciphertext:
      (pkg.ciphertext[0] === "A" ? "B" : "A") + pkg.ciphertext.slice(1),
  };
  await assert.rejects(decryptPackage(modified, key));
});
test("unsupported work factor and plaintext or malformed data are rejected", async () => {
  const key = await importPassword(password);
  await assert.rejects(
    decryptPackage({ ...(await packageFor(empty)), iterations: 1e12 }, key),
  );
  await assert.rejects(decryptPackage({ schema_version: 1, cards: [] }, key));
  await assert.rejects(importPassword("short"));
  await assert.rejects(decryptPackage(await packageFor({ cards: [] }), key));
});
test("large ciphertext uses bounded base64 decoding without regex stack overflow", async () => {
  const data = { ...empty, padding: "a".repeat(1024 * 1024) },
    pkg = await packageFor(data);
  assert.equal(
    (await decryptPackage(pkg, await importPassword(password))).padding.length,
    1024 * 1024,
  );
});
test("malformed or disguised SVG images cannot create object URLs", async () => {
  await assert.rejects(
    createMediaURLs({
      ...empty,
      media: {
        "x.png": {
          id: "a".repeat(64),
          mime: "image/png",
          data: Buffer.from('<svg onload="alert(1)">').toString("base64"),
        },
      },
    }),
  );
  const urls = new Map();
  revokeMediaURLs(urls);
  assert.equal(urls.size, 0);
});

test("encrypted image chunks load only from safe same-site names and validate their images", async () => {
  const bytes = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf4sAAAAASUVORK5CYII=", "base64");
  const id = Buffer.from(await crypto.subtle.digest("SHA-256", bytes)).toString("hex");
  const part = await packageFor({schema_version:1, media:{"private-name.png":{id,mime:"image/png",data:bytes.toString("base64")}}});
  const filename = "media-" + "a".repeat(64) + ".enc.json";
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push([url,options]);
    return new Response(JSON.stringify(part));
  };
  try {
    const key = await importPassword(password);
    const urls = await createMediaURLs({...empty,media_packages:[filename]},key);
    assert.equal(urls.size,1);
    assert.ok(urls.get(id).startsWith("blob:"));
    revokeMediaURLs(urls);
    assert.equal(requests[0][0],"./"+filename);
    assert.equal(requests[0][1].credentials,"omit");
    assert.equal(requests[0][1].redirect,"error");
    requests.length=0;
    await assert.rejects(createMediaURLs({...empty,media_packages:["https://evil.test/private"]},key));
    assert.equal(requests.length,0);
    await assert.rejects(createMediaURLs({...empty,media_packages:[filename]},await importPassword("wrong-password-12345678")));
  } finally { globalThis.fetch = original; }
});
