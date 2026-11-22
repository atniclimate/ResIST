import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { packetHTML, renderReports, stateMessage } from "../../pages/reports.js";

const packet = {
  request: "atni:res:00-1",
  completeness: { missing_pages: 1, citation_missing_pages: 0, missing_extraction_records: 1 },
  sources: [{ number: "00-1", title: "Neutral <title>", status: "unknown", status_authority: "none",
    sha256: "a".repeat(64), text_sha256: "b".repeat(64), source_file_state: "hash-verified",
    extraction: { state: "not-recorded", records: [] }, clauses: [
      { statement_type: "excerpt", text_state: "verified-normalized", locator_state: "missing-page",
        span: { quote: "Neutral <script> & Á 🙂\n" + "Long neutral text. ".repeat(50), page: null, start: 0, end: 1000 } },
      { statement_type: "excerpt", text_state: "withheld-identity", locator_state: "identity-failed", span: null },
    ] }], citations: [],
};

test("complete escaped quotations retain long text, Unicode and provenance gaps", () => {
  const html = packetHTML(packet);
  assert.ok(html.includes("&lt;script&gt; &amp; Á 🙂\n"));
  assert.ok(html.includes("Long neutral text. ".repeat(50)));
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("Text withheld"));
  assert.ok(html.includes("Page not recorded"));
  assert.ok(html.includes("1 source without historical extraction records"));
  assert.ok(html.includes("not evidence that no policy exists"));
});

test("refusal, stale, missing and failure are distinct plain-language outcomes", () => {
  const states = ["verified", "missing", "refused", "stale-input", "failed", "unavailable"];
  assert.equal(new Set(states.map(stateMessage)).size, states.length);
  assert.match(stateMessage("verified"), /matches current local sources/);
  assert.match(stateMessage("stale-input"), /integrity is unverified/);
  assert.equal(stateMessage("unknown"), stateMessage("failed"));
});

const turn = () => new Promise(resolve => setImmediate(resolve));
function element() {
  return { innerHTML: "", textContent: "", hidden: false, disabled: false, dataset: {}, handlers: {},
    addEventListener(event, handler) { this.handlers[event] = handler; }, setAttribute() {}, removeAttribute() {},
    focus() {}, reportValidity: () => true, querySelectorAll: () => [] };
}
function reportView() {
  const selectors = ["#report-status", "form", "#report-actions", "#report-output", "#report-formats", "#report-word", "input"];
  const nodes = Object.fromEntries(selectors.map(selector => [selector, element()]));
  const buttons = [element(), element(), element()];
  const root = element();
  root.querySelector = selector => nodes[selector];
  root.querySelectorAll = selector => selector === "[data-report-format]" ? buttons.slice(1) : buttons;
  const main = element();
  main.querySelector = () => root;
  return { main, nodes, buttons };
}

test("returning to a retained packet hides quotations until current policy is checked", async () => {
  const before = { document: globalThis.document, fetch: globalThis.fetch };
  globalThis.document = { getElementById: () => null };
  let resolveVerification, checks = 0;
  const fingerprint = "f".repeat(64);
  globalThis.fetch = async (path, options) => {
    if (path === "capabilities.json") return { ok: true, json: async () => ({ face: "local", reports: { available: true } }) };
    if (path === "/api/v1/reports") return { ok: true, json: async () => ({ status: "verified", packet, fingerprint }) };
    assert.equal(path, "/api/v1/reports/verify");
    assert.deepEqual(JSON.parse(options.body), {request: packet.request, fingerprint});
    checks++;
    return new Promise(resolve => { resolveVerification = state => resolve({ ok: false, json: async () => ({ status: state }) }); });
  };
  let dispose;
  try {
    const first = reportView();
    dispose = renderReports(first.main);
    await turn();
    first.nodes.input.value = "00-1";
    await first.nodes.form.handlers.submit({ preventDefault() {} });
    assert.match(first.nodes["#report-output"].innerHTML, /Long neutral text/);
    dispose();
    for (const state of ["stale-input", "refused"]) {
      const returned = reportView();
      dispose = renderReports(returned.main);
      await turn();
      assert.equal(returned.nodes["#report-output"].innerHTML, "");
      assert.equal(returned.nodes["#report-status"].dataset.state, "generating");
      assert.ok(returned.buttons.every(button => button.disabled));
      resolveVerification(state);
      await turn();
      assert.equal(returned.nodes["#report-output"].innerHTML, "");
      assert.equal(returned.nodes["#report-status"].dataset.state, state);
      assert.equal(returned.buttons[0].disabled, false);
      assert.ok(returned.buttons.slice(1).every(button => button.disabled));
      dispose();
    }
    assert.equal(checks, 2);
  } finally {
    dispose?.();
    Object.assign(globalThis, before);
  }
});

