/* Years and Conventions: resolutions each year (recorded, likely, numbered, the moving average), conventions compared,
   outcomes, TO NCAI and places. Also the hero of the Overview, which is the same chart. */
import { D, KINDS, KIND_LABEL, FIELDS, makeSpec, esc, fmt, plural, ofWhole, covState, unrecordedRuns, kindLabel, yearsIn, span, cname, nr, median, num1, join, runs,
  missingConventions, cnt, splitCell, table, sec, keyHtml, COV_KEY, covSentence, covCells, lrow, basisKey, mark, uncertain, WORD_LIKELY, WORD_OPEN } from "./kit.js";
import * as DT from "./data.js";
import { yearBarsSvg, rowBarsHtml } from "./charts.js";

export const SMOOTH_METHOD = "The line is the mean of a year and the years either side, drawn only where all three years hold every convention in the Library. It breaks at a year with a convention missing.";
let covPick = "preparer", risen = false;
export const setCovPick = v => { covPick = v; };

/* ---------------------------------------------------------------------------------------------------------- */
/* data for the year charts                                                                                     */
/** One row per year in the filter. Each seg is {key, kind, n, label, spec}; key "likely" is the hatched part. `s` and
 *  `l` are the recorded and likely counts of the bar; `tick` the highest number of the year; `smooth` the mean. */
export function yearData(S, mode) {
  const f = S.f, km = DT.kindMatrix(f.c), plain = !f.k && !f.c;
  const keys = f.k ? [f.k] : DT.ALL_KINDS;
  const rows = [];
  let max = 1;
  for (const y of yearsIn(f)) {
    const m = km[D.yi.get(y)], a = D.agg.years[D.yi.get(y)];
    const sp = o => makeSpec({ y, c: f.c, ...o });
    const lay = f.c ? { ly: "c" } : { ib: "no" };
    const layL = f.c ? { ly: "l" } : { ib: "likely" };
    const why = f.c ? "the committee link is likely" : "its inclusion is likely";
    const segs = [];
    let s = 0, l = 0;
    if (mode === "hero") {
      for (const k of keys) { s += m.s[k]; l += m.l[k]; }
      segs.push({ key: "total", n: s, label: `${y}: ${fmt(s)} recorded`, spec: sp({ k: f.k, ...lay }) });
      if (l) segs.push({ key: "likely", n: l, label: `${y}: ${fmt(l)} likely (${why})`, spec: sp({ k: f.k, ...layL }) });
    } else {
      for (const k of keys) {
        const kl = m.kl[k], sol = m.s[k] - kl, lk = m.l[k];
        s += sol; l += kl + lk;
        segs.push({ key: k, kind: k, n: sol, label: `${y}, ${kindLabel(k)}: ${fmt(sol)} recorded`, spec: sp({ k, kb: "no", ...lay }) });
        if (kl) segs.push({ key: "likely", kind: k, n: kl, label: `${y}, ${kindLabel(k)}: ${fmt(kl)} likely (the convention is likely)`, spec: sp({ k, kb: "likely", ...lay }) });
        if (lk) segs.push({ key: "likely", kind: k, n: lk, label: `${y}, ${kindLabel(k)}: ${fmt(lk)} likely (${why})`, spec: sp({ k, ...layL }) });
      }
    }
    const total = s + l;
    const so = plain ? D.siteOnly.get(y) || 0 : 0;
    const tick = plain && a.numbered > 0 ? { n: a.numbered, label: `${y}: highest number ${fmt(a.numbered)}${a.number_gaps ? `; ${plural(a.number_gaps, "number is", "numbers are")} not in the record` : ""}` } : null;
    rows.push({
      year: y, total, s, l, segs, tick, numbered: a.numbered, gaps: a.number_gaps, smooth: a.smooth,
      outline: so ? { key: "siteonly", n: so, label: `${y}: ${fmt(so)} numbered resolutions on this site that the Library does not list` } : null,
      yearSpec: makeSpec({ y, k: f.k, c: f.c, ly: f.c ? "b" : "" }),
    });
    max = Math.max(max, total + so, tick ? tick.n : 0);
  }
  return { rows, max, plain };
}

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
  const lk = d.rows.reduce((n, r) => n + r.l, 0);
  if (lk) t += ` ${fmt(lk)} of them are marked likely.`;
  for (const [fld, cells] of allCov) {
    const r = unrecordedRuns(cells, d.rows.map(x => x.year));
    if (r.length) t += ` ${FIELDS[fld].name} is not recorded for any resolution in ${join(r)}.`;
  }
  return t;
}
const SERIES_KEY = [{ cls: "s-winter", k: "winter", label: "Winter" }, { cls: "s-midyear", k: "midyear", label: "Mid-Year" }, { cls: "s-annual", k: "annual", label: "Annual" }, { cls: "s-executive", k: "executive", label: "Executive Board" }, { cls: "s-special", k: "special", label: "Special" }];

