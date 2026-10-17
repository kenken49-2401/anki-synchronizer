import test from "node:test";
import assert from "node:assert/strict";
import { updateChecker } from "../web/updates.mjs";
const old = "a".repeat(64),
  next = "b".repeat(64);
const response = (version = next) =>
  new Response(JSON.stringify({ schema_version: 1, version }));

test("a new build reloads automatically without sending credentials", async () => {
  let actual = null;
  const check = updateChecker({
    current: old,
    safe: () => true,
    reload: (v) => (actual = v),
    fetcher: async (url, options) => {
      assert.equal(url, "./release.json");
      assert.deepEqual(options, {
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
      });
      return response();
    },
  });
  await check();
  assert.equal(actual, next);
});
test("unsaved input delays update and a later safe check applies it", async () => {
  let safe = false,
    reloads = 0,
    notices = 0;
  const check = updateChecker({
    current: old,
    safe: () => safe,
    reload: () => reloads++,
    waiting: () => notices++,
    fetcher: async () => response(),
  });
  await check();
  await check();
  assert.equal(reloads, 0);
  assert.equal(notices, 1);
  safe = true;
  await check();
  assert.equal(reloads, 1);
});
test("offline, unchanged, malformed, and oversized releases do not reload", async () => {
  for (const fetcher of [
    async () => {
      throw new Error("offline");
    },
    async () => response(old),
    async () => new Response("not json"),
    async () => response("not-a-version"),
    async () => new Response("x".repeat(1100)),
    async () => new Response("", { status: 503 }),
  ]) {
    const check = updateChecker({
      current: old,
      safe: () => true,
      reload: () => assert.fail("unexpected reload"),
      fetcher,
    });
    await check();
  }
});
test("a delayed CDN deployment cannot produce a reload loop across page loads", async () => {
  const cache = new Map(),
    storage = {
      getItem: (k) => cache.get(k),
      setItem: (k, v) => cache.set(k, v),
    };
  let time = 100000,
    reloads = 0;
  const options = {
    current: old,
    safe: () => true,
    reload: () => reloads++,
    fetcher: async () => response(),
    storage,
    now: () => time,
  };
  await updateChecker(options)();
  await updateChecker(options)();
  assert.equal(reloads, 1);
  time += 61000;
  await updateChecker(options)();
  assert.equal(reloads, 2);
  assert.deepEqual([...cache.keys()], ["atlas-update-attempt"]);
});
