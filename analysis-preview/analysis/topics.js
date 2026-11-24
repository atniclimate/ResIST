// Topics tab of the Analysis preview ("Issues, Laws and Wording"). Plain ES module with typed comments (D-083 item 14).
// No top-level DOM access, so Node can import it. Everything shown comes from ../data/topics.json (schema
// resist-topics/1) or from the fixed copy deck below; the module composes no label, summary or claim, and a count is
// a text match, never a statement of what a resolution is about (D-078). It draws its own SVG and tables, keeps its
// own lists inside its own root, adds no document-level listener, and makes one request: the data file.
//
// The pure helpers (esc, fmt, plural) are carried here as copies, so a change to charts.js cannot break this tab.

export const DATA_URL = "../data/topics.json";
export const SCHEMA = "resist-topics/1";

/** @typedef {{ n: string, y: number|null, t: string }} SiteRow
 *  @typedef {{ n: string, y: number|null, t: string, s: number|null }} LibraryRow
 *  @typedef {{ y: number|null, n: number, ids: Array<number|string> }} YearCount
 *  @typedef {{ siteBase?: string|null, announce?: (text: string) => void, data?: any }} TopicsCtx */

/* ---------------------------------------------------------------------------------------------------------- */
/* Pure helpers                                                                                                 */

