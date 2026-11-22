// The Research collection (pages/collect.js, D-078) in Node with an in-memory localStorage and a stub storage-event
// target. Clause text is real published ATNI text (26-51, 2026 Annual Convention) from docx-fixtures.mjs. Comparisons
// are folded to booleans, so a failure prints no clause or title.
import test from "node:test";
import assert from "node:assert/strict";

const mem = new Map();
let failSet = false;
globalThis.localStorage = {
  getItem: k => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => { if (failSet) throw new Error("blocked"); mem.set(k, String(v)); },
  removeItem: k => { mem.delete(k); },
};
const listeners = [];
globalThis.addEventListener = (type, fn) => { if (type === "storage") listeners.push(fn); };
const fire = key => listeners.forEach(fn => fn({ key }));

const C = await import("../../pages/collect.js");
const { collection, KEY, SCHEMA, MAX_ITEMS } = C;
const { R2651, STATEMENTS } = await import("./docx-fixtures.mjs");
const { store } = await import("../../pages/draft.js");

// A Q.resolution() row and a Q.statements() row, the shapes the page passes in.
const ROW = { id: R2651.resolutionId, document_id: R2651.documentId, resolution_number: R2651.number, title: R2651.title,
  convention_name: R2651.convention, convention_year: R2651.year };
const stRow = ([t, i, text], p = 2) => ({ id: 1, t, i, text, p });
const W3 = C.statementItem(ROW, stRow(STATEMENTS[0]), R2651.url);
const R0 = C.statementItem(ROW, stRow(STATEMENTS[1]), R2651.url);
const RES = C.resolutionItem(ROW, R2651.url);
const reset = () => { mem.clear(); failSet = false; fire(KEY); };
const json = x => JSON.stringify(x);

test("independent tabs preserve interleaved additions and removals before storage events arrive", async () => {
  reset();
  const a = await import("../../pages/collect.js?tab=a"), b = await import("../../pages/collect.js?tab=b");
  const previous = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  let queue = Promise.resolve();
  const locks = { request: (_key, fn) => (queue = queue.then(fn)) };
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: { locks } });
  try {
    await Promise.all([a.changeCollection(() => a.collection.add(W3)), b.changeCollection(() => b.collection.add(R0))]);
    await Promise.all([a.changeCollection(() => a.collection.remove(C.itemKey(W3))), b.changeCollection(() => b.collection.add(RES))]);
    assert.deepEqual(JSON.parse(mem.get(KEY)).items.map(C.itemKey), [R0, RES].map(C.itemKey));
  } finally {
    if (previous) Object.defineProperty(globalThis, "navigator", previous);
    else delete globalThis.navigator;
    reset();
  }
});

test("keys: a resolution is its SHA-256, a statement is the draft's carry key", () => {
  assert.equal(C.itemKey(RES), R2651.documentId);
  assert.equal(C.itemKey(W3), `${R2651.documentId}:whereas:3`);
  assert.equal(C.itemKey(R0), `${R2651.documentId}:resolved:0`);
  reset(); store.reset();
  const carried = store.carry(C.draftSource(W3));
  assert.equal(`${carried.source.documentId}:${carried.source.statementType}:${carried.source.index}`, C.itemKey(W3),
    "one key means one clause in both stores");
  store.reset();
});

test("resolutionItem and statementItem carry exactly the documented fields", () => {
  assert.deepEqual(Object.keys(RES), ["kind", "resolutionId", "number", "title", "year", "convention", "documentId", "url"]);
  assert.deepEqual(Object.keys(W3), ["kind", "resolutionId", "number", "title", "year", "convention", "documentId",
    "statementType", "index", "page", "text", "url"]);
  assert.ok(W3.text === STATEMENTS[0][2] && W3.statementType === "whereas" && W3.index === 3 && W3.page === 2);
  assert.equal(C.statementItem(ROW, stRow(STATEMENTS[0], null), "").page, null);
  assert.equal(C.statementItem(ROW, { ...stRow(STATEMENTS[0]), p: undefined }, undefined).page, null);
  assert.equal(C.statementItem(ROW, stRow(STATEMENTS[0]), undefined).url, "");
  assert.deepEqual(Object.keys(C.draftSource(W3)), ["resolutionId", "number", "title", "year", "convention", "documentId",
    "statementType", "index", "text", "url"]);
  assert.ok(C.draftSource(W3).text === W3.text);
  assert.equal(C.draftSource(RES), null);
  assert.equal(C.itemLabel(RES), "resolution 26-51");
  assert.equal(C.itemLabel(W3), "WHEREAS 4 of resolution 26-51");
  assert.equal(C.itemLabel(R0), "RESOLVED 1 of resolution 26-51");
});