export function drawYearChart(el, S, mode, fields) {
  const d = yearData(S, mode), yrs = d.rows.map(r => r.year), id = el.dataset.sum.replace(/-sum$/, "");
  const sumEl = document.getElementById(id + "-sum");
  const showLine = S.sm && d.plain;
  if (sumEl) {
    if (sumEl.dataset.base === undefined) sumEl.dataset.base = sumEl.textContent.replace(/ A table with the same numbers follows\.$/, "");
    sumEl.textContent = `${sumEl.dataset.base} ${readingOf(d, fields.map(fld => [fld, covCells(S, fld, yrs)]))}${showLine ? ` The three-year moving average is drawn as a line. ${SMOOTH_METHOD}` : ""} Show table, below the chart, has the same numbers.`.replace(/\s+/g, " ");
  }
  const heroH = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--resist-hero-height")) || 200;
  let key = [];
  if (mode !== "hero") key = S.f.k ? SERIES_KEY.filter(k => k.k === S.f.k) : SERIES_KEY.slice();
  const hasLikely = d.rows.some(r => r.l > 0);
  if (mode === "hero" && d.plain) key.push({ cls: "s-siteonly", label: "Numbered on this site, not in the Library" });
  if (mode !== "hero" && !S.f.k) key.push({ cls: "s-none", label: "Convention not recorded" });
  if (d.plain) key.push({ cls: "s-tick", label: "Highest number of the year" });
  if (showLine) key.push({ cls: "s-smooth", label: "Three-year moving average" });
  const line = showLine ? { values: d.rows.map(r => r.smooth), titles: d.rows.map(r => (r.smooth == null ? null : `${r.year}: three-year mean ${num1(r.smooth)}`)) } : null;
  const after = (hasLikely || mode === "hero" ? basisKey(hasLikely ? ["likely"] : [], mode === "hero") : "") + (S.sm && !d.plain ? `<p class="cov-sentence">The moving average is for all resolutions. Clear the convention and committee filters to draw it.</p>` : "");
  if (S.wide) {
    const strips = fields.map(fld => ({ name: FIELDS[fld].rec, cells: covCells(S, fld, yrs) }));
    el.innerHTML = yearBarsSvg({ id, width: el.clientWidth, height: heroH, rows: d.rows, max: d.max, href: S.listHref, strips, line, rise: mode === "hero" && !risen });
    if (mode === "hero") risen = true;
    key = key.concat(COV_KEY);
    el.insertAdjacentHTML("beforeend", keyHtml(key) + after);
  } else {
    const fld = fields.includes(covPick) ? covPick : fields[0];
    const cells = covCells(S, fld, yrs);
    const rows = d.rows.map((r, i) => ({ ...r, text: fmt(r.total) + (r.outline ? ` <span class="rb-plus">+ ${fmt(r.outline.n)}</span>` : "") + (r.tick ? ` <span class="rb-plus">numbered ${fmt(r.tick.n)}</span>` : "") + (showLine && r.smooth != null ? ` <span class="rb-plus">mean ${num1(r.smooth)}</span>` : ""), cov: cells[i] }));
    el.innerHTML = `<div class="cov-pick"><label for="${id}-cp">Field recorded beside each year</label><select id="${id}-cp" data-cov-pick>${fields.map(x => `<option value="${x}"${x === fld ? " selected" : ""}>${esc(FIELDS[x].rec)}</option>`).join("")}</select></div>`
      + rowBarsHtml({ id, rows, max: d.max, covName: FIELDS[fld].rec })
      + keyHtml(key.concat(COV_KEY)) + after;
  }
}

/** A cell for one kind: the recorded count, then each likely part beside it with its word. */
function segCell(segs, label) {
  const sol = segs.find(s => s.key !== "likely"), lks = segs.filter(s => s.key === "likely" && s.n > 0);
  if (!(sol && sol.n) && !lks.length) return `<span class="zero">0</span>`;
  return `${sol && sol.n ? cnt(sol.n, sol.spec, `${label}, recorded`) : ""}${lks.map(s => ` <span class="lkn">${sol && sol.n ? "+ " : ""}${cnt(s.n, s.spec, `${label}, likely`)} ${WORD_LIKELY}</span>`).join("")}`;
}

