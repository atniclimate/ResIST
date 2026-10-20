// Run by tests/test_pages_js.py (node --test). Clause text is ATNI's published T0 wording (D-052), from 26-51.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  COMMITTEES, STANDARD, body, clauseState, compose, hasPageHeader, isStandard, lineText, newClause, newDraft,
  removePageHeader, resolvedLead, safeUrl, validDraft, segments, cleanCites, anchorCites, insertCite, citeFrom, squash,
} from "../../pages/compose.js";
import { CITE, CITE_SOURCE } from "./docx-fixtures.mjs";

const PUBLISHED_CLOSING = "that this will be the policy of ATNI until it is withdrawn or modified by subsequent resolution(s)";
const CLOSING_WITH_HEADER = PUBLISHED_CLOSING + ".\nAFFILIATED TRIBES OF NORTHWEST INDIANS  \nRESOLUTION #2026 � 051 " +
  "\n \n2026 ANNUAL CONVENTION \n \n \n         PAGE 3";
const URGE = "that ATNI urges both Tribal and Public Schools to exercise caution and establish strong ethical " +
  "safeguards governing the use of artificial intelligence (AI) in Tribal educational systems; and";
const source = text => ({ resolutionId: 1, number: "26-51", title: "Supporting Responsible Governance", year: 2026,
  convention: "Annual Convention", documentId: "a".repeat(64), statementType: "resolved", index: 0, text,
  url: "https://atnitribes.org/wp-content/uploads/2026/09/26-51.pdf" });

test("body strips lead words and joiners but keeps abbreviations", () => {
  assert.equal(body("WHEREAS, the Affiliated Tribes of Northwest Indians (ATNI) are the representatives; and"),
    "the Affiliated Tribes of Northwest Indians (ATNI) are the representatives");
  assert.equal(body("THEREFORE, BE IT RESOLVED, that ATNI supports policies; and"), "that ATNI supports policies");
  assert.equal(body("NOW, THEREFORE, BE IT RESOLVED that ATNI acts."), "that ATNI acts");
  assert.equal(body("BE IT FINALLY RESOLVED, " + STANDARD.closing + "."), STANDARD.closing);
  assert.equal(body("future generations; now"), "future generations");
  assert.equal(body("as provided in 25 U.S.C."), "as provided in 25 U.S.C.");
  // Verbatim from 24-01 RESOLVED 1 as stored: the next clause's lead word leaked into this one.
  assert.equal(body("that ATNI condemns the Western Oregon Termination Act of 1954; and THEREFORE"),
    "that ATNI condemns the Western Oregon Termination Act of 1954");
});

test("resolved lead words follow position", () => {
  assert.equal(resolvedLead(0, 1), "THEREFORE, BE IT RESOLVED,");
  assert.deepEqual([0, 1, 2].map(i => resolvedLead(i, 3)),
    ["THEREFORE, BE IT RESOLVED,", "BE IT FURTHER RESOLVED,", "BE IT FINALLY RESOLVED,"]);
});

test("a new draft composes to the template's form with fillable unknowns", () => {
  const out = compose(newDraft(2026));
  assert.equal(out.number, "RESOLUTION # 2026 – DRFT-XX");
  assert.equal(out.runningHeader, "AFFILIATED TRIBES OF NORTHWEST INDIANS RESOLUTION #2026-DRFT-XX");
  assert.equal(lineText(out.heading[0]), "ATNI [Convention]");
  assert.equal(lineText(out.title), "“[Resolution title]”");
  assert.equal(lineText(out.certification), "The foregoing Resolution was adopted at the Affiliated Tribes of " +
    "Northwest Indians [Convention] held at the [Venue] in [City, State] on [Convention dates], with a quorum present.");
  assert.deepEqual(out.whereas.map(w => w.text.slice(-5)), ["; and", "; and", "; now"]);
  assert.equal(out.resolved.length, 1);
  assert.equal(out.resolved[0].lead, "THEREFORE, BE IT RESOLVED,");
  assert.ok(out.resolved[0].text.endsWith("subsequent resolutions."));
  assert.ok(out.problems.includes("Add a title."));
  assert.ok(out.problems.includes("Add at least one RESOLVED clause of your own."));
  assert.match(out.problems.at(-1), /^Convention details still to fill in: name, city and state, venue, dates\./);
  assert.equal(out.form.ncai, null);
  assert.equal(out.form.committees.flat().filter(c => c && c.checked).length, 0);
});

