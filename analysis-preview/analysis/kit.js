/* Shared pieces of the views: formatting helpers, the section frame, the table frame, count buttons and the row of a
   list. Every value from the data passes through esc(); the visual language of likely and open lives in basis.js. */
import { esc, fmt, plural, ofWhole, covState, unrecordedRuns } from "./charts.js";
import * as DT from "./data.js";
import { uncertain, mark, basisKey, WORD_LIKELY, WORD_OPEN } from "./basis.js";

export { esc, fmt, plural, ofWhole, covState, unrecordedRuns, basisKey, uncertain, mark, WORD_LIKELY, WORD_OPEN };
export const D = DT.D, KINDS = DT.KINDS, KIND_LABEL = DT.KIND_LABEL, FIELDS = DT.FIELDS, makeSpec = DT.makeSpec;

export const kindLabel = k => KIND_LABEL[k] ?? "No convention recorded";
export const yearsIn = f => D.years.filter(y => y >= f.y0 && y <= f.y1);
export const span = f => (f.y0 === f.y1 ? String(f.y0) : `${f.y0} to ${f.y1}`);
export const cname = key => D.cm[key]?.name ?? key;
export const nr = `<span class="nr">not recorded</span>`;
export const median = a => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
export const num1 = n => (Number.isInteger(n) ? fmt(n) : n.toFixed(1));
export const slug = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-");
export const join = a => (a.length <= 1 ? a.join("") : a.length === 2 ? a.join(" and ") : `${a.slice(0, -1).join(", ")}, and ${a[a.length - 1]}`);

/** "2014 to 2025, 2007" style runs from a list of years */
export function runs(list) {
  const a = [...list].sort((x, y) => x - y), out = [];
  for (let i = 0; i < a.length;) { let j = i; while (j + 1 < a.length && a[j + 1] === a[j] + 1) j++; out.push(i === j ? String(a[i]) : j === i + 1 ? `${a[i]} and ${a[j]}` : `${a[i]} to ${a[j]}`); i = j + 1; }
  return out;
}
/** Scheduled conventions with no resolution in the Library (a missing convention, never a zero). */
export function missingConventions() {
  const km = DT.kindMatrix(""), out = [];
  for (const y of D.years) if (y > D.yMin) for (const k of ["winter", "midyear", "annual"]) { const m = km[D.yi.get(y)]; if (m.s[k] + m.l[k] === 0) out.push(`${y} ${kindLabel(k)}`); }
  return out;
}

/* ---------------------------------------------------------------------------------------------------------- */
/* shared pieces                                                                                               */
export const src = () => `<p class="source">Source: <a href="#credit" data-goto="credit">The Resolution Library</a>, an ATNI spreadsheet of ${fmt(D.total)} numbered resolutions, ${D.yMin} to ${D.yMax}, built by Wyatt Ash-Milby at ATNI.${D.builtAt ? ` Counted ${esc(D.builtAt)}.` : ""}</p>`;

export const cnt = (n, spec, label) => (n > 0 ? `<button type="button" class="count" data-list="${esc(spec)}" aria-label="${esc(label)}: ${fmt(n)} resolutions. Open the list.">${fmt(n)}</button>` : `<span class="zero">0</span>`);

/** A recorded count and a likely count side by side, each opening its own list: "120 + 14 likely". Never one total. */
export function splitCell(s, l, specS, specL, label) {
  if (!s && !l) return `<span class="zero">0</span>`;
  const a = s > 0 ? cnt(s, specS, `${label}, recorded`) : "";
  const b = l > 0 ? `<span class="lkn">${s > 0 ? "+ " : ""}${cnt(l, specL, `${label}, likely`)} ${WORD_LIKELY}</span>` : "";
  return `${a}${a && b ? " " : ""}${b}`;
}

/** "120 recorded, 14 likely" as a sentence part: each number opens its own list. */
export function splitSentence(s, l, specS, specL, label) {
  const parts = [];
  if (s || !l) parts.push(`${cnt(s, specS, `${label}, recorded`)} recorded`);
  if (l) parts.push(`${cnt(l, specL, `${label}, likely`)} ${WORD_LIKELY}`);
  return parts.join(", ");
}

