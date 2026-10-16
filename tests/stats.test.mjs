import test from "node:test";
import assert from "node:assert/strict";
import {
  dayKey,
  dayRange,
  studyReviews,
  summarize,
  filterCards,
  percent,
  minutes,
  deckTree,
  groupCards,
  periodSummary,
} from "../web/stats.mjs";

test("period statistics sum Anki time, ratings and decks across Tokyo day boundaries", () => {
  const now = new Date("2026-10-16T05:00:00Z"),
    data = {
      cards: [
        { id: 1, deck: "科学::化学" },
        { id: 2, deck: "英語" },
      ],
      reviews: [
        {
          id: Date.parse("2026-10-15T15:00:00Z"),
          card_id: 1,
          ease: 1,
          time_ms: 10000,
          type: 1,
        },
        {
          id: Date.parse("2026-10-15T14:59:59Z"),
          card_id: 2,
          ease: 3,
          time_ms: 30000,
          type: 1,
        },
        {
          id: Date.parse("2026-10-16T04:00:00Z"),
          card_id: 1,
          ease: 4,
          time_ms: 20000,
          type: 1,
        },
        {
          id: Date.parse("2026-10-16T04:00:01Z"),
          card_id: 1,
          ease: 0,
          time_ms: 999999,
          type: 4,
        },
        {
          id: Date.parse("2026-10-17T04:00:00Z"),
          card_id: 1,
          ease: 4,
          time_ms: 999999,
          type: 1,
        },
      ],
    };
  const s = periodSummary(data, { days: 1, now });
  assert.equal(s.time, 30000);
  assert.equal(s.count, 2);
  assert.equal(s.correct, 1);
  assert.equal(s.averageMs, 15000);
  assert.equal(s.activeDays, 1);
  assert.equal(s.uniqueCards, 1);
  assert.deepEqual(s.byEase, [1, 0, 0, 1]);
  assert.equal(s.decks[0].deck, "科学::化学");
  const all = periodSummary(data, { days: 0, now });
  assert.equal(all.time, 60000);
  assert.equal(all.activeDays, 2);
  assert.equal(all.decks.length, 2);
  assert.equal(periodSummary({ cards: [], reviews: [] }, { now }).averageMs, 0);
});

test("deck tree includes empty parents, direct counts and descendant counts", () => {
  const cards = [
    { deck: "科学" },
    { deck: "科学::化学" },
    { deck: "科学::化学::高分子" },
    { deck: "科学::生物" },
    { deck: "科学館" },
    { deck: "英語::単語" },
  ];
  const tree = new Map(deckTree(cards).map((n) => [n.name, n]));
  assert.deepEqual(tree.get("科学"), {
    name: "科学",
    depth: 0,
    count: 4,
    directCount: 1,
  });
  assert.deepEqual(tree.get("科学::化学"), {
    name: "科学::化学",
    depth: 1,
    count: 2,
    directCount: 1,
  });
  assert.deepEqual(tree.get("英語"), {
    name: "英語",
    depth: 0,
    count: 1,
    directCount: 0,
  });
  assert.equal(tree.get("科学館").count, 1);
});

test("parent deck filtering includes subdecks only when enabled and respects separator", () => {
  const cards = [
    card(1, { deck: "科学" }),
    card(2, { deck: "科学::化学" }),
    card(3, { deck: "科学::化学::高分子" }),
    card(4, { deck: "科学館" }),
  ];
  assert.deepEqual(
    filterCards(cards, { deck: "科学" }).map((c) => c.id),
    [1],
  );
  assert.deepEqual(
    filterCards(cards, { deck: "科学", includeSubdecks: true }).map(
      (c) => c.id,
    ),
    [1, 2, 3],
  );
  assert.deepEqual(
    filterCards(cards, { deck: "科学::化学", includeSubdecks: true }).map(
      (c) => c.id,
    ),
    [2, 3],
  );
});

test("folder groups keep parent and descendants together, exact decks remain separate", () => {
  const cards = [
    card(1, { deck: "科学::化学" }),
    card(2, { deck: "科学" }),
    card(3, { deck: "英語::単語" }),
    card(4, { deck: "科学::化学::高分子" }),
  ];
  const before = structuredClone(cards);
  const folder = groupCards(cards, "folder");
  assert.equal(folder.length, 2);
  assert.deepEqual(
    folder.find((g) => g.name === "科学").cards.map((c) => c.id),
    [1, 2, 4],
  );
  assert.equal(groupCards(cards, "deck").length, 4);
  assert.deepEqual(groupCards(cards, "none")[0].cards, cards);
  assert.deepEqual(groupCards([], "folder"), []);
  assert.deepEqual(cards, before);
});

