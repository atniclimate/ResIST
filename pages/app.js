// ResIST public site: header, router and the search, detail and about views (SPEC 6.1). The draft workspace is
// draft.js; Policy Sentinel lookups are sentinel.js; every database query is a named export of query.js. Every
// string from the database passes through esc(); user search text reaches a query only through Q.ftsMatch() or as
// a bound parameter.
import { load, build, caps, issues, issuesOk, issuesRefused } from "./db.js";
import * as Q from "./query.js";
import { esc, local, toast, say, refreshDock } from "./ui.js";
import { isStandard, hasPageHeader, resolvedLead, usDate, squash, segments } from "./compose.js";
import { store, renderDraft, refreshLookupLabel } from "./draft.js";
import { renderReports } from "./reports.js";
import { collection, changeCollection, resolutionItem, statementItem, itemLabel, MAX_ITEMS } from "./collect.js";
import { renderResearch } from "./research.js";
import { searchedHTML } from "./searched.js";
import { openLookup, allowLookup, lookupWords, FEDERAL_TYPES, SENTINEL_HOME, isLookupLive, wordsHTML, copyText } from "./sentinel.js";

const PAGE = 25;
const main = document.getElementById("main");
const CONVENTIONS = [["annual", "Annual", "Annual Convention"], ["midyear", "Mid-Year", "Mid-Year Convention"],
  ["winter", "Winter", "Winter Convention"]];
const TSDF = "https://atniclimate.github.io/TieredSovereignDataFramework/";
const CODE = "https://github.com/atniclimate/ResIST";
const num = n => Number(n).toLocaleString("en-US");
const plural = (n, one, many = one + "s") => `${num(n)} ${n === 1 ? one : many}`;
const fileName = u => { const f = u.split("/").pop() || u; try { return decodeURIComponent(f); } catch { return f; } };

/* Theme: data-theme is set before first paint by the inline script in index.html; default dark. */
const themeButton = document.getElementById("theme-toggle");
// Icon-only button: its name says the action, not the current state.
const showTheme = () => {
  const label = document.documentElement.dataset.theme === "light" ? "Dark theme" : "Light theme";
  themeButton.setAttribute("aria-label", label);
  themeButton.title = label;
};
themeButton.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  local.set("resist-theme", next);
  showTheme();
});
showTheme();

/* Draft count in the header, and pressed state of any "Add to draft" toggles on screen. */
const keyOf = s => `${s.documentId}:${s.statementType}:${s.index}`;
function syncDraft() {
  const n = store.carriedCount();
  document.getElementById("draft-count").textContent = n ? String(n) : "";
  document.getElementById("draft-count-words").textContent = n ? ` (${plural(n, "carried clause")})` : "";
  main.querySelectorAll("button[data-key]").forEach(b => b.setAttribute("aria-pressed", String(store.isCarried(b.dataset.key))));
  main.querySelectorAll(".clause[data-key]").forEach(r => r.classList.toggle("in-draft", store.isCarried(r.dataset.key)));
  // The draft bar (#dock): the way to the draft from every other view while something is carried (UI-1 D6).
  const m = store.citeCount(), onDraft = document.body.dataset.view === "draft";
  document.getElementById("dock-count").textContent = `Your draft: ${plural(n, "carried clause")}${m ? `, ${plural(m, "carried citation")}` : ""}`;
  document.getElementById("dock-draft").hidden = !(n + m) || onDraft;
  // The insert point (UI-2 D19): where the next citation goes, with the way to clear it. The draft view shows its own caret.
  const ip = store.insertPoint;
  document.getElementById("dock-ins").hidden = !ip || onDraft;
  document.getElementById("dock-ins-pos").textContent = ip ? ip.label : "";
  refreshDock();
}
store.subscribe(syncDraft);

/* Research count in the header, and pressed state of any "Collect" toggles on screen (D-078). */
function syncResearch() {
  const n = collection.count();
  document.getElementById("research-count").textContent = n ? String(n) : "";
  document.getElementById("research-count-words").textContent = n ? ` (${plural(n, "item")})` : "";
  main.querySelectorAll("button.collect[data-rkey]").forEach(b => b.setAttribute("aria-pressed", String(collection.has(b.dataset.rkey))));
}
collection.subscribe(syncResearch);
document.getElementById("dock-ins-clear").addEventListener("click", () => {
  const open = main.querySelector(".cpop:not([hidden])");
  closePop(false);
  store.clearInsertPoint();
  syncDraft();
  // The button hides itself, so focus goes to the open citation, else the draft link, else the page.
  (open && document.getElementById(open.id.replace("pop-", "m-")) || [...document.querySelectorAll("#dock-draft a")].find(a => a.offsetParent) || main).focus({ preventScroll: true });
  say("Insert point cleared. Add to draft now starts a new WHEREAS clause.");
});

/* Router */
function parse() {
  const [path, query = ""] = location.hash.slice(1).split("?");
  return { path: path || "/", q: new URLSearchParams(query) };
}
let lastSearch = "#/", lastView = "", backTo = null;

// Draft opens at once while its stored provenance is checked in the background.
// Reports use only the authoritative local API and do not start the public database download.
const LOADING = main.innerHTML;
let ready = false, loadError = "", loadingDatabase = false;
let disposeReport = () => {};

// Back to results (UI-1 D5): the scroll position and the opened result, keyed by the normalized search href.
// In memory only, so a reload starts at the top as before.
const back = new Map();
try { history.scrollRestoration = "manual"; } catch { /* the browser restores as it likes */ }
let countTimer;

