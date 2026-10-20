// The draft store (pages/draft.js) in Node, with an in-memory localStorage. Clause text is real published ATNI text
// (26-51, 2026 Annual Convention), as read from the database.
import test from "node:test";
import assert from "node:assert/strict";

const mem = new Map();
globalThis.localStorage = {
  getItem: k => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => { mem.set(k, String(v)); },
  removeItem: k => { mem.delete(k); },
};
const { store } = await import("../../pages/draft.js");
const { isStandard, STANDARD, compose } = await import("../../pages/compose.js");
const KEY = "resist-draft-v1";

const source = (statementType, index, text) => ({
  resolutionId: 409, number: "26-51", year: 2026, convention: "Annual Convention",
  title: "Supporting Responsible Governance of Youth Use of Artificial Intelligence Chatbots in Schools and Education",
  documentId: "5b62a9708e4081fd5baa676ba2ea0aae0c3dad1daf03f05dc4cab722fc193a91", statementType, index, text,
  url: "https://atnitribes.org/wp-content/uploads/2026/09/20260917_26-51_YOUTH%20USE%20OF%20ARTIFICIAL%20INTELLIGENCE%20CHATBOTS%20IN%20SCHOOLS.pdf",
});
const R0 = source("resolved", 0, "that ATNI urges both Tribal and Public Schools to exercise caution and establish strong " +
  "ethical safeguards governing the use of artificial intelligence (AI) in Tribal educational systems; and");
const R3 = source("resolved", 3, "that ATNI urges State and Federal Governments to consult with Tribes in creating stronger " +
  "safeguards to protect American Indian/ Alaska Native youth from potential harms associated with the use of AI in schools; and");
const W3 = source("whereas", 3, "the ATNI Youth Committee expresses concern that overreliance on artificial intelligence " +
  "(AI) in education may negatively affect critical thinking, creativity, writing, AFFILIATED TRIBES OF NORTHWEST " +
  "INDIANS RESOLUTION #2026 – 051 2026 ANNUAL CONVENTION PAGE 2 motor skills, learning strategies, traditional " +
  "teaching practices, cultural transmission, language revitalization, and relationships with Indigenous knowledge " +
  "keepers, educators, parents, and Elders; and");
const key = s => `${s.documentId}:${s.statementType}:${s.index}`;

test("carry places WHEREAS last and RESOLVED before the standard closing, once", () => {
  store.reset();
  let seen = 0;
  const off = store.subscribe(() => { seen++; });
  const w = store.carry(W3);
  assert.equal(store.draft.whereas.at(-1), w);
  assert.equal(w.origin, "carried");
  assert.equal(w.source.text, W3.text, "provenance keeps the stored text exactly");
  store.carry(R0);
  store.carry(R3);
  const texts = store.draft.resolved.map(c => c.text);
  assert.ok(texts[0].startsWith("that ATNI urges both Tribal"));
  assert.ok(texts[1].startsWith("that ATNI urges State and Federal"));
  assert.ok(isStandard(texts.at(-1)), "the closing stays last");
  assert.equal(store.carry(R0), null, "a second carry of the same clause is refused");
  assert.equal(store.carriedCount(), 3);
  assert.ok(store.isCarried(key(R3)));
  assert.equal(seen, 3);
  off();
});

test("RESOLVED carries go before the whole closing run, NCAI transmittal included", () => {
  store.reset();
  store.update(d => { d.resolved.unshift({ id: "x", text: STANDARD.ncai, origin: "standard" }); });
  store.carry(R0);
  assert.equal(store.draft.resolved[0].source?.index, 0);
  assert.equal(store.draft.resolved.length, 3);
});

test("uncarry removes only that clause", () => {
  store.reset();
  store.carry(R0); store.carry(W3);
  store.uncarry(key(R0));
  assert.equal(store.carriedCount(), 1);
  assert.ok(!store.isCarried(key(R0)));
  assert.ok(store.isCarried(key(W3)));
});

test("every change is saved and a reload restores it; bad storage falls back to a new draft", async () => {
  store.reset();
  store.carry(R3);
  store.update(d => { d.title = "Test title"; });
  const savedDraft = JSON.parse(mem.get(KEY));
  assert.equal(savedDraft.title, "Test title");
  const again = await import("../../pages/draft.js?reload=1");
  assert.equal(again.store.draft.title, "Test title");
  assert.equal(again.store.carriedCount(), 1);
  mem.set(KEY, "{not json");
  const fresh = await import("../../pages/draft.js?reload=2");
  assert.equal(fresh.store.draft.schema, "resist-draft/1");
  assert.equal(fresh.store.carriedCount(), 0);
  mem.set(KEY, JSON.stringify({ schema: "resist-draft/1", whereas: [{ id: 1 }], resolved: [] }));
  const rejected = await import("../../pages/draft.js?reload=3");
  assert.equal(rejected.store.draft.whereas.length, 3, "an invalid stored draft is replaced by newDraft()");
});

test("replace validates; addNote and reset", () => {
  store.reset();
  assert.equal(store.replace({ schema: "other" }), false);
  const copy = JSON.parse(JSON.stringify(store.draft));
  copy.title = "Opened from a file";
  assert.equal(store.replace(copy), true);
  assert.equal(store.draft.title, "Opened from a file");
  store.addNote({ id: "n1", title: "A policy", issues: [] });
  assert.equal(store.draft.notes.length, 1);
  store.reset();
  assert.equal(store.draft.title, "");
  assert.equal(store.draft.notes.length, 0);
});

test("own toString/valueOf keys in a stored draft cannot break the draft view", async () => {
  store.reset();
  const d = JSON.parse(mem.get(KEY));
  d.title = { toString: 0 };
  d.header.number = { toString: 1, valueOf: 1 };
  mem.set(KEY, JSON.stringify(d));
  const again = await import("../../pages/draft.js?reload=4");
  assert.doesNotThrow(() => compose(again.store.draft));
});

test("provenance comes from the database: a forged label is corrected, unknown text becomes typed", () => {
  globalThis.document ??= { getElementById: () => null };   // toast() has no page here
  store.reset();
  store.carry(R0); store.carry(W3);
  const db = [R0, W3];
  const lookup = c => db.find(s => s.documentId === c?.documentId && s.statementType === c?.statementType &&
    s.text === c?.text) ?? null;
  store.verifyWith(lookup);
  assert.equal(store.carriedCount(), 2, "genuine carries are unchanged");
  const forged = JSON.parse(JSON.stringify(store.draft));
  forged.resolved[0].source.number = "23-40";
  forged.whereas.at(-1).source.text = "the moon is made of cheese";
  forged.whereas[0].text = "that ATNI opposes every federal consultation policy";   // still labelled "standard"
  assert.equal(store.replace(forged), true);
  assert.equal(store.draft.resolved[0].source.number, "26-51");
  assert.equal(store.draft.whereas.at(-1).origin, "typed");
  assert.equal(store.draft.whereas.at(-1).source, undefined);
  assert.equal(store.draft.whereas[0].origin, "typed");
  assert.equal(store.carriedCount(), 1);
  store.verifyWith(null);
});