const card = (id, extra = {}) => ({
  id,
  tags: [],
  deck: "日本語",
  front: `表${id}`,
  back: `裏${id}`,
  fields: {},
  ...extra,
});
const review = (cardId, at, extra = {}) => ({
  card_id: cardId,
  id: Date.parse(at),
  ease: 3,
  time_ms: 1000,
  type: 1,
  ...extra,
});

test("Tokyo study days change at local midnight and aggregate daily time", () => {
  assert.equal(dayKey("2026-10-14T14:59:59.999Z"), "2026-10-14");
  assert.equal(dayKey("2026-10-14T15:00:00.000Z"), "2026-10-15");
  assert.equal(dayKey("invalid"), null);
  const stats = summarize(
    {
      cards: [card(1)],
      reviews: [
        review(1, "2026-10-14T14:59:59.999Z", { time_ms: 30000 }),
        review(1, "2026-10-14T15:00:00.000Z", { time_ms: 60000, ease: 1 }),
        review(1, "2026-10-15T00:00:00.000Z", { time_ms: 30000 }),
      ],
    },
    { now: "2026-10-15T01:00:00Z" },
  );
  assert.deepEqual(stats.today, { count: 2, correct: 1, time: 90000 });
  assert.deepEqual(stats.byDay.get("2026-10-14"), {
    count: 1,
    correct: 1,
    time: 30000,
  });
  assert.equal(minutes(stats.today.time), 1.5);
});

test("seven-day ranges retain consecutive calendar dates across DST changes", () => {
  assert.deepEqual(dayRange(7, "2026-03-09T03:30:00Z", "America/New_York"), [
    "2026-03-02",
    "2026-03-03",
    "2026-03-04",
    "2026-03-05",
    "2026-03-06",
    "2026-03-07",
    "2026-03-08",
  ]);
  assert.deepEqual(dayRange(7, "2026-11-02T04:30:00Z", "America/New_York"), [
    "2026-10-26",
    "2026-10-27",
    "2026-10-28",
    "2026-10-29",
    "2026-10-30",
    "2026-10-31",
    "2026-11-01",
  ]);
});

test("multi-tag cards contribute once to each tag, including deduplication and untagged cards", () => {
  const stats = summarize(
    {
      cards: [
        card(1, { tags: ["文法", "N2", "文法"] }),
        card(2, { tags: ["文法"] }),
        card(3),
      ],
      reviews: [
        review(1, "2026-10-14T16:00:00Z", { ease: 1 }),
        review(1, "2026-10-14T17:00:00Z"),
        review(2, "2026-10-14T18:00:00Z"),
      ],
    },
    { now: "2026-10-15T00:00:00Z" },
  );
  assert.equal(stats.cards, 3);
  assert.equal(stats.tags[0].tag, "文法");
  const tags = new Map(stats.tags.map((t) => [t.tag, t]));
  assert.deepEqual(tags.get("文法"), {
    tag: "文法",
    count: 2,
    reviews: 3,
    correct: 2,
  });
  assert.deepEqual(tags.get("N2"), {
    tag: "N2",
    count: 1,
    reviews: 2,
    correct: 1,
  });
  assert.deepEqual(tags.get("タグなし"), {
    tag: "タグなし",
    count: 1,
    reviews: 0,
    correct: 0,
  });
});

test("accuracy considers ease 1 incorrect and ease 2–4 correct for study types 0–3", () => {
  const reviews = [0, 1, 2, 3].map((type, i) =>
    review(1, `2026-10-15T0${i}:00:00Z`, {
      type,
      ease: i + 1,
      time_ms: (i + 1) * 1000,
    }),
  );
  const stats = summarize(
    { cards: [card(1), card(2)], reviews },
    { now: "2026-10-15T05:00:00Z" },
  );
  assert.equal(stats.reviews, 4);
  assert.equal(stats.correct, 3);
  assert.deepEqual(stats.byCard.get(1), {
    count: 4,
    correct: 3,
    time: 10000,
    last: reviews[3].id,
  });
  assert.equal(stats.byCard.has(2), false);
  assert.equal(
    percent(stats.byCard.get(1).correct, stats.byCard.get(1).count),
    "75%",
  );
});

test("manual, rescheduled, unknown-card, and invalid reviews do not enter study totals", () => {
  const valid = review(1, "2026-10-15T00:00:00Z");
  const snapshot = {
    cards: [card(1)],
    reviews: [
      valid,
      { ...valid, type: 4 },
      { ...valid, type: 5 },
      { ...valid, type: -1 },
      { ...valid, card_id: 999 },
      { ...valid, ease: 0 },
      { ...valid, ease: 5 },
      { ...valid, id: 0 },
      { ...valid, id: NaN },
      { ...valid, id: Infinity },
    ],
  };
  assert.deepEqual(studyReviews(snapshot), [valid]);
  const stats = summarize(snapshot, { now: "2026-10-15T00:00:00Z" });
  assert.equal(stats.reviews, 1);
  assert.equal(stats.byCard.has(999), false);
  assert.deepEqual(stats.today, { count: 1, correct: 1, time: 1000 });
});

