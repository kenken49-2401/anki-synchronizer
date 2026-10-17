// Opt-in device access: IndexedDB stores a structured-cloned, non-extractable
// PBKDF2 CryptoKey, never the password or exported key bytes. Anyone who can use
// this browser profile can unlock the data until forgetDevice() succeeds.
// Storage may be denied/evicted, so callers must keep ordinary sign-in available.
// All operations reject DeviceSessionError on failure; a missing key is null.
// Save only after successful decryption. Network/decryption failures never erase
// a remembered key here; explicit logout/forget must await forgetDevice().

export class DeviceSessionError extends Error {
  constructor(code, cause) {
    super(
      "この端末のログイン情報を保存・読み込みできません。ブラウザの保存設定を確認してください。",
      { cause },
    );
    this.name = "DeviceSessionError";
    this.code = code;
  }
}

const STORE = "device-session";
const SLOT = "master-key";
const TIMEOUT = 5000;

function validKey(key, env) {
  try {
    return (
      typeof env.CryptoKey === "function" &&
      key instanceof env.CryptoKey &&
      key.type === "secret" &&
      key.extractable === false &&
      key.algorithm?.name === "PBKDF2" &&
      key.usages.length === 1 &&
      key.usages[0] === "deriveKey"
    );
  } catch {
    return false;
  }
}

// Environment injection also lets storage error paths be tested without adding
// a dependency. Default exports below use the actual browser environment.
export function createDeviceSessionStore(env = globalThis) {
  function settings() {
    try {
      if (!env.isSecureContext || !env.crypto?.subtle || !env.indexedDB)
        throw new DeviceSessionError("unavailable");
      const path = new URL("./", env.document.baseURI).pathname;
      // GitHub Pages repositories share an origin; each app directory gets its
      // own database. Query strings and index.html do not change its identity.
      return { factory: env.indexedDB, name: "anki-atlas-device:v1:" + path };
    } catch (error) {
      throw error instanceof DeviceSessionError
        ? error
        : new DeviceSessionError("unavailable", error);
    }
  }

  async function open() {
    const { factory, name } = settings();
    return new Promise((resolve, reject) => {
      let finished = false;
      const timer = setTimeout(
        () => fail(new Error("Storage open timed out")),
        TIMEOUT,
      );
      function fail(error) {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        reject(new DeviceSessionError("storage", error));
      }
      try {
        const request = factory.open(name, 1);
        request.onupgradeneeded = () => {
          if (!request.result.objectStoreNames.contains(STORE))
            request.result.createObjectStore(STORE);
        };
        request.onerror = () => fail(request.error);
        request.onblocked = () => fail(new Error("Storage upgrade blocked"));
        request.onsuccess = () => {
          const db = request.result;
          if (finished) {
            db.close();
            return;
          }
          finished = true;
          clearTimeout(timer);
          db.onversionchange = () => db.close();
          resolve(db);
        };
      } catch (error) {
        fail(error);
      }
    });
  }

  async function run(mode, action) {
    const db = await open();
    return new Promise((resolve, reject) => {
      let transaction,
        result,
        finished = false;
      const timer = setTimeout(() => {
        try {
          transaction?.abort();
        } catch {
          /* already completed */
        }
        finish(new Error("Storage transaction timed out"));
      }, TIMEOUT);
      function finish(error) {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        db.close();
        if (error) reject(new DeviceSessionError("storage", error));
        else resolve(result);
      }
      try {
        // Ask for a durable commit where supported, while supporting older
        // Safari versions that do not accept the options argument.
        try {
          transaction = db.transaction(STORE, mode, { durability: "strict" });
        } catch (error) {
          if (!(error instanceof TypeError)) throw error;
          transaction = db.transaction(STORE, mode);
        }
        transaction.oncomplete = () => finish();
        transaction.onabort = () =>
          finish(transaction.error || new Error("Storage transaction aborted"));
        const request = action(transaction.objectStore(STORE));
        request.onsuccess = () => {
          result = request.result;
        };
        // Request success is not a durable commit: quota/revocation can abort
        // the transaction afterwards. Its onabort handler reports that failure.
      } catch (error) {
        try {
          transaction?.abort();
        } catch {
          /* inactive */
        }
        finish(error);
      }
    });
  }

  return {
    async rememberDevice(key) {
      if (!validKey(key, env)) throw new DeviceSessionError("invalid-key");
      await run("readwrite", (store) => store.put({ version: 1, key }, SLOT));
      return true;
    },
    async loadDeviceKey() {
      const record = await run("readonly", (store) => store.get(SLOT));
      if (record === undefined) return null;
      if (record?.version !== 1 || !validKey(record.key, env))
        throw new DeviceSessionError("invalid-record");
      return record.key;
    },
    async forgetDevice() {
      await run("readwrite", (store) => store.delete(SLOT));
      return true;
    },
  };
}

const device = createDeviceSessionStore();
export const rememberDevice = device.rememberDevice;
export const loadDeviceKey = device.loadDeviceKey;
export const forgetDevice = device.forgetDevice;
