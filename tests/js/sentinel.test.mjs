// Run by tests/test_pages_js.py (node --test). Fixtures are trimmed copies of real responses from the Policy Sentinel
// public demo (federal-register source, recorded 2026-10-19); they hold public Federal Register metadata only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  ApiFailure, FEDERAL_TYPES, MAX_BYTES, SENTINEL_HOME, SOURCES, citationValue, lookupWords, noteFromPolicy,
  officialUrl, policyId, policyValue, readPolicy, searchPolicies, searchValue,
} from "../../pages/sentinel.js";

const fixture = name => JSON.parse(readFileSync(new URL(`../fixtures/sentinel/${name}`, import.meta.url), "utf8"));
const sources = fixture("sources.json");
const search = fixture("search-federal-register.json");
const policy = fixture("policy-2025-23880.json");
const clone = v => structuredClone(v);

test("lookupWords normalizes the four federal citation types", () => {
  assert.equal(lookupWords("E.O. 13175", "executive_order"), "Executive Order 13175");
  assert.equal(lookupWords("Executive Order No. 13,175 of November 6, 2000", "executive_order"), "Executive Order 13175");
  assert.equal(lookupWords("P.L. 93–638", "public_law"), "Public Law 93-638");
  assert.equal(lookupWords("Public Law 93-638, as amended", "public_law"), "Public Law 93-638");
  assert.equal(lookupWords("25 USC § 5301.", "usc"), "25 U.S.C. 5301");
  assert.equal(lookupWords("42 U.S.C. 2000bb-1(a)", "usc"), "42 U.S.C. 2000bb-1(a)");
  assert.equal(lookupWords("25 C.F.R. Part 900", "cfr"), "25 CFR 900");
});

test("lookupWords falls back to the squashed text and never exceeds 200 characters", () => {
  assert.equal(lookupWords("  the   Indian\nSelf-Determination Act. ", "other"), "the Indian Self-Determination Act");
  assert.equal(lookupWords("no number here", "executive_order"), "no number here");
  assert.equal(lookupWords(null, "usc"), "");
  const long = lookupWords("word ".repeat(100), "other");
  assert.ok(long.length <= 200);
  assert.ok(FEDERAL_TYPES.has("cfr") && !FEDERAL_TYPES.has("treaty"));
});

test("policyId reads the Federal Register document number", () => {
  assert.equal(policyId({ sourceId: "federal-register", identifier: "90 FR 60570 (FR Doc. 2025-23880)" }), "2025-23880");
  assert.equal(policyId({ sourceId: "federal-register", identifier: "no number" }), "no number");
  assert.equal(policyId({ sourceId: "congress", identifier: "H.R. 1234" }), "H.R. 1234");
});

test("the recorded source catalog still offers every source this panel lists", () => {
  const live = new Map(sources.sources.map(s => [s.id, s]));
  for (const s of SOURCES) {
    assert.ok(live.has(s.id), s.id);
    assert.equal(live.get(s.id).status, "live");
  }
  assert.equal(SOURCES[0].id, "federal-register");
});

test("recorded search and policy responses validate", () => {
  const found = searchValue(search, "federal-register", search.query);
  assert.equal(found.results.length, 5);
  assert.equal(found.total, 10000);
  const p = policyValue(policy, { source: "federal-register", id: "2025-23880" });
  assert.equal(p.issues.length, 5);
  assert.equal(p.engine.rulesVersion, "demo-rules-1.0.2");
  assert.equal(p.receipt.sha256.length, 64);
});

test("validation rejects malformed input", () => {
  const c = () => clone(search.results[0]);
  const reject = (mutate, check = citationValue) => {
    const v = c();
    mutate(v);
    assert.throws(() => check(v, "federal-register"), /Invalid/);
  };
  reject(v => { delete v.title; });
  reject(v => { v.title = "   "; });
  reject(v => { v.textAvailable = "yes"; });
  reject(v => { v.date = "2025-02-30"; });
  reject(v => { v.date = "12/29/2025"; });
  reject(v => { v.retrievedAt = "yesterday"; });
  reject(v => { v.sourceId = "govinfo"; });
  assert.throws(() => citationValue(null, "federal-register"), /Invalid/);
  assert.throws(() => citationValue([], "federal-register"), /Invalid/);
  const s = clone(search);
  s.query = "something else";
  assert.throws(() => searchValue(s, "federal-register", search.query), /Invalid/);
  const dup = clone(search);
  dup.results[1] = dup.results[0];
  assert.throws(() => searchValue(dup, "federal-register", search.query), /Invalid/);
  const many = clone(search);
  many.results = Array.from({ length: 11 }, (_, i) => ({ ...search.results[0], identifier: `id ${i}` }));
  assert.throws(() => searchValue(many, "federal-register", search.query), /Invalid/);
});

