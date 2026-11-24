/* Views of the Analysis preview. Each view returns an HTML string; every value from the data passes through esc().
   Charts that depend on the width of their box are drawn by drawers[name](el, S) after the view is in the page.
   The views live in v-*.js; this file is the table of them, plus the Overview and the frame of the Topics tab. */
import { D, makeSpec, esc, fmt, span, cnt, sec, keyHtml, basisKey, src } from "./kit.js";
import { heroSection, view_years, drawYearChart, setCovPick } from "./v-years.js";
import { view_committees, committeeBars, committeeBarsTable, committeeTotals, drawHeat } from "./v-committees.js";
import { view_people, drawCareer } from "./v-people.js";
import { view_words, wordBox, wordAnswer, drawDots } from "./v-words.js";
import { view_record } from "./v-record.js";

export { view_years, view_committees, view_people, view_words, view_record, wordAnswer, setCovPick };
export { lrow, lrows } from "./kit.js";

/* ---------------------------------------------------------------------------------------------------------- */
/* OVERVIEW                                                                                                     */
const TAB_BLURBS = [
  ["years", "Years and Conventions", "Resolutions each year and at each convention, the highest number of each year, a moving average you can switch on, where the conventions met, and the outcomes and the TO NCAI column where the record has them."],
  ["committees", "Committees", "Resolutions by committee and year with recorded and likely counts, where a resolution came from, committee labels as written, and Wyatt Ash-Milby's own counts."],
  ["people", "People", "Names in the Prepared By column as the Library records them, with spellings joined as likely, first and last year and years present."],
  ["words", "Words and Titles", "Words in titles, and titles that appear more than once."],
  ["topics", "Issues, Laws and Wording", "Issue names, laws and orders the resolutions name, and groups of resolutions with similar wording, as text matches."],
  ["record", "The Record", "What the Library holds, year by year, the list to verify, and the files behind these counts."],
];
function limitsPanel(S) {
  const L = D.agg.meta.limits, c = D.agg.meta.counts;
  return `<section class="vs" id="limits" aria-labelledby="limits-h"><h2 id="limits-h">What This Page Counts and Leaves Out</h2>
    <p class="sub">${fmt(c.resolutions_listed)} resolutions are listed. A value marked likely is the most likely answer, applied and counted; a value marked open stays as written. Both are on the <a href="${esc(S.hrefView("record"))}" data-goto="verify">list to verify</a>. On this page, “the Library” and “the workbook” are the same file: The Resolution Library.</p>
    <ul class="plain">${L.map(x => `<li>${esc(x)}</li>`).join("")}</ul></section>`;
}
export function view_overview(S) {
  const f = S.f;
  const hero = heroSection(S);
  const t = committeeTotals(S);
  const cm = sec({
    id: "ov-comm", h2: "Committees, as the Record Names Them", h3: "Resolutions by committee",
    sub: `Each resolution is counted under the committee its Committee cell names, ${esc(span(f))}. A bar has a recorded part and a likely part, and both numbers are printed. A resolution that names two committees is counted under each, so no total across committees is printed. Sorted by number of resolutions. Choose a committee to filter every chart.`,
    summary: `Bars of resolutions by committee, ${span(f)}, sorted by number of resolutions, each with a recorded and a likely count.`,
    chartHtml: committeeBars(S), skip: false,
    key: keyHtml([{ cls: "s-total", label: "Recorded under the committee" }, { cls: "s-none", label: "Names no committee" }]) + basisKey(["likely"]),
    cov: [`${fmt(t.blank + t.other)} resolutions name no committee: ${fmt(t.blank)} have a blank cell and ${fmt(t.other)} write a name that is not a committee, such as Off the Floor or Executive Board.`],
    table: committeeBarsTable(S), csv: "t-ov-comm",
    caveat: "Hatched counts are likely: the committee a label most likely names, applied and counted, with the label kept as written and listed for Wyatt Ash-Milby to verify.",
  });
  const words = `<section class="vs" id="ov-words" aria-labelledby="ov-words-h"><h2 id="ov-words-h">Which Titles Use a Word?</h2><p class="sub">Look up one word. The answer is a count of titles by year and the list behind it.</p>${wordBox(S, "ov")}${src()}</section>`;
  const tabs = `<section class="vs" id="ov-tabs" aria-labelledby="ov-tabs-h"><h2 id="ov-tabs-h">The Other Views</h2><ul class="tabcards">${TAB_BLURBS.map(([v, name, text]) => `<li><a href="${esc(S.hrefView(v))}">${esc(name)}</a><p>${esc(text)}</p></li>`).join("")}</ul></section>`;
  return hero + cm + words + tabs + limitsPanel(S);
}

/* ---------------------------------------------------------------------------------------------------------- */
/* ISSUES, LAWS AND WORDING: the frame only. topics.js draws inside #topics-root (analysis.js loads it on the first visit). */
export function view_topics() {
  return `<section class="vs" id="topics-sec" aria-labelledby="topics-sec-h"><h2 id="topics-sec-h">Issues, Laws and Wording</h2><div id="topics-root" data-state="loading"><p class="empty-line" role="status">Loading this tab.</p></div></section>`;
}

/* ---------------------------------------------------------------------------------------------------------- */
/* drawers (need the width of their box)                                                                        */
export const drawers = {
  hero: (el, S) => drawYearChart(el, S, "hero", ["title", "committee", "preparer"]),
  kind: (el, S) => drawYearChart(el, S, "kind", ["convention"]),
  heat: drawHeat,
  career: drawCareer,
  dots: drawDots,
};