test("empty snapshots have safe zero denominators and empty aggregates", () => {
  const stats = summarize(undefined, { now: "2026-10-15T00:00:00Z" });
  assert.deepEqual(
    [stats.cards, stats.reviews, stats.correct, stats.streak],
    [0, 0, 0, 0],
  );
  assert.deepEqual(stats.today, { count: 0, correct: 0, time: 0 });
  assert.equal(stats.byCard.size, 0);
  assert.equal(stats.byDay.size, 0);
  assert.deepEqual(stats.tags, []);
  assert.equal(percent(0, 0), "—");
  assert.equal(percent(0, 3), "0%");
  assert.equal(minutes(0), 0);
});

test("filters search fields, tags and deck together without mutating cards or source order", () => {
  const cards = [
    card(3, { tags: ["N2"], fields: { Reading: "HAYAI" } }),
    card(1, { tags: ["N2"], deck: "別デッキ", back: "hayai" }),
    card(2),
  ];
  const before = structuredClone(cards);
  const stats = new Map([
    [3, { count: 4, correct: 3, last: 100 }],
    [1, { count: 2, correct: 0, last: 200 }],
  ]);
  assert.deepEqual(
    filterCards(
      cards,
      { tag: "N2", deck: "日本語", query: "  hayai " },
      stats,
    ).map((c) => c.id),
    [3],
  );
  assert.deepEqual(
    filterCards(cards, { query: "N2" }).map((c) => c.id),
    [3, 1],
  );
  assert.deepEqual(
    filterCards(cards, { query: "別デッキ" }).map((c) => c.id),
    [1],
  );
  assert.deepEqual(
    filterCards(cards, { tag: "タグなし" }).map((c) => c.id),
    [2],
  );
  assert.deepEqual(
    filterCards(cards, { sort: "accuracy" }, stats).map((c) => c.id),
    [1, 3, 2],
  );
  assert.deepEqual(
    filterCards(cards, { sort: "recent" }, stats).map((c) => c.id),
    [1, 3, 2],
  );
  assert.deepEqual(
    filterCards(cards, {}, stats).map((c) => c.id),
    [3, 1, 2],
  );
  assert.deepEqual(cards, before);
});

test("streaks continue beyond 90 days, tolerate an unfinished today, and stop at a gap", () => {
  const last = Date.parse("2026-10-15T00:00:00Z");
  const reviews = Array.from({ length: 125 }, (_, i) => ({
    ...review(1, "2026-10-15T00:00:00Z"),
    id: last - i * 86400000,
  }));
  const snapshot = { cards: [card(1)], reviews };
  assert.equal(summarize(snapshot, { now: last }).streak, 125);
  assert.equal(summarize(snapshot, { now: last + 86400000 }).streak, 125);
  assert.equal(summarize(snapshot, { now: last + 2 * 86400000 }).streak, 0);
  assert.equal(
    summarize(
      { ...snapshot, reviews: reviews.filter((_, i) => i !== 20) },
      { now: last },
    ).streak,
    20,
  );
});

test("large histories reuse one date formatter per timezone without mixing local study dates", (t) => {
  const OriginalDateTimeFormat = Intl.DateTimeFormat;
  const constructions = [];
  t.mock.method(Intl, "DateTimeFormat", function (...args) {
    constructions.push(args[1].timeZone);
    return new OriginalDateTimeFormat(...args);
  });
  const timestamp = Date.parse("2026-10-15T10:00:00Z");
  const snapshot = {
    cards: [card(1)],
    reviews: Array.from({ length: 10000 }, (_, i) => ({
      card_id: 1,
      id: timestamp + i,
      ease: (i % 4) + 1,
      time_ms: 1000,
      type: i % 4,
    })),
  };
  const now = "2026-10-16T00:00:00Z";
  const auckland = summarize(snapshot, { timezone: "Pacific/Auckland", now });
  const honolulu = summarize(snapshot, { timezone: "Pacific/Honolulu", now });
  summarize(snapshot, { timezone: "Pacific/Auckland", now });
  assert.deepEqual(constructions, ["Pacific/Auckland", "Pacific/Honolulu"]);
  assert.equal(auckland.reviews, 10000);
  assert.equal(auckland.correct, 7500);
  assert.deepEqual(auckland.byCard.get(1), {
    count: 10000,
    correct: 7500,
    time: 10000000,
    last: timestamp + 9999,
  });
  assert.deepEqual(auckland.byDay.get("2026-10-15"), {
    count: 10000,
    correct: 7500,
    time: 10000000,
  });
  assert.deepEqual(auckland.today, { count: 0, correct: 0, time: 0 });
  assert.deepEqual(honolulu.today, {
    count: 10000,
    correct: 7500,
    time: 10000000,
  });
});
