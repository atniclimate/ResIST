/* Data layer for the Analysis mockup. Loads ../data/aggregates.json (every figure the build counted) and rows.json
   (the per-resolution rows the lists and the cross-tabs need, from the same ledger run). Where a selection can be
   read straight from aggregates.json, it is; the rows are used for cross-tabs the aggregates do not carry, and
   selfTest() proves that the two agree wherever both can answer. */
import { esc, fmt } from "./charts.js";

export const KINDS = [
  { key: "winter", label: "Winter" },
  { key: "midyear", label: "Mid-Year" },
  { key: "annual", label: "Annual" },
  { key: "executive", label: "Executive Board" },
];
export const KIND_LABEL = Object.fromEntries(KINDS.map(k => [k.key, k.label]));
export const ERAS = [
  { id: "e1", label: "2000 to 2006", y0: 2000, y1: 2006 },
  { id: "e2", label: "2007 to 2012", y0: 2007, y1: 2012 },
  { id: "e3", label: "2013 to 2018", y0: 2013, y1: 2018 },
  { id: "e4", label: "2019 to 2026", y0: 2019, y1: 2026 },
  { id: "w1", label: "Wyatt's 2005 to 2014", y0: 2005, y1: 2014 },
  { id: "w2", label: "Wyatt's 2015 to 2024", y0: 2015, y1: 2024 },
  { id: "w3", label: "Wyatt's 2025", y0: 2025, y1: 2025 },
];
export const OUTCOME_LABEL = { adopted: "Yes (adopted)", not_adopted: "No (not adopted)", tabled: "Tabled" };
export const NCAI_LABEL = { yes: "Yes", no: "No", na: "n/a" };

export const D = { agg: null, rows: [], years: [], builtAt: "", yi: new Map() };

const memos = new Map();
const memo = (key, fn) => { if (!memos.has(key)) memos.set(key, fn()); return memos.get(key); };

const pad2 = n => String(n).padStart(2, "0");
export function usDate(d) { return d instanceof Date && !Number.isNaN(d.getTime()) ? `${pad2(d.getMonth() + 1)}/${pad2(d.getDate())}/${d.getFullYear()}` : ""; }

