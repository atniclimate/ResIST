// pages/query.js: the one query grammar (shared vectors with tests/test_query_vectors.py) and the wasm adapter's
// guards. A fake exec records SQL and bind values. The last test runs every export against a real site database
// (node:sqlite, read-only) that tests/test_query_vectors.py builds from two real fixtures and names in
// RESIST_QUERY_DB; it skips without one. Assertions there check counts, ids and shapes, never corpus text.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as Q from "../../pages/query.js";

const V = JSON.parse(readFileSync(new URL("../fixtures/query/fts-match-vectors.json", import.meta.url), "utf8"));
const CAPS = { index: Q.INDEX }, BUILT = { fts_tokenize: Q.INDEX.tokenizer, page_numbers: true, refs: { version: 1 } };
const STALE = { fts_tokenize: Q.INDEX.tokenizer, page_numbers: true }; // an export built before the cite table (UI-2 D9)
const COLS = "id, sid, s0, s1, text, kind, src, l, n, tt".split(", ");
// The alias list of a select: the last word of each top-level item between "select" and the first "from".
const aliases = sql => sql.replace(/\s+/g, " ").match(/^\s*select (.*?) from /)[1].split(", ").map(x => x.split(" ").pop().split(".").pop());
const recorder = () => {
  const calls = [];
  const exec = (sql, bind) => { calls.push({ sql, bind }); return []; };
  return { calls, exec };
};

test("ftsMatch agrees with every shared vector", () => {
  for (const v of V.vectors) assert.equal(Q.ftsMatch(v.q), v.match, JSON.stringify(v.q));
});

// The broad grammar (D-078): tests/test_broaden_vectors.py runs the same file against resist.index.broaden.
const B = JSON.parse(readFileSync(new URL("../fixtures/query/broaden-vectors.json", import.meta.url), "utf8"));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b); // fold to a boolean so a failure prints no text

test("broaden agrees with every shared vector", () => {
  assert.equal(B.schema, "resist-broaden-vectors/1");
  assert.deepEqual({ ...Q.INDEX }, B.index);
  assert.equal(B.vectors.length, 27);
  B.vectors.forEach((v, n) => assert.ok(same(Q.broaden(v.q, B.issues, { exact: v.exact }), v.expected), `vector ${n}`));
});

test("broaden with exact reproduces ftsMatch, and its words are the typed words", () => {
  for (const [n, v] of V.vectors.entries()) {
    const b = Q.broaden(v.q, B.issues, { exact: true });
    assert.ok(b.match === v.match && b.match === Q.ftsMatch(v.q) && b.issue === null, `old vector ${n}`);
    assert.ok(b.words.every(w => w.prefix === false), `old vector ${n} words`);
  }
});