function route() {
  disposeReport();
  disposeReport = () => {};
  const { path, q } = parse();
  const view = path.startsWith("/r/") ? "detail" : path === "/draft" ? "draft" : path === "/reports" ? "reports" : path === "/research" ? "research" : path === "/about" ? "about" : "search";
  document.body.dataset.view = view;
  const needsDatabase = !["draft", "reports", "research"].includes(view);
  if (view !== "reports") void loadDatabase();
  // Busy only while a view is waiting for the download; the draft and Research never wait.
  if (!ready && !loadError && needsDatabase) main.setAttribute("aria-busy", "true");
  else main.removeAttribute("aria-busy");
  // A resolution opened from Research goes back to Research. "" is the loading placeholder, which keeps what was set.
  if (view !== "detail") backTo = null;
  else if (lastView === "research") backTo = "#/research";
  else if (lastView) backTo = null;
  if (!ready && needsDatabase) {
    main.innerHTML = loadError ? `<div class="wrap wide"><div class="notice" role="alert"><p>${esc(loadError)}</p></div></div>` : LOADING;
    lastView = "";
    syncDraft();
    syncResearch();
    return;
  }
  if (lastView === "search" && view === "detail") back.set(lastSearch, { y: window.scrollY, id: Number(path.slice(3)) });
  const focusId = view === lastView && document.activeElement?.id;
  const firstRender = !lastView;
  const fromDetail = lastView === "detail";
  detail = null; // only an open resolution has marks to act on
  try {
    if (view === "detail") detailView(Number(path.slice(3)));
    else if (view === "draft") { document.title = "Draft Resolution, ResIST"; renderDraft(main); }
    else if (view === "reports") disposeReport = renderReports(main);
    else if (view === "research") { document.title = "Research, ResIST"; disposeReport = renderResearch(main); }
    else if (view === "about") aboutView();
    else searchView(q);
  } catch (e) {
    main.innerHTML = `<div class="wrap wide"><h1 tabindex="-1">This Page Could Not Be Shown</h1>
      <p>${esc(e.message)}</p><p><a href="#/">Search all resolutions</a></p></div>`;
  }
  document.querySelectorAll(".site-nav a[data-nav]").forEach(a =>
    a.dataset.nav === view || (view === "detail" && a.dataset.nav === "search") ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  syncDraft();
  syncResearch();
  lastView = view;
  clearTimeout(countTimer);
  // Back from a resolution to the results it was opened from: same place, focus on that result, no count announced.
  const saved = view === "search" && fromDetail && back.get(lastSearch);
  if (saved && main.querySelector("#results-count")) {
    window.scrollTo(0, saved.y);
    (main.querySelector(`a[href="#/r/${saved.id}"]`) ?? main.querySelector("h1"))?.focus({ preventScroll: true });
    return;
  }
  // The result count is said once the filters settle: arrowing through a closed select fires one change per arrow.
  if (view === "search" && !firstRender) {
    // The count, then what was searched, then a fallback notice when there is one (RM-2: the person hears the words too).
    countTimer = setTimeout(() => {
      const count = document.body.dataset.view === "search" && main.querySelector("#results-count");
      if (count) say([count, main.querySelector("#searched-lead"), main.querySelector("#search-fallback")].filter(Boolean)
        .map(el => el.textContent.trim().replace(/\.$/, "")).join(". ") + ".");
    }, 500);
  }
  // A filter change keeps focus on the control used; any other route change moves focus to the new h1.
  const keep = focusId && document.getElementById(focusId);
  if (keep) { keep.focus({ preventScroll: true }); return; }
  window.scrollTo(0, 0);
  if (!firstRender) main.querySelector("h1")?.focus({ preventScroll: true });
}

// Jump links (detail) move focus without touching the hash, which the router owns; Copy buttons (local face) copy
// a citation's search words; citation marks, their popovers, Add to draft and the lookups (UI-2 D18) are handled
// here too. One click and one keydown listener on main, which outlives every view; `detail` is the open resolution's
// citation table (null on any other view).
let detail = null;
const byId = id => document.getElementById(id);
main.addEventListener("click", e => {
  const jump = e.target.closest("a[data-jump]");
  if (jump) {
    const target = byId(jump.dataset.jump);
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ block: "start" });
    target.focus({ preventScroll: true });
    return;
  }
  const copy = e.target.closest("button[data-copy]");
  if (copy) {
    copyText(byId(copy.dataset.copy)).then(ok =>
      say(ok ? "Search words copied" : "Search words selected. Press Control and C to copy."));
    return;
  }
  const collect = e.target.closest("button.collect");
  if (collect) {
    const removing = collection.has(collect.dataset.rkey);
    changeCollection(() => collectItem(collect, removing));
    return;
  }
  const mark = e.target.closest("button[data-mark]");
  if (mark) { togglePop(Number(mark.dataset.mark)); return; }
  const close = e.target.closest("button[data-close-pop]");
  if (close) { closePop(true); return; }
  const add = e.target.closest("button[data-add]");
  if (add && detail) { addCite(Number(add.dataset.add), add.dataset.at === "new" ? "new" : "auto", add.closest(".cpop") !== null); return; }
  const look = e.target.closest("button[data-look]");
  if (look && detail) lookCite(look);
});
main.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  const open = main.querySelector(".cpop:not([hidden])");
  if (open && (open.contains(e.target) || e.target.id === open.id.replace("pop-", "m-"))) { e.preventDefault(); closePop(true); }
});

