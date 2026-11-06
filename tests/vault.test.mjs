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

test("image index defers downloads, bounds decrypted cache and closes on logout", async () => {
  const key = await importPassword(password);
  const packages=[], index={}, bodies=new Map(), ids=[];
  const png=Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf4sAAAAASUVORK5CYII=","base64");
  for(let i=0;i<9;i++) {
    const bytes=Buffer.concat([png,Buffer.from([i])]);
    const id=Buffer.from(await crypto.subtle.digest("SHA-256",bytes)).toString("hex");
    const name="media-"+i.toString(16).padStart(64,"0")+".enc.json";
    packages.push(name);index[id]=name;ids.push(id);
    bodies.set("./"+name,await encryptData({schema_version:1,media:{[i+".png"]:{id,mime:"image/png",data:bytes.toString("base64")}}},key));
  }
  const original=globalThis.fetch, calls=[];
  globalThis.fetch=async (url,options)=>{calls.push(url);assert.equal(options.credentials,"omit");return new Response(JSON.stringify(bodies.get(url)));};
  try {
    const urls=await createMediaURLs({...empty,media_packages:packages,media_index:index},key);
    assert.equal(calls.length,0);
    for(const id of ids) assert.ok((await urls.loadImage(id)).startsWith("blob:"));
    assert.equal(urls.size,8);
    assert.equal(urls.has(ids[0]),false);
    assert.equal(calls.length,9);
    await urls.loadImage(ids[8]);assert.equal(calls.length,9);
    revokeMediaURLs(urls);assert.equal(urls.size,0);
    await assert.rejects(urls.loadImage(ids[8]));
    assert.equal(calls.length,9);
    await assert.rejects(createMediaURLs({...empty,media_packages:packages,media_index:{[ids[0]]:"https://evil.test/private"}},key));
  } finally {globalThis.fetch=original;}
});

test('media retries transient network failures and reuses only encrypted cached data', async () => {
 const key=await importPassword(password),bytes=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf4sAAAAASUVORK5CYII=','base64'),id=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex'),name='media-'+'b'.repeat(64)+'.enc.json';
 const payload=await encryptData({schema_version:1,media:{'secret-picture.png':{id,mime:'image/png',data:bytes.toString('base64')}}},key),stored=new Map(),cache={async match(k){return stored.get(k)?.clone()},async put(k,v){stored.set(k,v.clone())},async keys(){return [...stored.keys()]},async delete(k){return stored.delete(k)}};
 const originalFetch=globalThis.fetch,originalCaches=globalThis.caches;let calls=0;globalThis.caches={open:async()=>cache};globalThis.fetch=async()=>{calls++;if(calls<3)throw Error('temporary network failure');return new Response(JSON.stringify(payload))};
 try {const snap={...empty,media_packages:[name],media_index:{[id]:name}},urls=await createMediaURLs(snap,key);assert.ok((await urls.loadImage(id)).startsWith('blob:'));assert.equal(calls,3);for(let i=0;i<20&&!stored.size;i++)await new Promise(r=>setTimeout(r,10));assert.equal(stored.size,1);const text=await stored.get('./'+name).clone().text();assert.ok(!text.includes('secret-picture.png'));revokeMediaURLs(urls);globalThis.fetch=async()=>{throw Error('offline')};const second=await createMediaURLs(snap,key);assert.ok((await second.loadImage(id)).startsWith('blob:'));revokeMediaURLs(second)}finally{globalThis.fetch=originalFetch;if(originalCaches===undefined)delete globalThis.caches;else globalThis.caches=originalCaches}
});

test('visible images are not evicted when more than eight chunks are loaded', async () => {
 const key=await importPassword(password),packages=[],index={},bodies=new Map(),ids=[],png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf4sAAAAASUVORK5CYII=','base64');
 for(let i=0;i<9;i++){const bytes=Buffer.concat([png,Buffer.from([i])]),id=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex'),name='media-'+(i+20).toString(16).padStart(64,'0')+'.enc.json';packages.push(name);index[id]=name;ids.push(id);bodies.set('./'+name,await encryptData({schema_version:1,media:{[i+'.png']:{id,mime:'image/png',data:bytes.toString('base64')}}},key))}
 const original=globalThis.fetch;globalThis.fetch=async url=>new Response(JSON.stringify(bodies.get(url)));
 try{const urls=await createMediaURLs({...empty,media_packages:packages,media_index:index},key);urls.isImageInUse=id=>id===ids[0];for(const id of ids)await urls.loadImage(id);assert.equal(urls.size,8);assert.ok(urls.has(ids[0]));assert.equal(urls.has(ids[1]),false);revokeMediaURLs(urls)}finally{globalThis.fetch=original}
});

test('media downloads use at most two concurrent requests and coalesce same chunk', async () => {
 const key=await importPassword(password),packages=[],index={},bodies=new Map(),ids=[],png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf4sAAAAASUVORK5CYII=','base64');
 for(let i=0;i<3;i++){const bytes=Buffer.concat([png,Buffer.from([i])]),id=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex'),name='media-'+(i+50).toString(16).padStart(64,'0')+'.enc.json';packages.push(name);index[id]=name;ids.push(id);bodies.set('./'+name,await encryptData({schema_version:1,media:{[i+'.png']:{id,mime:'image/png',data:bytes.toString('base64')}}},key))}
 const original=globalThis.fetch;let active=0,maxActive=0,calls=0;globalThis.fetch=async url=>{calls++;active++;maxActive=Math.max(maxActive,active);await new Promise(r=>setTimeout(r,60));active--;return new Response(JSON.stringify(bodies.get(url)))};
 try{const urls=await createMediaURLs({...empty,media_packages:packages,media_index:index},key);const results=await Promise.all([urls.loadImage(ids[0]),urls.loadImage(ids[0]),urls.loadImage(ids[1]),urls.loadImage(ids[2])]);assert.equal(results[0],results[1]);assert.equal(calls,3);assert.equal(maxActive,2);revokeMediaURLs(urls)}finally{globalThis.fetch=original}
});
