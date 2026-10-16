import test from "node:test";
import assert from "node:assert/strict";
import {
  parseTags,
  stageTags,
  tagPayload,
  validateChanges,
  withTagChanges,
} from "../web/tags.mjs";
const card = {
  id: 1,
  note_id: 10,
  model: "Basic",
  tag_identity: "a".repeat(64),
  tags: ["既存"],
};
const snapshot = {
  source: { kind: "ankiweb", profile: "AnkiWeb", timezone: "Asia/Tokyo" },
  cards: [card, { ...card, id: 2 }, { ...card, id: 3, note_id: 20 }],
};
test("Anki tag capitalization does not create duplicate additions", () => {
  assert.deepEqual(parseTags("Review review REVIEW"), ["Review"]);
  const data = { ...snapshot, cards: [{ ...card, tags: ["Review"] }] };
  assert.equal(stageTags(data, new Map(), 10, "review").size, 0);
});
test("manual tags accept Japanese hierarchy, deduplicate and reject special/control characters", () => {
  assert.deepEqual(parseTags(" 要復習  化学::高分子 要復習 "), [
    "要復習",
    "化学::高分子",
  ]);
  for (const text of ["", "a*", "a?", "a\u200b", "a".repeat(129)])
    assert.throws(() => parseTags(text));
});
test("staging changes every sibling card, leaves other notes and original tags untouched", () => {
  const changes = stageTags(snapshot, new Map(), 10, "要復習 既存");
  assert.deepEqual(changes.get(10).add_tags, ["要復習"]);
  const visible = withTagChanges(snapshot, changes);
  assert.deepEqual(
    visible.cards.map((c) => c.tags),
    [["既存", "要復習"], ["既存", "要復習"], ["既存"]],
  );
  assert.deepEqual(snapshot.cards[0].tags, ["既存"]);
  assert.equal(stageTags(snapshot, changes, 10, "要復習").size, 1);
  assert.equal(stageTags(snapshot, new Map(), 10, "既存").size, 0);
});
test("export has only addition operations and binds original note identity", () => {
  const data = tagPayload(snapshot, stageTags(snapshot, new Map(), 10, "復習"));
  assert.deepEqual(data.source, { kind: "ankiweb", profile: "AnkiWeb" });
  assert.deepEqual(data.changes[0].card_ids, [1, 2]);
  assert.equal(data.changes[0].fingerprint, card.tag_identity);
  assert.equal(validateChanges(data), data);
  assert.throws(() =>
    validateChanges({ ...data, changes: [...data.changes, ...data.changes] }),
  );
  assert.throws(() =>
    withTagChanges(
      {
        ...snapshot,
        cards: snapshot.cards.map((c) => ({
          ...c,
          tag_identity: "b".repeat(64),
        })),
      },
      new Map([[10, data.changes[0]]]),
    ),
  );
  assert.throws(() =>
    stageTags(
      { ...snapshot, cards: [{ ...card, tag_identity: undefined }] },
      new Map(),
      10,
      "復習",
    ),
  );
});