// One popover open at a time. It is filled when opened, so the insert point it names is current (D18).
function closePop(focusMark) {
  const open = main.querySelector(".cpop:not([hidden])");
  if (!open) return;
  const mark = byId(open.id.replace("pop-", "m-"));
  open.hidden = true;
  mark?.setAttribute("aria-expanded", "false");
  if (focusMark) mark?.focus({ preventScroll: true });
}
function togglePop(id) {
  const pop = byId(`pop-${id}`), mark = byId(`m-${id}`), info = detail?.cites.get(id);
  if (!pop || !mark || !info) return;
  const wasOpen = !pop.hidden;
  closePop(false);
  if (wasOpen) return;
  pop.innerHTML = popHTML(info);
  pop.hidden = false;
  mark.setAttribute("aria-expanded", "true");
  pop.querySelector("button, a")?.focus({ preventScroll: true });
  pop.scrollIntoView({ block: "nearest" });
}
// A short toast names the target. From a popover, the popover closes and focus returns to its mark.
function addCite(id, at, fromPop) {
  const info = detail.cites.get(id);
  const out = info && store.carryCite(info.source(), { at });
  if (!out) return;
  const words = squash(info.c.text);
  toast(out.duplicate ? `This citation is already in ${out.label}`
    : out.created ? `Added ${words} as a new ${out.label}` : `Added ${words} to ${out.label}`);
  if (fromPop) closePop(true);
}
function lookCite(b) {
  const c = detail.byId.get(Number(b.dataset.look));
  if (!c) return;
  const words = b.getAttribute("aria-controls") && byId(b.getAttribute("aria-controls"));
  if (words) {
    words.hidden = false;
    b.setAttribute("aria-expanded", "true");
    say("Policy Sentinel opened in a new tab. Its search words are shown below the button.");
  }
  openLookup({
    query: lookupWords(c.text, c.kind),
    onAddNote: note => { store.addNote(note); toast("Policy note added to your draft"); },
  });
}

// Collect (D-078): one click adds the item to the Research collection, the next removes it. The item is built from the
// database, never from the button's attributes; the button only names which one. Focus stays on the button.
function collectItem(b, removing) {
  if (removing) {
    const gone = collection.remove(b.dataset.rkey);
    if (gone) toast(`Removed ${itemLabel(gone.item)} from your research.`);
    return;
  }
  const r = Q.resolution(Number(b.dataset.rid));
  const s = b.dataset.rkind === "statement" && r ? Q.statements(r.id).find(x => x.t === b.dataset.rtype && x.i === Number(b.dataset.ri)) : null;
  if (!r || (b.dataset.rkind === "statement" && !s)) return;
  const url = Q.sourceUrls(r.document_id)[0];
  const item = s ? statementItem(r, s, url) : resolutionItem(r, url);
  const out = collection.add(item);
  toast(out === "added"
    ? `Collected ${itemLabel(item)}. Your research has ${plural(collection.count(), "item")}.${collection.saved?.ok === false ? " This browser would not keep it after you leave." : ""}`
    : out === "full" ? `Your research holds ${plural(MAX_ITEMS, "item")}. Remove one to add another.` : "This item could not be collected.");
}

/* Search */
let topCommittees;
function committees() {
  topCommittees ??= Q.committees();
  return topCommittees;
}

