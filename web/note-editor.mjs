import { encryptData, decryptData, MAX_PACKAGE } from "./vault.mjs";
import {
  stageNoteEdit,
  notePayload,
  validateNoteChanges,
  noteEditStatus,
  unconfirmedNoteEdits,
} from "./note-edits.mjs";
const SLOT = "atlas-note-draft";
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );

export function createNoteEditor({
  snapshot,
  key,
  demo,
  tagPending,
  onChange,
  notify,
  send,
}) {
  const state = {
    changes: new Map(),
    busy: false,
    stored: null,
    storageError: false,
    recoveryError: false,
  };
  const active = () => document.querySelector("#note-edit-dialog[open]");
  const conflicts = (data = snapshot()) =>
    [...state.changes.values()].some(
      (c) => noteEditStatus(data, c) === "conflict",
    );
  function checkVersion() {
    if (localStorage.getItem(SLOT) !== state.stored)
      throw new Error(
        "別のタブで本文の下書きが更新されました。バックアップを保存してから読み直してください。",
      );
  }
  async function persist(data = snapshot()) {
    if (demo()) return;
    if (state.recoveryError)
      throw new Error(
        "以前の本文の下書きを保存・取り消してから編集してください。",
      );
    checkVersion();
    if (!state.changes.size) {
      localStorage.removeItem(SLOT);
      state.stored = null;
      return;
    }
    const currentKey = key(),
      encoded = JSON.stringify(
        await encryptData(notePayload(data, state.changes), currentKey),
      );
    if (!currentKey || currentKey !== key())
      throw new Error("ログイン状態が変わりました。読み直してください。");
    checkVersion();
    localStorage.setItem(SLOT, encoded);
    state.stored = encoded;
  }
  async function reconcile(data) {
    const pending = unconfirmedNoteEdits(data, state.changes);
    if (pending.size === state.changes.size) return;
    state.changes = pending;
    try {
      await persist(data);
      state.storageError = false;
    } catch {
      state.storageError = true;
    }
  }
  async function restore(data) {
    try {
      state.stored = localStorage.getItem(SLOT);
      if (!state.stored) return;
      if (state.stored.length > MAX_PACKAGE) throw new Error();
      const p = validateNoteChanges(
        await decryptData(JSON.parse(state.stored), key()),
      );
      if (
        p.source.kind !== data.source.kind ||
        p.source.profile !== data.source.profile
      )
        throw new Error();
      state.changes = new Map(p.changes.map((c) => [c.note_id, c]));
      await reconcile(data);
    } catch {
      state.recoveryError = true;
    }
  }
  function download(contents) {
    const url = URL.createObjectURL(
      new Blob([contents], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "anki-note-changes.enc.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function backup() {
    if (demo()) {
      notify("デモの変更は書き出せません。");
      return;
    }
    if (state.busy) return;
    state.busy = true;
    try {
      if (state.recoveryError) {
        if (state.stored) download(state.stored);
        return;
      }
      const currentKey = key(),
        encoded = await encryptData(
          notePayload(snapshot(), state.changes),
          currentKey,
        );
      if (!currentKey || currentKey !== key()) return;
      download(JSON.stringify(encoded));
    } catch {
      notify("本文のバックアップを保存できませんでした。");
    } finally {
      state.busy = false;
    }
  }
  async function discard(noteId = null) {
    if (
      state.busy ||
      !confirm(
        "本文の下書きを取り消しますか？送信済みの変更は、GitHubのIssueを処理前に閉じて取り消してください。",
      )
    )
      return;
    state.busy = true;
    try {
      checkVersion();
      if (noteId === null) {
        if (!demo()) localStorage.removeItem(SLOT);
        state.stored = null;
        state.changes.clear();
        state.recoveryError = false;
        state.storageError = false;
      } else {
        state.changes.delete(noteId);
        await persist();
        state.storageError = false;
      }
      onChange();
    } catch (e) {
      state.storageError = true;
      notify(e.message);
    } finally {
      state.busy = false;
    }
  }
  function sendable() {
    if (demo()) throw new Error("デモの変更は送信できません。");
    if (
      state.busy ||
      !state.changes.size ||
      state.recoveryError ||
      state.storageError ||
      !state.stored
    )
      throw new Error("本文の下書きを端末に保存してから送信してください。");
    checkVersion();
    if (conflicts())
      throw new Error(
        "Anki側の本文が変わった下書きがあります。バックアップを保存して取り消し、最新の本文から編集し直してください。",
      );
    return state.stored;
  }
  function button(card) {
    const entry = state.changes.get(card.note_id),
      status = entry ? noteEditStatus(snapshot(), entry) : null;
    return `<div class="note-edit-status"><button class="button subtle small" data-edit-note="${card.id}" ${!card.editable_fields ? "disabled" : ""}>本文を編集${entry ? "（下書きあり）" : ""}</button>${!card.editable_fields ? '<span class="muted small">本文編集用のデータは次の同期・公開後に利用できます。</span>' : ""}${entry ? `<span class="small ${status === "conflict" ? "error" : "muted"}">${status === "conflict" ? "Anki側の本文と競合しています。" : "未反映の本文があります。カード表示はAnkiへの反映・再取得後に更新されます。"}</span>` : ""}</div>`;
  }
  function panel() {
    const count = state.changes.size,
      bad = state.recoveryError || state.storageError;
    const note = state.recoveryError
      ? "以前の本文の下書きを復元できません。バックアップを保存してから取り消してください。"
      : state.storageError
        ? "端末への保存に失敗しました。閉じる前にバックアップを保存してください。"
        : count && conflicts()
          ? "Anki側で本文が変わったノートがあります。下書きを保存して取り消し、最新の本文から編集し直してください。"
          : count
            ? "本文の下書きを暗号化して保存しました。スマホから送信すると、毎時のActionsでAnkiへの反映を確認します。"
            : "各カードの「本文を編集」から、表・裏などのフィールドを変更できます。";
    return `<section class="panel tag-sync-panel" aria-label="Ankiへ戻す本文変更"><div><h2>Ankiへ戻す本文変更 <span class="chip">${count} ノート</span></h2><p>${note}</p></div><div class="tag-sync-actions"><button class="button primary small" data-send-notes ${!count || bad || conflicts() ? "disabled" : ""}>本文をスマホから送信</button><button class="button subtle small" data-backup-notes ${!count && !state.recoveryError ? "disabled" : ""}>本文のバックアップを保存</button><button class="button subtle small" data-discard-notes ${!count && !state.recoveryError ? "disabled" : ""}>本文の下書きを取り消す</button></div></section>`;
  }
  function open(cardId) {
    if (state.busy || state.recoveryError) {
      notify("保存中、または以前の下書きの確認が必要です。");
      return;
    }
    const data = snapshot(),
      card = data?.cards.find((c) => c.id === cardId);
    if (!card?.editable_fields) {
      notify("本文編集用のデータは次のAnkiWeb同期・公開後に利用できます。");
      return;
    }
    if (tagPending(card.note_id)) {
      notify(
        "このノートはタグ変更が未反映です。タグの反映を確認してから本文を編集してください。",
      );
      return;
    }
    if (
      state.changes.has(card.note_id) &&
      noteEditStatus(data, state.changes.get(card.note_id)) === "conflict"
    ) {
      notify(
        "本文が競合しています。下書きをバックアップして取り消してから編集し直してください。",
      );
      return;
    }
    document.querySelector("#note-edit-dialog")?.remove();
    const pending = state.changes.get(card.note_id),
      values = { ...card.editable_fields, ...pending?.set_fields };
    const names = Object.keys(values),
      dialog = document.createElement("dialog");
    dialog.id = "note-edit-dialog";
    dialog.className = "note-edit-dialog";
    dialog.innerHTML = `<h2>カードの本文を編集</h2><p>同じノートから作られたカードにも反映されます。HTML・画像参照・穴埋めは元の記法で編集してください。画像の追加アップロードには対応していません。</p><form id="note-edit-form">${names.map((name, i) => `<label for="note-field-${i}">${esc(name)}</label><textarea id="note-field-${i}" data-field-index="${i}" rows="5" maxlength="128000" spellcheck="false"></textarea>`).join("")}<details class="note-edit-diff"><summary>保存する変更内容を確認</summary><div data-note-diff></div></details><p class="error" role="alert" data-note-error></p><p class="small muted">下書き保存だけではAnkiは変わりません。「本文をスマホから送信」→ GitHubでCreate issue → 毎時の同期 → スマホのAnkiで同期、の順に反映します。カードの表裏の表示は再取得後に更新されます。</p><div class="tag-sync-actions"><button type="submit" class="button primary">本文の下書きを保存</button><button type="button" class="button subtle" data-note-cancel>閉じる</button>${pending ? '<button type="button" class="text-button" data-note-discard>このノートの下書きを取り消す</button>' : ""}</div></form>`;
    const inputs = [...dialog.querySelectorAll("textarea")];
    inputs.forEach((el, i) => {
      el.value = values[names[i]];
    });
    const dirty = () => inputs.some((el, i) => el.value !== values[names[i]]);
    dialog.dataset.dirty = "false";
    const diff = () => {
      dialog.dataset.dirty = String(dirty());
      dialog.querySelector("[data-note-diff]").innerHTML =
        inputs
          .map((el, i) =>
            el.value === card.editable_fields[names[i]]
              ? ""
              : `<h3>${esc(names[i])}</h3><p class="small muted">変更前</p><pre>${esc(card.editable_fields[names[i]])}</pre><p class="small muted">変更後</p><pre>${esc(el.value)}</pre>`,
          )
          .join("") || "<p>変更はありません。</p>";
    };
    inputs.forEach((el) => el.addEventListener("input", diff));
    diff();
    const close = () => {
      if (state.busy) return;
      if (dirty() && !confirm("入力中の変更を保存せず閉じますか？")) return;
      dialog.remove();
    };
    dialog.addEventListener("cancel", (e) => {
      e.preventDefault();
      close();
    });
    dialog.querySelector("[data-note-cancel]").addEventListener("click", close);
    dialog
      .querySelector("[data-note-discard]")
      ?.addEventListener("click", async () => {
        await discard(card.note_id);
        if (!state.changes.has(card.note_id)) dialog.remove();
      });
    dialog.querySelector("form").addEventListener("submit", async (e) => {
      e.preventDefault();
      if (state.busy) return;
      state.busy = true;
      dialog.querySelector('button[type="submit"]').disabled = true;
      const currentKey = key();
      try {
        const current = snapshot(),
          latest = current?.cards.find((c) => c.id === cardId);
        if (
          !latest ||
          latest.tag_identity !== card.tag_identity ||
          (!demo() && !currentKey)
        )
          throw new Error(
            "データが更新されました。閉じて最新の本文を確認してください。",
          );
        if (!demo()) checkVersion();
        const next = await stageNoteEdit(
          current,
          state.changes,
          card.note_id,
          Object.fromEntries(inputs.map((el, i) => [names[i], el.value])),
        );
        if (!demo() && currentKey !== key())
          throw new Error("ログイン状態が変わりました。");
        state.changes = next;
        try {
          await persist();
          state.storageError = false;
        } catch {
          state.storageError = true;
        }
        dialog.remove();
        onChange();
        notify(
          state.storageError
            ? "端末に保存できません。本文のバックアップを保存してください。"
            : demo()
              ? "デモの本文の下書きを保存しました。実際のAnkiには送信しません。"
              : "本文の下書きを保存しました。スマホから送信するとAnkiへの反映を予約できます。",
        );
      } catch (error) {
        dialog.querySelector("[data-note-error]").textContent = error.message;
      } finally {
        state.busy = false;
        const button = dialog.querySelector('button[type="submit"]');
        if (button) button.disabled = false;
      }
    });
    document.body.append(dialog);
    dialog.showModal();
  }
  function reset() {
    document.querySelector("#note-edit-dialog")?.remove();
    state.changes.clear();
    state.stored = null;
    state.recoveryError = false;
    state.storageError = false;
  }
  document.addEventListener("click", (event) => {
    const button = event.target.closest?.(
      "[data-edit-note],[data-send-notes],[data-backup-notes],[data-discard-notes]",
    );
    if (!button || button.disabled) return;
    if (button.hasAttribute("data-edit-note"))
      open(Number(button.dataset.editNote));
    else if (button.hasAttribute("data-send-notes")) send();
    else if (button.hasAttribute("data-backup-notes")) void backup();
    else void discard();
  });
  return {
    panel,
    button,
    restore,
    reconcile,
    sendable,
    reset,
    get busy() {
      return state.busy;
    },
    get editing() {
      return !!active();
    },
    get unsafe() {
      return (
        state.busy ||
        (state.storageError && state.changes.size > 0) ||
        active()?.dataset.dirty === "true"
      );
    },
    has: (noteId) => state.changes.has(noteId),
    checkSource(data) {
      const old = snapshot();
      if (
        state.changes.size &&
        old &&
        (data.source.kind !== old.source.kind ||
          data.source.profile !== old.source.profile)
      )
        throw new Error(
          "本文の下書きとプロフィールが異なります。バックアップを保存して取り消してから更新してください。",
        );
    },
  };
}
