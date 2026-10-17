import test from "node:test";
import assert from "node:assert/strict";
import {
  createDeviceSessionStore,
  DeviceSessionError,
} from "../web/device-session.mjs";
import { importPassword, encryptData, decryptData } from "../web/vault.mjs";

// Model transaction commit separately from request success, including storage
// revocation after a successful put. Real Chromium structured-clone persistence
// is also exercised by the browser QA workflow.
function browser() {
  const databases = new Map();
  const state = { abort: false, opens: [] };
  const env = {
    isSecureContext: true,
    crypto,
    CryptoKey,
    document: { baseURI: "https://example.test/atlas/index.html?x=1" },
    indexedDB: {
      open(name) {
        state.opens.push(name);
        const request = {};
        setImmediate(() => {
          const data = databases.get(name) || new Map();
          databases.set(name, data);
          request.result = {
            objectStoreNames: { contains: () => true },
            close() {},
            transaction() {
              const tx = {
                abort() {},
                objectStore() {
                  function operation(kind, key, value) {
                    const req = {};
                    setImmediate(() => {
                      req.result =
                        kind === "get"
                          ? structuredClone(data.get(key))
                          : undefined;
                      req.onsuccess?.();
                      setImmediate(() => {
                        if (state.abort) {
                          tx.error = new DOMException(
                            "Storage revoked",
                            "QuotaExceededError",
                          );
                          tx.onabort?.();
                        } else {
                          if (kind === "put")
                            data.set(key, structuredClone(value));
                          if (kind === "delete") data.delete(key);
                          tx.oncomplete?.();
                        }
                      });
                    });
                    return req;
                  }
                  return {
                    get: (key) => operation("get", key),
                    put: (value, key) => operation("put", key, value),
                    delete: (key) => operation("delete", key),
                  };
                },
              };
              return tx;
            },
          };
          request.onsuccess();
        });
        return request;
      },
    },
  };
  return { env, state, databases, store: createDeviceSessionStore(env) };
}

const key = await importPassword("device-test-password-only-1732");

test("remembered key stays non-extractable and decrypts snapshots and tag drafts", async () => {
  const { store } = browser();
  assert.equal(await store.loadDeviceKey(), null);
  const data = { private: "encrypted tag draft" };
  const encrypted = await encryptData(data, key);
  assert.equal(await store.rememberDevice(key), true);
  const restored = await store.loadDeviceKey();
  assert.notEqual(restored, key);
  assert.equal(restored.extractable, false);
  await assert.rejects(crypto.subtle.exportKey("raw", restored));
  assert.deepEqual(await decryptData(encrypted, restored), data);
  assert.equal(await store.forgetDevice(), true);
  assert.equal(await store.loadDeviceKey(), null);
  assert.equal(await store.forgetDevice(), true);
});

test("request success followed by transaction abort is a failed save", async () => {
  const { store, state } = browser();
  state.abort = true;
  await assert.rejects(
    store.rememberDevice(key),
    (e) => e instanceof DeviceSessionError && e.code === "storage",
  );
  state.abort = false;
  assert.equal(await store.loadDeviceKey(), null);
});

test("failed forgetting reports failure and preserves the previously committed key", async () => {
  const { store, state } = browser();
  await store.rememberDevice(key);
  state.abort = true;
  await assert.rejects(store.forgetDevice(), { code: "storage" });
  state.abort = false;
  assert.ok(await store.loadDeviceKey());
});

test("GitHub Pages app directories are isolated but index and query variants agree", async () => {
  const { env, store, state } = browser();
  await store.rememberDevice(key);
  env.document.baseURI = "https://example.test/atlas/?v=2";
  assert.ok(await store.loadDeviceKey());
  env.document.baseURI = "https://example.test/another-app/";
  assert.equal(await store.loadDeviceKey(), null);
  assert.deepEqual(state.opens, [
    "anki-atlas-device:v1:/atlas/",
    "anki-atlas-device:v1:/atlas/",
    "anki-atlas-device:v1:/another-app/",
  ]);
});

test("insecure, denied and unavailable storage produce typed errors", async () => {
  const { env } = browser();
  env.isSecureContext = false;
  await assert.rejects(createDeviceSessionStore(env).loadDeviceKey(), {
    code: "unavailable",
  });
  env.isSecureContext = true;
  env.indexedDB.open = () => {
    throw new DOMException("Denied", "SecurityError");
  };
  await assert.rejects(createDeviceSessionStore(env).loadDeviceKey(), {
    code: "storage",
  });
  Object.defineProperty(env, "indexedDB", {
    get() {
      throw new DOMException("Denied", "SecurityError");
    },
  });
  await assert.rejects(createDeviceSessionStore(env).loadDeviceKey(), {
    code: "unavailable",
  });
});

test("plaintext, forged, extractable and unrelated keys cannot be remembered", async () => {
  const { store, state } = browser();
  const aes = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt"],
  );
  const exportable = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt"],
  );
  for (const value of [
    "password",
    {},
    { ...key },
    Object.create(CryptoKey.prototype),
    aes,
    exportable,
    null,
  ]) {
    await assert.rejects(store.rememberDevice(value), { code: "invalid-key" });
  }
  assert.equal(state.opens.length, 0);
});

test("malformed stored records fail without silently deleting remembered state", async () => {
  const { store, databases } = browser();
  await store.rememberDevice(key);
  const data = databases.values().next().value;
  data.set("master-key", {
    version: 1,
    key: "plaintext must never be accepted",
  });
  await assert.rejects(store.loadDeviceKey(), { code: "invalid-record" });
  assert.equal(data.has("master-key"), true);
});
