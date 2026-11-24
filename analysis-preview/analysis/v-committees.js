/* Committees: bars and grid with recorded and likely parts side by side, committee pages with direct and roll-up counts,
   committee names over time, origin, and Wyatt Ash-Milby's own grid behind a switch. */
import { D, makeSpec, esc, fmt, plural, ofWhole, kindLabel, yearsIn, span, cname, nr, join, runs, cnt, splitCell, splitSentence, table, sec, keyHtml, covSentence, src, basisKey, mark, uncertain, WORD_LIKELY, WORD_OPEN } from "./kit.js";
import * as DT from "./data.js";
import { splitText } from "./basis.js";
import { rowBarsHtml, heatmapHtml, sparkSvg } from "./charts.js";

export const REASON_WORDS = {
  education_rows: "His Education (Higher) and Education (K-12) rows repeat one Education count.",
  window_2025: "His 2025 column counts a fixed block of rows.",
  label_elsewhere: "His count takes the labels that begin with this word; the Library counts the committee each label names.",
  other: "Other, not explained.",
  blank: "His cell is blank.",
  unmapped: "His row is not matched to a committee in the Library, so it is not compared.",
  unreadable: "His cell is not a whole number.",
};
const REASON_LETTER = { education_rows: "A", window_2025: "B", label_elsewhere: "C", other: "D", unmapped: "E", unreadable: "F" };

/** The working name of a committee as markup: a likely name is marked, with its labels as written one step away. */
export const nameHtml = cm => (cm.name_basis === "likely" ? uncertain({ text: cm.name, basis: "likely", asWritten: cm.labels.map(l => l.label).join("”, “"), none: "no label in the record" }) : esc(cm.name));
const nameTag = cm => (cm.name_basis === "likely" ? ` ${WORD_LIKELY}` : "");

/* ---------------------------------------------------------------------------------------------------------- */
export function committeeTotals(S) {
  const f = S.f, mx = DT.commMatrix(f.k, S.ru), yrs = yearsIn(f);
  const rows = [];
  for (const cm of D.agg.committees) {
    let c = 0, l = 0;
    for (const y of yrs) { const [a, b] = mx.get(cm.key, y); c += a; l += b; }
    if (c + l > 0) rows.push({ key: cm.key, name: cm.name, cm, c, l });
  }
  rows.sort((a, b) => b.c + b.l - (a.c + a.l) || a.name.localeCompare(b.name));
  let blank = 0, other = 0;
  for (const y of yrs) { blank += mx.blank.get(y); other += mx.other.get(y); }
  return { rows, blank, other };
}
const rspec = (S, r, o) => makeSpec({ c: r.key, k: S.f.k, y0: S.f.y0, y1: S.f.y1, ru: S.ru && r.cm.children.length ? 1 : "", ...o });

