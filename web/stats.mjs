const dayFormatters = new Map();

export function dayKey(value, timezone = "Asia/Tokyo") {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return null;
  let formatter = dayFormatters.get(timezone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    dayFormatters.set(timezone, formatter);
  }
  const parts = formatter.formatToParts(date);
  const get = (type) => parts.find((p) => p.type === type).value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export function dayRange(days, today, timezone = "Asia/Tokyo") {
  const end = dayKey(today, timezone);
  const anchor = new Date(`${end}T12:00:00Z`);
  return Array.from({ length: days }, (_, i) => {
    const d = new Date(anchor);
    d.setUTCDate(d.getUTCDate() - (days - 1 - i));
    return d.toISOString().slice(0, 10);
  });
}

export function studyReviews(snapshot) {
  const ids = new Set((snapshot?.cards || []).map((c) => c.id));
  return (snapshot?.reviews || []).filter(
    (r) =>
      ids.has(r.card_id) &&
      Number.isFinite(r.id) &&
      r.id > 0 &&
      r.ease >= 1 &&
      r.ease <= 4 &&
      r.type >= 0 &&
      r.type <= 3,
  );
}

export function summarize(
  snapshot,
  { timezone = "Asia/Tokyo", now = new Date() } = {},
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
    const day = dayKey(r.id, timezone);
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
  const todayKey = dayKey(now, timezone);
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
  { tag = "", deck = "", query = "", sort = "default" } = {},
  byCard = new Map(),
) {
  const q = query.trim().toLocaleLowerCase();
  const selected = cards.filter(
    (c) =>
      (!tag || (tag === "タグなし" ? !c.tags.length : c.tags.includes(tag))) &&
      (!deck || c.deck === deck) &&
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

export function percent(correct, count) {
  return count ? `${Math.round((correct / count) * 100)}%` : "—";
}
export function minutes(ms) {
  return Math.round((ms / 60000) * 10) / 10;
}
