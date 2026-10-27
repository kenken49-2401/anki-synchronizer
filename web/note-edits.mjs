// Edit original note fields, never reverse-engineer rendered card templates.
const validText = (s, max, nonempty = false) =>
  typeof s === "string" &&
  [...s].length <= max &&
  (!nonempty || s.trim().length > 0) &&
  !/[\u0000\uD800-\uDFFF]/u.test(s);
const id = (n) => Number.isSafeInteger(n) && n > 0;
const keys = (o, expected) =>
  o &&
  typeof o === "object" &&
  !Array.isArray(o) &&
  Object.keys(o).length === expected.length &&
  expected.every((k) => Object.hasOwn(o, k));
export const sameFields = (a, b) =>
  !!a &&
  !!b &&
  Object.keys(a).length === Object.keys(b).length &&
  Object.keys(a).every((k) => Object.hasOwn(b, k) && a[k] === b[k]);
const fieldsOK = (o) =>
  o &&
  typeof o === "object" &&
  !Array.isArray(o) &&
  Object.keys(o).length >= 1 &&
  Object.keys(o).length <= 64 &&
  Object.entries(o).every(
    ([k, v]) => validText(k, 256, true) && validText(v, 128000),
  );
export function validateNoteChanges(p) {
  const invalid = () => {
    throw new Error("本文変更ファイルの形式が正しくありません。");
  };
  if (
    !keys(p, ["format", "version", "created_at", "source", "changes"]) ||
    p.format !== "anki-atlas-note-changes" ||
    p.version !== 1 ||
    !validText(p.created_at, 64) ||
    !Number.isFinite(Date.parse(p.created_at)) ||
    !/(Z|[+-]\d\d:\d\d)$/.test(p.created_at) ||
    !keys(p.source, ["kind", "profile"]) ||
    !["ankiweb", "ankiconnect"].includes(p.source.kind) ||
    !validText(p.source.profile, 256, true) ||
    !Array.isArray(p.changes) ||
    !p.changes.length ||
    p.changes.length > 500
  )
    invalid();
  const notes = new Set(),
    cards = new Set();
  for (const c of p.changes) {
    if (
      !keys(c, [
        "note_id",
        "card_ids",
        "model",
        "fingerprint",
        "fields",
        "set_fields",
      ]) ||
      !id(c.note_id) ||
      notes.has(c.note_id) ||
      !validText(c.model, 256, true) ||
      !/^[a-f0-9]{64}$/.test(c.fingerprint || "") ||
      !Array.isArray(c.card_ids) ||
      !c.card_ids.length ||
      c.card_ids.length > 50000 ||
      !fieldsOK(c.fields) ||
      !fieldsOK(c.set_fields) ||
      Object.entries(c.set_fields).some(
        ([k, v]) => !Object.hasOwn(c.fields, k) || c.fields[k] === v,
      )
    )
      invalid();
    notes.add(c.note_id);
    for (const cid of c.card_ids) {
      if (!id(cid) || cards.has(cid) || cards.size >= 50000) invalid();
      cards.add(cid);
    }
  }
  return p;
}
export function notePayload(snapshot, changes) {
  return validateNoteChanges({
    format: "anki-atlas-note-changes",
    version: 1,
    created_at: new Date().toISOString(),
    source: { kind: snapshot.source.kind, profile: snapshot.source.profile },
    changes: [...changes.values()],
  });
}
export async function noteFingerprint(model, fields) {
  // Python sorts by Unicode code point; default JS sort uses UTF-16 code units.
  const compare = (a, b) => {
    const x = [...a],
      y = [...b];
    for (let i = 0; i < Math.min(x.length, y.length); i++) {
      const d = x[i].codePointAt(0) - y[i].codePointAt(0);
      if (d) return d;
    }
    return x.length - y.length;
  };
  const raw = JSON.stringify([
    model,
    Object.keys(fields)
      .sort(compare)
      .map((k) => [k, fields[k]]),
  ]);
  return [
    ...new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw)),
    ),
  ]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
export function noteEditStatus(snapshot, change) {
  const cards = snapshot.cards.filter((c) => c.note_id === change.note_id);
  if (
    !cards.length ||
    cards.some((c) => c.model !== change.model || !c.editable_fields) ||
    change.card_ids.some((id) => !cards.some((c) => c.id === id))
  )
    return "conflict";
  const desired = { ...change.fields, ...change.set_fields };
  if (cards.every((c) => sameFields(c.editable_fields, desired)))
    return "applied";
  if (
    cards.every(
      (c) =>
        c.tag_identity === change.fingerprint &&
        sameFields(c.editable_fields, change.fields),
    )
  )
    return "pending";
  return "conflict";
}
export function unconfirmedNoteEdits(snapshot, changes) {
  return new Map(
    [...changes].filter(([, c]) => noteEditStatus(snapshot, c) !== "applied"),
  );
}
export async function stageNoteEdit(snapshot, changes, noteId, updates) {
  const cards = snapshot.cards.filter((c) => c.note_id === noteId),
    first = cards[0];
  if (
    !first ||
    !fieldsOK(first.editable_fields) ||
    cards.some(
      (c) =>
        c.model !== first.model ||
        c.tag_identity !== first.tag_identity ||
        !sameFields(c.editable_fields, first.editable_fields),
    ) ||
    (await noteFingerprint(first.model, first.editable_fields)) !==
      first.tag_identity
  )
    throw new Error(
      "本文編集用のデータが必要です。最新のAnkiWeb同期・Pages更新後に読み直してください。",
    );
  if (
    changes.has(noteId) &&
    noteEditStatus(snapshot, changes.get(noteId)) === "conflict"
  )
    throw new Error(
      "Anki側の本文が変わっています。下書きを保存して取り消し、最新の本文から編集し直してください。",
    );
  if (
    !updates ||
    typeof updates !== "object" ||
    Object.keys(updates).some((k) => !Object.hasOwn(first.editable_fields, k))
  )
    throw new Error("フィールドが一致しません。");
  const set_fields = Object.fromEntries(
    Object.entries(updates).filter(([k, v]) => v !== first.editable_fields[k]),
  );
  const next = new Map(changes);
  if (!Object.keys(set_fields).length) next.delete(noteId);
  else {
    next.set(noteId, {
      note_id: noteId,
      card_ids: cards.map((c) => c.id),
      model: first.model,
      fingerprint: first.tag_identity,
      fields: { ...first.editable_fields },
      set_fields,
    });
    notePayload(snapshot, next);
  }
  return next;
}
