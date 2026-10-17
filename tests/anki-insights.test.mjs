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
