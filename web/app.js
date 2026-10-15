import {
  summarize,
  filterCards,
  percent,
  minutes,
  dayKey,
  dayRange,
} from "./stats.mjs";

const $ = (s) => document.querySelector(s);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const paths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  cards:
    '<rect x="6" y="6" width="15" height="15" rx="3"/><path d="M16 3H6a3 3 0 0 0-3 3v10M10 11h7m-7 5h4"/>',
  chart: '<path d="M4 3v17h17M8 15v-4m5 4V7m5 8v-6"/>',
  settings:
    '<path d="m9 3 1 3h4l1-3 3 2-1 3 2 3 3 1v4l-3 1-2 3-3-1-3 2-2-3-3-1v-4l3-1 2-3-1-3Z"/><circle cx="12" cy="12" r="3"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  refresh:
    '<path d="M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 4M5 14a8 8 0 0 0 13 4"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  tag: '<path d="M3 3h8l10 10-8 8L3 11V3Z"/><circle cx="7.5" cy="7.5" r="1"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  cloud:
    '<path d="M7 18a5 5 0 1 1 .4-9.98A6 6 0 0 1 19 9a4.5 4.5 0 0 1-.5 9M12 21V11m-4 4 4-4 4 4"/>',
  download: '<path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/>',
  book: '<path d="M12 6c-3-3-7-3-10-2v15c3-1 7-1 10 2 3-3 7-3 10-2V4c-3-1-7-1-10 2Zm0 0v15"/>',
  flame:
    '<path d="M13 3c2 5-1 5 2 9 1-2 2-3 3-3 4 5 2 12-6 12-9 0-10-9-5-14 0 4 2 4 3 5 2-3 0-5 3-9Z"/>',
  out: '<path d="M9 5H4v14h5m6-11 4 4-4 4m-7-4h11"/>',
  calendar:
    '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 11h18m-13 4h2m4 0h2"/>',
};
const icon = (name, size = 20) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.cards}</svg>`;
const views = {
  overview: "学習ダッシュボード",
  cards: "タグ別カード",
  insights: "学習の記録",
  settings: "接続・設定",
};
const state = {
  demo: new URLSearchParams(location.search).get("demo") === "1",
  snapshot: null,
  stats: null,
  view: location.hash.slice(1) || "overview",
  tag: "",
  query: "",
  deck: "",
  sort: "default",
  page: 0,
  timezone: localStorage.getItem("atlas-timezone") || "Asia/Tokyo",
  expanded: new Set(),
  busy: false,
};
try {
  new Intl.DateTimeFormat("ja-JP", { timeZone: state.timezone });
} catch {
  state.timezone = "Asia/Tokyo";
}

function demoSnapshot() {
  const seed = [
    [
      "生理学::循環",
      "心拍出量を決める2つの要素は？",
      "心拍出量（CO）＝ 1回拍出量（SV）× 心拍数（HR）。安静時の目安は約5 L/分。",
      "医学",
    ],
    [
      "生理学::循環",
      "Frank–Starlingの法則とは？",
      "生理的な範囲で、心室の拡張末期容積が増えるほど、心筋の収縮力と1回拍出量が増加する。",
      "医学",
    ],
    [
      "生理学::循環",
      "血圧を規定する主な因子は？",
      "平均動脈圧 ≒ 心拍出量 × 総末梢血管抵抗。",
      "医学",
    ],
    [
      "生理学::呼吸",
      "肺胞でガス交換が起こる原理は？",
      "肺胞と毛細血管の間の分圧差による拡散。酸素は血液へ、二酸化炭素は肺胞へ移動する。",
      "医学",
    ],
    [
      "生理学::呼吸",
      "サーファクタントの役割は？",
      "肺胞表面の表面張力を低下させ、特に小さな肺胞の虚脱を防ぐ。II型肺胞上皮細胞から分泌される。",
      "医学",
    ],
    [
      "解剖学::神経",
      "副交感神経の主な神経伝達物質は？",
      "節前線維・節後線維ともにアセチルコリン。節後の標的器官では主にムスカリン受容体に作用する。",
      "医学",
    ],
    [
      "解剖学::神経",
      "海馬が主に関わる記憶は？",
      "新しいエピソード記憶や空間記憶の形成に関わる。",
      "医学",
    ],
    [
      "英語::語彙",
      "consolidate",
      "まとめる、強化する、定着させる。例：Sleep helps consolidate memories.",
      "英語",
    ],
    [
      "英語::語彙",
      "a little / little の違いは？",
      "a little：少しある（肯定的）。little：ほとんどない（否定的）。どちらも不可算名詞に使う。",
      "英語",
    ],
    [
      "英語::表現",
      "「少しずつ、着実に」を英語で？",
      "Slowly but surely. / One step at a time.",
      "英語",
    ],
    [
      "生化学::代謝",
      "解糖系が行われる場所は？",
      "細胞質基質。グルコース1分子からピルビン酸2分子が生成される。",
      "医学",
    ],
    [
      "生化学::代謝",
      "クエン酸回路が行われる場所は？",
      "ミトコンドリアのマトリックス（基質）。",
      "医学",
    ],
  ];
  seed.unshift(
    [
      "化学::高分子",
      "エチレンが付加重合すると何になる？",
      "ポリエチレン。二重結合が開いて鎖状につながる。",
      "化学",
    ],
    [
      "化学::高分子",
      "ポリエステルの主鎖に含まれる結合は？",
      "エステル結合（−CO−O−）。",
      "化学",
    ],
  );
  const cards = seed.map(([tag, front, back, deck], i) => ({
    id: 1000 + i,
    note_id: 2000 + i,
    deck,
    model: "Basic",
    tags: i % 4 === 0 ? [tag, "重点復習"] : [tag],
    front,
    back,
    fields: { Front: front, Back: back },
    reps: 0,
    lapses: 0,
    interval: 3 + i * 2,
    due: 0,
    suspended: false,
  }));
  cards[0].front_html =
    "<p>エチレン C<sub>2</sub>H<sub>4</sub> が付加重合すると何になる？</p>";
  cards[0].back_html =
    "<p><strong>ポリエチレン</strong></p><p>n CH<sub>2</sub>＝CH<sub>2</sub> → ［−CH<sub>2</sub>−CH<sub>2</sub>−］<sub>n</sub></p>";
  const reviews = [];
  const now = new Date();
  for (let day = 83; day >= 0; day--) {
    if (day > 7 && day % 9 === 0) continue;
    const stamp = new Date(now.valueOf() - day * 86400000);
    const count = day === 0 ? 18 : 8 + ((day * 7) % 24);
    for (let i = 0; i < count; i++) {
      const c = cards[(day + i) % cards.length];
      reviews.push({
        id: stamp.valueOf() - i * 1000,
        card_id: c.id,
        ease: (day + i) % 7 === 0 ? 1 : 2 + (i % 3),
        time_ms: 12000 + ((i * 6700) % 48000),
        type: 1,
      });
      c.reps++;
    }
  }
  return {
    schema_version: 1,
    source: { profile: "デモプロフィール", kind: "ankiconnect" },
    synced_at: now.toISOString(),
    cards,
    reviews,
  };
}

async function api(path, options = {}) {
  const res = await fetch(`./api/${path}`, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!res.ok) {
    const error = new Error(
      res.status === 401
        ? "パスワードを確認してください。"
        : res.status === 429
          ? "操作が続いたため、少し待ってからもう一度お試しください。"
          : "接続できませんでした。時間をおいて再度お試しください。",
    );
    error.status = res.status;
    throw error;
  }
  return res.json();
}
function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.add("visible");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("visible"), 4000);
}
function setSnapshot(snapshot) {
  state.snapshot = snapshot;
  state.stats = summarize(snapshot, { timezone: state.timezone });
}
function dateLabel(value, options = {}) {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: state.timezone,
    month: "short",
    day: "numeric",
    ...options,
  }).format(new Date(value));
}
function syncLabel() {
  return state.snapshot
    ? dateLabel(state.snapshot.synced_at, {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "まだ接続されていません";
}

function login(message = "") {
  $("#app").innerHTML =
    `<div class="login-layout"><section class="login-story"><a class="brand" href="./"><span class="brand-mark">A</span>Anki <strong>Atlas</strong></a><div><span class="eyebrow">YOUR LEARNING, CONNECTED</span><h1>学びを、<br>ひとつの景色に。</h1><p>散らばったカードをタグで整理。<br>積み重ねた学習を、見えるかたちに。</p><div class="story-cards"><div>${icon("tag", 24)}<b>タグでつながる知識</b><span>カードを横断して、まとめて読む。</span></div><div>${icon("chart", 24)}<b>毎日の、小さな前進</b><span>正解率と学習時間を振り返る。</span></div></div></div><small>Made for your Anki collection.</small></section><main class="login-main"><div class="login-box"><span class="eyebrow">WELCOME BACK</span><h2>あなたの学習スペースへ</h2><p class="muted">ダッシュボードのパスワードでログイン</p><form id="login-form"><label for="password">パスワード</label><input id="password" name="password" type="password" autocomplete="current-password" required placeholder="ダッシュボードのパスワード"><p id="login-error" class="error" role="alert">${esc(message)}</p><button class="button primary wide" type="submit">ログイン ${icon("arrow", 17)}</button></form><div class="login-divider"><span>まずは雰囲気を見たい方へ</span></div><a class="button subtle wide" href="?demo=1">デモを見てみる ${icon("arrow", 17)}</a><p class="login-note">Ankiの接続先はあとから設定できます。<br>AnkiWebのパスワードは、この画面では入力しません。</p></div></main></div>`;
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const button = e.target.querySelector("button");
    button.disabled = true;
    try {
      await api("login", {
        method: "POST",
        body: JSON.stringify({ password: $("#password").value }),
      });
      $("#password").value = "";
      await refresh();
    } catch (err) {
      $("#login-error").textContent = err.message;
    } finally {
      button.disabled = false;
    }
  });
}

function shell() {
  if (!views[state.view]) state.view = "overview";
  const nav = (key, name) =>
    `<button class="nav-item ${state.view === key ? "active" : ""}" data-view="${key}" aria-label="${views[key]}" ${state.view === key ? 'aria-current="page"' : ""}>${icon(name)}<span>${views[key]}</span>${key === "cards" && state.snapshot ? `<small>${state.stats.cards}</small>` : ""}</button>`;
  $("#app").innerHTML =
    `<div class="app-layout"><aside class="sidebar"><a class="brand" href="${state.demo ? "?demo=1" : "./"}"><span class="brand-mark">A</span>Anki <strong>Atlas</strong></a><div class="workspace-label">MY WORKSPACE</div><nav aria-label="メインメニュー">${nav("overview", "grid")}${nav("cards", "cards")}${nav("insights", "chart")}<div class="nav-separator"></div>${nav("settings", "settings")}</nav><div class="sidebar-note"><span class="note-icon">✦</span><strong>知識は、つながると強い。</strong><p>カードをタグでまとめて、<br>学びのつながりを見つけよう。</p></div><div class="profile"><span class="avatar">${state.demo ? "D" : "A"}</span><div><strong>${esc(state.snapshot?.source.profile || "My Anki")}</strong><span>${state.demo ? "デモワークスペース" : "プライベートワークスペース"}</span></div><button class="icon-button" id="logout" aria-label="${state.demo ? "デモを終了" : "ログアウト"}">${icon("out", 18)}</button></div></aside><main class="main"><header class="topbar"><div class="breadcrumb">ワークスペース <span>/</span> <strong>${views[state.view]}</strong></div><div class="topbar-right">${state.demo ? '<span class="pill demo-pill">デモデータ</span>' : ""}<span class="private-label"><span class="status-dot"></span>プライベート</span><button class="icon-button header-logout" id="header-logout" aria-label="${state.demo ? "デモを終了" : "ログアウト"}">${icon("out", 18)}</button></div></header><div class="page-body">${state.demo ? '<div class="demo-notice">この画面はサンプルデータです。あなたのAnkiには接続していません。<a href="?">自分のAnkiを接続する →</a></div>' : ""}<div id="view">${view()}</div><footer>学びの積み重ねを、あなたのペースで。<span>Anki Atlas · ${esc(state.timezone)}</span></footer></div></main></div>`;
  document.querySelectorAll("[data-view]").forEach((el) => {
    el.dataset.bound = "1";
    el.addEventListener("click", () => navigate(el.dataset.view));
  });
  document.querySelectorAll("#logout, #header-logout").forEach((el) =>
    el.addEventListener("click", async () => {
      if (!state.demo) {
        try {
          await api("logout", { method: "POST", body: "{}" });
        } catch {
          toast("ログアウトできませんでした。再度お試しください。");
          return;
        }
      }
      location.assign(location.pathname);
    }),
  );
  paintCharts();
  bindView();
}
function navigate(view) {
  state.view = view;
  state.page = 0;
  history.replaceState(
    null,
    "",
    `${location.pathname}${location.search}#${view}`,
  );
  shell();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function heading(eyebrow, title, description, action = "") {
  return `<div class="page-heading"><div><span class="eyebrow">${eyebrow}</span><h1>${title}</h1><p>${description}</p></div>${action}</div>`;
}
function empty() {
  return `<section class="empty-state"><span class="empty-icon">${icon("cloud", 36)}</span><h2>あなたのAnkiと、つながろう。</h2><p>いつものカードを、いつでも振り返れる場所へ。<br>PCのAnkiを接続すると、カードと学習記録がここに届きます。</p><button class="button primary" data-go-settings>接続を設定する ${icon("arrow", 17)}</button><p class="muted small">アカウントの設定はあとから変更できます。</p></section>`;
}
function view() {
  if (state.view === "settings") return settings();
  if (!state.snapshot)
    return (
      heading(
        "YOUR LEARNING SPACE",
        views[state.view],
        "まずはAnkiを接続して、学習の景色を広げましょう。",
      ) + empty()
    );
  if (state.view === "cards") return cardsView();
  if (state.view === "insights") return insights();
  return overview();
}