/* ---------------------------------------------------------------------------------------------------------- */
/* titles and words                                                                                            */
const STOP = new Set("a an and as at be by for from in is it of on or that the this to with".split(" "));
export function titleText(r) { return r.t ? r.t.replace(/_/g, " ").replace(/\s+/g, " ").trim() : null; }
export function tokenize(text) {
  return (text || "").toLowerCase().replace(/_/g, " ").match(/[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*/gu) || [];
}
const indexed = w => !STOP.has(w) && (w.length > 1 || /\d/.test(w));

export async function load() {
  const [a, r] = await Promise.all([fetch("../data/aggregates.json"), fetch("rows.json")]);
  if (!a.ok || !r.ok) throw new Error("The counts did not load.");
  const lm = a.headers.get("last-modified");
  D.builtAt = lm ? usDate(new Date(lm)) : "";
  const abuf = await a.arrayBuffer();
  D.agg = JSON.parse(new TextDecoder().decode(abuf));
  D.aggSha = "";
  try { D.aggSha = [...new Uint8Array(await crypto.subtle.digest("SHA-256", abuf))].map(b => b.toString(16).padStart(2, "0")).join(""); } catch { /* not a secure context */ }
  D.rows = (await r.json()).rows;
  D.years = D.agg.meta.years;
  D.years.forEach((y, i) => D.yi.set(y, i));
  D.yMin = D.years[0]; D.yMax = D.years[D.years.length - 1];
  D.total = D.agg.meta.counts.resolutions_listed;
  D.cm = Object.fromEntries(D.agg.committees.map(c => [c.key, c]));
  D.cmList = [...D.agg.committees].sort((a, b) => a.name.localeCompare(b.name));
  D.persons = new Map(D.agg.preparers.map((p, i) => [p.key, { ...p, idx: i }]));
  D.byNumber = new Map(D.rows.map(r => [r.n, r]));
  D.byId = new Map(D.rows.map(r => [r.id, r]));
  for (const r of D.rows) {
    const words = tokenize(r.t);
    r._w = new Set(words.filter(indexed));
    r._ph = new Set();
    for (let i = 0; i + 1 < words.length; i++) if (indexed(words[i]) && indexed(words[i + 1])) r._ph.add(`${words[i]} ${words[i + 1]}`);
    r._first = words[0] || "";
  }
  D.siteOnly = new Map(D.agg.site_coverage_by_year.years.map(s => [s.year, s.site_only]));
  return D;
}

/* ---------------------------------------------------------------------------------------------------------- */
/* selections                                                                                                  */
export const layerOf = (r, c) => (r.ck === c ? "c" : r.ck == null && r.pk.includes(c) ? "w" : null);
export const selects = (r, k, c) => (!k || r.k === k) && (!c || layerOf(r, c) !== null);

/* Year by convention kind. With a committee chosen, the rows count; otherwise aggregates.json answers. */
export function kindMatrix(c) {
  return memo("km:" + c, () => {
    if (!c) return D.agg.year_by_kind.map(r => ({ year: r.year, winter: r.winter, midyear: r.midyear, annual: r.annual, executive: r.executive, none: r.none, wait: 0, wk: {}, total: r.total }));
    const m = new Map(D.years.map(y => [y, { year: y, winter: 0, midyear: 0, annual: 0, executive: 0, none: 0, wait: 0, wk: { winter: 0, midyear: 0, annual: 0, executive: 0, none: 0 }, total: 0 }]));
    for (const r of D.rows) {
      const lay = layerOf(r, c);
      if (!lay) continue;
      const o = m.get(r.y);
      if (lay === "c") o[r.k || "none"]++; else { o.wait++; o.wk[r.k || "none"]++; }
      o.total++;
    }
    return [...m.values()];
  });
}

/* Committee by year, confirmed (applied) and waiting (proposed) parts, optionally within one convention kind. */
export function commMatrix(kind) {
  return memo("cmx:" + kind, () => {
    const cells = new Map(); // key -> Map(year -> [c, w])
    const blank = new Map(), other = new Map();
    const put = (key, y, i, v) => { if (!cells.has(key)) cells.set(key, new Map()); const m = cells.get(key); if (!m.has(y)) m.set(y, [0, 0]); m.get(y)[i] += v; };
    if (!kind) {
      const a = D.agg.year_by_committee, p = D.agg.year_by_committee_proposed;
      D.years.forEach((y, i) => {
        for (const k of Object.keys(a.committees)) put(k, y, 0, a.committees[k][i]);
        for (const k of Object.keys(p.committees)) put(k, y, 1, p.committees[k][i]);
        const cov = D.agg.coverage_by_year.years[i];
        const b = cov.resolutions - cov.with_committee_written;
        blank.set(y, b); other.set(y, a.none[i] - b - p.resolutions_with_proposed_only[i]);
      });
    } else {
      for (const y of D.years) { blank.set(y, 0); other.set(y, 0); }
      for (const r of D.rows) {
        if (r.k !== kind) continue;
        if (r.ck) put(r.ck, r.y, 0, 1);
        else if (r.pk.length) for (const k of r.pk) put(k, r.y, 1, 1);
        else if (!r.cl) blank.set(r.y, blank.get(r.y) + 1);
        else other.set(r.y, other.get(r.y) + 1);
      }
    }
    return { cells, blank, other, get: (k, y) => (cells.get(k) && cells.get(k).get(y)) || [0, 0] };
  });
}

/* Fields that can be blank, with their presence test on a row and their column in aggregates.json. */
export const FIELDS = {
  title: { agg: "with_title", row: r => !!r.t, name: "Title", rec: "Title recorded" },
  committee: { agg: "with_committee_written", row: r => !!r.cl, name: "Committee as written", rec: "Committee recorded" },
  committeeConfirmed: { agg: "with_committee_applied", row: r => !!r.ck, name: "Committee confirmed", rec: "Committee confirmed" },
  preparer: { agg: "with_preparer", row: r => !!r.pb, name: "Prepared By", rec: "Prepared By recorded" },
  convention: { agg: "with_session", row: r => !!r.k, name: "Convention", rec: "Convention recorded" },
  outcome: { agg: "with_outcome", row: r => !!r.o, name: "Outcome", rec: "Outcome recorded" },
  ncai: { agg: "with_to_ncai", row: r => !!r.nc, name: "TO NCAI", rec: "TO NCAI recorded" },
  permalink: { agg: "with_permalink", row: r => !!r.u, name: "Permalink", rec: "Permalink recorded" },
  site: { agg: "with_site", row: r => !!r.s, name: "Text on this site", rec: "Text on this site" },
};

/* Per year {year, n, total} for one field under the filter. */
export function covMatrix(field, k, c) {
  return memo(`cov:${field}:${k}:${c}`, () => {
    const F = FIELDS[field];
    if (!k && !c) return D.agg.coverage_by_year.years.map(r => ({ year: r.year, n: r[F.agg], total: r.resolutions }));
    const m = new Map(D.years.map(y => [y, { year: y, n: 0, total: 0 }]));
    for (const r of D.rows) if (selects(r, k, c)) { const o = m.get(r.y); o.total++; if (F.row(r)) o.n++; }
    return [...m.values()];
  });
}

/* Outcome and TO NCAI by year. */
export function outcomeMatrix(k, c) {
  return memo(`out:${k}:${c}`, () => {
    if (!k && !c) return D.agg.outcome_by_year;
    const m = new Map(D.years.map(y => [y, { year: y, resolutions: 0, recorded: 0, not_recorded: 0, adopted: 0, not_adopted: 0, tabled: 0 }]));
    for (const r of D.rows) if (selects(r, k, c)) { const o = m.get(r.y); o.resolutions++; if (r.o) { o.recorded++; o[r.o]++; } else o.not_recorded++; }
    return [...m.values()];
  });
}
export function ncaiMatrix(k, c) {
  return memo(`nc:${k}:${c}`, () => {
    if (!k && !c) return D.agg.to_ncai_by_year;
    const m = new Map(D.years.map(y => [y, { year: y, resolutions: 0, recorded: 0, not_recorded: 0, yes: 0, no: 0, na: 0 }]));
    for (const r of D.rows) if (selects(r, k, c)) { const o = m.get(r.y); o.resolutions++; if (r.nc) { o.recorded++; o[r.nc]++; } else o.not_recorded++; }
    return [...m.values()];
  });
}

export const inRange = (y, f) => y >= f.y0 && y <= f.y1;
export const sumBy = (arr, f, pick) => arr.reduce((s, r) => s + (inRange(r.year, f) ? pick(r) : 0), 0);

/* ---------------------------------------------------------------------------------------------------------- */
/* list specs: a selection written as a query string, so a link carries everything the count counted          */
export const parseSpec = s => Object.fromEntries(new URLSearchParams(s || ""));
export const makeSpec = o => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== "" && v != null).map(([k, v]) => [k, String(v)])).toString();