export function committeeBars(S) {
  const f = S.f, t = committeeTotals(S);
  const max = Math.max(1, ...t.rows.map(r => r.c + r.l), t.blank + t.other);
  const rows = f.c ? t.rows.filter(r => r.key === f.c) : t.rows;
  let h = `<ol class="cbars" role="list" id="ov-comm-list" aria-labelledby="ov-comm-sum">`;
  for (const r of rows) {
    const on = f.c === r.key;
    h += `<li class="cb"><div class="cb-name"><button type="button" class="link-btn" data-setc="${esc(on ? "" : r.key)}" aria-pressed="${on}" aria-label="${on ? "Show all committees" : `Choose ${esc(r.name)} for every chart`}">${esc(r.name)}</button>${nameTag(r.cm)} <a class="cb-page" href="${esc(S.hrefView("committees", { cm: r.key }))}" aria-label="Committee page for ${esc(r.name)}">page</a></div>`
      + `<div class="cb-track">${r.c ? `<button type="button" class="hseg s-total" style="width:${(r.c / max * 100).toFixed(2)}%" data-list="${esc(rspec(S, r, { ly: "c" }))}" data-tip="${esc(r.name)}: ${fmt(r.c)} recorded" aria-label="${esc(r.name)}: ${fmt(r.c)} recorded"></button>` : ""}`
      + `${r.l ? `<button type="button" class="hseg s-likely" style="width:${(r.l / max * 100).toFixed(2)}%" data-list="${esc(rspec(S, r, { ly: "l" }))}" data-tip="${esc(r.name)}: ${fmt(r.l)} likely" aria-label="${esc(r.name)}: ${fmt(r.l)} likely"></button>` : ""}</div>`
      + `<div class="cb-n">${splitText(r.c, r.l)}</div></li>`;
  }
  if (!f.c) {
    const nn = t.blank + t.other;
    h += `<li class="cb cb-none"><div class="cb-name"><span>Names no committee</span></div><div class="cb-track"><button type="button" class="hseg s-none" style="width:${(nn / max * 100).toFixed(2)}%" data-list="${esc(makeSpec({ cn: "any", k: f.k, y0: f.y0, y1: f.y1 }))}" data-tip="${plural(nn, "resolution names", "resolutions name")} no committee" aria-label="${plural(nn, "resolution names", "resolutions name")} no committee"></button></div><div class="cb-n">${fmt(nn)}</div></li>`;
  }
  return h + `</ol>`;
}
export function committeeBarsTable(S) {
  const f = S.f, t = committeeTotals(S);
  return table("t-ov-comm", "Resolutions by committee, recorded and likely", ["Committee", "Recorded", "Likely"], [...t.rows.map(r => [esc(r.name) + nameTag(r.cm), r.c ? cnt(r.c, rspec(S, r, { ly: "c" }), `${r.name}, recorded`) : `<span class="zero">0</span>`, r.l ? cnt(r.l, rspec(S, r, { ly: "l" }), `${r.name}, likely`) : `<span class="zero">0</span>`]), ["Names no committee", cnt(t.blank + t.other, makeSpec({ cn: "any", k: f.k, y0: f.y0, y1: f.y1 }), "Names no committee"), ""]]);
}

/* ---------------------------------------------------------------------------------------------------------- */
const wyattMap = () => { const m = new Map(); for (const r of D.agg.wyatt.rows) if (r.key) for (const c of r.cells) m.set(r.key + "|" + c.year, c); return m; };

