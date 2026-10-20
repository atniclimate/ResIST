// pages/query.js: the one query grammar (shared vectors with tests/test_query_vectors.py) and the wasm adapter's
// guards. A fake exec records SQL and bind values. The last test runs every export against a real site database
// (node:sqlite, read-only) that tests/test_query_vectors.py builds from two real fixtures and names in
// RESIST_QUERY_DB; it skips without one. Assertions there check counts, ids and shapes, never corpus text.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as Q from "../../pages/query.js";

const V = JSON.parse(readFileSync(new URL("../fixtures/query/fts-match-vectors.json", import.meta.url), "utf8"));
const CAPS = { index: Q.INDEX }, BUILT = { fts_tokenize: Q.INDEX.tokenizer };
const recorder = () => {
  const calls = [];
  const exec = (sql, bind) => { calls.push({ sql, bind }); return []; };
  return { calls, exec };
};

test("ftsMatch agrees with every shared vector", () => {
  for (const v of V.vectors) assert.equal(Q.ftsMatch(v.q), v.match, JSON.stringify(v.q));
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
      "convention_year", "id", "needs_review", "resolution_number", "snip", "title"]);
    assert.ok(rows.every(r => r.snip === null), "no snippet without a match");
    assert.deepEqual(Q.search(all, { sort: "old", limit: 25, offset: 0 }).map(r => r.id).sort(), rows.map(r => r.id).sort());
    assert.equal(Q.search(all, { sort: "new", limit: 25, offset: n }).length, 0);

    // "Tribes" is in the issuer's own name, Affiliated Tribes of Northwest Indians: an operator word, not clause text.
    const f = { ...all, match: Q.ftsMatch("Tribes") };
    const hits = Q.search(f, { sort: "best", limit: 25, offset: 0 });
    assert.ok(hits.length > 0 && hits.length === Q.searchTotal(f), "a full-text match finds and counts the same rows");
    assert.ok(hits.every(r => typeof r.snip === "string" && r.snip.includes("\x02")), "snippet marks the match");

    for (const y of Q.yearCounts(all).keys()) {
      if (y != null) assert.equal(Q.searchTotal({ ...all, year: y }), Q.yearCounts(all).get(y));
    }
    let dated = 0;
    for (const { id } of rows) {
      const r = Q.resolution(id);
      assert.ok(r && r.id === id && /^[0-9a-f]{64}$/.test(r.document_id), "resolution by id carries its SHA-256");
      assert.deepEqual(Object.keys(r).sort(), ["convention_location", "convention_name", "convention_year", "date_adopted",
        "document_id", "full_text", "id", "needs_review", "resolution_number", "title"]);
      if (r.date_adopted != null) dated++;
      if (r.convention_name) assert.ok(Q.searchTotal({ ...all, convention: r.convention_name }) >= 1, "convention filter");
      const st = Q.statements(id);
      assert.ok(st.every((s, i) => i === 0 || st[i - 1].i <= s.i), "statements in index order");
      if (st.length) {
        const same = Q.storedStatements(st[0].t, st[0].text, r.document_id);
        assert.ok(same.some(s => s.resolution_id === id), "storedStatements finds the stored clause");
      }
      assert.ok(Array.isArray(Q.citations(id)) && Q.citedBy(id).every(c => c.id !== id), "citations and cited-by");
      for (const c of Q.committeesOf(id)) assert.ok(Q.searchTotal({ ...all, committee: c }) >= 1, "committee filter");
      const urls = Q.sourceUrls(r.document_id);
      assert.ok(urls.length >= 1 && urls[0].startsWith("tests/fixtures/atni/"), "the atni-table url comes first");
    }
    if (n <= 25) assert.equal(Q.datedCount(), dated); // rows held every resolution
  } finally {
    db.close();
  }
});