function searchView(q) {
  const text = q.get("q") || "";
  const year = /^\d{4}$/.test(q.get("year") || "") ? q.get("year") : "";
  const conv = CONVENTIONS.find(c => c[0] === q.get("convention")) || null;
  const committee = committees().includes(q.get("committee")) ? q.get("committee") : "";
  // The words as searched (D-078): exact=1 in the address searches only the typed words; otherwise the broad grammar runs.
  const exact = q.get("exact") === "1";
  let b = Q.broaden(text, issues, { exact });
  const match = b.match; // empty exactly when no word was typed, in either grammar
  const sort = ["new", "old"].includes(q.get("sort")) ? q.get("sort") : match ? "best" : "new";
  const page = Math.max(1, Math.floor(Number(q.get("page"))) || 1);

  const run = () => {
    const f = { match: b.match, convention: conv?.[2] || "", committee, year: year ? Number(year) : "" };
    const byYear = Q.yearCounts(f), total = Q.searchTotal(f);
    const pages = Math.max(1, Math.ceil(total / PAGE)), at = Math.min(page, pages);
    return { byYear, total, pages, at, hits: Q.search(f, { sort, limit: PAGE, offset: (at - 1) * PAGE }) };
  };
  // If the browser's SQLite refuses the broad query, the typed words are searched exactly and the page says so.
  let fellBack = false, res;
  try { res = run(); } catch (e) {
    if (exact) throw e;
    b = Q.broaden(text, [], { exact: true });
    fellBack = true;
    res = run();
  }
  const { byYear, total, pages, at, hits } = res;

  const state = { q: text, year, convention: conv?.[0] || "", committee, exact: exact ? "1" : "", sort: sort === "best" || sort === (match ? "" : "new") ? "" : sort, page: "" };
  const href = changes => {
    const p = { ...state, ...changes };
    return "#/?" + new URLSearchParams(Object.entries(p).filter(([, v]) => v !== "" && v != null));
  };
  lastSearch = href({ page: at > 1 ? at : "" });
  const filtered = Boolean(year || conv || committee);
  // The Searched block and its one link between the two searches; each link is offered only when it would change the words searched.
  const exactNow = exact || fellBack;
  const searched = searchedHTML(b, {
    exact: exactNow,
    hrefExact: !exactNow && b.match !== Q.ftsMatch(text) ? href({ exact: "1", page: "" }) : "",
    hrefBroad: exact && Q.broaden(text, issues).match !== b.match ? href({ exact: "", page: "" }) : "",
  });

  const option = (value, label, current) => `<option value="${esc(value)}"${value === current ? " selected" : ""}>${esc(label)}</option>`;
  const yearsWith = [...byYear.keys()].filter(Boolean).sort((a, b) => b - a);
  if (year && !yearsWith.includes(Number(year))) yearsWith.unshift(Number(year));
  // Year chips (UI-1 D14): out of the tab order, since the Year select is the keyboard path; hidden on phones.
  const chips = yearsWith.map(y => {
    const n = byYear.get(y) || 0, on = String(y) === year;
    const what = (match ? " matching resolution" : " resolution") + (n === 1 ? "" : "s");
    return `<a class="ychip" id="y${y}" tabindex="-1" href="${href({ year: on ? "" : y })}"${on ? ' aria-current="true"' : ""}>${y} <span class="yn">${num(n)}<span class="visually-hidden">${what}</span></span></a>`;
  });
  const sortName = { best: "best match first", new: "newest first", old: "oldest first" }[sort];

  document.title = text ? `${text}, ResIST search` : "ResIST, ATNI Resolutions";
  main.innerHTML = `<div class="wrap wide search-view">
    <h1 tabindex="-1">What has ATNI already resolved?</h1>
    <form class="search-form" role="search" id="search-form">
      <label class="visually-hidden" for="q">Search the resolutions</label>
      <div class="search-row">
        <input id="q" type="search" name="q" value="${esc(text)}" autocomplete="off" spellcheck="false"
          placeholder="Such as salmon or 23-40">
        <button class="btn primary" type="submit">Search</button>
      </div>
      ${exact ? '<input type="hidden" name="exact" value="1">' : ""}
      <p class="meta search-note">${num(build.resolutions)} resolutions from ${build.year_min} to ${build.year_max}. Search runs in this browser; nothing you type is sent anywhere.</p>
      ${searched}
      ${fellBack ? '<div class="notice" id="search-fallback" role="status"><p>The broader search did not run in this browser, so your words were searched exactly.</p></div>' : ""}
      ${text && !exact && issuesRefused ? '<p class="meta" id="issues-note">Policy Sentinel issue names could not be loaded here, so no names are added to your words.</p>' : ""}
      ${chips.length ? `<nav class="ychips" aria-label="${match ? "Matching resolutions" : "Resolutions"} by convention year">${chips.join("")}</nav>` : ""}
      <div class="filters">
        <label class="field"><span>Year</span><select id="f-year" name="year">${option("", "All years", year)}${yearsWith.map(y => option(String(y), `${y} (${num(byYear.get(y) || 0)})`, year)).join("")}</select></label>
        <label class="field"><span>Convention</span><select id="f-convention" name="convention">${option("", "All", state.convention)}${CONVENTIONS.map(c => option(c[0], c[1], state.convention)).join("")}</select></label>
        <label class="field"><span>Committee</span><select id="f-committee" name="committee">${option("", "All committees", committee)}${committees().map(c => option(c, c, committee)).join("")}</select></label>
        <label class="field"><span>Sort</span><select id="f-sort" name="sort">${match ? option("", "Best match", state.sort) : option("", "Newest", state.sort)}${match ? option("new", "Newest", state.sort) : ""}${option("old", "Oldest", state.sort)}</select></label>
      </div>
    </form>
    <div class="results-head">
      <p class="count-line" id="results-count">${total ? `${plural(total, match ? "match" : "resolution", match ? "matches" : "resolutions")}${year ? ` in ${year}` : ""}, ${sortName}` : "No matches"}</p>
      ${filtered && total ? `<a href="${href({ year: "", convention: "", committee: "" })}" id="clear-filters">Clear filters</a>` : ""}
    </div>
    ${hits.length ? `<ol class="results">${hits.map(h => {
      const meta = [h.convention_name, h.convention_year, h.convention_location, h.committee].filter(Boolean).map(esc).join(", ");
      const snipHtml = h.snip ? esc(squash(h.snip)).replace(/\u0002/g, "<mark>").replace(/\u0003/g, "</mark>") : "";
      return `<li class="result">
        <span class="num">${esc(h.resolution_number)}</span>
        <div class="result-body">
          <h2><a href="#/r/${h.id}">${esc(h.title)}</a></h2>
          <p class="meta">${meta}${h.needs_review ? ' <span class="chip review">OCR, unreviewed</span>' : ""}</p>
          ${snipHtml ? `<p class="snip">${snipHtml}</p>` : ""}
          <div class="acts"><button type="button" class="btn small collect" data-rkind="resolution" data-rid="${Number(h.id)}" data-rkey="${esc(h.document_id)}"
            aria-pressed="false" aria-label="Collect resolution ${esc(h.resolution_number)}">Collect</button></div>
        </div></li>`;
    }).join("")}</ol>` : `<div class="empty-state">
      <h2>Nothing Matched</h2>
      <p>No resolution matches ${text ? `the words “${esc(text)}”` : "this selection"}${filtered ? " with these filters" : ""}.</p>
      <p>${filtered ? `<a class="btn" href="${href({ year: "", convention: "", committee: "", page: "" })}">Clear filters</a>` : ""}
        ${text ? `<a class="btn quiet" href="#/">Clear the search</a>` : ""}</p>
      ${text && !filtered ? `<p class="meta">Every word must appear in a resolution${exactNow ? "" : ", and a word also matches longer words that start with it"}. Try fewer words or a different spelling.</p>` : ""}
    </div>`}
    ${pages > 1 ? `<nav class="pager" aria-label="Pages">
      ${at > 1 ? `<a class="btn" href="${href({ page: at - 1 > 1 ? at - 1 : "" })}">Previous page</a>` : ""}
      <span>Page ${num(at)} of ${num(pages)}</span>
      ${at < pages ? `<a class="btn" href="${href({ page: at + 1 })}">Next page</a>` : ""}</nav>` : ""}
  </div>`;

  const form = main.querySelector("#search-form");
  const go = () => {
    const f = new FormData(form);
    location.hash = "#/?" + new URLSearchParams([...f].filter(([, v]) => v));
  };
  form.addEventListener("submit", e => { e.preventDefault(); go(); });
  form.querySelectorAll("select").forEach(s => s.addEventListener("change", go));
}

/* Detail */
// A carried clause's provenance, exactly as the draft stores it.
const sourceFrom = (r, s, url) => ({
  resolutionId: r.id, number: r.resolution_number, title: r.title, year: r.convention_year,
  convention: r.convention_name, documentId: r.document_id, statementType: s.t, index: s.i, text: s.text,
  url: url || "",
});
// The database's record for a claimed source: the same statement text in the same ATNI document, or null.
function storedSource(claim) {
  const s = Q.storedStatements(String(claim?.statementType ?? ""), String(claim?.text ?? ""), String(claim?.documentId ?? ""));
  const hit = s.find(x => x.i === claim?.index) ?? s[0];
  if (!hit) return null;
  const r = Q.resolution(hit.resolution_id);
  return sourceFrom(r, hit, Q.sourceUrls(r.document_id)[0]);
}

