// The Policy Sentinel seam (D-078, RM-3): the pinned copy of its reviewed issue table (pages/issues.json) read by the
// page's own code. Issue facts come only from the pin, text matches only from the published ATNI export, and a hit is a
// text match. The real-database tests read RESIST_QUERY_DB through node:sqlite (counts and ids only, never text);
// the Section 106 counts hold for one export, named by SHA-256, and are skipped for any other.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import * as Q from "../../pages/query.js";
import { verifyDatabase } from "../../pages/db.js";
import { searchedHTML } from "../../pages/searched.js";

const pinFile = readFileSync(new URL("../../pages/issues.json", import.meta.url), "utf8");
const issues = Q.issuesFrom(JSON.parse(pinFile));

test("a database must match its publication even when both use the same tokenizer", async () => {
  const previous = Uint8Array.of(1, 2, 3), current = Uint8Array.of(1, 2, 4);
  const manifest = { fts_tokenize: "porter", db_sha256: createHash("sha256").update(current).digest("hex") };
  await verifyDatabase(current, manifest);
  await assert.rejects(verifyDatabase(previous, manifest), /does not match build.json/);
});
const dbFile = process.env.RESIST_QUERY_DB;
// The published export the Section 106 counts were taken on (datapool/exchange/pages/build.json db_sha256, 2026-11-20).
const EXPORT_SHA = "41caf84cc4668218404eb428325dce9f5ca9265c7f3ff348107888e5c8ce6645";
const sameExport = Boolean(dbFile) && createHash("sha256").update(readFileSync(dbFile)).digest("hex") === EXPORT_SHA;

test("the pinned table loads whole and Section 106 expands to its names and references", () => {
  assert.equal(issues.length, 9);
  const b = Q.broaden("Section 106", issues);
  assert.equal(b.issue?.id, "section-106");
  assert.equal(b.issue.added.length, 8);
  assert.equal(b.issue.reviewedOn, "2026-11-18");
  assert.ok(b.match.startsWith('("Section" "106") OR '));
  const html = searchedHTML(b, { hrefExact: "#/?q=Section+106&exact=1" });
  assert.ok(html.includes("reviewed 11/18/2026"));
  assert.ok(html.includes("Policy Sentinel's reviewed issue table"));
});

test("an issue name inside a longer query is not expanded, and exact never is", () => {
  assert.equal(Q.broaden("Clean Water Act section 106", issues).issue, null);
  assert.equal(Q.broaden("Section 106 salmon", issues).issue, null);
  assert.equal(Q.broaden("Section 106", issues, { exact: true }).issue, null);
  assert.equal(Q.broaden("Section 106", []).issue, null, "an unavailable table adds nothing");
});

test("the pin carries its source, a SHA-256 and a reviewed date, and no workstation path", () => {
  const { source } = JSON.parse(pinFile);
  assert.equal(source.repo, "policy-sentinel");
  assert.match(source.file_sha256, /^[0-9a-f]{64}$/);
  assert.match(source.reviewed_on, /^\d{4}-\d{2}-\d{2}$/);
  assert.match(source.license, /^https:\/\/polyformproject\.org\/licenses\//); // Policy Sentinel's terms travel (D-080)
  assert.ok(source.notice.startsWith("Required Notice: "));
  assert.ok(!/\b[A-Za-z]:[\\/]/.test(pinFile), "no drive-letter path"); // \b: a web address is not a drive
});

function withDatabase(fn) {
  return async () => {
    const { DatabaseSync } = await import("node:sqlite");
    const db = new DatabaseSync(dbFile, { readOnly: true });
    try {
      Q.useDatabase((sql, bind) => db.prepare(sql).all(...bind), { index: Q.INDEX },
        { fts_tokenize: Q.INDEX.tokenizer, page_numbers: true, refs: { version: 1 } });
      const ids = match => new Set(Q.search({ match, convention: "", committee: "", year: "" }, { sort: "new", limit: 5000, offset: 0 }).map(r => r.id));
      await fn(ids);
    } finally {
      db.close();
    }
  };
}

test("every pinned issue label runs and finds at least what its typed words find",
  { skip: !dbFile && "RESIST_QUERY_DB is not set" }, withDatabase(ids => {
    for (const i of issues) {
      const narrow = ids(Q.broaden(i.label, issues, { exact: true }).match), wide = ids(Q.broaden(i.label, issues).match);
      assert.ok([...narrow].every(id => wide.has(id)), `issue ${i.id}: broad holds every exact result`);
    }
  }));

// 15 resolutions contain both words; the name "NHPA" adds two more (resolution ids 313 and 542 in this export);
// the reference spellings add none (G1 of the design). Counts taken 2026-11-20 on the 1,129-resolution export
// (finals only, D-080; before that the draft of 25-15, id 931, made it 18).
test("Section 106 on the published export: 15 exact, 17 with the pinned names, the two added are those NHPA finds",
  { skip: !sameExport && "export differs from the one these counts were taken on" }, withDatabase(ids => {
    const exact = ids(Q.broaden("Section 106", issues, { exact: true }).match), broad = ids(Q.broaden("Section 106", issues).match);
    assert.equal(exact.size, 15);
    assert.equal(broad.size, 17);
    const added = [...broad].filter(id => !exact.has(id)).sort((a, b) => a - b);
    assert.deepEqual(added, [313, 542]);
    assert.deepEqual([...ids('"NHPA"')].filter(id => !exact.has(id)).sort((a, b) => a - b), added);
    assert.ok([...exact].every(id => broad.has(id)));
  }));
