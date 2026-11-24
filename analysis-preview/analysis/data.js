/* Data layer for the Analysis preview. Loads ../data/aggregates.json (schema resist-analysis/2: every figure the build
   counted and recounted) and ../data/rows.json (schema resist-analysis-rows/2: one row per listed resolution). Where a
   selection can be read straight from aggregates.json, it is; the rows answer the cross-tabs the aggregates do not
   carry, and selfTest() proves that the two agree wherever both can answer. Every number on the page is read from
   these two files; none is typed into the code.

   @typedef {Object} Row   one resolution, rows.json (design 2.9)
   @property {string} id  @property {string} n  @property {number} y  @property {string|null} t  @property {"likely"|"open"|null} tb  @property {string|null} tw
   @property {string|null} cl  @property {Array<[string,"r"|"l"]>} cs  @property {string|null} k  @property {"likely"|"open"|null} kb  @property {string|null} cv
   @property {string|null} og  @property {"r"|"l"|"o"|null} ogb  @property {string|null} o  @property {"likely"|"open"|null} ob
   @property {string|null} nc  @property {"open"|null} nb  @property {string|null} pb  @property {Array<[string,"r"|"l",string]>} pp
   @property {Array<[string,"o"]>} po  @property {Array<[string,string,string|null]>} nm  @property {"likely"|null} ib
   @property {string|null} u  @property {number|null} s  @property {string|null} rk  @property {"likely"|null} sb      */
import { esc, fmt } from "./charts.js";

export const KINDS = [
  { key: "winter", label: "Winter" },
  { key: "midyear", label: "Mid-Year" },
  { key: "annual", label: "Annual" },
  { key: "executive", label: "Executive Board" },
  { key: "special", label: "Special" },
];
export const KIND_LABEL = Object.fromEntries(KINDS.map(k => [k.key, k.label]));
export const ALL_KINDS = [...KINDS.map(k => k.key), "none"];
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
export const ORIGIN_LABEL = { floor: "From the floor", executive_board: "Executive Board", general_assembly: "General Assembly", steering_committee: "Steering Committee" };
export const KIND_OF_COMMITTEE = { committee: "A committee", subcommittee_or_topic: "A sub-committee or subject label" };

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

/** @returns {Promise<typeof D>} */
export async function load() {
  const [a, r] = await Promise.all([fetch("../data/aggregates.json"), fetch("../data/rows.json")]);
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
  D.persons = new Map(D.agg.people.map((p, i) => [p.key, { ...p, idx: i }]));
  D.byNumber = new Map(D.rows.map(r => [r.n, r]));
  D.byId = new Map(D.rows.map(r => [r.id, r]));
  for (const r of D.rows) {
    const words = tokenize(r.t);
    r._w = new Set(words.filter(indexed));
    r._ph = new Set();
    for (let i = 0; i + 1 < words.length; i++) if (indexed(words[i]) && indexed(words[i + 1])) r._ph.add(`${words[i]} ${words[i + 1]}`);
    r._first = words[0] || "";
    r._pk = [...new Set(r.pp.map(p => p[0]))];
  }
  D.siteOnly = new Map(D.agg.years.map(s => [s.year, s.site_only]));
  const linkedYears = D.agg.site_coverage_by_year.years.filter(s => s.linked > 0).map(s => s.year);
  D.siteFirstYear = linkedYears.length ? Math.min(...linkedYears) : null;
  const pc = D.agg.places.counts;
  D.conventions = pc.conventions ? pc.conventions.sessions : pc.sessions - pc.not_applicable;   // sessions that are not Executive Board action groups, from the file
  return D;
}

/* ---------------------------------------------------------------------------------------------------------- */
/* selections                                                                                                  */
/** "c" when the row has a recorded link to the committee, "l" when it has only likely links, else null. With `ru`, the
 *  committee's sub-committees count as the committee. */
export function layerOf(r, c, ru = false) {
  let l = null;
  const kids = ru && D.cm[c] ? D.cm[c].children : null;
  for (const [k, b] of r.cs) {
    if (k === c || (kids && kids.includes(k))) { if (b === "r") return "c"; l = "l"; }
  }
  return l;
}
const kindOK = (r, k) => !k || (k === "none" ? r.k === null : r.k === k);
export const selects = (r, k, c) => kindOK(r, k) && (!c || layerOf(r, c) !== null);

