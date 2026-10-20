// The A6 gate in pages/sentinel.js (D-059 item 5 (2)(a)): until allowLookup(true), openLookup() links out to
// Policy Sentinel and never builds the lookup dialog, so the local face never calls the Worker. Own file because the
// gate is module state. document/window/fetch are minimal shims; no resolution text.
import { test } from "node:test";
import assert from "node:assert/strict";
import { SENTINEL_HOME, SOURCES, allowLookup, openLookup } from "../../pages/sentinel.js";

function shims() {
  const seen = { opens: [], fetches: 0, modal: 0, appended: 0 };
  const els = new Map();
  const el = s => {
    if (!els.has(s)) els.set(s, { value: s === "#sn-source" ? SOURCES[0].id : "", textContent: "", innerHTML: "", focus() {} });
    return els.get(s);
  };
  const dlg = { setAttribute() {}, addEventListener() {}, querySelector: el, showModal() { seen.modal++; } };
  globalThis.document = { activeElement: null, createElement: () => dlg, body: { append() { seen.appended++; } } };
  globalThis.window = { open: (...a) => { seen.opens.push(a); } };
  globalThis.fetch = async () => { seen.fetches++; throw new Error("no request expected"); };
  return seen;
}

test("openLookup links out unless allowLookup(true), and opening the dialog sends nothing", () => {
  const real = { document: globalThis.document, window: globalThis.window, fetch: globalThis.fetch };
  try {
    for (const on of [undefined, "true", 1, false]) { // undefined: the default, before any allowLookup call
      if (on !== undefined) allowLookup(on);
      const seen = shims();
      openLookup({ query: "Executive Order 13175" });
      assert.deepEqual(seen.opens, [[SENTINEL_HOME, "_blank", "noopener"]], String(on));
      assert.equal(seen.modal + seen.appended + seen.fetches, 0, String(on));
    }
    allowLookup(true);
    const seen = shims();
    openLookup({ query: "Executive Order 13175" });
    assert.equal(seen.opens.length, 0);
    assert.equal(seen.modal, 1);
    assert.equal(seen.fetches, 0); // only a submitted search makes a request
    allowLookup(false);
    const after = shims();
    openLookup();
    assert.equal(after.opens.length, 1);
    assert.equal(after.modal, 0);
  } finally {
    Object.assign(globalThis, real);
  }
});
