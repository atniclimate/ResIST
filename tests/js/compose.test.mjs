// Run by tests/test_pages_js.py (node --test). Clause text is ATNI's published T0 wording (D-052), from 26-51.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  COMMITTEES, STANDARD, body, clauseState, compose, hasPageHeader, isStandard, lineText, newClause, newDraft,
  removePageHeader, resolvedLead, safeUrl, validDraft,
} from "../../pages/compose.js";

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