export function matchSpec(r, s) {
  if (s.y && r.y !== +s.y) return false;
  if (s.y0 && r.y < +s.y0) return false;
  if (s.y1 && r.y > +s.y1) return false;
  if (s.k) { if (s.k === "none" ? r.k !== null : r.k !== s.k) return false; }
  if (s.c) {
    const lay = layerOf(r, s.c), want = s.ly || "c";
    if (want === "b" ? !lay : lay !== want) return false;
  }
  if (s.cn) {
    const blank = !r.cl, nameless = !r.ck && !r.pk.length;
    if (s.cn === "blank" ? !(blank) : s.cn === "other" ? !(r.cl && nameless) : !nameless) return false;
  }
  if (s.lab != null && s.lab !== "" && r.cl !== s.lab) return false;
  if (s.o) {
    if (s.o === "rec" ? !r.o : s.o === "norec" ? !!r.o : s.o === "notadopted" ? !(r.o === "not_adopted" || r.o === "tabled") : r.o !== s.o) return false;
  }
  if (s.nc) { if (s.nc === "rec" ? !r.nc : s.nc === "norec" ? !!r.nc : r.nc !== s.nc) return false; }
  if (s.has && !FIELDS[s.has].row(r)) return false;
  if (s.hasnt && FIELDS[s.hasnt].row(r)) return false;
  if (s.p && !r.pp.includes(s.p)) return false;
  if (s.p2 && !r.pp.includes(s.p2)) return false;
  if (s.w && !tokenize(s.w).every(t => r._w.has(t))) return false;
  if (s.ph && !r._ph.has(s.ph)) return false;
  if (s.fw && r._first !== s.fw) return false;
  if (s.nums && !s.nums.split(";").includes(r.n)) return false;
  if (s.ys && !s.ys.split(",").includes(String(r.y))) return false;
  if (s.site === "linked" ? !r.s : s.site === "unlinked" ? !!r.s : false) return false;
  return true;
}
export const rowsFor = s => D.rows.filter(r => matchSpec(r, s));