test("known convention details replace the placeholders", () => {
  const d = newDraft(2026);
  Object.assign(d.header, { convention: "2026 Annual Convention", location: "Snoqualmie, Washington",
    venue: "Snoqualmie Casino and Hotel", dates: "September 13-17, 2026" });
  const out = compose(d);
  assert.equal(lineText(out.certification), "The foregoing Resolution was adopted at the Affiliated Tribes of " +
    "Northwest Indians 2026 Annual Convention held at the Snoqualmie Casino and Hotel in Snoqualmie, Washington on " +
    "September 13-17, 2026, with a quorum present.");
  assert.equal(out.runningFooter, "2026 ANNUAL CONVENTION");
  assert.ok(!out.problems.some(p => p.startsWith("Convention details")));
});

test("carried clauses keep provenance and report their state", () => {
  const d = newDraft(2026);
  d.title = "Supporting Responsible Governance of Youth Use of Artificial Intelligence Chatbots";
  d.resolved.unshift(newClause(URGE, "carried", source(URGE)));
  const out = compose(d);
  assert.equal(lineText(out.title), "“Supporting Responsible Governance of Youth Use of Artificial Intelligence Chatbots”");
  assert.equal(out.resolved[0].lead, "THEREFORE, BE IT RESOLVED,");
  assert.equal(out.resolved[1].lead, "BE IT FINALLY RESOLVED,");
  assert.ok(out.resolved[0].text.endsWith("educational systems; and"));
  assert.deepEqual(out.sources.map(s => [s.position, s.state, s.number]), [["RESOLVED 1", "verbatim", "26-51"]]);
  d.resolved[0].text += " of the region";
  assert.equal(compose(d).sources[0].state, "edited");
});

test("a leaked page header is detected, removable, and not counted as an edit", () => {
  assert.ok(hasPageHeader(CLOSING_WITH_HEADER));
  assert.ok(!hasPageHeader("the Affiliated Tribes of Northwest Indians (ATNI) are the representatives"));
  assert.equal(removePageHeader(CLOSING_WITH_HEADER), PUBLISHED_CLOSING + ".");
  const c = newClause(CLOSING_WITH_HEADER, "carried", source(CLOSING_WITH_HEADER));
  const d = newDraft(2026);
  d.resolved = [c];
  assert.equal(clauseState(c), "verbatim");
  assert.match(compose(d).problems.join(" "), /RESOLVED 1 contains page-header text/);
  c.text = removePageHeader(c.text);
  assert.equal(clauseState(c), "cleaned");
  assert.ok(isStandard(c.text), "the published wording counts as standard");
});

test("committees and NCAI follow the submission form", () => {
  assert.equal(COMMITTEES.length, 22);
  assert.deepEqual(COMMITTEES.slice(0, 3), ["Culture/Elders", "Drug Abuse & Prev.", "Economic Development"]);
  const d = newDraft(2026);
  d.meta.committees = ["Energy"];
  d.meta.otherCommittee = "Climate Resilience";
  d.meta.ncai.forward = true;
  const out = compose(d);
  const checked = out.form.committees.flat().filter(c => c && c.checked).map(c => c.name);
  assert.deepEqual(checked, ["Energy", "Other"]);
  assert.deepEqual(out.form.ncai, { emergency: "" });
  assert.ok(out.problems.includes("A resolution forwarded to NCAI needs ATNI's transmittal clause."));
  d.resolved.unshift(newClause(STANDARD.ncai, "standard"));
  assert.ok(!compose(d).problems.includes("A resolution forwarded to NCAI needs ATNI's transmittal clause."));
});

test("draft files round-trip and bad ones are refused", () => {
  const d = newDraft(2026);
  assert.deepEqual(validDraft(JSON.parse(JSON.stringify(d))), d);
  assert.equal(validDraft({ schema: "other" }), null);
  assert.equal(validDraft({ ...d, whereas: [{ id: "x", text: "t", origin: "carried" }] }), null);
  const partial = validDraft({ schema: d.schema, whereas: [], resolved: [], meta: { committees: ["Energy", "Bogus"] } });
  assert.equal(partial.meta.ncai.forward, false);
  assert.deepEqual(partial.meta.committees, ["Energy"]);
});

