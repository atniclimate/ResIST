/* Charts for the Analysis page mockup. Inline SVG and plain HTML drawn by this file; no library, no request.
   Every string that reaches markup passes through esc(). Colours come only from the --resist-* and --atni-* tokens,
   through the classes in analysis.css. */

export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const fmt = n => (n == null || Number.isNaN(n) ? "" : Number(n).toLocaleString("en-US"));
export const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : many}`;
/* "{n} of {whole}", with a percent only where the whole is 20 or more (AQ4). */
export const ofWhole = (n, whole, withPct = false) =>
  `${fmt(n)} of ${fmt(whole)}${withPct && whole >= 20 ? ` (${Math.round((100 * n) / whole)}%)` : ""}`;

/* Heatmap bins from the 756 committee-year cells: 1, 2 to 3, 4 to 6, 7 to 10, 11 to 15, 16 or more. */
export const step = n => (n <= 0 ? 0 : n === 1 ? 1 : n <= 3 ? 2 : n <= 6 ? 3 : n <= 10 ? 4 : n <= 15 ? 5 : 6);

export function niceMax(v) {
  if (v <= 10) return 10;
  const mag = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 1.2, 1.6, 2, 2.4, 3, 4, 5, 6, 8, 10]) if (m * mag >= v) return m * mag;
  return 10 * mag;
}

/* State of one year of a coverage strip: recorded on all, on some, on none. */
export const covState = (n, total) => (total === 0 ? "empty" : n === 0 ? "none" : n === total ? "full" : "part");

/* Runs of fully unrecorded years, written "2000 to 2004" (leading, trailing or inside). */
export function unrecordedRuns(cells, years) {
  const runs = [];
  let start = null;
  cells.forEach((c, i) => {
    if (c.state === "none") { if (start === null) start = i; }
    else if (start !== null) { runs.push([years[start], years[i - 1]]); start = null; }
  });
  if (start !== null) runs.push([years[start], years[years.length - 1]]);
  return runs.map(([a, b]) => (a === b ? String(a) : `${a} to ${b}`));
}

/* ---------------------------------------------------------------------------------------------------------- */
/* Vertical year bars (48rem and wider). One column per year on the shared year spine; each coverage strip is
   drawn on the same columns directly under the baseline, so a dip in a bar lines up with its "not recorded".     */
/* o: { width, height, rows:[{year, total, segs:[{key,n,label,spec}], outline:{key,n,label}|null, tick:{n,label}|null, yearSpec}],
        max, href(spec), strips:[{name, cells:[{state,share,text}]}], line:{values:[number|null], titles:[string|null]}|null, rise, id }
   A seg with key "likely" is drawn hatched in the second colour, a seg with key "open" as a dashed outline; both carry
   their word in the label. A tick is a short bar across the column at the highest number of the year. The line is the
   moving average: it breaks at every null and never crosses one.                                                      */
export function yearBarsSvg(o) {
  const W = Math.max(280, Math.round(o.width));
  const n = o.rows.length;
  const padL = 38, padR = 4, padT = 20, labelH = 20;
  const plotH = o.height;
  const slot = (W - padL - padR) / Math.max(1, n);
  const bw = Math.max(3, slot - 2);
  const base = padT + plotH;
  const top = niceMax(o.max);
  const y = v => (v / top) * plotH;
  const capH = 16, cellH = 12, stripBlock = capH + cellH + 4;
  const stripsTop = base + 4;
  const labelsTop = stripsTop + o.strips.length * stripBlock;
  const H = labelsTop + labelH;
  const labelEvery = slot >= 36 ? 1 : slot >= 18 ? 2 : 5;
  const showCounts = slot >= 28;
  let s = `<svg class="chart-svg${o.rise ? " rise" : ""}" xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="group" aria-labelledby="${esc(o.id)}-sum" focusable="false">`;
  // gridlines and y ticks (decorative)
  for (let t = 0; t <= 4; t++) {
    const v = (top / 4) * t, gy = base - y(v);
    s += `<line class="grid" x1="${padL}" x2="${W - padR}" y1="${gy.toFixed(1)}" y2="${gy.toFixed(1)}"/>`;
    s += `<text class="tick" aria-hidden="true" x="${padL - 6}" y="${(gy + 4).toFixed(1)}" text-anchor="end">${fmt(Math.round(v * 10) / 10)}</text>`;
  }
  s += `<line class="axis" x1="${padL}" x2="${W - padR}" y1="${base}" y2="${base}"/>`;
  o.rows.forEach((r, i) => {
    const x = padL + i * slot + 1;
    let cum = 0;
    s += `<g class="yr" style="--i:${i}">`;
    for (const sg of r.segs) {
      if (!sg.n) continue;
      const h = y(sg.n);
      const rectY = base - cum - h;
      const rectH = Math.max(1, h - (cum > 0 ? 2 : 0));
      s += `<a href="${esc(o.href(sg.spec))}" data-list="${esc(sg.spec)}" tabindex="-1" aria-hidden="true" data-tip="${esc(sg.label)}"><rect class="seg s-${esc(sg.key)}" x="${x.toFixed(1)}" y="${rectY.toFixed(1)}" width="${bw.toFixed(1)}" height="${rectH.toFixed(1)}"/></a>`;
      cum += h;
    }
    if (r.outline && r.outline.n) {
      const h = y(r.outline.n);
      s += `<g data-tip="${esc(r.outline.label)}"><rect class="seg s-siteonly" x="${(x + 0.75).toFixed(1)}" y="${(base - cum - h + 0.75).toFixed(1)}" width="${Math.max(1, bw - 1.5).toFixed(1)}" height="${Math.max(1, h - 1.5 - (cum > 0 ? 2 : 0)).toFixed(1)}"/></g>`;
      cum += h;
    }
    s += `</g>`;
    if (r.tick && r.tick.n > 0) s += `<g data-tip="${esc(r.tick.label)}"><line class="num-tick" x1="${(x - 1).toFixed(1)}" x2="${(x + bw + 1).toFixed(1)}" y1="${(base - y(r.tick.n)).toFixed(1)}" y2="${(base - y(r.tick.n)).toFixed(1)}"/></g>`;
    const above = r.tick && r.tick.n > 0 ? Math.max(cum, y(r.tick.n)) : cum;
    if (showCounts && r.total > 0) s += `<text class="cnt" aria-hidden="true" x="${(x + bw / 2).toFixed(1)}" y="${(base - above - 5).toFixed(1)}" text-anchor="middle">${fmt(r.total)}</text>`;
  });
  // the moving average: polyline segments that break at every null
  if (o.line) {
    const px = i => padL + i * slot + 1 + bw / 2, py = v => base - y(v);
    let d = "", pen = false, dots = "";
    o.line.values.forEach((v, i) => {
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${px(i).toFixed(1)} ${py(v).toFixed(1)}`;
      pen = true;
      dots += `<rect class="smooth-dot" x="${(px(i) - 2.5).toFixed(1)}" y="${(py(v) - 2.5).toFixed(1)}" width="5" height="5"><title>${esc(o.line.titles[i])}</title></rect>`;
    });
    if (d) s += `<g class="smooth" aria-hidden="true"><path class="smooth-line" d="${d}"/>${dots}</g>`;
  }
  // coverage strips
  o.strips.forEach((st, si) => {
    const ty = stripsTop + si * stripBlock;
    const runs = unrecordedRuns(st.cells, o.rows.map(r => r.year));
    s += `<text class="cap" aria-hidden="true" x="${padL}" y="${ty + 12}">${esc(st.name)}${runs.length ? `. Not recorded: ${esc(runs.join(", "))}.` : ""}</text>`;
    st.cells.forEach((c, i) => {
      if (c.state === "empty") return;
      const x = padL + i * slot + 1, cy = ty + capH;
      s += `<g data-tip="${esc(c.text)}">`;
      if (c.state === "full") s += `<rect class="cov-full" x="${x.toFixed(1)}" y="${cy}" width="${bw.toFixed(1)}" height="${cellH}"/>`;
      else if (c.state === "none") s += `<rect class="cov-none" x="${(x + 0.5).toFixed(1)}" y="${cy + 0.5}" width="${(bw - 1).toFixed(1)}" height="${cellH - 1}"/>`;
      else {
        const fh = Math.max(1, Math.round((cellH - 1) * c.share));
        s += `<rect class="cov-part" x="${(x + 0.5).toFixed(1)}" y="${cy + 0.5}" width="${(bw - 1).toFixed(1)}" height="${cellH - 1}"/><rect class="cov-fill" x="${(x + 0.5).toFixed(1)}" y="${(cy + cellH - 0.5 - fh).toFixed(1)}" width="${(bw - 1).toFixed(1)}" height="${fh}"/>`;
      }
      s += `</g>`;
    });
  });
  // year links: one per year (keyboard path), label drawn every labelEvery years
  o.rows.forEach((r, i) => {
    const x = padL + i * slot;
    s += `<a class="ylab" href="${esc(o.href(r.yearSpec))}" data-list="${esc(r.yearSpec)}" aria-label="${esc(String(r.year))}: ${fmt(r.total)} resolutions. Open the list.">`
      + `<rect class="hit" x="${x.toFixed(1)}" y="${labelsTop}" width="${slot.toFixed(1)}" height="${labelH}"/>`
      + (i % labelEvery === 0 ? `<text class="tick" x="${(x + slot / 2).toFixed(1)}" y="${labelsTop + 14}" text-anchor="middle">${r.year}</text>` : "")
      + `</a>`;
  });
  s += `</svg>`;
  return s;
}

