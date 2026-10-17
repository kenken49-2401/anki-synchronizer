import test from "node:test";
import assert from "node:assert/strict";
import { renderAnkiInsights, bindAnkiInsights } from "../web/anki-insights.mjs";

const sample = {
  timezone: "Asia/Tokyo",
  rolloverHour: 4,
  today: { count: 4, correct: 3, again: 1, time: 120000, uniqueCards: 2 },
  futureDue: {
    bins: [
      { day: -1, count: 3 },
      { day: 1, count: 2 },
    ],
    overdue: 3,
    tomorrow: 2,
    total: 5,
    average: 2.5,
    workload: 1.5,
  },
  calendar: [{ day: "2024-02-29", count: 4, correct: 3, time: 120000 }],
  reviews: {
    bins: [
      {
        day: "2024-02-29",
        count: 4,
        correct: 3,
        time: 120000,
        learn: 1,
        young: 3,
      },
    ],
    count: 4,
    correct: 3,
    time: 120000,
    days: 30,
    activeDays: 1,
    averagePerDay: 4 / 30,
    averagePerActiveDay: 4,
  },
  cardCounts: { new: 1, young: 1, total: 2 },
  intervals: { bins: [{ value: 1, count: 2 }], count: 2, median: 1 },
  ease: { bins: [{ value: 250, count: 2 }], count: 2, median: 250 },
  retention: [
    {
      period: "week",
      young: { rate: 0.75 },
      mature: { rate: null },
      all: { count: 4, rate: 0.75 },
    },
  ],
  hourly: [{ hour: 8, count: 4, correct: 3, rate: 0.75 }],
  answerButtons: {
    learn: [1, 0, 0, 0],
    young: [0, 1, 1, 1],
    mature: [0, 0, 0, 0],
  },
  added: [{ day: "2024-02-29", count: 2 }],
  availability: { dueDates: true, previousIntervals: true },
};

test("insights present the full reference sections and preserve units", () => {
  const html = renderAnkiInsights(sample);
  for (const heading of [
    "今日",
    "今後の期日",
    "カレンダー",
    "学習",
    "カード枚数",
    "復習間隔",
    "カードの易しさ",
    "正答率（True retention）",
    "時間帯の分析",
    "回答ボタン",
    "追加",
    "FSRS",
  ])
    assert.ok(html.includes(heading), heading);
  assert.ok(html.includes("2024-02-29：4回答・2分・正答率 75%"));
  assert.ok(html.includes("250%"));
  assert.ok(html.includes('data-anki-review-chart="time" hidden'));
  assert.ok(html.includes("data-anki-overdue"));
  assert.ok(!/\sstyle=|\sonclick=/.test(html));
});

test("yearly calendar contains every leap-year date as focusable buttons", () => {
  const html = renderAnkiInsights(sample);
  const leap = html
    .split('data-anki-calendar-year="2024"')[1]
    .split("data-anki-calendar-year=")[0];
  assert.equal((leap.match(/data-anki-day=/g) || []).length, 366);
  assert.ok(leap.includes("2024-12-31"));
  assert.ok(leap.includes("2024-01-01"));
});

test("unavailable data stays explicit and arbitrary labels are escaped", () => {
  const html = renderAnkiInsights({
    timezone: '"><img src=x onerror=alert(1)>',
    calendar: [{ day: 'bad\"><script>alert(1)</script>', count: 1 }],
    availability: { dueDates: false, previousIntervals: false },
  });
  assert.ok(html.includes("True retentionを算出できません"));
  assert.ok(html.includes("次回期日のデータがありません"));
  assert.ok(html.includes("FSRSの記憶状態データは"));
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes("<script"));
  assert.ok(!html.includes("NaN"));
  assert.ok(!html.includes("Infinity"));
});

test("empty rendering and binding without mounted insights are safe", () => {
  assert.ok(renderAnkiInsights().includes("この範囲にはデータがありません"));
  assert.doesNotThrow(() => bindAnkiInsights(null));
  assert.doesNotThrow(() => bindAnkiInsights({ querySelector: () => null }));
});