export function yearTable(S, mode) {
  const d = yearData(S, mode), f = S.f;
  const head = ["Year"];
  const withNum = d.plain && !f.k;
  if (mode === "hero") head.push(f.c ? "Recorded under it" : "Recorded", f.c ? "Likely under it" : "Included as likely");
  else (f.k ? [f.k] : DT.ALL_KINDS).forEach(k => head.push(k === "none" ? "Convention not recorded" : kindLabel(k)));
  if (withNum) head.push("Numbered (highest number)", "Numbers not in the record", "Numbered on this site, not in the Library");
  if (S.sm && d.plain) head.push("Three-year mean");
  const fieldsFor = mode === "hero" ? ["title", "committee", "preparer"] : ["convention"];
  fieldsFor.forEach(x => head.push(FIELDS[x].rec));
  const cov = fieldsFor.map(x => DT.covMatrix(x, f.k, f.c));
  const rows = d.rows.map(r => {
    const row = [`<button type="button" class="count" data-list="${esc(r.yearSpec)}" aria-label="${r.year}: open the list">${r.year}</button>`];
    if (mode === "hero") {
      const sp = r.segs[0].spec, lsp = (r.segs.find(s => s.key === "likely") || {}).spec;
      row.push(f.c ? cnt(r.s, sp, `${r.year}, recorded`) : cnt(r.total, r.yearSpec, `${r.year}, recorded`), r.l ? cnt(r.l, lsp, `${r.year}, likely`) : `<span class="zero">0</span>`);
    } else for (const k of (f.k ? [f.k] : DT.ALL_KINDS)) row.push(segCell(r.segs.filter(s => s.kind === k), `${r.year}, ${kindLabel(k)}`));
    if (withNum) {
      row.push(r.numbered ? fmt(r.numbered) : `<span class="zero">0</span>`,
        r.gaps ? `<button type="button" class="count" data-goto="gaps" aria-label="${r.year}: ${plural(r.gaps, "number is", "numbers are")} not in the record. Go to the list of numbers.">${fmt(r.gaps)}</button>` : `<span class="zero">0</span>`,
        r.outline ? fmt(r.outline.n) : `<span class="zero">0</span>`);
    }
    if (S.sm && d.plain) row.push(r.smooth == null ? `<span class="nr">gap</span>` : num1(r.smooth));
    cov.forEach(m => { const c = m[D.yi.get(r.year)]; row.push(c.total === 0 ? "" : c.n === 0 ? nr : ofWhole(c.n, c.total)); });
    return row;
  });
  return table(`t-${mode}`, mode === "hero" ? "Resolutions recorded each year" : "Resolutions by convention", head, rows);
}

/** The switch for the moving average, off at first, with the method beside it. */
export function smoothSwitch(S, idp) {
  return `<label class="switch"><input type="checkbox" data-switch="sm"${S.sm ? " checked" : ""} aria-describedby="${idp}-smn"> Show a three-year moving average</label><span class="sm-note" id="${idp}-smn">${esc(SMOOTH_METHOD)}</span>`;
}

const sumLikelyIncluded = () => D.agg.years.reduce((s, y) => s + y.likely_included, 0);
export function heroSection(S) {
  const f = S.f, km = DT.kindMatrix(f.c);
  const keys = f.k ? [f.k] : DT.ALL_KINDS;
  let s = 0, l = 0;
  for (const y of yearsIn(f)) { const m = km[D.yi.get(y)]; for (const k of keys) { s += m.s[k]; l += m.l[k]; } }
  const totalGaps = D.agg.years.reduce((n, y) => n + y.number_gaps, 0);
  const heading = f.c ? `${esc(cname(f.c))}: ${fmt(s)} recorded${l ? `, ${fmt(l)} likely` : ""}, ${esc(span(f))}` : `${fmt(s + l)} resolutions, ${esc(span(f))}`;
  return sec({
    id: "hero", h2: heading, h3: "Resolutions recorded each year",
    sub: `One bar for each year, ${esc(span(f))}. Each bar opens the list of resolutions behind it. A short bar across a column marks the highest number written for that year.`,
    summary: `Bar chart of resolutions recorded each year, ${span(f)}, with the highest number of each year marked. A table with the same numbers follows.`,
    chart: "hero", table: yearTable(S, "hero"), csv: "t-hero", pre: `<div class="chart-tools">${smoothSwitch(S, "hero")}</div>`,
    cov: [covSentence(S, "preparer"), covSentence(S, "committee"), covSentence(S, "title"),
      !f.c && sumLikelyIncluded() ? `${fmt(sumLikelyIncluded())} resolutions are included in the counts as likely, not yet verified. They carry the word likely in every list.` : "",
      !f.c && !f.k && totalGaps ? `Numbered is the highest number written for a year, from the Library and this site. ${fmt(totalGaps)} numbers below those highest numbers are in neither: they are listed under The Record, never drawn as resolutions.` : ""].filter(Boolean),
    caveat: `Counted from The Resolution Library. A resolution is counted once, in the year of its number. ${D.siteFirstYear ? `Before ${D.siteFirstYear} this site holds no text; the Library lists titles. ` : ""}An outlined segment is a numbered resolution this site holds and the Library does not list. A hatched segment is likely.`,
  });
}