test("only https links survive", () => {
  assert.equal(safeUrl("https://atnitribes.org/x.pdf"), "https://atnitribes.org/x.pdf");
  assert.equal(safeUrl("javascript:alert(1)"), "");
  assert.equal(safeUrl('https://x.org/"onmouseover='), "");
});

// Carried citations (UI-2, D-077). CITE is a real span of a stored clause (docx-fixtures.mjs); assertion messages
// are fixed strings, never the text.
const citeOf = (source = CITE_SOURCE, id = "k1") => ({ id, text: squash(source.text), source: { ...source } });
const citedClause = () => {
  const c = { id: "c1", text: "", origin: "typed" };
  insertCite(c, 0, citeOf());
  return c;
};

test("segments splits at spans and collapses whitespace per piece", () => {
  const parts = segments(CITE.statement, [{ start: CITE.start, end: CITE.end }]);
  assert.equal(parts.length, 3);
  assert.deepEqual(parts.map(p => p.span && [p.span.start, p.span.end]), [null, [CITE.start, CITE.end], null]);
  assert.ok(parts[1].text === CITE.text, "the span piece is the citation");
  assert.ok(parts.map(p => p.text).join("") === squash(CITE.statement), "the pieces rejoin to the squashed text");
  assert.equal(segments(CITE.statement, [{ start: -1, end: 3 }, { start: 5, end: 99999 }]).length, 1, "spans that do not fit are ignored");
  const spaced = ` \n${CITE.statement.slice(0, CITE.start)}\n\n${CITE.text}  ${CITE.statement.slice(CITE.end)} `;
  const at = 4 + CITE.start;   // " \n" before, "\n\n" between
  const p2 = segments(spaced, [{ start: at, end: at + CITE.text.length }]);
  assert.ok(p2.map(p => p.text).join("") === squash(spaced), "whitespace collapses in every piece and the ends are trimmed");
  assert.equal(segments("", []).length, 0);
});

test("cleanCites keeps valid entries and drops forged ones", () => {
  const ok = citedClause();
  assert.equal(cleanCites(ok), ok, "a valid clause is returned as the same object");
  const plain = newClause("typed words", "typed");
  assert.equal(cleanCites(plain), plain);
  const forge = fn => { const c = citedClause(); fn(c, c.cites[0]); return cleanCites(c); };
  for (const [name, fn] of [
    ["out of range", (c, x) => { x.end = c.text.length + 1; }],
    ["non-integer", (c, x) => { x.start = 0.5; }],
    ["slice mismatch", (c, x) => { x.text = x.text.slice(1); }],
    ["bad statementType", (c, x) => { x.source.statementType = "preamble"; }],
    ["missing source.text", (c, x) => { delete x.source.text; }],
    ["page not an integer", (c, x) => { x.source.page = "2"; }],
    ["no id", (c, x) => { delete x.id; }],
  ]) {
    const out = forge(fn);
    assert.ok(!("cites" in out), `${name}: dropped, and no cites key remains`);
    assert.equal(out.text, citedClause().text, `${name}: the words stay`);
  }
  // An overlapping second entry is dropped and the first kept.
  const two = citedClause(), sub = two.text.slice(0, 9);
  two.cites.push({ id: "k2", start: 0, end: 9, text: sub, source: { ...CITE_SOURCE, text: sub } });
  const kept = cleanCites(two);
  assert.notEqual(kept, two);
  assert.deepEqual(kept.cites.map(x => x.id), ["k1"]);
  const notList = cleanCites({ ...ok, cites: "x" });
  assert.ok(!("cites" in notList));
  // A whole draft round-trips with its citations.
  const d = newDraft(2026);
  d.whereas.push(citedClause());
  const back = validDraft(JSON.parse(JSON.stringify(d)));
  assert.deepEqual(back, d);
});

