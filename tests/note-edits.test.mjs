import test from "node:test";
import assert from "node:assert/strict";
import {
  stageNoteEdit,
  notePayload,
  noteFingerprint,
  noteEditStatus,
  unconfirmedNoteEdits,
  validateNoteChanges,
} from "../web/note-edits.mjs";
import { noteRequest, NOTE_MARKER, NOTE_TITLE } from "../web/tag-queue.mjs";
import { encryptData, decryptData, importPassword } from "../web/vault.mjs";
const fields = {
  Front: 'C<sub>2</sub>H<sub>4</sub><img src="molecule.png">',
  Back: "{{c1::polymer}}",
};
async function snapshot() {
  const tag_identity = await noteFingerprint("Basic", fields);
  return {
    source: { kind: "ankiweb", profile: "AnkiWeb" },
    cards: [1, 2].map((id) => ({
      id,
      note_id: 3,
      model: "Basic",
      tag_identity,
      editable_fields: { ...fields },
      fields: { Front: "C2H4", Back: "polymer" },
      tags: ["existing"],
    })),
  };
}
test("edits use raw HTML, bind siblings and retain other fields; reverting removes the draft", async () => {
  const s = await snapshot(),
    next = await stageNoteEdit(s, new Map(), 3, {
      ...fields,
      Back: "new answer",
    }),
    c = next.get(3);
  assert.deepEqual(c.card_ids, [1, 2]);
  assert.deepEqual(c.fields, fields);
  assert.deepEqual(c.set_fields, { Back: "new answer" });
  assert.equal(s.cards[0].editable_fields.Back, fields.Back);
  assert.equal(noteEditStatus(s, c), "pending");
  assert.equal((await stageNoteEdit(s, next, 3, fields)).size, 0);
});
test("already-applied changes clear only after all sibling fields match; conflicts survive for recovery", async () => {
  const s = await snapshot(),
    changes = await stageNoteEdit(s, new Map(), 3, { Back: "" }),
    c = changes.get(3);
  const applied = structuredClone(s);
  for (const card of applied.cards) {
    card.editable_fields.Back = "";
    card.tag_identity = await noteFingerprint("Basic", card.editable_fields);
  }
  assert.equal(noteEditStatus(applied, c), "applied");
  assert.equal(unconfirmedNoteEdits(applied, changes).size, 0);
  applied.cards[1].editable_fields.Front = "phone edit";
  assert.equal(noteEditStatus(applied, c), "conflict");
  assert.equal(unconfirmedNoteEdits(applied, changes).size, 1);
  await assert.rejects(stageNoteEdit(applied, changes, 3, { Back: "other" }));
});
test("legacy, inconsistent raw fields, unknown fields, bad changes and duplicate card bindings fail", async () => {
  const s = await snapshot(),
    legacy = structuredClone(s);
  delete legacy.cards[0].editable_fields;
  await assert.rejects(stageNoteEdit(legacy, new Map(), 3, { Back: "x" }));
  await assert.rejects(stageNoteEdit(s, new Map(), 3, { Unknown: "x" }));
  const changes = await stageNoteEdit(s, new Map(), 3, { Back: "x" }),
    p = notePayload(s, changes);
  const invalid = structuredClone(p);
  invalid.changes[0].set_fields.Back = fields.Back;
  assert.throws(() => validateNoteChanges(invalid));
  const duplicate = structuredClone(p);
  duplicate.changes[0].card_ids.push(1);
  assert.throws(() => validateNoteChanges(duplicate));
  const surrogate = structuredClone(p);
  surrogate.changes[0].set_fields.Back = "\ud800";
  assert.throws(() => validateNoteChanges(surrogate));
});
test("note changes encrypt and open a distinct owner confirmation form without plaintext", async () => {
  const s = await snapshot(),
    changes = await stageNoteEdit(s, new Map(), 3, {
      Back: "secret revised answer",
    }),
    payload = notePayload(s, changes);
  const key = await importPassword("test-long-private-password"),
    encrypted = JSON.stringify(await encryptData(payload, key));
  const request = noteRequest(encrypted),
    url = new URL(request.url);
  assert.equal(url.searchParams.get("title"), NOTE_TITLE);
  assert.ok(request.body.startsWith(NOTE_MARKER));
  assert.ok(!request.url.includes("secret revised answer"));
  assert.ok(!request.body.includes(fields.Front));
  assert.deepEqual(await decryptData(JSON.parse(encrypted), key), payload);
});