test("validCollection keeps good items and drops each kind of bad one", () => {
  const bad = [
    { ...W3, kind: "note" }, { ...W3, documentId: "G".repeat(64) }, { ...W3, documentId: "a".repeat(63) },
    { ...W3, statementType: "toString" }, { ...W3, statementType: "other" }, { ...W3, index: -1 }, { ...W3, index: 1.5 },
    { ...W3, page: 0 }, { ...W3, page: 2.5 }, { ...W3, page: undefined }, { ...W3, text: "" }, { ...W3, text: "   " },
    { ...W3, text: 7 }, { ...W3, url: "javascript:alert(1)" }, { ...W3, url: "http://atnitribes.org/x.pdf" },
    { ...W3, url: undefined }, { ...W3, resolutionId: 0 }, { ...W3, resolutionId: "409" },
    { ...RES, url: "data:text/html,x" }, null, 7, "x", [],
  ];
  const got = C.validCollection({ schema: SCHEMA, items: [RES, W3, ...bad, W3, { ...W3, text: "another copy" }, R0] });
  assert.equal(got.schema, SCHEMA);
  assert.ok(json(got.items) === json([RES, W3, R0]), "good items kept in order; the duplicate key is dropped");
  assert.ok(json(C.validCollection({ schema: SCHEMA, items: [{ ...W3, url: "" }] }).items) === json([{ ...W3, url: "" }]),
    "an empty url is allowed");
  assert.ok(json(C.validCollection({ schema: SCHEMA, items: [{ ...W3, page: null }] }).items) === json([{ ...W3, page: null }]));
  assert.equal(C.validCollection({ schema: SCHEMA }).items.length, 0);
  for (const other of [null, undefined, 7, "x", {}, { schema: "resist-research/2", items: [W3] }, { items: [W3] }]) {
    assert.equal(C.validCollection(other), null);
  }
  const many = Array.from({ length: MAX_ITEMS + 5 }, (_, i) => ({ ...R0, index: i }));
  assert.equal(C.validCollection({ schema: SCHEMA, items: many }).items.length, MAX_ITEMS);
});

test("a stored collection with own toString and valueOf keys loads without throwing", () => {
  const raw = `{"schema":"${SCHEMA}","toString":"x","items":[${json({ ...W3, toString: "x", valueOf: 1 })},` +
    `${json({ ...RES, title: { toString: "x" } })}]}`;
  mem.set(KEY, raw); fire(KEY);
  assert.equal(collection.count(), 2);
  assert.ok(collection.items.every(i => typeof i.title === "string"));
  assert.ok(!collection.items.some(i => Object.hasOwn(i, "toString")));
  reset();
});

test("add reports added, duplicate, invalid and full; the saved string reads back; the draft is untouched", () => {
  reset();
  const draftBefore = mem.get("resist-draft-v1") ?? null;
  assert.equal(collection.add(W3), "added");
  assert.equal(collection.add({ ...W3, text: "another copy" }), "duplicate");
  assert.equal(collection.add({ ...W3, index: -1 }), "invalid");
  assert.equal(collection.add(null), "invalid");
  assert.equal(collection.add({ ...W3, documentId: [W3.documentId] }), "invalid", "an array is not a document id");
  assert.equal(collection.add(RES), "added");
  assert.deepEqual([collection.count(), collection.has(C.itemKey(W3)), collection.has("nope")], [2, true, false]);
  assert.equal(collection.saved.ok, true);
  assert.ok(json(C.validCollection(JSON.parse(mem.get(KEY))).items) === json(collection.items), "saved items read back the same");
  assert.equal(mem.get("resist-draft-v1") ?? null, draftBefore, "nothing is written to the draft's key");
  reset();
  for (let i = 0; i < MAX_ITEMS; i++) assert.equal(collection.add({ ...R0, index: i }), "added");
  assert.equal(collection.add({ ...R0, index: MAX_ITEMS }), "full");
  assert.equal(collection.add({ ...R0, index: 0 }), "duplicate");
  assert.equal(collection.count(), MAX_ITEMS);
  assert.equal(JSON.parse(mem.get(KEY)).items.length, MAX_ITEMS);
  reset();
});

test("a stored item is a copy: changing the caller's object later changes nothing", () => {
  reset();
  const mine = { ...W3 };
  collection.add(mine);
  mine.text = "changed"; mine.index = 99;
  assert.ok(collection.items[0].text === W3.text && collection.items[0].index === 3);
  reset();
});

