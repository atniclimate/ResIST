// The Research collection (D-078, RM-1): whole resolutions and single statements a person collects while exploring,
// kept only in this browser under its own key, never in the draft. Every item is ATNI's published words exactly with
// its document SHA-256, statement type and index, page and source URL; nothing is written, summarized or described.
// No DOM here. A stored collection is untrusted: each item is validated on open, and once the database has loaded
// verifyWith() replaces it with the database's record or removes it (the draft's rule for carried clauses).
import { local } from "./ui.js";
import { safeUrl, squash } from "./compose.js";

export const KEY = "resist-research-v1", SCHEMA = "resist-research/1", MAX_ITEMS = 200;
const WORD = { whereas: "WHEREAS", resolved: "RESOLVED" };

export const itemKey = item => item.kind === "statement"
  ? `${item.documentId}:${item.statementType}:${item.index}` // the draft's carryKey: one key, one clause, in both stores
  : String(item.documentId);

export const resolutionItem = (r, url) => ({
  kind: "resolution", resolutionId: r.id, number: r.resolution_number, title: r.title, year: r.convention_year,
  convention: r.convention_name, documentId: r.document_id, url: url || "",
});
export const statementItem = (r, s, url) => ({
  kind: "statement", resolutionId: r.id, number: r.resolution_number, title: r.title, year: r.convention_year,
  convention: r.convention_name, documentId: r.document_id, statementType: s.t, index: s.i,
  page: Number.isInteger(s.p) ? s.p : null, text: s.text, url: url || "",
});

export const itemLabel = item => item.kind === "statement"
  ? `${WORD[item.statementType]} ${item.index + 1} of resolution ${item.number}` : `resolution ${item.number}`;

// The ten fields the draft's carry() takes (app.js sourceFrom): no kind, no page. A resolution has no clause to carry.
export const draftSource = item => item.kind !== "statement" ? null : ({
  resolutionId: item.resolutionId, number: item.number, title: item.title, year: item.year, convention: item.convention,
  documentId: item.documentId, statementType: item.statementType, index: item.index, text: item.text, url: item.url,
});

const text = v => typeof v === "string" ? v : Number.isFinite(v) ? String(v) : "";
// A clean copy of a valid item, or null. Fields are in one fixed order, so a stored item equals a rebuilt one.
function validItem(x) {
  if (!x || typeof x !== "object" || (x.kind !== "resolution" && x.kind !== "statement")) return null;
  if (typeof x.documentId !== "string" || !/^[0-9a-f]{64}$/.test(x.documentId) || !Number.isInteger(x.resolutionId) || x.resolutionId < 1) return null;
  if (typeof x.url !== "string" || (x.url !== "" && safeUrl(x.url) !== x.url)) return null;
  const head = { kind: x.kind, resolutionId: x.resolutionId, number: text(x.number), title: text(x.title),
    year: Number.isInteger(x.year) ? x.year : null, convention: text(x.convention), documentId: x.documentId };
  if (x.kind === "resolution") return { ...head, url: x.url };
  if (!Object.hasOwn(WORD, x.statementType) || !Number.isInteger(x.index) || x.index < 0 || typeof x.text !== "string" ||
    !x.text.trim() || !(x.page === null || (Number.isInteger(x.page) && x.page >= 1))) return null;
  return { ...head, statementType: x.statementType, index: x.index, page: x.page, text: x.text, url: x.url };
}

// Invalid and duplicate items are dropped; at most MAX_ITEMS are kept. Another schema or a non-object is null.
export function validCollection(value) {
  if (!value || typeof value !== "object" || value.schema !== SCHEMA) return null;
  const seen = new Set(), items = [];
  for (const x of Array.isArray(value.items) ? value.items : []) {
    const v = validItem(x);
    if (!v || seen.has(itemKey(v)) || items.length >= MAX_ITEMS) continue;
    seen.add(itemKey(v)); items.push(v);
  }
  return { schema: SCHEMA, items };
}