/** @param {unknown} s @returns {string} */
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
/** @param {number|null|undefined} n @returns {string} */
const fmt = n => (n == null || Number.isNaN(n) ? "" : Number(n).toLocaleString("en-US"));
/** @param {number} n @param {string} one @param {string} many @returns {string} */
const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : many}`;
const res = n => plural(n, "resolution", "resolutions");

/** Natural order: runs of digits compare as integers. @param {unknown} a @param {unknown} b @returns {number} */
function nat(a, b) {
  const A = String(a).split(/(\d+)/), B = String(b).split(/(\d+)/);
  for (let i = 0; i < Math.min(A.length, B.length); i++) {
    if (A[i] === B[i]) continue;
    if (i % 2 === 1) { const d = Number(A[i]) - Number(B[i]); if (d) return d; }
    return A[i] < B[i] ? -1 : 1;
  }
  return A.length - B.length;
}

/** Years with a count, ascending. @param {YearCount[]} rows @returns {number[]} */
const yearsOf = rows => rows.filter(r => r.y != null).map(r => r.y).sort((a, b) => a - b);
/** "{first} to {last}", or the one year. @param {number[]} ys @returns {string} */
const span = ys => (ys.length === 0 ? "" : ys[0] === ys[ys.length - 1] ? String(ys[0]) : `${ys[0]} to ${ys[ys.length - 1]}`);

/* ---------------------------------------------------------------------------------------------------------- */
/* Fixed copy deck (design section 2.5). Template words only; {} values come from the file.                    */

const COPY = {
  failed: "The counts for this tab could not be read. Nothing is shown.",
  lead: "Counts of issue names, laws and wording found in the text of ATNI's resolutions. A count is a text match: it never says what a resolution is about, and it is not a measure of ATNI's priorities.",
  issuesH: "Issue Names in the Text",
  issuesLead: "For each issue in Policy Sentinel's reviewed issue table, how many resolutions use one of its names or references, by year. Each count opens its list.",
  lawsH: "Laws and Orders Named",
  lawsLead: "Executive orders, public laws, U.S. Code sections, CFR parts and Federal Register pages the resolutions cite, grouped by the number as written, with every written form. Other federal law, treaties and declarations are listed as written.",
  wordingH: "Groups of Resolutions with Similar Wording",
  wordingLead: "Groups of resolutions that use similar wording. Each group is shown only by its own most frequent distinctive words. A group is a count of shared wording: it does not say what its resolutions are about, that they are related, or that they are ATNI's priorities. Not yet reviewed.",
  caveatIssue: "A text match in the published text, never what a resolution is about.",
  notBuilt: "Groups of resolutions with similar wording are not built yet.",
  notReviewed: "Not yet reviewed",
  noLibraryText: "This site holds no text for this resolution; The Resolution Library lists it.",
};
const BASIS = { "name:official": "official name", "name:people_use": "name in use", "rests_on:usc": "U.S. Code reference", "rests_on:cfr": "CFR reference" };
const KIND_LABEL = {
  executive_order: "Executive order", public_law: "Public law", usc: "U.S. Code section", cfr: "CFR part",
  federal_register: "Federal Register page", federal_law: "Other federal law, as written", treaty: "Treaty, as written",
  instrument: "Declaration or other instrument, as written",
};
const KIND_ORDER = ["executive_order", "public_law", "usc", "cfr", "federal_register", "federal_law", "treaty", "instrument"];
const PAGE = 50, LAW_FIRST = 25, CARD_FIRST = 20;

/* ---------------------------------------------------------------------------------------------------------- */
/* Validation                                                                                                   */

/** Problems found in a parsed topics.json; [] when it can be drawn.
 *  @param {unknown} data @returns {string[]} */
export function validate(data) {
  const bad = [];
  const isObj = v => v !== null && typeof v === "object" && !Array.isArray(v);
  const str = v => typeof v === "string";
  const int = v => Number.isInteger(v);
  if (!isObj(data)) return ["not an object"];
  const d = /** @type {any} */ (data);
  if (d.schema !== SCHEMA) bad.push("schema");
  if (!Array.isArray(d.parts) || !d.parts.every(str) || !d.parts.includes("issues") || !d.parts.includes("laws")) bad.push("parts");
  if (!isObj(d.inputs) || !Array.isArray(d.inputs.site_years) || d.inputs.site_years.length !== 2 || !d.inputs.site_years.every(int)) bad.push("inputs.site_years");
  if (!isObj(d.site)) bad.push("site");
  if (!isObj(d.library)) bad.push("library");
  if (bad.length) return bad;
  for (const [k, r] of Object.entries(d.site)) {
    if (!/^\d+$/.test(k) || !isObj(r) || !str(r.n) || !str(r.t) || !(r.y === null || int(r.y))) bad.push(`site.${k}`);
  }
  for (const [k, r] of Object.entries(d.library)) {
    if (!isObj(r) || !str(r.n) || !str(r.t) || !(r.y === null || int(r.y)) || !(r.s === null || int(r.s))) bad.push(`library.${k}`);
  }
  if (bad.length) return bad.slice(0, 8);
  const has = (src, id) => (src === "s" ? Object.prototype.hasOwnProperty.call(d.site, String(id)) : Object.prototype.hasOwnProperty.call(d.library, String(id)));
  /** An ids list and its by_year: ids exist, n === ids.length, by_year sums to n and its ids are the same ids. */
  const ids = (where, n, list, byYear, src) => {
    if (!int(n) || !Array.isArray(list) || list.length !== n) { bad.push(`${where}.n`); return; }
    if (!list.every(i => has(src, i))) bad.push(`${where}.ids`);
    if (byYear === undefined) return;
    if (!Array.isArray(byYear)) { bad.push(`${where}.by_year`); return; }
    let sum = 0, same = new Set(list.map(String)), seen = 0;
    for (const y of byYear) {
      if (!isObj(y) || !(y.y === null || int(y.y)) || !int(y.n) || !Array.isArray(y.ids) || y.ids.length !== y.n) { bad.push(`${where}.by_year`); return; }
      sum += y.n;
      for (const i of y.ids) { if (same.has(String(i))) seen++; }
    }
    if (sum !== n || seen !== n) bad.push(`${where}.by_year sum`);
  };
  // Part 1
  const items = d.issues?.items;
  if (!isObj(d.issues) || !isObj(d.issues.source) || !Array.isArray(items)) bad.push("issues");
  else {
    const s = d.issues.source;
    for (const k of ["license", "notice", "reviewed_on", "pinned_on"]) if (!str(s[k])) bad.push(`issues.source.${k}`);
    items.forEach((it, i) => {
      const w = `issues.items.${i}`;
      if (!isObj(it) || !str(it.id) || !str(it.label) || !str(it.reviewed_on) || !isObj(it.named) || !Array.isArray(it.phrases) || !isObj(it.search)) { bad.push(w); return; }
      ids(`${w}.named`, it.named.n, it.named.ids, it.named.by_year, "s");
      it.phrases.forEach((p, j) => {
        if (!isObj(p) || !str(p.text) || !str(p.from)) bad.push(`${w}.phrases.${j}`);
        else ids(`${w}.phrases.${j}`, p.n, p.ids, undefined, "s");
      });
      if (!str(it.search.key) || typeof it.search.applied !== "boolean" || !int(it.search.n)) bad.push(`${w}.search`);
    });
  }
  // Part 2
  const L = d.laws;
  if (!isObj(L) || !int(L.resolutions) || !int(L.placed_rows) || !Array.isArray(L.kinds) || !Array.isArray(L.groups) || !Array.isArray(L.unreadable) || !isObj(L.unplaced) || !Array.isArray(L.unplaced.items) || !int(L.unplaced.rows)) bad.push("laws");
  else {
    L.kinds.forEach((k, i) => { if (!isObj(k) || !str(k.kind) || !int(k.groups) || !int(k.resolutions) || !(k.grouped === "number" || k.grouped === "as_written")) bad.push(`laws.kinds.${i}`); });
    L.groups.forEach((g, i) => {
      const w = `laws.groups.${i}`;
      if (!isObj(g) || !str(g.kind) || !str(g.key) || !str(g.heading) || !Array.isArray(g.forms) || !int(g.unplaced)) { bad.push(w); return; }
      ids(w, g.n, g.ids, g.by_year, "s");
      for (const f of g.forms) if (!isObj(f) || !str(f.text) || !int(f.rows) || !int(f.n)) { bad.push(`${w}.forms`); break; }
    });
    for (const u of [...L.unreadable, ...L.unplaced.items]) if (!isObj(u) || !str(u.text) || !str(u.kind) || !has("s", u.id)) { bad.push("laws.unplaced or unreadable"); break; }
  }
  // Part 3 (optional)
  if (d.parts.includes("wording")) {
    const W = d.wording;
    if (!isObj(W) || !Array.isArray(W.corpora) || !isObj(W.packages)) bad.push("wording");
    else W.corpora.forEach((c, ci) => {
      const w = `wording.corpora.${ci}`;
      if (!isObj(c) || !(c.id === "text" || c.id === "titles") || !int(c.documents)) { bad.push(w); return; }
      if (c.built === false) return;
      const src = c.id === "text" ? "s" : "l";
      if (!isObj(c.params) || !Array.isArray(c.years) || c.years.length !== 2 || !Array.isArray(c.groups) || !Array.isArray(c.ungrouped) || !int(c.grouped)) { bad.push(w); return; }
      if (!c.ungrouped.every(i => has(src, i))) bad.push(`${w}.ungrouped`);
      let inGroups = 0;
      c.groups.forEach((g, gi) => {
        const gw = `${w}.groups.${gi}`;
        if (!isObj(g) || !str(g.id) || !int(g.years_present) || !Array.isArray(g.words) || !g.words.every(x => isObj(x) && str(x.w) && int(x.in))) { bad.push(gw); return; }
        ids(gw, g.n, g.ids, g.by_year, src);
        inGroups += g.n;
      });
      if (inGroups !== c.grouped) bad.push(`${w}.grouped`);
    });
  }
  return bad.slice(0, 12);
}

/* ---------------------------------------------------------------------------------------------------------- */
/* Data and state                                                                                               */

/** @type {Promise<any>|null} */
let dataPromise = null;
/** One request for the data file per page load; a failure is not cached. @returns {Promise<any>} */
function loadData() {
  if (!dataPromise) {
    dataPromise = fetch(DATA_URL).then(r => { if (!r.ok) throw new Error("status"); return r.json(); })
      .catch(e => { dataPromise = null; throw e; });
  }
  return dataPromise;
}

/** What survives a repaint or a second render of the tab. */
const state = {
  lawSort: "count", lawKind: "", lawShown: LAW_FIRST, lawFresh: -1, lawOpen: /** @type {Set<number>} */ (new Set()),
  corpus: "text", order: "count", cardsShown: CARD_FIRST, cardFresh: -1,
  details: /** @type {Set<string>} */ (new Set()),
  list: /** @type {null|{ slot: string, title: string, src: "s"|"l", ids: Array<number|string>, shown: number, opener: string }} */ (null),
};
/** @type {WeakMap<HTMLElement, any>} */
const views = new WeakMap();

/* ---------------------------------------------------------------------------------------------------------- */
/* Year chart and its table                                                                                     */

/** Top of the vertical scale: integer ticks, no taller than the data needs. @param {number} max @returns {number} */
function niceTop(max) {
  if (max <= 4) return Math.max(2, max);
  const mag = 10 ** Math.floor(Math.log10(max));
  for (const m of [1, 1.2, 1.4, 1.6, 1.8, 2, 2.4, 3, 4, 5, 6, 8, 10]) { const v = m * mag; if (v >= max && Number.isInteger(v) && v % 2 === 0) return v; }
  return 10 * mag;
}

/** Year bars on a fixed natural width (the SVG shrinks, never grows). Decorative: the table under it is the
 *  keyboard path. Every year from lo to hi is drawn; a year with no count prints a real 0; a count with no year
 *  gets its own hatched bar. @param {{lo:number, hi:number, rows:YearCount[], small?:boolean, spec:(y:number|null)=>string, label:(y:number|null,n:number)=>string}} o
 *  @returns {string} */
function chartSvg(o) {
  const small = !!o.small;
  const byY = new Map(o.rows.filter(r => r.y != null).map(r => [r.y, r.n]));
  const unknown = o.rows.find(r => r.y == null && r.n > 0) || null;
  const years = []; for (let y = o.lo; y <= o.hi; y++) years.push(y);
  const slot = small ? 14 : 22, padL = small ? 24 : 30, padR = 6, padT = small ? 14 : 22, plotH = small ? 52 : 120, labelH = small ? 20 : 24;
  const uW = unknown ? (small ? 58 : 70) : 0, gap = unknown ? 10 : 0;
  const W = padL + years.length * slot + gap + uW + padR;
  const H = padT + plotH + labelH + (unknown ? (small ? 12 : 14) : 0);
  const max = Math.max(1, ...o.rows.map(r => r.n));
  const top = niceTop(max), base = padT + plotH;
  const yv = v => (v / top) * plotH;
  let s = `<svg class="tp-svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="max-width:${W}px" aria-hidden="true" focusable="false">`;
  const ticks = top <= 5 ? Array.from({ length: top + 1 }, (_, i) => i) : [0, top / 2, top];
  for (const t of ticks) {
    const gy = base - yv(t);
    s += `<line class="tp-grid" x1="${padL}" x2="${W - padR}" y1="${gy.toFixed(1)}" y2="${gy.toFixed(1)}"/>`;
    s += `<text class="tp-tick" x="${padL - 5}" y="${(gy + 4).toFixed(1)}" text-anchor="end">${fmt(t)}</text>`;
  }
  s += `<line class="tp-axis" x1="${padL}" x2="${W - padR}" y1="${base}" y2="${base}"/>`;
  const labelled = new Set(years.filter(y => y % 5 === 0));
  if (small) { labelled.clear(); }
  const near = y => [...labelled].some(l => Math.abs(l - y) < 3);
  if (!near(o.lo)) labelled.add(o.lo);
  if (!near(o.hi)) labelled.add(o.hi);
  years.forEach((y, i) => {
    const n = byY.get(y) || 0, x = padL + i * slot, bw = slot - 3;
    if (n > 0) {
      const h = Math.max(2, yv(n));
      s += `<rect class="tp-bar" data-act="open" data-open="${esc(o.spec(y))}" data-fk="bar|${esc(o.spec(y))}" x="${(x + 1.5).toFixed(1)}" y="${(base - h).toFixed(1)}" width="${bw}" height="${h.toFixed(1)}"><title>${esc(o.label(y, n))}</title></rect>`;
      if (!small) s += `<text class="tp-cnt" x="${(x + slot / 2).toFixed(1)}" y="${(base - h - 4).toFixed(1)}" text-anchor="middle">${fmt(n)}</text>`;
    } else if (!small) {
      s += `<text class="tp-zero" x="${(x + slot / 2).toFixed(1)}" y="${base - 4}" text-anchor="middle">0</text>`;
    }
    if (labelled.has(y)) s += `<text class="tp-tick" x="${(x + slot / 2).toFixed(1)}" y="${base + (small ? 13 : 16)}" text-anchor="middle">${y}</text>`;
  });
  if (unknown) {
    const x = padL + years.length * slot + gap, h = Math.max(2, yv(unknown.n)), bw = uW - 12;
    s += `<rect class="tp-bar tp-bar-nr" data-act="open" data-open="${esc(o.spec(null))}" data-fk="bar|${esc(o.spec(null))}" fill="url(#tp-hatch)" x="${x + 6}" y="${(base - h).toFixed(1)}" width="${bw}" height="${h.toFixed(1)}"><title>${esc(o.label(null, unknown.n))}</title></rect>`;
    if (!small) s += `<text class="tp-cnt" x="${(x + uW / 2).toFixed(1)}" y="${(base - h - 4).toFixed(1)}" text-anchor="middle">${fmt(unknown.n)}</text>`;
    s += `<text class="tp-tick" x="${(x + uW / 2).toFixed(1)}" y="${base + (small ? 12 : 15)}" text-anchor="middle">Year not</text>`;
    s += `<text class="tp-tick" x="${(x + uW / 2).toFixed(1)}" y="${base + (small ? 23 : 28)}" text-anchor="middle">recorded</text>`;
  }
  return s + `</svg>`;
}

