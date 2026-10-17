const dayFormatters = new Map();

export function dayKey(value, timezone = "Asia/Tokyo", rolloverHour = 0) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return null;
  let formatter = dayFormatters.get(timezone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      hourCycle: "h23",
    });
    dayFormatters.set(timezone, formatter);
  }
  const parts = formatter.formatToParts(date);
  const get = (type) => parts.find((p) => p.type === type).value;
  const key = `${get("year")}-${get("month")}-${get("day")}`;
  return Number(get("hour")) < rolloverHour ? shiftDay(key, -1) : key;
}

export function dayRange(
  days,
  today,
  timezone = "Asia/Tokyo",
  rolloverHour = 0,
) {
  const end = dayKey(today, timezone, rolloverHour);
  const anchor = new Date(`${end}T12:00:00Z`);
  return Array.from({ length: days }, (_, i) => {
    const d = new Date(anchor);
    d.setUTCDate(d.getUTCDate() - (days - 1 - i));
    return d.toISOString().slice(0, 10);
  });
}

export function studyReviews(snapshot) {
  const ids = new Set((snapshot?.cards || []).map((c) => c.id));
  const valid = (r) =>
    Number.isFinite(r.id) &&
    r.id > 0 &&
    r.ease >= 1 &&
    r.ease <= 4 &&
    r.type >= 0 &&
    r.type <= 3;
  const reviews = (snapshot?.reviews || []).filter(
    (r) => ids.has(r.card_id) && valid(r),
  );
  if (snapshot?.source?.history_scope === "collection") {
    for (const review of snapshot.orphan_reviews || []) {
      if (!ids.has(review.card_id) && valid(review)) reviews.push(review);
    }
  }
  return reviews;
}

export function summarize(
  snapshot,
  { timezone = "Asia/Tokyo", now = new Date(), rolloverHour = 0 } = {},
) {
  const cards = snapshot?.cards || [];
  const reviews = studyReviews(snapshot);
  const byCard = new Map();
  const byDay = new Map();
  let correct = 0;
  for (const r of reviews) {
    const isCorrect = Number(r.ease > 1);
    correct += isCorrect;
    const entry = byCard.get(r.card_id) || {
      count: 0,
      correct: 0,
      time: 0,
      last: 0,
    };
    entry.count++;
    entry.correct += isCorrect;
    entry.time += Math.max(0, r.time_ms || 0);
    entry.last = Math.max(entry.last, r.id);
    byCard.set(r.card_id, entry);
    const day = dayKey(r.id, timezone, rolloverHour);
    const daily = byDay.get(day) || { count: 0, correct: 0, time: 0 };
    daily.count++;
    daily.correct += isCorrect;
    daily.time += Math.max(0, r.time_ms || 0);
    byDay.set(day, daily);
  }
  const tags = new Map();
  for (const c of cards) {
    for (const tag of c.tags.length ? [...new Set(c.tags)] : ["タグなし"]) {
      const group = tags.get(tag) || { tag, count: 0, reviews: 0, correct: 0 };
      group.count++;
      group.reviews += byCard.get(c.id)?.count || 0;
      group.correct += byCard.get(c.id)?.correct || 0;
      tags.set(tag, group);
    }
  }
  const todayKey = dayKey(now, timezone, rolloverHour);
  const today = byDay.get(todayKey) || { count: 0, correct: 0, time: 0 };
  let streak = 0;
  const streakDay = new Date(`${todayKey}T12:00:00Z`);
  if (!today.count) streakDay.setUTCDate(streakDay.getUTCDate() - 1);
  while (byDay.get(streakDay.toISOString().slice(0, 10))?.count) {
    streak++;
    streakDay.setUTCDate(streakDay.getUTCDate() - 1);
  }
  return {
    cards: cards.length,
    reviews: reviews.length,
    correct,
    byCard,
    byDay,
    today,
    streak,
    tags: [...tags.values()].sort(
      (a, b) => b.count - a.count || a.tag.localeCompare(b.tag, "ja"),
    ),
  };
}