/* The selection in words: "Health, 2023" or "Winter 2003". */
export function describe(s) {
  const bits = [];
  if (s.c) bits.push(`${D.cm[s.c]?.name ?? s.c}${s.ly === "w" ? ", labels waiting for ATNI" : s.ly === "b" ? ", confirmed and waiting" : ""}`);
  if (s.cn) bits.push(s.cn === "blank" ? "Committee cell blank" : s.cn === "other" ? "Committee cell names no committee" : "Names no committee");
  if (s.lab) bits.push(`Committee label “${s.lab}” as written`);
  if (s.p) bits.push(`Prepared By names ${D.persons.get(s.p)?.name ?? s.p}${s.p2 ? ` and ${D.persons.get(s.p2)?.name ?? s.p2}` : ""}`);
  if (s.w) bits.push(`Title has “${s.w}”`);
  if (s.ph) bits.push(`Title has the words “${s.ph}”`);
  if (s.fw) bits.push(`Title begins with “${s.fw}”`);
  if (s.nc) bits.push(s.nc === "rec" ? "TO NCAI recorded" : s.nc === "norec" ? "TO NCAI not recorded" : `TO NCAI ${NCAI_LABEL[s.nc]}`);
  if (s.o) bits.push(s.o === "rec" ? "Outcome recorded" : s.o === "norec" ? "Outcome not recorded" : s.o === "notadopted" ? "Recorded as not adopted or tabled" : `Outcome recorded as ${OUTCOME_LABEL[s.o]}`);
  if (s.has) bits.push(`${FIELDS[s.has].name} recorded`);
  if (s.hasnt) bits.push(`${FIELDS[s.hasnt].name} not recorded`);
  if (s.site) bits.push(s.site === "linked" ? "Text on this site" : "No text on this site");
  if (s.nums) bits.push(`Numbers ${s.nums.split(";").join(", ")}`);
  if (s.ys) bits.push("in years where it is recorded on every resolution");
  const kind = s.k ? (s.k === "none" ? "No convention recorded" : KIND_LABEL[s.k]) : "";
  const yr = s.y ? s.y : s.y0 && s.y1 ? (s.y0 === s.y1 ? s.y0 : `${s.y0} to ${s.y1}`) : "";
  if (kind && yr && !bits.length) return `${kind} ${yr}`;
  if (kind) { if (s.ys) bits.unshift(kind); else bits.push(kind); }
  if (yr) bits.push(String(yr));
  return bits.length ? bits.join(", ") : "All resolutions";
}

/* ---------------------------------------------------------------------------------------------------------- */
/* people                                                                                                      */
export const personRows = key => memo("pr:" + key, () => D.rows.filter(r => r.pp.includes(key)));
export function personKinds(key) {
  const c = { winter: 0, midyear: 0, annual: 0, executive: 0, none: 0 };
  for (const r of personRows(key)) c[r.k || "none"]++;
  return c;
}
export function personWithSite(key) { return personRows(key).filter(r => r.s).length; }
export function coPartners(key) {
  return D.agg.co_preparation.filter(p => p.a === key || p.b === key);
}

/* ---------------------------------------------------------------------------------------------------------- */
/* words, phrases, first words, repeated titles                                                                */
export function wordIndex() {
  return memo("wi", () => {
    const words = new Map(), phrases = new Map();
    for (const r of D.rows) {
      for (const w of r._w) words.set(w, (words.get(w) || 0) + 1);
      for (const p of r._ph) phrases.set(p, (phrases.get(p) || 0) + 1);
    }
    return { words, phrases, distinct: words.size };
  });
}
export const BANDS = [[2000, 2006], [2007, 2012], [2013, 2018], [2019, 2026]];
export function firstWords(min = 25) {
  return memo("fw" + min, () => {
    const m = new Map();
    for (const r of D.rows) {
      if (!r._first) continue;
      if (!m.has(r._first)) m.set(r._first, [0, 0, 0, 0]);
      const b = BANDS.findIndex(([a, z]) => r.y >= a && r.y <= z);
      m.get(r._first)[b]++;
    }
    return [...m.entries()].map(([w, c]) => ({ w, c, total: c.reduce((a, b) => a + b, 0) })).filter(x => x.total >= min).sort((a, b) => b.total - a.total || a.w.localeCompare(b.w));
  });
}

/* Titles that share most of their words: at least 3 shared indexed words and at least three quarters of the words
   they use between them (Jaccard 0.75), joined into groups. Counting only; nothing is named or merged. */