/* ---------------------------------------------------------------------------------------------------------- */
/* conventions                                                                                                  */
const step = n => (n <= 1 ? 1 : n <= 3 ? 2 : n <= 6 ? 3 : n <= 10 ? 4 : n <= 15 ? 5 : 6);
function conventionsBlock(S) {
  const f = S.f, km = DT.kindMatrix(f.c);
  const yrs = yearsIn(f);
  const kinds = f.k ? KINDS.filter(k => k.key === f.k) : KINDS;
  const spec = (y, k) => makeSpec({ y, k, c: f.c, ly: f.c ? "b" : "" });
  const head = `<thead><tr><th scope="col">Year</th>${kinds.map(k => `<th scope="col" class="num">${k.label}</th>`).join("")}${f.k ? "" : `<th scope="col" class="num">Not recorded<span class="sr-only"> (convention)</span></th>`}<th scope="col" class="num">Recorded</th></tr></thead>`;
  let body = "";
  const lk = (m, k) => m.l[k] + m.kl[k];
  for (const y of yrs) {
    const m = km[D.yi.get(y)];
    body += `<tr><th scope="row">${y}</th>`;
    for (const k of kinds) {
      const n = m.s[k.key] + m.l[k.key], sched = k.key === "winter" || k.key === "midyear" || k.key === "annual", l = lk(m, k.key);
      if (n === 0 && sched && !f.c) body += `<td class="num"><span class="gridcell miss" role="img" aria-label="${y} ${k.label}: ${y === D.yMin && m.s.none + m.l.none ? "no convention recorded" : "not in the Library"}" data-tip="${y} ${k.label}: ${y === D.yMin && m.s.none + m.l.none ? "no convention recorded" : "not in the Library"}"></span></td>`;
      else if (n === 0) body += `<td class="num"><span class="zero">0</span></td>`;
      else body += `<td class="num"><button type="button" class="gridcell step-${step(n)}${l ? " lk" : ""}" data-list="${esc(spec(y, k.key))}" aria-label="${y} ${k.label}: ${fmt(n)} resolutions${l ? `, ${fmt(l)} likely` : ""}. Open the list.">${l ? `${fmt(n - l)}${n - l ? " + " : ""}${fmt(l)} <span class="gc-w">likely</span>` : fmt(n)}</button></td>`;
    }
    if (!f.k) { const n = m.s.none + m.l.none, l = lk(m, "none"); body += `<td class="num">${n ? `<button type="button" class="gridcell none-n${l ? " lk" : ""}" data-list="${esc(spec(y, "none"))}" aria-label="${y}, convention not recorded: ${fmt(n)} resolutions${l ? `, ${fmt(l)} likely` : ""}. Open the list.">${l ? `${fmt(n - l)}${n - l ? " + " : ""}${fmt(l)} <span class="gc-w">likely</span>` : fmt(n)}</button>` : `<span class="zero">0</span>`}</td>`; }
    const tot = f.k ? m.s[f.k] + m.l[f.k] : m.sT + m.lT;
    body += `<td class="num"><button type="button" class="count" data-list="${esc(makeSpec({ y, k: f.k, c: f.c, ly: f.c ? "b" : "" }))}" aria-label="${y}: ${fmt(tot)} resolutions. Open the list.">${fmt(tot)}</button></td></tr>`;
  }
  const grid = `<div class="tbl-wrap"><table class="data convgrid" id="t-convgrid"><caption class="sr-only">Resolutions at each convention, one row for each year. A count marked likely is a likely reading.</caption>${head}<tbody>${body}</tbody></table></div>`;
  const nOf = (m, k) => m.s[k] + m.l[k];
  const kRows = KINDS.map(k => {
    const ns = yrs.map(y => ({ y, n: nOf(km[D.yi.get(y)], k.key) })).filter(x => x.n > 0);
    const tot = ns.reduce((s, x) => s + x.n, 0);
    const big = ns.reduce((a, x) => (x.n > a.n ? x : a), { n: -1 }), small = ns.reduce((a, x) => (x.n < a.n ? x : a), { n: 1e9 });
    return [k.label, fmt(ns.length), cnt(tot, makeSpec({ k: k.key, c: f.c, ly: f.c ? "b" : "", y0: f.y0, y1: f.y1 }), k.label), ns.length ? num1(median(ns.map(x => x.n))) : nr, ns.length ? `${fmt(big.n)} (${big.y} ${k.label})` : nr, ns.length ? `${fmt(small.n)} (${small.y} ${k.label})` : nr];
  });
  const kTable = table("t-kinds", "Sessions and resolutions for each convention kind", ["Kind", "Sessions", "Resolutions", "Median per session", "Largest", "Smallest"], kRows);
  const sched = ["winter", "midyear", "annual"];
  const bandsDef = D.agg.meta.bands || [[2001, 2006], [2007, 2012], [2013, 2018], [2019, D.yMax]];
  const bands = bandsDef.map(([a, z]) => {
    const ns = []; for (const y of D.years) if (y >= a && y <= z) for (const k of sched) { const n = nOf(km[D.yi.get(y)], k); if (n > 0) ns.push(n); }
    return [`${a} to ${z}`, fmt(ns.length), ns.length ? num1(median(ns)) : nr];
  });
  const allN = []; for (const y of D.years) for (const k of sched) { const n = nOf(km[D.yi.get(y)], k); if (n > 0) allN.push(n); }
  const bTable = table("t-bands", "Median resolutions per scheduled session, by span of years", ["Years", "Scheduled sessions", "Median per session"], bands);
  const last = D.yMax, a = km[D.yi.get(last)], b = km[D.yi.get(last - 1)];
  const held = KINDS.filter(k => nOf(a, k.key) > 0);
  const so = held.length ? `${last} so far: ${held.map(k => `${k.label} ${fmt(nOf(a, k.key))}`).join(", ")}. At the same point in ${last - 1}: ${held.map(k => `${k.label} ${fmt(nOf(b, k.key))}`).join(", ")}.` : "";
  // committee by kind: recorded and likely links, counted once per committee
  const ck = new Map();
  for (const r of D.rows) {
    if (r.y < f.y0 || r.y > f.y1) continue;
    const seen = new Map();
    for (const [key, b2] of r.cs) { if (b2 === "r") seen.set(key, "s"); else if (!seen.has(key)) seen.set(key, "l"); }
    for (const [key, lay] of seen) { if (!ck.has(key)) ck.set(key, { s: Object.fromEntries(DT.ALL_KINDS.map(x => [x, 0])), l: Object.fromEntries(DT.ALL_KINDS.map(x => [x, 0])) }); ck.get(key)[lay][r.k || "none"]++; }
  }
  const ckRows = [...ck.entries()].sort((x, y) => cname(x[0]).localeCompare(cname(y[0]))).map(([key, c]) => [esc(cname(key)), ...DT.ALL_KINDS.map(k => splitCell(c.s[k], c.l[k], makeSpec({ c: key, ly: "c", k, y0: f.y0, y1: f.y1 }), makeSpec({ c: key, ly: "l", k, y0: f.y0, y1: f.y1 }), `${cname(key)}, ${kindLabel(k)}`))]);
  return { grid, kTable, bTable, so, allMedian: allN.length ? num1(median(allN)) : "", nSched: allN.length, bandsNote: !D.agg.meta.bands, ckTable: table("t-ck", "Committees by convention kind, recorded and likely", ["Committee", ...KINDS.map(k => k.label), "Convention not recorded"], ckRows) };
}