/* ---------------------------------------------------------------------------------------------------------- */
/* Horizontal year rows (phones, and wherever a row carries "{n} of {total}" text). Years run down the screen.   */
/* o: { rows:[{year, total, segs:[{key,n,label,spec}], outline, yearSpec, text, cov:{state,share,text}|null}],
        max, covName, id }                                                                                     */
export function rowBarsHtml(o) {
  const max = Math.max(1, o.max);
  let h = `<ol class="rowbars" role="list" aria-labelledby="${esc(o.id)}-sum">`;
  for (const r of o.rows) {
    const only = r.segs.filter(x => x.n).length === 1;
    h += `<li class="rb"><button type="button" class="rb-year" data-list="${esc(r.yearSpec)}" aria-label="${esc(String(r.year))}: ${fmt(r.total)} resolutions. Open the list.">${r.year}</button>`;
    h += `<span class="rb-track" aria-hidden="false">`;
    for (const sg of r.segs) {
      if (!sg.n) continue;
      h += `<button type="button" class="hseg s-${esc(sg.key)}"${only && sg.spec === r.yearSpec ? ' tabindex="-1"' : ""} style="width:${((sg.n / max) * 100).toFixed(2)}%" data-list="${esc(sg.spec)}" data-tip="${esc(sg.label)}" aria-label="${esc(sg.label)}"></button>`;
    }
    if (r.outline && r.outline.n) h += `<span class="hseg s-siteonly" style="width:${((r.outline.n / max) * 100).toFixed(2)}%" data-tip="${esc(r.outline.label)}" role="img" aria-label="${esc(r.outline.label)}"></span>`;
    h += `</span>`;
    h += `<span class="rb-text">${r.text ?? fmt(r.total)}</span>`;
    if (o.covName !== undefined) {
      h += r.cov && r.cov.state !== "empty"
        ? `<span class="cov-cell cov-${r.cov.state}" style="--share:${Math.round((r.cov.share || 0) * 100)}%" role="img" aria-label="${esc(r.cov.text)}" data-tip="${esc(r.cov.text)}"></span>`
        : `<span class="cov-cell cov-empty" aria-hidden="true"></span>`;
    }
    h += `</li>`;
  }
  return h + `</ol>`;
}

