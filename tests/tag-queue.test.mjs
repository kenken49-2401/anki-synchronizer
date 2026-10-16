import test from "node:test";
import assert from "node:assert/strict";
import { encryptData, importPassword } from "../web/vault.mjs";
import {
  tagRequest,
  unconfirmedTags,
  TAG_MARKER,
  TAG_TITLE,
} from "../web/tag-queue.mjs";

test("phone submission contains only ciphertext and opens the correct GitHub confirmation form", async () => {
  const key = await importPassword("browser-test-only-password-62710");
  const encoded = JSON.stringify(
    await encryptData({ private: "PRIVATE_TAG_QUEUE_TEST" }, key),
  );
  const request = tagRequest(encoded),
    url = new URL(request.url);
  assert.equal(url.origin, "https://github.com");
  assert.equal(url.pathname, "/kenken49-2401/anki-synchronizer/issues/new");
  assert.equal(url.searchParams.get("title"), TAG_TITLE);
  assert.equal(url.searchParams.get("body"), request.body);
  assert.ok(request.body.startsWith(TAG_MARKER));
  assert.ok(
    !request.url.includes("PRIVATE_TAG_QUEUE_TEST") &&
      !request.body.includes("PRIVATE_TAG_QUEUE_TEST"),
  );
  assert.equal(request.prefilled, true);
  assert.throws(() =>
    tagRequest(
      JSON.stringify({
        format: "anki-atlas-tag-changes",
        add_tags: ["private"],
      }),
    ),
  );
  assert.throws(() =>
    tagRequest(
      JSON.stringify({ ...JSON.parse(encoded), private: "must never be sent" }),
    ),
  );
});

test("large encrypted submissions use copy/paste rather than oversized URLs", async () => {
  const encoded = JSON.stringify(
    await encryptData(
      { padding: "x".repeat(9000) },
      await importPassword("browser-test-only-password-62710"),
    ),
  );
  const request = tagRequest(encoded);
  assert.equal(request.prefilled, false);
  assert.equal(new URL(request.url).searchParams.get("body"), null);
  assert.ok(request.url.length < 200);
  assert.throws(() => tagRequest("x".repeat(60000)));
});

test("confirmed server tags clear pending additions without discarding unapplied tags", () => {
  const changes = new Map([
    [10, { note_id: 10, add_tags: ["Review", "未反映"] }],
    [20, { note_id: 20, add_tags: ["済"] }],
  ]);
  const snapshot = {
    cards: [
      { note_id: 10, tags: ["review"] },
      { note_id: 10, tags: ["review"] },
      { note_id: 20, tags: ["済"] },
    ],
  };
  const pending = unconfirmedTags(snapshot, changes);
  assert.equal(pending.size, 1);
  assert.deepEqual(pending.get(10).add_tags, ["未反映"]);
  assert.deepEqual(changes.get(10).add_tags, ["Review", "未反映"]);
  assert.equal(unconfirmedTags({ cards: [] }, changes).size, 2);
});
