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
const { isStandard, STANDARD, compose, newClause, newDraft } = await import("../../pages/compose.js");
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

test("replace({ quiet }) keeps the mismatch note for the caller instead of toasting it", () => {
  const say = announcer();
  try {
    store.reset();
    store.carry(R0);
    const forged = JSON.parse(JSON.stringify(store.draft));
    forged.resolved[0].source.text = "forged words";
    store.verifyWith(c => (c?.text === R0.text ? R0 : null));
    assert.ok(store.replace(forged, { quiet: true }) === true, "the draft opens");
    assert.ok(store.checkNote.includes("not match"), "the note is kept for the caller");
    assert.ok(say.count === 0, "the store announced nothing");
    assert.ok(store.replace(JSON.parse(JSON.stringify(store.draft)), { quiet: true }) === true, "the draft opens again");
    assert.ok(store.checkNote === "", "a clean draft leaves no note");
  } finally { store.verifyWith(null); say.restore(); }
});

test("remove keeps one undo that restores the same clause in place", () => {
  globalThis.document ??= { getElementById: () => null };
  store.reset();
  const w = store.carry(W3);
  const typedClause = newClause("typed words", "typed");
  store.update(d => { d.whereas.push(typedClause); });
  const index = store.draft.whereas.indexOf(w);
  const r = store.remove("whereas", w.id);
  assert.deepEqual(Object.keys(r).sort(), ["clause", "index", "kind"]);
  assert.equal(r.kind, "whereas");
  assert.equal(r.index, index);
  assert.equal(r.clause, w);
  assert.ok(!store.draft.whereas.includes(w));
  assert.ok(!JSON.parse(mem.get(KEY)).whereas.some(c => c.id === w.id), "the removal is saved");
  assert.equal(store.removed, r);
  const back = store.undo();
  assert.equal(back, w, "the same clause object comes back");
  assert.equal(back.origin, "carried");
  assert.equal(back.source.text, W3.text);
  assert.equal(store.draft.whereas.indexOf(w), index);
  assert.equal(store.removed, null);
  assert.equal(store.undo(), null, "one level only");
  assert.equal(store.remove("whereas", "no-such-id"), null);
  assert.equal(store.remove("header", w.id), null);
});

test("any other change clears the undo, and it is never saved", () => {
  store.reset();
  let w = store.carry(W3);
  store.remove("whereas", w.id);
  assert.deepEqual(Object.keys(JSON.parse(mem.get(KEY))).sort(), Object.keys(newDraft()).sort(), "no undo field is saved");
  store.update(d => { d.title = "t"; });
  assert.equal(store.undo(), null);
  w = store.carry(W3);
  store.remove("whereas", w.id);
  store.carry(R0);
  assert.equal(store.removed, null);
  w = store.draft.resolved.find(c => c.origin === "carried");
  store.remove("resolved", w.id);
  store.reset();
  assert.equal(store.removed, null);
});

test("a stored resist-draft/1 draft opens unchanged", async () => {
  store.reset();
  store.carry(R0); store.carry(W3);
  store.update(d => { d.whereas.push(newClause("typed words", "typed")); });
  const stored = mem.get(KEY);
  mem.set(KEY, stored);
  const again = await import("../../pages/draft.js?reload=undo1");
  assert.equal(again.store.draft.schema, "resist-draft/1");
  assert.ok(JSON.stringify(again.store.draft) === JSON.stringify(JSON.parse(stored)), "the draft opens unchanged");
  const db = [R0, W3];
  const lookup = c => db.find(s => s.documentId === c?.documentId && s.statementType === c?.statementType &&
    s.text === c?.text) ?? null;
  const setItem = globalThis.localStorage.setItem;
  let writes = 0;
  globalThis.localStorage.setItem = (k, v) => { writes++; setItem(k, v); };
  try {
    again.store.verifyWith(lookup);
  } finally {
    globalThis.localStorage.setItem = setItem;
    again.store.verifyWith(null);
  }
  assert.ok(JSON.stringify(again.store.draft) === JSON.stringify(JSON.parse(stored)), "the draft opens unchanged");
  assert.equal(writes, 0, "nothing was re-saved");
  assert.ok(mem.get(KEY) === stored, "the stored draft is untouched");
});