/** The marks a row carries: whether any of its values is likely, or open. */
export function marksOf(r) {
  const likely = r.tb === "likely" || r.kb === "likely" || r.ogb === "l" || r.ob === "likely" || r.ib === "likely" || r.sb === "likely"
    || r.cs.some(x => x[1] === "l") || r.pp.some(x => x[1] === "l");
  const open = r.tb === "open" || r.kb === "open" || r.ogb === "o" || r.ob === "open" || r.nb === "open" || r.po.length > 0;
  return { likely, open };
}

const blankKinds = () => Object.fromEntries(ALL_KINDS.map(k => [k, 0]));

/** Year by convention kind, for one committee or for all. Per year: s (recorded layer), l (likely layer), kl (rows in
 *  the recorded layer whose convention is itself likely). Without a committee the likely layer is the inclusion that is
 *  likely (Q21); with one it is the committee link. */
export function kindMatrix(c) {
  return memo("km:" + c, () => {
    const m = new Map(D.years.map(y => [y, { year: y, s: blankKinds(), l: blankKinds(), kl: blankKinds(), sT: 0, lT: 0, klT: 0 }]));
    for (const r of D.rows) {
      const lay = c ? layerOf(r, c) : (r.ib === "likely" ? "l" : "c");
      if (!lay) continue;
      const o = m.get(r.y), kk = r.k || "none";
      if (lay === "c") { o.s[kk]++; o.sT++; if (r.kb === "likely") { o.kl[kk]++; o.klT++; } } else { o.l[kk]++; o.lT++; }
    }
    return [...m.values()];
  });
}

/** Committee by year: get(key, year) is [recorded, likely]. With no convention filter and no roll-up it is
 *  committee_years.cells itself; otherwise the rows are counted. `ru` counts a parent with its sub-committees: the
 *  distinct resolutions linked to either, recorded if any link is. */
export function commMatrix(kind, ru = false) {
  return memo(`cmx:${kind}:${ru}`, () => {
    const cy = D.agg.committee_years;
    const cells = new Map(), blank = new Map(), other = new Map();
    if (!kind) {
      for (const k of Object.keys(cy.cells)) cells.set(k, (ru && cy.rollup[k]) ? cy.rollup[k] : cy.cells[k]);
      D.years.forEach((y, i) => { blank.set(y, cy.blank[i]); other.set(y, cy.other[i]); });
    } else {
      for (const y of D.years) { blank.set(y, 0); other.set(y, 0); }
      const put = (key, y, i) => { if (!cells.has(key)) cells.set(key, D.years.map(() => [0, 0])); cells.get(key)[D.yi.get(y)][i]++; };
      for (const r of D.rows) {
        if (!kindOK(r, kind)) continue;
        const layer = new Map();
        for (const [k, b] of r.cs) {
          const targets = [k]; if (ru && D.cm[k] && D.cm[k].parent) targets.push(D.cm[k].parent);
          for (const t of targets) { if (b === "r") layer.set(t, 0); else if (!layer.has(t)) layer.set(t, 1); }
        }
        for (const [key, i] of layer) put(key, r.y, i);
        if (!r.cs.length) { if (!r.cl) blank.set(r.y, blank.get(r.y) + 1); else other.set(r.y, other.get(r.y) + 1); }
      }
      for (const k of Object.keys(cy.cells)) if (!cells.has(k)) cells.set(k, D.years.map(() => [0, 0]));
    }
    return { cells, blank, other, get: (k, y) => (cells.get(k) && cells.get(k)[D.yi.get(y)]) || [0, 0] };
  });
}