// A clause's text with a button.cmark on each citation; segments() indexes the stored text, each piece is escaped.
const markedText = (s, marks) => marks?.length
  ? segments(s.text, marks).map(p => p.span
    ? `<button type="button" class="cmark" id="m-${Number(p.span.c.id)}" data-mark="${Number(p.span.c.id)}" aria-expanded="false" aria-controls="pop-${Number(p.span.c.id)}">${esc(p.text)}</button>`
    : esc(p.text)).join("")
  : esc(squash(s.text));
// A carried citation's provenance, in the draft's key order (D11). c is a cite row: s0 and s1 are its UTF-16 offsets
// in the stored clause s, whose type, 0-based index and page it carries; position is the clause's 1-based position.
const citeSourceFrom = (r, s, c, position, url) => ({
  resolutionId: r.id, number: r.resolution_number, title: r.title, year: r.convention_year, documentId: r.document_id,
  statementType: s.t, index: s.i, position, page: Number.isInteger(s.p) ? s.p : null, start: c.s0, end: c.s1, text: c.text,
  url: url || "",
});
// The database's record for a claimed carried citation (D15): undefined when the export has no cite table, null when
// it holds none at those offsets, else the source exactly as carrying it now would make it.
function storedCiteSource(claim) {
  let row;
  try { row = Q.storedCite(claim?.documentId, claim?.statementType, claim?.index, claim?.start, claim?.end); } catch { return null; }
  if (row === undefined) return undefined;
  const r = row && Q.resolution(row.resolution_id);
  return r ? citeSourceFrom(r, { t: row.t, i: row.i, p: row.p }, row, row.pos, Q.sourceUrls(r.document_id)[0]) : null;
}

// The database's record for a collected item (D-078): the same document and, for a statement, the same text; or null.
// Found items are rebuilt from the record, so a changed title, link or page replaces the stored one.
function storedItem(item) {
  const id = Q.resolutionByDocument(item.documentId);
  const r = id && Q.resolution(id);
  if (!r) return null;
  const url = Q.sourceUrls(r.document_id)[0];
  if (item.kind === "resolution") return resolutionItem(r, url);
  const same = Q.statements(r.id).filter(s => s.t === item.statementType && s.text === item.text);
  const hit = same.find(s => s.i === item.index) ?? same[0];
  return hit ? statementItem(r, hit, url) : null;
}

const KIND = { executive_order: "Executive order", usc: "United States Code", public_law: "Public law", cfr: "Code of Federal Regulations",
  treaty: "Treaty", federal_register: "Federal Register", federal_law: "Federal law", resolution_number: "Resolution number, issuer not stated",
  instrument: "Instrument or standard" };
const kindLabel = c => c.kind === "prior_atni_resolution" ? `ATNI resolution${c.l ? "" : ", not in this collection"}`
  : c.kind === "ncai_resolution" ? "NCAI resolution, not in this collection" : KIND[c.kind] || "Other";
const LAWS = new Set(["executive_order", "usc", "public_law", "cfr", "treaty", "federal_register", "federal_law"]);
const groupOf = c => c.l || c.kind === "prior_atni_resolution" || c.kind === "resolution_number" ? 0 : LAWS.has(c.kind) ? 1 : 2;
const WORD = { whereas: "WHEREAS", resolved: "RESOLVED" };

// The lookup control for a federal citation: the static face opens the Sentinel dialog; the local face opens
// Policy Sentinel in a new tab and shows the words to copy (UI-1 D12). idp is the words block's id.
function lookupControl(c, idp) {
  if (c.l || !FEDERAL_TYPES.has(c.kind)) return "";
  const q = lookupWords(c.text, c.kind);
  if (!q) return ""; // a federal citation with no readable number has nothing to look up
  return isLookupLive()
    ? `<button type="button" class="btn small lookup" data-look="${Number(c.id)}" aria-label="Look up in Policy Sentinel: ${esc(q)}">Look up in Policy Sentinel</button>`
    : `<button type="button" class="btn small lookup" data-look="${Number(c.id)}" aria-expanded="false" aria-controls="${idp}" aria-label="Open Policy Sentinel, ${esc(q)}">Open Policy Sentinel</button>${wordsHTML(q, idp)}`;
}
// The popover of one mark, filled when it opens so the insert point it names is the current one.
function popHTML({ c, s, where }) {
  const id = Number(c.id), ip = store.insertPoint;
  return `<p class="cpop-h" id="pop-${id}-h"><b>${esc(squash(c.text))}</b> <span class="meta">${esc(kindLabel(c))}</span></p>
    <p class="meta cite-where">In ${esc(where)}${Number.isInteger(s.p) ? `, page ${s.p}` : ""}</p>
    <div class="acts">
      <button type="button" class="btn small primary" data-add="${id}" data-at="auto">${ip ? `Add to draft at ${esc(ip.label)}` : "Add to draft as a new WHEREAS"}</button>
      ${ip ? `<button type="button" class="btn small" data-add="${id}" data-at="new">Add as a new WHEREAS instead</button>` : ""}
      ${lookupControl(c, `sw-c${id}`)}
      ${c.l ? `<a class="btn small" href="#/r/${Number(c.l)}">Open Resolution ${esc(c.n)}</a>` : ""}
      <button type="button" class="btn small quiet" data-close-pop>Close</button>
    </div>`;
}