export function table(id, caption, head, rows, o = {}) {
  const numFrom = o.numFrom ?? 1;
  return `<div class="tbl-wrap${o.tall ? " tall" : ""}" tabindex="0" role="region" aria-label="${esc(caption)}"><table class="data" id="${esc(id)}"><caption class="sr-only">${esc(caption)}</caption><thead><tr>${head.map((h, i) => `<th scope="col"${i >= numFrom && !o.left ? ' class="num"' : ""}>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map((c, i) => (i === 0 ? `<th scope="row">${c}</th>` : `<td${i >= numFrom && !o.left ? ' class="num"' : ""}>${c}</td>`)).join("")}</tr>`).join("")}</tbody></table></div>`;
}

export function sec(o) {
  const L = o.level || 3;
  const nm = o.h3 || o.h2 || "";
  const H = (lvl, id, t) => `<h${lvl} id="${id}">${t}</h${lvl}>`;
  return `<section class="vs" id="${o.id}" aria-labelledby="${o.id}-h">
    ${o.h2 ? H(2, o.id + "-h", o.h2) : ""}
    ${o.h3 ? H(o.h2 ? 3 : L, o.h2 ? o.id + "-h3" : o.id + "-h", o.h3) : ""}
    ${o.sub ? `<p class="sub">${o.sub}</p>` : ""}
    ${o.summary ? `<p class="sr-only" id="${o.id}-sum">${esc(o.summary)}</p>` : ""}
    ${o.pre || ""}
    ${o.chart ? `${o.skip === false ? "" : `<a class="skip-link" href="#${o.id}-after">Skip this chart</a>`}<div class="chart" data-chart="${o.chart}" data-sum="${o.id}-sum" id="${o.id}-chart"></div>` : ""}
    ${o.chartHtml || ""}
    ${o.key || ""}
    ${(o.cov || []).map(p => `<p class="cov-sentence">${p}</p>`).join("")}
    <div class="acts" id="${o.id}-after">
      ${o.table ? `<details class="tbl"${o.tableOpen ? " open" : ""}><summary>Show table<span class="sr-only">: ${nm}</span></summary>${o.table}</details>` : ""}
      ${o.csv ? `<button type="button" class="btn small quiet" data-csv="${esc(o.csv)}" data-csv-name="${esc(o.id)}">Download this table (CSV)<span class="sr-only">: ${nm}</span></button>` : ""}
      ${o.actions || ""}
    </div>
    ${o.extra || ""}
    ${o.caveat ? `<p class="caveat">${o.caveat}</p>` : ""}
    ${o.nosrc ? "" : src()}
  </section>`;
}

export const keyHtml = items => `<ul class="key" aria-label="Key">${items.map(i => `<li><span class="sw ${i.cls}" aria-hidden="true"></span>${esc(i.label)}</li>`).join("")}</ul>`;
export const COV_KEY = [{ cls: "cov-full", label: "Recorded on every resolution" }, { cls: "cov-part", label: "Recorded on some" }, { cls: "cov-none", label: "Not recorded" }];

export const NOUN = { title: "Title", titleShown: "A title is shown", committee: "Committee", committeeApplied: "A committee", committeeLikely: "A likely committee only", preparer: "Prepared By", convention: "Convention", origin: "Origin", outcome: "Outcome", ncai: "TO NCAI", permalink: "A permalink", site: "Text on this site" };
export function covSentence(S, field) {
  const m = DT.covMatrix(field, S.f.k, S.f.c), f = S.f;
  const n = DT.sumBy(m, f, r => r.n), t = DT.sumBy(m, f, r => r.total);
  return `${esc(NOUN[field] || FIELDS[field].name)} is recorded for ${ofWhole(n, t)} resolutions.`;
}
export function covCells(S, field, yrs) {
  const m = DT.covMatrix(field, S.f.k, S.f.c);
  return yrs.map(y => {
    const c = m[D.yi.get(y)];
    const st = covState(c.n, c.total);
    const text = c.total === 0 ? `${y}: no resolutions in this selection` : c.n === 0 ? `${y}: ${FIELDS[field].rec} for none of ${fmt(c.total)} resolutions` : `${y}: ${FIELDS[field].rec} for ${ofWhole(c.n, c.total)} resolutions`;
    return { state: st, share: c.total ? c.n / c.total : 0, text };
  });
}