/* ---------------------------------------------------------------------------------------------------------- */
/* outcomes and TO NCAI                                                                                         */
function outcomesBlock(S) {
  const f = S.f, m = DT.outcomeMatrix(f.k, f.c), yrs = yearsIn(f);
  const max = Math.max(1, ...yrs.map(y => m[D.yi.get(y)].resolutions));
  const ly = f.c ? "b" : "";
  const sp = (y, o) => makeSpec({ y, k: f.k, c: f.c, ly, ...o });
  const rows = yrs.map(y => {
    const o = m[D.yi.get(y)], total = o.resolutions;
    const segs = [];
    for (const v of ["adopted", "not_adopted", "tabled"]) {
      const lk = o.lk[v], s = o[v] - lk;
      segs.push({ key: v, n: s, label: `${y}: recorded as ${DT.OUTCOME_LABEL[v]}: ${fmt(s)} resolutions`, spec: sp(y, { o: v, ob: "no" }) });
      if (lk) segs.push({ key: "likely", n: lk, label: `${y}: likely ${DT.OUTCOME_LABEL[v]}: ${fmt(lk)} resolutions`, spec: sp(y, { o: v, ob: "likely" }) });
    }
    const plainNone = o.not_recorded - o.open;
    if (plainNone) segs.push({ key: "none", n: plainNone, label: `${y}: outcome not recorded for ${fmt(plainNone)} resolutions`, spec: sp(y, { o: "norec", ob: "no" }) });
    if (o.open) segs.push({ key: "open", n: o.open, label: `${y}: outcome open, kept as written, for ${fmt(o.open)} resolutions`, spec: sp(y, { o: "norec", ob: "open" }) });
    const st = covState(o.recorded, total);
    const extra = (o.likely ? `, ${fmt(o.likely)} likely` : "") + (o.open ? `, ${fmt(o.open)} open` : "");
    return { year: y, total, segs, yearSpec: sp(y, {}), text: total ? (o.recorded === 0 ? nr + (o.open ? ` ${fmt(o.open)} open` : "") : `${ofWhole(o.recorded, total)} recorded${extra}`) : "", cov: { state: st, share: total ? o.recorded / total : 0, text: `${y}: outcome recorded for ${ofWhole(o.recorded, total)} resolutions` } };
  });
  const full = yrs.filter(y => { const o = m[D.yi.get(y)]; return o.resolutions && o.recorded === o.resolutions; });
  const part = yrs.filter(y => { const o = m[D.yi.get(y)]; return o.recorded > 0 && o.recorded < o.resolutions; });
  const none = yrs.filter(y => m[D.yi.get(y)].recorded === 0 && m[D.yi.get(y)].resolutions);
  const na = DT.sumBy(m, f, r => r.not_adopted), tb = DT.sumBy(m, f, r => r.tabled), ad = DT.sumBy(m, f, r => r.adopted), lkAll = DT.sumBy(m, f, r => r.likely), opAll = DT.sumBy(m, f, r => r.open);
  const listed = D.rows.filter(r => (r.o === "not_adopted" || r.o === "tabled") && r.y >= f.y0 && r.y <= f.y1 && DT.selects(r, f.k, f.c));
  const cell = (y, o, v) => (o.recorded === 0 ? nr : splitCell(o[v] - o.lk[v], o.lk[v], sp(y, { o: v, ob: "no" }), sp(y, { o: v, ob: "likely" }), `${y}, ${DT.OUTCOME_LABEL[v]}`));
  const tbl = table("t-outcomes", "Outcomes recorded for resolutions, by year", ["Year", "Yes (adopted)", "No (not adopted)", "Tabled", "Outcome recorded", "Open, kept as written", "Resolutions"],
    yrs.map(y => { const o = m[D.yi.get(y)]; return [String(y), ...["adopted", "not_adopted", "tabled"].map(v => cell(y, o, v)), o.recorded === 0 ? nr : ofWhole(o.recorded, o.resolutions), o.open ? cnt(o.open, sp(y, { o: "norec", ob: "open" }), `${y}, outcome open`) : `<span class="zero">0</span>`, fmt(o.resolutions)]; }));
  return {
    chartHtml: rowBarsHtml({ id: "outcomes", rows, max, covName: "Outcome recorded" }),
    key: keyHtml([{ cls: "s-adopted", label: "Yes (adopted)" }, { cls: "s-not_adopted", label: "No (not adopted)" }, { cls: "s-tabled", label: "Tabled" }, { cls: "s-none", label: "Outcome not recorded" }, ...COV_KEY]) + basisKey(["likely", "open"]),
    table: tbl,
    cov: [covSentence({ ...S }, "outcome"), `${fmt(na + tb)} resolutions are recorded as not adopted (${fmt(na)}) or tabled (${fmt(tb)}); ${fmt(ad)} are recorded as adopted.${lkAll ? ` ${fmt(lkAll)} of the recorded outcomes are likely.` : ""}${opAll ? ` ${fmt(opAll)} blanks inside otherwise recorded conventions are open, kept as written.` : ""}`, `Outcome is recorded in every resolution of ${full.length ? esc(join(runs(full))) : "no year"}${part.length ? `, and for part of ${esc(join(runs(part)))}` : ""}. It is not recorded for ${none.length ? esc(join(runs(none))) : "no year"}.`],
    listed,
  };
}