export function similarGroups() {
  return memo("sim", () => {
    const rows = D.rows.filter(r => r._w.size >= 3);
    const inv = new Map();
    rows.forEach((r, i) => { for (const w of r._w) { if (!inv.has(w)) inv.set(w, []); inv.get(w).push(i); } });
    const parent = rows.map((_, i) => i);
    const find = i => (parent[i] === i ? i : (parent[i] = find(parent[i])));
    let pairs = 0;
    rows.forEach((r, i) => {
      const cnt = new Map();
      for (const w of r._w) { const l = inv.get(w); if (l.length > 60) continue; for (const j of l) if (j > i) cnt.set(j, (cnt.get(j) || 0) + 1); }
      for (const [j, shared] of cnt) {
        if (shared < 3) continue;
        const union = r._w.size + rows[j]._w.size - shared;
        if (shared / union >= 0.75) { pairs++; parent[find(j)] = find(i); }
      }
    });
    const groups = new Map();
    rows.forEach((r, i) => { const root = find(i); if (!groups.has(root)) groups.set(root, []); groups.get(root).push(r); });
    const out = [...groups.values()].filter(g => g.length > 1).map(g => g.sort((a, b) => a.y - b.y || a.n.localeCompare(b.n)));
    out.sort((a, b) => a[0].y - b[0].y || a[0].n.localeCompare(b[0].n));
    return { groups: out, pairs };
  });
}

/* ---------------------------------------------------------------------------------------------------------- */
/* a proof that the rows and aggregates.json agree wherever both answer                                        */
export function selfTest() {
  const res = [];
  const ok = (name, pass, detail = "") => res.push({ name, pass: !!pass, detail });
  const A = D.agg;
  ok("rows count = resolutions_listed", D.rows.length === A.meta.counts.resolutions_listed, `${D.rows.length}`);
  const byY = new Map(); for (const r of D.rows) byY.set(r.y, (byY.get(r.y) || 0) + 1);
  ok("rows per year = year_by_kind totals", A.year_by_kind.every(r => byY.get(r.year) === r.total));
  let kindOk = true;
  for (const r of A.year_by_kind) for (const k of ["winter", "midyear", "annual", "executive"]) {
    if (D.rows.filter(x => x.y === r.year && x.k === k).length !== r[k]) kindOk = false;
  }
  ok("rows per year and kind = year_by_kind", kindOk);
  let commOk = true;
  const cm = commMatrix("");
  const rowsC = commMatrix.bind(null);
  for (const k of Object.keys(A.year_by_committee.committees)) D.years.forEach((y, i) => {
    if (D.rows.filter(x => x.y === y && x.ck === k).length !== A.year_by_committee.committees[k][i]) commOk = false;
  });
  for (const k of Object.keys(A.year_by_committee_proposed.committees)) D.years.forEach((y, i) => {
    if (D.rows.filter(x => x.y === y && !x.ck && x.pk.includes(k)).length !== A.year_by_committee_proposed.committees[k][i]) commOk = false;
  });
  ok("rows per committee, year and layer = year_by_committee (applied and proposed)", commOk);
  let covOk = true;
  for (const f of Object.keys(FIELDS)) {
    const a = covMatrix(f, "", "");
    for (const r of a) if (D.rows.filter(x => x.y === r.year && FIELDS[f].row(x)).length !== r.n) covOk = false;
  }
  ok("rows per field and year = coverage_by_year", covOk);
  const out = A.outcome_by_year.every(r => D.rows.filter(x => x.y === r.year && x.o === "adopted").length === r.adopted
    && D.rows.filter(x => x.y === r.year && x.o === "not_adopted").length === r.not_adopted && D.rows.filter(x => x.y === r.year && x.o === "tabled").length === r.tabled);
  ok("rows per outcome and year = outcome_by_year", out);
  const nc = A.to_ncai_by_year.every(r => ["yes", "no", "na"].every(v => D.rows.filter(x => x.y === r.year && x.nc === v).length === r[v]));
  ok("rows per TO NCAI value and year = to_ncai_by_year", nc);
  ok("rows linked to the site = 1,066", D.rows.filter(r => r.s).length === A.meta.counts.linked_to_site);
  ok("preparers: rows naming each person = preparers[].total", A.preparers.every(p => personRows(p.key).length === p.total));
  ok("readoption members found among the rows", A.readoptions.groups.every(g => g.members.every(m => D.byNumber.has(m.number))));
  // a committee-filtered cube equals the sum of its layers
  const hk = kindMatrix("health");
  ok("committee-filtered year totals add to confirmed + waiting", hk.reduce((s, r) => s + r.total, 0) === D.cm.health.total + D.cm.health.proposed_total);
  return res;
}
export { esc, fmt };