/** The data table under a chart: one row per year with a count (the count is a button), the unknown year last, and one
 *  sentence for the years that hold none. @param {{lo:number, hi:number, rows:YearCount[], caption:string, spec:(y:number|null)=>string, label:(y:number|null,n:number)=>string, tag:string}} o
 *  @returns {string} */
function yearTable(o) {
  const rows = [...o.rows].filter(r => r.n > 0).sort((a, b) => (a.y == null) - (b.y == null) || (a.y ?? 0) - (b.y ?? 0));
  const withYear = rows.filter(r => r.y != null).length;
  const zeroYears = (o.hi - o.lo + 1) - withYear;
  let h = `<table class="tp-table tp-ytable"><caption class="tp-sr">${esc(o.caption)}</caption><thead><tr><th scope="col">Year</th><th scope="col" class="tp-num">Resolutions</th></tr></thead><tbody>`;
  for (const r of rows) {
    h += `<tr><th scope="row">${r.y == null ? "Year not recorded" : r.y}</th><td class="tp-num">${countBtn(r.n, o.spec(r.y), `${o.tag}|${r.y}`, o.label(r.y, r.n))}</td></tr>`;
  }
  h += `</tbody></table>`;
  if (zeroYears > 0) h += `<p class="tp-zero-note">${withYear === 0 ? `Every year` : `Every other year`} from ${o.lo} to ${o.hi}: 0 resolutions.</p>`;
  return h;
}

/** A count that opens its list. @param {number} n @param {string} spec @param {string} tag @param {string} label @param {string} [cls] @returns {string} */
function countBtn(n, spec, tag, label, cls = "") {
  return `<button type="button" class="tp-count${cls ? " " + cls : ""}" data-act="open" data-open="${esc(spec)}" data-fk="open|${esc(spec)}|${esc(tag)}" aria-label="${esc(label ? `${label}. Open the list.` : `${fmt(n)}. Open the list.`)}">${fmt(n)}</button>`;
}