/* ---------------------------------------------------------------------------------------------------------- */
/* the list behind a number                                                                                     */
export function lrow(r, S) {
  const title = DT.titleText(r);
  const titleHtml = r.tb === "likely" ? uncertain({ text: title ?? "", basis: "likely", asWritten: r.tw, none: "No title in the record" })
    : r.tb === "open" ? uncertain({ text: "", basis: "open", asWritten: r.tw ?? r.t, none: "No title in the record" })
    : title ? esc(title) : `<span class="nr">No title in the record</span>`;
  const items = [
    ["Committee", r.cl ? esc(r.cl) : nr],
    ["Convention", r.cv ? esc(r.cv) : nr],
  ];
  if (r.cs.length) items.push(["Counted under", r.cs.map(([k, b]) => (b === "l" ? mark(cname(k), "likely") : esc(cname(k)))).join(", ")]);
  if (r.kb === "likely" && r.k) items.push(["Counted as", mark(kindLabel(r.k), "likely")]);
  else if (r.kb === "open") items.push(["Convention", `<span class="open-text">not applied</span> ${WORD_OPEN}`]);
  if (S.names && r.pb) {
    const lk = r.pp.filter(p => p[1] === "l"), op = r.po.length;
    items.push(["Prepared By", esc(r.pb) + (lk.length ? ` <span class="sub-inline">counted under ${lk.map(p => mark(D.persons.get(p[0])?.name ?? p[0], "likely")).join(", ")}</span>` : "") + (op ? ` ${WORD_OPEN}` : "")]);
  }
  if (r.og) items.push(["Origin", mark(DT.ORIGIN_LABEL[r.og] ?? r.og, r.ogb)]);
  else if (r.ogb === "o") items.push(["Origin", `<span class="open-text">not applied</span> ${WORD_OPEN}`]);
  if (r.ob === "likely" && r.o) items.push(["Outcome", mark(DT.OUTCOME_LABEL[r.o], "likely")]);
  else if (r.ob === "open") items.push(["Outcome", `<span class="open-text">not recorded</span> ${WORD_OPEN}`]);
  if (r.nb === "open") items.push(["TO NCAI", `<span class="open-text">not recorded</span> ${WORD_OPEN}`]);
  if (r.ib === "likely") items.push(["Included", `<mark class="likely">in the count</mark> ${WORD_LIKELY}`]);
  if (r.sb === "likely") items.push(["Link to the site text", `<mark class="likely">by number</mark> ${WORD_LIKELY}`]);
  const act = r.s
    ? `<a class="btn small" href="#/r/${r.s}" data-live="the resolution page for ${esc(r.n)}" aria-label="Open resolution ${esc(r.n)}">Open</a><button type="button" class="btn small collect" data-rkey="${esc(r.rk)}" aria-pressed="false" aria-label="Collect resolution ${esc(r.n)}">Collect</button>`
    : `${r.u ? `<a class="btn small quiet" href="${esc(r.u)}" rel="noopener" aria-label="Resolution ${esc(r.n)} on atnitribes.org">On atnitribes.org</a>` : ""}<span class="l-note">This site holds no text for this resolution; The Resolution Library lists it.</span>`;
  return `<li class="lrow"><span class="l-num">${esc(r.n)}</span><div class="l-body"><p class="l-title">${titleHtml}</p><dl class="l-meta">${items.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl></div><div class="l-act">${act}</div></li>`;
}
export const lrows = (rows, S, from = 0, n = 100) => rows.slice(from, from + n).map(r => lrow(r, S)).join("");