test("no typed character reaches FTS5 syntax", () => {
  for (const q of [...V.vectors, ...B.vectors].map(v => v.q)) {
    const m = Q.broaden(q, B.issues).match;
    assert.ok(/^(?:"[^"]*"\*?|\(| OR |\)|\s)*$/.test(m), "only quoted terms, parentheses and OR outside quotes");
  }
  const m = Q.broaden('NOT NEAR(a b) "x" c*', B.issues).match;
  assert.ok(m.split('"').filter((_, i) => i % 2 === 0).join("").replace(/[\s*]/g, "") === "", "typed operators stay inside quotes");
});

test("a broad match is one bound parameter", () => {
  const { calls, exec } = recorder();
  Q.useDatabase(exec, CAPS, BUILT);
  const { match } = Q.broaden("Section 106", B.issues);
  assert.ok(match.includes(" OR "));
  Q.search({ match, convention: "", committee: "", year: "" }, { sort: "best", limit: 25, offset: 0 });
  assert.equal(calls.length, 1);
  assert.ok(!/Section|NHPA|306108|CFR|OR "/.test(calls[0].sql), "the SQL holds no typed word, phrase or OR");
  assert.deepEqual(calls[0].bind, [match, 25, 0]);
});

test("search selects document_id; resolutionByDocument binds one parameter", () => {
  const { calls, exec } = recorder();
  Q.useDatabase(exec, CAPS, BUILT);
  Q.search({ match: "", convention: "", committee: "", year: "" }, { sort: "new", limit: 25, offset: 0 });
  assert.ok(/^\s*select r\.id, r\.document_id, r\.resolution_number, /.test(calls[0].sql) && !calls[0].sql.includes("*"));
  const doc = "ab".repeat(32);
  assert.equal(Q.resolutionByDocument(doc), null);
  assert.ok(!calls[1].sql.includes("*") && !calls[1].sql.includes(doc));
  assert.deepEqual(calls[1].bind, [doc]);
  Q.useDatabase(() => [{ id: 7 }], CAPS, BUILT);
  assert.equal(Q.resolutionByDocument(doc), 7);
});

test("issuesFrom accepts a well-formed file and refuses each damage", () => {
  const good = () => ({
    schema: "resist-issue-names/1",
    source: { repo: "policy-sentinel", path: "config/issues.v1.json", commit: "not tracked", commit_date: "2026-11-19",
      file_sha256: "a".repeat(64), reviewed_on: "2026-11-18", pinned_on: "2026-11-20", schema_version: "1.0.0" },
    expansions: structuredClone(B.issues),
  });
  const got = Q.issuesFrom(good());
  assert.equal(got.length, 3);
  assert.ok(same(got, B.issues), "the accepted copy keeps exactly the vectors' fields");
  const sha = good(); sha.source.commit = "b".repeat(40);
  assert.equal(Q.issuesFrom(sha).length, 3, "a 40-hex commit is accepted");
  const damage = [
    f => { f.schema = "resist-issue-names/2"; },
    f => { delete f.source.file_sha256; },
    f => { f.source.file_sha256 = "a".repeat(63); },
    f => { f.source.file_sha256 = "A".repeat(64); },
    f => { f.source.commit = "abc"; },
    f => { f.source.reviewed_on = "11/18/2026"; },
    f => { f.source.pinned_on = undefined; },
    f => { delete f.source; },
    f => { f.expansions = []; },
    f => { f.expansions = "x"; },
    f => { f.expansions[1].id = f.expansions[0].id; },
    f => { f.expansions[0].id = "Not Valid"; },
    f => { f.expansions[0].label = ""; },
    f => { f.expansions[0].reviewedOn = "2026-1-1"; },
    f => { f.expansions[0].phrases[0].text = "x"; },
    f => { f.expansions[0].phrases = Array.from({ length: 41 }, () => ({ text: "ab", from: "name:official" })); },
    f => { f.expansions[0].triggers[0] = 7; },
    f => { f.expansions[0].triggers = []; },
    f => { f.expansions[0].phrases[0].from = "name:official-ish"; },
    f => { f.expansions[0].phrases[1] = null; },
  ];
  damage.forEach((d, n) => { const f = good(); d(f); assert.ok(Q.issuesFrom(f).length === 0, `damage ${n}`); });
  for (const bad of [null, undefined, [], "x", 7, {}]) assert.equal(Q.issuesFrom(bad).length, 0);
});

test("INDEX is the vectors file's index manifest", () => {
  assert.deepEqual({ ...Q.INDEX }, V.index);
  Q.requireIndex(Q.INDEX);
});

test("requireIndex refuses a manifest it does not speak", () => {
  for (const bad of [{ ...Q.INDEX, tokenizer: "porter unicode61" }, { ...Q.INDEX, adapter: "other" },
    { ...Q.INDEX, version: "2" }, undefined]) {
    assert.throws(() => Q.requireIndex(bad), /index manifest not supported/);
  }
});

test("a refused manifest leaves no database open", () => {
  const { exec } = recorder();
  assert.throws(() => Q.useDatabase(exec, { index: { ...Q.INDEX, version: "2" } }, BUILT), /not supported/);
  assert.throws(() => Q.committees(), /database not open/);
  assert.throws(() => Q.useDatabase(exec, {}, BUILT), /not supported/);
  assert.throws(() => Q.committees(), /database not open/);
});

test("an export built with another tokenizer is refused even when capabilities match (local face, A5)", () => {
  const { exec } = recorder();
  for (const built of [{ fts_tokenize: "unicode61" }, {}, null, undefined]) {
    Q.useDatabase(exec, CAPS, BUILT);
    assert.throws(() => Q.useDatabase(exec, CAPS, built), /export tokenizer/);
    assert.throws(() => Q.committees(), /database not open/);
  }
});

test("search binds the match, limit and offset; SQL holds no user value", () => {
  const { calls, exec } = recorder();
  Q.useDatabase(exec, CAPS, BUILT);
  Q.search({ match: Q.ftsMatch("salmon"), convention: "", committee: "", year: "" }, { sort: "best", limit: 25, offset: 0 });
  assert.equal(calls.length, 1);
  assert.ok(!calls[0].sql.includes("salmon"));
  assert.deepEqual(calls[0].bind, ['"salmon"', 25, 0]);
});

test("search refuses an unknown sort, best without a match, and non-integer paging", () => {
  const { exec } = recorder();
  Q.useDatabase(exec, CAPS, BUILT);
  const f = { match: '"salmon"', convention: "", committee: "", year: "" };
  assert.throws(() => Q.search(f, { sort: "worst", limit: 25, offset: 0 }), /unsupported sort/);
  assert.throws(() => Q.search({ ...f, match: "" }, { sort: "best", limit: 25, offset: 0 }), /unsupported sort/);
  assert.throws(() => Q.search(f, { sort: "new", limit: 2.5, offset: 0 }), /non-negative integers/);
  assert.throws(() => Q.search(f, { sort: "new", limit: 25, offset: -1 }), /non-negative integers/);
  assert.throws(() => Q.search(f, { sort: "new", limit: "25", offset: 0 }), /non-negative integers/);
});

test("filters are bound parameters", () => {
  const { calls, exec } = recorder();
  Q.useDatabase(exec, CAPS, BUILT);
  Q.search({ match: "", convention: "Annual Convention", committee: "Some Committee", year: 2019 },
    { sort: "new", limit: 25, offset: 50 });
  assert.ok(!/Annual Convention|Some Committee|2019/.test(calls[0].sql));
  assert.deepEqual(calls[0].bind, ["Annual Convention", "Some Committee", 2019, 25, 50]);
});

test("resolution names its columns; sourceUrls keeps the build's order", () => {
  const { calls, exec } = recorder();
  Q.useDatabase(exec, CAPS, BUILT);
  assert.equal(Q.resolution(1), null);
  assert.ok(!calls[0].sql.includes("*"));
  assert.deepEqual(calls[0].bind, [1]);
  Q.sourceUrls("0".repeat(64));
  assert.ok(calls[1].sql.includes("order by rowid"));
});

test("statements selects page_number only when the export carries it", () => {
  const { calls, exec } = recorder();
  Q.useDatabase(exec, CAPS, BUILT);
  Q.statements(1);
  Q.useDatabase(exec, CAPS, { fts_tokenize: Q.INDEX.tokenizer }); // an export built before page_number (UI-1 D2)
  Q.statements(1);
  assert.equal(calls.length, 2);
  assert.ok(calls[0].sql.includes("page_number p"));
  assert.ok(calls[1].sql.includes("null p") && !calls[1].sql.includes("page_number"));
  for (const c of calls) {
    assert.deepEqual(c.bind, [1]);
    assert.ok(!c.sql.includes("*"));
    assert.deepEqual(aliases(c.sql), ["id", "t", "i", "text", "p"]);
  }
});

test("citations reads cite when the export has it, else the legacy table in the same shape", () => {
  const { calls, exec } = recorder();
  Q.useDatabase(exec, CAPS, BUILT);
  Q.citations(1);
  Q.useDatabase(exec, CAPS, STALE);
  Q.citations(1);
  assert.equal(calls.length, 2);
  assert.ok(calls[0].sql.includes("from cite"));
  assert.ok(calls[1].sql.includes("from citation") && !calls[1].sql.includes("cite c"));
  for (const c of calls) {
    assert.deepEqual(aliases(c.sql), COLS);
    assert.deepEqual(c.bind, [1]);
    assert.ok(!c.sql.includes("*"));
  }
});

test("citedBy and storedCite follow the export", () => {
  const { calls, exec } = recorder();
  Q.useDatabase(exec, CAPS, BUILT);
  Q.citedBy(1);
  assert.ok(calls[0].sql.includes("from cite c"));
  assert.equal(Q.storedCite("a", "whereas", 0, 1, 5), null);
  assert.deepEqual(calls[1].bind, ["a", "whereas", 0, 1, 5]);
  assert.ok(!calls[1].sql.includes("*") && !calls[1].sql.includes("'a'") && !calls[1].sql.includes("'whereas'"));
  for (const bad of [[-1, 1, 5], [0, 1.5, 5], [0, 1, "5"]]) {
    assert.throws(() => Q.storedCite("a", "whereas", ...bad), /non-negative integers/);
  }
  Q.useDatabase(exec, CAPS, STALE);
  const before = calls.length;
  Q.citedBy(1);
  assert.ok(calls[before].sql.includes("from citation c"));
  assert.equal(Q.storedCite("a", "whereas", 0, 1, 5), undefined);
  assert.equal(calls.length, before + 1, "no SQL without the cite table");
});

// Messages are fixed strings: a failure must not print a title, snippet or clause.
test("every export runs on a real built site database", { skip: !process.env.RESIST_QUERY_DB && "RESIST_QUERY_DB not set (tests/test_query_vectors.py sets it)" }, async () => {
  const { DatabaseSync } = await import("node:sqlite");
  const db = new DatabaseSync(process.env.RESIST_QUERY_DB, { readOnly: true });
  try {
    Q.useDatabase((sql, bind) => db.prepare(sql).all(...bind), CAPS, BUILT);
    const n = db.prepare("select count(*) n from resolution").get().n;
    const all = { match: "", convention: "", committee: "", year: "" };
    assert.ok(n > 0, "the built database holds resolutions");
    assert.ok(Array.isArray(Q.committees()), "committees");
    assert.equal(Q.searchTotal(all), n);
    assert.equal([...Q.yearCounts(all).values()].reduce((a, b) => a + b, 0), n);
    const rows = Q.search(all, { sort: "new", limit: 25, offset: 0 });
    assert.equal(rows.length, Math.min(n, 25));
    assert.deepEqual(Object.keys(rows[0]).sort(), ["committee", "convention_location", "convention_name",
      "convention_year", "document_id", "id", "needs_review", "resolution_number", "snip", "title"]);
    assert.ok(rows.every(r => /^[0-9a-f]{64}$/.test(r.document_id) && Q.resolutionByDocument(r.document_id) === r.id),
      "a result's document_id finds its resolution");
    assert.equal(Q.resolutionByDocument("0".repeat(64)), null);
    assert.ok(rows.every(r => r.snip === null), "no snippet without a match");
    if (n <= 25) { // a larger export has different first pages for new and old
      assert.deepEqual(Q.search(all, { sort: "old", limit: 25, offset: 0 }).map(r => r.id).sort(), rows.map(r => r.id).sort());
      assert.equal(Q.search(all, { sort: "new", limit: 25, offset: n }).length, 0);
    }

    // "Tribes" is in the issuer's own name, Affiliated Tribes of Northwest Indians: an operator word, not clause text.
    const f = { ...all, match: Q.ftsMatch("Tribes") };
    const hits = Q.search(f, { sort: "best", limit: 25, offset: 0 });
    assert.ok(hits.length > 0 && hits.length === Math.min(25, Q.searchTotal(f)), "a full-text match finds and counts the same rows");
    assert.ok(hits.every(r => typeof r.snip === "string" && r.snip.includes("\x02")), "snippet marks the match");

    for (const y of Q.yearCounts(all).keys()) {
      if (y != null) assert.equal(Q.searchTotal({ ...all, year: y }), Q.yearCounts(all).get(y));
    }
    let dated = 0, firstCite = null;
    for (const { id } of rows) {
      const r = Q.resolution(id);
      assert.ok(r && r.id === id && /^[0-9a-f]{64}$/.test(r.document_id), "resolution by id carries its SHA-256");
      assert.deepEqual(Object.keys(r).sort(), ["convention_location", "convention_name", "convention_year", "date_adopted",
        "document_id", "full_text", "id", "needs_review", "resolution_number", "title"]);
      if (r.date_adopted != null) dated++;
      if (r.convention_name) assert.ok(Q.searchTotal({ ...all, convention: r.convention_name }) >= 1, "convention filter");
      const st = Q.statements(id);
      assert.ok(st.every((s, i) => i === 0 || st[i - 1].i <= s.i), "statements in index order");
      assert.ok(st.every(s => Object.keys(s).sort().join() === "i,id,p,t,text"), "statement keys");
      assert.ok(st.every(s => s.p === null || (Number.isInteger(s.p) && s.p >= 1)), "page is null or a page number");
      if (st.length) {
        const same = Q.storedStatements(st[0].t, st[0].text, r.document_id);
        assert.ok(same.some(s => s.resolution_id === id), "storedStatements finds the stored clause");
      }
      const cites = Q.citations(id);
      assert.ok(cites.every(c => Object.keys(c).sort().join() === "id,kind,l,n,s0,s1,sid,src,text,tt"), "citation keys");
      for (const c of cites.filter(x => x.sid !== null)) {
        const s = st.find(x => x.id === c.sid);
        assert.ok(s && s.text.slice(c.s0, c.s1) === c.text, "cite slices its clause");
        if (!firstCite) firstCite = { r, s, c };
      }
      assert.ok(Q.citedBy(id).every(c => c.id !== id), "cited-by never lists the resolution itself");
      for (const c of Q.committeesOf(id)) assert.ok(Q.searchTotal({ ...all, committee: c }) >= 1, "committee filter");
      const urls = Q.sourceUrls(r.document_id);
      assert.ok(urls.length >= 1 && /^(tests\/fixtures\/atni\/|https:\/\/atnitribes\.org\/)/.test(urls[0]), "the atni-table url comes first");
    }
    if (n <= 25) assert.equal(Q.datedCount(), dated); // rows held every resolution
    assert.ok(firstCite, "the built export holds an anchored citation");
    const { r, s, c } = firstCite;
    const got = Q.storedCite(r.document_id, s.t, s.i, c.s0, c.s1);
    assert.ok(got && got.resolution_id === r.id && got.pos >= 1 && got.s0 === c.s0 && got.s1 === c.s1, "storedCite finds the row");
    assert.ok(got.text === c.text, "storedCite returns the stored text");
    assert.ok(Q.storedCite(r.document_id, s.t, s.i, c.s0, c.s1 + 1) === null, "another span is no stored citation");
  } finally {
    db.close();
  }
});

// A broad search finds at least what the exact search finds (RM-2), and every broad match string runs in SQLite
// (Node's own build here, not the vendored WASM, which the interface test covers). Counts and ids only.
test("every broad match runs and finds a superset of the exact search", { skip: !process.env.RESIST_QUERY_DB && "RESIST_QUERY_DB not set (tests/test_query_vectors.py sets it)" }, async () => {
  const { DatabaseSync } = await import("node:sqlite");
  const db = new DatabaseSync(process.env.RESIST_QUERY_DB, { readOnly: true });
  try {
    Q.useDatabase((sql, bind) => db.prepare(sql).all(...bind), CAPS, BUILT);
    const ids = match => new Set(Q.search({ match, convention: "", committee: "", year: "" },
      { sort: "new", limit: 5000, offset: 0 }).map(r => r.id));
    const queries = ["salmon", ...B.issues.map(i => i.label), ...B.vectors.filter(v => !v.exact).map(v => v.q)];
    for (const [n, q] of queries.entries()) {
      const broad = Q.broaden(q, B.issues).match;
      if (!broad) continue;
      const wide = ids(broad), narrow = ids(Q.broaden(q, B.issues, { exact: true }).match);
      assert.ok([...narrow].every(id => wide.has(id)), `query ${n}: broad holds every exact result`);
    }
  } finally {
    db.close();
  }
});