export const collectionJson = items => JSON.stringify({ schema: SCHEMA, items }, null, 2) + "\n";

export function collectionText(items) {
  const block = (n, head, body, item) => [`${n}. ${head}`, `   ${body}`,
    ...(item.url ? [`   Source PDF: ${item.url}`] : []), `   SHA-256: ${item.documentId}`].join("\n");
  const res = items.filter(i => i.kind === "resolution"), sts = items.filter(i => i.kind === "statement");
  return [
    "ATNI-ResIST research collection\n" +
    "Text is copied word for word from resolutions published by the Affiliated Tribes of Northwest Indians. The source PDF governs. Nothing here is a summary, a finding or a legal conclusion.",
    ...(res.length ? [`RESOLUTIONS (${res.length})`, ...res.map((i, n) =>
      block(n + 1, [`Resolution ${squash(i.number)}`, squash(i.year), squash(i.convention)].filter(Boolean).join(", "),
        squash(i.title), i))] : []),
    ...(sts.length ? [`STATEMENTS (${sts.length})`, ...sts.map((i, n) =>
      block(n + 1, [`${WORD[i.statementType]} ${i.index + 1}`, `Resolution ${squash(i.number)}`, squash(i.year),
        i.page === null ? "page unknown" : `page ${i.page}`].filter(p => p !== "").join(", "), squash(i.text), i))] : []),
  ].join("\n\n") + "\n";
}

// Own toString/valueOf keys in untrusted JSON make String() and template literals throw; JSON cannot carry others.
const reviver = (k, v) => k === "toString" || k === "valueOf" ? undefined : v;
function load() {
  try { return validCollection(JSON.parse(local.get(KEY), reviver))?.items ?? []; } catch { return []; }
}

let items = load(), saved = null;
const subs = new Set();
const notify = () => { for (const fn of [...subs]) fn(items); };
// Every change saves at once (there is no typing here, so no debounce). A browser that keeps nothing says so in saved.
const commit = next => {
  items = next;
  saved = { ok: local.set(KEY, JSON.stringify({ schema: SCHEMA, items })) };
  notify();
};
const indexOf = key => items.findIndex(i => itemKey(i) === key);

// Another tab saved: take its copy, so this tab's next save cannot overwrite it with a stale one.
globalThis.addEventListener?.("storage", e => {
  if (e.key !== KEY) return;
  items = load(); notify();
});

export const collection = {
  get items() { return items; },
  get saved() { return saved; },
  count: () => items.length,
  has: key => indexOf(key) >= 0,
  // "added" | "duplicate" | "full" | "invalid"
  add(item) {
    const v = validItem(item);
    if (!v) return "invalid";
    if (indexOf(itemKey(v)) >= 0) return "duplicate";
    if (items.length >= MAX_ITEMS) return "full";
    commit([...items, v]);
    return "added";
  },
  // No undo state is kept here; the view holds what remove() returns.
  remove(key) {
    const index = indexOf(key);
    if (index < 0) return null;
    const item = items[index];
    commit(items.filter((_, i) => i !== index));
    return { item, index };
  },
  restore({ item, index } = {}) {
    const v = validItem(item);
    if (!v || indexOf(itemKey(v)) >= 0 || items.length >= MAX_ITEMS) return false;
    const at = Math.min(Number.isInteger(index) && index >= 0 ? index : items.length, items.length);
    commit([...items.slice(0, at), v, ...items.slice(at)]);
    return true;
  },
  subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },
  // lookup(item) -> the database's record or null. Found items take the record (current id, url, page), the rest are
  // removed. Returns how many were removed.
  verifyWith(lookup) {
    const seen = new Set(), next = [];
    for (const item of items) {
      const v = validItem(lookup(item));
      if (v && !seen.has(itemKey(v))) { seen.add(itemKey(v)); next.push(v); }
    }
    const dropped = items.length - next.length;
    if (JSON.stringify(next) !== JSON.stringify(items)) commit(next);
    return dropped;
  },
};