/* ---------------------------------------------------------------------------------------------------------- */
/* The view                                                                                                     */

/** @param {HTMLElement} root @param {any} d @param {TopicsCtx} ctx */
function createView(root, d, ctx) {
  const siteBase = typeof ctx.siteBase === "string" ? ctx.siteBase : null;
  const [lo, hi] = d.inputs.site_years;
  const items = d.issues.items, laws = d.laws;
  const hasWording = d.parts.includes("wording") && d.wording;
  const corpora = hasWording ? d.wording.corpora : [];
  if (!corpora.some(c => c.id === state.corpus)) state.corpus = corpora.length ? corpora[0].id : "text";
  let liveToggle = false;
  const $ = s => root.querySelector(s);

  const say = text => {
    if (typeof ctx.announce === "function") { ctx.announce(text); return; }
    const el = $(".tp-live");
    if (el) { liveToggle = !liveToggle; el.textContent = text + (liveToggle ? "" : " "); }
  };

  /* ---- lists ---- */
  const rowOf = (src, id) => (src === "s" ? d.site[String(id)] : d.library[String(id)]);
  const sortedIds = (src, list) => [...list].sort((a, b) => {
    const A = rowOf(src, a), B = rowOf(src, b);
    return (A.y ?? 1e9) - (B.y ?? 1e9) || nat(A.n, B.n);
  });

  /** Resolves an open spec to its slot, title and ids. @param {string} spec */
  function resolve(spec) {
    const p = spec.split(":");
    const yr = v => (v === "null" ? null : Number(v));
    const yearIds = (rows, y) => (rows.find(r => r.y === y)?.ids ?? []);
    const yTitle = (ctxName, y) => `${ctxName}, ${y == null ? "year not recorded" : y}`;
    if (p[0] === "i") {
      const it = items[Number(p[1])];
      if (p[2] === "all") return { slot: `i:${p[1]}`, title: it.label, src: "s", ids: it.named.ids };
      if (p[2] === "y") { const y = yr(p[3]); return { slot: `i:${p[1]}`, title: yTitle(it.label, y), src: "s", ids: yearIds(it.named.by_year, y) }; }
      if (p[2] === "p") { const ph = it.phrases[Number(p[3])]; return { slot: `i:${p[1]}`, title: `${it.label}, “${ph.text}”`, src: "s", ids: ph.ids }; }
    }
    if (p[0] === "l") {
      const g = laws.groups[Number(p[1])];
      if (p[2] === "all") return { slot: `l:${p[1]}`, title: g.heading, src: "s", ids: g.ids };
      if (p[2] === "y") { const y = yr(p[3]); return { slot: `l:${p[1]}`, title: yTitle(g.heading, y), src: "s", ids: yearIds(g.by_year, y) }; }
    }
    if (p[0] === "lk") return { slot: "lk", title: KIND_LABEL[p[1]] || p[1], src: "s", ids: kindIds(p[1]) };
    if (p[0] === "lr") return { slot: "lk", title: "Resolutions that name at least one law or order", src: "s", ids: allLawIds() };
    if (p[0] === "w") {
      const c = corpora[Number(p[1])], g = c.groups[Number(p[2])], src = c.id === "text" ? "s" : "l";
      const name = groupName(g);
      if (p[3] === "all") return { slot: `w:${p[1]}:${p[2]}`, title: name, src, ids: g.ids };
      if (p[3] === "y") { const y = yr(p[4]); return { slot: `w:${p[1]}:${p[2]}`, title: yTitle(name, y), src, ids: yearIds(g.by_year, y) }; }
    }
    if (p[0] === "wu") {
      const c = corpora[Number(p[1])];
      return { slot: `wu:${p[1]}`, title: "Resolutions that join no group", src: c.id === "text" ? "s" : "l", ids: c.ungrouped };
    }
    return null;
  }
  /** A group is named only by its own words, never by a rank or a build number. @param {{words:Array<{w:string}>}} g */
  const groupName = g => `Wording group: ${g.words.slice(0, 3).map(x => x.w).join(", ")}`;
  const kindIds = kind => [...new Set([...laws.groups.filter(g => g.kind === kind).flatMap(g => g.ids), ...laws.unreadable.filter(u => u.kind === kind).map(u => u.id)])];
  const allLawIds = () => [...new Set([...laws.groups.flatMap(g => g.ids), ...laws.unreadable.map(u => u.id)])];
  const sectionOf = slot => (slot[0] === "i" ? "issues" : slot[0] === "l" ? "laws" : "wording");

  /** The open list for a slot, or "". @param {string} slot @returns {string} */
  function listHtml(slot) {
    const L = state.list;
    if (!L || L.slot !== slot) return "";
    const ids = sortedIds(L.src, L.ids), shown = ids.slice(0, L.shown);
    let h = `<section class="tp-list" aria-labelledby="tp-list-h"><div class="tp-list-head"><h4 id="tp-list-h" class="tp-list-h" tabindex="-1" data-fk="list-head">${esc(L.title)}: ${res(ids.length)}</h4>`;
    h += `<button type="button" class="tp-btn" data-act="close">Close list</button></div>`;
    if (!ids.length) h += `<p class="tp-note">No resolutions are listed here.</p>`;
    h += `<ol class="tp-lrows">`;
    for (const id of shown) {
      const r = rowOf(L.src, id);
      const siteId = L.src === "s" ? Number(id) : r.s;
      const link = siteBase && siteId != null ? `${siteBase}#/r/${Number(siteId)}` : null;
      h += `<li class="tp-lrow"><span class="tp-lnum">${link ? `<a href="${esc(link)}" aria-label="Open resolution ${esc(r.n)}">${esc(r.n)}</a>` : esc(r.n)}</span>`;
      h += `<span class="tp-lyear">${r.y == null ? "Year not recorded" : r.y}</span><span class="tp-ltitle">${esc(r.t)}</span>`;
      if (L.src === "l" && r.s == null) h += `<span class="tp-lnote">${esc(COPY.noLibraryText)}</span>`;
      h += `</li>`;
    }
    h += `</ol>`;
    if (shown.length < ids.length) h += `<p><button type="button" class="tp-btn" data-act="more" data-fk="list-more">Show ${Math.min(PAGE, ids.length - shown.length)} more (${fmt(shown.length)} of ${fmt(ids.length)} shown)</button></p>`;
    h += `<p><button type="button" class="tp-btn" data-act="close" data-fk="list-close">Close list</button></p></section>`;
    return h;
  }
  const slotDiv = slot => `<div class="tp-slot" data-slot="${esc(slot)}">${listHtml(slot)}</div>`;

  /* ---- part 1: issue names ---- */
  function issueHtml(it, i) {
    const key = `yr:i:${i}`;
    const ys = yearsOf(it.named.by_year);
    const n = it.named.n;
    const lab = `${it.label}`;
    let h = `<article class="tp-issue" aria-labelledby="tp-i-${i}"><h3 id="tp-i-${i}">${esc(it.label)}</h3>`;
    h += `<p class="tp-meta">Policy Sentinel issue, reviewed ${esc(it.reviewed_on)}</p>`;
    if (n === 0) h += `<p class="tp-headline">Named in no resolution this site publishes</p>`;
    else h += `<p class="tp-headline">Named in ${countBtn(n, `i:${i}:all`, "head", "", "tp-big")} ${n === 1 ? "resolution" : "resolutions"}, ${esc(span(ys))}</p>`;
    if (n > 0) {
      const o = { lo, hi, rows: it.named.by_year, spec: y => `i:${i}:y:${y}`, label: (y, c) => `${lab}, ${y == null ? "year not recorded" : y}: ${res(c)}`, tag: `iy${i}` };
      h += `<details class="tp-details" data-key="${key}"${state.details.has(key) ? " open" : ""}><summary>Show by year</summary><div class="tp-chart">${chartSvg(o)}</div>${yearTable({ ...o, caption: `${lab}: resolutions by year` })}</details>`;
    }
    h += `<h4 class="tp-h4">Names searched</h4><table class="tp-table"><caption class="tp-sr">${esc(it.label)}: names and references searched, and how many resolutions use each</caption><thead><tr><th scope="col">Name or reference</th><th scope="col">Basis</th><th scope="col" class="tp-num">Resolutions</th></tr></thead><tbody>`;
    it.phrases.forEach((ph, j) => {
      h += `<tr><th scope="row" class="tp-phrase">${esc(ph.text)}</th><td>${esc(BASIS[ph.from] || ph.from)}</td><td class="tp-num">${ph.n > 0 ? countBtn(ph.n, `i:${i}:p:${j}`, `p${j}`, `${lab}, “${ph.text}”: ${res(ph.n)}`) : `<span class="tp-zeroval">0</span>`}</td></tr>`;
    });
    h += `</tbody></table>`;
    h += `<p class="tp-sline">${siteSearchLine(it)}</p><p class="tp-caveat">${esc(COPY.caveatIssue)}</p>${slotDiv(`i:${i}`)}</article>`;
    return h;
  }
  function siteSearchLine(it) {
    const q = it.search, k = `“${esc(q.key)}”`;
    const m = siteBase ? `<a href="${esc(`${siteBase}#/?q=${encodeURIComponent(q.key)}`)}">${fmt(q.n)}</a>` : fmt(q.n);
    if (!q.applied) return `The site's search for ${k} adds no other names and searches the words alone; it lists ${m}.`;
    if (q.n > it.named.n) return `The site's search for ${k} lists ${m}: it also matches the words of ${k} when they are not side by side.`;
    if (q.n === it.named.n) return `The site's search for ${k} lists the same ${m}.`;
    return `The site's search for ${k} lists ${m}.`;
  }
  function issuesHtml() {
    const s = d.issues.source, [a, b] = d.inputs.site_years;
    let h = `<h2 id="tp-h-issues" class="tp-h2" tabindex="-1">${esc(COPY.issuesH)}</h2><p class="tp-sub">${esc(COPY.issuesLead)}</p>`;
    h += items.map(issueHtml).join("");
    h += `<p class="tp-source">Issue names: Policy Sentinel's reviewed issue table, pinned ${esc(s.pinned_on)}, reviewed ${esc(s.reviewed_on)}, under the PolyForm Noncommercial License 1.0.0 (${esc(s.license)}). ${esc(s.notice)}. Text: the ${fmt(d.inputs.site_resolutions)} resolutions this site publishes, ${a} to ${b}.</p>`;
    return h;
  }

  /* ---- part 2: laws and orders ---- */
  function sortedGroups() {
    const idx = laws.groups.map((g, i) => ({ g, i }));
    const rank = k => { const r = KIND_ORDER.indexOf(k); return r < 0 ? 99 : r; };
    if (state.lawSort === "kind") idx.sort((x, y) => rank(x.g.kind) - rank(y.g.kind) || nat(x.g.key, y.g.key));
    return state.lawKind ? idx.filter(x => x.g.kind === state.lawKind) : idx;
  }
  function lawRowHtml({ g, i }, first) {
    const ys = yearsOf(g.by_year);
    const yl = ys.length ? `${span(ys)}, in ${ys.length === 1 ? "1 year" : `${ys.length} years`}` : "Year not recorded";
    const open = state.lawOpen.has(i);
    let h = `<tr class="tp-lawrow"><th scope="row"><span class="tp-lawname">${esc(g.heading)}</span><span class="tp-kind">${esc(KIND_LABEL[g.kind] || g.kind)}</span><span class="tp-yl">${esc(yl)}</span>`;
    if (g.unplaced > 0) h += `<span class="tp-yl">Also found, not placed in a clause: ${fmt(g.unplaced)}</span>`;
    h += `</th><td class="tp-num">${countBtn(g.n, `l:${i}:all`, "row", `${g.heading}: ${res(g.n)}`)}</td>`;
    h += `<td class="tp-num"><button type="button" class="tp-btn tp-btn-sm" data-act="law" data-law="${i}" data-fk="law|${i}" aria-expanded="${open}" aria-controls="tp-law-${i}"${first ? ' data-first="1"' : ""}>${open ? "Hide details" : "Details"}<span class="tp-sr"> for ${esc(g.heading)}</span></button></td></tr>`;
    if (open) {
      const o = { lo, hi, rows: g.by_year, spec: y => `l:${i}:y:${y}`, label: (y, c) => `${g.heading}, ${y == null ? "year not recorded" : y}: ${res(c)}`, tag: `ly${i}` };
      h += `<tr class="tp-detailrow"><td colspan="3" id="tp-law-${i}"><div class="tp-chart">${chartSvg(o)}</div>${yearTable({ ...o, caption: `${g.heading}: resolutions by year` })}`;
      h += `<h4 class="tp-h4">Written forms</h4><ul class="tp-forms">${g.forms.map(f => `<li><span class="tp-form">${esc(f.text)}</span> ${plural(f.rows, "citation", "citations")}, ${res(f.n)}</li>`).join("")}</ul></td></tr>`;
    }
    if (state.list && state.list.slot === `l:${i}`) h += `<tr class="tp-listrow"><td colspan="3">${slotDiv(`l:${i}`)}</td></tr>`;
    return h;
  }
  function lawsHtml() {
    const [a, b] = d.inputs.site_years;
    const groups = sortedGroups(), shown = groups.slice(0, state.lawShown);
    const allIds = allLawIds();
    let h = `<h2 id="tp-h-laws" class="tp-h2" tabindex="-1">${esc(COPY.lawsH)}</h2><p class="tp-sub">${esc(COPY.lawsLead)}</p>`;
    h += `<p class="tp-summary">${allIds.length === laws.resolutions ? countBtn(laws.resolutions, "lr", "sum", `${res(laws.resolutions)} name at least one law or order`) : fmt(laws.resolutions)} ${laws.resolutions === 1 ? "resolution names" : "resolutions name"} at least one of these, ${a} to ${b}.</p>`;
    h += `<table class="tp-table tp-kinds"><caption class="tp-sr">Laws and orders named, by kind</caption><thead><tr><th scope="col">Kind</th><th scope="col" class="tp-num">Groups</th><th scope="col" class="tp-num">Resolutions</th></tr></thead><tbody>`;
    for (const k of laws.kinds) {
      const ok = kindIds(k.kind).length === k.resolutions;
      h += `<tr><th scope="row">${esc(KIND_LABEL[k.kind] || k.kind)}</th><td class="tp-num">${fmt(k.groups)}</td><td class="tp-num">${ok ? countBtn(k.resolutions, `lk:${k.kind}`, "kind", `${KIND_LABEL[k.kind] || k.kind}: ${res(k.resolutions)}`) : fmt(k.resolutions)}</td></tr>`;
    }
    h += `</tbody></table>`;
    h += `<div class="tp-slotwrap">${slotDiv("lk")}</div>`;
    h += `<div class="tp-controls"><div class="tp-fld"><label for="tp-law-kind">Kind</label><select id="tp-law-kind" data-act="lawkind" data-fk="lawkind"><option value="">All kinds</option>${laws.kinds.map(k => `<option value="${esc(k.kind)}"${state.lawKind === k.kind ? " selected" : ""}>${esc(KIND_LABEL[k.kind] || k.kind)}</option>`).join("")}</select></div>`;
    h += `<div class="tp-fld"><span class="tp-lab" id="tp-law-sort-l">Order</span><div class="tp-seg" role="group" aria-labelledby="tp-law-sort-l"><button type="button" class="tp-btn" data-act="lawsort" data-v="count" data-fk="lawsort|count" aria-pressed="${state.lawSort === "count"}">by number of resolutions</button><button type="button" class="tp-btn" data-act="lawsort" data-v="kind" data-fk="lawsort|kind" aria-pressed="${state.lawSort === "kind"}">by kind and number</button></div></div></div>`;
    h += `<table class="tp-table tp-laws"><caption class="tp-sr">Laws and orders named: ${fmt(groups.length)} groups. Each row has its count and a details button.</caption><thead><tr><th scope="col">Law or order</th><th scope="col" class="tp-num">Resolutions</th><th scope="col" class="tp-num"><span class="tp-sr">Details</span></th></tr></thead><tbody>`;
    shown.forEach((x, j) => { h += lawRowHtml(x, j === state.lawFresh); });
    h += `</tbody></table>`;
    if (shown.length < groups.length) h += `<p><button type="button" class="tp-btn" data-act="lawall" data-fk="lawall">Show all ${fmt(groups.length)}</button></p>`;
    else if (groups.length === 0) h += `<p class="tp-note">No groups of this kind.</p>`;
    // unplaced and unreadable
    const U = laws.unplaced;
    if (U.items.length) {
      h += `<details class="tp-details" data-key="unplaced"${state.details.has("unplaced") ? " open" : ""}><summary>Not counted above: ${fmt(U.rows)} citations the older citation reader found but could not place as whole words in a clause</summary><p class="tp-sub">Listed as written.</p>${citeList(U.items)}</details>`;
    }
    if (laws.unreadable.length) {
      h += `<details class="tp-details" data-key="unreadable"${state.details.has("unreadable") ? " open" : ""}><summary>Numbers not readable: ${fmt(laws.unreadable.length)} citations, listed as written</summary>${citeList(laws.unreadable)}</details>`;
    }
    h += `<p class="tp-caveat">Read from the citations the site marks in the text of the resolutions it publishes (${a} on). A number is grouped as written and is not checked against any register. A citation is text found, never a statement of legal effect. Citations of ATNI and NCAI resolutions and of court cases are not listed here.</p>`;
    return h;
  }
  /** A list of citations as written, each with its resolution. @param {Array<{text:string,id:number|string,kind:string}>} list */
  function citeList(list) {
    let h = `<table class="tp-table"><caption class="tp-sr">Citations as written, with the resolution that holds each</caption><thead><tr><th scope="col">As written</th><th scope="col">Kind</th><th scope="col">Resolution</th></tr></thead><tbody>`;
    for (const u of list) {
      const r = d.site[String(u.id)];
      const link = siteBase ? `<a href="${esc(`${siteBase}#/r/${Number(u.id)}`)}" aria-label="Open resolution ${esc(r.n)}">${esc(r.n)}</a>` : esc(r.n);
      h += `<tr><th scope="row" class="tp-phrase">${esc(u.text)}</th><td>${esc(KIND_LABEL[u.kind] || u.kind)}</td><td>${link}, ${r.y == null ? "year not recorded" : r.y}</td></tr>`;
    }
    return h + `</tbody></table>`;
  }

  /* ---- part 3: similar wording ---- */
  function wordingHtml() {
    let h = `<h2 id="tp-h-wording" class="tp-h2" tabindex="-1">${esc(COPY.wordingH)}</h2>`;
    if (!hasWording || !corpora.length) return h + `<p class="tp-note">${esc(COPY.notBuilt)}</p>`;
    h += `<p class="tp-sub">${esc(COPY.wordingLead)}</p>`;
    const ci = corpora.findIndex(c => c.id === state.corpus), c = corpora[ci], inp = d.inputs;
    const label = k => (k.id === "text" ? "Resolution text" : "Titles");
    h += `<div class="tp-controls"><div class="tp-fld"><span class="tp-lab" id="tp-corp-l">Wording read from</span><div class="tp-seg" role="group" aria-labelledby="tp-corp-l">`;
    corpora.forEach(k => {
      const yrs = k.years ? `${k.years[0]} to ${k.years[1]}` : "";
      h += `<button type="button" class="tp-btn" data-act="corpus" data-v="${esc(k.id)}" data-fk="corpus|${esc(k.id)}" aria-pressed="${k.id === state.corpus}">${label(k)}${yrs ? `, ${yrs}` : ""}</button>`;
    });
    h += `</div></div>`;
    if (c.built !== false) h += `<div class="tp-fld"><span class="tp-lab" id="tp-ord-l">Ordered by</span><div class="tp-seg" role="group" aria-labelledby="tp-ord-l"><button type="button" class="tp-btn" data-act="order" data-v="count" data-fk="order|count" aria-pressed="${state.order === "count"}">number of resolutions</button><button type="button" class="tp-btn" data-act="order" data-v="years" data-fk="order|years" aria-pressed="${state.order === "years"}">number of years</button></div></div>`;
    h += `</div>`;
    if (c.built === false) return h + `<p class="tp-note">Not built: ${plural(c.documents, "resolution", "resolutions")} is too few to form groups.</p>`;
    const [f, t] = c.years;
    if (c.id === "text") h += `<p class="tp-cov">Read from the titles and the WHEREAS and RESOLVED clauses of the ${fmt(c.documents)} resolutions this site publishes, ${f} to ${t}. Clauses repeated word for word in ${fmt(c.params.repeated_clause_floor ?? 5)} or more resolutions are left out. Nothing before ${f}.</p>`;
    else h += `<p class="tp-cov">Read from the titles in The Resolution Library: ${fmt(c.documents)} resolutions with a title, ${f} to ${t} (${fmt(Math.max(0, inp.library_rows - inp.library_titled))} have no title in the record). Titles are short, so most join no group. The Resolution Library was built by Wyatt Ash-Milby at ATNI.</p>`;
    const order = c.groups.map((g, gi) => ({ g, gi }));
    if (state.order === "years") order.sort((x, y) => y.g.years_present - x.g.years_present || y.g.n - x.g.n || x.gi - y.gi);
    const shown = order.slice(0, state.cardsShown);
    h += `<ol class="tp-cards">`;
    shown.forEach(({ g, gi }, j) => { h += cardHtml(c, ci, g, gi, j === state.cardFresh); });
    h += `</ol>`;
    if (shown.length < order.length) h += `<p><button type="button" class="tp-btn" data-act="cardall" data-fk="cardall">Show all ${fmt(order.length)}</button></p>`;
    const u = c.ungrouped.length;
    h += `<div class="tp-ungrouped"><h3 class="tp-h3" id="tp-un-h">${fmt(u)} ${u === 1 ? "resolution joins" : "resolutions join"} no group</h3><p class="tp-sub">They are listed here and never placed in a group.</p>`;
    if (u) h += `<p>${countBtn(u, `wu:${ci}`, "ungrouped", `${res(u)} join no group`, "tp-big-sm")} <span class="tp-inline">${u === 1 ? "resolution" : "resolutions"}, open the list</span></p>`;
    h += slotDiv(`wu:${ci}`) + `</div>`;
    const p = c.params, pk = d.wording.packages;
    h += `<details class="tp-details" data-key="method"${state.details.has("method") ? " open" : ""}><summary>How the groups are made</summary><p class="tp-method">How the groups are made: each resolution's words are counted (TF-IDF), reduced to ${fmt(p.components)} dimensions with a fixed seed (truncated SVD), and joined into groups by average similarity (average linkage on cosine distance, cut at ${esc(p.max_distance)}). Groups are joined while their average similarity stays above ${esc((1 - Number(p.max_distance)).toFixed(1))}, so two individual resolutions in one group can be less alike than that. A group needs ${fmt(p.group_floor)} or more resolutions and ${fmt(p.min_words)} or more words that appear in at least half its resolutions and at least three times as often as in all of them. Built with numpy ${esc(pk.numpy)}, SciPy ${esc(pk.scipy)} and scikit-learn ${esc(pk["scikit-learn"])}; the same inputs give the same groups.</p></details>`;
    return h;
  }
  function cardHtml(c, ci, g, gi, first) {
    const ys = yearsOf(g.by_year);
    const [a, b] = c.years;
    const spec = `w:${ci}:${gi}`;
    const o = { lo: a, hi: b, rows: g.by_year, small: true, spec: y => `${spec}:y:${y}`, label: (y, n) => `${groupName(g)}, ${y == null ? "year not recorded" : y}: ${res(n)}`, tag: `wy${ci}${gi}` };
    let h = `<li class="tp-card${state.list && state.list.slot === `w:${ci}:${gi}` ? " tp-card-open" : ""}" aria-labelledby="tp-g-${ci}-${gi}"><div class="tp-card-top"><p class="tp-badge">${esc(COPY.notReviewed)}</p></div>`;
    h += `<h3 class="tp-h3" id="tp-g-${ci}-${gi}"${first ? ' tabindex="-1" data-first="1"' : ""}>${fmt(g.n)} ${g.n === 1 ? "resolution" : "resolutions"}, ${esc(span(ys))}, in ${g.years_present === 1 ? "1 year" : `${fmt(g.years_present)} years`}</h3>`;
    h += `<p class="tp-words-l">Words:</p><ul class="tp-words">${g.words.map(w => `<li>${esc(w.w)} <span class="tp-in">(in ${fmt(w.in)} of ${fmt(g.n)})</span></li>`).join("")}</ul>`;
    h += `<p class="tp-open">${countBtn(g.n, `${spec}:all`, "card", `${groupName(g)}: ${res(g.n)}`, "tp-big-sm")} <span class="tp-inline">${g.n === 1 ? "resolution" : "resolutions"}, open the list</span></p>`;
    const key = `yr:w:${ci}:${gi}`;
    h += `<div class="tp-chart tp-chart-sm">${chartSvg(o)}</div>`;
    h += `<details class="tp-details tp-ydetails" data-key="${key}"${state.details.has(key) ? " open" : ""}><summary>Counts by year</summary>${yearTable({ ...o, caption: `${groupName(g)}: resolutions by year` })}</details>${slotDiv(`w:${ci}:${gi}`)}</li>`;
    return h;
  }

  /* ---- painting ---- */
  const SECTIONS = { issues: issuesHtml, laws: lawsHtml, wording: wordingHtml };
  /** Redraws one section and puts focus back on the control that had it. @param {string} name @param {string} [focusKey] */
  function paint(name, focusKey) {
    const el = $(`[data-section="${name}"]`);
    if (!el) return;
    const keep = focusKey ?? (root.contains(document.activeElement) ? document.activeElement?.getAttribute?.("data-fk") : null);
    el.innerHTML = SECTIONS[name]();
    if (keep) {
      const t = [...el.querySelectorAll("[data-fk]")].find(x => x.getAttribute("data-fk") === keep);
      if (t) t.focus({ preventScroll: true });
    }
  }
  const paintAll = () => { for (const n of Object.keys(SECTIONS)) paint(n); };

  function openList(spec, openerKey) {
    const r = resolve(spec);
    if (!r) return;
    const prev = state.list ? sectionOf(state.list.slot) : null;
    state.list = { slot: r.slot, title: r.title, src: r.src, ids: r.ids, shown: PAGE, opener: openerKey };
    if (prev && prev !== sectionOf(r.slot)) paint(prev, "");
    paint(sectionOf(r.slot), "list-head");
    const head = root.querySelector('[data-fk="list-head"]');
    head?.scrollIntoView({ block: "nearest" });
    say(`${res(r.ids.length)} listed.`);
  }
  function closeList() {
    const L = state.list;
    if (!L) return;
    state.list = null;
    paint(sectionOf(L.slot), L.opener);
    const back = [...root.querySelectorAll("[data-fk]")].find(x => x.getAttribute("data-fk") === L.opener);
    back?.focus();
    say("List closed.");
  }

  /* ---- events (one click, one change and one toggle handler, all on root) ---- */
  function onClick(e) {
    const t = e.target instanceof Element ? e.target.closest("[data-act]") : null;
    if (!t || !root.contains(t) || t.tagName === "SELECT") return;
    const act = t.getAttribute("data-act"), v = t.getAttribute("data-v");
    if (act === "open") openList(t.getAttribute("data-open"), t.getAttribute("data-fk") || "");
    else if (act === "close") closeList();
    else if (act === "more") { state.list.shown += PAGE; paint(sectionOf(state.list.slot), "list-more"); }
    else if (act === "jump") { const h = $(`#${t.getAttribute("data-target")}`); h?.scrollIntoView({ block: "start" }); h?.focus({ preventScroll: true }); }
    else if (act === "law") { const i = Number(t.getAttribute("data-law")); if (state.lawOpen.has(i)) state.lawOpen.delete(i); else state.lawOpen.add(i); paint("laws", `law|${i}`); }
    else if (act === "lawsort") { state.lawSort = v; state.lawShown = LAW_FIRST; state.lawFresh = -1; paint("laws", `lawsort|${v}`); say(`Ordered ${v === "count" ? "by number of resolutions" : "by kind and number"}.`); }
    else if (act === "lawall") { state.lawShown = 1e9; state.lawFresh = LAW_FIRST; paint("laws", ""); const f = root.querySelector('[data-section="laws"] .tp-laws [data-first="1"]'); f?.focus(); say(`All ${fmt(sortedGroups().length)} groups shown.`); }
    else if (act === "corpus") { state.corpus = v; state.cardsShown = CARD_FIRST; state.cardFresh = -1; paint("wording", `corpus|${v}`); say(`Showing wording read from ${v === "text" ? "resolution text" : "titles"}.`); }
    else if (act === "order") { state.order = v; state.cardsShown = CARD_FIRST; state.cardFresh = -1; paint("wording", `order|${v}`); say(`Ordered ${v === "count" ? "by number of resolutions" : "by number of years"}.`); }
    else if (act === "cardall") {
      const c = corpora.find(k => k.id === state.corpus);
      state.cardsShown = 1e9; state.cardFresh = CARD_FIRST; paint("wording", "");
      root.querySelector('[data-section="wording"] [data-first="1"]')?.focus();
      say(`All ${fmt(c.groups.length)} groups shown.`);
    }
  }
  function onChange(e) {
    const t = e.target;
    if (t instanceof Element && t.getAttribute("data-act") === "lawkind") {
      state.lawKind = /** @type {HTMLSelectElement} */ (t).value; state.lawShown = LAW_FIRST; state.lawFresh = -1;
      paint("laws", "lawkind");
      say(`${fmt(sortedGroups().length)} groups shown.`);
    }
  }
  function onToggle(e) {
    const t = e.target;
    if (t instanceof Element && t.tagName === "DETAILS") {
      const k = t.getAttribute("data-key");
      if (k) { if (/** @type {HTMLDetailsElement} */ (t).open) state.details.add(k); else state.details.delete(k); }
    }
  }
  root.addEventListener("click", onClick);
  root.addEventListener("change", onChange);
  root.addEventListener("toggle", onToggle, true);

  /* ---- first draw ---- */
  const parts = [["issues", "tp-h-issues", COPY.issuesH], ["laws", "tp-h-laws", COPY.lawsH], ["wording", "tp-h-wording", COPY.wordingH]];
  root.innerHTML = `<svg class="tp-defs" width="0" height="0" aria-hidden="true" focusable="false"><defs><pattern id="tp-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(135)"><rect class="tp-hatch-bg" width="5" height="5"/><line class="tp-hatch-line" x1="0" y1="0" x2="0" y2="5"/></pattern></defs></svg>`
    + `<p class="tp-lead">${esc(COPY.lead)}</p>`
    + `<nav class="tp-jump" aria-label="On this tab">${parts.map(([n, id, label]) => `<button type="button" class="tp-btn" data-act="jump" data-target="${id}">${esc(label)}</button>`).join("")}</nav>`
    + `<div class="tp-live tp-sr" role="status" aria-live="polite"></div>`
    + parts.map(([n]) => `<section class="tp-section" data-section="${n}" aria-label="${esc(parts.find(p => p[0] === n)[2])}"></section>`).join("");
  paintAll();
  return { destroy() { root.removeEventListener("click", onClick); root.removeEventListener("change", onChange); root.removeEventListener("toggle", onToggle, true); } };
}

/* ---------------------------------------------------------------------------------------------------------- */

/** Draws the tab into root. Reads DATA_URL once per page load when ctx.data is absent. Fails closed: a read error or
 *  any validate problem shows one sentence and nothing else. A second call on the same root replaces the first.
 *  @param {HTMLElement} root @param {TopicsCtx} [ctx] @returns {Promise<void>} */
export async function render(root, ctx = {}) {
  views.get(root)?.destroy();
  views.delete(root);
  root.classList.add("tp");
  root.innerHTML = `<p class="tp-note" role="status">Reading the counts.</p>`;
  let data;
  try { data = ctx.data ?? (await loadData()); } catch { data = null; }
  if (!data || validate(data).length) {
    root.innerHTML = `<p class="tp-fail" role="alert">${esc(COPY.failed)}</p>`;
    return;
  }
  views.set(root, createView(root, data, ctx));
}