function heatRows(S, years) {
  const f = S.f, mx = DT.commMatrix(f.k, S.ru), t = committeeTotals(S);
  const wy = S.wy ? wyattMap() : null;
  const rows = (f.c ? t.rows.filter(r => r.key === f.c) : t.rows).map(r => ({
    key: r.key, name: r.name, nameHtml: nameTag(r.cm), href: S.hrefView("committees", { cm: r.key }),
    cells: years.map(y => {
      const [c, l] = mx.get(r.key, y);
      const wc = wy && !S.ru && wy.get(r.key + "|" + y);
      const diff = !!(wc && wc.state === "differs");
      return { c, l, diff, spec: rspec(S, r, { y, y0: "", y1: "", ly: l ? "b" : "c" }), label: `${r.name}, ${y}: ${fmt(c)} recorded${l ? `, ${fmt(l)} likely` : ""}${diff ? `. His grid reads ${fmt(wc.his)}. ${REASON_WORDS[wc.reason]}` : ""}` };
    }),
  }));
  if (!f.c) rows.push({ key: "none", name: "Names no committee", hatched: true, cells: years.map(y => { const n = mx.blank.get(y) + mx.other.get(y); return { c: n, l: 0, spec: makeSpec({ y, cn: "any", k: f.k }), label: `Names no committee, ${y}: ${fmt(n)} resolutions` }; }) });
  return rows;
}
function heatTable(S) {
  const f = S.f, yrs = yearsIn(f), rows = heatRows(S, yrs);
  const head = ["Committee", ...yrs.map(String)];
  return table("t-heat", "Resolutions by committee and year, recorded and likely", head, rows.map(r => [esc(r.name) + (r.nameHtml || ""), ...r.cells.map(c => (c.c || c.l ? (r.hatched ? cnt(c.c, c.spec, r.name) : splitCell(c.c, c.l, c.spec, c.spec, r.name)) : `<span class="zero">0</span>`))]), { numFrom: 1 });
}
export function drawHeat(el, S) {
  const id = el.dataset.sum.replace(/-sum$/, ""), f = S.f, yrs = yearsIn(f);
  if (!S.wide) {
    const rowsAll = committeeTotals(S).rows;
    const pickKey = S.q.get("hc") && D.cm[S.q.get("hc")] ? S.q.get("hc") : (rowsAll[0] || {}).key;
    const mx = DT.commMatrix(f.k, S.ru);
    const pr = rowsAll.find(r => r.key === pickKey);
    const rows = yrs.map(y => { const [c, l] = mx.get(pickKey, y); const sp = o => rspec(S, pr, { y, y0: "", y1: "", ...o }); return { year: y, total: c + l, segs: [{ key: "total", n: c, label: `${y}: ${fmt(c)} recorded`, spec: sp({ ly: "c" }) }, { key: "likely", n: l, label: `${y}: ${fmt(l)} likely`, spec: sp({ ly: "l" }) }], yearSpec: sp({ ly: "b" }), text: l ? `${fmt(c)} + ${fmt(l)} likely` : fmt(c) }; });
    const max = Math.max(1, ...rows.map(r => r.total));
    el.innerHTML = `<div class="cov-pick"><label for="${id}-pick">Committee</label><select id="${id}-pick" data-pick="hc">${rowsAll.map(r => `<option value="${esc(r.key)}"${r.key === pickKey ? " selected" : ""}>${esc(r.name)}${r.cm.name_basis === "likely" ? " (name likely)" : ""}</option>`).join("")}</select></div>` + (pickKey ? rowBarsHtml({ id, rows, max }) : `<p class="empty-line">No committee in this selection.</p>`);
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
}

/* ---------------------------------------------------------------------------------------------------------- */
/* committee names over time                                                                                    */
function namesBlock(S, onlyKey) {
  const f = S.f, keys = (onlyKey ? [onlyKey] : f.c ? [f.c] : D.agg.committees.map(c => c.key));
  const items = [];
  for (const key of keys) {
    const cm = D.cm[key];
    const lines = cm.labels.map(l => ({ ...l, nIn: Object.entries(l.years).reduce((s, [y, n]) => s + (+y >= f.y0 && +y <= f.y1 ? n : 0), 0) })).filter(l => l.nIn > 0)
      .sort((a, b) => (a.basis === b.basis ? a.first_year - b.first_year || a.label.localeCompare(b.label) : a.basis === "likely" ? 1 : -1));
    if (!lines.length) continue;
    items.push(`<div class="nm-group"><h4 id="nm-${esc(key)}"><a href="${esc(S.hrefView("committees", { cm: key }))}">${esc(cm.name)}</a>${nameTag(cm)}</h4><ul class="labels">${lines.map(l => {
      const lk = l.basis === "likely";
      const yrs = D.years.map(y => (l.years[y] ? "u" : y >= l.first_year && y <= l.last_year ? "b" : "e"));
      const spec = makeSpec({ c: key, ly: "b", lab: l.label, y0: f.y0, y1: f.y1 });
      return `<li class="lab"><div class="lab-head"><span class="lab-text">${esc(l.label)}</span>${lk ? ` ${WORD_LIKELY}` : ""}<span class="lab-yrs">${l.first_year === l.last_year ? l.first_year : `${l.first_year} to ${l.last_year}`}</span>${cnt(l.nIn, spec, `Label ${l.label} as written`)}</div><div class="lab-strip${lk ? " lk" : ""}" role="img" aria-label="${esc(l.label)}${lk ? ", likely," : ""} is used in ${esc(join(runs(Object.keys(l.years).map(Number))))}">${D.years.map((y, i) => `<i class="${yrs[i]}${y < f.y0 || y > f.y1 ? " out" : ""}" data-tip="${y}${l.years[y] ? `: ${fmt(l.years[y])}` : ""}"></i>`).join("")}</div></li>`;
    }).join("")}</ul></div>`);
  }
  return sec({
    id: "names", h2: "Committee Names Over Time", h3: "Committee names as the record writes them",
    sub: "Each strip is one label as the record writes it, from its first year to its last. A filled square is a year the label is used. A label marked likely is assigned to the committee as the most likely reading.",
    summary: "Timelines of committee labels, one strip for each label as written.",
    chartHtml: `<div class="nm">${items.join("") || `<p class="empty-line">No committee label in this selection.</p>`}</div>`,
    key: keyHtml([{ cls: "tl-u", label: "A year the label is used" }, { cls: "tl-b", label: "Between its first and last year" }]) + basisKey(["likely"]), skip: false,
    caveat: "Labels are shown exactly as the workbook writes them, including spelling. Which committee a label belongs to is a reading; a label marked likely is the most likely one, and it stays here as written.",
  });
}

/* ---------------------------------------------------------------------------------------------------------- */
function committeePage(S, key) {
  const f = S.f, cm = D.cm[key];
  const km = DT.kindMatrix(key), yrs = yearsIn(f);
  const rows = yrs.map(y => { const m = km[D.yi.get(y)]; return { year: y, total: m.sT + m.lT, segs: [{ key: "total", n: m.sT, label: `${y}: ${fmt(m.sT)} recorded`, spec: makeSpec({ y, c: key, ly: "c" }) }, { key: "likely", n: m.lT, label: `${y}: ${fmt(m.lT)} likely`, spec: makeSpec({ y, c: key, ly: "l" }) }], yearSpec: makeSpec({ y, c: key, ly: "b" }) }; });
  const max = Math.max(1, ...rows.map(r => r.total));
  const cr = D.rows.filter(r => DT.layerOf(r, key) && r.y >= f.y0 && r.y <= f.y1);
  const nc = { rec: 0, yes: 0 }; for (const r of cr) if (r.nc) { nc.rec++; if (r.nc === "yes") nc.yes++; }
  const withPb = cr.filter(r => r.pb).length;
  let people = "";
  if (S.names) {
    const pm = new Map(); for (const r of cr) for (const p of r._pk) pm.set(p, (pm.get(p) || 0) + 1);
    const list = [...pm.entries()].map(([k, n]) => ({ k, n, name: D.persons.get(k).name })).sort((a, b) => a.name.localeCompare(b.name));
    people = `<h3 class="list-h">People Named on Its Resolutions</h3><p class="sub">${fmt(withPb)} of ${fmt(cr.length)} ${esc(cm.name)} resolutions name a preparer. Names are shown as written in ATNI's record, in name order.</p><ul class="plist">${list.map(p => `<li><a href="${esc(S.hrefView("people", { p: p.k }))}">${esc(p.name)}</a> <span class="pl-n">${cnt(p.n, makeSpec({ p: p.k, c: key, ly: "b" }), p.name)}</span></li>`).join("")}</ul>`;
  } else people = `<p class="sub">Names are not yet published, so people are not listed here. ${fmt(withPb)} of ${fmt(cr.length)} ${esc(cm.name)} resolutions name a preparer.</p>`;
  const parent = cm.parent ? D.cm[cm.parent] : null;
  const kindSentence = `${DT.KIND_OF_COMMITTEE[cm.kind] ?? esc(cm.kind)}${cm.kind_basis === "likely" ? ` ${WORD_LIKELY}` : cm.kind_basis === "owner" ? ", as ATNI decided" : ""}${parent ? `, under <a href="${esc(S.hrefView("committees", { cm: parent.key }))}">${esc(parent.name)}</a>` : ""}.`;
  const direct = `${esc(cm.name)} itself: ${splitSentence(cm.recorded, cm.likely, makeSpec({ c: key, ly: "c" }), makeSpec({ c: key, ly: "l" }), cm.name)}${cm.first_year ? `, ${cm.first_year} to ${cm.last_year}` : ""}.`;
  const kids = cm.children.map(k => D.cm[k]?.name).filter(Boolean);
  const ro = cm.rollup ? `With ${esc(join(kids))}, ${plural(cm.rollup.total, "distinct resolution", "distinct resolutions")}: ${splitSentence(cm.rollup.recorded, cm.rollup.likely, makeSpec({ c: key, ru: 1, ly: "c" }), makeSpec({ c: key, ru: 1, ly: "l" }), `${cm.name} with its sub-committees`)}. A resolution that names two of them is counted once.` : "";
  const body = `<p class="sub">${kindSentence}${cm.source_names ? ` In Wyatt Ash-Milby's workbook: ${esc(cm.source_names)}.` : ""}</p>
    <p>Working name: ${nameHtml(cm)}${cm.name_basis === "owner" ? ", decided by ATNI" : ""}. ${direct}</p>
    ${ro ? `<p>${ro}</p>` : ""}
    ${nc.rec ? `<p>TO NCAI (National Congress of American Indians) is recorded for ${ofWhole(nc.rec, cr.length)} resolutions: ${ofWhole(nc.yes, nc.rec, true)} say Yes.</p>` : `<p>TO NCAI is not recorded for any of them in this selection.</p>`}
    <p class="sr-only" id="cp-sum">Bars of ${esc(cm.name)} resolutions by year, recorded and likely.</p>
    ${rowBarsHtml({ id: "cp", rows, max })}${keyHtml([{ cls: "s-total", label: "Recorded" }]) }${basisKey(["likely"])}
    <p class="cov-sentence">A year with no resolution under a committee means no resolution in the Library, never that the committee did not exist.</p>
    ${people}`;
  return `<section class="vs" id="committee-page" aria-labelledby="committee-page-h"><h2 id="committee-page-h">${nameHtml(cm)}</h2>${body}<p><a class="btn small quiet" href="${esc(S.href({ cm: undefined }))}">Close this committee page</a></p>${src()}</section>`;
}

/* ---------------------------------------------------------------------------------------------------------- */
/* origin                                                                                                       */
function originBlock(S) {
  const f = S.f, O = D.agg.origin, vals = O.values;
  const rs = D.rows.filter(r => r.y >= f.y0 && r.y <= f.y1 && DT.selects(r, f.k, f.c));
  const cnts = Object.fromEntries(vals.map(v => [v, { r: 0, l: 0 }]));
  let open = 0, none = 0;
  for (const r of rs) { if (r.og) cnts[r.og][r.ogb === "l" ? "l" : "r"]++; else if (r.ogb === "o") open++; else none++; }
  const sp = (o) => makeSpec({ k: f.k, c: f.c, ly: f.c ? "b" : "", y0: f.y0, y1: f.y1, ...o });
  const max = Math.max(1, ...vals.map(v => cnts[v].r + cnts[v].l), open, none);
  let h = `<ol class="cbars" role="list" aria-labelledby="origin-sum">`;
  for (const v of vals) {
    const o = cnts[v], lab = DT.ORIGIN_LABEL[v] ?? v;
    h += `<li class="cb"><div class="cb-name"><span>${esc(lab)}</span></div><div class="cb-track">${o.r ? `<button type="button" class="hseg s-total" style="width:${(o.r / max * 100).toFixed(2)}%" data-list="${esc(sp({ og: v, ogb: "r" }))}" data-tip="${esc(lab)}: ${fmt(o.r)} recorded" aria-label="${esc(lab)}: ${fmt(o.r)} recorded"></button>` : ""}${o.l ? `<button type="button" class="hseg s-likely" style="width:${(o.l / max * 100).toFixed(2)}%" data-list="${esc(sp({ og: v, ogb: "l" }))}" data-tip="${esc(lab)}: ${fmt(o.l)} likely" aria-label="${esc(lab)}: ${fmt(o.l)} likely"></button>` : ""}</div><div class="cb-n">${splitText(o.r, o.l)}</div></li>`;
  }
  h += `<li class="cb"><div class="cb-name"><span>Open, kept as written</span></div><div class="cb-track">${open ? `<button type="button" class="hseg s-open" style="width:${(open / max * 100).toFixed(2)}%" data-list="${esc(sp({ ogb: "o" }))}" data-tip="${fmt(open)} open" aria-label="${fmt(open)} open: origin not applied, kept as written"></button>` : ""}</div><div class="cb-n">${fmt(open)} open</div></li>`;
  h += `<li class="cb cb-none"><div class="cb-name"><span>Origin not recorded</span></div><div class="cb-track"><button type="button" class="hseg s-none" style="width:${(none / max * 100).toFixed(2)}%" data-list="${esc(sp({ og: "none" }))}" data-tip="${fmt(none)} with no origin" aria-label="${fmt(none)} resolutions with no origin recorded"></button></div><div class="cb-n">${fmt(none)}</div></li></ol>`;
  const yrs = yearsIn(f);
  const by = new Map(yrs.map(y => [y, Object.fromEntries(vals.map(v => [v, { r: 0, l: 0 }]).concat([["open", 0]]))]));
  for (const r of rs) { const o = by.get(r.y); if (r.og) o[r.og][r.ogb === "l" ? "l" : "r"]++; else if (r.ogb === "o") o.open++; }
  const tRows = yrs.filter(y => vals.some(v => by.get(y)[v].r + by.get(y)[v].l) || by.get(y).open).map(y => { const o = by.get(y); return [String(y), ...vals.map(v => splitCell(o[v].r, o[v].l, sp({ y: y, y0: "", y1: "", og: v, ogb: "r" }), sp({ y: y, y0: "", y1: "", og: v, ogb: "l" }), `${y}, ${DT.ORIGIN_LABEL[v] ?? v}`)), o.open ? cnt(o.open, sp({ y, y0: "", y1: "", ogb: "o" }), `${y}, origin open`) : `<span class="zero">0</span>`]; });
  const tbl = table("t-origin", "Resolutions by origin and year, recorded and likely", ["Year", ...vals.map(v => DT.ORIGIN_LABEL[v] ?? v), "Open, kept as written"], tRows);
  return sec({
    id: "origin", h2: "Where a Resolution Came From", h3: "Origin, as a word in the Committee or Prepared By cell",
    sub: "Origin is a field of its own, never a committee and never a person. It is applied only where one of those two cells says it.",
    summary: `Bars of resolutions by origin, ${span(f)}: ${vals.map(v => `${DT.ORIGIN_LABEL[v] ?? v} ${cnts[v].r} recorded and ${cnts[v].l} likely`).join("; ")}; ${open} open; ${none} not recorded.`,
    chartHtml: `<p class="sr-only" id="origin-sum"></p>` + h, skip: false,
    key: basisKey(["likely", "open", "nr"], true),
    cov: [`Origin is recorded for ${ofWhole(vals.reduce((n, v) => n + cnts[v].r + cnts[v].l, 0), rs.length)} resolutions.`],
    table: tbl, csv: "t-origin",
    caveat: "Origin is read only from a word written in the Committee or Prepared By cell. The Executive Board signs every ratified resolution; signing is not origin. Origin never removes a committee link.",
  });
}

/* ---------------------------------------------------------------------------------------------------------- */
/* Wyatt Ash-Milby's grid, behind a switch                                                                       */
function wyattBlock(S) {
  const W = D.agg.wyatt, sum = W.summary;
  const picked = S.q.get("wc") && W.rows.some(r => r.label === S.q.get("wc")) ? S.q.get("wc") : W.rows[0].label;
  const hisOf = c => (c.his == null ? "not a number" : fmt(c.his));
  const cellHtml = c => {
    if (!c) return "";
    if (c.state === "blank") return `<span class="zero">blank</span><span class="sr-only"> (his cell is blank)</span>`;
    if (c.state === "equal") return fmt(c.his);
    const rw = esc(REASON_WORDS[c.reason] ?? REASON_WORDS.other);
    if (c.state === "unmapped" || c.state === "unreadable") return `<span class="wd wd-um" data-tip="${esc(c.state === "unmapped" ? `His ${hisOf(c)}. ${REASON_WORDS.unmapped}` : REASON_WORDS.unreadable)}"><span class="sr-only">his count </span><b>${c.state === "unreadable" ? "?" : hisOf(c)}</b><sup class="wr">${REASON_LETTER[c.state]}</sup><span class="sr-only">, reason: ${rw}</span></span>`;
    return `<span class="wd" data-tip="His ${fmt(c.his)}; the Library ${fmt(c.ours)}. ${rw}"><span class="sr-only">his count </span><b>${fmt(c.his)}</b><span class="sr-only">, the Library counts </span><i>${fmt(c.ours)}</i><sup class="wr">${REASON_LETTER[c.reason] || ""}</sup><span class="sr-only">, reason: ${rw}</span></span>`;
  };
  const odd = c => c.state === "differs" || c.state === "unmapped" || c.state === "unreadable";
  const libOf = c => (c.ours == null ? "not matched to a committee" : `${fmt(c.ours)}${c.ours_likely ? ` (${fmt(c.ours_likely)} likely)` : ""}`);
  const wide = `<div class="tbl-wrap wy-wrap" tabindex="0" role="region" aria-label="Wyatt Ash-Milby's committee counts"><table class="data wy" id="t-wyatt"><caption class="sr-only">Wyatt Ash-Milby's committee counts, ${W.years[0]} to ${W.years[W.years.length - 1]}, with the Library's count beside each differing cell</caption><thead><tr><th scope="col">Committee</th>${W.years.map(y => `<th scope="col" class="num">${String(y).slice(2)}<span class="sr-only"> (${y})</span></th>`).join("")}<th scope="col">Sparkline</th></tr></thead><tbody>${W.rows.map(r => `<tr><th scope="row">${esc(r.label)}</th>${r.cells.map(c => `<td class="num${odd(c) ? " diff" : ""}${c.state === "unmapped" || c.state === "unreadable" ? " um" : ""}">${cellHtml(c)}</td>`).join("")}<td class="spark-cell">${sparkSvg(r.cells.map(c => c.his))}</td></tr>`).join("")}</tbody></table></div>`;
  const row = W.rows.find(r => r.label === picked);
  const narrow = `<div class="cov-pick"><label for="wc-pick">Committee</label><select id="wc-pick" data-pick="wc">${W.rows.map(r => `<option${r.label === picked ? " selected" : ""}>${esc(r.label)}</option>`).join("")}</select></div>
    <table class="data wy-one"><caption class="sr-only">${esc(picked)}, Wyatt Ash-Milby's counts by year, with the Library's count and the reason where they differ</caption><thead><tr><th scope="col">Year</th><th scope="col" class="num">His count</th><th scope="col" class="num">The Library</th><th scope="col">Reason</th></tr></thead><tbody>${row.cells.map(c => `<tr><th scope="row">${c.year}</th><td class="num${odd(c) ? " diff" : ""}">${c.state === "blank" ? `<span class="zero">blank</span>` : hisOf(c)}</td><td class="num">${c.state === "blank" && c.ours == null ? "" : c.ours == null ? "not matched" : fmt(c.ours)}</td><td>${c.state === "blank" ? esc(REASON_WORDS.blank) : odd(c) ? esc(REASON_WORDS[c.reason] ?? REASON_WORDS.other) : ""}</td></tr>`).join("")}</tbody></table>`;
  const diffRows = W.rows.flatMap(r => r.cells.filter(odd).map(c => [esc(r.label), String(c.year), hisOf(c), libOf(c), esc(REASON_WORDS[c.reason] ?? REASON_WORDS.other)]));
  const reasons = Object.keys(REASON_LETTER).filter(k => (sum.by_reason[k] ?? 0) > 0);
  return sec({
    id: "wyatt", h2: "Wyatt Ash-Milby's Counts", h3: "Wyatt Ash-Milby's committee counts, beside the Library's",
    sub: `His chart is titled “${esc(W.title)}”. ${fmt(W.rows.length)} committee rows, ${W.years[0]} to ${W.years[W.years.length - 1]}, as he built them. In a differing cell his number is shown first, then the Library's, then a letter for the reason. A cell he left blank says so.`,
    summary: "Table of Wyatt Ash-Milby's committee counts by year with a sparkline for each committee. Where his number differs from the Library's, the Library's number and the reason follow it.",
    chartHtml: `<div class="wy-only-wide">${wide}</div><div class="wy-only-narrow">${narrow}</div>`, skip: false,
    key: keyHtml([{ cls: "wd-key", label: "Marked cell: his number, the Library's number, reason" }]) + `<ul class="wy-reasons" aria-label="Reasons">${reasons.map(k => `<li><b>${REASON_LETTER[k]}</b> ${esc(REASON_WORDS[k])} <span class="sub-inline">${fmt(sum.by_reason[k])} ${sum.by_reason[k] === 1 ? "cell" : "cells"}</span></li>`).join("")}</ul>`,
    cov: [`${fmt(sum.cells)} cells: ${fmt(sum.equal)} equal the Library's count, ${fmt(sum.differs)} differ, ${fmt(sum.blank)} are blank in his grid, ${fmt(sum.unmapped)} are on a row not matched to a committee, and ${fmt(sum.unreadable)} are not a whole number. The Library's count is the resolutions linked to that committee, recorded and likely, in the year. A cell on a row not matched to a committee is never compared: it is neither agreement nor zero.`],
    table: table("t-wyatt-diff", "Cells where Wyatt Ash-Milby's count differs from the Library's, with the reason", ["Committee", "Year", "His count", "The Library", "Reason"], diffRows, { numFrom: 1 }), csv: "t-wyatt-diff",
    caveat: "Wyatt Ash-Milby built these counts in The Resolution Library. The Library counts again by the committee each resolution is linked to. Neither replaces the other. His grid is not extended past the years it holds.",
  });
}