/* Fields that can be blank, with their presence test on a row and their column in aggregates.json. */
export const FIELDS = {
  title: { agg: "with_title", row: r => (r.tb ? !!r.tw : !!r.t), name: "Title as written", rec: "Title recorded" },
  titleShown: { agg: "with_title_shown", row: r => !!r.t, name: "Title shown", rec: "Title shown" },
  committee: { agg: "with_committee_written", row: r => !!r.cl, name: "Committee as written", rec: "Committee recorded" },
  committeeApplied: { agg: "with_committee_applied", row: r => r.cs.length > 0, name: "A committee applied", rec: "A committee applied" },
  committeeLikely: { agg: "with_committee_likely_only", row: r => r.cs.length > 0 && r.cs.every(x => x[1] === "l"), name: "Committee likely only", rec: "Committee likely only" },
  preparer: { agg: "with_preparer", row: r => !!r.pb, name: "Prepared By", rec: "Prepared By recorded" },
  convention: { agg: "with_session", row: r => !!r.k, name: "Convention", rec: "Convention recorded" },
  origin: { agg: "with_origin", row: r => !!r.og, name: "Origin", rec: "Origin recorded" },
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

/** Outcome by year under the filter: recorded values, with `lk` the likely part of each and `open` the blanks Wyatt is
 *  asked about (inside not_recorded). */
export function outcomeMatrix(k, c) {
  return memo(`out:${k}:${c}`, () => {
    const m = new Map(D.years.map(y => [y, { year: y, resolutions: 0, recorded: 0, not_recorded: 0, adopted: 0, not_adopted: 0, tabled: 0, likely: 0, open: 0, lk: { adopted: 0, not_adopted: 0, tabled: 0 } }]));
    for (const r of D.rows) if (selects(r, k, c)) {
      const o = m.get(r.y); o.resolutions++;
      if (r.o) { o.recorded++; o[r.o]++; if (r.ob === "likely") { o.likely++; o.lk[r.o]++; } } else { o.not_recorded++; if (r.ob === "open") o.open++; }
    }
    return [...m.values()];
  });
}
export function ncaiMatrix(k, c) {
  return memo(`nc:${k}:${c}`, () => {
    const m = new Map(D.years.map(y => [y, { year: y, resolutions: 0, recorded: 0, not_recorded: 0, yes: 0, no: 0, na: 0, open: 0 }]));
    for (const r of D.rows) if (selects(r, k, c)) {
      const o = m.get(r.y); o.resolutions++;
      if (r.nc) { o.recorded++; o[r.nc]++; } else { o.not_recorded++; if (r.nb === "open") o.open++; }
    }
    return [...m.values()];
  });
}

export const inRange = (y, f) => y >= f.y0 && y <= f.y1;
export const sumBy = (arr, f, pick) => arr.reduce((s, r) => s + (inRange(r.year, f) ? pick(r) : 0), 0);

/* ---------------------------------------------------------------------------------------------------------- */
/* list specs: a selection written as a query string, so a link carries everything the count counted          */
export const parseSpec = s => Object.fromEntries(new URLSearchParams(s || ""));
export const makeSpec = o => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== "" && v != null && v !== false).map(([k, v]) => [k, String(v)])).toString();

export function matchSpec(r, s) {
  if (s.y && r.y !== +s.y) return false;
  if (s.y0 && r.y < +s.y0) return false;
  if (s.y1 && r.y > +s.y1) return false;
  if (s.k && !kindOK(r, s.k)) return false;
  if (s.kb && (s.kb === "no" ? !!r.kb : r.kb !== s.kb)) return false;   // "no": the value carries no mark
  if (s.ib && (s.ib === "likely" ? r.ib !== "likely" : r.ib === "likely")) return false;
  if (s.c) {
    const lay = layerOf(r, s.c, s.ru === "1");
    const want = s.ly === "w" ? "l" : (s.ly || "c");   // "w" is the older name of "l"
    if (want === "b" ? !lay : lay !== want) return false;
  }
  if (s.cn) {
    const blank = !r.cl, nameless = r.cs.length === 0;
    if (s.cn === "blank" ? !blank : s.cn === "other" ? !(r.cl && nameless) : !nameless) return false;
  }
  if (s.lab != null && s.lab !== "" && r.cl !== s.lab) return false;
  if (s.o) {
    if (s.o === "rec" ? !r.o : s.o === "norec" ? !!r.o : s.o === "notadopted" ? !(r.o === "not_adopted" || r.o === "tabled") : r.o !== s.o) return false;
  }
  if (s.ob && (s.ob === "no" ? !!r.ob : r.ob !== s.ob)) return false;
  if (s.nc) { if (s.nc === "rec" ? !r.nc : s.nc === "norec" ? !!r.nc : r.nc !== s.nc) return false; }
  if (s.nb && (s.nb === "no" ? !!r.nb : r.nb !== s.nb)) return false;
  if (s.og) { if (s.og === "any" ? !r.og : s.og === "none" ? !!(r.og || r.ogb) : r.og !== s.og) return false; }
  if (s.ogb && r.ogb !== s.ogb) return false;
  if (s.vb) { const m = marksOf(r); if (!m[s.vb]) return false; }
  if (s.has && !FIELDS[s.has].row(r)) return false;
  if (s.hasnt && FIELDS[s.hasnt].row(r)) return false;
  if (s.p && !r._pk.includes(s.p)) return false;
  if (s.p2 && !r._pk.includes(s.p2)) return false;
  if (s.pf && !r.pp.some(x => x[0] === s.p && x[2] === s.pf)) return false;   // one spelling of a person, as the cell writes it
  if (s.nm && !r.nm.length) return false;
  if (s.w && !tokenize(s.w).every(t => r._w.has(t))) return false;
  if (s.ph && !r._ph.has(s.ph)) return false;
  if (s.fw && r._first !== s.fw) return false;
  if (s.nums && !s.nums.split(";").includes(r.n)) return false;
  if (s.ys && !s.ys.split(",").includes(String(r.y))) return false;
  if (s.site === "linked" ? !r.s : s.site === "unlinked" ? !!r.s : false) return false;
  return true;
}
export const rowsFor = s => D.rows.filter(r => matchSpec(r, s));

