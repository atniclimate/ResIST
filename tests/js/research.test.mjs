// The Research view (pages/research.js, D-078) in Node: the pure markup, then renderResearch against a small stub DOM.
// Clause text is real published ATNI text (26-51, 2026 Annual Convention) from docx-fixtures.mjs. Assertions on clause
// or title text are folded to booleans, so a failure prints none of it.
import test from "node:test";
import assert from "node:assert/strict";
import { resolveObjectURL } from "node:buffer";

const mem = new Map();
Object.defineProperty(globalThis, "navigator", { configurable: true, value: { locks: { request: (_key, fn) => Promise.resolve(fn()) } } });
globalThis.localStorage = {
  getItem: k => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => { mem.set(k, String(v)); },
  removeItem: k => { mem.delete(k); },
};
const listeners = [];
globalThis.addEventListener = (type, fn) => { if (type === "storage") listeners.push(fn); };
const fire = key => listeners.forEach(fn => fn({ key }));

const C = await import("../../pages/collect.js");
const { collection, KEY, itemKey, itemLabel } = C;
const { researchHTML, renderResearch } = await import("../../pages/research.js");
const { store } = await import("../../pages/draft.js");
const { R2651, STATEMENTS } = await import("./docx-fixtures.mjs");

const ROW = { id: R2651.resolutionId, document_id: R2651.documentId, resolution_number: R2651.number, title: R2651.title,
  convention_name: R2651.convention, convention_year: R2651.year };
const stRow = ([t, i, text], p = 2) => ({ id: 1, t, i, text, p });
const RES = C.resolutionItem(ROW, R2651.url);
const W3 = C.statementItem(ROW, stRow(STATEMENTS[0]), R2651.url);
const R0 = C.statementItem(ROW, stRow(STATEMENTS[1], null), "");
// assert.match prints the whole actual string on failure; rendered rows hold clause text, so report the pattern only.
const matches = (html, re) => assert.ok(re.test(html), `expected the markup to match ${re}`);
const reset = items => {
  mem.clear();
  if (items) mem.set(KEY, JSON.stringify({ schema: C.SCHEMA, items }));
  fire(KEY);
};

test("an empty collection says so and offers the search, with no action buttons", () => {
  const html = researchHTML([]);
  assert.match(html, /<h1 tabindex="-1">Research<\/h1>/);
  assert.match(html, /Nothing Collected Yet/);
  assert.match(html, /<a class="btn" href="#\/">Search resolutions<\/a>/);
  assert.match(html, /nothing is sent anywhere/);
  assert.ok(!/research-json|research-text|research-print|data-remove/.test(html));
});

test("one resolution and two statements: counts, verbatim escaped text, full SHA-256, page, safe links, buttons", () => {
  const html = researchHTML([RES, W3, R0], { carried: key => key === itemKey(W3) });
  matches(html, /3 items collected: 1 resolution and 2 statements\./);
  matches(html, /<h2 id="research-res">Resolutions <span class="n">1<\/span>/);
  matches(html, /<h2 id="research-st">Statements <span class="n">2<\/span>/);
  assert.ok(html.includes(W3.text) && html.includes(R0.text) && html.includes(RES.title), "text and title appear exactly");
  assert.equal(html.split(`<code class="sha">${R2651.documentId}</code>`).length - 1, 0, "no visible hash row");
  matches(html, /Resolution 26-51<\/a>, 2026, Annual Convention, page 2/);
  matches(html, /Resolution 26-51<\/a>, 2026, Annual Convention, page unknown/);
  matches(html, /WHEREAS 4/);
  matches(html, /RESOLVED 1/);
  matches(html, new RegExp(`href="#/r/${R2651.resolutionId}"`));
  // The source link is present for the https address and absent where none was recorded; it opens in a new tab and says so.
  assert.equal(html.split('target="_blank"').length - 1, 2);
  assert.equal(html.split("(opens in a new tab)").length - 1, 2);
  matches(html, /Not recorded/);
  // Remove: data-remove with an aria-label naming the item.
  assert.equal(html.split("data-remove=").length - 1, 3);
  assert.ok(html.includes('aria-label="Remove WHEREAS 4 of resolution 26-51 from research"'));
  assert.ok(html.includes('aria-label="Remove resolution 26-51 from research"'));
  // Add to draft: only on statements; data-key, class carry, aria-pressed from carried().
  const draftButtons = html.match(/<button[^>]*class="btn small carry"[^>]*>/g);
  assert.equal(draftButtons.length, 2);
  assert.ok(draftButtons[0].includes(`data-key="${itemKey(W3)}"`) && draftButtons[0].includes('aria-pressed="true"'));
  assert.ok(draftButtons[1].includes(`data-key="${itemKey(R0)}"`) && draftButtons[1].includes('aria-pressed="false"'));
  assert.ok(draftButtons[0].includes('aria-label="Add to draft, WHEREAS 4 of resolution 26-51"'));
  matches(html, /id="research-json"[^>]*>Download JSON/);
  matches(html, /id="research-text"[^>]*>Download text/);
  matches(html, /id="research-print"[^>]*>Print/);
});