// Carried citations (UI-2, D-077). CITE_SOURCE is a real span of a stored clause (docx-fixtures.mjs). A second,
// distinct citation for the store is the same words claimed at another index (the store does not check the database).
const { CITE, CITE_SOURCE } = await import("./docx-fixtures.mjs");
const OTHER = { ...CITE_SOURCE, index: CITE_SOURCE.index + 1 };
const slices = c => (c.cites ?? []).every(x => c.text.slice(x.start, x.end) === x.text);
// Counts say() calls (each clears #announce first); toast() announces through say().
function announcer() {
  const was = globalThis.document, el = { n: 0, set textContent(v) { if (v === "") this.n++; } };
  globalThis.document = { getElementById: id => (id === "announce" ? el : null) };
  return { get count() { return el.n; }, restore() { globalThis.document = was; } };
}

test("carryCite inserts at the remembered insert point", () => {
  store.reset();
  const target = store.draft.whereas[0], k = target.text.length;
  store.setInsertPoint(target.id, k, k);
  assert.deepEqual(store.insertPoint, { id: target.id, kind: "whereas", index: 0, n: 3, label: "WHEREAS 1 of 3" });
  const r = store.carryCite(CITE_SOURCE);
  assert.deepEqual(r, { label: "WHEREAS 1 of 3", created: false, duplicate: false });
  assert.equal(target.cites.length, 1);
  assert.ok(slices(target), "the carried citation slices its clause");
  assert.equal(target.cites[0].start, k + 1, "one separating space before");
  assert.equal(target.origin, "typed", "standard text with a citation in it is typed");
  assert.equal(JSON.parse(mem.get(KEY)).whereas[0].cites.length, 1, "the saved draft holds it");
  assert.equal(store.citeCount(), 1);
  // The insert point moved past it: the next citation lands right after, with one space between.
  store.carryCite(OTHER);
  assert.equal(target.cites[1].start, target.cites[0].end + 1);
  assert.ok(slices(target), "both citations slice their clause");
  assert.equal(store.citeCount(), 2);
});

test("without an insert point carryCite starts a new typed WHEREAS, and at new does so with one present", () => {
  store.reset();
  assert.equal(store.insertPoint, null);
  const r = store.carryCite(CITE_SOURCE);
  assert.deepEqual(r, { label: "WHEREAS 4 of 4", created: true, duplicate: false });
  const c = store.draft.whereas.at(-1);
  assert.deepEqual(Object.keys(c), ["id", "text", "origin", "cites"]);
  assert.equal(c.origin, "typed");
  assert.ok(c.text === CITE.text, "the new clause holds exactly the citation");
  assert.deepEqual([c.cites[0].start, c.cites[0].end], [0, CITE.text.length]);
  assert.equal(store.insertPoint.label, "WHEREAS 4 of 4", "the insert point moved into the new clause");
  const again = store.carryCite(OTHER, { at: "new" });
  assert.deepEqual(again, { label: "WHEREAS 5 of 5", created: true, duplicate: false });
  assert.equal(store.carriedCount(), 0, "a citation does not count as a carried clause");
});

test("a removed insert-point clause falls back to a new WHEREAS; reset and replace clear the insert point", () => {
  store.reset();
  const typedClause = newClause("typed words", "typed");
  store.update(d => { d.whereas.push(typedClause); });
  store.setInsertPoint(typedClause.id, 2, 2);
  assert.equal(store.insertPoint.label, "WHEREAS 4 of 4");
  store.remove("whereas", typedClause.id);
  assert.equal(store.insertPoint, null);
  assert.equal(store.carryCite(CITE_SOURCE).created, true);
  assert.ok(store.insertPoint);
  store.reset();
  assert.equal(store.insertPoint, null);
  store.carryCite(CITE_SOURCE);
  assert.ok(store.insertPoint);
  assert.equal(store.replace(JSON.parse(JSON.stringify(store.draft))), true);
  assert.equal(store.insertPoint, null);
  store.setInsertPoint(store.draft.whereas[0].id, 0, 0);
  store.clearInsertPoint();
  assert.equal(store.insertPoint, null);
});

