// Source HTML is parsed only in inert templates. Never mount note HTML directly.
const TAGS = new Set(
  "P DIV SPAN BR HR STRONG B EM I U S STRIKE SUB SUP UL OL LI TABLE THEAD TBODY TFOOT TR TH TD H1 H2 H3 H4 H5 H6 BLOCKQUOTE PRE CODE FONT A".split(
    " ",
  ),
);
const VOID = new Set(["BR", "HR"]);
const STYLES = new Set([
  "color",
  "background-color",
  "font-weight",
  "font-style",
  "font-size",
  "font-family",
  "text-decoration",
  "text-decoration-line",
  "text-align",
  "vertical-align",
  "white-space",
  "list-style-type",
]);
const esc = (v) =>
  String(v).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
function safeStyle(name, value) {
  if (
    !STYLES.has(name) ||
    !value ||
    value.length > 180 ||
    /url\s*\(|expression|var\s*\(|[{}<>\\]/i.test(value)
  )
    return false;
  if (
    name === "font-size" &&
    !/^(?:(?:\d{1,2}(?:\.\d+)?|100)(?:px|pt|%|em|rem)|xx-small|x-small|small|medium|large|x-large|xx-large|smaller|larger)$/.test(
      value,
    )
  )
    return false;
  return CSS.supports(name, value);
}
function imageName(src) {
  try {
    const name = decodeURIComponent(src || "");
    return name &&
      name.length <= 255 &&
      !/[\\/:\x00]/.test(name) &&
      ![".", ".."].includes(name)
      ? name
      : null;
  } catch {
    return null;
  }
}
function safeAttributes(node) {
  const attrs = [];
  for (const name of ["colspan", "rowspan"])
    if (/^[1-9]\d?$/.test(node.getAttribute(name) || ""))
      attrs.push([name, node.getAttribute(name)]);
  return attrs;
}
function documentView(
  html,
  { resolveImage = async () => null, pasted = false } = {},
) {
  const template = document.createElement("template");
  template.innerHTML = html;
  const records = new Map();
  let sequence = 0;
  const root = document.createElement("div");
  root.className = "rich-note-content";
  function token(node) {
    const id = String(++sequence),
      wrapper = document.createElement("span");
    records.set(id, { html: node.outerHTML });
    wrapper.dataset.richToken = id;
    wrapper.contentEditable = "false";
    wrapper.className = "rich-note-token";
    if (node.tagName === "IMG") {
      const name = imageName(node.getAttribute("src")),
        img = document.createElement("img"),
        label = document.createElement("span");
      label.textContent = node.getAttribute("alt") || "画像";
      img.alt = label.textContent;
      img.dataset.richToken = id;
      img.contentEditable = "false";
      wrapper.classList.add("rich-note-image");
      wrapper.append(label, img);
      queueMicrotask(async () => {
        if (!name || !wrapper.isConnected) return;
        try {
          const url = await resolveImage(name);
          if (
            wrapper.isConnected &&
            typeof url === "string" &&
            url.startsWith("blob:")
          ) {
            img.src = url;
            label.hidden = true;
          }
        } catch {
          label.textContent = "画像（未取得・元データを保持）";
        }
      });
    } else
      wrapper.textContent = ["MATH", "SVG"].includes(node.tagName)
        ? "数式・図（元データを保持）"
        : "埋め込み（元データを保持）";
    return wrapper;
  }
  function convert(node) {
    if (node.nodeType === Node.TEXT_NODE)
      return document.createTextNode(node.data);
    if (node.nodeType === Node.COMMENT_NODE) {
      if (pasted) return document.createTextNode("");
      const span = document.createElement("span");
      const id = String(++sequence);
      records.set(id, { html: `<!--${node.data}-->` });
      span.dataset.richToken = id;
      span.hidden = true;
      span.contentEditable = "false";
      return span;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return document.createTextNode("");
    if (node.tagName === "IMG") {
      if (pasted && !imageName(node.getAttribute("src")))
        return document.createTextNode("［画像は挿入できません］");
      return token(node);
    }
    if (!TAGS.has(node.tagName)) {
      if (!pasted) return token(node);
      if (
        [
          "SCRIPT",
          "STYLE",
          "IFRAME",
          "OBJECT",
          "SVG",
          "MATH",
          "TEMPLATE",
          "META",
          "LINK",
          "FORM",
          "INPUT",
          "VIDEO",
          "AUDIO",
        ].includes(node.tagName)
      )
        return document.createTextNode("");
      const fragment = document.createDocumentFragment();
      for (const child of node.childNodes) fragment.append(convert(child));
      return fragment;
    }
    const element = document.createElement(node.tagName),
      id = String(++sequence);
    const attributes = pasted
      ? safeAttributes(node)
      : [...node.attributes].map((a) => [a.name, a.value]);
    if (
      pasted &&
      node.tagName === "A" &&
      /^https?:\/\//i.test(node.getAttribute("href") || "")
    )
      attributes.push(["href", node.getAttribute("href")]);
    const originalStyles = new Map(
      Array.from(node.style).map((k) => [k, node.style.getPropertyValue(k)]),
    );
    for (const [k, v] of originalStyles)
      if (safeStyle(k, v)) element.style.setProperty(k, v);
    if (node.tagName === "FONT") {
      const color = node.getAttribute("color");
      if (color && safeStyle("color", color)) element.style.color = color;
      const sizes = ["10px", "13px", "16px", "18px", "24px", "32px", "48px"];
      const size = node.getAttribute("size");
      if (/^[1-7]$/.test(size || ""))
        element.style.fontSize = sizes[Number(size) - 1];
    }
    const align = node.getAttribute("align");
    if (["left", "center", "right", "justify"].includes(align))
      element.style.textAlign = align;
    for (const [k, v] of safeAttributes(node)) element.setAttribute(k, v);
    element.dataset.richOrigin = id;
    const savedStyles = pasted
      ? new Map([...originalStyles].filter(([k, v]) => safeStyle(k, v)))
      : originalStyles;
    if (pasted && element.getAttribute("style"))
      attributes.push(["style", element.getAttribute("style")]);
    records.set(id, {
      attributes,
      styles: savedStyles,
      safeStyle: element.getAttribute("style") || "",
    });
    for (const child of node.childNodes) element.append(convert(child));
    return element;
  }
  for (const child of template.content.childNodes) root.append(convert(child));
  function serialize(node) {
    if (node.nodeType === Node.TEXT_NODE) return esc(node.data);
    if (node.nodeType !== Node.ELEMENT_NODE) return "";
    const protectedNode = records.get(node.dataset.richToken);
    if (protectedNode?.html !== undefined) return protectedNode.html;
    if (!TAGS.has(node.tagName))
      return [...node.childNodes].map(serialize).join("");
    const record = records.get(node.dataset.richOrigin),
      attributes = new Map(record?.attributes || safeAttributes(node));
    const styles = new Map(record?.styles || []),
      liveStyle = node.getAttribute("style") || "";
    if (!record || liveStyle !== record.safeStyle) {
      for (const key of STYLES) styles.delete(key);
      for (const key of Array.from(node.style)) {
        const value = node.style.getPropertyValue(key);
        if (safeStyle(key, value)) styles.set(key, value);
      }
      if (styles.size)
        attributes.set(
          "style",
          [...styles].map(([k, v]) => `${k}: ${v}`).join("; "),
        );
      else attributes.delete("style");
    }
    // Browser-created nodes may never export editor metadata, blob URLs or events.
    const attrs = [...attributes]
      .filter(([k]) => !/^data-rich-/i.test(k))
      .map(([k, v]) => ` ${k}="${esc(v)}"`)
      .join("");
    const tag = node.tagName.toLowerCase();
    return `<${tag}${attrs}>${VOID.has(node.tagName) ? "" : [...node.childNodes].map(serialize).join("") + `</${tag}>`}`;
  }
  return {
    root,
    records,
    serialize: (container = root) =>
      [...container.childNodes].map(serialize).join(""),
  };
}

export function richNotePreview(html, options = {}) {
  const { root } = documentView(html, options);
  root.classList.add("rich-note-preview");
  return root;
}

export function createRichNoteField({
  value,
  label,
  id,
  resolveImage,
  onChange = () => {},
}) {
  const wrapper = document.createElement("div");
  wrapper.className = "rich-note-field";
  const toolbar = document.createElement("div");
  toolbar.className = "rich-note-toolbar";
  toolbar.setAttribute("role", "toolbar");
  toolbar.setAttribute("aria-label", `${label}の書式`);
  let view,
    baseline,
    raw = value,
    range = null,
    sourceMode = false;
  const source = document.createElement("textarea");
  source.id = `${id}-source`;
  source.hidden = true;
  source.spellcheck = false;
  source.maxLength = 128000;
  source.setAttribute("aria-label", `${label}のHTML`);
  source.autocapitalize = "off";
  const host = document.createElement("div");
  wrapper.append(toolbar, host, source);
  const error = document.createElement("p");
  error.className = "small muted";
  error.setAttribute("role", "status");
  wrapper.append(error);
  function remember() {
    const selection = getSelection();
    if (
      selection?.rangeCount &&
      view?.root.contains(selection.getRangeAt(0).commonAncestorContainer)
    )
      range = selection.getRangeAt(0).cloneRange();
  }
  function read() {
    if (sourceMode) return source.value;
    const serialized = view.serialize();
    return serialized === baseline ? raw : serialized;
  }
  function mount(html) {
    raw = html;
    source.value = html;
    view = documentView(html, { resolveImage });
    baseline = view.serialize();
    range = null;
    const editor = view.root;
    editor.id = id;
    editor.contentEditable = "true";
    editor.setAttribute("role", "textbox");
    editor.setAttribute("aria-multiline", "true");
    editor.setAttribute("aria-label", label);
    editor.setAttribute("spellcheck", "false");
    editor.addEventListener("input", () => {
      remember();
      onChange();
    });
    editor.addEventListener("keyup", remember);
    editor.addEventListener("mouseup", remember);
    editor.addEventListener("touchend", remember);
    editor.addEventListener("blur", remember);
    editor.addEventListener("paste", (event) => {
      event.preventDefault();
      if (!event.clipboardData) return;
      const html = event.clipboardData.getData("text/html");
      if (html) {
        const fragment = documentView(html, { resolveImage, pasted: true });
        // Re-key tokens/attributes into this field so pasted image references survive.
        for (const [key, record] of fragment.records) {
          const newKey = `paste-${crypto.randomUUID()}`;
          fragment.root
            .querySelectorAll(
              `[data-rich-token="${key}"],[data-rich-origin="${key}"]`,
            )
            .forEach((node) => {
              if (node.dataset.richToken === key)
                node.dataset.richToken = newKey;
              if (node.dataset.richOrigin === key)
                node.dataset.richOrigin = newKey;
            });
          view.records.set(newKey, record);
        }
        document.execCommand("insertHTML", false, fragment.root.innerHTML);
        loadPastedImages(editor);
      } else
        document.execCommand(
          "insertText",
          false,
          event.clipboardData.getData("text/plain"),
        );
      remember();
      onChange();
    });
    function copy(event, cut = false) {
      const selection = getSelection();
      if (
        !event.clipboardData ||
        !selection?.rangeCount ||
        !editor.contains(selection.getRangeAt(0).commonAncestorContainer)
      )
        return;
      event.preventDefault();
      const clone = selection.getRangeAt(0).cloneContents(),
        tmp = document.createElement("div");
      tmp.append(clone);
      // Serialize selection using this view's token records, not temporary blob URLs.
      const html = view.serialize(tmp);
      event.clipboardData.setData("text/html", html);
      event.clipboardData.setData("text/plain", selection.toString());
      if (cut) {
        document.execCommand("delete");
        onChange();
      }
    }
    // Native copy contains blob image URLs/editor metadata; copy original source instead.
    editor.addEventListener("copy", (event) => copy(event));
    editor.addEventListener("cut", (event) => copy(event, true));
    editor.addEventListener("drop", (event) => {
      event.preventDefault();
      error.textContent =
        "画像のアップロードには対応していません。文章はコピーして貼り付けてください。";
    });
    host.replaceChildren(editor);
  }
  async function loadPastedImages(editor) {
    for (const token of editor.querySelectorAll("[data-rich-token]")) {
      const record = view.records.get(token.dataset.richToken);
      if (!record?.html?.startsWith("<img")) continue;
      const t = document.createElement("template");
      t.innerHTML = record.html;
      const name = imageName(t.content.firstElementChild?.getAttribute("src"));
      if (!name) continue;
      try {
        const url = await resolveImage(name);
        if (token.isConnected && url?.startsWith("blob:")) {
          const image = token.querySelector("img");
          if (image) {
            image.src = url;
            const label = token.querySelector("span");
            if (label) label.hidden = true;
          }
        }
      } catch {}
    }
  }
  function restoreSelection() {
    view.root.focus({ preventScroll: true });
    const selection = getSelection();
    if (range && view.root.contains(range.commonAncestorContainer)) {
      selection.removeAllRanges();
      selection.addRange(range);
    } else {
      const end = document.createRange();
      end.selectNodeContents(view.root);
      end.collapse(false);
      selection.removeAllRanges();
      selection.addRange(end);
    }
  }
  const commands = [
    ["bold", "太字", "B"],
    ["italic", "斜体", "I"],
    ["underline", "下線", "U"],
    ["strikeThrough", "取り消し線", "S"],
    ["subscript", "下付き文字", "x₂"],
    ["superscript", "上付き文字", "x²"],
    ["insertUnorderedList", "箇条書き", "• リスト"],
    ["insertOrderedList", "番号付きリスト", "1. リスト"],
    ["justifyLeft", "左揃え", "左"],
    ["justifyCenter", "中央揃え", "中央"],
    ["justifyRight", "右揃え", "右"],
    ["undo", "元に戻す", "↶"],
    ["redo", "やり直す", "↷"],
    ["removeFormat", "書式を解除", "書式解除"],
  ];
  function command(name, arg = null) {
    if (sourceMode) return;
    remember();
    restoreSelection();
    document.execCommand("styleWithCSS", false, true);
    document.execCommand(name, false, arg);
    remember();
    onChange();
  }
  for (const [name, title, text] of commands) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.title = title;
    button.setAttribute("aria-label", `${label}：${title}`);
    button.addEventListener("pointerdown", (e) => e.preventDefault());
    button.addEventListener("click", () => command(name));
    toolbar.append(button);
  }
  const colorLabel = document.createElement("label");
  colorLabel.className = "rich-note-color";
  colorLabel.textContent = "文字色";
  const color = document.createElement("input");
  color.type = "color";
  color.value = "#172846";
  color.setAttribute("aria-label", `${label}：文字色`);
  color.addEventListener("pointerdown", remember);
  color.addEventListener("input", () => command("foreColor", color.value));
  colorLabel.append(color);
  toolbar.append(colorLabel);
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "rich-note-source-toggle";
  toggle.textContent = "HTMLを直接編集";
  toggle.setAttribute("aria-expanded", "false");
  toggle.addEventListener("click", () => {
    const current = read();
    sourceMode = !sourceMode;
    source.hidden = !sourceMode;
    host.hidden = sourceMode;
    toggle.textContent = sourceMode ? "文書形式に戻る" : "HTMLを直接編集";
    toggle.setAttribute("aria-expanded", String(sourceMode));
    for (const el of toolbar.querySelectorAll("button,input"))
      if (el !== toggle) el.disabled = sourceMode;
    if (sourceMode) source.value = current;
    else mount(current);
  });
  toolbar.append(toggle);
  source.addEventListener("input", onChange);
  mount(value);
  return {
    element: wrapper,
    getValue: read,
    dirty: () => read() !== value,
    focus: () => (sourceMode ? source.focus() : view.root.focus()),
    destroy: () => wrapper.remove(),
  };
}