test("every value is escaped and only an https address becomes a link", () => {
  const nasty = { ...W3, text: '<b>x</b> & "y"', title: "<script>t</script>", number: "<i>1</i>",
    url: "javascript:alert(1)", convention: '"><img src=x>' };
  const html = researchHTML([nasty, { ...RES, title: "<u>t</u>", url: "http://atnitribes.org/a.pdf" }]);
  assert.ok(html.includes("&lt;b&gt;x&lt;/b&gt; &amp; &quot;y&quot;"));
  assert.ok(!/<b>x|<script|<img|<i>1|<u>t/.test(html));
  assert.ok(!html.includes("javascript:") && !html.includes("http://"));
  assert.equal(html.split('target="_blank"').length - 1, 0);
});

test("the Undo notice shows in both the empty and the filled state", () => {
  for (const items of [[], [RES]]) {
    const html = researchHTML(items, { removed: { item: W3, index: 1 } });
    matches(html, /<p class="notice" id="research-gone">Removed WHEREAS 4 of resolution 26-51\. <button type="button" id="research-undo"[^>]*>Undo<\/button>/);
  }
  assert.ok(!researchHTML([RES]).includes("research-undo"));
});

test("a full collection says so", () => {
  const many = Array.from({ length: C.MAX_ITEMS }, (_, n) => ({ ...RES, documentId: n.toString(16).padStart(64, "0") }));
  matches(researchHTML(many), /holds the most it can \(200 items\)/);
  assert.ok(!/holds the most it can/.test(researchHTML([RES])));
});

// The export boilerplate in collect.js says "Nothing here is a summary" on purpose and is outside this rule.
test("wording rule: nothing says what a resolution is about, deals with, relates to or summarizes", () => {
  const strip = html => [W3.text, R0.text, RES.title].reduce((h, t) => h.split(t).join(""), html);
  const outs = [researchHTML([]), researchHTML([], { removed: { item: RES, index: 0 } }),
    researchHTML([RES, W3, R0], { removed: { item: W3, index: 1 }, carried: () => true }),
    ...["resolution", "statement"].map(k => researchHTML([k === "resolution" ? RES : W3]))];
  for (const out of outs) {
    const text = strip(out);
    assert.ok(!/\b(about|deals? with|relates? to|regarding|concerns?|relevan\w*|summar\w*|similar|related)\b/i.test(text),
      "the view's own words stay free of descriptive claims");
  }
});

