// pages/searched.js: the plain-words statement of what a search ran (D-078, RM-2). Pure string output from the result of
// broaden(); the issue is the grammar-test issue of tests/fixtures/query/broaden-vectors.json, never corpus data.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { broaden } from "../../pages/query.js";
import { searchedHTML } from "../../pages/searched.js";

const V = JSON.parse(readFileSync(new URL("../fixtures/query/broaden-vectors.json", import.meta.url), "utf8"));
const text = html => html.replace(/<[^>]+>/g, " ").replace(/&#39;/g, "'").replace(/\s+/g, " ").trim();
const lead = html => text(html.match(/<p id="searched-lead">(.*?)<\/p>/s)[1]);
const link = html => html.match(/<a id="search-mode" href="([^"]*)">(.*?)<\/a>/s)?.slice(1);

const typed = broaden("salmon 2019", V.issues);
const issue = broaden("Section 106", V.issues);
const exact = broaden("salmon 2019", V.issues, { exact: true });

test("the broad search lists each word as searched, with the link to the exact search", () => {
  const html = searchedHTML(typed, { hrefExact: "#/?q=salmon+2019&exact=1" });
  assert.equal(lead(html), "Searched: resolutions that contain all of these words.");
  assert.ok(text(html).includes("“salmon”, or a word that starts with it"));
  assert.ok(text(html).includes("“2019”, exactly"));
  assert.deepEqual(link(html), ["#/?q=salmon+2019&amp;exact=1", "Search only the exact words"]);
  assert.equal(link(searchedHTML(typed)), undefined, "no link when none is given");
});

test("an issue lists the added names and references, their basis, the issue, the reviewed date and the source", () => {
  const html = searchedHTML(issue, { hrefExact: "#/?q=Section+106&exact=1" });
  assert.equal(lead(html), "Searched: resolutions that contain “Section 106”, or any of the names and references below.");
  assert.equal((html.match(/<li>/g) ?? []).length, issue.issue.added.length);
  assert.ok(text(html).includes("Section 106 Compliance (a name people use)"));
  assert.ok(text(html).includes("NHPA (a name people use)"));
  assert.ok(text(html).includes("54 U.S.C. 306108 (a reference the issue rests on)"));
  assert.ok(text(html).includes("36 C.F.R. Part 800 (a reference the issue rests on)"));
  assert.ok(text(html).includes("These names and references come from Policy Sentinel's reviewed issue table, issue “Section 106 consultation”, reviewed 11/18/2026. They are not taken from the resolutions. Every result is a text match; none is a finding about a resolution."));
  assert.equal(link(html)[1], "Search only the words I typed");
  const official = searchedHTML(broaden("Section 106 Compliance", V.issues));
  assert.ok(text(official).includes("Section 106 (an official name)"));
  assert.ok(!/NHPA \(an official name\)|Compliance \(an official name\)/.test(text(searchedHTML(issue))), "a name people use is never called official");
});

test("the exact search says so, lists the words as typed and offers the broad search only when given", () => {
  const html = searchedHTML(exact, { exact: true, hrefBroad: "#/?q=salmon+2019" });
  assert.equal(lead(html), "Searched exactly: resolutions that contain every one of these words, as typed.");
  assert.ok(text(html).includes("“salmon”") && text(html).includes("“2019”"));
  assert.ok(!text(html).includes("starts with it"));
  assert.deepEqual(link(html), ["#/?q=salmon+2019", "Search with longer words and issue names"]);
  assert.equal(link(searchedHTML(exact, { exact: true })), undefined);
});

test("nothing is searched, nothing is said", () => {
  assert.equal(searchedHTML(broaden("", V.issues)), "");
  assert.equal(searchedHTML(broaden("   ", V.issues), { exact: true }), "");
});

test("no output says what a resolution is about or asserts a conflict (D14)", () => {
  const banned = /\b(about|deals? with|relates? to|regarding|concerns?|conflicts?|contradicts?|summar\w+)\b/i;
  const cases = [searchedHTML(typed, { hrefExact: "#x" }), searchedHTML(issue, { hrefExact: "#x" }), searchedHTML(exact, { exact: true, hrefBroad: "#x" }),
    searchedHTML(broaden("Section 106 Compliance", V.issues)), searchedHTML(broaden("NHPA", V.issues))];
  // The one fixed denial in the issue provenance sentence ("none is a finding about a resolution") is the only allowed use.
  for (const [n, html] of cases.entries()) assert.ok(!banned.test(text(html).replace("none is a finding about a resolution", "")), `case ${n}`);
  assert.match(text(cases[1]), /text match/);
});

test("typed words, issue labels and phrases are escaped", () => {
  const html = searchedHTML(broaden("<b>x</b> a&b", V.issues), { hrefExact: '#/?q="><script>' });
  assert.ok(!html.includes("<b>") && !html.includes("<script>"));
  assert.ok(html.includes("&lt;b&gt;x&lt;/b&gt;") && html.includes("a&amp;b"));
  const hostile = { match: "m", words: [{ text: "x", prefix: false }],
    issue: { id: "i", label: "A <i>label</i>", reviewedOn: "2026-01-02", added: [{ text: "<u>phrase</u>", from: "name:official" }] } };
  const out = searchedHTML(hostile);
  assert.ok(!out.includes("<i>") && !out.includes("<u>"));
  assert.ok(out.includes("&lt;i&gt;label&lt;/i&gt;") && out.includes("&lt;u&gt;phrase&lt;/u&gt;") && out.includes("reviewed 01/02/2026"));
});