test("anchorCites follows a moved citation and drops an edited one", () => {
  const c = citedClause();
  assert.equal(anchorCites(c), 0);
  c.text = "As stated in " + c.text;
  assert.equal(anchorCites(c), 0);
  assert.deepEqual([c.cites[0].start, c.cites[0].end], [13, 13 + CITE.text.length]);
  assert.ok(c.text.slice(c.cites[0].start, c.cites[0].end) === c.cites[0].text, "the moved citation slices its words");
  const i = c.cites[0].start + 2;
  c.text = c.text.slice(0, i) + "x" + c.text.slice(i + 1);
  assert.equal(anchorCites(c), 1);
  assert.ok(!("cites" in c), "no cites key once none remain");
  const plain = newClause("typed words", "typed");
  assert.equal(anchorCites(plain), 0);
  assert.ok(!("cites" in plain));
});

test("insertCite adds separating spaces only where needed and shifts later citations", () => {
  const words = CITE.text, n = words.length;
  const a = { id: "a", text: CITE.statement, origin: "typed" };
  const end = insertCite(a, a.text.length, citeOf());
  assert.deepEqual(end, { start: CITE.statement.length + 1, end: CITE.statement.length + 1 + n });
  assert.ok(a.text === `${CITE.statement} ${words}`, "a space before, none after at the end");
  const start = insertCite(a, 0, citeOf({ ...CITE_SOURCE, index: 0 }, "k2"));
  assert.deepEqual(start, { start: 0, end: n });
  assert.ok(a.text.startsWith(`${words} ${CITE.statement.slice(0, 5)}`), "a space after, none before at the start");
  assert.deepEqual(a.cites.map(x => x.id), ["k2", "k1"], "sorted by start");
  assert.equal(a.cites[1].start, CITE.statement.length + 1 + n + 1, "the later citation shifted by the inserted length");
  for (const x of a.cites) assert.ok(a.text.slice(x.start, x.end) === x.text, "every citation still slices its words");
  // Inside a citation the insert moves to its end; before a comma no space follows.
  const b = { id: "b", text: CITE.statement, origin: "typed" };
  const comma = b.text.indexOf(",");
  assert.ok(comma > 0);
  const r = insertCite(b, comma, citeOf());
  assert.equal(b.text[r.end], ",", "no space before a comma");
  assert.equal(b.text[r.start - 1], " ");
  const r2 = insertCite(b, r.start + 2, citeOf({ ...CITE_SOURCE, index: 1 }, "k3"));
  assert.equal(r2.start, r.end + 1, "an insert inside a citation lands after it");
  // After a space no extra space is added; a non-integer position means the end.
  const c = { id: "c", text: "see ", origin: "typed" };
  insertCite(c, 4, citeOf());
  assert.ok(c.text === `see ${words}`, "no doubled space");
  const e = { id: "e", text: "", origin: "typed" };
  assert.deepEqual(insertCite(e, undefined, citeOf()), { start: 0, end: n });
});

test("compose lists every carried citation with page or page unknown, and marks only when offsets hold", () => {
  const d = newDraft(2026);
  const own = citedClause();
  const joined = { id: "c2", text: "; and", origin: "typed" };
  insertCite(joined, 0, citeOf({ ...CITE_SOURCE, page: null }, "k2"));
  d.whereas.push(own, joined);
  const out = compose(d);
  assert.deepEqual(out.citations.map(x => [x.position, x.number, x.clause, x.page, x.documentId.length]),
    [["WHEREAS 4", CITE.number, `WHEREAS ${CITE.position}`, CITE.page, 64], ["WHEREAS 5", CITE.number, `WHEREAS ${CITE.position}`, null, 64]]);
  assert.ok(out.citations.every(x => x.text === CITE.text), "the citation words are listed verbatim");
  assert.equal(citeFrom(out.citations[0]), `ATNI ${CITE.number}, WHEREAS ${CITE.position}, page ${CITE.page}`);
  assert.equal(citeFrom(out.citations[1]), `ATNI ${CITE.number}, WHEREAS ${CITE.position}, page unknown`);
  assert.deepEqual(out.whereas[3].marks, [{ start: 0, end: CITE.text.length }]);
  assert.ok(out.whereas[3].text.slice(0, CITE.text.length) === CITE.text, "the mark indexes the line text");
  assert.deepEqual(out.whereas[4].marks, [], "body() rewrote the text, so no mark");
  assert.deepEqual(out.whereas[0].marks, []);
  assert.deepEqual(compose(newDraft(2026)).citations, []);
});