export function filterCards(
  cards,
  {
    tag = "",
    deck = "",
    decks = [],
    includeSubdecks = false,
    query = "",
    sort = "default",
  } = {},
  byCard = new Map(),
) {
  const q = query.trim().toLocaleLowerCase();
  const selected = cards.filter(
    (c) =>
      (!tag || (tag === "タグなし" ? !c.tags.length : c.tags.includes(tag))) &&
      (!(decks.length || deck) ||
        (decks.length ? decks : [deck]).some(
          (name) =>
            c.deck === name ||
            (includeSubdecks && c.deck.startsWith(name + "::")),
        )) &&
      (!q ||
        [c.front, c.back, c.deck, ...c.tags, ...Object.values(c.fields || {})]
          .join(" ")
          .toLocaleLowerCase()
          .includes(q)),
  );
  if (sort === "accuracy")
    selected.sort((a, b) => {
      const stat = (c) => {
        const s = byCard.get(c.id);
        return s?.count ? s.correct / s.count : 2;
      };
      return stat(a) - stat(b) || a.id - b.id;
    });
  if (sort === "recent")
    selected.sort(
      (a, b) => (byCard.get(b.id)?.last || 0) - (byCard.get(a.id)?.last || 0),
    );
  return selected;
}

// Anki separates a deck from its subdecks with ::, not a loose string prefix.
export function deckTree(cards) {
  const nodes = new Map();
  for (const card of cards) {
    const parts = card.deck.split("::");
    for (let depth = 0; depth < parts.length; depth++) {
      const name = parts.slice(0, depth + 1).join("::");
      const node = nodes.get(name) || { name, depth, count: 0, directCount: 0 };
      node.count++;
      if (depth === parts.length - 1) node.directCount++;
      nodes.set(name, node);
    }
  }
  return [...nodes.values()].sort((a, b) =>
    a.name.localeCompare(b.name, "ja", { numeric: true }),
  );
}

export function groupCards(cards, mode = "none") {
  if (!["deck", "folder"].includes(mode))
    return [{ name: "", cards: [...cards] }];
  const groups = new Map();
  for (const card of cards) {
    const name = mode === "folder" ? card.deck.split("::")[0] : card.deck;
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(card);
  }
  return [...groups]
    .sort(([a], [b]) => a.localeCompare(b, "ja", { numeric: true }))
    .map(([name, items]) => ({ name, cards: items }));
}

export function percent(correct, count) {
  return count ? `${Math.round((correct / count) * 100)}%` : "—";
}
export function minutes(ms) {
  return Math.round((ms / 60000) * 10) / 10;
}

export function periodSummary(
  snapshot,
  {
    days = 30,
    timezone = "Asia/Tokyo",
    now = new Date(),
    rolloverHour = 0,
  } = {},
) {
  const until = new Date(now).valueOf();
  const today = dayKey(now, timezone, rolloverHour);
  const first = days ? dayRange(days, now, timezone, rolloverHour)[0] : "";
  const cards = new Map((snapshot?.cards || []).map((c) => [c.id, c]));
  const byDeck = new Map(),
    byEase = [0, 0, 0, 0],
    studied = new Set(),
    active = new Set();
  let count = 0,
    correct = 0,
    time = 0;
  for (const r of studyReviews(snapshot)) {
    const day = dayKey(r.id, timezone, rolloverHour);
    if (!day || r.id > until || day > today || (first && day < first)) continue;
    const duration = Number.isFinite(r.time_ms) ? Math.max(0, r.time_ms) : 0;
    const deck = cards.get(r.card_id)?.deck || "削除済みカード";
    const entry = byDeck.get(deck) || { deck, count: 0, correct: 0, time: 0 };
    count++;
    correct += Number(r.ease > 1);
    time += duration;
    entry.count++;
    entry.correct += Number(r.ease > 1);
    entry.time += duration;
    byDeck.set(deck, entry);
    byEase[r.ease - 1]++;
    studied.add(r.card_id);
    active.add(day);
  }
  return {
    count,
    correct,
    time,
    averageMs: count ? time / count : 0,
    activeDays: active.size,
    uniqueCards: studied.size,
    byEase,
    decks: [...byDeck.values()].sort(
      (a, b) => b.time - a.time || a.deck.localeCompare(b.deck, "ja"),
    ),
  };
}

// Shift a wall calendar date rather than elapsed milliseconds (safe across DST).
function shiftDay(day, offset) {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}
const daysBetween = (a, b) =>
  Math.round((Date.parse(b) - Date.parse(a)) / 86400000);
const ratio = (correct, count) => (count ? correct / count : null);
function distribution(values) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b),
    bins = new Map();
  for (const value of sorted) bins.set(value, (bins.get(value) || 0) + 1);
  const n = sorted.length;
  return {
    count: n,
    median: n
      ? (sorted[Math.floor((n - 1) / 2)] + sorted[Math.floor(n / 2)]) / 2
      : null,
    bins: [...bins].map(([value, count]) => ({ value, count })),
  };
}

