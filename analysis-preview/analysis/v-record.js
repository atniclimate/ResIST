/* The Record: where each field is recorded, gaps in the numbering, what the Library lists and this site holds, the
   list to verify (likely and open items, for Wyatt Ash-Milby), and the files behind the counts. */
import { D, FIELDS, makeSpec, esc, fmt, plural, ofWhole, covState, yearsIn, join, cnt, table, sec, keyHtml, COV_KEY, missingConventions, src, WORD_LIKELY, WORD_OPEN } from "./kit.js";
import * as DT from "./data.js";

const GRID_FIELDS = ["title", "titleShown", "committee", "committeeApplied", "committeeLikely", "preparer", "convention", "origin", "outcome", "ncai", "permalink", "site"];
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
  const dflt = yrs.includes(D.yMax - 1) ? D.yMax - 1 : yrs[0];
  const py = +S.q.get("ry") || dflt;
  const one = `<div class="cov-pick"><label for="ry-pick">Year</label><select id="ry-pick" data-pick="ry">${yrs.map(y => `<option${y === py ? " selected" : ""}>${y}</option>`).join("")}</select></div><table class="data"><caption class="sr-only">${py}, what the record holds</caption><thead><tr><th scope="col">Field</th><th scope="col" class="num">Recorded</th></tr></thead><tbody>${GRID_FIELDS.map(x => `<tr><th scope="row">${esc(FIELDS[x].name)}</th><td class="num">${cell(x, py)}</td></tr>`).join("")}</tbody></table>`;
  return `<div class="cg-wide">${wide}</div><div class="cg-narrow">${one}</div>`;
}

const SHEET_NAMES = { people: "People", committees: "Committees", origin: "Origin", sessions: "Sessions", titles: "Titles", places: "Places", other: "Other" };
const kb = n => (n >= 1024 ? `${fmt(Math.round(n / 1024))} KB` : `${fmt(n)} bytes`);
function verifySection() {
  const V = D.agg.verify;
  const byName = new Map(V.files.map(x => [x.name, x]));
  const rows = V.sheets.map(s => { const f = byName.get(`${s.sheet}.csv`); return [esc(SHEET_NAMES[s.sheet] ?? s.sheet), fmt(s.likely), fmt(s.open), f ? `<a href="../data/verify/${esc(f.name)}" download>${esc(f.name)}</a> <span class="sub-inline">${kb(f.bytes)}</span>` : ""]; });
  const xl = byName.get("to-verify.xlsx");
  return sec({
    id: "verify", h2: "To Verify", h3: "Likely and open items, listed for Wyatt Ash-Milby",
    sub: `${fmt(V.total.likely)} likely items and ${fmt(V.total.open)} open items are listed. A likely item is applied, counted and marked; an open item stays as written. Each row says what the workbook writes, where, what the Library now shows and why. Wyatt Ash-Milby's answers come back as rows of the library's answers file; the workbook is never edited.`,
    summary: "Table of the lists to verify, with the number of likely and open items on each sheet and a link to its file.",
    chartHtml: table("t-verify", "The lists to verify, by sheet", ["Sheet", "Likely", "Open", "File"], rows, { numFrom: 1 }), skip: false,
    actions: xl ? `<a class="btn" href="../data/verify/${esc(xl.name)}" download>Download the whole list (${esc(xl.name)}, ${kb(xl.bytes)})</a>` : "",
    csv: "t-verify",
    caveat: "Each file holds ATNI's own T0 record only. No file-path column is ever in a list.",
  });
}