function ncaiBlock(S) {
  const f = S.f, m = DT.ncaiMatrix(f.k, f.c), yrs = yearsIn(f);
  const max = Math.max(1, ...yrs.map(y => m[D.yi.get(y)].resolutions));
  const ly = f.c ? "b" : "";
  const sp = (y, o) => makeSpec({ y, k: f.k, c: f.c, ly, ...o });
  const rows = yrs.map(y => {
    const o = m[D.yi.get(y)], total = o.resolutions;
    const segs = ["yes", "no", "na"].map(k => ({ key: k, n: o[k], label: `${y}: TO NCAI ${DT.NCAI_LABEL[k]}: ${fmt(o[k])} resolutions`, spec: sp(y, { nc: k }) }));
    const plainNone = o.not_recorded - o.open;
    if (plainNone) segs.push({ key: "none", n: plainNone, label: `${y}: TO NCAI not recorded for ${fmt(plainNone)} resolutions`, spec: sp(y, { nc: "norec", nb: "no" }) });
    if (o.open) segs.push({ key: "open", n: o.open, label: `${y}: TO NCAI open, kept as written, for ${fmt(o.open)} resolutions`, spec: sp(y, { nc: "norec", nb: "open" }) });
    return { year: y, total, segs, yearSpec: sp(y, {}), text: o.recorded === 0 ? (total ? nr + (o.open ? ` ${fmt(o.open)} open` : "") : "") : `${ofWhole(o.yes, o.recorded, true)} Yes${o.open ? `, ${fmt(o.open)} open` : ""}`, cov: { state: covState(o.recorded, total), share: total ? o.recorded / total : 0, text: `${y}: TO NCAI recorded for ${ofWhole(o.recorded, total)} resolutions` } };
  });
  const tot = k => DT.sumBy(m, f, r => r[k]);
  const fullYears = yrs.filter(y => { const o = m[D.yi.get(y)]; return o.resolutions && o.recorded === o.resolutions; });
  const partYears = yrs.filter(y => { const o = m[D.yi.get(y)]; return o.recorded > 0 && o.recorded < o.resolutions; });
  const cmap = new Map();
  for (const r of D.rows) {
    if (r.y < f.y0 || r.y > f.y1 || !r.nc || (f.k && r.k !== f.k)) continue;
    const seen = new Map();
    for (const [key, b] of r.cs) { if (b === "r") seen.set(key, "c"); else if (!seen.has(key)) seen.set(key, "l"); }
    for (const [key, lay] of seen) { const id = key + "|" + lay; if (!cmap.has(id)) cmap.set(id, { key, ly: lay, rec: 0, yes: 0, no: 0, na: 0 }); const o = cmap.get(id); o.rec++; o[r.nc]++; }
  }
  const cRows = [...cmap.values()].sort((a, b) => b.rec - a.rec || cname(a.key).localeCompare(cname(b.key))).map(o => [`${esc(cname(o.key))}${o.ly === "l" ? ` ${WORD_LIKELY}` : ""}`, ofWhole(o.yes, o.rec, true) + " Yes", cnt(o.rec, makeSpec({ c: o.key, ly: o.ly, nc: "rec", k: f.k, y0: f.y0, y1: f.y1 }), cname(o.key)), cnt(o.yes, makeSpec({ c: o.key, ly: o.ly, nc: "yes", k: f.k, y0: f.y0, y1: f.y1 }), `${cname(o.key)}, Yes`), cnt(o.no, makeSpec({ c: o.key, ly: o.ly, nc: "no", k: f.k, y0: f.y0, y1: f.y1 }), `${cname(o.key)}, No`), cnt(o.na, makeSpec({ c: o.key, ly: o.ly, nc: "na", k: f.k, y0: f.y0, y1: f.y1 }), `${cname(o.key)}, n/a`)]);
  const nf = new Set(DT.ncaiMatrix("", f.c).filter(o => o.resolutions && o.recorded === o.resolutions).map(o => o.year));
  const kRows = ["midyear", "annual", "winter"].map(k => { const rs = D.rows.filter(r => r.k === k && nf.has(r.y) && r.nc && DT.selects(r, "", f.c)); const y = rs.filter(r => r.nc === "yes").length; return { k, rec: rs.length, yes: y }; }).sort((a, b) => b.yes / (b.rec || 1) - a.yes / (a.rec || 1)).map(o => [kindLabel(o.k), ofWhole(o.yes, o.rec, true) + " Yes", cnt(o.rec, makeSpec({ k: o.k, nc: "rec", c: f.c, ly: f.c ? "b" : "", ys: [...nf].join(",") }), kindLabel(o.k))]);
  return {
    chartHtml: rowBarsHtml({ id: "ncai", rows, max, covName: "TO NCAI recorded" }),
    key: keyHtml([{ cls: "s-yes", label: "Yes" }, { cls: "s-no", label: "No" }, { cls: "s-na", label: "n/a" }, { cls: "s-none", label: "Not recorded" }, ...COV_KEY]) + basisKey(["open"]),
    table: table("t-ncai", "TO NCAI by year", ["Year", "Yes", "No", "n/a", "Recorded", "Open, kept as written", "Resolutions"], yrs.map(y => { const o = m[D.yi.get(y)]; return [String(y), ...["yes", "no", "na"].map(k => o.recorded === 0 ? nr : cnt(o[k], sp(y, { nc: k }), `${y}, TO NCAI ${DT.NCAI_LABEL[k]}`)), o.recorded === 0 ? nr : ofWhole(o.recorded, o.resolutions), o.open ? cnt(o.open, sp(y, { nc: "norec", nb: "open" }), `${y}, TO NCAI open`) : `<span class="zero">0</span>`, fmt(o.resolutions)]; })),
    cov: [covSentence(S, "ncai"), `Of the ${fmt(tot("recorded"))} resolutions with TO NCAI recorded, ${fmt(tot("yes"))} say Yes, ${fmt(tot("no"))} say No and ${fmt(tot("na"))} say n/a. It is recorded in every resolution of ${fullYears.length ? esc(join(runs(fullYears))) : "no year"}${partYears.length ? ` and for part of ${esc(join(runs(partYears)))}` : ""}.${tot("open") ? ` ${fmt(tot("open"))} blanks inside otherwise recorded conventions are open, kept as written.` : ""}`],
    byCommittee: table("t-ncai-c", "TO NCAI by committee, recorded and likely links", ["Committee", "Share Yes", "Recorded", "Yes", "No", "n/a"], cRows, { numFrom: 1 }),
    byKind: table("t-ncai-k", "TO NCAI by convention kind in the years where it is recorded on every resolution", ["Kind", "Share Yes", "Recorded"], kRows),
    fullYears,
  };
}