/** Anki-style statistics from optional schema-1 scheduling fields.
 * Counts are answer events, times milliseconds, rates fractions/null, intervals
 * days, ease percentages. Calendar/added use YYYY-MM-DD; due bins use day offsets.
 * No historical interval or scheduling state is inferred from today's card state.
 * Calendar contains all available history; reviews/hourly/buttons/added use days.
 */
export function ankiStatistics(
  snapshot,
  {
    days = 30,
    timezone = snapshot?.source?.timezone || "Asia/Tokyo",
    now = new Date(),
    decks = [],
    includeSubdecks = false,
    rolloverHour = snapshot?.source?.rollover_hour ?? 4,
  } = {},
) {
  const cards = filterCards(snapshot?.cards || [], { decks, includeSubdecks });
  const scoped = {
    ...snapshot,
    cards,
    orphan_reviews: decks.length ? [] : snapshot?.orphan_reviews,
  };
  const until = new Date(now).valueOf(),
    todayKey = dayKey(now, timezone, rolloverHour);
  const first = days > 0 ? shiftDay(todayKey, 1 - days) : null;
  const calendarMap = new Map(),
    period = [],
    all = [];
  const hourly = Array.from({ length: 24 }, (_, hour) => ({
    hour,
    count: 0,
    correct: 0,
    rate: null,
  }));
  const hourFormat = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    hour: "2-digit",
    hourCycle: "h23",
  });
  const answerButtons = {
    learn: [0, 0, 0, 0],
    young: [0, 0, 0, 0],
    mature: [0, 0, 0, 0],
  };
  const blank = (day) => ({
    day,
    count: 0,
    correct: 0,
    time: 0,
    learn: 0,
    young: 0,
    mature: 0,
    relearn: 0,
    filtered: 0,
  });
  for (const review of studyReviews(scoped)) {
    if (review.id > until) continue;
    const day = dayKey(review.id, timezone, rolloverHour),
      correct = Number(review.ease > 1);
    const row = calendarMap.get(day) || blank(day);
    row.count++;
    row.correct += correct;
    row.time += Math.max(0, review.time_ms || 0);
    // Review maturity is based on the interval BEFORE answering, never card.interval.
    const group =
      review.type === 0
        ? "learn"
        : review.type === 2
          ? "relearn"
          : review.type === 3
            ? "filtered"
            : review.last_interval >= 21
              ? "mature"
              : "young";
    row[group]++;
    calendarMap.set(day, row);
    all.push({ ...review, day });
    if (first && day < first) continue;
    period.push({ ...review, day });
    const hour = Number(hourFormat.format(new Date(review.id)));
    if (review.type !== 3) {
      hourly[hour].count++;
      hourly[hour].correct += correct;
    }
    const buttonGroup =
      review.type !== 1
        ? "learn"
        : review.last_interval >= 21
          ? "mature"
          : "young";
    answerButtons[buttonGroup][review.ease - 1]++;
  }
  for (const row of hourly) row.rate = ratio(row.correct, row.count);
  const calendar = [...calendarMap.values()].sort((a, b) =>
    a.day.localeCompare(b.day),
  );
  const reviewDays =
    days > 0
      ? days
      : calendar.length
        ? daysBetween(calendar[0].day, todayKey) + 1
        : 0;
  const bins =
    days > 0
      ? Array.from(
          { length: days },
          (_, i) =>
            calendarMap.get(shiftDay(first, i)) || blank(shiftDay(first, i)),
        )
      : calendar;
  const reviews = {
    count: period.length,
    correct: period.filter((r) => r.ease > 1).length,
    time: period.reduce((sum, r) => sum + Math.max(0, r.time_ms || 0), 0),
    activeDays: new Set(period.map((r) => r.day)).size,
    days: reviewDays,
    bins,
  };
  reviews.averagePerDay = reviewDays ? reviews.count / reviewDays : 0;
  reviews.averagePerActiveDay = reviews.activeDays
    ? reviews.count / reviews.activeDays
    : 0;
  const todayEvents = all.filter((r) => r.day === todayKey);
  const today = {
    ...(calendarMap.get(todayKey) || blank(todayKey)),
    uniqueCards: new Set(todayEvents.map((r) => r.card_id)).size,
    again: todayEvents.filter((r) => r.ease === 1).length,
  };
  const cardCounts = {
    new: 0,
    learn: 0,
    relearn: 0,
    young: 0,
    mature: 0,
    suspended: 0,
    buried: 0,
    unknown: 0,
    total: cards.length,
  };
  const due = new Map(),
    addedMap = new Map(),
    workloadIntervals = new Map();
  for (const card of cards) {
    const state =
      card.queue === -1 || card.suspended
        ? "suspended"
        : card.queue === -2 || card.queue === -3
          ? "buried"
          : card.type === 0
            ? "new"
            : card.type === 1
              ? "learn"
              : card.type === 3
                ? "relearn"
                : card.type === 2
                  ? card.interval >= 21
                    ? "mature"
                    : "young"
                  : "unknown";
    cardCounts[state]++;
    if (
      Number.isInteger(card.queue) &&
      card.queue !== -1 &&
      [1, 2, 3].includes(card.type)
    ) {
      const interval = Math.max(1, card.interval || 0);
      workloadIntervals.set(
        interval,
        (workloadIntervals.get(interval) || 0) + 1,
      );
      if (card.due_date) {
        const day = card.queue === 1 ? 0 : daysBetween(todayKey, card.due_date);
        due.set(day, (due.get(day) || 0) + 1);
      }
    }
    const added = card.added_at;
    if (Number.isFinite(added) && added <= until) {
      const day = dayKey(added, timezone, rolloverHour);
      if (!first || day >= first)
        addedMap.set(day, (addedMap.get(day) || 0) + 1);
    }
  }
  const dueBins = [...due]
    .sort(([a], [b]) => a - b)
    .map(([day, count]) => ({ day, count }));
  const totalDue = dueBins.reduce((s, r) => s + r.count, 0);
  const futureDue = {
    bins: dueBins,
    overdue: dueBins.filter((r) => r.day < 0).reduce((s, r) => s + r.count, 0),
    tomorrow: due.get(1) || 0,
    total: totalDue,
    average: totalDue
      ? totalDue / (Math.max(0, ...due.keys()) - Math.min(0, ...due.keys()) + 1)
      : 0,
    // Anki reports an integer daily load. Aggregate equal intervals first to
    // avoid repeated-addition rounding (ten cards / ten days is exactly one).
    workload: Math.trunc(
      [...workloadIntervals].reduce(
        (sum, [interval, count]) => sum + count / interval,
        0,
      ),
    ),
  };
  const retention = [
    ["today", 1],
    ["yesterday", -1],
    ["week", 7],
    ["month", 31],
    ["year", 365],
    ["all", 0],
  ].map(([period, length]) => {
    const start =
      length === -1
        ? shiftDay(todayKey, -1)
        : length
          ? shiftDay(todayKey, 1 - length)
          : null;
    const eligible = all.filter(
      (r) =>
        Number.isFinite(r.last_interval) &&
        (r.type === 1 || r.last_interval >= 1 || r.last_interval <= -86400) &&
        (!start || r.day >= start) &&
        (length !== -1 || r.day === start),
    );
    const aggregate = (items) => {
      const count = items.length,
        correct = items.filter((r) => r.ease > 1).length;
      return { count, correct, rate: ratio(correct, count) };
    };
    return {
      period,
      young: aggregate(eligible.filter((r) => r.last_interval < 21)),
      mature: aggregate(eligible.filter((r) => r.last_interval >= 21)),
      all: aggregate(eligible),
    };
  });
  const reviewCards = cards.filter((c) => c.type === 2 || c.type === 3);
  const easeValues = reviewCards
    .filter((c) => Number.isFinite(c.ease_factor))
    .map((c) => c.ease_factor / 10);
  return {
    timezone,
    rolloverHour,
    today,
    futureDue,
    calendar,
    reviews,
    cardCounts,
    intervals: distribution(reviewCards.map((c) => c.interval)),
    ease: {
      ...distribution(easeValues.map(Math.floor)),
      average: easeValues.length
        ? easeValues.reduce((sum, value) => sum + value, 0) / easeValues.length
        : null,
    },
    retention,
    hourly,
    answerButtons,
    added: [...addedMap]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([day, count]) => ({ day, count })),
    fsrs: {
      stability: distribution(cards.map((c) => c.stability)),
      difficulty: distribution(cards.map((c) => c.difficulty)),
      retrievability: distribution(
        cards
          .filter((c) => Number.isFinite(c.retrievability))
          .map((c) => c.retrievability * 100),
      ),
    },
    availability: {
      scheduling:
        cards.length > 0 &&
        cards.every(
          (c) => Number.isInteger(c.type) && Number.isInteger(c.queue),
        ),
      previousIntervals:
        all.length > 0 && all.every((r) => Number.isFinite(r.last_interval)),
      dueDates: cards.some((c) => Boolean(c.due_date)),
      nativeGraphs: Boolean(snapshot?.native_statistics),
      orphanReviews: snapshot?.source?.orphan_review_count || 0,
      collectionReviews: snapshot?.source?.collection_review_count ?? null,
      historyScope: snapshot?.source?.history_scope || "included_cards",
    },
  };
}