/* ---------------------------------------------------------------------------------------------------------- */
/* Heatmap: committee rows by year columns. Every cell prints its recorded count. A chip hatched in the second colour
   prints the likely count beside it. A recorded zero prints "0" on the bare ground; a not-recorded cell never prints 0.
   A cell where Wyatt's number differs carries a corner flag when the switch is on.                              */
/* o: { years:[..], rows:[{key, name, nameHtml?, href, cells:[{c,l,spec,diff,label}], hatched:boolean}], id }     */
export function heatmapHtml(o) {
  let h = `<table class="heat" data-grid aria-labelledby="${esc(o.id)}-sum"><thead><tr><th scope="col" class="heat-corner"><span class="sr-only">Committee</span></th>`;
  for (const y of o.years) h += `<th scope="col" class="heat-year"><span>${y}</span></th>`;
  h += `</tr></thead><tbody>`;
  let first = true;
  for (const r of o.rows) {
    h += `<tr class="${r.hatched ? "heat-none-row" : ""}"><th scope="row" class="heat-name">${r.href ? `<a href="${esc(r.href)}">${esc(r.name)}</a>` : esc(r.name)}${r.nameHtml || ""}</th>`;
    for (const c of r.cells) {
      const st = r.hatched ? "none" : step(c.c);
      const tab = first ? "0" : "-1";
      first = false;
      h += `<td><button type="button" class="hc step-${st}${c.diff ? " wdiff" : ""}" tabindex="${tab}" data-list="${esc(c.spec)}" aria-label="${esc(c.label)}">`
        + (r.hatched ? `<span class="hc-hatch" aria-hidden="true"></span><span class="hc-n hc-n-chip" aria-hidden="true">${fmt(c.c)}</span>`
          : `<span class="hc-n" aria-hidden="true">${fmt(c.c)}</span>${c.l ? `<span class="hc-l" aria-hidden="true">${fmt(c.l)}</span>` : ""}`)
        + `</button></td>`;
    }
    h += `</tr>`;
  }
  return h + `</tbody></table>`;
}