function detailView(id) {
  const r = Number.isInteger(id) ? Q.resolution(id) : null;
  if (!r) {
    document.title = "Resolution not found, ResIST";
    main.innerHTML = `<div class="wrap wide"><h1 tabindex="-1">Resolution Not Found</h1>
      <p>No resolution has this address. It may have been typed or copied incompletely.</p>
      <p><a class="btn" href="${esc(lastSearch)}">Back to search</a></p></div>`;
    return;
  }
  const statements = Q.statements(id);
  const cites = Q.citations(id);
  const citedBy = Q.citedBy(id);
  const committee = Q.committeesOf(id);
  const urls = Q.sourceUrls(r.document_id);
  const where = [r.convention_name, r.convention_year, r.convention_location].filter(Boolean);

  const source = s => sourceFrom(r, s, urls[0]);

  // Each anchored citation becomes a mark in its clause, when its span fits the clause text and the one before it (D18).
  const posOf = new Map(), marksOf = new Map(), info = new Map();
  for (const type of ["resolved", "whereas"]) statements.filter(s => s.t === type).forEach((s, i) => posOf.set(s.id, i + 1));
  const stById = new Map(statements.map(s => [s.id, s]));
  for (const c of cites) {
    const s = stById.get(c.sid), list = s && (marksOf.get(s.id) ?? marksOf.set(s.id, []).get(s.id));
    if (!s || !Number.isInteger(c.s0) || !Number.isInteger(c.s1) || c.s0 < (list.at(-1)?.end ?? 0) || c.s0 >= c.s1 || c.s1 > s.text.length) continue;
    list.push({ start: c.s0, end: c.s1, c });
    info.set(c.id, { c, s, where: `${WORD[s.t]} ${posOf.get(s.id)}`, source: () => citeSourceFrom(r, s, c, posOf.get(s.id), urls[0]) });
  }
  detail = { cites: info, byId: new Map(cites.map(c => [c.id, c])) };

  const sections = ["resolved", "whereas"].map(type => {
    const list = statements.filter(s => s.t === type);
    const word = type === "resolved" ? "RESOLVED" : "WHEREAS";
    const rowsHtml = list.map((s, i) => {
      const key = keyOf(source(s)), std = isStandard(s.text);
      const lead = type === "resolved" ? resolvedLead(i, list.length) : "WHEREAS,";
      // The page the clause begins on, display only (UI-1 D3/D4); nothing when the export does not know it.
      const pg = Number.isInteger(s.p) ? `<span class="pg"><span aria-hidden="true">p. ${s.p}</span><span class="visually-hidden">page ${s.p}</span></span>` : "";
      return `<li class="clause" data-key="${esc(key)}">
        <span class="clause-lead"><b>${esc(lead)}</b>${pg}</span>
        <div class="clause-text"><p>${markedText(s, marksOf.get(s.id))}</p>${(marksOf.get(s.id) ?? []).map(m =>
          `<div class="cpop" id="pop-${Number(m.c.id)}" role="group" aria-labelledby="pop-${Number(m.c.id)}-h" hidden></div>`).join("")}
          ${std ? '<span class="chip">ATNI standard text</span>' : ""}
          ${hasPageHeader(s.text) ? '<p class="meta header-note">Includes page-header text from the PDF; you can remove it in your draft.</p>' : ""}
        </div>
        <div class="clause-acts">
          <button type="button" class="btn small carry" data-key="${esc(key)}" data-type="${type}" data-i="${i}"
            aria-pressed="false" aria-label="Add to draft, ${word} ${i + 1}">Add to draft</button>
          <button type="button" class="btn small collect" data-rkind="statement" data-rid="${Number(r.id)}" data-rtype="${type}" data-ri="${Number(s.i)}"
            data-rkey="${esc(key)}" aria-pressed="false" aria-label="Collect ${word} ${i + 1}">Collect</button>
        </div>
      </li>`;
    }).join("");
    const title = type === "resolved" ? "Resolved" : "Whereas";
    return `<section class="clauses" aria-labelledby="h-${type}">
      <div class="section-head"><h2 id="h-${type}" tabindex="-1">${title} <span class="n">${list.length}</span></h2>
        ${list.some(s => !isStandard(s.text)) ? `<button type="button" class="btn small bulk" data-type="${type}">Add all ${word} clauses</button>` : ""}</div>
      ${list.length ? `<ol class="clause-list">${rowsHtml}</ol>`
        : `<p class="meta">No ${word} clause was recognized in this document. The full text below, and the PDF, have it.</p>`}
    </section>`;
  }).join("");

  // One aside item per distinct citation (kind, words, link), however many clauses it is cited in (D18).
  const distinct = new Map();
  for (const c of cites) {
    const key = `${c.kind}|${squash(c.text)}|${c.l ?? ""}`;
    const it = distinct.get(key) ?? distinct.set(key, { c, words: squash(c.text), marks: [] }).get(key);
    if (info.has(c.id)) it.marks.push(info.get(c.id));
  }
  const citeItem = ({ c, words, marks }) => {
    const m = marks[0];
    const head = c.l ? `<a href="#/r/${Number(c.l)}">${esc(words)}</a>` : `<span class="cite-text">${esc(words)}</span>`;
    const sub = c.l ? (c.tt ? `<span class="meta">${esc(c.tt)}</span>` : "") : `<span class="meta">${esc(kindLabel(c))}</span>`;
    const where = m ? `Cited in ${marks.map(x => `<a href="#m-${Number(x.c.id)}" data-jump="m-${Number(x.c.id)}">${esc(x.where)}${Number.isInteger(x.s.p) ? `, p. ${x.s.p}` : ""}</a>`).join(", ")}`
      : build.refs?.version === 1 ? "Not found in a clause; it is in the full text." : ""; // a stale export has no anchors (D9)
    const add = m ? `<button type="button" class="btn small" data-add="${Number(m.c.id)}" data-at="auto" aria-label="Add to draft: ${esc(words)}">Add to draft</button>` : "";
    const acts = add + lookupControl(c, `sw-a${Number(c.id)}`);
    return `<li data-cite="${Number(c.id)}">${head}${sub}${where ? `<span class="meta cite-where">${where}</span>` : ""}${acts ? `<div class="acts">${acts}</div>` : ""}</li>`;
  };
  const groups = [["Earlier ATNI Resolutions", []], ["Laws, Treaties and Executive Orders", []], ["Other Citations", []]];
  for (const it of distinct.values()) groups[groupOf(it.c)][1].push(citeItem(it));
  const citeGroups = groups.filter(([, items]) => items.length)
    .map(([h, items]) => `<div class="cgroup"><h3>${h}</h3><ul class="squares cites">${items.join("")}</ul></div>`).join("");
  const federal = cites.some(c => !c.l && FEDERAL_TYPES.has(c.kind));
  const live = isLookupLive();
  const fact = (dt, dd) => dd ? `<dt>${dt}</dt><dd>${dd}</dd>` : "";
  // An export without page_number (older build) shows no page facts at all (D2).
  const unknown = build.page_numbers === true ? statements.filter(s => !Number.isInteger(s.p)).length : 0;
  const newTab = '<span class="visually-hidden"> (opens in a new tab)</span>';
  const jumpTo = (id, label, n) => `<a href="#${id}" data-jump="${id}">${label}${n === undefined ? "" : ` <b>${num(n)}</b>`}</a>`;
  const jump = `<nav class="jump" aria-label="On this page">${jumpTo("h-resolved", "Resolved", statements.filter(s => s.t === "resolved").length)}${
    jumpTo("h-whereas", "Whereas", statements.filter(s => s.t === "whereas").length)}${
    distinct.size ? jumpTo("h-cites", "Citations", distinct.size) : ""}${jumpTo("h-record", "Record")}</nav>`;

  document.title = `Resolution ${r.resolution_number}, ResIST`;
  main.innerHTML = `<div class="wrap wide detail-view">
    <p class="back">${backTo ? `<a href="${backTo}">Back to your research</a>`
      : `<a href="${esc(lastSearch)}">${lastSearch === "#/" ? "Search all resolutions" : "Back to results"}</a>`}</p>
    <header class="detail-head">
      ${where.length ? `<p class="eyebrow">${where.map(esc).join(", ")}</p>` : ""}
      <h1 tabindex="-1">Resolution ${esc(r.resolution_number)}</h1>
      <p class="lead">${esc(r.title)}</p>
      <div class="acts"><button type="button" class="btn small collect" data-rkind="resolution" data-rid="${Number(r.id)}" data-rkey="${esc(r.document_id)}"
        aria-pressed="false" aria-label="Collect resolution ${esc(r.resolution_number)}">Collect resolution</button></div>
    </header>
    ${r.needs_review ? `<div class="notice"><p>This document is a scan. Its text was read by OCR and has not been reviewed; the PDF has the authoritative wording.</p></div>` : ""}
    ${jump}
    <div class="detail-grid">
      <div class="detail-main">
        ${sections}
        <details class="full-text"><summary>Full extracted text</summary><pre>${esc(r.full_text)}</pre></details>
      </div>
      <aside class="detail-aside" aria-label="About this resolution">
        <h2 class="aside-h" id="h-record" tabindex="-1">Record</h2>
        <dl class="facts">
          ${fact("Convention", esc(r.convention_name))}${fact("Year", esc(r.convention_year))}
          ${fact("Location", esc(r.convention_location))}${fact("Committee", committee.map(esc).join(", "))}
          ${fact("Adopted", esc(usDate(r.date_adopted)))}
          ${fact("Clause pages", unknown ? `Page unknown for ${num(unknown)} of ${plural(statements.length, "clause")}` : "")}
          ${fact("Source PDF", urls.map(u => `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(fileName(u))}${newTab}</a>`).join("<br>") || "Not recorded")}
        </dl>
        ${cites.length ? `<h2 class="aside-h" id="h-cites" tabindex="-1">Citations <span class="n">${distinct.size}</span></h2>
          ${federal ? `<p class="meta">${live ? "Look up opens a Policy Sentinel panel. A search there sends only the words shown in its box, never your draft."
            : "Policy Sentinel opens in a new tab. This copy of ResIST never contacts it: press the button under a citation to show its search words, copy them and paste them there."}</p>` : ""}
          ${citeGroups}` : ""}
        ${citedBy.length ? `<h2 class="aside-h">Cited By <span class="n">${citedBy.length}</span></h2>
          <ul class="squares cites">${citedBy.map(c => `<li><a href="#/r/${c.id}">${esc(c.resolution_number)}</a><span class="meta">${esc(c.title)}</span></li>`).join("")}</ul>` : ""}
      </aside>
    </div>
  </div>`;

  const byType = type => statements.filter(s => s.t === type);
  main.querySelectorAll("button.carry").forEach(b => b.addEventListener("click", () => {
    const s = byType(b.dataset.type)[Number(b.dataset.i)];
    if (store.isCarried(b.dataset.key)) { store.uncarry(b.dataset.key); toast("Removed from your draft"); }
    else if (store.carry(source(s))) toast("Added to your draft");
  }));
  main.querySelectorAll("button.bulk").forEach(b => b.addEventListener("click", () => {
    const word = b.dataset.type === "resolved" ? "RESOLVED" : "WHEREAS";
    const added = byType(b.dataset.type).filter(s => !isStandard(s.text) && store.carry(source(s))).length;
    toast(added ? `Added ${plural(added, `${word} clause`)} to your draft` : `Every ${word} clause is already in your draft`);
  }));
}

