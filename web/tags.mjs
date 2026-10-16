// Pending additions belong to Anki notes, shared by all sibling cards.
export function parseTags(text) {
  const unique = new Map();
  for (const tag of text.trim().split(/\s+/u).filter(Boolean))
    if (!unique.has(tag.toLowerCase())) unique.set(tag.toLowerCase(), tag);
  const tags = [...unique.values()];
  if (
    !tags.length ||
    tags.length > 100 ||
    tags.some((t) => [...t].length > 128 || /[\s\p{C}*?]/u.test(t))
  )
    throw new Error(
      "タグは空白で区切って入力してください。1個128文字以内、最大100個で、制御文字・*・?は使えません。",
    );
  return tags;
}

export function validateChanges(value) {
  const id = (n) => Number.isSafeInteger(n) && n > 0;
  if (
    value?.format !== "anki-atlas-tag-changes" ||
    value.version !== 1 ||
    !["ankiweb", "ankiconnect"].includes(value.source?.kind) ||
    typeof value.source.profile !== "string" ||
    value.source.profile.length > 256 ||
    !Array.isArray(value.changes) ||
    value.changes.length > 50000 ||
    typeof value.created_at !== "string" ||
    !Number.isFinite(Date.parse(value.created_at))
  )
    throw new Error("タグ変更ファイルの形式が正しくありません。");
  const notes = new Set(),
    cards = new Set();
  for (const c of value.changes) {
    if (
      !c ||
      !id(c.note_id) ||
      notes.has(c.note_id) ||
      !Array.isArray(c.card_ids) ||
      !c.card_ids.length ||
      c.card_ids.length > 50000 ||
      typeof c.model !== "string" ||
      c.model.length > 256 ||
      !/^[a-f0-9]{64}$/.test(c.fingerprint || "") ||
      !Array.isArray(c.add_tags) ||
      !c.add_tags.length ||
      c.add_tags.length > 100 ||
      c.add_tags.some(
        (t) =>
          typeof t !== "string" ||
          !t ||
          [...t].length > 128 ||
          /[\s\p{C}*?]/u.test(t),
      ) ||
      new Set(c.add_tags).size !== c.add_tags.length
    )
      throw new Error("タグ変更ファイルの形式が正しくありません。");
    notes.add(c.note_id);
    for (const n of c.card_ids) {
      if (!id(n) || cards.has(n) || cards.size >= 50000)
        throw new Error("タグ変更のカードが重複または不正です。");
      cards.add(n);
    }
  }
  return value;
}

export function tagPayload(snapshot, changes) {
  return validateChanges({
    format: "anki-atlas-tag-changes",
    version: 1,
    created_at: new Date().toISOString(),
    source: { kind: snapshot.source.kind, profile: snapshot.source.profile },
    changes: [...changes.values()],
  });
}

export function stageTags(snapshot, changes, noteId, text) {
  const cards = snapshot.cards.filter((c) => c.note_id === noteId),
    first = cards[0];
  if (
    !first ||
    !/^[a-f0-9]{64}$/.test(first.tag_identity || "") ||
    cards.some(
      (c) => c.tag_identity !== first.tag_identity || c.model !== first.model,
    )
  )
    throw new Error(
      "このカードはタグ編集に対応するデータへ更新が必要です。Ankiから取り込み直してください。",
    );
  const additions = parseTags(
    [...(changes.get(noteId)?.add_tags || []), text].join(" "),
  );
  const tags = additions.filter(
    (tag) =>
      !cards.every((c) =>
        c.tags.some((t) => t.toLowerCase() === tag.toLowerCase()),
      ),
  );
  if (tags.length > 100)
    throw new Error("1ノートに追加できるタグは100個までです。");
  const next = new Map(changes);
  if (tags.length)
    next.set(noteId, {
      note_id: noteId,
      card_ids: cards.map((c) => c.id),
      model: first.model,
      fingerprint: first.tag_identity,
      add_tags: tags,
    });
  return next;
}

export function withTagChanges(snapshot, changes) {
  const notes = new Map(snapshot.cards.map((c) => [c.note_id, c]));
  for (const entry of changes.values()) {
    const card = notes.get(entry.note_id);
    if (
      !card ||
      card.model !== entry.model ||
      card.tag_identity !== entry.fingerprint
    )
      throw new Error(
        "保存したタグ変更と現在のカードが一致しません。変更ファイルをPCで取り込むか、下書きを取り消してください。",
      );
  }
  return {
    ...snapshot,
    cards: snapshot.cards.map((c) => {
      const entry = changes.get(c.note_id);
      if (
        entry &&
        (c.model !== entry.model || c.tag_identity !== entry.fingerprint)
      )
        throw new Error(
          "同じノートのカードが一致しません。Ankiから取り込み直してください。",
        );
      return {
        ...c,
        tags: [...new Set([...c.tags, ...(entry?.add_tags || [])])],
      };
    }),
  };
}
