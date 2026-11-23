/* Views of the Analysis page mockup. Each view returns an HTML string; every value from the data passes through esc().
   Charts that depend on the width of their box are drawn by drawers[name](el, S) after the view is in the page. */
import { esc, fmt, plural, ofWhole, covState, unrecordedRuns, yearBarsSvg, rowBarsHtml, heatmapHtml, sparkSvg, dotPlotSvg } from "./charts.js";
import * as DT from "./data.js";
const { D, KINDS, KIND_LABEL, FIELDS, makeSpec } = DT;

const kindLabel = k => KIND_LABEL[k] ?? "No convention recorded";
const yearsIn = f => D.years.filter(y => y >= f.y0 && y <= f.y1);
const span = f => (f.y0 === f.y1 ? String(f.y0) : `${f.y0} to ${f.y1}`);
const cname = key => D.cm[key]?.name ?? key;
const qnum = q => (q ? `question ${parseInt(String(q).replace(/\D/g, ""), 10)}` : "");
const nr = `<span class="nr">not recorded</span>`;
const median = a => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const num1 = n => (Number.isInteger(n) ? fmt(n) : n.toFixed(1));
const slug = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-");

/* "2014 to 2025, 2007" style runs from a list of years */
function runs(list) {
  const a = [...list].sort((x, y) => x - y), out = [];
  for (let i = 0; i < a.length;) { let j = i; while (j + 1 < a.length && a[j + 1] === a[j] + 1) j++; out.push(i === j ? String(a[i]) : j === i + 1 ? `${a[i]} and ${a[j]}` : `${a[i]} to ${a[j]}`); i = j + 1; }
  return out;
}
/* Scheduled conventions with no resolution in the Library (a missing convention, never a zero). */
function missingConventions() {
  const km = DT.kindMatrix(""), out = [];
  for (const y of D.years) if (y > D.yMin) for (const k of ["winter", "midyear", "annual"]) if (km[D.yi.get(y)][k] === 0) out.push(`${y} ${kindLabel(k)}`);
  return out;
}
const join = a =>(a.length <= 1 ? a.join("") : a.length === 2 ? a.join(" and ") : `${a.slice(0, -1).join(", ")}, and ${a[a.length - 1]}`);

/* ---------------------------------------------------------------------------------------------------------- */
/* shared pieces                                                                                               */
const src = () => `<p class="source">Source: <a href="#credit" data-goto="credit">The Resolution Library</a>, an ATNI spreadsheet of ${fmt(D.total)} numbered resolutions, ${D.yMin} to ${D.yMax}, built by Wyatt Ash-Milby at ATNI.${D.builtAt ? ` Counted ${esc(D.builtAt)}.` : ""}</p>`;

const cnt = (n, spec, label) => (n > 0 ? `<button type="button" class="count" data-list="${esc(spec)}" aria-label="${esc(label)}: ${fmt(n)} resolutions. Open the list.">${fmt(n)}</button>` : `<span class="zero">0</span>`);

