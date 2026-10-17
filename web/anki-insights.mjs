// Presentation only: all calculations and deck filtering live in stats.mjs.
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const num = (v, digits = 0) =>
  Number.isFinite(Number(v))
    ? Number(v).toLocaleString("ja-JP", { maximumFractionDigits: digits })
    : "—";
const value = (v) => (Number.isFinite(Number(v)) ? Math.max(0, Number(v)) : 0);
const rate = (n, d) => (d > 0 ? `${num((n / d) * 100, 1)}%` : "—");
const duration = (ms) =>
  value(ms) < 60000
    ? `${num(value(ms) / 1000, 1)}秒`
    : `${num(value(ms) / 60000, 1)}分`;
const empty = (text = "この範囲にはデータがありません。") =>
  `<p class="anki-empty">${esc(text)}</p>`;
const metric = (label, content) =>
  `<div><dt>${esc(label)}</dt><dd>${esc(content)}</dd></div>`;
const metrics = (items) =>
  `<dl class="anki-metrics">${items.map(([l, v]) => metric(l, v)).join("")}</dl>`;
const table = (headers, rows, caption = "グラフの数値を見る") =>
  `<details class="anki-data"><summary>${esc(caption)}</summary><div class="anki-table-scroll"><table><thead><tr>${headers.map((h) => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((v, i) => (i ? `<td>${esc(v)}</td>` : `<th scope="row">${esc(v)}</th>`)).join("")}</tr>`).join("")}</tbody></table></div></details>`;
const panel = (title, subtitle, body, extra = "") =>
  `<section class="panel anki-panel ${extra}"><div class="anki-heading"><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div>${body}</section>`;

// Equal numeric widths keep sparse scheduling values from looking equally spaced.
function numericBins(bins, unit = "", bounds = null) {
  const sorted = bins
    .filter((b) => Number.isFinite(Number(b.value)))
    .map((b) => ({ ...b, value: Number(b.value) }))
    .sort((a, b) => a.value - b.value);
  if (sorted.length < 2)
    return sorted.map((b) => ({ ...b, label: `${num(b.value, 1)}${unit}` }));
  const min = sorted[0].value,
    max = sorted.at(-1).value,
    raw = (max - min) / 35;
  const power = 10 ** Math.floor(Math.log10(Math.max(raw, 0.1)));
  const step =
    [1, 2, 5, 10].map((n) => n * power).find((n) => n >= raw) || power * 10;
  const integer = sorted.every((b) => Number.isInteger(b.value));
  const width = integer ? Math.max(1, step) : step,
    start = bounds?.start ?? Math.floor(min / width) * width;
  const groups = Array.from(
    { length: Math.floor((max - start) / width) + 1 },
    (_, i) => {
      const lower = start + i * width,
        upper = Math.min(max, lower + width - (integer ? 1 : 0));
      return {
        value: lower,
        count: 0,
        label: `${num(lower, 1)}${upper > lower && (width > 1 || !integer) ? `–${num(upper, 1)}` : ""}${unit}`,
      };
    },
  );
  for (const b of sorted)
    groups[
      Math.min(groups.length - 1, Math.floor((b.value - start) / width))
    ].count += value(b.count);
  return groups;
}

// Every bar occupies an equal number of calendar days, including inactive days.
// Long histories use at most 120 buckets instead of creating one SVG node per day.
function timelineBins(rows, field = "count", scope = {}) {
  const valid = rows.filter(
    (row) =>
      /^\d{4}-\d{2}-\d{2}$/.test(row.day) &&
      Number.isFinite(Date.parse(row.day)),
  );
  if (!valid.length) return [];
  const dayMs = 86400000;
  const first = valid.reduce(
    (min, row) => Math.min(min, Date.parse(row.day)),
    Infinity,
  );
  const anchor = scope.bins?.[0]?.day;
  const start =
    anchor && Number.isFinite(Date.parse(anchor))
      ? Math.min(first, Date.parse(anchor))
      : first;
  const last = valid.reduce(
    (max, row) => Math.max(max, Date.parse(row.day)),
    -Infinity,
  );
  const scopeStart =
    anchor && Number.isFinite(Date.parse(anchor)) ? Date.parse(anchor) : start;
  const end =
    scope.days > 0
      ? Math.max(last, scopeStart + (scope.days - 1) * dayMs)
      : last;
  const span = Math.round((end - start) / dayMs) + 1;
  const bucketDays = Math.max(1, Math.ceil(span / 120));
  const dateLabel = (ms) => new Date(ms).toISOString().slice(0, 10);
  const bins = Array.from({ length: Math.ceil(span / bucketDays) }, (_, i) => {
    const day = start + i * bucketDays * dayMs;
    const until = Math.min(end, day + (bucketDays - 1) * dayMs);
    return {
      count: 0,
      label: dateLabel(day) + (until > day ? `〜${dateLabel(until)}` : ""),
    };
  });
  for (const row of valid)
    bins[
      Math.floor((Date.parse(row.day) - start) / dayMs / bucketDays)
    ].count += field === "time" ? value(row.time) / 60000 : value(row.count);
  return bins;
}

// SVG numeric attributes avoid inline styles and keep charts compatible with CSP.
function histogram(
  bins,
  {
    label = "枚数",
    format = (n) => num(n),
    cumulative = false,
    cumulativeTotal = null,
    accuracy = false,
    percent = false,
    color = "purple",
  } = {},
) {
  if (!bins.length || !bins.some((b) => value(b.count))) return empty();
  const w = 640,
    h = 170,
    left = 42,
    bottom = 143,
    width = 580,
    top = 12;
  const max = Math.max(...bins.map((b) => value(b.count)), 1),
    sum =
      cumulativeTotal > 0
        ? cumulativeTotal
        : bins.reduce((a, b) => a + value(b.count), 0);
  const step = width / bins.length;
  let running = 0;
  const bars = bins
    .map((b, i) => {
      const height = (value(b.count) / max) * (bottom - top);
      running += value(b.count);
      return `<rect class="anki-bar anki-${color}" x="${(left + i * step + step * 0.12).toFixed(2)}" y="${(bottom - height).toFixed(2)}" width="${Math.max(0.4, step * 0.76).toFixed(2)}" height="${height.toFixed(2)}"><title>${esc(b.label ?? b.value ?? b.day)}: ${esc(format(b.count))} ${esc(label)}</title></rect>`;
    })
    .join("");
  running = 0;
  const points = bins
    .map((b, i) => {
      running += value(b.count);
      return `${(left + (i + 0.5) * step).toFixed(2)},${(bottom - (running / sum) * (bottom - top)).toFixed(2)}`;
    })
    .join(" ");
  const accuracyPoints = bins
    .filter((b) => b.count > 0 && b.rate != null)
    .map(
      (b) =>
        `${(left + (bins.indexOf(b) + 0.5) * step).toFixed(2)},${(bottom - Math.max(0, Math.min(1, Number(b.rate))) * (bottom - top)).toFixed(2)}`,
    )
    .join(" ");
  const ticks = [0, Math.floor((bins.length - 1) / 2), bins.length - 1].filter(
    (x, i, a) => a.indexOf(x) === i,
  );
  return `<div class="anki-chart"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(label)}の分布${cumulative ? "。青緑の線は累積割合" : accuracy ? "。青緑の線は正答率" : ""}"><line class="anki-gridline" x1="${left}" x2="622" y1="12" y2="12"/><line class="anki-gridline" x1="${left}" x2="622" y1="77" y2="77"/><line class="anki-gridline" x1="${left}" x2="622" y1="143" y2="143"/><text x="36" y="16" text-anchor="end">${esc(format(max))}${percent ? "%" : ""}</text><text x="36" y="146" text-anchor="end">0</text>${bars}${cumulative ? `<polyline class="anki-cumulative" points="${points}"/>` : ""}${accuracy ? `<polyline class="anki-cumulative" points="${accuracyPoints}"/><text x="622" y="10" text-anchor="end">正答率 100%</text>` : ""}${ticks.map((i) => `<text x="${left + (i + 0.5) * step}" y="163" text-anchor="${i === 0 ? "start" : i === bins.length - 1 ? "end" : "middle"}">${esc(bins[i].label ?? bins[i].value ?? bins[i].day)}</text>`).join("")}</svg></div>${cumulative ? '<p class="anki-chart-key"><i></i>累積割合（上端 = 100%）</p>' : accuracy ? '<p class="anki-chart-key"><i></i>正答率（上端 = 100%、下端 = 0%）</p>' : ""}`;
}
function distribution(title, subtitle, data, unit = "日") {
  const bins = (data?.bins || []).map((b) => ({
    ...b,
    label: `${num(b.value, 1)}${unit}`,
  }));
  const total = bins.reduce((sum, b) => sum + value(b.count), 0);
  const slicePercent = (fraction) => {
    let cumulative = 0;
    return bins.filter((b) => {
      const include = cumulative < total * fraction;
      cumulative += value(b.count);
      return include;
    });
  };
  const ranges = [
    ["month", "1か月", bins.filter((b) => value(b.value) <= 30)],
    ["half", "50%", slicePercent(0.5)],
    ["most", "95%", slicePercent(0.95)],
    ["all", "全期間", bins],
  ];
  const chart =
    unit === "日"
      ? `<label class="anki-range-label">表示範囲 <select data-anki-range>${ranges.map(([key, label]) => `<option value="${key}"${key === "all" ? " selected" : ""}>${label}</option>`).join("")}</select></label>${ranges.map(([key, , subset]) => `<div data-anki-range-chart="${key}"${key === "all" ? "" : " hidden"}>${histogram(numericBins(subset, unit), { cumulative: true, cumulativeTotal: total })}</div>`).join("")}`
      : histogram(numericBins(bins, unit), { cumulative: true });
  return panel(
    title,
    subtitle,
    chart +
      metrics([
        ["対象カード", `${num(data?.count || 0)}枚`],
        [
          "中央値",
          data?.median == null ? "—" : `${num(data.median, 1)}${unit}`,
        ],
        ...(data?.average !== undefined
          ? [
              [
                "平均",
                data.average == null ? "—" : `${num(data.average, 2)}${unit}`,
              ],
            ]
          : []),
      ]) +
      (bins.length
        ? table(
            ["値", "枚数"],
            bins.map((b) => [b.label, num(b.count)]),
          )
        : ""),
  );
}
function calendarMarkup(entries, year) {
  const byDay = new Map(entries.map((d) => [d.day, d]));
  const start = new Date(Date.UTC(year, 0, 1)),
    end = new Date(Date.UTC(year + 1, 0, 1));
  const prefix = Array.from(
    { length: start.getUTCDay() },
    () => '<span class="anki-day-pad"></span>',
  ).join("");
  let cells = "";
  for (
    let date = new Date(start);
    date < end;
    date.setUTCDate(date.getUTCDate() + 1)
  ) {
    const day = date.toISOString().slice(0, 10),
      d = byDay.get(day) || {};
    const count = value(d.count),
      level = count ? Math.min(4, 1 + Math.floor(Math.log2(count) / 2)) : 0;
    const description = `${day}：${num(count)}回答・${duration(d.time)}・正答率 ${rate(d.correct, count)}`;
    cells += `<button type="button" class="anki-day anki-level-${level}" data-anki-day="${esc(description)}" aria-label="${esc(description)}" title="${esc(description)}"><span class="anki-sr">${esc(day)}</span></button>`;
  }
  return `<div class="anki-calendar-scroll"><div class="anki-months" aria-hidden="true">${Array.from({ length: 12 }, (_, i) => `<span>${i + 1}月</span>`).join("")}</div><div class="anki-calendar-body"><div class="anki-weekdays" aria-hidden="true">${["日", "月", "火", "水", "木", "金", "土"].map((day) => `<span>${day}</span>`).join("")}</div><div class="anki-calendar" aria-label="${year}年の学習カレンダー">${prefix}${cells}</div></div></div>`;
}
function calendar(entries) {
  const years = [
    ...new Set(
      entries
        .map((d) => Number(String(d.day).slice(0, 4)))
        .filter((y) => y >= 1900 && y < 10000),
    ),
  ].sort((a, b) => a - b);
  if (!years.length) years.push(new Date().getFullYear());
  const currentYear = new Date().getFullYear();
  if (!years.includes(currentYear)) {
    years.push(currentYear);
    years.sort((a, b) => a - b);
  }
  const current = currentYear;
  return panel(
    "カレンダー",
    "日付に触れる・フォーカスする・タップすると、学習時間・回答数・正答率を確認できます。",
    `<div class="anki-calendar-toolbar"><label>表示年 <select data-anki-year>${years.map((y) => `<option value="${y}"${y === current ? " selected" : ""}>${y}年</option>`).join("")}</select></label><span class="anki-calendar-legend">少ない ${[0, 1, 2, 3, 4].map((i) => `<i class="anki-level-${i}"></i>`).join("")} 多い</span></div>${years.map((y) => `<div data-anki-calendar-year="${y}"${y === current ? "" : " hidden"}>${calendarMarkup(entries, y)}</div>`).join("")}<p class="anki-calendar-status" data-anki-day-status role="status" aria-live="polite">日付を選択してください。</p>`,
    "anki-wide",
  );
}
function reviews(s) {
  const r = s.reviews || {},
    bins = r.bins || [];
  const charts = ["count", "time"]
    .map(
      (mode) =>
        `<div data-anki-review-chart="${mode}"${mode === "time" ? " hidden" : ""}>${histogram(
          timelineBins(bins, mode, r),
          {
            label: mode === "time" ? "学習時間（分）" : "回答数",
            format: (n) => num(n, 1),
          },
        )}</div>`,
    )
    .join("");
  const categories = [
    ["learn", "習得中"],
    ["young", "復習・未習熟"],
    ["mature", "復習・習熟"],
    ["relearn", "再習得"],
    ["filtered", "フィルター"],
  ];
  return panel(
    "学習",
    "カードに回答した回数と学習時間。1枚のカードへの複数回の回答を含みます。",
    `<div class="anki-toggle" role="group" aria-label="学習グラフの単位"><button type="button" data-anki-review="count" aria-pressed="true">回答数</button><button type="button" data-anki-review="time" aria-pressed="false">時間</button></div>${charts}${metrics(
      [
        [
          "学習した日の割合",
          `${num(r.activeDays)} / ${num(r.days)}日 (${rate(r.activeDays, r.days)})`,
        ],
        ["合計", `${num(r.count)}回答・${duration(r.time)}`],
        ["期間全体での平均", `${num(r.averagePerDay, 1)}回答 / 日`],
        ["学習した日での平均", `${num(r.averagePerActiveDay, 1)}回答 / 日`],
      ],
    )}${table(
      ["日付", "回答数", "時間", "正答率", ...categories.map((c) => c[1])],
      bins.map((b) => [
        b.day,
        num(b.count),
        duration(b.time),
        rate(b.correct, b.count),
        ...categories.map((c) => num(b[c[0]])),
      ]),
    )}`,
    "anki-wide",
  );
}
function future(s) {
  const f = s.futureDue || {},
    bins = f.bins || [];
  const ranges = [
    ["month", "1か月", 30],
    ["quarter", "3か月", 90],
    ["year", "1年", 365],
    ["all", "全期間", Infinity],
  ];
  const chart = `<div class="anki-future-controls"><label class="anki-range-label">表示範囲 <select data-anki-range>${ranges.map(([key, label]) => `<option value="${key}">${label}</option>`).join("")}</select></label><label class="anki-overdue-label"><input type="checkbox" data-anki-overdue checked> 延滞込み</label></div>${ranges
    .map(([key, , limit]) =>
      [true, false]
        .map((overdue) => {
          const visible = bins.filter(
            (b) => b.day <= limit && (overdue || b.day >= 0),
          );
          const start = Math.min(0, ...visible.map((b) => b.day));
          const end = Number.isFinite(limit)
            ? limit
            : Math.max(0, ...visible.map((b) => b.day));
          const days = end - start + 1;
          const total = visible.reduce((sum, b) => sum + value(b.count), 0);
          const overdueTotal = visible
            .filter((b) => b.day < 0)
            .reduce((sum, b) => sum + value(b.count), 0);
          return `<div data-anki-range-chart="${key}" data-anki-overdue-chart="${overdue}"${key === "month" && overdue ? "" : " hidden"}>${histogram(numericBins([...visible.map((b) => ({ ...b, value: b.day })), { value: start, count: 0 }, { value: end, count: 0 }], "日", { start }), { cumulative: true })}${metrics(
            [
              ["表示範囲の延滞", `${num(overdueTotal)}枚`],
              ["表示範囲の合計", `${num(total)}枚`],
              ["表示範囲の平均", `${num(total / days, 1)}枚 / 日`],
            ],
          )}<p class="anki-note">平均は表示範囲の合計 ÷ ${num(days)}日（${num(start)}〜${num(end)}日後、期日0枚の日を含む）です。</p></div>`;
        })
        .join(""),
    )
    .join("")}`;
  return panel(
    "今後の期日",
    "今日から次の復習・学習までの日数。負の日数は延滞です。",
    s.availability?.dueDates === false
      ? empty("次回期日のデータがありません。新しい形式で同期してください。")
      : `${chart}${metrics([
          ["明日が期日", `${num(f.tomorrow)}枚`],
          [
            "現在の負荷",
            f.workload == null ? "—" : `${num(f.workload, 1)}枚 / 日`,
          ],
        ])}<p class="anki-note">現在の負荷は学習・復習カードの「1 ÷ 復習間隔（最低1日）」の合計です。新規・休止中のカードは含みません。</p>${table(
          ["今日からの日数", "期日の枚数"],
          bins.map((b) => [b.day, num(b.count)]),
        )}`,
    "anki-wide",
  );
}
function states(s) {
  const c = s.cardCounts || {},
    labels = [
      ["new", "新規"],
      ["learn", "習得中"],
      ["relearn", "再習得中"],
      ["young", "復習・未習熟期"],
      ["mature", "復習・習熟期"],
      ["suspended", "休止中"],
      ["buried", "今日は非表示"],
      ["unknown", "不明"],
    ];
  const bins = labels.map(([key, label]) => ({ label, count: c[key] || 0 }));
  return panel(
    "カード枚数",
    "休止中・今日は非表示のカードを分けて集計します。",
    histogram(bins) +
      table(
        ["カードの状態", "枚数", "割合"],
        bins.map((b) => [b.label, num(b.count), rate(b.count, c.total)]),
        "状態ごとの枚数と割合",
      ) +
      metrics([["合計", `${num(c.total)}枚`]]),
  );
}
function retention(s) {
  const labels = {
    today: "今日",
    yesterday: "昨日",
    week: "直近1週間",
    month: "直近1か月",
    year: "直近1年",
    all: "全期間",
    "7d": "直近1週間",
    "30d": "直近1か月",
    "365d": "直近1年",
  };
  const rows = (s.retention || []).map((r) => [
    labels[r.period] || r.period,
    ...["young", "mature", "all"].map((k) =>
      r[k]?.rate == null ? "—" : `${num(r[k].rate * 100, 1)}%`,
    ),
    num(r.all?.count),
  ]);
  return panel(
    "正答率（True retention）",
    "直前の復習間隔が1日以上の回答を対象にします。未習熟期は21日未満、習熟期は21日以上。",
    s.availability?.previousIntervals === false
      ? empty(
          "以前の復習間隔が保存されていないため、True retentionを算出できません。",
        )
      : `<div class="anki-table-scroll"><table><thead><tr>${["期間", "未習熟期", "習熟期", "全体", "回答数"].map((x) => `<th scope="col">${x}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((x, i) => (i ? `<td>${esc(x)}</td>` : `<th scope="row">${esc(x)}</th>`)).join("")}</tr>`).join("")}</tbody></table></div>`,
    "anki-wide",
  );
}
function hourly(s) {
  const bins = (s.hourly || []).map((b) => ({ ...b, label: `${b.hour}時` }));
  return panel(
    "時間帯の分析",
    `各時間帯の回答数と正答率（${s.timezone || "コレクションのタイムゾーン"}）。`,
    histogram(bins, { label: "回答数", accuracy: true }) +
      table(
        ["時間帯", "回答数", "正答率"],
        bins.map((b) => [
          b.label,
          num(b.count),
          b.rate == null ? "—" : `${num(b.rate * 100, 1)}%`,
        ]),
      ),
  );
}
function buttons(s) {
  const groups = [
      ["learn", "習得中"],
      ["young", "復習・未習熟期"],
      ["mature", "復習・習熟期"],
    ],
    names = ["Again", "Hard", "Good", "Easy"];
  return panel(
    "回答ボタン",
    "評価ごとの回答数。正答率はAgain以外の回答の割合です。",
    groups
      .map(([key, label]) => {
        const counts = (s.answerButtons?.[key] || [0, 0, 0, 0]).map(value),
          total = counts.reduce((a, b) => a + b, 0);
        return `<div class="anki-answer-group"><h3>${label} <small>正答率 ${rate(total - counts[0], total)}</small></h3>${histogram(
          counts.map((count, i) => ({ label: names[i], count })),
          { label: "回答数" },
        )}</div>`;
      })
      .join("") +
      table(
        ["状態", "Again", "Hard", "Good", "Easy"],
        groups.map(([key, label]) => [
          label,
          ...(s.answerButtons?.[key] || [0, 0, 0, 0]).map((n) => num(n)),
        ]),
      ),
  );
}
export function renderAnkiInsights(s = {}) {
  const t = s.today || {},
    added = s.added || [];
  return `<div class="anki-insights"><p class="anki-scope-note">日付の区切り：${num(s.rolloverHour ?? 4)}時 · ${esc(s.timezone || "コレクションのタイムゾーン")}。すべて選択したデッキが対象です。学習・時間帯・回答ボタン・追加は選択した期間、カレンダーは全履歴、正答率は表の各期間を集計します。今日の集計は当日、カード状態・復習間隔・易しさ・FSRSは現在の状態です。今後の期日は各グラフの表示範囲に従います。</p><div class="anki-grid">${panel(
    "今日",
    "今日の学習を振り返る。",
    metrics([
      ["回答数", `${num(t.count || 0)}回`],
      ["学習したカード", `${num(t.uniqueCards || 0)}枚`],
      ["学習時間", duration(t.time)],
      ["正解", `${num(t.correct || 0)}回 (${rate(t.correct, t.count)})`],
      ["Again", `${num(t.again || 0)}回`],
      ["1回答の平均", t.count ? duration(t.time / t.count) : "—"],
    ]),
    "anki-wide",
  )}${future(s)}${calendar(s.calendar || [])}${reviews(s)}${states(s)}${distribution("復習間隔", "次の復習までの間隔日数とカード枚数。", s.intervals)}${distribution("カードの易しさ", "易しさが低いほど、カードが表示される頻度が高くなります。", s.ease, "%")}${retention(s)}${hourly(s)}${buttons(s)}${panel(
    "追加",
    "新規カードを追加した日と枚数。",
    histogram(timelineBins(added, "count", s.reviews)) +
      metrics([
        [
          "追加したカード",
          `${num(added.reduce((n, b) => n + value(b.count), 0))}枚`,
        ],
      ]) +
      (added.length
        ? table(
            ["追加日", "枚数"],
            added.map((b) => [b.day, num(b.count)]),
          )
        : ""),
  )}${s.fsrs && ["stability", "difficulty", "retrievability"].some((key) => s.fsrs[key]?.count > 0) ? distribution("FSRS 安定性", "記憶が90%保持されるまでの日数。", s.fsrs.stability) + distribution("FSRS 難易度", "カードの記憶の難しさ（1〜10）。", s.fsrs.difficulty, "") + distribution("FSRS 想起確率", "現在の記憶を取り出せる推定確率。", s.fsrs.retrievability, "%") : panel("FSRS", "安定性・難易度・想起確率", empty("FSRSの記憶状態データは、この同期データには含まれていません。"), "anki-wide")}</div></div>`;
}
export function bindAnkiInsights(container) {
  const root = container?.querySelector?.(".anki-insights");
  if (!root || root.dataset.bound) return;
  root.dataset.bound = "true";
  const updateDay = (event) => {
    const day = event.target.closest?.("[data-anki-day]");
    if (day && root.contains(day))
      root.querySelector("[data-anki-day-status]").textContent =
        day.dataset.ankiDay;
  };
  root.addEventListener("pointerover", updateDay);
  root.addEventListener("focusin", updateDay);
  root.addEventListener("click", (event) => {
    updateDay(event);
    const toggle = event.target.closest?.("[data-anki-review]");
    if (toggle) {
      root
        .querySelectorAll("[data-anki-review]")
        .forEach((button) =>
          button.setAttribute("aria-pressed", String(button === toggle)),
        );
      root
        .querySelectorAll("[data-anki-review-chart]")
        .forEach(
          (chart) =>
            (chart.hidden =
              chart.dataset.ankiReviewChart !== toggle.dataset.ankiReview),
        );
    }
  });
  root.addEventListener("change", (event) => {
    if (event.target.matches("[data-anki-year]"))
      root
        .querySelectorAll("[data-anki-calendar-year]")
        .forEach(
          (year) =>
            (year.hidden =
              year.dataset.ankiCalendarYear !== event.target.value),
        );
    if (event.target.matches("[data-anki-range], [data-anki-overdue]")) {
      const scope = event.target.closest(".anki-panel"),
        selected = scope.querySelector("[data-anki-range]").value,
        overdue = scope.querySelector("[data-anki-overdue]");
      scope
        .querySelectorAll("[data-anki-range-chart]")
        .forEach(
          (chart) =>
            (chart.hidden =
              chart.dataset.ankiRangeChart !== selected ||
              (overdue &&
                chart.dataset.ankiOverdueChart !== String(overdue.checked))),
        );
    }
  });
}