/* About */
function aboutView() {
  const dated = Q.datedCount();
  document.title = "About ResIST";
  main.innerHTML = `<div class="wrap wide about-view">
    <h1 tabindex="-1">About ResIST</h1>
    <p class="lead measure">ResIST makes the resolutions of the Affiliated Tribes of Northwest Indians searchable: what ATNI resolved, when, through which committee, and on what cited authority.</p>
    <div class="about-grid">
      <section><h2>ATNI's Own Words</h2>
        <p>Every word shown is ATNI's published text, quoted verbatim. Clauses are separated by fixed rules from the PDFs ATNI publishes at <a href="https://atnitribes.org/resolutions/" rel="noopener">atnitribes.org</a>. Each record links its source PDF. The PDF is authoritative.</p>
        <p>Nothing on this site is generated, summarized or paraphrased by AI.</p></section>
      <section><h2>Search in This Browser</h2>
        <p>The whole collection (${num(build.resolutions)} documents, ${build.year_min} to ${build.year_max}) downloads once and is searched here with SQLite full-text search, best matches first. Every word you type must appear in a resolution, and a word of four or more letters also matches longer words that start with it.${issuesOk ? " Typing the name of an issue that Policy Sentinel lists also searches the names and references it gives for that issue." : ""} The page shows exactly what was searched and links to a search of only your words. Nothing you type is sent anywhere.</p></section>
      <section><h2>Research</h2>
        <ul class="squares">
          <li>“Collect” on a result, a resolution or a single WHEREAS or RESOLVED clause keeps it in your research, word for word, with its source PDF link and the clause's page when ATNI's PDF gives it.</li>
          <li>Open Research to review what you collected, remove an item and undo, download it as JSON or text, or print it. “Add to draft” there carries a clause into your draft.</li>
          <li>Your research stays in this browser, apart from your draft. It is never sent anywhere. Nothing is summarized or rewritten.</li>
        </ul></section>
      ${issuesOk ? `<section><h2>Names From Policy Sentinel</h2>
        <p>Issue names and the laws and regulations they rest on come only from a copy of the reviewed issue table of <a href="${SENTINEL_HOME}" rel="noopener">Policy Sentinel</a>, kept with this site and last reviewed ${esc(usDate(issues.map(i => i.reviewedOn).sort().at(-1)))}. Matches in resolutions come only from ATNI's published text. The copy (<a href="issues.json">issues.json</a>) is Policy Sentinel's, under the <a href="https://polyformproject.org/licenses/noncommercial/1.0.0" rel="noopener">PolyForm Noncommercial License 1.0.0</a>; its required notice is inside the file.</p>
        <p>A result is a text match: the words appear in that resolution. It is not a finding or a legal conclusion.</p></section>` : ""}
      <section><h2>The Draft Tool</h2>
        <ul class="squares">
          <li>On any resolution, “Add to draft” carries a WHEREAS or RESOLVED clause into your draft, word for word, with a record of where it came from.</li>
          <li>The draft starts from ATNI's form text in the official resolution template. You can type your own clauses, reorder them and edit any of them; an edited clause is labelled “Edited”, and its original stays on record.</li>
          <li>“Download Word document” produces the resolution and the Resolution Submission Form in ATNI's format. Convention details that are not announced yet stay as fillable placeholders you can complete in Word.</li>
          <li>Your draft stays in this browser and in files you download. It is never sent anywhere. Nothing suggests, completes or rewrites clause text.</li>
        </ul></section>
      <section><h2>Policy Sentinel Lookups</h2>
        <p><a href="${SENTINEL_HOME}" rel="noopener">Policy Sentinel</a> is ATNI Climate's policy monitor. ${isLookupLive()
          ? "A lookup sends only the search words shown in its box, by default a public citation such as “Executive Order 13175” from a published resolution, to Policy Sentinel's service."
          : "On this local copy, ResIST never contacts Policy Sentinel. The lookup button opens it in a new tab and shows the search words to copy."} Your draft is never sent.</p>
        <p>The notes it returns are rule-based flags (consultation language, Tribal references, dates and deadlines, cross references, status signals) that quote the policy text. They are not legal conclusions.</p></section>
      <section><h2>Known Limits</h2>
        <ul class="squares">
          <li>${num(build.needs_review)} scanned documents were read by OCR and are not yet reviewed; they carry an “OCR, unreviewed” label.</li>
          <li>Some clauses that cross a page break include the PDF's page-header text. They are marked, and the draft tool can remove it.</li>
          <li>Adoption dates come from file names where ATNI provided them (${num(dated)} of ${num(build.resolutions)}).</li>
          <li>Some resolution numbers appear on more than one PDF; amended or re-posted versions are kept separate.</li>
        </ul></section>
      <section><h2>Data and Code</h2>
        <p>Under the <a href="${TSDF}" rel="noopener">Tiered Sovereign Data Framework</a>, ATNI's web-published resolutions are T0: public. This site carries no other material.</p>
        <p>Code: <a href="${CODE}" rel="noopener">github.com/atniclimate/ResIST</a>, under the <a href="https://polyformproject.org/licenses/noncommercial/1.0.0" rel="noopener">PolyForm Noncommercial License 1.0.0</a>. Required Notice: Copyright Affiliated Tribes of Northwest Indians (https://atnitribes.org)</p>
        <p class="meta">Built ${esc(usDate(build.built) || build.built)}.</p></section>
    </div>
  </div>`;
}