// app.js runs as a script with its imports stripped (single-line imports only) and every imported name stubbed here.
const appContext = (view, extra = {}) => {
  const elements = new Map();
  const byId = id => {
    if (!elements.has(id)) elements.set(id, { ...element(), querySelector: () => element() });
    return elements.get(id);
  };
  const seen = { loaded: 0, rendered: 0, verified: 0, collected: 0, finish: null };
  const context = vm.createContext({
    document: { getElementById: byId, documentElement: { dataset: {} }, body: { dataset: {} },
      querySelector: () => null, querySelectorAll: () => [] },
    location: { hash: `#/${view}` }, history: {}, window: { scrollTo() {} }, URLSearchParams,
    setTimeout, clearTimeout, addEventListener() {}, local: { set() {} }, refreshDock() {},
    store: { subscribe() {}, carriedCount: () => 0, citeCount: () => 0, verifyWith() { seen.verified++; } },
    changeCollection: fn => fn(),
    collection: { subscribe() {}, count: () => 0, has: () => false, verifyWith() { seen.collected++; return 0; } },
    resolutionItem: () => ({}), statementItem: () => ({}), itemLabel: () => "", MAX_ITEMS: 200, searchedHTML: () => "",
    issues: [], issuesOk: false, issuesRefused: false, toast() {},
    renderDraft() { seen.rendered++; }, renderReports() { seen.rendered++; return () => {}; },
    renderResearch() { seen.rendered++; return () => {}; },
    load() { seen.loaded++; return new Promise(resolve => { seen.finish = resolve; }); },
    build: null, caps: { sentinel: false }, allowLookup() {}, refreshLookupLabel() {}, say() {}, ...extra,
  });
  return { byId, seen, context };
};
const appSource = async () => (await readFile(new URL("../../pages/app.js", import.meta.url), "utf8")).replace(/^import .*;\r?\n/gm, "");

test("direct Draft or Research entry starts provenance loading without blocking; Reports starts no database load", async () => {
  const source = await appSource();
  for (const view of ["draft", "research", "reports"]) {
    const { seen, context } = appContext(view);
    new vm.Script(source).runInContext(context);
    const loads = view !== "reports";
    assert.equal(seen.rendered, 1, "initial view renders while the loader is pending");
    assert.equal(seen.loaded, loads ? 1 : 0);
    assert.equal(seen.verified, 0);
    assert.equal(seen.collected, 0);
    if (seen.finish) {
      seen.finish(); await turn();
      assert.equal(seen.verified, 1, "retained draft provenance is checked when the database arrives");
      assert.equal(seen.collected, 1, "the collection is checked against the database once, at the same time");
      assert.equal(seen.rendered, 1, "background loading preserves the open view and its focus");
    }
  }
});

test("Collect is handled by one delegated listener on every view, not only on a resolution", async () => {
  const source = await appSource();
  const doc = "a".repeat(64), added = [], toasts = [];
  const { byId, context } = appContext("research", {
    Q: { resolution: id => ({ id, resolution_number: "00-1", document_id: doc, title: "Neutral title", convention_year: 2000, convention_name: "Neutral" }),
      statements: () => [{ t: "whereas", i: 2, text: "Neutral clause.", p: null }], sourceUrls: () => [] },
    resolutionItem: (r, url) => ({ kind: "resolution", documentId: r.document_id, url }),
    statementItem: (r, s, url) => ({ kind: "statement", documentId: r.document_id, statementType: s.t, index: s.i, url }),
    itemLabel: item => `${item.kind} label`,
    collection: { subscribe() {}, count: () => added.length, has: () => false, verifyWith: () => 0, saved: { ok: false },
      add(item) { added.push(item); return "added"; } },
    toast: text => toasts.push(text),
  });
  new vm.Script(source).runInContext(context);
  const click = dataset => byId("main").handlers.click({ target: { closest: selector => selector === "button.collect" ? { dataset } : null } });
  click({ rkind: "resolution", rid: "7", rkey: doc });
  click({ rkind: "statement", rid: "7", rtype: "whereas", ri: "2", rkey: `${doc}:whereas:2` });
  click({ rkind: "statement", rid: "7", rtype: "whereas", ri: "9", rkey: `${doc}:whereas:9` });
  assert.deepEqual(added.map(i => i.kind), ["resolution", "statement"], "a button naming a clause that is not there adds nothing");
  assert.equal(added[1].index, 2);
  assert.match(toasts[0], /^Collected resolution label\. Your research has 1 item\. This browser would not keep it after you leave\.$/);
});

test("Word projection refusal retains verified quotations and alternative downloads", async () => {
  const before = { document: globalThis.document, fetch: globalThis.fetch };
  globalThis.document = { getElementById: () => null };
  globalThis.fetch = async path => {
    const result = path === "capabilities.json" ? { face: "local", reports: { available: true, formats: ["json", "md", "docx"] } }
      : path === "/api/v1/reports" ? { status: "verified", packet }
      : path === "/api/v1/reports/verify" ? { status: "verified", verified: true }
      : { verified: true, status: "format-unavailable", format: "docx" };
    return { ok: path !== "/api/v1/reports/download", json: async () => result };
  };
  const view = reportView();
  const dispose = renderReports(view.main);
  try {
    await turn();
    view.nodes.input.value = "00-1";
    await view.nodes.form.handlers.submit({ preventDefault() {} });
    assert.equal(view.nodes["#report-word"].hidden, false);
    assert.equal(view.nodes["#report-formats"].hidden, true);
    const button = { dataset: { reportFormat: "docx" } };
    await view.nodes["#report-actions"].handlers.click({ target: { closest: () => button } });
    assert.equal(view.nodes["#report-status"].dataset.state, "word-unavailable");
    assert.match(view.nodes["#report-status"].textContent, /still matches current local sources/);
    assert.match(view.nodes["#report-status"].textContent, /Download JSON or Markdown/);
    assert.match(view.nodes["#report-output"].innerHTML, /Long neutral text/);
    assert.ok(view.buttons.every(button => !button.disabled));
  } finally {
    dispose(); Object.assign(globalThis, before);
  }
});
