// The Research view (#/research, D-078): the resolutions and single clauses a person collected, each in ATNI's published
// words with its source PDF link, document SHA-256 and page. Nothing here writes, summarizes or describes a resolution.
// researchHTML() is pure; renderResearch() owns the one-level Undo and talks to the collection and the draft's own door.
import { esc, toast, download } from "./ui.js";
import { safeUrl } from "./compose.js";
import { collection, changeCollection, itemKey, itemLabel, draftSource, collectionJson, collectionText, MAX_ITEMS } from "./collect.js";
import { store } from "./draft.js";

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

function rowHTML(item, carried) {
  const key = esc(itemKey(item)), label = esc(itemLabel(item)), statement = item.kind === "statement";
  const url = safeUrl(item.url), link = `#/r/${esc(item.resolutionId)}`;
  const where = [item.year, item.convention].filter(v => v !== null && v !== undefined && v !== "").map(esc);
  const pdf = url
    ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open the source PDF<span class="visually-hidden"> (opens in a new tab)</span></a>`
    : "Not recorded";
  const facts = `<dl class="research-facts"><dt>Source PDF</dt><dd class="research-src">${pdf}</dd>
      </dl>`;
  const remove = `<button type="button" class="btn small" data-remove="${key}" aria-label="Remove ${label} from research">Remove</button>`;
  if (!statement) {
    return `<li class="crow research-row" data-kind="resolution"><div class="research-lead"><span class="num">${esc(item.number)}</span></div>
      <div class="research-main"><p class="research-title"><a href="${link}">${esc(item.title || `Resolution ${item.number}`)}</a></p>
        ${where.length ? `<p class="meta">${where.join(", ")}</p>` : ""}${facts}
        <div class="crow-acts">${remove}</div></div></li>`;
  }
  const from = [`<a href="${link}">Resolution ${esc(item.number)}</a>`, ...where, item.page === null ? "page unknown" : `page ${esc(item.page)}`];
  return `<li class="crow research-row" data-kind="statement"><div class="research-lead"><span class="num">${esc(item.statementType.toUpperCase())} ${esc(item.index + 1)}</span></div>
    <div class="research-main"><p class="research-text">${esc(item.text)}</p>
      <p class="meta research-from">${from.join(", ")}</p>${facts}
      <div class="crow-acts"><button type="button" class="btn small carry" data-key="${key}" aria-pressed="${carried(itemKey(item)) ? "true" : "false"}" aria-label="Add to draft, ${label}">Add to draft</button>${remove}</div></div></li>`;
}

// removed: { item } | null, the one-level Undo shown as a notice; carried(key) -> true when that clause is in the draft.
export function researchHTML(items, { removed = null, carried = () => false, verified = true, unsaved = false } = {}) {
  const res = items.filter(i => i.kind === "resolution"), sts = items.filter(i => i.kind === "statement");
  const section = (id, title, list) => list.length ? `<section aria-labelledby="${id}"><h2 id="${id}">${title} <span class="n">${list.length}</span></h2>
    <ul class="research-rows">${list.map(i => rowHTML(i, carried)).join("")}</ul></section>` : "";
  const gone = removed ? `<p class="notice" id="research-gone">Removed ${esc(itemLabel(removed.item))}. <button type="button" id="research-undo" class="btn small">Undo</button></p>` : "";
  const body = items.length ? `<div class="research-actions"><button type="button" id="research-json" class="btn">Download JSON</button>
      <button type="button" id="research-text" class="btn">Download text</button><button type="button" id="research-print" class="btn">Print</button></div>
    <p class="count-line" id="research-count-line">${plural(items.length, "item")} collected: ${plural(res.length, "resolution")} and ${plural(sts.length, "statement")}.</p>
    ${items.length >= MAX_ITEMS ? `<p class="meta">Your collection holds the most it can (${MAX_ITEMS} items). Remove one to add another.</p>` : ""}
    ${section("research-res", "Resolutions", res)}${section("research-st", "Statements", sts)}`
    : `<div class="empty-state"><h2>Nothing Collected Yet</h2>
      <p>Search the resolutions, then choose Collect on a result or on a clause.</p><a class="btn" href="#/">Search resolutions</a></div>`;
  return `<h1 tabindex="-1">Research</h1>
    <p class="lead measure">Collect resolutions and single clauses as you search. ${verified ? "Each item keeps ATNI's published words exactly, with its source PDF link." : "Stored text and source details have not been verified against the resolution database."} Your collection stays in this browser; nothing is sent anywhere.</p>
    ${unsaved ? '<p class="notice">Your latest changes are only available in this tab. Download your collection before closing it.</p>' : ""}${gone}${body}`;
}

export function renderResearch(main) {
  main.innerHTML = '<div class="wrap research-view"></div>';
  const root = main.querySelector(".research-view");
  let removed = null, own = false; // own: this view caused the change it is about to be told of, so it paints once itself
  const paint = () => {
    if (removed && collection.has(itemKey(removed.item))) removed = null; // another tab put it back
    const active = globalThis.document?.activeElement, held = !!active && root.contains(active);
    root.innerHTML = researchHTML(collection.items, { removed, carried: store.isCarried, verified: collection.verified,
      unsaved: collection.saved?.ok === false });
    if (held) root.querySelector("h1")?.focus(); // the focused control is gone; keep the keyboard in the view
  };
  const change = fn => { own = true; try { return fn(); } finally { own = false; } };

  function remove(key) {
    const r = change(() => collection.remove(key));
    if (!r) return;
    removed = r; paint();
    root.querySelector("#research-undo")?.focus();
    toast(`Removed ${itemLabel(r.item)} from your research. Undo restores it.`);
  }
  function undo() {
    const r = removed;
    if (!r) return;
    removed = null;
    const ok = change(() => collection.restore(r)), label = itemLabel(r.item);
    paint();
    if (ok) {
      [...root.querySelectorAll("[data-remove]")].find(b => b.dataset.remove === itemKey(r.item))?.focus();
      toast(`Restored ${label} to your research.`);
    } else {
      root.querySelector("h1")?.focus();
      toast(`Could not restore ${label}. Your research already has it or is full.`);
    }
  }
  function carry(button) {
    const key = button.dataset.key, item = collection.items.find(i => itemKey(i) === key);
    if (!item) return;
    if (store.isCarried(key)) { store.uncarry(key); toast("Removed from your draft"); }
    else if (store.carry(draftSource(item))) toast("Added to your draft");
    button.setAttribute("aria-pressed", String(store.isCarried(key)));
  }

  root.addEventListener("click", e => {
    const b = e.target.closest?.("button");
    if (!b) return;
    if (b.id === "research-json") { download(collectionJson(collection.items), "resist-research.json", "application/json"); toast("Downloaded resist-research.json"); }
    else if (b.id === "research-text") { download(collectionText(collection.items, collection.verified), "resist-research.txt", "text/plain;charset=utf-8"); toast("Downloaded resist-research.txt"); }
    else if (b.id === "research-print") window.print();
    else if (b.id === "research-undo") changeCollection(undo);
    else if (b.dataset.remove) changeCollection(() => remove(b.dataset.remove));
    else if (b.dataset.key) carry(b);
  });
  const off = collection.subscribe(() => { if (!own) paint(); });
  paint();
  return () => { off(); };
}