/* Start */
// "#main" is not a route: the skip link moves focus itself, so the router never sees it.
document.querySelector(".skip")?.addEventListener("click", e => { e.preventDefault(); main.focus(); });
addEventListener("hashchange", route);
route();
async function loadDatabase() {
  if (loadingDatabase || ready || loadError) return;
  loadingDatabase = true;
try {
  await load(f => {
    const pct = Math.round(f * 100), status = document.getElementById("status"), bar = document.getElementById("loadbar");
    if (status) status.textContent = `Loading ${build ? num(build.resolutions) + " resolutions" : "the resolutions"}, ${pct}%`;
    if (bar) bar.style.width = pct + "%";
  });
  allowLookup(caps?.sentinel === true); // the local face links out instead (D-059 item 5)
  refreshLookupLabel(); // an open draft rendered before this point shows the pre-load label (D12)
  ready = true;
  store.verifyWith(storedSource, build?.refs?.version === 1 ? storedCiteSource : null);
  const dropped = await changeCollection(() => collection.verifyWith(storedItem));
  if (dropped) toast(`${plural(dropped, "collected item")} ${dropped === 1 ? "is" : "are"} not in this version of the data and ${dropped === 1 ? "was" : "were"} removed from your research.`);
} catch (e) {
  loadError = `The resolution database did not load (${e.message}). Reload the page to try again.`;
}
main.removeAttribute("aria-busy");
if (!["/draft", "/reports", "/research"].includes(parse().path)) {
  route(); // re-rendering an open draft would take focus from the person typing
  if (ready) say("Resolutions loaded");
}
}