function metrics() {
  const s = state.stats;
  const items = [
    [
      "cards",
      "カード総数",
      s.cards.toLocaleString(),
      "枚",
      `${s.tags.length} 個のタグで整理`,
      "purple",
    ],
    [
      "check",
      "正解率",
      percent(s.correct, s.reviews),
      "",
      `${s.reviews.toLocaleString()} 回の回答から集計`,
      "teal",
    ],
    [
      "clock",
      "今日の学習時間",
      minutes(s.today.time),
      "分",
      `今日の回答 ${s.today.count} 回`,
      "orange",
    ],
    [
      "flame",
      "連続学習",
      s.streak,
      "日",
      s.streak ? "一歩ずつ、いいペースです" : "今日の1枚からはじめよう",
      "pink",
    ],
  ];
  return `<div class="metrics">${items.map(([i, label, value, unit, detail, color]) => `<article class="metric"><div class="metric-top"><span>${label}</span><span class="metric-icon ${color}">${icon(i, 18)}</span></div><div class="metric-number">${value}<small>${unit}</small></div><p>${detail}</p></article>`).join("")}</div>`;
}
function chart(days = 7) {
  const range = dayRange(days, new Date(), state.timezone);
  const times = range.map((d) => (state.stats.byDay.get(d)?.time || 0) / 60000);
  const max = Math.max(10, Math.ceil(Math.max(...times) / 5) * 5);
  return `<div class="chart"><div class="chart-axis"><span>${max}分</span><span>${max / 2}</span><span>0</span></div><div class="chart-plot"><div class="chart-grid"><i></i><i></i><i></i></div><div class="chart-bars">${range.map((d, i) => `<div class="chart-column"><div class="bar-track"><div class="chart-bar ${i === days - 1 ? "today" : ""}" data-height="${(times[i] / max) * 100}" title="${esc(d)}：${minutes(times[i] * 60000)}分・${state.stats.byDay.get(d)?.count || 0}回" role="img" aria-label="${d} 学習${minutes(times[i] * 60000)}分"></div></div><span>${days <= 7 ? ["日", "月", "火", "水", "木", "金", "土"][new Date(d + "T00:00:00Z").getUTCDay()] : d.slice(5)}</span></div>`).join("")}</div></div></div>`;
}
function heatmap() {
  const range = dayRange(84, new Date(), state.timezone);
  const studied = range.filter((d) => state.stats.byDay.get(d)?.count).length;
  return `<div class="activity-summary"><span><strong>${studied}</strong> 日の積み重ね</span><small>過去12週間</small></div><div class="heatmap" role="img" aria-label="過去84日の学習履歴。${studied}日学習。">${range
    .map((d) => {
      const count = state.stats.byDay.get(d)?.count || 0;
      return `<span class="heat-cell level-${count === 0 ? 0 : count < 10 ? 1 : count < 20 ? 2 : count < 30 ? 3 : 4}" title="${esc(d)}：${count}回"></span>`;
    })
    .join(
      "",
    )}</div><div class="heatmap-legend"><span>毎日の小さな一歩を記録</span><div>少<span class="heat-cell level-0"></span><span class="heat-cell level-1"></span><span class="heat-cell level-2"></span><span class="heat-cell level-3"></span><span class="heat-cell level-4"></span>多</div></div>`;
}
function tagRows(limit = 5) {
  return state.stats.tags
    .slice(0, limit)
    .map(
      (g, i) =>
        `<button class="tag-row" data-tag="${esc(g.tag)}"><span class="tag-symbol tag-color-${i % 4}">${icon("tag", 17)}</span><span class="tag-row-name"><strong>${esc(g.tag.replaceAll("::", " / "))}</strong><small>${g.count} 枚のカード</small></span><span class="tag-progress"><span data-width="${g.reviews ? (g.correct / g.reviews) * 100 : 0}"></span></span><b>${percent(g.correct, g.reviews)}</b>${icon("chevron", 15)}</button>`,
    )
    .join("");
}
function overview() {
  return (
    heading(
      "A LITTLE PROGRESS, EVERY DAY",
      "今日も、学びをひとつ。",
      "あなたの知識のつながりと、日々の積み重ねを見渡しましょう。",
      `<button class="button subtle" id="refresh">${icon("refresh", 17)}表示を更新</button>`,
    ) +
    metrics() +
    `<div class="overview-grid"><section class="panel"><div class="panel-title"><div><h2>学習のリズム</h2><p>1日ごとの学習時間</p></div><span class="chip">過去7日間</span></div>${chart()}<div class="chart-foot"><span><i></i>学習時間</span><strong>今週 ${minutes(dayRange(7, new Date(), state.timezone).reduce((n, d) => n + (state.stats.byDay.get(d)?.time || 0), 0))} 分</strong></div></section><section class="panel"><div class="panel-title"><div><h2>学習アクティビティ</h2><p>続けた日が、見える自信に。</p></div>${icon("calendar", 20)}</div>${heatmap()}</section></div><div class="overview-grid bottom-grid"><section class="panel tag-panel"><div class="panel-title"><div><h2>タグで、知識をつなぐ</h2><p>気になるテーマから、まとめて振り返る。</p></div><button class="text-button" data-view="cards">すべて見る ${icon("arrow", 16)}</button></div>${tagRows()}${!state.stats.tags.length ? '<p class="muted">まだカードがありません。</p>' : ""}</section><section class="learning-note"><span class="eyebrow">YOUR NEXT CHAPTER</span><span class="note-illustration">${icon("book", 66)}</span><h2>覚えるだけじゃなく、<br>つながりを見つけよう。</h2><p>同じタグのカードを並べると、<br>ひとつずつでは見えなかった<br>知識の流れが見えてきます。</p><button class="button primary" data-view="cards">カードをまとめて見る ${icon("arrow", 16)}</button></section></div><div class="sync-strip"><span class="status-dot"></span><span>${state.demo ? "デモデータ" : "最終データ受信"}：${esc(syncLabel())}</span><span>正解率は Again 以外の評価を集計しています。</span></div>`
  );
}