test("remove returns the item and its place; restore puts it back there; subscribe fires once per change", () => {
  reset();
  collection.add(RES); collection.add(W3); collection.add(R0);
  let seen = 0, last = null;
  const off = collection.subscribe(items => { seen++; last = items; });
  assert.equal(collection.remove("nope"), null);
  assert.equal(seen, 0);
  const gone = collection.remove(C.itemKey(W3));
  assert.deepEqual([gone.index, json(gone.item) === json(W3), collection.count(), seen], [1, true, 2, 1]);
  assert.equal(last.length, 2);
  assert.equal(collection.restore(gone), true);
  assert.ok(json(collection.items.map(C.itemKey)) === json([RES, W3, R0].map(C.itemKey)), "back at its old position");
  assert.equal(seen, 2);
  assert.equal(collection.restore(gone), false, "a key already present is not restored twice");
  assert.equal(collection.restore({ item: { ...W3, index: -1 }, index: 0 }), false);
  const tail = collection.remove(C.itemKey(R0));
  collection.remove(C.itemKey(W3));
  assert.equal(collection.restore({ item: tail.item, index: 99 }), true, "an index past the end goes last");
  assert.equal(collection.items.at(-1).index, 0);
  off();
  collection.add(W3);
  assert.equal(seen, 5, "no call after unsubscribe");
  reset();
});

test("a storage event for the collection's key reloads and notifies; another key does nothing", () => {
  reset();
  collection.add(R0);
  let seen = 0;
  const off = collection.subscribe(() => { seen++; });
  mem.set(KEY, JSON.stringify({ schema: SCHEMA, items: [RES, W3] }));
  fire("resist-draft-v1");
  assert.deepEqual([collection.count(), seen], [1, 0]);
  fire(KEY);
  assert.deepEqual([collection.count(), seen], [2, 1]);
  assert.ok(collection.has(C.itemKey(RES)));
  mem.set(KEY, "{not json");
  fire(null);
  assert.equal(collection.count(), 0, "an unreadable copy is an empty collection");
  off();
  reset();
});

test("verifyWith replaces found items, removes the others, counts them and saves", () => {
  reset();
  collection.add(RES); collection.add(W3); collection.add(R0);
  const moved = { ...W3, resolutionId: 500, page: 3, url: "https://atnitribes.org/new.pdf" };
  const dropped = collection.verifyWith(item => (item.kind === "resolution" ? RES : C.itemKey(item) === C.itemKey(W3) ? moved : null));
  assert.equal(dropped, 1);
  assert.ok(json(collection.items) === json([RES, moved]));
  assert.ok(json(JSON.parse(mem.get(KEY)).items) === json([RES, moved]), "saved");
  let seen = 0;
  const off = collection.subscribe(() => { seen++; });
  assert.equal(collection.verifyWith(item => item), 0);
  assert.equal(seen, 0, "nothing changed, nothing notified");
  assert.equal(collection.verifyWith(() => ({ ...RES, documentId: "x" })), 2, "an invalid record counts as not found");
  assert.equal(collection.count(), 0);
  off();
  collection.add(RES); collection.add(W3);
  assert.equal(collection.verifyWith(() => RES), 1, "two items verified to one key leave one");
  reset();
});

test("a browser that keeps nothing still holds the item in memory and says so", () => {
  reset();
  failSet = true;
  assert.equal(collection.add(W3), "added");
  assert.equal(collection.count(), 1);
  assert.equal(collection.saved.ok, false);
  failSet = false;
  collection.add(RES);
  assert.equal(collection.saved.ok, true);
  reset();
});

test("collectionText is the golden text; collectionJson round-trips", () => {
  const sha = R2651.documentId, url = R2651.url;
  const head = "ATNI-ResIST research collection\n" +
    "Text is copied word for word from resolutions published by the Affiliated Tribes of Northwest Indians. " +
    "The source PDF governs. Nothing here is a summary, a finding or a legal conclusion.\n\n";
  const golden = head +
    `RESOLUTIONS (1)\n\n1. Resolution 26-51, 2026, Annual Convention\n   ${R2651.title}\n   Source PDF: ${url}\n\n` +
    `STATEMENTS (1)\n\n1. WHEREAS 4, Resolution 26-51, 2026, page 2\n   ${STATEMENTS[0][2]}\n   Source PDF: ${url}\n`;
  assert.ok(C.collectionText([RES, W3]) === golden, "one resolution and one statement");
  assert.ok(C.collectionText([W3, RES]) === golden, "sections keep their own order, resolutions first");

  const bare = { ...W3, page: null, url: "", text: "  two   spaces\nhere  " }, plain = { ...RES, convention: "", url: "", title: "a\n b" };
  assert.ok(C.collectionText([plain, bare, R0]) === head +
    `RESOLUTIONS (1)\n\n1. Resolution 26-51, 2026\n   a b\n\n` +
    `STATEMENTS (2)\n\n1. WHEREAS 4, Resolution 26-51, 2026, page unknown\n   two spaces here\n\n` +
    `2. RESOLVED 1, Resolution 26-51, 2026, page 2\n   ${STATEMENTS[1][2]}\n   Source PDF: ${url}\n`);
  assert.ok(C.collectionText([]) === head.slice(0, -1), "an empty collection is the heading and the notice");

  const text = C.collectionJson([RES, W3]);
  assert.ok(text.endsWith("\n") && text.startsWith("{\n  \"schema\""));
  assert.ok(json(C.validCollection(JSON.parse(text)).items) === json([RES, W3]));
});