test("the same citation twice in one clause is refused", () => {
  store.reset();
  store.carryCite(CITE_SOURCE);
  const before = JSON.stringify(store.draft), saved = mem.get(KEY);
  let seen = 0;
  const off = store.subscribe(() => { seen++; });
  const r = store.carryCite({ ...CITE_SOURCE });
  off();
  assert.deepEqual(r, { label: "WHEREAS 4 of 4", created: false, duplicate: true });
  assert.equal(JSON.stringify(store.draft), before, "the draft is unchanged");
  assert.equal(mem.get(KEY), saved, "nothing was saved");
  assert.equal(seen, 0, "nobody was told");
  assert.equal(store.carryCite({ ...CITE_SOURCE }, { at: "new" }).created, true, "a new clause may hold it again");
});

test("verifyWith checks carried citations", () => {
  const say = announcer();
  try {
    store.reset();
    store.carryCite(CITE_SOURCE);
    const saved = mem.get(KEY);
    const setItem = globalThis.localStorage.setItem;
    let writes = 0;
    globalThis.localStorage.setItem = (k, v) => { writes++; setItem(k, v); };
    try { store.verifyWith(null, () => ({ ...CITE_SOURCE })); } finally { globalThis.localStorage.setItem = setItem; }
    assert.equal(writes, 0, "a matching database record changes nothing");
    assert.ok(mem.get(KEY) === saved, "the stored draft is untouched");
    store.verifyWith(null, () => undefined);
    assert.equal(store.citeCount(), 1, "an export that cannot check leaves the citation");
    assert.equal(say.count, 0);
    // The database corrects forged provenance.
    store.draft.whereas.at(-1).cites[0].source.number = "23-40";
    store.verifyWith(null, () => ({ ...CITE_SOURCE }));
    assert.equal(store.draft.whereas.at(-1).cites[0].source.number, CITE_SOURCE.number);
    store.verifyWith(null, () => null);
    const c = store.draft.whereas.at(-1);
    assert.equal(store.citeCount(), 0, "a citation the database does not hold loses its mark");
    assert.ok(!("cites" in c));
    assert.ok(c.text === CITE.text, "its words stay");
    assert.equal(c.origin, "typed");
    assert.equal(say.count, 1, "one announcement");
    assert.ok(!JSON.parse(mem.get(KEY)).whereas.at(-1).cites, "the change is saved");
  } finally { store.verifyWith(null); say.restore(); }
});

test("a stored draft with carried citations opens unchanged", async () => {
  store.reset();
  store.carry(R0);
  const k = store.draft.whereas[0].text.length;
  store.setInsertPoint(store.draft.whereas[0].id, k, k);
  store.carryCite(CITE_SOURCE);
  store.carryCite(OTHER, { at: "new" });
  const stored = mem.get(KEY);
  const again = await import("../../pages/draft.js?reload=cites1");
  assert.ok(JSON.stringify(again.store.draft) === JSON.stringify(JSON.parse(stored)), "the draft opens unchanged");
  assert.equal(again.store.citeCount(), 2);
  assert.equal(again.store.insertPoint, null, "the insert point is never saved");
  const setItem = globalThis.localStorage.setItem;
  let writes = 0;
  globalThis.localStorage.setItem = (k, v) => { writes++; setItem(k, v); };
  try {
    again.store.verifyWith(c => (c?.text === R0.text ? R0 : null), s => ({ ...s }));
  } finally {
    globalThis.localStorage.setItem = setItem;
    again.store.verifyWith(null);
  }
  assert.ok(JSON.stringify(again.store.draft) === JSON.stringify(JSON.parse(stored)), "the draft opens unchanged");
  assert.equal(writes, 0, "nothing was re-saved");
});

test("the lookup button label follows allowLookup in place, and a missing button is a no-op", async () => {
  const { refreshLookupLabel } = await import("../../pages/draft.js");
  const { allowLookup } = await import("../../pages/sentinel.js");
  const button = { innerHTML: "" }, root = { getElementById: id => (id === "b-lookup" ? button : null) };
  try {
    allowLookup(false);
    refreshLookupLabel(root);
    assert.match(button.innerHTML, /^Open Policy Sentinel<span class="visually-hidden"> \(opens in a new tab\)<\/span>$/);
    allowLookup(true);
    refreshLookupLabel(root);
    assert.equal(button.innerHTML, "Look up a policy");
    refreshLookupLabel({ getElementById: () => null });
    refreshLookupLabel(undefined); // Node has no document
  } finally { allowLookup(false); }
});