/* ---------------------------------------------------------------------------------------------------------- */
/* places                                                                                                       */
const SOURCE_WORDS = { conventions_json: "confirmed in the ResIST list of conventions", published_text: "the certification text of the published resolutions" };
function placesBlock(S) {
  const f = S.f, P = D.agg.places, c = P.counts, cv = c.conventions;
  const list = P.sessions.filter(s => s.basis !== null && s.year >= f.y0 && s.year <= f.y1 && (!f.k || s.kind === f.k));
  const rowsHtml = list.map(s => {
    const read = `${fmt(s.naming)} of ${plural(s.usable, "usable reading", "usable readings")} name${s.naming === 1 ? "s" : ""} it, from ${plural(s.texts, "published document", "published documents")} read`;
    const place = s.basis === "recorded" ? esc(s.place) : s.basis === "likely"
      ? uncertain({ text: s.place, basis: "likely", asWritten: null, none: `no place in the workbook; ${read} (${SOURCE_WORDS[s.source] || s.source})` })
      : `<span class="open-text">not known</span> ${WORD_OPEN}`;
    const how = s.basis === "recorded" ? SOURCE_WORDS[s.source] || s.source || "" : s.basis === "likely" ? `${SOURCE_WORDS[s.source] || s.source}: ${read}. Not yet verified` : (s.texts ? `${plural(s.texts, "published document", "published documents")} read, ${fmt(s.usable)} usable, none naming one place for most; listed for Wyatt` : "No published text; listed for Wyatt");
    return [esc(String(s.year)), esc(kindLabel(s.kind)), place, esc(how), cnt(s.n_resolutions, makeSpec({ y: s.year, k: s.kind }), `${s.year} ${kindLabel(s.kind)}`)];
  });
  const nShown = list.length;
  const part = (n, cls) => (n ? `<span class="hseg ${cls}" style="flex:${n}"></span>` : "");
  const bar = `<div class="pl-bar" role="img" aria-label="${esc(`Of ${cv.sessions} conventions: ${cv.recorded} confirmed, ${cv.likely} likely, ${cv.unknown} not known`)}">${part(cv.recorded, "s-total")}${part(cv.likely, "s-likely")}${part(cv.unknown, "s-open")}</div>`;
  return sec({
    id: "places", h2: "Where the Conventions Met", h3: "Places known for the conventions",
    sub: `Place known for ${fmt(cv.known)} of ${fmt(cv.sessions)} conventions: ${fmt(cv.recorded)} confirmed, ${fmt(cv.likely)} from the certification text of the published resolutions (likely, not yet verified); ${fmt(cv.unknown)} not known. ${plural(c.not_applicable, "Executive Board action group is", "Executive Board action groups are")} not ${c.not_applicable === 1 ? "a convention and has" : "conventions and have"} no place.`,
    summary: `Table of ${nShown} conventions with the place known for each, and how it is known.`,
    chartHtml: bar, skip: false,
    key: keyHtml([{ cls: "s-total", label: "Confirmed" }, { cls: "s-likely", label: "Likely: from the published text, not yet verified" }, { cls: "s-open", label: "Not known, listed for Wyatt" }]),
    table: table("t-places", "Where each convention met, and how the place is known", ["Year", "Convention", "Place", "How it is known", "Resolutions"], rowsHtml, { left: true, tall: true }), tableOpen: true, csv: "t-places",
    caveat: "A likely place is the town most published certifications of that convention name. It may be where a certification was signed rather than where the convention met, which is why it is marked likely until ATNI confirms it.",
  });
}