const INPUT_NAMES = { library_build_id: "Library build id (SHA-256 of build.json)", library_schema_version: "Library schema version", library_source_sha256: "Library source (SHA-256)", library_build_script_sha256: "Library build script (SHA-256)", build_json_sha256: "The library build record (build.json)", public_sqlite_sha256: "The public library export (library.sqlite)", verify_xlsx_sha256: "The list to verify (to-verify.xlsx)" };
export function view_record(S) {
  const A = D.agg, all = A.coverage_by_year.all;
  const cover = sec({
    id: "coverage", h2: "Where Each Field Is Recorded", h3: "What the record holds, year by year",
    sub: "Each cell is the number of resolutions with the field recorded, of the resolutions numbered that year. A hatched cell is a field recorded for none. Title as written is the workbook's cell; Title shown is what this page prints, after likely fills. Committee likely only counts resolutions whose every committee link is likely.",
    summary: "Grid of fields by year: each cell shows how many resolutions have the field recorded.",
    chartHtml: coverageBlock(S), skip: false,
    key: keyHtml([{ cls: "cov-full", label: "Recorded on every resolution" }, { cls: "cov-part", label: "Recorded on some" }, { cls: "cov-none", label: "Recorded on none" }]),
    cov: [`Over all years: title as written ${ofWhole(all.with_title, all.resolutions)}, title shown ${ofWhole(all.with_title_shown, all.resolutions)}, committee as written ${ofWhole(all.with_committee_written, all.resolutions)}, a committee applied ${ofWhole(all.with_committee_applied, all.resolutions)} (${fmt(all.with_committee_likely_only)} likely only), Prepared By ${ofWhole(all.with_preparer, all.resolutions)}, convention ${ofWhole(all.with_session, all.resolutions)}, origin ${ofWhole(all.with_origin, all.resolutions)}, outcome ${ofWhole(all.with_outcome, all.resolutions)}, TO NCAI ${ofWhole(all.with_to_ncai, all.resolutions)}, permalink ${ofWhole(all.with_permalink, all.resolutions)}, text on this site ${ofWhole(all.with_site, all.resolutions)}.`],
    caveat: "A missing number is a gap in the numbering, not a missing resolution; most are absent from the site too. The file column of the workbook is counted only as present or not and is never shown.",
  });
  const gaps = A.number_gaps;
  const gapRows = gaps.by_year.map(g => [String(g.year), fmt(g.highest), fmt(g.count), esc(g.ranges.map(r => (r.includes("..") ? r.split("..").map(n => `${g.year}-${n}`).join(" to ") : `${g.year}-${r}`)).join(" and "))]);
  const missing = missingConventions();
  const gapSec = sec({
    id: "gaps", h3: "Gaps in the numbering",
    sub: `${fmt(gaps.count)} numbers are missing between 1 and the highest listed number of their year, in ${fmt(gaps.by_year.length)} years. A missing number is neither drawn as a resolution nor added to a bar.`,
    summary: "Table of missing numbers by year.",
    chartHtml: table("t-gaps", "Missing numbers by year", ["Year", "Highest listed number", "Missing", "Which numbers"], gapRows, { numFrom: 1 }), skip: false, csv: "t-gaps",
    cov: [`Conventions missing from the Library: ${esc(join(missing))}.`], caveat: (gaps.note ? gaps.note.charAt(0).toUpperCase() + gaps.note.slice(1) : "A gap is a missing number between 1 and the highest listed number of the year, not a missing resolution") + ".",
  });
  const sc = A.site_coverage_by_year, soTot = sc.years.reduce((s, r) => s + r.site_only, 0);
  const siteRows = sc.years.filter(r => r.workbook_total || r.site_only).map(r => [String(r.year), fmt(r.workbook_total), cnt(r.linked, makeSpec({ y: r.year, site: "linked" }), `${r.year}, text on this site`), cnt(r.workbook_only, makeSpec({ y: r.year, site: "unlinked" }), `${r.year}, Library only`), fmt(r.site_only)]);
  const siteSec = sec({
    id: "site", h3: "What the Library lists and what this site holds",
    sub: "Resolutions the Library lists, and whether this site holds their text.",
    summary: "Table of resolutions in the Library, with text on this site or not, by year.",
    chartHtml: table("t-site", "What the Library lists and what this site holds, by year", ["Year", "In the Library", "Text on this site", "Library only", "On this site, not in the Library"], siteRows, { numFrom: 1 }), skip: false, csv: "t-site",
    cov: [`This site holds ${fmt(soTot)} numbered resolutions the Library does not list. The Library lists ${fmt((sc.workbook_only_classes || {})["workbook-only-in-site-range"] || 0)} numbers inside the site's years that this site does not hold.`],
    caveat: D.siteFirstYear ? `Before ${D.siteFirstYear} this site holds no text; the Library lists titles.` : "",
  });
  const m = A.meta;
  const files = [...Object.entries(m.inputs || {}).map(([k, h]) => [INPUT_NAMES[k] ?? k, h]), ["aggregates.json (as loaded here)", D.aggSha || "not available in this browser"]];
  const data = `<section class="vs" id="credit" aria-labelledby="credit-h"><h2 id="credit-h">Download the Numbers</h2>
    <p class="credit">${esc(m.credit)}.</p>
    <p class="sub">Every table on this page has a “Download this table” button, and every list has “Download this list”. Both give a CSV file (comma-separated values), which opens in a spreadsheet. The files behind the counts are below, each with its SHA-256 checksum, a code that changes if the file changes.</p>
    <p><a class="btn" href="../data/aggregates.json" download="aggregates.json">Download aggregates.json</a></p>
    <ul class="shas">${files.map(([n, h]) => `<li><span class="sha-n">${esc(n)}</span><code class="sha">${esc(h)}</code></li>`).join("")}</ul>
    <p class="caveat">The data licence is not set. No file-path column and no review table is ever in a download.</p>${src()}</section>`;
  return cover + gapSec + siteSec + verifySection() + data;
}