// Apply the same small formatting allowlist defensively in the browser.
function cardHTML(card, side) {
  if (!card[side + "_html"]) return esc(card[side] || "（テキストなし）");
  const template = document.createElement("template");
  template.innerHTML = card[side + "_html"];
  const allowed = new Set(
    "P DIV SPAN BR HR STRONG B EM I U S SUB SUP UL OL LI TABLE THEAD TBODY TR TH TD H1 H2 H3 H4 BLOCKQUOTE PRE CODE IMG".split(
      " ",
    ),
  );
  for (const node of [...template.content.querySelectorAll("*")]) {
    if (!allowed.has(node.tagName)) {
      node.replaceWith(document.createTextNode(node.textContent));
      continue;
    }
    const src = node.getAttribute("src");
    const alt = node.getAttribute("alt");
    for (const attribute of [...node.attributes])
      node.removeAttribute(attribute.name);
    if (node.tagName === "IMG") {
      if (!/^\.\/api\/media\/[a-f0-9]{64}$/.test(src || "")) {
        node.remove();
        continue;
      }
      node.setAttribute("src", src);
      node.setAttribute("alt", alt || "カードの図");
      node.setAttribute("loading", "lazy");
    }
  }
  return template.innerHTML;
}

function cardsView() {
  const s = state.stats;
  return (
    heading(
      "EXPLORE YOUR KNOWLEDGE",
      "カードを、じっくり読み返す。",
      "同じテーマを並べて、知識をひとつのまとまりに。",
      '<button class="button subtle" id="export-cards">' +
        icon("download", 17) +
        "Markdownで保存</button>",
    ) +
    `<div class="card-workspace"><aside class="tag-sidebar"><div class="tag-sidebar-heading">タグ一覧<span>${s.tags.length}</span></div><button class="tag-filter ${!state.tag ? "selected" : ""}" data-tag="">${icon("cards", 17)}<span>すべてのカード</span><small>${s.cards}</small></button>${s.tags.map((g, i) => `<button class="tag-filter ${state.tag === g.tag ? "selected" : ""}" data-tag="${esc(g.tag)}"><span class="tag-bullet tag-color-${i % 4}">#</span><span title="${esc(g.tag)}">${esc(g.tag.replaceAll("::", " / "))}</span><small>${g.count}</small></button>`).join("")}</aside><section class="cards-main"><div class="card-toolbar"><label class="search-input">${icon("search", 18)}<input id="search" type="search" placeholder="質問・答え・タグを検索" aria-label="カードを検索" value="${esc(state.query)}"></label><select id="deck-filter" aria-label="デッキで絞り込み"><option value="">すべてのデッキ</option>${[
      ...new Set(state.snapshot.cards.map((c) => c.deck)),
    ]
      .sort()
      .map(
        (d) =>
          `<option ${state.deck === d ? "selected" : ""} value="${esc(d)}">${esc(d)}</option>`,
      )
      .join(
        "",
      )}</select><select id="sort" aria-label="並び順"><option value="default">カード順</option><option value="accuracy" ${state.sort === "accuracy" ? "selected" : ""}>正解率が低い順</option><option value="recent" ${state.sort === "recent" ? "selected" : ""}>最近学習した順</option></select></div><div id="card-results">${cardResults()}</div></section></div><p class="data-note">${icon("check", 14)} 正解率：Again＝不正解、Hard / Good / Easy＝正解。未回答のカードは「—」。タグはAnkiのノート単位で付きます。</p>`
  );
}
function selectedCards() {
  return filterCards(state.snapshot.cards, state, state.stats.byCard);
}
function cardResults() {
  const cards = selectedCards();
  const pageSize = 20;
  const shown = cards.slice(state.page * pageSize, (state.page + 1) * pageSize);
  const selectedTag = state.tag || "すべてのカード";
  return `<div class="collection-heading"><div><span class="eyebrow">COLLECTION</span><h2>${esc(selectedTag.replaceAll("::", " / "))}<span>${cards.length} 枚</span></h2></div><button class="text-button" id="toggle-all">${shown.length && shown.every((c) => state.expanded.has(c.id)) ? "答えをすべて隠す" : "答えをすべて表示"}</button></div><div class="cards-list">${
    shown.length
      ? shown
          .map((c, i) => {
            const s = state.stats.byCard.get(c.id);
            const accuracy = s?.count
              ? Math.round((s.correct / s.count) * 100)
              : null;
            return `<article class="study-card"><div class="study-card-main"><span class="card-index">${String(state.page * pageSize + i + 1).padStart(2, "0")}</span><div class="card-content"><div class="card-meta"><span>${esc(c.deck)}</span><span>·</span><span>${esc(c.model)}</span>${c.suspended ? '<span class="suspended">休止中</span>' : ""}</div><div class="card-question rich-card">${cardHTML(c, "front")}</div><div class="card-tags">${c.tags.map((t) => `<button data-tag="${esc(t)}"># ${esc(t.replaceAll("::", " / "))}</button>`).join("")}</div></div><div class="card-accuracy"><strong class="${accuracy === null ? "muted" : accuracy < 70 ? "needs-practice" : ""}">${accuracy === null ? "—" : accuracy + "%"}</strong><span>${s?.count || 0} 回回答</span></div></div><button class="answer-toggle" data-answer="${c.id}" aria-expanded="${state.expanded.has(c.id)}" aria-controls="answer-${c.id}">${state.expanded.has(c.id) ? "答えを隠す" : "答えを見る"}${icon("chevron", 13)}</button><div class="answer-content" id="answer-${c.id}" ${state.expanded.has(c.id) ? "" : "hidden"}><span>ANSWER</span><div class="rich-card">${cardHTML(c, "back")}</div>${
              Object.entries(c.fields || {}).length > 2
                ? `<details><summary>すべてのフィールド</summary>${Object.entries(
                    c.fields,
                  )
                    .map(
                      ([name, value]) =>
                        `<dl><dt>${esc(name)}</dt><dd>${esc(value)}</dd></dl>`,
                    )
                    .join("")}</details>`
                : ""
            }</div></article>`;
          })
          .join("")
      : '<div class="no-results">' +
        icon("search", 30) +
        "<h3>カードが見つかりませんでした</h3><p>検索語や絞り込みを変えてみてください。</p></div>"
  }</div><div class="pagination"><span>${cards.length ? state.page * pageSize + 1 : 0}–${Math.min((state.page + 1) * pageSize, cards.length)} / ${cards.length} 枚</span><div><button class="button subtle small" id="prev-page" ${state.page === 0 ? "disabled" : ""}>前へ</button><button class="button subtle small" id="next-page" ${(state.page + 1) * pageSize >= cards.length ? "disabled" : ""}>次へ</button></div></div>`;
}
function insights() {
  const range = dayRange(30, new Date(), state.timezone).reverse();
  return (
    heading(
      "LOOK BACK, MOVE FORWARD",
      "積み重ねが、力になる。",
      "毎日の学習と、カードごとの得意・苦手を振り返りましょう。",
    ) +
    metrics() +
    `<section class="panel"><div class="panel-title"><div><h2>日ごとの学習記録</h2><p>過去30日間 · ${esc(state.timezone)}</p></div><span class="chip">回答履歴から集計</span></div><div class="table-scroll"><table class="daily-table"><thead><tr><th scope="col">日付</th><th scope="col">回答回数</th><th scope="col">正解率</th><th scope="col">学習時間</th><th scope="col">学習のリズム</th></tr></thead><tbody>${range
      .map((d) => {
        const s = state.stats.byDay.get(d) || { count: 0, correct: 0, time: 0 };
        return `<tr><th scope="row">${esc(d)}${d === dayKey(new Date(), state.timezone) ? '<span class="today-label">今日</span>' : ""}</th><td>${s.count} 回</td><td>${percent(s.correct, s.count)}</td><td>${minutes(s.time)} 分</td><td><span class="time-bar"><span data-width="${Math.min(100, (minutes(s.time) / 30) * 100)}"></span></span></td></tr>`;
      })
      .join(
        "",
      )}</tbody></table></div></section><p class="data-note">学習時間はAnkiの回答時間の合計です。アプリを開いていた時間・休憩時間は含みません。Anki側の計測上限が反映されます。</p>`
  );
}
function settings() {
  const profile = localStorage.getItem("atlas-profile") || "";
  return (
    heading(
      "MAKE IT YOURS",
      "いつものAnkiと、つなぐ。",
      "アカウントは、PCのAnkiで開いているプロフィールから接続します。",
    ) +
    `<div class="settings-grid"><section class="panel"><div class="panel-title"><div><h2>接続の状態</h2><p>あなたのカードは、あなたのためだけに。</p></div><span class="pill ${state.snapshot ? "connected" : ""}">${state.demo ? "デモ" : state.snapshot ? "受信済み" : "未接続"}</span></div><dl class="connection-info"><div><dt>プロフィール</dt><dd>${esc(state.snapshot?.source.profile || "未設定")}</dd></div><div><dt>最終データ受信</dt><dd>${esc(syncLabel())}</dd></div><div><dt>接続方式</dt><dd>${state.snapshot?.source.kind === "ankiweb" ? "AnkiWeb → GitHub Actions" : "AnkiConnect → クラウド"}</dd></div></dl><div class="info-box">PC停止中の自動更新はGitHub Actionsで設定できます。学習した端末でAnkiWebへの同期を済ませてください。PC取り込みを使う場合はAnkiと接続プログラムの起動が必要です。</div><label class="setting-label" for="timezone">集計タイムゾーン</label><select id="timezone"><option value="Asia/Tokyo" ${state.timezone === "Asia/Tokyo" ? "selected" : ""}>日本（Asia/Tokyo）</option><option value="UTC" ${state.timezone === "UTC" ? "selected" : ""}>UTC</option><option value="America/New_York" ${state.timezone === "America/New_York" ? "selected" : ""}>ニューヨーク</option><option value="Europe/London" ${state.timezone === "Europe/London" ? "selected" : ""}>ロンドン</option></select><p class="muted small">このブラウザーの表示設定として保存されます。</p></section><section class="panel setup-panel"><span class="eyebrow">CONNECT IN 3 STEPS</span><h2>接続は、あとからでも大丈夫。</h2><ol class="setup-steps"><li><span>1</span><div><h3>PCのAnkiを準備</h3><p>自分のAnkiプロフィールを開き、公式のAnkiConnectアドオン（2055492159）を追加します。AnkiWebのアカウントはAnki側で設定します。</p></div></li><li><span>2</span><div><h3>接続用の設定を用意</h3><p>公開先とPCに、同じ送信用トークンを設定します。秘密の設定ファイルはGitHubに公開しません。</p></div></li><li><span>3</span><div><h3>PCからデータを送信</h3><p>接続プログラムを起動すると、カードと学習履歴が届きます。Ankiのカードを書き換える操作は行いません。</p></div></li></ol><label class="setting-label" for="profile-name">接続するプロフィール名（任意）</label><input id="profile-name" type="text" maxlength="200" placeholder="例：User 1" value="${esc(profile)}"><p class="muted small">指定すると、接続先が違う場合に送信を止めます。</p><pre class="command" id="connector-command"></pre><button class="button subtle" id="copy-command">接続コマンドをコピー</button><p class="muted small">PC取り込みは DASHBOARD.md、PC停止中の自動更新は ACTIONS_SETUP.md を参照してください。</p></section></div>`
  );
}
function command() {
  const quote = (v) => "'" + v.replaceAll("'", "'\\''") + "'";
  const profile = $("#profile-name")?.value.trim() || "";
  return `uv run --frozen --env-file .dashboard.env python connector.py --server ${quote(state.demo ? "https://YOUR-DASHBOARD.example" : location.origin)}${profile ? " --profile " + quote(profile) : ""} --timezone ${quote(state.timezone)} --watch 60`;
}
function paintCharts() {
  document.querySelectorAll("[data-height]").forEach((el) => {
    el.style.height = `${Math.min(100, Math.max(0, Number(el.dataset.height) || 0))}%`;
  });
  document.querySelectorAll("[data-width]").forEach((el) => {
    el.style.width = `${Math.min(100, Math.max(0, Number(el.dataset.width) || 0))}%`;
  });
}
function bindView() {
  document
    .querySelectorAll("[data-go-settings]")
    .forEach((el) => el.addEventListener("click", () => navigate("settings")));
  document.querySelectorAll("#view [data-view]").forEach((el) => {
    if (!el.dataset.bound) {
      el.dataset.bound = "1";
      el.addEventListener("click", () => navigate(el.dataset.view));
    }
  });
  bindTags();
  $("#refresh")?.addEventListener("click", () => refresh(true));
  $("#search")?.addEventListener("input", (e) => {
    state.query = e.target.value;
    state.page = 0;
    updateCards();
  });
  $("#deck-filter")?.addEventListener("change", (e) => {
    state.deck = e.target.value;
    state.page = 0;
    updateCards();
  });
  $("#sort")?.addEventListener("change", (e) => {
    state.sort = e.target.value;
    state.page = 0;
    updateCards();
  });
  $("#export-cards")?.addEventListener("click", exportCards);
  bindCards();
  $("#timezone")?.addEventListener("change", (e) => {
    state.timezone = e.target.value;
    localStorage.setItem("atlas-timezone", state.timezone);
    setSnapshot(state.snapshot);
    shell();
    toast("集計タイムゾーンを変更しました。");
  });
  if ($("#connector-command")) {
    const updateCommand = () => {
      $("#connector-command").textContent = command();
      localStorage.setItem("atlas-profile", $("#profile-name").value);
    };
    updateCommand();
    $("#profile-name").addEventListener("input", updateCommand);
    $("#copy-command").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(command());
        toast("接続コマンドをコピーしました。");
      } catch {
        toast("コマンドを選択してコピーしてください。");
      }
    });
  }
}
function bindTags() {
  document.querySelectorAll("[data-tag]").forEach((el) => {
    if (el.dataset.bound) return;
    el.dataset.bound = "1";
    el.addEventListener("click", () => {
      state.tag = el.dataset.tag;
      state.page = 0;
      navigate("cards");
    });
  });
}
function updateCards() {
  $("#card-results").innerHTML = cardResults();
  bindCards();
  bindTags();
}
function bindCards() {
  document.querySelectorAll("[data-answer]").forEach((el) =>
    el.addEventListener("click", () => {
      const id = Number(el.dataset.answer);
      state.expanded.has(id)
        ? state.expanded.delete(id)
        : state.expanded.add(id);
      updateCards();
      document.querySelector(`[data-answer="${id}"]`)?.focus();
    }),
  );
  $("#toggle-all")?.addEventListener("click", () => {
    const cards = selectedCards().slice(state.page * 20, (state.page + 1) * 20);
    const open = !cards.every((c) => state.expanded.has(c.id));
    cards.forEach((c) =>
      open ? state.expanded.add(c.id) : state.expanded.delete(c.id),
    );
    updateCards();
    $("#toggle-all")?.focus();
  });
  $("#prev-page")?.addEventListener("click", () => {
    state.page--;
    updateCards();
  });
  $("#next-page")?.addEventListener("click", () => {
    state.page++;
    updateCards();
  });
}
function exportCards() {
  const markdown = `# ${state.tag || "Anki カード一覧"}\n\n${selectedCards()
    .map((c) => {
      const s = state.stats.byCard.get(c.id);
      return `## ${c.front}\n\n${c.back}\n\nタグ: ${c.tags.join(", ") || "なし"} · 正解率: ${percent(s?.correct || 0, s?.count || 0)}\n`;
    })
    .join("\n---\n\n")}`;
  const url = URL.createObjectURL(
    new Blob([markdown], { type: "text/markdown;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "anki-cards.md";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function refresh(notify = false) {
  if (state.busy) return;
  state.busy = true;
  try {
    const result = state.demo
      ? { snapshot: demoSnapshot() }
      : await api("snapshot");
    setSnapshot(result.snapshot);
    shell();
    if (notify)
      toast(
        state.demo
          ? "デモデータを更新しました。"
          : "最後に届いたデータを読み込みました。",
      );
  } catch (err) {
    if (err.status === 401) login();
    else if (state.snapshot) toast(err.message);
    else login("サーバーに接続できません。デモは接続なしでご覧いただけます。");
  } finally {
    state.busy = false;
  }
}
window.addEventListener("hashchange", () => {
  state.view = location.hash.slice(1);
  if (state.stats) shell();
});
if (state.demo) await refresh();
else {
  try {
    const session = await api("session");
    if (session.authenticated) await refresh();
    else login();
  } catch {
    login("サーバーが未設定の場合は、デモをご覧ください。");
  }
}