/* A one-series sparkline (Wyatt's rows). values may hold null for a blank cell. */
export function sparkSvg(values, w = 120, hgt = 24) {
  const nums = values.filter(v => v != null);
  const max = Math.max(1, ...nums);
  const n = values.length;
  const px = i => 2 + (i * (w - 4)) / Math.max(1, n - 1);
  const py = v => hgt - 3 - (v / max) * (hgt - 6);
  let d = "", pen = false;
  values.forEach((v, i) => {
    if (v == null) { pen = false; return; }
    d += `${pen ? "L" : "M"}${px(i).toFixed(1)} ${py(v).toFixed(1)}`;
    pen = true;
  });
  return `<svg class="spark" width="${w}" height="${hgt}" viewBox="0 0 ${w} ${hgt}" aria-hidden="true" focusable="false"><path d="${d}"/></svg>`;
}

/* Dot plot: one square per group across the years apart. Squares, not circles (radius 0). */
/* o: { groups:[{id, gap, label, spec}], maxGap, width, id }                                                   */
export function dotPlotSvg(o) {
  const W = Math.max(260, Math.round(o.width));
  const padL = 28, padR = 8, padB = 24, cell = 16, gapPx = 3;
  const cols = o.maxGap + 1;
  const slot = (W - padL - padR) / cols;
  const byGap = new Map();
  for (const g of o.groups) { if (!byGap.has(g.gap)) byGap.set(g.gap, []); byGap.get(g.gap).push(g); }
  const tallest = Math.max(1, ...[...byGap.values()].map(a => a.length));
  const H = 12 + tallest * (cell + gapPx) + padB;
  const base = H - padB;
  let s = `<svg class="chart-svg dot" xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="group" aria-labelledby="${esc(o.id)}-sum" focusable="false">`;
  s += `<line class="axis" x1="${padL}" x2="${W - padR}" y1="${base}" y2="${base}"/>`;
  for (let g = 0; g <= o.maxGap; g++) {
    const cx = padL + g * slot + slot / 2;
    if (slot >= 22 || g % 2 === 0) s += `<text class="tick" aria-hidden="true" x="${cx.toFixed(1)}" y="${base + 16}" text-anchor="middle">${g}</text>`;
  }
  for (const [g, list] of byGap) {
    const cx = padL + g * slot + slot / 2;
    list.forEach((grp, i) => {
      s += `<a href="${esc(grp.href)}" data-list="${esc(grp.spec)}" tabindex="-1" aria-hidden="true" data-tip="${esc(grp.label)}"><rect class="dot-sq" x="${(cx - cell / 2).toFixed(1)}" y="${(base - (i + 1) * (cell + gapPx) + gapPx / 2).toFixed(1)}" width="${cell}" height="${cell}"/></a>`;
    });
  }
  return s + `</svg>`;
}