test("validation rejects oversized fields and lists", () => {
  const v = clone(search.results[0]);
  v.title = "x".repeat(4001);
  assert.throws(() => citationValue(v, "federal-register"), /Invalid/);
  const p = clone(policy);
  p.issues[0].quote = "q".repeat(4001);
  assert.throws(() => policyValue(p, { source: "federal-register", id: "2025-23880" }), /Invalid/);
  const q = clone(policy);
  q.issues = Array.from({ length: 101 }, (_, i) => ({ ...policy.issues[0], id: `status_signal-${i + 1}` }));
  assert.throws(() => policyValue(q, { source: "federal-register", id: "2025-23880" }), /Invalid/);
  const b = clone(policy);
  b.receipt.bytes = 1_500_001;
  assert.throws(() => policyValue(b, { source: "federal-register", id: "2025-23880" }), /Invalid/);
});

test("validation rejects non-https, off-host and decorated URLs", () => {
  const ok = "https://www.federalregister.gov/d/2025-23880";
  assert.equal(officialUrl(ok, "federal-register"), ok);
  for (const u of [
    "http://www.federalregister.gov/d/2025-23880",
    "javascript:alert(1)",
    "https://evil.example/d/2025-23880",
    "https://www.federalregister.gov.evil.example/d/1",
    `https://user:pw${"@"}www.federalregister.gov/d/1`, // credentials in the URL; built so no address-like text is tracked
    "https://www.federalregister.gov:8443/d/1",
    "https://www.federalregister.gov/d/1?next=https://evil.example",
    "https://www.federalregister.gov/d/1#frag",
    "https://www.federalregister.gov/d/1 https://evil.example",
    "//www.federalregister.gov/d/1",
    "",
  ]) assert.throws(() => officialUrl(u, "federal-register"), /Invalid/, u);
  assert.throws(() => officialUrl("https://www.govinfo.gov/x", "congress"), /Invalid/);
  const v = clone(search.results[0]);
  v.officialUrl = "http://www.federalregister.gov/d/2025-23880";
  assert.throws(() => citationValue(v, "federal-register"), /Invalid/);
});

test("policyValue rejects a response for a different policy or without readable text", () => {
  assert.throws(() => policyValue(policy, { source: "federal-register", id: "2024-06055" }), /Invalid/);
  const p = clone(policy);
  p.citation.textAvailable = false;
  assert.throws(() => policyValue(p, { source: "federal-register", id: "2025-23880" }), /Invalid/);
  const q = clone(policy);
  q.receipt.textUrl = "https://www.govinfo.gov/content/pkg/other.htm";
  assert.throws(() => policyValue(q, { source: "federal-register", id: "2025-23880" }), /Invalid/);
  const r = clone(policy);
  r.issues[1].type = "legal_conclusion";
  assert.throws(() => policyValue(r, { source: "federal-register", id: "2025-23880" }), /Invalid/);
  const s = clone(policy);
  s.issues[1].id = s.issues[0].id;
  assert.throws(() => policyValue(s, { source: "federal-register", id: "2025-23880" }), /Invalid/);
  const t = clone(policy);
  t.receipt.sha256 = "ABC";
  assert.throws(() => policyValue(t, { source: "federal-register", id: "2025-23880" }), /Invalid/);
});

test("noteFromPolicy produces the PolicyNote shape with only the chosen flags", () => {
  const p = policyValue(policy, { source: "federal-register", id: "2025-23880" });
  const ids = ["tribal_reference-1", "consultation_language-1"];
  const note = noteFromPolicy(p, ids, "  Check against our 2024 resolution.  ");
  assert.deepEqual(Object.keys(note).sort(), [
    "comment", "date", "id", "identifier", "issues", "issuingBody", "kind", "officialUrl", "receiptSha256",
    "retrievedAt", "rulesVersion", "sourceId", "textUrl", "title",
  ]);
  assert.match(note.id, /\S/);
  assert.equal(note.sourceId, "federal-register");
  assert.equal(note.identifier, "90 FR 60570 (FR Doc. 2025-23880)");
  assert.equal(note.date, "2025-12-29");
  assert.equal(note.officialUrl, "https://www.federalregister.gov/d/2025-23880");
  assert.equal(note.textUrl, p.receipt.textUrl);
  assert.equal(note.retrievedAt, p.receipt.retrievedAt);
  assert.equal(note.receiptSha256, p.receipt.sha256);
  assert.equal(note.rulesVersion, "demo-rules-1.0.2");
  assert.equal(note.comment, "Check against our 2024 resolution.");
  // Kept in the policy's own order, with exactly the fields of SPEC section 7.
  assert.deepEqual(note.issues.map(i => i.id), ["consultation_language-1", "tribal_reference-1"]);
  assert.deepEqual(Object.keys(note.issues[0]), ["id", "type", "label", "quote", "locator", "rule", "limits"]);
  assert.equal(noteFromPolicy(p, []).issues.length, 0);
  assert.equal(noteFromPolicy(p, []).comment, "");
  assert.notEqual(noteFromPolicy(p, []).id, noteFromPolicy(p, []).id);
});