/* ---------------------------------------------------------------------------------------------------------- */
export function view_committees(S) {
  const f = S.f;
  let out = "";
  const cmKey = S.q.get("cm");
  if (cmKey && D.cm[cmKey]) out += committeePage(S, cmKey);
  const t = committeeTotals(S);
  out += sec({
    id: "heat", h2: "Resolutions by Committee", h3: "Resolutions by committee and year",
    sub: `Each cell prints the recorded count; a chip hatched in the second colour prints the likely count beside it. A resolution that names two committees is counted under each, so no total across committees is printed. ${esc(span(f))}. Rows are sorted by number of resolutions. Arrow keys move between cells; Enter opens the list behind a number.`,
    summary: `Grid of resolutions by committee and year, ${span(f)}, with the recorded count in each cell and the likely count beside it. A table with the same numbers follows.`,
    chart: "heat", skip: true,
    key: keyHtml([{ cls: "step-1", label: "1" }, { cls: "step-2", label: "2 to 3" }, { cls: "step-3", label: "4 to 6" }, { cls: "step-4", label: "7 to 10" }, { cls: "step-5", label: "11 to 15" }, { cls: "step-6", label: "16 or more" }, { cls: "s-none", label: "Names no committee" }]) + basisKey(["likely"]),
    cov: [`${fmt(t.blank + t.other)} resolutions name no committee: ${fmt(t.blank)} have a blank cell and ${fmt(t.other)} write a name that is not a committee, such as Off the Floor or Executive Board.`, covSentence(S, "committee"), "A year with no resolution under a committee means no resolution in the Library, never that the committee did not exist."],
    table: heatTable(S), csv: "t-heat",
    actions: `<label class="switch"><input type="checkbox" data-switch="ru"${S.ru ? " checked" : ""}> Count a parent with its sub-committees</label><label class="switch"><input type="checkbox" data-switch="wy"${S.wy ? " checked" : ""}> Show Wyatt Ash-Milby's counts</label>`,
    caveat: `A parent's count with its sub-committees counts each resolution once, however many of them it names. A name shown with the word likely is a working name chosen by ATNI's rule where the record is not clear; its labels as written are on the committee's page.${S.wy ? " Cells where his number differs carry a corner mark." : ""}`,
  });
  out += originBlock(S);
  out += namesBlock(S, cmKey);
  if (S.wy) out += wyattBlock(S);
  return out;
}
