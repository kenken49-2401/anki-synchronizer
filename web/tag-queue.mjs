// GitHub performs sign-in and final confirmation. No browser API token is used.
export const TAG_REPOSITORY = "kenken49-2401/anki-synchronizer";
export const TAG_TITLE = "[Anki Atlas] Encrypted tag update";
export const TAG_MARKER = "<!-- anki-atlas-tag-request:v1 -->";

export function tagRequest(encoded) {
  if (typeof encoded !== "string" || encoded.length > 59000)
    throw new Error(
      "変更が多すぎます。小分けに送信するか、変更ファイルをPCで取り込んでください。",
    );
  const data = JSON.parse(encoded);
  const keys = [
    "format",
    "version",
    "kdf",
    "iterations",
    "salt",
    "iv",
    "ciphertext",
  ];
  if (
    data?.format !== "anki-atlas-encrypted" ||
    data.version !== 1 ||
    Object.keys(data).length !== keys.length ||
    keys.some((k) => !Object.hasOwn(data, k)) ||
    data.kdf !== "PBKDF2-SHA256" ||
    data.iterations !== 600000 ||
    typeof data.salt !== "string" ||
    !/^[A-Za-z0-9+/]{22}==$/.test(data.salt) ||
    typeof data.iv !== "string" ||
    !/^[A-Za-z0-9+/]{16}$/.test(data.iv) ||
    typeof data.ciphertext !== "string" ||
    !/^[A-Za-z0-9+/]+={0,2}$/.test(data.ciphertext)
  )
    throw new Error("暗号化した下書きだけを送信できます。");
  const body = `${TAG_MARKER}\n\`\`\`json\n${JSON.stringify(data)}\n\`\`\``;
  const base = `https://github.com/${TAG_REPOSITORY}/issues/new`;
  const params = new URLSearchParams({ title: TAG_TITLE, body });
  const full = `${base}?${params}`;
  // Large requests are copied into GitHub's form, avoiding URL size limits.
  return {
    body,
    prefilled: full.length <= 7000,
    url:
      full.length <= 7000
        ? full
        : `${base}?${new URLSearchParams({ title: TAG_TITLE })}`,
  };
}

export function unconfirmedTags(snapshot, changes) {
  const notes = new Map();
  for (const c of snapshot.cards) {
    if (!notes.has(c.note_id)) notes.set(c.note_id, []);
    notes.get(c.note_id).push(c);
  }
  const result = new Map();
  for (const [id, change] of changes) {
    const cards = notes.get(id) || [];
    const tags = change.add_tags.filter(
      (t) =>
        !cards.length ||
        !cards.every((c) =>
          c.tags.some((existing) => existing.toLowerCase() === t.toLowerCase()),
        ),
    );
    if (tags.length) result.set(id, { ...change, add_tags: tags });
  }
  return result;
}