/* ---------------------------------------------------------------------------------------------------------- */
export function view_years(S) {
  const f = S.f;
  const missing = missingConventions();
  const yrs = sec({
    id: "years", h2: "Resolutions Each Year", h3: "Resolutions recorded each year",
    sub: `One bar for each year, ${esc(span(f))}, by convention.`,
    summary: `Stacked bar chart of resolutions recorded each year, ${span(f)}, split by convention, with the highest number of each year marked. A table with the same numbers follows.`,
    chart: "kind", table: yearTable(S, "kind"), csv: "t-kind", pre: `<div class="chart-tools">${smoothSwitch(S, "years")}</div>`, cov: [covSentence(S, "convention")],
    caveat: `Counted from The Resolution Library. A resolution is counted once, in the year of its number. ${D.siteFirstYear ? `Before ${D.siteFirstYear} this site holds no text; the Library lists titles. ` : ""}Missing from the Library: ${esc(join(missing))}. The count is of resolutions listed with a number; adoption is recorded on only part of them, so the chart never says passed.`,
  });
  const cv = conventionsBlock(S);
  const conv = sec({
    id: "conventions", h2: "Conventions Compared", h3: "Resolutions at each convention",
    sub: `Winter, Mid-Year, Annual, Executive Board and Special, ${esc(span(f))}. A hatched cell is a convention missing from the Library, not a zero. A count marked likely is a likely reading.`,
    summary: "Grid of resolutions at each convention: one row for each year, one column for each kind of convention. The same numbers are in the grid itself.",
    chartHtml: cv.grid, skip: false, key: basisKey(["likely", "nr"]),
    cov: [cv.so ? esc(cv.so) : "", `Median per scheduled session over the whole record: ${esc(cv.allMedian)}, across ${fmt(cv.nSched)} scheduled sessions.`].filter(Boolean),
    table: cv.kTable + `<h4 class="tbl-h">Median per scheduled session, by span of years</h4>` + cv.bTable, csv: "t-kinds",
    extra: `<details class="tbl"><summary>Show committees by kind</summary>${cv.ckTable}</details>`,
    caveat: "Executive Board actions are adopted between conventions and are counted as their own kind. A special meeting is a fifth kind. Conventions missing from the Library are marked, not zero.",
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
  return yrs + conv + out + ncai + placesBlock(S);
}