test("noteFromPolicy works for a metadata-only source", () => {
  const citation = { ...search.results[0], sourceId: "govinfo", textAvailable: false, textUrl: null };
  const note = noteFromPolicy({ citation, receipt: null, engine: null, issues: [] }, ["anything"]);
  assert.deepEqual(note.issues, []);
  assert.equal(note.receiptSha256, "");
  assert.equal(note.rulesVersion, "");
  assert.equal(note.textUrl, "");
  assert.equal(note.retrievedAt, citation.retrievedAt);
});

// ---- Network behavior, with fetch stubbed ----
async function withFetch(fn, run) {
  const real = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), init }); return fn(String(url), init); };
  try { return await run(calls); } finally { globalThis.fetch = real; }
}
const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers });

test("searchPolicies sends only the source, the squashed words and the page", async () => {
  await withFetch(() => json(search), async calls => {
    const r = await searchPolicies("federal-register", "  Executive   Order 13175 ");
    assert.equal(r.results.length, 5);
    assert.equal(calls.length, 1);
    const u = new URL(calls[0].url);
    assert.equal(u.origin, "https://policy-sentinel-demo.atniclimate.workers.dev");
    assert.equal(u.pathname, "/api/search");
    assert.deepEqual([...u.searchParams.keys()].sort(), ["page", "q", "source"]);
    assert.equal(u.searchParams.get("q"), "Executive Order 13175");
    assert.deepEqual(Object.keys(calls[0].init.headers), ["Accept"]);
  });
});

test("searchPolicies refuses bad input before any request is made", async () => {
  await withFetch(() => assert.fail("no request expected"), async calls => {
    for (const [source, q] of [["federal-register", ""], ["federal-register", "a"], ["federal-register", "x".repeat(201)], ["washington", "HB 1100"], ["nope", "tribal"]]) {
      await assert.rejects(searchPolicies(source, q), e => e instanceof ApiFailure && e.kind === "input");
    }
    await assert.rejects(readPolicy("nope", "2025-23880"), e => e.kind === "input");
    assert.equal(calls.length, 0);
  });
});

test("readPolicy validates the response against the requested policy", async () => {
  await withFetch(() => json(policy), async calls => {
    const p = await readPolicy("federal-register", "2025-23880");
    assert.equal(p.issues.length, 5);
    assert.equal(new URL(calls[0].url).searchParams.get("id"), "2025-23880");
    await assert.rejects(readPolicy("federal-register", "2024-06055"), e => e.kind === "service");
  });
});

test("HTTP failures map to limited, source and service", async () => {
  const kind = async (fn, run = () => searchPolicies("federal-register", "tribal consultation")) =>
    withFetch(fn, async () => { try { await run(); } catch (e) { return e.kind; } return "none"; });
  assert.equal(await kind(() => json({ ok: false, error: "rate_limited", message: "Slow down." }, 429)), "limited");
  assert.equal(await kind(() => new Response("busy", { status: 429 })), "limited");
  assert.equal(await kind(() => json({ ok: false, error: "bad_query", message: "Try other words." }, 400)), "source");
  assert.equal(await kind(() => new Response("<html>bad gateway</html>", { status: 502 })), "service");
  assert.equal(await kind(() => { throw new TypeError("network down"); }), "service");
  assert.equal(await kind(() => json({ ok: true, results: "not a list" })), "service");
});

test("a response over 2 MB is refused, declared or streamed", async () => {
  const kind = fn => withFetch(fn, async () => { try { await searchPolicies("federal-register", "tribal"); } catch (e) { return e.kind; } return "none"; });
  assert.equal(await kind(() => new Response("{}", { headers: { "Content-Length": String(MAX_BYTES + 1) } })), "service");
  const big = JSON.stringify({ ok: true, pad: "x".repeat(MAX_BYTES + 10) });
  assert.equal(await kind(() => new Response(big)), "service");
});

test("an aborted request surfaces as a service failure", async () => {
  const ctl = new AbortController();
  await withFetch((url, init) => new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))), async () => {
    const pending = searchPolicies("federal-register", "tribal", ctl.signal);
    ctl.abort();
    await assert.rejects(pending, e => e.kind === "service");
  });
});

test("the Policy Sentinel home is an https address", () => {
  assert.match(SENTINEL_HOME, /^https:\/\//);
});
