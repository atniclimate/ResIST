/* Words and Titles: a word lookup, titles that return, titles that share most of their words, the word index. The
   groups by similar wording of whole texts, and the issue names and laws, are on the Issues, Laws and Wording tab. */
import { D, makeSpec, esc, fmt, plural, yearsIn, span, join, runs, cnt, table, sec, src } from "./kit.js";
import * as DT from "./data.js";
import { rowBarsHtml, dotPlotSvg } from "./charts.js";

const noTitle = () => D.agg.coverage_by_year.all.resolutions - D.agg.coverage_by_year.all.with_title_shown;

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
  const ly = f.c ? "b" : "";
  const spec = makeSpec({ w: toks.join(" "), k: f.k, c: f.c, ly, y0: f.y0, y1: f.y1 });
  if (!hits.length) return `<div class="empty-state"><h3>No Titles Matched</h3><p>No title uses ${esc(toks.join(" "))} in this selection. Clear a filter or widen the years to see counts again.</p><p><a class="btn small" href="${esc(S.href({ y0: undefined, y1: undefined, k: undefined, c: undefined }))}">Clear filters</a></p></div>`;
  const byY = new Map(); for (const r of hits) byY.set(r.y, (byY.get(r.y) || 0) + 1);
  const rare = hits.length <= 6;
  const unit = rare ? DT.BANDS.map(([a, z]) => ({ label: `${a} to ${z}`, y0: Math.max(a, f.y0), y1: Math.min(z, f.y1), n: hits.filter(r => r.y >= a && r.y <= z).length })).filter(b => b.y0 <= b.y1)
    : yearsIn(f).map(y => ({ label: String(y), y0: y, y1: y, n: byY.get(y) || 0 }));
  const max = Math.max(1, ...unit.map(u => u.n));
  const rows = unit.map(u => { const sp = makeSpec({ w: toks.join(" "), k: f.k, c: f.c, ly, y0: u.y0, y1: u.y1 }); return { year: u.label, total: u.n, segs: [{ key: "total", n: u.n, label: `${u.label}: ${fmt(u.n)} titles`, spec: sp }], yearSpec: sp }; });
  return `<div class="word-answer"><h3>${plural(hits.length, "title uses", "titles use")} the ${toks.length > 1 ? "words" : "word"} “${esc(toks.join(" "))}”</h3>
    <p class="sub">${rare ? "A bar for each span of years, because the word is rare." : "One bar for each year."} ${esc(span(f))}. Whole words, in any letter case, in the title only.</p>
    <p class="sr-only" id="word-sum">Bar chart of titles using the word ${esc(toks.join(" "))}, by ${rare ? "span of years" : "year"}.</p>
    ${rowBarsHtml({ id: "word", rows, max })}
    <div class="acts"><button type="button" class="btn small" data-list="${esc(spec)}">Show the list (${fmt(hits.length)})</button>
      <a class="btn small quiet" href="#/?q=${encodeURIComponent(toks.join(" "))}" data-live="the search page, with “${esc(toks.join(" "))}” entered">Search the full text for this word</a></div>
    <p class="caveat">A word match is a text match in the title, never what a resolution is about. ${plural(noTitle(), "resolution has", "resolutions have")} no title in the record.</p></div>`;
}
export const wordBox = (S, idp) => `<form class="wordbox" role="search" data-wordform><label for="${idp}-q">Look up a word in the titles</label><div class="wb-row"><input id="${idp}-q" name="w" type="search" autocomplete="off" spellcheck="false" placeholder="A word from a title" value="${esc(S.q.get("w") || "")}"><button type="submit" class="btn">Look up</button></div></form><div class="word-out" aria-live="polite" data-wordout>${wordAnswer(S)}</div>`;

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

function wordIndexBlock() {
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
    caveat: `A word match is a text match in the title, never what a resolution is about. ${plural(noTitle(), "resolution has", "resolutions have")} no title in the record.`,
  });
}

export function view_words(S) {
  const lookup = `<section class="vs" id="lookup" aria-labelledby="lookup-h"><h2 id="lookup-h">Look Up a Word</h2><p class="sub">Count the titles that use a word, by year, and open the list.</p>${wordBox(S, "w")}${src()}</section>`;
  const clusters = `<section class="vs" id="clusters" aria-labelledby="clusters-h"><h2 id="clusters-h">Groups by Similar Wording</h2>
    <p class="sub">Groups of resolutions whose full text uses similar words, issue names from Policy Sentinel, and the laws and orders the resolutions name are on the <a href="${esc(S.hrefView("topics"))}">Issues, Laws and Wording</a> tab. What can be counted from the titles alone is on this tab: the word index, two-word phrases, how titles begin, titles that appear more than once and titles that share most of their words.</p>
    <p class="caveat">Full text exists only from ${D.siteFirstYear ?? "a later year"}, so a full-text group says nothing about the years before. A group by title covers every year, and ${plural(noTitle(), "title is", "titles are")} blank.</p></section>`;
  return lookup + returningBlock(S) + wordIndexBlock() + clusters;
}

export function drawDots(el, S) {
  const f = S.f, G = D.agg.readoptions.groups.filter(g => g.members.some(m => m.year >= f.y0 && m.year <= f.y1)).map(g => ({ ...g, gap: g.members[g.members.length - 1].year - g.members[0].year }));
  const id = el.dataset.sum.replace(/-sum$/, ""), maxGap = Math.max(1, ...G.map(g => g.gap));
  const groups = G.map(g => { const spec = makeSpec({ nums: g.members.map(m => m.number).join(";") }); return { id: g.group_id, gap: g.gap, label: `${g.members.map(m => m.number).join(", ")}: ${g.gap === 0 ? "same year" : plural(g.gap, "year", "years") + " apart"}`, spec, href: S.listHref(spec) }; });
  el.innerHTML = `<p class="axis-t">Years apart</p>` + dotPlotSvg({ id, width: el.clientWidth, groups, maxGap });
}