// A stub DOM small enough to read: the root holds the buttons that its current HTML names.
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function stubDom() {
  const announce = { textContent: "" }, anchors = [];
  const doc = { activeElement: null, getElementById: id => (id === "announce" ? announce : null),
    createElement: () => { const a = { click() {}, remove() {} }; anchors.push(a); return a; }, body: { append() {} } };
  const state = { paints: 0, html: "", live: new Set(), h1: null, handler: null };
  const attrs = tag => Object.fromEntries([...tag.matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2]
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&")]));
  const makeButton = tag => {
    const a = attrs(tag);
    const b = { id: a.id ?? "", attrs: a, dataset: { key: a["data-key"], remove: a["data-remove"] },
      closest: sel => (sel === "button" ? b : null), focus() { doc.activeElement = b; },
      setAttribute(k, v) { a[k] = String(v); } };
    return b;
  };
  const root = {
    get innerHTML() { return state.html; },
    set innerHTML(html) {
      state.paints++; state.html = html;
      state.buttons = [...html.matchAll(/<button\b[^>]*>/g)].map(m => makeButton(m[0]));
      state.h1 = { focus() { doc.activeElement = state.h1; } };
      state.live = new Set([...state.buttons, state.h1]);
    },
    addEventListener(type, fn) { if (type === "click") state.handler = fn; },
    contains: x => state.live.has(x),
    querySelector: sel => (sel === "h1" ? state.h1 : sel === "#research-undo" ? state.buttons.find(b => b.id === "research-undo") ?? null : null),
    querySelectorAll: sel => (sel === "[data-remove]" ? state.buttons.filter(b => b.dataset.remove) : []),
  };
  const main = { set innerHTML(_) {}, querySelector: () => root };
  const click = b => { doc.activeElement = b; state.handler({ target: b }); };
  const find = pred => state.buttons.find(pred);
  return { doc, announce, anchors, state, main, click, find, root };
}

test("Remove, Undo, Add to draft, downloads, print and the disposer, as a person uses them", async () => {
  const before = { document: globalThis.document, window: globalThis.window };
  const dom = stubDom();
  let printed = 0;
  globalThis.document = dom.doc;
  globalThis.window = { print() { printed++; } };
  const carries = [], uncarries = [], { carry, uncarry } = store;
  store.carry = s => { carries.push(s); return carry.call(store, s); };
  store.uncarry = k => { uncarries.push(k); return uncarry.call(store, k); };
  let dispose;
  try {
    reset([RES, W3, R0]); store.reset();
    dispose = renderResearch(dom.main);
    assert.equal(dom.state.paints, 1);
    assert.ok(dom.state.html.includes("Statements"));

    // Remove: one render, focus on Undo, the announcement says Undo restores it.
    dom.click(dom.find(b => b.dataset.remove === itemKey(W3)));
    assert.deepEqual(collection.items.map(itemKey), [itemKey(RES), itemKey(R0)]);
    assert.equal(dom.state.paints, 2, "the view's own change renders once");
    assert.equal(dom.doc.activeElement.id, "research-undo");
    assert.ok(dom.state.html.includes("research-gone"));
    await sleep(80);
    assert.equal(dom.announce.textContent, "Removed WHEREAS 4 of resolution 26-51 from your research. Undo restores it.");
    assert.equal(JSON.parse(mem.get(KEY)).items.length, 2, "the removal is saved");

    // Undo: back at its old position, focus on its Remove button.
    dom.click(dom.find(b => b.id === "research-undo"));
    assert.deepEqual(collection.items.map(itemKey), [itemKey(RES), itemKey(W3), itemKey(R0)]);
    assert.equal(dom.state.paints, 3);
    assert.equal(dom.doc.activeElement.dataset.remove, itemKey(W3));
    assert.ok(!dom.state.html.includes("research-gone"));
    await sleep(80);
    assert.equal(dom.announce.textContent, "Restored WHEREAS 4 of resolution 26-51 to your research.");

    // Add to draft: the draft's own door, once to add and once to take out; the button's state follows.
    const add = () => dom.find(b => b.dataset.key === itemKey(W3));
    dom.click(add());
    assert.equal(carries.length, 1);
    assert.ok(store.isCarried(itemKey(W3)));
    assert.equal(store.draft.whereas.find(c => c.origin === "carried").source.text === W3.text, true, "the clause is carried verbatim");
    assert.equal(add().attrs["aria-pressed"], "true");
    assert.equal(dom.state.paints, 3, "the draft changing does not re-render the research view");
    dom.click(add());
    assert.equal(uncarries.length, 1);
    assert.ok(!store.isCarried(itemKey(W3)));
    assert.equal(add().attrs["aria-pressed"], "false");
    assert.equal(collection.count(), 3, "the draft never changes the collection");

    // Downloads carry exactly the stored items; print asks the browser to print.
    const blobText = async a => resolveObjectURL(a.href).text();
    dom.click(dom.find(b => b.id === "research-json"));
    assert.equal(dom.anchors.at(-1).download, "resist-research.json");
    assert.equal(await blobText(dom.anchors.at(-1)) === C.collectionJson(collection.items), true);
    dom.click(dom.find(b => b.id === "research-text"));
    assert.equal(dom.anchors.at(-1).download, "resist-research.txt");
    assert.equal(await blobText(dom.anchors.at(-1)) === C.collectionText(collection.items, false), true);
    dom.click(dom.find(b => b.id === "research-print"));
    assert.equal(printed, 1);

    // Another tab: a change this view did not cause re-renders; a restored item clears the stale Undo.
    const paints = dom.state.paints;
    dom.click(dom.find(b => b.dataset.remove === itemKey(R0)));
    assert.equal(dom.state.paints, paints + 1);
    assert.ok(dom.state.html.includes("research-gone"));
    reset([RES, W3, R0]);
    assert.equal(dom.state.paints, paints + 2);
    assert.ok(!dom.state.html.includes("research-gone"), "another tab put the item back");
    reset([RES]);
    assert.equal(dom.state.paints, paints + 3);
    assert.ok(!dom.state.html.includes(W3.text));

    // The disposer unsubscribes.
    dispose(); dispose = null;
    reset([RES, W3]);
    assert.equal(dom.state.paints, paints + 3, "a disposed view no longer renders");
  } finally {
    dispose?.();
    store.carry = carry; store.uncarry = uncarry; store.reset();
    globalThis.document = before.document; globalThis.window = before.window;
    if (before.document === undefined) delete globalThis.document;
    if (before.window === undefined) delete globalThis.window;
  }
});

test("an item added again after Remove (from a result list) clears the Undo and is not doubled", () => {
  const before = globalThis.document, dom = stubDom();
  globalThis.document = dom.doc;
  let dispose;
  try {
    reset([RES, W3]);
    dispose = renderResearch(dom.main);
    dom.click(dom.find(b => b.dataset.remove === itemKey(W3)));
    assert.ok(dom.state.html.includes("research-gone"));
    assert.equal(collection.add(W3), "added");
    assert.ok(!dom.state.html.includes("research-gone"), "the stale Undo is gone");
    assert.equal(dom.find(b => b.id === "research-undo"), undefined);
    assert.deepEqual(collection.items.map(itemKey), [itemKey(RES), itemKey(W3)]);
  } finally {
    dispose?.();
    globalThis.document = before;
    if (before === undefined) delete globalThis.document;
    reset();
  }
});