const section = (html, title) =>
  html.split(`<h2>${title}</h2>`)[1].split("</section>")[0];
const variant = (html, range, overdue) =>
  html
    .split(
      `data-anki-range-chart="${range}" data-anki-overdue-chart="${overdue}"`,
    )[1]
    .split("data-anki-range-chart=")[0];

test("future summaries follow both horizon and overdue controls with explicit denominator", () => {
  const html = section(
    renderAnkiInsights({
      ...sample,
      futureDue: {
        ...sample.futureDue,
        bins: [...sample.futureDue.bins, { day: 100, count: 20 }],
        total: 25,
      },
    }),
    "今後の期日",
  );
  const month = variant(html, "month", true);
  assert.match(month, /表示範囲の合計<\/dt><dd>5枚/);
  assert.match(month, /表示範囲の平均<\/dt><dd>0.2枚 \/ 日/);
  assert.ok(month.includes("32日（-1〜30日後"));
  const noOverdue = variant(html, "month", false);
  assert.match(noOverdue, /表示範囲の延滞<\/dt><dd>0枚/);
  assert.match(noOverdue, /表示範囲の合計<\/dt><dd>2枚/);
  assert.ok(noOverdue.includes("31日（0〜30日後"));
  assert.ok(noOverdue.includes("30日: 0 枚数"));
  assert.ok(variant(html, "quarter", false).includes("90日: 0 枚数"));
  assert.ok(variant(html, "year", false).includes("365日: 0 枚数"));
  assert.match(variant(html, "all", true), /表示範囲の合計<\/dt><dd>25枚/);
});

test("ease average preserves precise backend value instead of averaging floored bins", () => {
  const html = section(
    renderAnkiInsights({
      ...sample,
      ease: {
        count: 2,
        median: 250,
        average: 250.45,
        bins: [{ value: 250, count: 2 }],
      },
    }),
    "カードの易しさ",
  );
  assert.match(html, /平均<\/dt><dd>250.45%/);
});

test("clipped interval cumulative share uses the full distribution denominator", () => {
  const html = section(
    renderAnkiInsights({
      ...sample,
      intervals: {
        count: 8,
        median: 55,
        bins: [
          { value: 1, count: 2 },
          { value: 10, count: 2 },
          { value: 100, count: 4 },
        ],
      },
    }),
    "復習間隔",
  );
  const half = html
    .split('data-anki-range-chart="half"')[1]
    .split("data-anki-range-chart=")[0];
  const points = half.match(/class="anki-cumulative" points="([^"]+)"/)[1];
  assert.equal(Number(points.split(" ").at(-1).split(",")[1]), 77.5); // 50% of 131px chart height.
});

test("sparse timelines retain zero days, full years and bounded chronological buckets", () => {
  const rows = [
    { day: "2023-01-01", count: 1, time: 1000 },
    { day: "2023-01-03", count: 2, time: 2000 },
  ];
  const html = renderAnkiInsights({
    ...sample,
    reviews: { ...sample.reviews, bins: rows, days: 3 },
    added: rows,
  });
  assert.ok(section(html, "学習").includes("2023-01-02: 0 回答数"));
  assert.ok(section(html, "追加").includes("2023-01-02: 0 枚数"));
  const long = renderAnkiInsights({
    ...sample,
    reviews: {
      ...sample.reviews,
      bins: [rows[0], { day: "2043-01-01", count: 1 }],
      days: 0,
    },
    added: [],
  });
  const countChart = section(long, "学習").split(
    'data-anki-review-chart="time"',
  )[0];
  assert.ok((countChart.match(/<rect /g) || []).length <= 120);
  assert.ok(countChart.includes("2023-01-01"));
  assert.ok(countChart.includes("2043-01-01"));
  assert.ok(html.includes("カレンダーは全履歴、正答率は表の各期間"));
});