function table(id, caption, head, rows, o = {}) {
  const numFrom = o.numFrom ?? 1;
  return `<div class="tbl-wrap" tabindex="0" role="region" aria-label="${esc(caption)}"><table class="data" id="${esc(id)}"><caption class="sr-only">${esc(caption)}</caption><thead><tr>${head.map((h, i) => `<th scope="col"${i >= numFrom && !o.left ? ' class="num"' : ""}>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map((c, i) => (i === 0 ? `<th scope="row">${c}</th>` : `<td${i >= numFrom && !o.left ? ' class="num"' : ""}>${c}</td>`)).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function sec(o) {
  const L = o.level || 3;
  const nm = o.h3 || o.h2 || "";
  const H = (lvl, id, t) => `<h${lvl} id="${id}">${t}</h${lvl}>`;
  return `<section class="vs" id="${o.id}" aria-labelledby="${o.id}-h">
    ${o.h2 ? H(2, o.id + "-h", o.h2) : ""}
    ${o.h3 ? H(o.h2 ? 3 : L, o.h2 ? o.id + "-h3" : o.id + "-h", o.h3) : ""}
    ${o.sub ? `<p class="sub">${o.sub}</p>` : ""}
    ${o.summary ? `<p class="sr-only" id="${o.id}-sum">${esc(o.summary)}</p>` : ""}
    ${o.chart ? `${o.skip === false ? "" : `<a class="skip-link" href="#${o.id}-after">Skip this chart</a>`}<div class="chart" data-chart="${o.chart}" data-sum="${o.id}-sum" id="${o.id}-chart"></div>` : ""}
    ${o.chartHtml || ""}
    ${o.key || ""}
    ${(o.cov || []).map(p => `<p class="cov-sentence">${p}</p>`).join("")}
    <div class="acts" id="${o.id}-after">
      ${o.table ? `<details class="tbl"><summary>Show table<span class="sr-only">: ${nm}</span></summary>${o.table}</details>` : ""}
      ${o.csv ? `<button type="button" class="btn small quiet" data-csv="${esc(o.csv)}" data-csv-name="${esc(o.id)}">Download this table (CSV)<span class="sr-only">: ${nm}</span></button>` : ""}
      ${o.actions || ""}
    </div>
    ${o.extra || ""}
    ${o.caveat ? `<p class="caveat">${o.caveat}</p>` : ""}
    ${o.nosrc ? "" : src()}
  </section>`;
}

const keyHtml = items => `<ul class="key" aria-label="Key">${items.map(i => `<li><span class="sw ${i.cls}" aria-hidden="true"></span>${esc(i.label)}</li>`).join("")}</ul>`;
const COV_KEY = [{ cls: "cov-full", label: "Recorded on every resolution" }, { cls: "cov-part", label: "Recorded on some" }, { cls: "cov-none", label: "Not recorded" }];

/* ---------------------------------------------------------------------------------------------------------- */
/* the list behind a number                                                                                     */
export function lrow(r, S) {
  const title = DT.titleText(r);
  const items = [
    ["Committee", r.cl ? esc(r.cl) : nr],
    ["Convention", r.cv ? esc(r.cv) : nr],
  ];
  if (S.names && r.pb) items.push(["Prepared By", esc(r.pb)]);
  const act = r.s
    ? `<a class="btn small" href="#/r/${r.s}" data-live="the resolution page for ${esc(r.n)}" aria-label="Open resolution ${esc(r.n)}">Open</a><button type="button" class="btn small collect" data-rkey="${esc(r.rk)}" aria-pressed="false" aria-label="Collect resolution ${esc(r.n)}">Collect</button>`
    : `${r.u ? `<a class="btn small quiet" href="${esc(r.u)}" rel="noopener" aria-label="Resolution ${esc(r.n)} on atnitribes.org">On atnitribes.org</a>` : ""}<span class="l-note">This site holds no text for this resolution; The Resolution Library lists it.</span>`;
  return `<li class="lrow"><span class="l-num">${esc(r.n)}</span><div class="l-body"><p class="l-title">${title ? esc(title) : `<span class="nr">No title in the record</span>`}</p><dl class="l-meta">${items.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl></div><div class="l-act">${act}</div></li>`;
}
export const lrows = (rows, S, from = 0, n = 100) => rows.slice(from, from + n).map(r => lrow(r, S)).join("");

/* ---------------------------------------------------------------------------------------------------------- */
/* data for the year charts                                                                                     */
function yearData(S, mode) {
  const f = S.f, km = DT.kindMatrix(f.c), rows = [];
  const keys = f.k ? [f.k] : ["winter", "midyear", "annual", "executive", "none"];
  let max = 1;
  for (const y of yearsIn(f)) {
    const m = km[D.yi.get(y)];
    const conf = f.k ? m[f.k] : m.total - m.wait;
    const wait = f.c ? (f.k ? m.wk[f.k] || 0 : m.wait) : 0;
    const total = conf + wait;
    const segs = [];
    const lay = f.c ? "c" : "";
    if (mode === "hero") segs.push({ key: "total", n: conf, label: `${y}: ${fmt(conf)} resolutions`, spec: makeSpec({ y, k: f.k, c: f.c, ly: lay }) });
    else for (const k of keys) segs.push({ key: k, n: m[k], label: `${y}, ${kindLabel(k)}: ${fmt(m[k])} of ${fmt(total)} resolutions`, spec: makeSpec({ y, k, c: f.c, ly: lay }) });
    if (wait) segs.push({ key: "waiting", n: wait, label: `${y}: ${fmt(wait)} with committee labels waiting for ATNI`, spec: makeSpec({ y, k: f.k, c: f.c, ly: "w" }) });
    const so = !f.k && !f.c ? D.siteOnly.get(y) || 0 : 0;
    rows.push({ year: y, total, segs, outline: so ? { key: "siteonly", n: so, label: `${y}: ${fmt(so)} numbered resolutions on this site that the Library does not list` } : null, yearSpec: makeSpec({ y, k: f.k, c: f.c, ly: f.c ? "b" : "" }) });
    max = Math.max(max, total + so);
  }
  return { rows, max };
}
function covCells(S, field, yrs) {
  const m = DT.covMatrix(field, S.f.k, S.f.c);
  return yrs.map(y => {
    const c = m[D.yi.get(y)];
    const st = covState(c.n, c.total);
    const text = c.total === 0 ? `${y}: no resolutions in this selection` : c.n === 0 ? `${y}: ${FIELDS[field].rec} for none of ${fmt(c.total)} resolutions` : `${y}: ${FIELDS[field].rec} for ${ofWhole(c.n, c.total)} resolutions`;
    return { state: st, share: c.total ? c.n / c.total : 0, text };
  });
}
const NOUN = { title: "Title", committee: "Committee", committeeConfirmed: "A confirmed committee", preparer: "Prepared By", convention: "Convention", outcome: "Outcome", ncai: "TO NCAI", permalink: "A permalink", site: "Text on this site" };
function covSentence(S, field) {
  const m = DT.covMatrix(field, S.f.k, S.f.c), f = S.f;
  const n = DT.sumBy(m, f, r => r.n), t = DT.sumBy(m, f, r => r.total);
  return `${esc(NOUN[field] || FIELDS[field].name)} is recorded for ${ofWhole(n, t)} resolutions.`;
}
let covPick = "preparer", risen = false;
export const setCovPick = v => { covPick = v; };

/* One reading of a year chart for its text alternative: the peak, the low, and the years a field is not recorded. */
function readingOf(d, allCov) {
  const rows = d.rows.filter(r => r.total > 0);
  if (!rows.length) return "";
  const hi = Math.max(...rows.map(r => r.total)), lo = Math.min(...rows.map(r => r.total));
  const at = n => join(rows.filter(r => r.total === n).map(r => r.year));
  let t = rows.length === 1 ? `Only ${rows[0].year} has resolutions in this selection (${fmt(hi)}).`
    : hi === lo ? `Every year with resolutions has ${fmt(hi)}.`
    : `Most in ${at(hi)} (${fmt(hi)}), fewest in ${at(lo)} (${fmt(lo)}).`;
  const none = d.rows.length - rows.length;
  if (none) t += ` ${plural(none, "year has", "years have")} none.`;
  for (const [fld, cells] of allCov) {
    const r = unrecordedRuns(cells, d.rows.map(x => x.year));
    if (r.length) t += ` ${NOUN[fld] || FIELDS[fld].name} is not recorded for any resolution in ${join(r)}.`;
  }
  return t;
}
function drawYearChart(el, S, mode, fields) {
  const d = yearData(S, mode), yrs = d.rows.map(r => r.year), id = el.dataset.sum.replace(/-sum$/, "");
  const sumEl = document.getElementById(id + "-sum");
  if (sumEl) {
    if (sumEl.dataset.base === undefined) sumEl.dataset.base = sumEl.textContent.replace(/ A table with the same numbers follows\.$/, "");
    sumEl.textContent = `${sumEl.dataset.base} ${readingOf(d, fields.map(fld => [fld, covCells(S, fld, yrs)]))} Show table, below the chart, has the same numbers.`.replace(/\s+/g, " ");
  }
  const heroH = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--resist-hero-height")) || 200;
  const kindKey = [{ cls: "s-winter", label: "Winter" }, { cls: "s-midyear", label: "Mid-Year" }, { cls: "s-annual", label: "Annual" }, { cls: "s-executive", label: "Executive Board" }];
  let key = [];
  if (mode === "hero") key.push({ cls: "s-total", label: "Resolutions numbered" });
  else key = S.f.k ? kindKey.filter(k => k.cls === "s-" + S.f.k) : kindKey.slice();
  if (S.f.c) key.push({ cls: "s-waiting", label: "Committee label waiting for ATNI" });
  if (mode === "hero" && !S.f.k && !S.f.c) key.push({ cls: "s-siteonly", label: "Numbered on this site, not in the Library" });
  if (mode !== "hero" && !S.f.k) key.push({ cls: "s-none", label: "Convention not recorded" });
  if (S.wide) {
    const strips = fields.map(fld => ({ name: FIELDS[fld].rec, cells: covCells(S, fld, yrs) }));
    el.innerHTML = yearBarsSvg({ id, width: el.clientWidth, height: heroH, rows: d.rows, max: d.max, href: S.listHref, strips, rise: mode === "hero" && !risen });
    if (mode === "hero") risen = true;
    key = key.concat(COV_KEY);
    el.insertAdjacentHTML("beforeend", keyHtml(key));
  } else {
    const fld = fields.includes(covPick) ? covPick : fields[0];
    const cells = covCells(S, fld, yrs);
    const rows = d.rows.map((r, i) => ({ ...r, text: fmt(r.total) + (r.outline ? ` <span class="rb-plus">+ ${fmt(r.outline.n)}</span>` : ""), cov: cells[i] }));
    el.innerHTML = `<div class="cov-pick"><label for="${id}-cp">Field recorded beside each year</label><select id="${id}-cp" data-cov-pick>${fields.map(x => `<option value="${x}"${x === fld ? " selected" : ""}>${esc(FIELDS[x].rec)}</option>`).join("")}</select></div>`
      + rowBarsHtml({ id, rows, max: d.max, covName: FIELDS[fld].rec })
      + keyHtml(key.concat(COV_KEY));
  }
}

function yearTable(S, mode) {
  const d = yearData(S, mode), f = S.f;
  const head = ["Year"];
  if (mode === "hero") head.push("Resolutions numbered");
  else (f.k ? [f.k] : ["winter", "midyear", "annual", "executive", "none"]).forEach(k => head.push(k === "none" ? "Convention not recorded" : kindLabel(k)));
  if (f.c) head.push("Label waiting for ATNI");
  head.push("Total");
  if (!f.k && !f.c) head.push("Numbered on this site, not in the Library");
  const fieldsFor = mode === "hero" ? ["title", "committee", "preparer"] : ["convention"];
  fieldsFor.forEach(x => head.push(FIELDS[x].rec));
  const cov = fieldsFor.map(x => DT.covMatrix(x, f.k, f.c));
  const rows = d.rows.map(r => {
    const row = [""];
    row[0] = `<button type="button" class="count" data-list="${esc(r.yearSpec)}" aria-label="${r.year}: open the list">${r.year}</button>`;
    for (const sg of r.segs) row.push(sg.n === 0 ? `<span class="zero">0</span>` : cnt(sg.n, sg.spec, sg.label.split(":")[0]));
    row.push(fmt(r.total));
    if (!f.k && !f.c) row.push(r.outline ? fmt(r.outline.n) : `<span class="zero">0</span>`);
    cov.forEach(m => { const c = m[D.yi.get(r.year)]; row.push(c.total === 0 ? "" : c.n === 0 ? nr : ofWhole(c.n, c.total)); });
    return row;
  });
  return table(`t-${mode}`, mode === "hero" ? "Resolutions numbered each year" : "Resolutions by convention", head, rows);
}

/* ---------------------------------------------------------------------------------------------------------- */
/* committee bars (overview) and the committee grid                                                             */
function committeeTotals(S) {
  const f = S.f, mx = DT.commMatrix(f.k), yrs = yearsIn(f);
  const rows = [];
  for (const cm of D.agg.committees) {
    let c = 0, w = 0;
    for (const y of yrs) { const [a, b] = mx.get(cm.key, y); c += a; w += b; }
    if (c + w > 0) rows.push({ key: cm.key, name: cm.name, c, w });
  }
  rows.sort((a, b) => b.c + b.w - (a.c + a.w) || a.name.localeCompare(b.name));
  let blank = 0, other = 0;
  for (const y of yrs) { blank += mx.blank.get(y); other += mx.other.get(y); }
  return { rows, blank, other };
}

function committeeBars(S) {
  const f = S.f, t = committeeTotals(S);
  const max = Math.max(1, ...t.rows.map(r => r.c + r.w), t.blank + t.other);
  const rows = f.c ? t.rows.filter(r => r.key === f.c) : t.rows;
  let h = `<ol class="cbars" role="list" id="ov-comm-list" aria-labelledby="ov-comm-sum">`;
  for (const r of rows) {
    const on = f.c === r.key;
    h += `<li class="cb"><div class="cb-name"><button type="button" class="link-btn" data-setc="${esc(on ? "" : r.key)}" aria-pressed="${on}" aria-label="${on ? "Show all committees" : `Choose ${esc(r.name)} for every chart`}">${esc(r.name)}</button> <a class="cb-page" href="${esc(S.hrefView("committees", { cm: r.key }))}" aria-label="Committee page for ${esc(r.name)}">page</a></div>`
      + `<div class="cb-track">${r.c ? `<button type="button" class="hseg s-total" style="width:${(r.c / max * 100).toFixed(2)}%" data-list="${esc(makeSpec({ c: r.key, ly: "c", k: f.k, y0: f.y0, y1: f.y1 }))}" data-tip="${esc(r.name)}: ${fmt(r.c)} resolutions" aria-label="${esc(r.name)}: ${fmt(r.c)} resolutions"></button>` : ""}`
      + `${r.w ? `<button type="button" class="hseg s-waiting" style="width:${(r.w / max * 100).toFixed(2)}%" data-list="${esc(makeSpec({ c: r.key, ly: "w", k: f.k, y0: f.y0, y1: f.y1 }))}" data-tip="${esc(r.name)}: ${fmt(r.w)} with labels waiting for ATNI" aria-label="${esc(r.name)}: ${fmt(r.w)} with labels waiting for ATNI"></button>` : ""}</div>`
      + `<div class="cb-n">${fmt(r.c)}<span class="cb-w"> confirmed${r.w ? `, ${fmt(r.w)} waiting` : ""}</span></div></li>`;
  }
  if (!f.c) {
    const nn = t.blank + t.other;
    h += `<li class="cb cb-none"><div class="cb-name"><span>Names no committee</span></div><div class="cb-track"><button type="button" class="hseg s-none" style="width:${(nn / max * 100).toFixed(2)}%" data-list="${esc(makeSpec({ cn: "any", k: f.k, y0: f.y0, y1: f.y1 }))}" data-tip="${plural(nn, "resolution names", "resolutions name")} no committee" aria-label="${plural(nn, "resolution names", "resolutions name")} no committee"></button></div><div class="cb-n">${fmt(nn)}</div></li>`;
  }
  return h + `</ol>`;
}

/* ---------------------------------------------------------------------------------------------------------- */
/* word lookup                                                                                                  */
function wordRows(S, q) {
  const toks = DT.tokenize(q);
  return D.rows.filter(r => DT.selects(r, S.f.k, S.f.c) && r.y >= S.f.y0 && r.y <= S.f.y1 && toks.every(t => r._w.has(t)));
}
export function wordAnswer(S) {
  const q = (S.q.get("w") || "").trim();
  if (!q) return "";
  const toks = DT.tokenize(q);
  if (!toks.length) return `<p class="empty-line">No word to look up. Type a word from a title.</p>`;
  const hits = wordRows(S, q), f = S.f;
  const spec = makeSpec({ w: toks.join(" "), k: f.k, c: f.c, ly: f.c ? "b" : "", y0: f.y0, y1: f.y1 });
  if (!hits.length) return `<div class="empty-state"><h3>No Titles Matched</h3><p>No title uses ${esc(toks.join(" "))} in this selection. Clear a filter or widen the years to see counts again.</p><p><a class="btn small" href="${esc(S.href({ y0: undefined, y1: undefined, k: undefined, c: undefined }))}">Clear filters</a></p></div>`;
  const byY = new Map(); for (const r of hits) byY.set(r.y, (byY.get(r.y) || 0) + 1);
  const rare = hits.length <= 6;
  const unit = rare ? DT.BANDS.map(([a, z]) => ({ label: `${a} to ${z}`, y0: Math.max(a, f.y0), y1: Math.min(z, f.y1), n: hits.filter(r => r.y >= a && r.y <= z).length })).filter(b => b.y0 <= b.y1)
    : yearsIn(f).map(y => ({ label: String(y), y0: y, y1: y, n: byY.get(y) || 0 }));
  const max = Math.max(1, ...unit.map(u => u.n));
  const rows = unit.map(u => ({ year: u.label, total: u.n, segs: [{ key: "total", n: u.n, label: `${u.label}: ${fmt(u.n)} titles`, spec: makeSpec({ w: toks.join(" "), k: f.k, c: f.c, ly: f.c ? "b" : "", y0: u.y0, y1: u.y1 }) }], yearSpec: makeSpec({ w: toks.join(" "), k: f.k, c: f.c, ly: f.c ? "b" : "", y0: u.y0, y1: u.y1 }) }));
  return `<div class="word-answer"><h3>${plural(hits.length, "title uses", "titles use")} the ${toks.length > 1 ? "words" : "word"} “${esc(toks.join(" "))}”</h3>
    <p class="sub">${rare ? "A bar for each span of years, because the word is rare." : "One bar for each year."} ${esc(span(f))}. Whole words, in any letter case, in the title only.</p>
    <p class="sr-only" id="word-sum">Bar chart of titles using the word ${esc(toks.join(" "))}, by ${rare ? "span of years" : "year"}.</p>
    ${rowBarsHtml({ id: "word", rows, max })}
    <div class="acts"><button type="button" class="btn small" data-list="${esc(spec)}">Show the list (${fmt(hits.length)})</button>
      <a class="btn small quiet" href="#/?q=${encodeURIComponent(toks.join(" "))}" data-live="the search page, with “${esc(toks.join(" "))}” entered">Search the full text for this word</a></div>
    <p class="caveat">A word match is a text match in the title, never what a resolution is about. ${plural(D.agg.coverage_by_year.all.resolutions - D.agg.coverage_by_year.all.with_title, "resolution has", "resolutions have")} no title in the record.</p></div>`;
}
const wordBox = (S, idp) => `<form class="wordbox" role="search" data-wordform><label for="${idp}-q">Look up a word in the titles</label><div class="wb-row"><input id="${idp}-q" name="w" type="search" autocomplete="off" spellcheck="false" placeholder="A word from a title" value="${esc(S.q.get("w") || "")}"><button type="submit" class="btn">Look up</button></div></form><div class="word-out" aria-live="polite" data-wordout>${wordAnswer(S)}</div>`;

/* ---------------------------------------------------------------------------------------------------------- */
/* OVERVIEW                                                                                                     */
const TAB_BLURBS = [
  ["years", "Years and Conventions", "Resolutions each year and at each convention, with outcomes and the TO NCAI column (marked to go on to the National Congress of American Indians, NCAI) where the record has them."],
  ["committees", "Committees", "Resolutions by committee and year, committee labels as written, and Wyatt Ash-Milby's own counts."],
  ["people", "People", "Names in the Prepared By column, as the Library records them."],
  ["words", "Words and Titles", "Words in titles, and titles that appear more than once."],
  ["record", "The Record", "What the Library holds, year by year, and the files behind these counts."],
];
function limitsPanel() {
  const L = D.agg.meta.limits, c = D.agg.meta.counts;
  return `<section class="vs" id="limits" aria-labelledby="limits-h"><h2 id="limits-h">What This Page Counts and Leaves Out</h2>
    <p class="sub">${fmt(c.resolutions_listed)} resolutions are listed. ${fmt(c.resolutions_in_library_rows - c.resolutions_listed)} numbered row, the second ${esc(c.excluded.number)}, is left out. Only decisions ATNI has made are applied; the rest are drawn separately and labelled with their question number. On this page, “the Library” and “the workbook” are the same file: The Resolution Library.</p>
    <ul class="plain">${L.map(x => `<li>${esc(x)}</li>`).join("")}</ul></section>`;
}
export function view_overview(S) {
  const f = S.f, c = D.agg.meta.counts;
  const hero = sec({
    id: "hero", h2: `${fmt(DT.sumBy(DT.kindMatrix(f.c), f, r => (f.k ? r[f.k] : r.total - r.wait)))} ${f.c ? `${esc(cname(f.c))} resolutions` : "resolutions"}, ${esc(span(f))}`, h3: "Resolutions numbered each year",
    sub: `One bar for each year, ${esc(span(f))}. Each bar opens the list of resolutions behind it.`,
    summary: `Bar chart of resolutions numbered each year, ${span(f)}. A table with the same numbers follows.`,
    chart: "hero", table: yearTable(S, "hero"), csv: "t-hero",
    cov: [covSentence(S, "preparer"), covSentence(S, "committee"), covSentence(S, "title")],
    caveat: `Counted from The Resolution Library. A resolution is counted once, in the year of its number. Before 2007 this site holds no text; the Library lists titles. An outlined segment is a numbered resolution this site holds and the Library does not list.`,
  });
  const t = committeeTotals(S);
  const cm = sec({
    id: "ov-comm", h2: "Committees, as the Record Names Them", h3: "Resolutions by committee",
    sub: `Each resolution is counted under one committee, as the workbook's Committee column names it, ${esc(span(f))}. Sorted by number of resolutions. Choose a committee to filter every chart.`,
    summary: `Bars of resolutions by committee, ${span(f)}, sorted by number of resolutions.`,
    chartHtml: committeeBars(S), skip: false,
    key: keyHtml([{ cls: "s-total", label: "Confirmed committee" }, { cls: "s-waiting", label: "Label waiting for ATNI" }, { cls: "s-none", label: "Names no committee" }]),
    cov: [`${fmt(t.blank + t.other)} resolutions name no committee: ${fmt(t.blank)} have a blank cell and ${fmt(t.other)} say Off the Floor, Executive Board or another body.`],
    table: table("t-ov-comm", "Resolutions by committee", ["Committee", "Confirmed", "Waiting for ATNI"], [...t.rows.map(r => [esc(r.name), cnt(r.c, makeSpec({ c: r.key, ly: "c", k: f.k, y0: f.y0, y1: f.y1 }), r.name), r.w ? cnt(r.w, makeSpec({ c: r.key, ly: "w", k: f.k, y0: f.y0, y1: f.y1 }), r.name + ", waiting") : `<span class="zero">0</span>`]), ["Names no committee", cnt(t.blank + t.other, makeSpec({ cn: "any", k: f.k, y0: f.y0, y1: f.y1 }), "Names no committee"), ""]]),
    csv: "t-ov-comm",
    caveat: "Hatched counts are committee labels waiting for ATNI to confirm which committee they belong to (questions 1 to 5); no single merged total is printed until ATNI answers.",
  });
  const words = `<section class="vs" id="ov-words" aria-labelledby="ov-words-h"><h2 id="ov-words-h">Which Titles Use a Word?</h2><p class="sub">Look up one word. The answer is a count of titles by year and the list behind it.</p>${wordBox(S, "ov")}${src()}</section>`;
  const tabs = `<section class="vs" id="ov-tabs" aria-labelledby="ov-tabs-h"><h2 id="ov-tabs-h">The Other Views</h2><ul class="tabcards">${TAB_BLURBS.map(([v, name, text]) => `<li><a href="${esc(S.hrefView(v))}">${esc(name)}</a><p>${esc(text)}</p></li>`).join("")}</ul></section>`;
  return hero + cm + words + tabs + limitsPanel();
}

/* ---------------------------------------------------------------------------------------------------------- */
/* YEARS AND CONVENTIONS                                                                                        */
function conventionsBlock(S) {
  const f = S.f, km = DT.kindMatrix(f.c);
  const yrs = yearsIn(f);
  const kinds = f.k ? KINDS.filter(k => k.key === f.k) : KINDS;
  const spec = (y, k) => makeSpec({ y, k, c: f.c, ly: f.c ? "c" : "" });
  let head = `<thead><tr><th scope="col">Year</th>${kinds.map(k => `<th scope="col" class="num">${k.label}</th>`).join("")}${f.k ? "" : `<th scope="col" class="num">Not recorded<span class="sr-only"> (convention)</span></th>`}<th scope="col" class="num">Total</th></tr></thead>`;
  let body = "";
  for (const y of yrs) {
    const m = km[D.yi.get(y)];
    body += `<tr><th scope="row">${y}</th>`;
    for (const k of kinds) {
      const n = m[k.key], sched = k.key !== "executive";
      if (n === 0 && sched && !f.c) body += `<td class="num"><span class="gridcell miss" role="img" aria-label="${y} ${k.label}: ${y === D.yMin && m.none ? "no convention recorded" : "not in the Library"}" data-tip="${y} ${k.label}: ${y === D.yMin && m.none ? "no convention recorded" : "not in the Library"}"></span></td>`;
      else if (n === 0) body += `<td class="num"><span class="zero">0</span></td>`;
      else body += `<td class="num"><button type="button" class="gridcell step-${DT_step(n)}" data-list="${esc(spec(y, k.key))}" aria-label="${y} ${k.label}: ${fmt(n)} resolutions. Open the list.">${fmt(n)}</button></td>`;
    }
    if (!f.k) body += `<td class="num">${m.none ? `<button type="button" class="gridcell none-n" data-list="${esc(spec(y, "none"))}" aria-label="${y}, convention not recorded: ${fmt(m.none)} resolutions. Open the list.">${fmt(m.none)}</button>` : `<span class="zero">0</span>`}</td>`;
    const tot = f.k ? m[f.k] : m.total - m.wait;
    body += `<td class="num"><button type="button" class="count" data-list="${esc(makeSpec({ y, k: f.k, c: f.c, ly: f.c ? "c" : "" }))}" aria-label="${y}: ${fmt(tot)} resolutions. Open the list.">${fmt(tot)}</button></td></tr>`;
  }
  const grid = `<div class="tbl-wrap"><table class="data convgrid" id="t-convgrid"><caption class="sr-only">Resolutions at each convention, one row for each year</caption>${head}<tbody>${body}</tbody></table></div>`;
  // per kind
  const kRows = KINDS.map(k => {
    const ns = yrs.map(y => ({ y, n: km[D.yi.get(y)][k.key] })).filter(x => x.n > 0);
    const tot = ns.reduce((s, x) => s + x.n, 0);
    const big = ns.reduce((a, x) => (x.n > a.n ? x : a), { n: -1 }), small = ns.reduce((a, x) => (x.n < a.n ? x : a), { n: 1e9 });
    return [k.label, fmt(ns.length), cnt(tot, makeSpec({ k: k.key, c: f.c, ly: f.c ? "c" : "", y0: f.y0, y1: f.y1 }), k.label), ns.length ? num1(median(ns.map(x => x.n))) : nr, ns.length ? `${fmt(big.n)} (${big.y} ${k.label})` : nr, ns.length ? `${fmt(small.n)} (${small.y} ${k.label})` : nr];
  });
  const kTable = table("t-kinds", "Sessions and resolutions for each convention kind", ["Kind", "Sessions", "Resolutions", "Median per session", "Largest", "Smallest"], kRows);
  // bands
  const bands = [[2001, 2006], [2007, 2012], [2013, 2018], [2019, 2026]].map(([a, z]) => {
    const ns = []; for (const y of D.years) if (y >= a && y <= z) for (const k of ["winter", "midyear", "annual"]) { const n = km[D.yi.get(y)][k]; if (n > 0) ns.push(n); }
    return [`${a} to ${z}`, fmt(ns.length), ns.length ? num1(median(ns)) : nr];
  });
  const allN = []; for (const y of D.years) for (const k of ["winter", "midyear", "annual"]) { const n = km[D.yi.get(y)][k]; if (n > 0) allN.push(n); }
  const bTable = table("t-bands", "Median resolutions per scheduled session, by span of years", ["Years", "Scheduled sessions", "Median per session"], bands);
  // this year so far
  const last = D.yMax, a = km[D.yi.get(last)], b = km[D.yi.get(last - 1)];
  const held = KINDS.filter(k => a[k.key] > 0);
  const so = held.length ? `${last} so far: ${held.map(k => `${k.label} ${fmt(a[k.key])}`).join(", ")}. At the same point in ${last - 1}: ${held.map(k => `${k.label} ${fmt(b[k.key])}`).join(", ")}.` : "";
  // committee by kind
  const ck = new Map();
  for (const r of D.rows) { if (r.y < f.y0 || r.y > f.y1 || !r.ck) continue; if (!ck.has(r.ck)) ck.set(r.ck, { winter: 0, midyear: 0, annual: 0, executive: 0, none: 0 }); ck.get(r.ck)[r.k || "none"]++; }
  const ckRows = [...ck.entries()].sort((x, y) => cname(x[0]).localeCompare(cname(y[0]))).map(([key, c]) => [esc(cname(key)), ...["winter", "midyear", "annual", "executive"].map(k => cnt(c[k], makeSpec({ c: key, ly: "c", k, y0: f.y0, y1: f.y1 }), `${cname(key)}, ${kindLabel(k)}`)), cnt(c.none, makeSpec({ c: key, ly: "c", k: "none", y0: f.y0, y1: f.y1 }), `${cname(key)}, convention not recorded`)]);
  return { grid, kTable, bTable, so, allMedian: allN.length ? num1(median(allN)) : "", nSched: allN.length, ckTable: table("t-ck", "Committees by convention kind, confirmed committees", ["Committee", "Winter", "Mid-Year", "Annual", "Executive Board", "Convention not recorded"], ckRows) };
}
const DT_step = n => (n <= 1 ? 1 : n <= 3 ? 2 : n <= 6 ? 3 : n <= 10 ? 4 : n <= 15 ? 5 : 6);

function outcomesBlock(S) {
  const f = S.f, m = DT.outcomeMatrix(f.k, f.c), yrs = yearsIn(f);
  const max = Math.max(1, ...yrs.map(y => m[D.yi.get(y)].resolutions));
  const rows = yrs.map(y => {
    const o = m[D.yi.get(y)], total = o.resolutions;
    const segs = ["adopted", "not_adopted", "tabled"].map(k => ({ key: k, n: o[k], label: `${y}: recorded as ${DT.OUTCOME_LABEL[k]}: ${fmt(o[k])} resolutions`, spec: makeSpec({ y, o: k, k: f.k, c: f.c, ly: f.c ? "b" : "" }) }));
    if (o.not_recorded) segs.push({ key: "none", n: o.not_recorded, label: `${y}: outcome not recorded for ${fmt(o.not_recorded)} resolutions`, spec: makeSpec({ y, o: "norec", k: f.k, c: f.c, ly: f.c ? "b" : "" }) });
    const st = covState(o.recorded, total);
    return { year: y, total, segs, yearSpec: makeSpec({ y, k: f.k, c: f.c, ly: f.c ? "b" : "" }), text: total ? (o.recorded === 0 ? nr : ofWhole(o.recorded, total) + " recorded") : "", cov: { state: st, share: total ? o.recorded / total : 0, text: `${y}: outcome recorded for ${ofWhole(o.recorded, total)} resolutions` } };
  });
  const full = yrs.filter(y => { const o = m[D.yi.get(y)]; return o.resolutions && o.recorded === o.resolutions; });
  const part = yrs.filter(y => { const o = m[D.yi.get(y)]; return o.recorded > 0 && o.recorded < o.resolutions; });
  const none = yrs.filter(y => m[D.yi.get(y)].recorded === 0 && m[D.yi.get(y)].resolutions);
  const na = DT.sumBy(m, f, r => r.not_adopted), tb = DT.sumBy(m, f, r => r.tabled), ad = DT.sumBy(m, f, r => r.adopted);
  const listed = D.rows.filter(r => (r.o === "not_adopted" || r.o === "tabled") && r.y >= f.y0 && r.y <= f.y1 && DT.selects(r, f.k, f.c));
  const tbl = table("t-outcomes", "Outcomes recorded for resolutions, by year", ["Year", "Yes (adopted)", "No (not adopted)", "Tabled", "Outcome recorded", "Resolutions"],
    yrs.map(y => { const o = m[D.yi.get(y)]; return [String(y), ...["adopted", "not_adopted", "tabled"].map(k => o.recorded === 0 ? nr : cnt(o[k], makeSpec({ y, o: k, k: f.k, c: f.c, ly: f.c ? "b" : "" }), `${y}, ${DT.OUTCOME_LABEL[k]}`)), o.recorded === 0 ? nr : ofWhole(o.recorded, o.resolutions), fmt(o.resolutions)]; }));
  return {
    chartHtml: rowBarsHtml({ id: "outcomes", rows, max, covName: "Outcome recorded" }),
    key: keyHtml([{ cls: "s-adopted", label: "Yes (adopted)" }, { cls: "s-not_adopted", label: "No (not adopted)" }, { cls: "s-tabled", label: "Tabled" }, { cls: "s-none", label: "Outcome not recorded" }, ...COV_KEY]),
    table: tbl,
    cov: [covSentence({ ...S }, "outcome"), `${fmt(na + tb)} resolutions are recorded as not adopted (${fmt(na)}) or tabled (${fmt(tb)}); ${fmt(ad)} are recorded as adopted.`, `Outcome is recorded in every resolution of ${full.length ? esc(join(runs(full))) : "no year"}${part.length ? `, and for part of ${esc(join(runs(part)))}` : ""}. It is not recorded for ${none.length ? esc(join(runs(none))) : "no year"}.`],
    listed,
  };
}

function ncaiBlock(S) {
  const f = S.f, m = DT.ncaiMatrix(f.k, f.c), yrs = yearsIn(f);
  const max = Math.max(1, ...yrs.map(y => m[D.yi.get(y)].resolutions));
  const rows = yrs.map(y => {
    const o = m[D.yi.get(y)], total = o.resolutions;
    const segs = ["yes", "no", "na"].map(k => ({ key: k, n: o[k], label: `${y}: TO NCAI ${DT.NCAI_LABEL[k]}: ${fmt(o[k])} resolutions`, spec: makeSpec({ y, nc: k, k: f.k, c: f.c, ly: f.c ? "b" : "" }) }));
    if (o.not_recorded) segs.push({ key: "none", n: o.not_recorded, label: `${y}: TO NCAI not recorded for ${fmt(o.not_recorded)} resolutions`, spec: makeSpec({ y, nc: "norec", k: f.k, c: f.c, ly: f.c ? "b" : "" }) });
    return { year: y, total, segs, yearSpec: makeSpec({ y, k: f.k, c: f.c, ly: f.c ? "b" : "" }), text: o.recorded === 0 ? (total ? nr : "") : `${ofWhole(o.yes, o.recorded, true)} Yes`, cov: { state: covState(o.recorded, total), share: total ? o.recorded / total : 0, text: `${y}: TO NCAI recorded for ${ofWhole(o.recorded, total)} resolutions` } };
  });
  const tot = k => DT.sumBy(m, f, r => r[k]);
  const fullYears = yrs.filter(y => { const o = m[D.yi.get(y)]; return o.resolutions && o.recorded === o.resolutions; });
  const partYears = yrs.filter(y => { const o = m[D.yi.get(y)]; return o.recorded > 0 && o.recorded < o.resolutions; });
  // by committee (confirmed and waiting parts)
  const cmap = new Map();
  for (const r of D.rows) {
    if (r.y < f.y0 || r.y > f.y1 || !r.nc || (f.k && r.k !== f.k)) continue;
    const parts = r.ck ? [[r.ck, "c"]] : r.pk.map(k => [k, "w"]);
    for (const [key, ly] of parts) { const id = key + "|" + ly; if (!cmap.has(id)) cmap.set(id, { key, ly, rec: 0, yes: 0, no: 0, na: 0 }); const o = cmap.get(id); o.rec++; o[r.nc]++; }
  }
  const cRows = [...cmap.values()].sort((a, b) => b.rec - a.rec || cname(a.key).localeCompare(cname(b.key))).map(o => [`${esc(cname(o.key))}${o.ly === "w" ? ` <span class="tag">waiting for ATNI</span>` : ""}`, ofWhole(o.yes, o.rec, true) + " Yes", cnt(o.rec, makeSpec({ c: o.key, ly: o.ly, nc: "rec", k: f.k, y0: f.y0, y1: f.y1 }), cname(o.key)), cnt(o.yes, makeSpec({ c: o.key, ly: o.ly, nc: "yes", k: f.k, y0: f.y0, y1: f.y1 }), `${cname(o.key)}, Yes`), cnt(o.no, makeSpec({ c: o.key, ly: o.ly, nc: "no", k: f.k, y0: f.y0, y1: f.y1 }), `${cname(o.key)}, No`), cnt(o.na, makeSpec({ c: o.key, ly: o.ly, nc: "na", k: f.k, y0: f.y0, y1: f.y1 }), `${cname(o.key)}, n/a`)]);
  // by kind, in fully recorded years
  const nf = new Set(DT.ncaiMatrix("", f.c).filter(o => o.resolutions && o.recorded === o.resolutions).map(o => o.year));
  const kRows = ["midyear", "annual", "winter"].map(k => { const rs = D.rows.filter(r => r.k === k && nf.has(r.y) && r.nc && DT.selects(r, "", f.c)); const y = rs.filter(r => r.nc === "yes").length; return { k, rec: rs.length, yes: y }; }).sort((a, b) => b.yes / (b.rec || 1) - a.yes / (a.rec || 1)).map(o => [kindLabel(o.k), ofWhole(o.yes, o.rec, true) + " Yes", cnt(o.rec, makeSpec({ k: o.k, nc: "rec", c: f.c, ly: f.c ? "b" : "", ys: [...nf].join(",") }), kindLabel(o.k))]);
  return {
    chartHtml: rowBarsHtml({ id: "ncai", rows, max, covName: "TO NCAI recorded" }),
    key: keyHtml([{ cls: "s-yes", label: "Yes" }, { cls: "s-no", label: "No" }, { cls: "s-na", label: "n/a" }, { cls: "s-none", label: "Not recorded" }, ...COV_KEY]),
    table: table("t-ncai", "TO NCAI by year", ["Year", "Yes", "No", "n/a", "Recorded", "Resolutions"], yrs.map(y => { const o = m[D.yi.get(y)]; return [String(y), ...["yes", "no", "na"].map(k => o.recorded === 0 ? nr : cnt(o[k], makeSpec({ y, nc: k, k: f.k, c: f.c, ly: f.c ? "b" : "" }), `${y}, TO NCAI ${DT.NCAI_LABEL[k]}`)), o.recorded === 0 ? nr : ofWhole(o.recorded, o.resolutions), fmt(o.resolutions)]; })),
    cov: [covSentence(S, "ncai"), `Of the ${fmt(tot("recorded"))} resolutions with TO NCAI recorded, ${fmt(tot("yes"))} say Yes, ${fmt(tot("no"))} say No and ${fmt(tot("na"))} say n/a. It is recorded in every resolution of ${fullYears.length ? esc(join(runs(fullYears))) : "no year"}${partYears.length ? ` and for part of ${esc(join(runs(partYears)))}` : ""}.`],
    byCommittee: table("t-ncai-c", "TO NCAI by committee, confirmed and waiting parts", ["Committee", "Share Yes", "Recorded", "Yes", "No", "n/a"], cRows, { numFrom: 1 }),
    byKind: table("t-ncai-k", "TO NCAI by convention kind in the years where it is recorded on every resolution", ["Kind", "Share Yes", "Recorded"], kRows),
    fullYears,
  };
}

export function view_years(S) {
  const f = S.f;
  const yrs = sec({
    id: "years", h2: "Resolutions Each Year", h3: "Resolutions numbered each year",
    sub: `One bar for each year, ${esc(span(f))}, by convention.`,
    summary: `Stacked bar chart of resolutions numbered each year, ${span(f)}, split by convention. A table with the same numbers follows.`,
    chart: "kind", table: yearTable(S, "kind"), csv: "t-kind", cov: [covSentence(S, "convention")],
    caveat: `Counted from The Resolution Library. A resolution is counted once, in the year of its number. Before 2007 this site holds no text; the Library lists titles. Missing from the Library: ${esc(join(missingConventions()))}. The count is of resolutions listed with a number; adoption is recorded on only part of them, so the chart never says passed.`,
  });
  const cv = conventionsBlock(S);
  const conv = sec({
    id: "conventions", h2: "Conventions Compared", h3: "Resolutions at each convention",
    sub: `Winter, Mid-Year, Annual and Executive Board, ${esc(span(f))}. A hatched cell is a convention missing from the Library, not a zero.`,
    summary: "Grid of resolutions at each convention: one row for each year, one column for each kind of convention. The same numbers are in the grid itself.",
    chartHtml: cv.grid, skip: false,
    cov: [cv.so ? esc(cv.so) : "", `Median per scheduled session over the whole record: ${esc(cv.allMedian)}, across ${fmt(cv.nSched)} scheduled sessions.`].filter(Boolean),
    table: cv.kTable + `<h4 class="tbl-h">Median per scheduled session, by span of years</h4>` + cv.bTable, csv: "t-kinds",
    extra: `<details class="tbl"><summary>Show committees by kind</summary>${cv.ckTable}</details>`,
    caveat: "Executive Board actions are adopted between conventions and are counted as their own kind. 2014-66 and 2014-67 are counted as Annual until ATNI answers question 12. Conventions missing from the Library are marked, not zero.",
  });
  const oc = outcomesBlock(S);
  const out = sec({
    id: "outcomes", h2: "Outcomes the Record Marks", h3: "Outcomes recorded for resolutions",
    sub: "How many resolutions are marked Yes, No or Tabled. Years where the record has no outcome are hatched.",
    summary: `Bars of outcomes recorded for resolutions by year, ${span(f)}. A table with the same numbers follows.`,
    chartHtml: oc.chartHtml, key: oc.key, table: oc.table, csv: "t-outcomes", cov: oc.cov, skip: false,
    extra: `<h3 class="list-h">Recorded as not adopted or tabled: ${fmt(oc.listed.length)}</h3><ol class="lrows" id="ten-list">${oc.listed.map(r => lrow(r, S)).join("")}</ol>`,
    caveat: "Outcome (the Passed column) is recorded for part of the resolutions. A blank means not recorded, never No. The certification text on a published final resolution is a template, so ResIST does not read it as an outcome.",
  });
  const nc = ncaiBlock(S);
  const ncai = sec({
    id: "ncai", h2: "Sent On to NCAI, Where Recorded", h3: "Resolutions marked to go on to NCAI",
    sub: "Only years where the record says Yes, No or n/a. National Congress of American Indians (NCAI).",
    summary: `Bars of resolutions marked to go on to NCAI by year, ${span(f)}. A table with the same numbers follows.`,
    chartHtml: nc.chartHtml, key: nc.key, table: nc.table, csv: "t-ncai", cov: nc.cov, skip: false,
    extra: `<details class="tbl"><summary>Show TO NCAI by committee</summary>${nc.byCommittee}</details><details class="tbl"><summary>Show TO NCAI by kind of convention, in years recorded on every resolution (${esc(join(runs(nc.fullYears)))})</summary>${nc.byKind}</details>`,
    caveat: "A blank means not recorded, never No. A committee's total mixes years, and years differ: choose a year range to compare like with like. A percent is shown only where the recorded whole is 20 or more.",
  });
  return yrs + conv + out + ncai;
}

/* ---------------------------------------------------------------------------------------------------------- */
/* COMMITTEES                                                                                                   */
function wyattMap() {
  return DT_memo("wm", () => { const m = new Map(); for (const c of D.agg.wyatt_vs_recount.cells) if (c.committee_key) m.set(c.committee_key + "|" + c.year, c); return m; });
}
const _memos = new Map();
function DT_memo(k, fn) { if (!_memos.has(k)) _memos.set(k, fn()); return _memos.get(k); }

function heatRows(S, years) {
  const f = S.f, mx = DT.commMatrix(f.k), t = committeeTotals(S);
  const wy = S.q.get("wy") === "1" ? wyattMap() : null;
  const rows = (f.c ? t.rows.filter(r => r.key === f.c) : t.rows).map(r => ({
    key: r.key, name: r.name, href: S.hrefView("committees", { cm: r.key }),
    cells: years.map(y => {
      const [c, w] = mx.get(r.key, y);
      const wc = wy && wy.get(r.key + "|" + y);
      const diff = wc && !wc.match;
      return { c, w, diff, spec: makeSpec({ y, c: r.key, ly: c || !w ? "c" : "w", k: f.k }), label: `${r.name}, ${y}: ${fmt(c)} resolutions${w ? `, and ${fmt(w)} with labels waiting for ATNI` : ""}${diff ? `. Wyatt's grid reads ${wc.his ?? "blank"}; the recount reads ${wc.recount}` : ""}` };
    }),
  }));
  if (!f.c) rows.push({ key: "none", name: "Names no committee", hatched: true, cells: years.map(y => { const n = mx.blank.get(y) + mx.other.get(y); return { c: n, w: 0, spec: makeSpec({ y, cn: "any", k: f.k }), label: `Names no committee, ${y}: ${fmt(n)} resolutions` }; }) });
  return rows;
}
function heatTable(S) {
  const f = S.f, yrs = yearsIn(f), rows = heatRows(S, yrs);
  const head = ["Committee", ...yrs.map(String)];
  return table("t-heat", "Resolutions by committee and year", head, rows.map(r => [esc(r.name), ...r.cells.map(c => (c.c || c.w ? `${c.c ? cnt(c.c, c.spec, r.name) : "0"}${c.w ? ` <span class="tag">${fmt(c.w)} waiting</span>` : ""}` : `<span class="zero">0</span>`))]), { numFrom: 1 });
}
export function view_committees(S) {
  const f = S.f;
  let out = "";
  const cmKey = S.q.get("cm");
  if (cmKey && D.cm[cmKey]) out += committeePage(S, cmKey);
  const w = S.q.get("wy") === "1";
  const t = committeeTotals(S);
  out += sec({
    id: "heat", h2: "Resolutions by Committee", h3: "Resolutions by committee and year",
    sub: `Each resolution is counted under one committee, as the workbook's Committee column names it, ${esc(span(f))}. Rows are sorted by number of resolutions. The number in each cell is the confirmed count; a hatched number is the count waiting for ATNI. Arrow keys move between cells; Enter opens the list behind a number.`,
    summary: `Grid of resolutions by committee and year, ${span(f)}, with the count printed in each cell. A table with the same numbers follows.`,
    chart: "heat", skip: true,
    key: keyHtml([{ cls: "step-1", label: "1" }, { cls: "step-2", label: "2 to 3" }, { cls: "step-3", label: "4 to 6" }, { cls: "step-4", label: "7 to 10" }, { cls: "step-5", label: "11 to 15" }, { cls: "step-6", label: "16 or more" }, { cls: "s-waiting", label: "Hatched number: label waiting for ATNI" }, { cls: "s-none", label: "Names no committee" }]),
    cov: [`${fmt(t.blank + t.other)} resolutions name no committee: ${fmt(t.blank)} have a blank cell and ${fmt(t.other)} say Off the Floor, Executive Board or another body.`, covSentence(S, "committee")],
    table: heatTable(S), csv: "t-heat",
    actions: `<label class="switch"><input type="checkbox" data-switch="wy"${w ? " checked" : ""}> Show Wyatt's counts</label>`,
    caveat: `Hatched counts are labels waiting for ATNI to confirm which committee they belong to (questions 1 to 5); select one to see the label as written. ${(() => { const c = DT.covMatrix("committee", "", "")[D.yi.get(2019)]; return `2019 has a committee on ${c.n} of ${c.total} resolutions. `; })()}No single merged total is printed while questions 1 to 5 are open.`,
  });
  out += namesBlock(S, cmKey);
  out += wyattBlock(S);
  return out;
}

function namesBlock(S, onlyKey) {
  const f = S.f, keys = (onlyKey ? [onlyKey] : f.c ? [f.c] : D.agg.committees.map(c => c.key));
  const items = [];
  for (const key of keys) {
    const cm = D.cm[key];
    const lines = [...cm.labels.map(l => ({ ...l, ly: "c" })), ...cm.proposed_labels.map(l => ({ ...l, ly: "w" }))]
      .map(l => ({ ...l, nIn: Object.entries(l.years).reduce((s, [y, n]) => s + (+y >= f.y0 && +y <= f.y1 ? n : 0), 0) })).filter(l => l.nIn > 0)
      .sort((a, b) => (a.ly === b.ly ? a.first_year - b.first_year || a.label.localeCompare(b.label) : a.ly === "c" ? -1 : 1));
    if (!lines.length) continue;
    items.push(`<div class="nm-group"><h4 id="nm-${esc(key)}"><a href="${esc(S.hrefView("committees", { cm: key }))}">${esc(cm.name)}</a>${cm.owner_q ? ` <span class="tag">waiting for ATNI, ${esc(qnum(cm.owner_q))}</span>` : ""}</h4><ul class="labels">${lines.map(l => {
      const yrs = D.years.map(y => (l.years[y] ? "u" : y >= l.first_year && y <= l.last_year ? "b" : "e"));
      const spec = makeSpec({ c: key, ly: l.ly, lab: l.label, y0: f.y0, y1: f.y1 });
      return `<li class="lab"><div class="lab-head"><span class="lab-text">${esc(l.label)}</span>${l.ly === "w" ? ` <span class="tag">waiting for ATNI</span>` : ""}<span class="lab-yrs">${l.first_year === l.last_year ? l.first_year : `${l.first_year} to ${l.last_year}`}</span>${cnt(l.nIn, spec, `Label ${l.label} as written`)}</div><div class="lab-strip${l.ly === "w" ? " wait" : ""}" role="img" aria-label="${esc(l.label)} is used in ${esc(join(runs(Object.keys(l.years).map(Number))))}">${D.years.map((y, i) => `<i class="${yrs[i]}${y < f.y0 || y > f.y1 ? " out" : ""}" data-tip="${y}${l.years[y] ? `: ${fmt(l.years[y])}` : ""}"></i>`).join("")}</div></li>`;
    }).join("")}</ul></div>`);
  }
  return sec({
    id: "names", h2: "Committee Names Over Time", h3: "Committee names as the record writes them",
    sub: "Each strip is one label, from its first year to its last. A filled square is a year the label is used.",
    summary: "Timelines of committee labels, one strip for each label as written.",
    chartHtml: `<div class="nm">${items.join("") || `<p class="empty-line">No committee label in this selection.</p>`}</div>`,
    key: keyHtml([{ cls: "tl-u", label: "A year the label is used" }, { cls: "tl-b", label: "Between its first and last year" }, { cls: "s-waiting", label: "Waiting for ATNI" }]), skip: false,
    caveat: "Labels are shown exactly as the workbook writes them, including spelling. Grouping labels under one committee is ATNI's decision (questions 1 to 5); until then the groups are proposals.",
  });
}

function committeePage(S, key) {
  const f = S.f, cm = D.cm[key];
  const km = DT.kindMatrix(key), yrs = yearsIn(f);
  const rows = yrs.map(y => { const m = km[D.yi.get(y)]; const conf = m.total - m.wait; return { year: y, total: conf + m.wait, segs: [{ key: "total", n: conf, label: `${y}: ${fmt(conf)} resolutions`, spec: makeSpec({ y, c: key, ly: "c" }) }, { key: "waiting", n: m.wait, label: `${y}: ${fmt(m.wait)} with labels waiting for ATNI`, spec: makeSpec({ y, c: key, ly: "w" }) }], yearSpec: makeSpec({ y, c: key, ly: "b" }) }; });
  const max = Math.max(1, ...rows.map(r => r.total));
  const cr = D.rows.filter(r => r.ck === key && r.y >= f.y0 && r.y <= f.y1);
  const nc = { rec: 0, yes: 0 }; for (const r of cr) if (r.nc) { nc.rec++; if (r.nc === "yes") nc.yes++; }
  const withPb = cr.filter(r => r.pb).length;
  let people = "";
  if (S.names) {
    const pm = new Map(); for (const r of cr) for (const p of r.pp) pm.set(p, (pm.get(p) || 0) + 1);
    const list = [...pm.entries()].map(([k, n]) => ({ k, n, name: D.persons.get(k).name })).sort((a, b) => a.name.localeCompare(b.name));
    people = `<h3 class="list-h">People Named on Its Resolutions</h3><p class="sub">${fmt(withPb)} of ${fmt(cr.length)} ${esc(cm.name)} resolutions name a preparer. Names are shown as written in ATNI's record, in name order.</p><ul class="plist">${list.map(p => `<li><a href="${esc(S.hrefView("people", { p: p.k }))}">${esc(p.name)}</a> <span class="pl-n">${cnt(p.n, makeSpec({ p: p.k, c: key, ly: "c" }), p.name)}</span></li>`).join("")}</ul>`;
  } else people = `<p class="sub">Names are not yet published, so people are not listed here. ${fmt(withPb)} of ${fmt(cr.length)} ${esc(cm.name)} resolutions name a preparer.</p>`;
  const body = `<p class="sub">${cm.status === "confirmed" ? "The committee name is confirmed." : `The committee name waits for ATNI (${esc(qnum(cm.owner_q))}).`}${cm.tab_name ? ` Wyatt Ash-Milby's workbook has a tab named ${esc(cm.tab_name)}.` : ""}${cm.chart_name ? ` His chart names it ${esc(cm.chart_name)}.` : ""}</p>
    <p>${fmt(cm.total)} resolutions are counted under ${esc(cm.name)}${cm.first_year ? `, ${cm.first_year} to ${cm.last_year}` : ""}. ${fmt(cm.proposed_total)} more carry labels waiting for ATNI.</p>
    ${nc.rec ? `<p>TO NCAI (National Congress of American Indians) is recorded for ${ofWhole(nc.rec, cr.length)} resolutions: ${ofWhole(nc.yes, nc.rec, true)} say Yes.</p>` : `<p>TO NCAI is not recorded for any of them in this selection.</p>`}
    <p class="sr-only" id="cp-sum">Bars of ${esc(cm.name)} resolutions by year, confirmed and waiting for ATNI.</p>
    ${rowBarsHtml({ id: "cp", rows, max })}${keyHtml([{ cls: "s-total", label: "Confirmed" }, { cls: "s-waiting", label: "Label waiting for ATNI" }])}
    ${people}`;
  return `<section class="vs" id="committee-page" aria-labelledby="committee-page-h"><h2 id="committee-page-h">${esc(cm.name)}</h2>${body}<p><a class="btn small quiet" href="${esc(S.href({ cm: undefined }))}">Close this committee page</a></p>${src()}</section>`;
}

function wyattBlock(S) {
  const W = D.agg.wyatt_vs_recount, sum = W.summary, show = S.q.get("wr") === "1";
  const cells = new Map(W.cells.map(c => [c.committee + "|" + c.year, c]));
  const fm = c => (c ? c.his ?? "" : "");
  const rowsFor = name => W.years.map(y => cells.get(name + "|" + y));
  const cellHtml = c => {
    if (!c) return "";
    const base = c.his == null ? `<span class="zero">blank</span>` : fmt(c.his);
    if (c.match) return base;
    return show ? `<span class="wd" data-tip="His ${c.his ?? "blank"}; recount ${c.recount}"><b>${c.his == null ? "blank" : fmt(c.his)}</b><i>${fmt(c.recount)}</i></span>` : `<span class="wd" data-tip="His ${c.his ?? "blank"}; recount ${c.recount}">${base}</span>`;
  };
  const picked = S.q.get("wc") && W.committees.includes(S.q.get("wc")) ? S.q.get("wc") : W.committees[0];
  const wideTable = `<div class="tbl-wrap wy-wrap" tabindex="0" role="region" aria-label="Wyatt Ash-Milby's committee counts"><table class="data wy" id="t-wyatt"><caption class="sr-only">Wyatt Ash-Milby's committee counts, 2001 to 2025</caption><thead><tr><th scope="col">Committee</th>${W.years.map(y => `<th scope="col" class="num">${String(y).slice(2)}<span class="sr-only"> (${y})</span></th>`).join("")}<th scope="col">Sparkline</th></tr></thead><tbody>${W.committees.map(name => { const cs = rowsFor(name); return `<tr><th scope="row">${esc(name)}</th>${cs.map(c => `<td class="num${c && !c.match ? " diff" : ""}">${cellHtml(c)}</td>`).join("")}<td class="spark-cell">${sparkSvg(cs.map(c => (c ? c.his : null)))}</td></tr>`; }).join("")}</tbody></table></div>`;
  const narrow = `<div class="cov-pick"><label for="wc-pick">Committee</label><select id="wc-pick" data-pick="wc">${W.committees.map(n => `<option${n === picked ? " selected" : ""}>${esc(n)}</option>`).join("")}</select></div>
    <table class="data wy-one"><caption class="sr-only">${esc(picked)}, Wyatt Ash-Milby's counts by year</caption><thead><tr><th scope="col">Year</th><th scope="col" class="num">His count</th>${show ? `<th scope="col" class="num">Recount</th>` : ""}</tr></thead><tbody>${rowsFor(picked).map(c => `<tr><th scope="row">${c.year}</th><td class="num${!c.match ? " diff" : ""}">${c.his == null ? `<span class="zero">blank</span>` : fmt(c.his)}</td>${show ? `<td class="num">${fmt(c.recount)}</td>` : ""}</tr>`).join("")}</tbody></table>`;
  const diffRows = W.cells.filter(c => !c.match);
  return sec({
    id: "wyatt", h2: "Wyatt Ash-Milby's Counts", h3: "Wyatt Ash-Milby's committee counts",
    sub: `His Sparklines and Charts grid as he built it: ${fmt(W.committees.length)} committee rows, ${W.years[0]} to ${W.years[W.years.length - 1]}. Choose Show the recount beside it to see his number and the recount together in the marked cells.`,
    summary: "Table of Wyatt Ash-Milby's committee counts by year with a sparkline for each committee.",
    chartHtml: `<div class="wy-only-wide">${wideTable}</div><div class="wy-only-narrow">${narrow}</div>`, skip: false,
    key: keyHtml([{ cls: "wd-key", label: "Marked cell: his number differs from the recount" }]),
    cov: [`${fmt(sum.cells)} cells: ${fmt(sum.cells - sum.differing_cells)} equal the recount and ${fmt(sum.differing_cells)} differ. ${fmt((sum.differing_by_committee["Education (Higher)"] || 0) + (sum.differing_by_committee["Education (K-12)"] || 0))} of the ${fmt(sum.differing_cells)} are on the Education (Higher) and Education (K-12) rows, where his grid repeats the Education count on both.`],
    actions: `<label class="switch"><input type="checkbox" data-switch="wr"${show ? " checked" : ""}> Show the recount beside it</label>`,
    table: table("t-wyatt-diff", "Cells where Wyatt Ash-Milby's count differs from the recount", ["Committee", "Year", "His count", "Recount"], diffRows.map(c => [esc(c.committee), String(c.year), c.his == null ? "blank" : fmt(c.his), fmt(c.recount)]), { numFrom: 1 }), csv: "t-wyatt-diff",
    caveat: "Wyatt Ash-Milby built these counts in The Resolution Library. The recount applies his own rule to the Library's rows. Neither replaces the other. His grid ends at 2025 and is not extended.",
  });
}

/* ---------------------------------------------------------------------------------------------------------- */
/* PEOPLE                                                                                                       */
const EXAMPLE = ["patricia-whitefoot", "patsy-whitefoot", "patrica-whitefoot"];
const withheld = S => sec({
  id: "withheld", h2: "Prepared By, as the Workbook Records", h3: "Resolutions by who prepared them",
  sub: "Names from The Resolution Library are not yet published on this site.",
  chartHtml: `<div class="empty-state"><h3>Names Are Not Yet Published</h3><p>Counts by committee and year are shown instead. Names publish only when ATNI decides (architecture owner question 12).</p><p><a class="btn small" href="${esc(S.hrefView("committees"))}">See committees</a></p></div>`,
  extra: (() => { const mx = D.rows.filter(r => r.pb && r.ck).reduce((m, r) => (m.set(r.ck, (m.get(r.ck) || 0) + 1), m), new Map()); return table("t-pb-committee", "Resolutions with Prepared By recorded, by committee", ["Committee", "With Prepared By recorded"], [...mx.entries()].sort((a, b) => b[1] - a[1]).map(([k, n]) => [esc(cname(k)), cnt(n, makeSpec({ c: k, ly: "c", has: "preparer" }), cname(k))])); })(),
  caveat: "A preparer is what The Resolution Library records; the resolutions themselves do not print one.", skip: false,
});
function stripHtml(p, S) {
  const cov = DT.covMatrix("preparer", "", "");
  const cells = D.years.map((y, i) => { const c = cov[i]; const n = p.by_year[y] || 0; return `<i class="${n ? "u" : c.n === 0 && c.total ? "h" : "e"}${y < S.f.y0 || y > S.f.y1 ? " out" : ""}" data-tip="${y}${n ? `: ${fmt(n)}` : c.n === 0 ? ": Prepared By not recorded" : ""}"></i>`; }).join("");
  return `<span class="pstrip" role="img" aria-label="${esc(p.name)} is named in ${esc(join(runs(Object.keys(p.by_year).map(Number))))}">${cells}</span>`;
}
export function view_people(S) {
  if (!S.names) return withheld(S);
  const pk = S.q.get("p");
  if (pk && D.persons.has(pk)) return personPage(S, pk);
  const f = S.f;
  const people = [...D.persons.values()];
  const sort = S.q.get("ps") === "n" ? "n" : "name";
  const picked = S.q.get("pc") || "";
  let list = people;
  if (picked) { const set = new Set(); for (const r of D.rows) if (r.ck === picked) r.pp.forEach(p => set.add(p)); list = people.filter(p => set.has(p.key)); }
  list = [...list].sort(sort === "n" ? (a, b) => b.total - a.total || a.name.localeCompare(b.name) : (a, b) => a.name.localeCompare(b.name));
  const pcs = D.cmList.filter(c => D.rows.some(r => r.ck === c.key && r.pp.length));
  const listHtml = `<ul class="plist people" data-people>${list.map(p => `<li data-name="${esc(p.name.toLowerCase())}"><div class="pl-head"><a href="${esc(S.hrefView("people", { p: p.key }))}">${esc(p.name)}</a><span class="pl-n">${cnt(p.total, makeSpec({ p: p.key }), p.name)} <span class="sub-inline">${p.first_year} to ${p.last_year}</span></span></div>${stripHtml(p, S)}</li>`).join("")}</ul>`;
  const ex = EXAMPLE.map(k => D.persons.get(k)).filter(Boolean);
  const exBlock = ex.length ? sec({
    id: "spellings", h2: "Spellings Side by Side", h3: "Three recorded spellings, on one year axis",
    sub: "Each spelling is counted on its own and never added to another.",
    summary: `Year strips for ${ex.map(p => p.name).join(", ")}.`,
    chartHtml: `<ul class="plist people ex">${ex.map(p => `<li><div class="pl-head"><a href="${esc(S.hrefView("people", { p: p.key }))}">${esc(p.name)}</a><span class="pl-n">${cnt(p.total, makeSpec({ p: p.key }), p.name)} <span class="sub-inline">${p.first_year} to ${p.last_year}${p.owner_q ? `, display name waits on ${esc(qnum(p.owner_q))}` : ", kept as recorded"}</span></span></div>${stripHtml(p, S)}</li>`).join("")}</ul>`, skip: false,
    caveat: "ATNI has been asked whether any of these spellings names the same person (question 9). Until then each spelling is counted on its own. Years where Prepared By is not recorded are hatched.", nosrc: false,
  }) : "";
  const main = sec({
    id: "people", h2: "Prepared By, as the Workbook Records", h3: "Resolutions by who prepared them",
    sub: "Names are shown as written in ATNI's record.",
    summary: `List of ${fmt(D.agg.meta.counts.people_in_ledger)} names, each with a strip of the years it is named in.`,
    chartHtml: `<div class="people-tools"><div class="pt-find"><label for="find-name">Find a name</label><input id="find-name" type="search" autocomplete="off" spellcheck="false" data-find placeholder="Part of a name"></div>
      <div class="pt-pick"><label for="pc-pick">Names on one committee</label><select id="pc-pick" data-pick="pc"><option value="">All committees</option>${pcs.map(c => `<option value="${esc(c.key)}"${c.key === picked ? " selected" : ""}>${esc(c.name)}</option>`).join("")}</select></div>
      <div class="pt-sort"><span id="sort-l">Order</span><div role="group" aria-labelledby="sort-l"><button type="button" class="btn small${sort === "name" ? "" : " quiet"}" data-patch="ps=" aria-pressed="${sort === "name"}">Name order</button><button type="button" class="btn small${sort === "n" ? "" : " quiet"}" data-patch="ps=n" aria-pressed="${sort === "n"}">Sorted by number of resolutions</button></div></div></div>
      <p class="find-count" role="status" aria-live="polite" data-findcount>${fmt(list.length)} names${picked ? ` on ${esc(cname(picked))} resolutions` : ""}.</p>${listHtml}`, skip: false,
    key: keyHtml([{ cls: "tl-u", label: "A year the name appears" }, { cls: "s-none", label: "Prepared By not recorded that year" }]),
    cov: [covSentence(S, "preparer")],
    caveat: `A preparer is what The Resolution Library records; the resolutions themselves do not print one. Preparers are not recorded for ${esc(join(runs(D.years.filter((y, i) => DT.covMatrix("preparer", "", "")[i].n === 0))))}. Possible matches between spellings of one name are waiting for ATNI review and are counted as written.`,
  });
  return main + exBlock + togetherBlock(S);
}

function togetherBlock(S) {
  const f = S.f, all = !f.k && !f.c && f.y0 === D.yMin && f.y1 === D.yMax;
  let pairs;
  if (all) pairs = D.agg.co_preparation;
  else {
    const m = new Map();
    for (const r of D.rows) { if (r.y < f.y0 || r.y > f.y1 || !DT.selects(r, f.k, f.c)) continue; for (let i = 0; i < r.pp.length; i++) for (let j = i + 1; j < r.pp.length; j++) { const id = r.pp[i] + "|" + r.pp[j]; if (!m.has(id)) m.set(id, { a: r.pp[i], b: r.pp[j], n: 0, ys: [] }); const o = m.get(id); o.n++; o.ys.push(r.y); } }
    pairs = [...m.values()].map(o => ({ a: o.a, b: o.b, a_name: D.persons.get(o.a).name, b_name: D.persons.get(o.b).name, n: o.n, first_year: Math.min(...o.ys), last_year: Math.max(...o.ys) })).sort((x, y) => y.n - x.n || x.a.localeCompare(y.a));
  }
  const multi = D.rows.filter(r => r.pp.length > 1 && r.y >= f.y0 && r.y <= f.y1 && DT.selects(r, f.k, f.c));
  const late = multi.filter(r => r.y >= 2024).length;
  const head = ["Two names", "Resolutions that name both", "Years"];
  const rows = pairs.map(p => [`<a href="${esc(S.hrefView("people", { p: p.a }))}">${esc(p.a_name)}</a> and <a href="${esc(S.hrefView("people", { p: p.b }))}">${esc(p.b_name)}</a>`, cnt(p.n, makeSpec({ p: p.a, p2: p.b }), `${p.a_name} and ${p.b_name}`), p.first_year === p.last_year ? String(p.first_year) : `${p.first_year} to ${p.last_year}`]);
  return sec({
    id: "together", h2: "Named Together", h3: "People named together in Prepared By",
    sub: `Pairs of names that one Prepared By cell names together, sorted by number of resolutions. ${fmt(pairs.length)} pairs. Being named in one cell is all the record says; it is not a measure of collaboration.`,
    summary: `List of ${pairs.length} pairs of names, with the number of resolutions that name both.`,
    chartHtml: pairs.length ? table("t-together", "People named together in Prepared By", head, rows, { numFrom: 1 }) : `<div class="empty-state"><h3>No Pairs in This Selection</h3><p>No Prepared By cell names two people in this selection. Clear a filter or widen the years to see counts again.</p></div>`, skip: false,
    csv: pairs.length ? "t-together" : "",
    caveat: `Two people are counted together when one Prepared By cell names both. ${fmt(multi.length)} resolutions name two or more people; ${fmt(late)} of them are from 2024 to ${D.yMax}. Names publish only under the names rule.`,
  });
}

function personPage(S, key) {
  const p = D.persons.get(key), rows = DT.personRows(key), f = S.f;
  const kinds = DT.personKinds(key), site = DT.personWithSite(key);
  const labels = new Map(); for (const r of rows) { const l = r.cl || ""; labels.set(l, (labels.get(l) || 0) + 1); }
  const covP = DT.covMatrix("preparer", "", "");
  const partYears = D.years.filter((y, i) => y >= p.first_year && y <= p.last_year && covP[i].n < covP[i].total);
  const loose = D.rows.filter(r => r.pb && !r.pp.includes(key) && r.pb.toLowerCase().includes(p.name.toLowerCase()));
  const partners = DT.coPartners(key);
  const similar = EXAMPLE.includes(key) ? EXAMPLE.filter(k => k !== key && D.persons.has(k)).map(k => D.persons.get(k)) : [];
  const request = `Resolution number: \nField: Prepared By\nWhat the record shows: \nWhat it should show: `;
  return `<section class="vs person" id="person" aria-labelledby="person-h">
    <p class="crumb"><a href="${esc(S.href({ p: undefined }))}">All names</a></p>
    <h2 id="person-h">${esc(p.name)}</h2>
    <p class="sub">Prepared by, as the workbook records.</p>
    <p class="lead-p">The Resolution Library names ${esc(p.name)} in the Prepared By column of ${plural(p.total, "resolution", "resolutions")}, ${p.first_year} to ${p.last_year}. ResIST shows what the record says and nothing more about any person.</p>
    ${p.owner_q ? `<p class="note">This name waits for ATNI: ${esc(qnum(p.owner_q))}. The spelling is counted as written.</p>` : ""}
    <h3>Spellings as Written</h3>
    <ul class="plain">${p.forms.map(fm => `<li>“${esc(fm.form)}” ${cnt(fm.n, makeSpec({ p: key }), fm.form)}</li>`).join("")}</ul>
    ${similar.length ? `<p class="sub">ATNI has been asked whether ${esc(join(similar.map(q => q.name)))} ${similar.length > 1 ? "name" : "names"} the same person as ${esc(p.name)} (question 9). Until then each spelling is counted on its own. <a href="${esc(S.hrefView("people", { p: similar[0].key }))}">${esc(similar[0].name)}</a></p>` : ""}
    <h3>Years Named</h3>
    <p class="sr-only" id="career-sum">Bars of resolutions naming ${esc(p.name)} by year, with a strip showing the years Prepared By is recorded.</p>
    <div class="chart" data-chart="career" data-sum="career-sum" data-person="${esc(key)}"></div>
    <p class="cov-sentence">Named in ${plural(Object.keys(p.by_year).length, "year", "years")}${partYears.length ? `. Prepared By is recorded for only part of ${esc(join(runs(partYears)))}, which fall inside these years` : ""}.</p>
    <h3>Committees</h3>
    <ul class="plain">${Object.entries(p.by_committee).sort((a, b) => b[1] - a[1]).map(([k, n]) => `<li>${k === "none" ? "No committee in the record" : esc(cname(k))} ${cnt(n, k === "none" ? makeSpec({ p: key, cn: "any" }) : makeSpec({ p: key, c: k, ly: "c" }), k === "none" ? "No committee" : cname(k))}</li>`).join("")}</ul>
    <p class="sub">Committee labels as written: ${esc([...labels.entries()].sort((a, b) => b[1] - a[1]).map(([l, n]) => `${l || "blank"} ${n}`).join("; "))}.</p>
    <h3>Convention Kinds</h3>
    <ul class="plain">${KINDS.concat([{ key: "none", label: "No convention recorded" }]).filter(k => kinds[k.key]).map(k => `<li>${esc(k.label)} ${cnt(kinds[k.key], makeSpec({ p: key, k: k.key }), k.label)}</li>`).join("")}</ul>
    <h3>Named Together With</h3>
    ${partners.length ? `<ul class="plain">${partners.map(q => { const o = q.a === key ? [q.b, q.b_name] : [q.a, q.a_name]; return `<li><a href="${esc(S.hrefView("people", { p: o[0] }))}">${esc(o[1])}</a> ${cnt(q.n, makeSpec({ p: key, p2: o[0] }), o[1])}</li>`; }).join("")}</ul>` : `<p>Named with no one else.</p>`}
    <p class="sub">${fmt(site)} of ${fmt(p.total)} resolutions link to a document on this site.</p>
    ${loose.length ? `<p class="note">${loose.map(r => `One more cell, on ${esc(r.n)}, reads “${esc(r.pb)}” with no separator. It is not counted under any name until ATNI answers question 11.`).join(" ")}</p>` : ""}
    <h3>The Resolutions</h3>
    <p class="sub">${fmt(p.total)} resolutions, as the workbook records them. No outcome, TO NCAI (National Congress of American Indians) or rate is shown for a person.</p>
    <ol class="lrows" id="person-list">${lrows(rows, S, 0, 50)}</ol>
    ${rows.length > 50 ? `<button type="button" class="btn small quiet" data-more="person-list" data-key="${esc(key)}" data-from="50">Show more (${fmt(rows.length - 50)})</button>` : ""}
    <div class="corrections"><h3>Is Something Wrong Here?</h3>
      <p>ResIST shows The Resolution Library as ATNI recorded it. <a href="https://atnitribes.org/" rel="noopener">Ask ATNI to correct it</a> through ATNI's own site. ResIST sends nothing. ATNI decides; the answer becomes a ledger row, the build runs again, and the value as written stays in the ledger beside the correction.</p>
      <p>A family may ask ATNI that a name not be shown here. ATNI decides, and the record keeps the name as written.</p>
      <details class="tbl"><summary>Request text to copy</summary><pre class="req" id="req-text">${esc(request)}</pre><button type="button" class="btn small" data-copy="req-text">Copy request text</button><span class="copied" role="status" aria-live="polite" data-copied></span></details></div>
    <p class="caveat">Everything on this page is what the Prepared By column records; the PDFs do not print preparers. Spellings are separate until ATNI answers question 9.</p>
    ${src()}</section>`;
}

/* ---------------------------------------------------------------------------------------------------------- */
/* WORDS AND TITLES                                                                                             */
function returningBlock(S) {
  const f = S.f, G = D.agg.readoptions;
  const groups = G.groups.filter(g => g.members.some(m => m.year >= f.y0 && m.year <= f.y1)).map(g => ({ ...g, gap: g.members[g.members.length - 1].year - g.members[0].year, nums: g.members.map(m => m.number) }));
  const gapHist = new Map(); for (const g of groups) gapHist.set(g.gap, (gapHist.get(g.gap) || 0) + 1);
  const list = groups.map(g => {
    const spec = makeSpec({ nums: g.nums.join(";") });
    return `<li class="grp"><div class="grp-head"><span class="grp-title">${esc(g.title.replace(/_/g, " "))}</span> ${g.on_duplicates_tab ? `<span class="tag">on the workbook's Duplicates tab</span>` : ""}</div><p class="grp-meta">${esc(join(g.nums))}. ${g.gap === 0 ? "Same year" : `${plural(g.gap, "year", "years")} apart`}, ${esc(join(runs([...new Set(g.members.map(m => m.year))])))}.</p><button type="button" class="btn small quiet" data-list="${esc(spec)}" aria-label="Show these resolutions: ${esc(join(g.nums))}">Show these resolutions</button></li>`;
  }).join("");
  const sim = DT.similarGroups();
  const exactSet = new Set(G.groups.flatMap(g => g.members.map(m => m.number)));
  const simList = sim.groups.filter(g => g.some(r => r.y >= f.y0 && r.y <= f.y1)).map(g => {
    const shared = [...g[0]._w].filter(w => g.every(r => r._w.has(w)));
    const nums = g.map(r => r.n), yrs = [...new Set(g.map(r => r.y))];
    return `<li class="grp"><p class="grp-meta"><strong>${esc(join(nums))}</strong>. ${esc(join(runs(yrs)))}. Shared words: ${esc(shared.join(", "))}.</p><button type="button" class="btn small quiet" data-list="${esc(makeSpec({ nums: nums.join(";") }))}" aria-label="Show these resolutions: ${esc(join(nums))}">Show these resolutions</button></li>`;
  }).join("");
  const first = sec({
    id: "returning", h2: "Titles That Return", h3: "Titles that appear more than once",
    sub: "The same or nearly the same title under different numbers.",
    summary: `Dot plot of ${groups.length} groups of resolutions with the same title, by years apart, followed by the list.`,
    chart: "dots", skip: false,
    cov: [`${fmt(groups.length)} groups share one title under two numbers: ${fmt(groups.filter(g => g.span === "across_years").length)} across years and ${fmt(groups.filter(g => g.span === "same_year").length)} within one year. ${fmt(groups.filter(g => g.on_duplicates_tab).length)} are on the workbook's Duplicates tab.`],
    table: table("t-returning", "Groups of resolutions with the same title", ["Years apart", "Groups"], [...gapHist.entries()].sort((a, b) => a[0] - b[0]).map(([g, n]) => [String(g), fmt(n)])), csv: "t-returning",
    extra: `<h3 class="list-h">The same title under two numbers</h3><ol class="grps">${list}</ol>`,
    caveat: "A repeated title is a repeat of words, not a statement that a resolution replaced or renewed another. Same-year repeats stay two resolutions and are marked for review.",
  });
  const second = sec({
    id: "similar", h3: "Titles that share most of their words",
    sub: "At least 3 shared words, and at least three quarters of all the words the two titles use. Similar wording, never what the resolutions are about.",
    summary: `List of ${sim.groups.length} groups of titles that share most of their words.`,
    chartHtml: `<p class="cov-sentence">${fmt(sim.groups.length)} groups, found by counting shared words in ${fmt(sim.groups.reduce((s, g) => s + g.length, 0))} titles; ${fmt(sim.groups.filter(g => g.every(r => exactSet.has(r.n))).length)} of them are the same-title groups above.</p><ol class="grps">${simList}</ol>`, skip: false,
    caveat: "They are shown for reading and never merged.",
  });
  return first + second;
}

function wordIndexBlock(S) {
  const wi = DT.wordIndex();
  const words = [...wi.words.entries()].filter(([, n]) => n >= 10).sort((a, b) => a[0].localeCompare(b[0]));
  const phr = [...wi.phrases.entries()].filter(([, n]) => n >= 5).sort((a, b) => a[0].localeCompare(b[0]));
  const fw = DT.firstWords(25);
  const wTable = table("t-first", "How titles begin, by span of years", ["First word", ...DT.BANDS.map(([a, z]) => `${a} to ${z}`), "All titles"], fw.map(x => [esc(x.w), ...x.c.map(n => fmt(n)), cnt(x.total, makeSpec({ fw: x.w }), `Titles that begin with ${x.w}`)]));
  const btns = (list, attr) => `<ul class="wordlist">${list.map(([w, n]) => `<li><button type="button" class="count wl" data-list="${esc(makeSpec({ [attr]: w }))}" aria-label="${esc(w)}: ${fmt(n)} titles. Open the list.">${esc(w)} <span>${fmt(n)}</span></button></li>`).join("")}</ul>`;
  return sec({
    id: "index", h2: "Words in the Titles", h3: "The word index",
    sub: "Every word in 10 or more titles, in alphabetical order with its count. An alphabetical index, not a ranking of topics.",
    summary: `Alphabetical index of ${words.length} words that each appear in 10 or more titles.`,
    chartHtml: `<details class="tbl"><summary>Show the ${fmt(words.length)} words in 10 or more titles</summary>${btns(words, "w")}</details><details class="tbl"><summary>Show the ${fmt(phr.length)} two-word phrases in 5 or more titles</summary>${btns(phr, "ph")}</details><details class="tbl" open><summary>How titles begin</summary>${wTable}</details>`, skip: false,
    cov: [`${fmt(wi.distinct)} distinct words are used across ${fmt(D.total)} listed resolutions. Words are matched whole, in any letter case. Joining words (a, an, and, for, of, the, to and similar) are left out. Synonyms are not combined: IHS and Indian Health Service are separate entries.`],
    caveat: `A word match is a text match in the title, never what a resolution is about. ${plural(D.agg.coverage_by_year.all.resolutions - D.agg.coverage_by_year.all.with_title, "resolution has", "resolutions have")} no title in the record.`,
  });
}

export function view_words(S) {
  const lookup = `<section class="vs" id="lookup" aria-labelledby="lookup-h"><h2 id="lookup-h">Look Up a Word</h2><p class="sub">Count the titles that use a word, by year, and open the list.</p>${wordBox(S, "w")}${src()}</section>`;
  const clusters = `<section class="vs" id="clusters" aria-labelledby="clusters-h"><h2 id="clusters-h">Clusters</h2>
    <div class="empty-state"><h3>Groups by Similar Wording Are Not Built Yet</h3><p>Groups of resolutions whose full text uses similar words wait for a later build. Nothing here approximates them. What can be counted now is on this tab: the word index, two-word phrases, how titles begin, titles that appear more than once and titles that share most of their words.</p></div>
    <p class="caveat">Full text exists only from 2007, so a full-text group says nothing about 2000 to 2006. A group by title covers every year, and ${plural(D.agg.coverage_by_year.all.resolutions - D.agg.coverage_by_year.all.with_title, "title is", "titles are")} blank.</p></section>`;
  return lookup + returningBlock(S) + wordIndexBlock(S) + clusters;
}

/* ---------------------------------------------------------------------------------------------------------- */
/* THE RECORD                                                                                                   */
const GRID_FIELDS = ["title", "committee", "committeeConfirmed", "preparer", "convention", "outcome", "ncai", "permalink", "site"];
function coverageBlock(S) {
  const f = S.f, yrs = yearsIn(f), mats = Object.fromEntries(GRID_FIELDS.map(x => [x, DT.covMatrix(x, f.k, f.c)]));
  const tot = DT.covMatrix("title", f.k, f.c);
  const cell = (x, y) => {
    const c = mats[x][D.yi.get(y)], st = covState(c.n, c.total);
    if (st === "empty") return "";
    const label = `${y}, ${FIELDS[x].name}: ${c.n === 0 ? "recorded for none of" : "recorded for " + ofWhole(c.n, c.total) + ","} ${c.n === 0 ? fmt(c.total) + " resolutions" : "resolutions"}`.replace(/,\s*resolutions$/, " resolutions");
    const inner = c.n === 0 ? `<span class="cg-hatch" aria-hidden="true"></span><span class="cg-t">0 of ${fmt(c.total)}</span>` : `<span class="cg-t">${ofWhole(c.n, c.total)}</span>`;
    return `<button type="button" class="cg cg-${st}" style="--share:${Math.round((c.n / c.total) * 100)}%" data-list="${esc(makeSpec({ y, has: x, k: f.k, c: f.c, ly: f.c ? "b" : "" }))}" aria-label="${esc(label)}. Open the list.">${inner}</button>`;
  };
  const wide = `<div class="tbl-wrap"><table class="data covgrid2" id="t-cov"><caption class="sr-only">What the record holds, year by year: each cell is the number of resolutions with the field recorded, of the resolutions numbered that year</caption><thead><tr><th scope="col">Year</th><th scope="col" class="num">Resolutions</th>${GRID_FIELDS.map(x => `<th scope="col" class="num">${esc(FIELDS[x].name)}</th>`).join("")}</tr></thead><tbody>${yrs.map(y => `<tr><th scope="row">${y}</th><td class="num">${fmt(tot[D.yi.get(y)].total)}</td>${GRID_FIELDS.map(x => `<td class="num">${cell(x, y)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  const py = +S.q.get("ry") || (yrs.includes(2019) ? 2019 : yrs[0]);
  const one = `<div class="cov-pick"><label for="ry-pick">Year</label><select id="ry-pick" data-pick="ry">${yrs.map(y => `<option${y === py ? " selected" : ""}>${y}</option>`).join("")}</select></div><table class="data"><caption class="sr-only">${py}, what the record holds</caption><thead><tr><th scope="col">Field</th><th scope="col" class="num">Recorded</th></tr></thead><tbody>${GRID_FIELDS.map(x => `<tr><th scope="row">${esc(FIELDS[x].name)}</th><td class="num">${cell(x, py)}</td></tr>`).join("")}</tbody></table>`;
  return `<div class="cg-wide">${wide}</div><div class="cg-narrow">${one}</div>`;
}
export function view_record(S) {
  const f = S.f, A = D.agg, all = A.coverage_by_year.all;
  const cover = sec({
    id: "coverage", h2: "Where Each Field Is Recorded", h3: "What the record holds, year by year",
    sub: "Each cell is the number of resolutions with the field recorded, of the resolutions numbered that year. A hatched cell is a field recorded for none.",
    summary: "Grid of fields by year: each cell shows how many resolutions have the field recorded.",
    chartHtml: coverageBlock(S), skip: false,
    key: keyHtml([{ cls: "cov-full", label: "Recorded on every resolution" }, { cls: "cov-part", label: "Recorded on some" }, { cls: "cov-none", label: "Recorded on none" }]),
    cov: [`Over all years: title ${ofWhole(all.with_title, all.resolutions)}, committee as written ${ofWhole(all.with_committee_written, all.resolutions)}, confirmed committee ${ofWhole(all.with_committee_applied, all.resolutions)}, Prepared By ${ofWhole(all.with_preparer, all.resolutions)}, convention ${ofWhole(all.with_session, all.resolutions)}, outcome ${ofWhole(all.with_outcome, all.resolutions)}, TO NCAI ${ofWhole(all.with_to_ncai, all.resolutions)}, permalink ${ofWhole(all.with_permalink, all.resolutions)}, text on this site ${ofWhole(all.with_site, all.resolutions)}.`],
    caveat: "A missing number is a gap in the numbering, not a missing resolution; most are absent from the site too. The file column of the workbook is counted only as present or not and is never shown.",
  });
  const gaps = A.number_gaps;
  const gapRows = gaps.by_year.map(g => [String(g.year), fmt(g.highest), fmt(g.count), esc(g.ranges.map(r => (r.includes("..") ? r.split("..").map(n => `${g.year}-${n}`).join(" to ") : `${g.year}-${r}`)).join(" and "))]);
  const missing = missingConventions();
  const gapSec = sec({
    id: "gaps", h3: "Gaps in the numbering",
    sub: `${fmt(gaps.count)} numbers are missing between 1 and the highest listed number of their year, in ${fmt(gaps.by_year.length)} years.`,
    summary: "Table of missing numbers by year.",
    chartHtml: table("t-gaps", "Missing numbers by year", ["Year", "Highest listed number", "Missing", "Which numbers"], gapRows, { numFrom: 1 }), skip: false, csv: "t-gaps",
    cov: [`Conventions missing from the Library: ${esc(join(missing))}.`], caveat: gaps.note.charAt(0).toUpperCase() + gaps.note.slice(1) + ".",
  });
  const sc = A.site_coverage_by_year, soTot = sc.years.reduce((s, r) => s + r.site_only, 0);
  const siteRows = sc.years.filter(r => r.workbook_total || r.site_only).map(r => [String(r.year), fmt(r.workbook_total), cnt(r.linked, makeSpec({ y: r.year, site: "linked" }), `${r.year}, text on this site`), cnt(r.workbook_only, makeSpec({ y: r.year, site: "unlinked" }), `${r.year}, Library only`), fmt(r.site_only)]);
  const siteSec = sec({
    id: "site", h3: "What the Library lists and what this site holds",
    sub: "Resolutions the Library lists, and whether this site holds their text.",
    summary: "Table of resolutions in the Library, with text on this site or not, by year.",
    chartHtml: table("t-site", "What the Library lists and what this site holds, by year", ["Year", "In the Library", "Text on this site", "Library only", "On this site, not in the Library"], siteRows, { numFrom: 1 }), skip: false, csv: "t-site",
    cov: [`This site holds ${fmt(soTot)} numbered resolutions the Library does not list. The Library lists ${fmt(sc.workbook_only_classes["workbook-only-in-site-range"] || 0)} numbers inside the site's years that this site does not hold.`],
    caveat: "Before 2007 this site holds no text; the Library lists titles.",
  });
  const m = A.meta;
  const files = [["The Resolution Library.xlsx", m.source_workbook_sha256], ["rows.jsonl", m.rows_jsonl_sha256], ["stats-recompute.csv", m.stats_recompute_sha256], ...Object.entries(m.ledger_sha256), ["aggregates.json (as loaded here)", D.aggSha || "not available in this browser"]];
  const data = `<section class="vs" id="credit" aria-labelledby="credit-h"><h2 id="credit-h">Download the Numbers</h2>
    <p class="credit">${esc(m.credit)}.</p>
    <p class="sub">Every table on this page has a “Download this table” button, and every list has “Download this list”. Both give a CSV file (comma-separated values), which opens in a spreadsheet. The files behind the counts are below, each with its SHA-256 checksum, a code that changes if the file changes.</p>
    <p><a class="btn" href="../data/aggregates.json" download="aggregates.json">Download aggregates.json</a></p>
    <ul class="shas">${files.map(([n, h]) => `<li><span class="sha-n">${esc(n)}</span><code class="sha">${esc(h)}</code></li>`).join("")}</ul>
    <p class="caveat">The data licence is not set (architecture owner question 22). No file-path column and no review table is ever in a download.</p>${src()}</section>`;
  return cover + gapSec + siteSec + data;
}

/* ---------------------------------------------------------------------------------------------------------- */
/* drawers (need the width of their box)                                                                        */
export const drawers = {
  hero: (el, S) => drawYearChart(el, S, "hero", ["title", "committee", "preparer"]),
  kind: (el, S) => drawYearChart(el, S, "kind", ["convention"]),
  heat(el, S) {
    const id = el.dataset.sum.replace(/-sum$/, ""), f = S.f, yrs = yearsIn(f);
    if (!S.wide) {
      const rowsAll = committeeTotals(S).rows;
      const pickKey = S.q.get("hc") && D.cm[S.q.get("hc")] ? S.q.get("hc") : (rowsAll[0] || {}).key;
      const mx = DT.commMatrix(f.k);
      const rows = yrs.map(y => { const [c, w] = mx.get(pickKey, y); return { year: y, total: c + w, segs: [{ key: "total", n: c, label: `${y}: ${fmt(c)} resolutions`, spec: makeSpec({ y, c: pickKey, ly: "c", k: f.k }) }, { key: "waiting", n: w, label: `${y}: ${fmt(w)} with labels waiting for ATNI`, spec: makeSpec({ y, c: pickKey, ly: "w", k: f.k }) }], yearSpec: makeSpec({ y, c: pickKey, ly: "b", k: f.k }) }; });
      const max = Math.max(1, ...rows.map(r => r.total));
      el.innerHTML = `<div class="cov-pick"><label for="${id}-pick">Committee</label><select id="${id}-pick" data-pick="hc">${rowsAll.map(r => `<option value="${esc(r.key)}"${r.key === pickKey ? " selected" : ""}>${esc(r.name)}</option>`).join("")}</select></div>` + (pickKey ? rowBarsHtml({ id, rows, max }) : `<p class="empty-line">No committee in this selection.</p>`);
      return;
    }
    let years = yrs, windowNav = "";
    if (!S.full && yrs.length > 14) {
      const half = Math.ceil(yrs.length / 2), w = +S.q.get("hw") || 0;
      const parts = [yrs.slice(0, half), yrs.slice(half)];
      years = parts[w] || parts[0];
      windowNav = `<div class="windows" role="group" aria-label="Years shown">${parts.map((p, i) => `<button type="button" class="btn small${i === (w || 0) ? "" : " quiet"}" data-patch="hw=${i || ""}" aria-pressed="${i === (w || 0)}">${p[0]} to ${p[p.length - 1]}</button>`).join("")}</div>`;
    }
    el.innerHTML = windowNav + heatmapHtml({ id, years, rows: heatRows(S, years) });
  },
  career(el, S) {
    const key = el.dataset.person, p = D.persons.get(key), f = S.f;
    const yrs = D.years;
    const covP = DT.covMatrix("preparer", "", "");
    const rows = yrs.map(y => { const n = p.by_year[y] || 0; const c = covP[D.yi.get(y)]; return { year: y, total: n, segs: [{ key: "total", n, label: `${y}: named on ${fmt(n)} resolutions`, spec: makeSpec({ p: key, y }) }], yearSpec: makeSpec({ p: key, y }), text: n ? fmt(n) : (c.n === 0 ? nr : ""), cov: { state: covState(c.n, c.total), share: c.total ? c.n / c.total : 0, text: `${y}: Prepared By recorded for ${ofWhole(c.n, c.total)} resolutions` } }; });
    const max = Math.max(1, ...rows.map(r => r.total));
    const id = el.dataset.sum.replace(/-sum$/, "");
    if (S.wide) el.innerHTML = yearBarsSvg({ id, width: el.clientWidth, height: 120, rows, max, href: S.listHref, strips: [{ name: "Prepared By recorded", cells: covCells(S, "preparer", yrs) }] }) + keyHtml([{ cls: "s-total", label: "Resolutions that name this person" }, ...COV_KEY]);
    else el.innerHTML = rowBarsHtml({ id, rows, max, covName: "Prepared By recorded" }) + keyHtml([{ cls: "s-total", label: "Resolutions that name this person" }, ...COV_KEY]);
  },
  dots(el, S) {
    const f = S.f, G = D.agg.readoptions.groups.filter(g => g.members.some(m => m.year >= f.y0 && m.year <= f.y1)).map(g => ({ ...g, gap: g.members[g.members.length - 1].year - g.members[0].year }));
    const id = el.dataset.sum.replace(/-sum$/, ""), maxGap = Math.max(1, ...G.map(g => g.gap));
    const groups = G.map(g => { const spec = makeSpec({ nums: g.members.map(m => m.number).join(";") }); return { id: g.group_id, gap: g.gap, label: `${g.members.map(m => m.number).join(", ")}: ${g.gap === 0 ? "same year" : plural(g.gap, "year", "years") + " apart"}`, spec, href: S.listHref(spec) }; });
    el.innerHTML = `<p class="axis-t">Years apart</p>` + dotPlotSvg({ id, width: el.clientWidth, groups, maxGap });
  },
};