/** The selection in words: "Health, 2023" or "Winter 2003". */
export function describe(s) {
  const bits = [];
  if (s.c) {
    const nm = D.cm[s.c]?.name ?? s.c, ly = s.ly === "w" ? "l" : s.ly;
    bits.push(`${nm}${s.ru === "1" ? " with its sub-committees" : ""}${ly === "l" ? ", likely" : ly === "b" ? ", recorded and likely" : ""}`);
  }
  if (s.cn) bits.push(s.cn === "blank" ? "Committee cell blank" : s.cn === "other" ? "Committee cell names no committee" : "Names no committee");
  if (s.lab) bits.push(`Committee label “${s.lab}” as written`);
  if (s.p) bits.push(`Prepared By names ${D.persons.get(s.p)?.name ?? s.p}${s.p2 ? ` and ${D.persons.get(s.p2)?.name ?? s.p2}` : ""}`);
  if (s.nm) bits.push("A name written in the Committee column, role not stated");
  if (s.w) bits.push(`Title has “${s.w}”`);
  if (s.ph) bits.push(`Title has the words “${s.ph}”`);
  if (s.fw) bits.push(`Title begins with “${s.fw}”`);
  if (s.nc) bits.push(s.nc === "rec" ? "TO NCAI recorded" : s.nc === "norec" ? "TO NCAI not recorded" : `TO NCAI ${NCAI_LABEL[s.nc]}`);
  if (s.nb === "open") bits.push("TO NCAI open, kept as written");
  if (s.o) bits.push(s.o === "rec" ? "Outcome recorded" : s.o === "norec" ? "Outcome not recorded" : s.o === "notadopted" ? "Recorded as not adopted or tabled" : `Outcome recorded as ${OUTCOME_LABEL[s.o]}`);
  if (s.ob === "likely" || s.ob === "open") bits.push(s.ob === "likely" ? "Outcome likely" : "Outcome open, kept as written");
  if (s.og) bits.push(s.og === "any" ? "Origin recorded" : s.og === "none" ? "Origin not recorded" : `Origin: ${ORIGIN_LABEL[s.og] ?? s.og}${s.ogb === "l" ? ", likely" : ""}`);
  else if (s.ogb === "o") bits.push("Origin open, kept as written");
  if (s.vb) bits.push(s.vb === "likely" ? "Any value likely" : "Any value open");
  if (s.has) bits.push(`${FIELDS[s.has].name} recorded`);
  if (s.hasnt) bits.push(`${FIELDS[s.hasnt].name} not recorded`);
  if (s.ib === "likely") bits.push("Included as likely");
  if (s.kb === "likely" || s.kb === "open") bits.push(s.kb === "likely" ? "Convention likely" : "Convention open, kept as written");
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
export const personRows = key => memo("pr:" + key, () => D.rows.filter(r => r._pk.includes(key)));
export function personKinds(key) {
  const c = blankKinds();
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
  ok("rows per year = years[].recorded", A.years.every(r => (byY.get(r.year) || 0) === r.recorded));
  ok("rows per year = year_by_kind totals", A.year_by_kind.every(r => (byY.get(r.year) || 0) === r.total));
  const km = kindMatrix("");
  ok("rows per year and kind = year_by_kind", A.year_by_kind.every((r, i) => ALL_KINDS.every(k => km[i].s[k] + km[i].l[k] === r[k])));
  ok("likely_included = rows with a likely inclusion", A.years.every((r, i) => km[i].lT === r.likely_included));
  let commOk = true, firstBad = "";
  for (const k of Object.keys(A.committee_years.cells)) D.years.forEach((y, i) => {
    let s = 0, l = 0;
    for (const r of D.rows) if (r.y === y) { const lay = layerOf(r, k); if (lay === "c") s++; else if (lay === "l") l++; }
    const [cs, cl] = A.committee_years.cells[k][i];
    if (cs !== s || cl !== l) { commOk = false; firstBad ||= `${k} ${y}`; }
  });
  ok("rows per committee, year and layer = committee_years.cells", commOk, firstBad);
  let ruOk = true;
  for (const k of Object.keys(A.committee_years.rollup || {})) D.years.forEach((y, i) => {
    let s = 0, l = 0;
    for (const r of D.rows) if (r.y === y) { const lay = layerOf(r, k, true); if (lay === "c") s++; else if (lay === "l") l++; }
    const [cs, cl] = A.committee_years.rollup[k][i];
    if (cs !== s || cl !== l) ruOk = false;
  });
  ok("rows per parent committee, year and layer = committee_years.rollup", ruOk);
  ok("committee totals = cells (recorded and likely)", A.committees.every(c => c.recorded === A.committee_years.cells[c.key].reduce((s, x) => s + x[0], 0) && c.likely === A.committee_years.cells[c.key].reduce((s, x) => s + x[1], 0)));
  let covOk = true, covBad = "";
  for (const f of Object.keys(FIELDS)) {
    const a = covMatrix(f, "", "");
    for (const r of a) if (D.rows.filter(x => x.y === r.year && FIELDS[f].row(x)).length !== r.n) { covOk = false; covBad ||= `${f} ${r.year}`; }
  }
  ok("rows per field and year = coverage_by_year", covOk, covBad);
  ok("rows per outcome and year = outcome_by_year", A.outcome_by_year.every(r => ["adopted", "not_adopted", "tabled"].every(v => D.rows.filter(x => x.y === r.year && x.o === v).length === r[v])
    && D.rows.filter(x => x.y === r.year && x.ob === "likely").length === r.likely));
  ok("rows per TO NCAI value and year = to_ncai_by_year", A.to_ncai_by_year.every(r => ["yes", "no", "na"].every(v => D.rows.filter(x => x.y === r.year && x.nc === v).length === r[v])));
  ok("rows per origin value and layer = origin.by_value", Object.entries(A.origin.by_value).every(([v, o]) => D.rows.filter(r => r.og === v && r.ogb === "r").length === o.recorded && D.rows.filter(r => r.og === v && r.ogb === "l").length === o.likely)
    && D.rows.filter(r => r.ogb === "o").length === A.origin.open);
  ok("rows linked to the site = meta.counts.linked_to_site", D.rows.filter(r => r.s).length === A.meta.counts.linked_to_site);
  ok("people: rows naming each person = people[].total", A.people.every(p => personRows(p.key).length === p.total));
  ok("people: first, last and years present = rows", A.people.every(p => { const ys = personRows(p.key).map(r => r.y); return Math.min(...ys) === p.first_year && Math.max(...ys) === p.last_year && new Set(ys).size === p.years_present; }));
  ok("readoption members found among the rows", A.readoptions.groups.every(g => g.members.every(m => D.byNumber.has(m.number))));
  ok("numbered = library numbers + site-only + number gaps (distinct numbers)", A.years.every(y => y.numbered === (y.library_numbers ?? y.recorded) + y.site_only + y.number_gaps));
  { const c = A.places.counts, cv = c.conventions || { sessions: c.sessions - c.not_applicable, known: c.known, recorded: c.recorded, likely: c.likely, unknown: c.open };
    ok("places: known = recorded + likely; the sessions and the conventions add up", c.known === c.recorded + c.likely && c.sessions === c.recorded + c.likely + c.open + c.not_applicable
      && A.places.sessions.length === c.sessions && cv.sessions === cv.known + cv.unknown && cv.sessions + c.not_applicable === c.sessions); }
  { const s = A.wyatt.summary, n = A.wyatt.rows.reduce((t, r) => t + r.cells.length, 0), by = k => A.wyatt.rows.reduce((t, r) => t + r.cells.filter(c => c.state === k).length, 0);
    ok("wyatt: summary = cells, in each of the five states", s.cells === n && ["equal", "differs", "blank", "unreadable", "unmapped"].every(k => s[k] === by(k)) && A.wyatt.rows.every(r => r.cells.every(c => c.state !== "unmapped" || c.ours === null))); }
  if (A.committees.length) {
    const hk = A.committees.find(c => c.total > 0), kmc = kindMatrix(hk.key);
    ok("committee-filtered year totals add to recorded + likely", kmc.reduce((s, r) => s + r.sT + r.lT, 0) === hk.total);
  }
  return res;
}
export { esc, fmt };
