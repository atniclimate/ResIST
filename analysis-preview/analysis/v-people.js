/* People: the names in the Prepared By column, with the likely merges marked ("likely includes ..."), first year, last
   year and years present. Sorted by name unless the reader chooses resolutions or years present. No score, rank or
   rate of any kind is shown for a person. Names written in the Committee column are kept apart, role not stated. */
import { D, KINDS, makeSpec, esc, fmt, plural, ofWhole, covState, kindLabel, cname, nr, join, runs, cnt, table, sec, keyHtml, COV_KEY, covSentence, covCells, lrows, src, mark, WORD_LIKELY, WORD_OPEN } from "./kit.js";
import * as DT from "./data.js";
import { yearBarsSvg, rowBarsHtml } from "./charts.js";

const personMark = p => (p.basis === "likely" ? `<mark class="likely">${esc(p.name)}</mark> ${WORD_LIKELY}` : esc(p.name));
const includes = p => (p.likely_includes && p.likely_includes.length ? `<span class="pl-inc">likely includes ${p.likely_includes.map(f => `“${esc(f)}”`).join(", ")}</span>` : "");

const withheld = S => sec({
  id: "withheld", h2: "Prepared By, as the Workbook Records", h3: "Resolutions by who prepared them",
  sub: "Names from The Resolution Library are not shown while Show names is off.",
  chartHtml: `<div class="empty-state"><h3>Names Are Hidden</h3><p>Counts by committee and year are shown instead. Turn on Show names, at the top of the page, to see the names the record writes.</p><p><a class="btn small" href="${esc(S.hrefView("committees"))}">See committees</a></p></div>`,
  extra: (() => {
    const mx = new Map();
    for (const r of D.rows) if (r.pb) for (const k of new Set(r.cs.map(x => x[0]))) mx.set(k, (mx.get(k) || 0) + 1);
    return table("t-pb-committee", "Resolutions with Prepared By recorded, by committee", ["Committee", "With Prepared By recorded"], [...mx.entries()].sort((a, b) => b[1] - a[1]).map(([k, n]) => [esc(cname(k)), cnt(n, makeSpec({ c: k, ly: "b", has: "preparer" }), cname(k))]));
  })(),
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
  const people = [...D.persons.values()];
  const sort = S.q.get("ps") === "n" ? "n" : S.q.get("ps") === "y" ? "y" : "name";
  const picked = S.q.get("pc") || "";
  let list = people;
  if (picked) { const set = new Set(); for (const r of D.rows) if (DT.layerOf(r, picked)) r._pk.forEach(p => set.add(p)); list = people.filter(p => set.has(p.key)); }
  const byName = (a, b) => a.name.localeCompare(b.name);
  list = [...list].sort(sort === "n" ? (a, b) => b.total - a.total || byName(a, b) : sort === "y" ? (a, b) => b.years_present - a.years_present || byName(a, b) : byName);
  const pcs = D.cmList.filter(c => D.rows.some(r => DT.layerOf(r, c.key) && r._pk.length));
  const likelyN = people.filter(p => p.basis === "likely").length;
  const listHtml = `<ul class="plist people" data-people>${list.map(p => `<li data-name="${esc([p.name, ...p.forms.map(f => f.form)].join(" ").toLowerCase())}"><div class="pl-head"><span class="pl-name"><a href="${esc(S.hrefView("people", { p: p.key }))}">${esc(p.name)}</a>${p.basis === "likely" ? ` ${WORD_LIKELY}` : ""}</span><span class="pl-n">${cnt(p.total, makeSpec({ p: p.key }), p.name)} <span class="sub-inline">${p.first_year === p.last_year ? p.first_year : `${p.first_year} to ${p.last_year}`}, ${plural(p.years_present, "year", "years")} present</span></span></div>${includes(p) ? `<div class="pl-sub">${includes(p)}</div>` : ""}${stripHtml(p, S)}</li>`).join("")}</ul>`;
  const btn = (v, label) => `<button type="button" class="btn small${sort === (v || "name") ? "" : " quiet"}" data-patch="ps=${v}" aria-pressed="${sort === (v || "name")}">${label}</button>`;
  const main = sec({
    id: "people", h2: "Prepared By, as the Workbook Records", h3: "Resolutions by who prepared them",
    sub: "Names are shown as written in ATNI's record. A name marked likely stands for spellings the Library most likely holds as one person; each spelling it includes is listed with it.",
    summary: `List of ${D.agg.meta.counts.people} names, each with a strip of the years it is named in.`,
    chartHtml: `<div class="people-tools"><div class="pt-find"><label for="find-name">Find a name</label><input id="find-name" type="search" autocomplete="off" spellcheck="false" data-find placeholder="Part of a name"></div>
      <div class="pt-pick"><label for="pc-pick">Names on one committee</label><select id="pc-pick" data-pick="pc"><option value="">All committees</option>${pcs.map(c => `<option value="${esc(c.key)}"${c.key === picked ? " selected" : ""}>${esc(c.name)}</option>`).join("")}</select></div>
      <div class="pt-sort"><span id="sort-l">Order</span><div role="group" aria-labelledby="sort-l">${btn("", "Name order")}${btn("n", "Most resolutions first")}${btn("y", "Most years present first")}</div></div></div>
      <p class="find-count" role="status" aria-live="polite" data-findcount>${fmt(list.length)} names${picked ? ` on ${esc(cname(picked))} resolutions` : ""}.</p>${listHtml}`, skip: false,
    key: keyHtml([{ cls: "tl-u", label: "A year the name appears" }, { cls: "s-none", label: "Prepared By not recorded that year" }]),
    cov: [covSentence(S, "preparer"), `${fmt(likelyN)} of the ${fmt(people.length)} names include spellings joined as likely, not yet verified. Forms that differ by a generation suffix are never joined by inference.`],
    caveat: `A preparer is what The Resolution Library records; the resolutions themselves do not print one. Preparers are not recorded for ${esc(join(runs(D.years.filter((y, i) => DT.covMatrix("preparer", "", "")[i].n === 0))))}. The list shows a count of resolutions and the years a name is present; it never ranks or scores a person.`,
  });
  return main + namedBlock(S) + togetherBlock(S);
}

function namedBlock(S) {
  const N = D.agg.named;
  const total = N.reduce((s, x) => s + x.n, 0);
  const KIND_WORDS = { person: "A person", tribe_or_org: "A Tribe or organization" };
  const rows = N.map(x => [x.text ? esc(x.text) : `<span class="nr">no text</span>`, KIND_WORDS[x.kind] ?? esc(x.kind), x.person_key && D.persons.has(x.person_key) ? `<a href="${esc(S.hrefView("people", { p: x.person_key }))}">${esc(D.persons.get(x.person_key).name)}</a>` : "", cnt(x.n, makeSpec({ nums: x.numbers.join(";") }), x.text || "A name with no text")]);
  return sec({
    id: "named", h2: "Named on the Record, Role Not Stated", h3: "Names written in the Committee column",
    sub: `${plural(N.length, "name or Tribe is", "names and Tribes are")} written in the Committee column with no role stated, on ${plural(total, "resolution", "resolutions")}. They are kept with the resolution and shown as written. They are not preparers, and they give no committee.`,
    summary: `Table of ${N.length} names written in the Committee column, role not stated.`,
    chartHtml: N.length ? table("t-named", "Names written in the Committee column, role not stated", ["As written", "Kind", "Same as", "Resolutions"], rows, { numFrom: 3 }) : `<p class="empty-line">No name is written in the Committee column in this record.</p>`, skip: false,
    csv: N.length ? "t-named" : "",
    caveat: "A Tribe written here, or after Off the Floor, is shown as written with no role. It is never read as an affiliation.",
  });
}

function togetherBlock(S) {
  const f = S.f, all = !f.k && !f.c && f.y0 === D.yMin && f.y1 === D.yMax;
  let pairs;
  if (all) pairs = D.agg.co_preparation;
  else {
    const m = new Map();
    for (const r of D.rows) {
      if (r.y < f.y0 || r.y > f.y1 || !DT.selects(r, f.k, f.c)) continue;
      for (let i = 0; i < r._pk.length; i++) for (let j = i + 1; j < r._pk.length; j++) {
        const [a, b] = [r._pk[i], r._pk[j]].sort(), id = a + "|" + b;
        if (!m.has(id)) m.set(id, { a, b, n: 0, ys: [] });
        const o = m.get(id); o.n++; o.ys.push(r.y);
      }
    }
    pairs = [...m.values()].map(o => ({ a: o.a, b: o.b, a_name: D.persons.get(o.a).name, b_name: D.persons.get(o.b).name, n: o.n, first_year: Math.min(...o.ys), last_year: Math.max(...o.ys) })).sort((x, y) => x.a.localeCompare(y.a) || x.b.localeCompare(y.b));
  }
  const multi = D.rows.filter(r => r._pk.length > 1 && r.y >= f.y0 && r.y <= f.y1 && DT.selects(r, f.k, f.c));
  const head = ["Two names", "Resolutions that name both", "Years"];
  const rows = pairs.map(p => [`<a href="${esc(S.hrefView("people", { p: p.a }))}">${esc(p.a_name)}</a> and <a href="${esc(S.hrefView("people", { p: p.b }))}">${esc(p.b_name)}</a>`, cnt(p.n, makeSpec({ p: p.a, p2: p.b }), `${p.a_name} and ${p.b_name}`), p.first_year === p.last_year ? String(p.first_year) : `${p.first_year} to ${p.last_year}`]);
  return sec({
    id: "together", h2: "Named Together", h3: "People named together in Prepared By",
    sub: `Pairs of names that one Prepared By cell names together. ${fmt(pairs.length)} pairs. Being named in one cell is all the record says; it is not a measure of collaboration.`,
    summary: `List of ${pairs.length} pairs of names, with the number of resolutions that name both.`,
    chartHtml: pairs.length ? table("t-together", "People named together in Prepared By", head, rows, { numFrom: 1 }) : `<div class="empty-state"><h3>No Pairs in This Selection</h3><p>No Prepared By cell names two people in this selection. Clear a filter or widen the years to see counts again.</p></div>`, skip: false,
    csv: pairs.length ? "t-together" : "",
    caveat: `Two people are counted together when one Prepared By cell names both. ${fmt(multi.length)} resolutions name two or more people in this selection.`,
  });
}

function personPage(S, key) {
  const p = D.persons.get(key), rows = DT.personRows(key);
  const kinds = DT.personKinds(key), site = DT.personWithSite(key);
  const labels = new Map(); for (const r of rows) { const l = r.cl || ""; labels.set(l, (labels.get(l) || 0) + 1); }
  const covP = DT.covMatrix("preparer", "", "");
  const partYears = D.years.filter((y, i) => y >= p.first_year && y <= p.last_year && covP[i].n < covP[i].total);
  const partners = DT.coPartners(key);
  const named = D.agg.named.filter(x => x.person_key === key);
  const namedNums = [...new Set(named.flatMap(x => x.numbers))];
  const request = `Resolution number: \nField: Prepared By\nWhat the record shows: \nWhat it should show: `;
  return `<section class="vs person" id="person" aria-labelledby="person-h">
    <p class="crumb"><a href="${esc(S.href({ p: undefined }))}">All names</a></p>
    <h2 id="person-h">${personMark(p)}</h2>
    <p class="sub">Prepared by, as the workbook records.</p>
    <p class="lead-p">The Resolution Library names ${esc(p.name)} in the Prepared By column of ${plural(p.total, "resolution", "resolutions")}, ${p.first_year === p.last_year ? p.first_year : `${p.first_year} to ${p.last_year}`}, in ${plural(p.years_present, "year", "years")}. ResIST shows what the record says and nothing more about any person.</p>
    ${p.basis === "likely" ? `<p class="note">${WORD_LIKELY} includes ${p.likely_includes.map(f => `“${esc(f)}”`).join(", ")}. These spellings are joined to this name as the most likely reading and are listed for Wyatt Ash-Milby to verify. Each is listed below as the record writes it.</p>` : ""}
    <h3>Spellings as Written</h3>
    <ul class="plain">${p.forms.map(fm => `<li>“${esc(fm.form)}” ${cnt(fm.n, makeSpec({ p: key, pf: fm.form }), fm.form)}${fm.basis === "likely" ? ` ${WORD_LIKELY}` : ""}</li>`).join("")}</ul>
    ${p.named_also ? `<p>Also named on the record, role not stated: ${namedNums.length ? cnt(p.named_also, makeSpec({ nums: namedNums.join(";") }), `${p.name}, named in the Committee column`) : fmt(p.named_also)}. A name written in the Committee column is kept with its resolution and is not counted as a preparer.</p>` : ""}
    <h3>Years Named</h3>
    <p class="sr-only" id="career-sum">Bars of resolutions naming ${esc(p.name)} by year, with a strip showing the years Prepared By is recorded.</p>
    <div class="chart" data-chart="career" data-sum="career-sum" data-person="${esc(key)}"></div>
    <p class="cov-sentence">Named in ${plural(p.years_present, "year", "years")}${partYears.length ? `. Prepared By is recorded for only part of ${esc(join(runs(partYears)))}, which fall inside these years` : ""}.</p>
    <h3>Committees</h3>
    <ul class="plain">${Object.entries(p.by_committee).sort((a, b) => b[1] - a[1]).map(([k, n]) => `<li>${k === "none" ? "No committee in the record" : esc(cname(k))} ${cnt(n, k === "none" ? makeSpec({ p: key, cn: "any" }) : makeSpec({ p: key, c: k, ly: "b" }), k === "none" ? "No committee" : cname(k))}</li>`).join("")}</ul>
    <p class="sub">Committee labels as written: ${esc([...labels.entries()].sort((a, b) => b[1] - a[1]).map(([l, n]) => `${l || "blank"} ${n}`).join("; "))}.</p>
    <h3>Convention Kinds</h3>
    <ul class="plain">${KINDS.concat([{ key: "none", label: "No convention recorded" }]).filter(k => kinds[k.key]).map(k => `<li>${esc(k.label)} ${cnt(kinds[k.key], makeSpec({ p: key, k: k.key }), k.label)}</li>`).join("")}</ul>
    <h3>Named Together With</h3>
    ${partners.length ? `<ul class="plain">${partners.map(q => { const o = q.a === key ? [q.b, q.b_name] : [q.a, q.a_name]; return `<li><a href="${esc(S.hrefView("people", { p: o[0] }))}">${esc(o[1])}</a> ${cnt(q.n, makeSpec({ p: key, p2: o[0] }), o[1])}</li>`; }).join("")}</ul>` : `<p>Named with no one else.</p>`}
    <p class="sub">${fmt(site)} of ${fmt(p.total)} resolutions link to a document on this site.</p>
    <h3>The Resolutions</h3>
    <p class="sub">${fmt(p.total)} resolutions, as the workbook records them. No outcome, TO NCAI (National Congress of American Indians) or rate is shown for a person.</p>
    <ol class="lrows" id="person-list">${lrows(rows, S, 0, 50)}</ol>
    ${rows.length > 50 ? `<button type="button" class="btn small quiet" data-more="person-list" data-key="${esc(key)}" data-from="50">Show more (${fmt(rows.length - 50)})</button>` : ""}
    <div class="corrections"><h3>Is Something Wrong Here?</h3>
      <p>ResIST shows The Resolution Library as ATNI recorded it. <a href="https://atnitribes.org/" rel="noopener">Ask ATNI to correct it</a> through ATNI's own site. ResIST sends nothing. ATNI decides; the answer becomes a ledger row, the build runs again, and the value as written stays in the ledger beside the correction.</p>
      <p>A family may ask ATNI that a name not be shown here. ATNI decides, and the record keeps the name as written.</p>
      <details class="tbl"><summary>Request text to copy</summary><pre class="req" id="req-text">${esc(request)}</pre><button type="button" class="btn small" data-copy="req-text">Copy request text</button><span class="copied" role="status" aria-live="polite" data-copied></span></details></div>
    <p class="caveat">Everything on this page is what the Prepared By column records; the PDFs do not print preparers. A spelling marked likely is applied as the most likely reading and is listed for Wyatt Ash-Milby to verify.</p>
    ${src()}</section>`;
}

export function drawCareer(el, S) {
  const key = el.dataset.person, p = D.persons.get(key);
  const covP = DT.covMatrix("preparer", "", "");
  const rows = D.years.map(y => { const n = p.by_year[y] || 0; const c = covP[D.yi.get(y)]; return { year: y, total: n, segs: [{ key: "total", n, label: `${y}: named on ${fmt(n)} resolutions`, spec: makeSpec({ p: key, y }) }], yearSpec: makeSpec({ p: key, y }), text: n ? fmt(n) : (c.n === 0 ? nr : ""), cov: { state: covState(c.n, c.total), share: c.total ? c.n / c.total : 0, text: `${y}: Prepared By recorded for ${ofWhole(c.n, c.total)} resolutions` } }; });
  const max = Math.max(1, ...rows.map(r => r.total));
  const id = el.dataset.sum.replace(/-sum$/, "");
  if (S.wide) el.innerHTML = yearBarsSvg({ id, width: el.clientWidth, height: 120, rows, max, href: S.listHref, strips: [{ name: "Prepared By recorded", cells: covCells(S, "preparer", D.years) }] }) + keyHtml([{ cls: "s-total", label: "Resolutions that name this person" }, ...COV_KEY]);
  else el.innerHTML = rowBarsHtml({ id, rows, max, covName: "Prepared By recorded" }) + keyHtml([{ cls: "s-total", label: "Resolutions that name this person" }, ...COV_KEY]);
}
