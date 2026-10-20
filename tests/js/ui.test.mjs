// pages/ui.js: the one polite announcer (say), the dock's short message (toast) and the dock's visibility
// (refreshDock). document is a minimal getElementById shim over plain objects; no resolution text.
import { test } from "node:test";
import assert from "node:assert/strict";
import { refreshDock, say, toast } from "../../pages/ui.js";

function page(ids) {
  const els = Object.fromEntries(ids.map(id => [id, { textContent: "", hidden: id === "dock" || id === "dock-draft" || id === "dock-ins" }]));
  globalThis.document = { getElementById: id => els[id] ?? null };
  return els;
}

test("say clears then writes the announcer", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const real = globalThis.document;
  try {
    const els = page(["announce"]);
    say("x");
    assert.equal(els.announce.textContent, "");
    t.mock.timers.tick(50);
    assert.equal(els.announce.textContent, "x");
    say("x");
    assert.equal(els.announce.textContent, "");
    t.mock.timers.tick(50);
    assert.equal(els.announce.textContent, "x");
  } finally {
    globalThis.document = real;
  }
});

test("toast is text only, announced, and shows the bar until it clears", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const real = globalThis.document;
  try {
    const markup = "<a href=x>y</a>";
    for (const draftShown of [false, true]) {
      const els = page(["announce", "dock", "toast", "dock-draft"]);
      els["dock-draft"].hidden = !draftShown;
      toast(markup);
      assert.equal(els.toast.textContent, markup);
      assert.equal(els.toast.innerHTML, undefined); // never written as HTML
      assert.equal(els.dock.hidden, false);
      t.mock.timers.tick(50);
      assert.equal(els.announce.textContent, markup);
      t.mock.timers.tick(4950);
      assert.equal(els.toast.textContent, "");
      assert.equal(els.dock.hidden, !draftShown);
    }
  } finally {
    globalThis.document = real;
  }
});

test("the dock also shows for the insert point", () => {
  const real = globalThis.document;
  try {
    const els = page(["dock", "toast", "dock-draft", "dock-ins"]);
    els["dock-ins"].hidden = false;
    refreshDock();
    assert.equal(els.dock.hidden, false);
    els["dock-ins"].hidden = true;
    refreshDock();
    assert.equal(els.dock.hidden, true);
  } finally {
    globalThis.document = real;
  }
});

test("helpers do nothing without their elements", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const real = globalThis.document;
  try {
    page([]);
    say("x"); toast("x"); refreshDock();
    t.mock.timers.tick(5000);
    delete globalThis.document;
    say("x"); toast("x"); refreshDock();
    t.mock.timers.tick(5000);
  } finally {
    globalThis.document = real;
  }
});
