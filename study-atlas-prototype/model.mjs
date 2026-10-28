export const MOCK_SHEETS = ["必勝1", "必勝2", "実戦1", "本レ2", "OP2", "過去問"];
export const SUBJECTS = ["数学", "物理", "化学", "英語", "国語"];
export const TAG_SHEET = "StudyAtlas_分野";
export const TIME_SHEET = "StudyAtlas_勉強時間";
export const quote = s => `'${s.replaceAll("'", "''")}'`;
export const number = x => x === "" || x == null || !Number.isFinite(Number(x)) ? null : Number(x);
export function column(n) { let out = ""; for (n++; n; n = Math.floor((n - 1) / 26)) out = String.fromCharCode(65 + (n - 1) % 26) + out; return out; }
export function parseExam(sheet, values, formulas = values) {
  const header = values[0] || [], result = [];
  for (let c = 0; c < header.length; c++) {
    const subject = String(header[c] || "");
    if (!["英語", "数学", "国語", "物理", "化学"].includes(subject)) continue;
    let end = header.findIndex((v,i) => i > c && ["英語", "数学", "国語", "物理", "化学"].includes(v));
    if (end < 0) end = header.length;
    while (end > c + 1 && !header[end - 1]) end--;
    const names = header.slice(c + 1, end);
    const fields = {score: names.indexOf("点数"), average: names.indexOf("平均"), self: names.findIndex(x => String(x).startsWith("自己")), max: names.indexOf("配点")};
    // Some historical sheets have missing labels in otherwise standard five-column blocks.
    if (end - c === 5 && fields.score < 0) fields.score = 0;
    if (end - c === 5 && fields.average < 0) fields.average = 1;
    if (end - c === 5 && fields.self < 0) fields.self = 2;
    for (let r = 1; r < Math.min(values.length, 20); r++) {
      const label = String(values[r]?.[c] ?? "").trim();
      if (!label || label === "計" || label === "合計") continue;
      const cells = {};
      for (const [key, offset] of Object.entries(fields)) if (offset >= 0) {
        const col = c + offset + 1, raw = formulas[r]?.[col] ?? "", val = values[r]?.[col] ?? "";
        cells[key] = {address: `${column(col)}${r + 1}`, value: val, raw, formula: typeof raw === "string" && raw.startsWith("=")};
      }
      if (cells.max) result.push({sheet, subject, label, cells});
    }
  }
  return result;
}
export function parseTags(rows) {
  const map = new Map();
  for (const row of rows.slice(1)) if (row.length >= 3) map.set(JSON.stringify(row.slice(0,3)), {tags: String(row[3] || "").split(",").map(x => x.trim()).filter(Boolean), date: String(row[4] || "")});
  return map;
}
export const examKey = e => JSON.stringify([e.sheet, e.subject, e.label]);
export function summarizeTopics(exams, tags) {
  const groups = new Map();
  for (const e of exams) {
    const meta = tags.get(examKey(e)); if (!meta) continue;
    const score = number(e.cells.score?.value), max = number(e.cells.max?.value), avg = number(e.cells.average?.value);
    if (score === null || max === null || max <= 0) continue;
    for (const tag of new Set(meta.tags)) {
      const key = `${e.subject} / ${tag}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push({score, max, avg, date: meta.date, exam: e.sheet, question: e.label});
    }
  }
  return [...groups].map(([name, items]) => ({name, items, rate: items.reduce((a,x)=>a+x.score,0) / items.reduce((a,x)=>a+x.max,0), comparison: items.filter(x=>x.avg !== null).map(x=>(x.score-x.avg)/x.max)})).sort((a,b)=>a.rate-b.rate);
}
export function parseTime(rows, legacy = false) {
  return rows.slice(legacy ? 2 : 1).map((r,i)=>({row: i + (legacy ? 3 : 2), date: String(r[0] || ""), hours: SUBJECTS.map((_,j)=>number(r[j+1]))})).filter(r=>r.date);
}
