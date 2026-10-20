// ResIST public site: header, router and the search, detail and about views (SPEC 6.1). The draft workspace is
// draft.js; Policy Sentinel lookups are sentinel.js; every database query is a named export of query.js. Every
// string from the database passes through esc(); user search text reaches a query only through Q.ftsMatch() or as
// a bound parameter.
import { load, build, caps } from "./db.js";
import * as Q from "./query.js";
import { esc, local, toast } from "./ui.js";
import { isStandard, hasPageHeader, resolvedLead, usDate, squash } from "./compose.js";
import { store, renderDraft } from "./draft.js";
import { openLookup, allowLookup, lookupWords, FEDERAL_TYPES, SENTINEL_HOME } from "./sentinel.js";

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
const showTheme = () => {
  themeButton.textContent = document.documentElement.dataset.theme === "light" ? "Dark theme" : "Light theme";
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
}
store.subscribe(syncDraft);

/* Router */
function parse() {
  const [path, query = ""] = location.hash.slice(1).split("?");
  return { path: path || "/", q: new URLSearchParams(query) };
}
let lastSearch = "#/", lastView = "";

// The draft workspace never reads the database, so it opens at once; every other view waits for the download.
const LOADING = main.innerHTML;
let ready = false, loadError = "";

function route() {
  const { path, q } = parse();
  const view = path.startsWith("/r/") ? "detail" : path === "/draft" ? "draft" : path === "/about" ? "about" : "search";
  if (!ready && view !== "draft") {
    main.innerHTML = loadError ? `<div class="wrap wide"><div class="notice" role="alert"><p>${esc(loadError)}</p></div></div>` : LOADING;
    lastView = "";
    return;
  }
  const focusId = view === lastView && document.activeElement?.id;
  const firstRender = !lastView;
  try {
    if (view === "detail") detailView(Number(path.slice(3)));
    else if (view === "draft") { document.title = "Draft Resolution, ResIST"; renderDraft(main); }
    else if (view === "about") aboutView();
    else searchView(q);
  } catch (e) {
    main.innerHTML = `<div class="wrap wide"><h1 tabindex="-1">This Page Could Not Be Shown</h1>
      <p>${esc(e.message)}</p><p><a href="#/">Search all resolutions</a></p></div>`;
  }
  document.querySelectorAll(".site-nav a[data-nav]").forEach(a =>
    a.dataset.nav === view || (view === "detail" && a.dataset.nav === "search") ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  syncDraft();
  lastView = view;
  // A filter change keeps focus on the control used; any other route change moves focus to the new h1.
  const keep = focusId && document.getElementById(focusId);
  if (keep) { keep.focus({ preventScroll: true }); return; }
  window.scrollTo(0, 0);
  if (!firstRender) main.querySelector("h1")?.focus({ preventScroll: true });
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
  const match = Q.ftsMatch(text);
  const sort = ["new", "old"].includes(q.get("sort")) ? q.get("sort") : match ? "best" : "new";
  const page = Math.max(1, Math.floor(Number(q.get("page"))) || 1);

  const f = { match, convention: conv?.[2] || "", committee, year: year ? Number(year) : "" };
  const byYear = Q.yearCounts(f);
  const total = Q.searchTotal(f);
  const pages = Math.max(1, Math.ceil(total / PAGE)), at = Math.min(page, pages);
  const hits = Q.search(f, { sort, limit: PAGE, offset: (at - 1) * PAGE });

  const state = { q: text, year, convention: conv?.[0] || "", committee, sort: sort === "best" || sort === (match ? "" : "new") ? "" : sort, page: "" };
  const href = changes => {
    const p = { ...state, ...changes };
    return "#/?" + new URLSearchParams(Object.entries(p).filter(([, v]) => v !== "" && v != null));
  };
  lastSearch = href({ page: at > 1 ? at : "" });
  const filtered = Boolean(year || conv || committee);

  const max = Math.max(1, ...byYear.values());
  const strip = [];
  for (let y = build.year_min; y <= build.year_max; y++) {
    const n = byYear.get(y) || 0, on = String(y) === year;
    // Sparse labels: the ends, every fifth year not crowding an end, and the selected year.
    const label = on || (!(year && Math.abs(y - Number(year)) < 3) && (y === build.year_min || y === build.year_max ||
      (y % 5 === 0 && y - build.year_min > 2 && build.year_max - y > 2)));
    const words = `${y}: ${plural(n, match ? "matching resolution" : "resolution")}`;
    const bar = `<span class="bar" style="height:${n ? Math.max(4, Math.round(n / max * 100)) : 0}%"></span>`;
    const tick = `<span class="tick${label ? "" : " dim"}">${y}</span>`;
    strip.push(n || on
      ? `<a id="y${y}" href="${href({ year: on ? "" : y })}" aria-label="${words}"${on ? ' aria-current="true"' : ""} title="${words}"><span class="col">${bar}</span>${tick}</a>`
      : `<span class="empty" title="${words}"><span class="col">${bar}</span>${tick}</span>`);
  }

  const option = (value, label, current) => `<option value="${esc(value)}"${value === current ? " selected" : ""}>${esc(label)}</option>`;
  const yearsWith = [...byYear.keys()].filter(Boolean).sort((a, b) => b - a);
  if (year && !yearsWith.includes(Number(year))) yearsWith.unshift(Number(year));
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
      <p class="meta search-note">${num(build.resolutions)} resolutions from ${build.year_min} to ${build.year_max}. Search runs in this browser; nothing you type is sent anywhere.</p>
      ${byYear.size ? `<nav class="years" aria-label="${match ? "Matching resolutions" : "Resolutions"} by convention year">${strip.join("")}</nav>` : ""}
      <div class="filters">
        <label class="field"><span>Year</span><select id="f-year" name="year">${option("", "All years", year)}${yearsWith.map(y => option(String(y), String(y), year)).join("")}</select></label>
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
        </div></li>`;
    }).join("")}</ol>` : `<div class="empty-state">
      <h2>Nothing Matched</h2>
      <p>No resolution matches ${text ? `the words “${esc(text)}”` : "this selection"}${filtered ? " with these filters" : ""}.</p>
      <p>${filtered ? `<a class="btn" href="${href({ year: "", convention: "", committee: "", page: "" })}">Clear filters</a>` : ""}
        ${text ? `<a class="btn quiet" href="#/">Clear the search</a>` : ""}</p>
      ${text && !filtered ? `<p class="meta">Every word must appear in a resolution. Try fewer words or a different spelling.</p>` : ""}
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
  const sections = ["resolved", "whereas"].map(type => {
    const list = statements.filter(s => s.t === type);
    const word = type === "resolved" ? "RESOLVED" : "WHEREAS";
    const rowsHtml = list.map((s, i) => {
      const key = keyOf(source(s)), std = isStandard(s.text);
      const lead = type === "resolved" ? resolvedLead(i, list.length) : "WHEREAS,";
      return `<li class="clause" data-key="${esc(key)}">
        <span class="clause-lead">${esc(lead)}</span>
        <div class="clause-text"><p>${esc(squash(s.text))}</p>
          ${std ? '<span class="chip">ATNI standard text</span>' : ""}
          ${hasPageHeader(s.text) ? '<p class="meta header-note">Includes page-header text from the PDF; you can remove it in your draft.</p>' : ""}
        </div>
        <button type="button" class="btn small carry" data-key="${esc(key)}" data-type="${type}" data-i="${i}"
          aria-pressed="false" aria-label="Add to draft, ${word} ${i + 1}">Add to draft</button>
      </li>`;
    }).join("");
    const title = type === "resolved" ? "Resolved" : "Whereas";
    return `<section class="clauses" aria-labelledby="h-${type}">
      <div class="section-head"><h2 id="h-${type}">${title} <span class="n">${list.length}</span></h2>
        ${list.some(s => !isStandard(s.text)) ? `<button type="button" class="btn small bulk" data-type="${type}">Add all ${word} clauses</button>` : ""}</div>
      ${list.length ? `<ol class="clause-list">${rowsHtml}</ol>`
        : `<p class="meta">No ${word} clause was recognized in this document. The full text below, and the PDF, have it.</p>`}
    </section>`;
  }).join("");

  const citeItem = (c, i) => {
    const words = squash(c.text);
    if (c.l) return `<li><a href="#/r/${c.l}">${esc(words)}</a>${c.tt ? `<span class="meta">${esc(c.tt)}</span>` : ""}</li>`;
    const kind = { executive_order: "Executive order", usc: "United States Code", public_law: "Public law", cfr: "Code of Federal Regulations",
      treaty: "Treaty", prior_atni_resolution: "ATNI resolution, not in this collection", other: "Other" }[c.citation_type] || "Other";
    return `<li><span class="cite-text">${esc(words)}</span><span class="meta">${esc(kind)}</span>
      ${FEDERAL_TYPES.has(c.citation_type) ? `<button type="button" class="btn small lookup" data-cite="${i}">Look up in Policy Sentinel</button>` : ""}</li>`;
  };
  const federal = cites.some(c => !c.l && FEDERAL_TYPES.has(c.citation_type));
  const fact = (dt, dd) => dd ? `<dt>${dt}</dt><dd>${dd}</dd>` : "";

  document.title = `Resolution ${r.resolution_number}, ResIST`;
  main.innerHTML = `<div class="wrap wide detail-view">
    <p class="back"><a href="${esc(lastSearch)}">${lastSearch === "#/" ? "Search all resolutions" : "Back to results"}</a></p>
    <header class="detail-head">
      ${where.length ? `<p class="eyebrow">${where.map(esc).join(", ")}</p>` : ""}
      <h1 tabindex="-1">Resolution ${esc(r.resolution_number)}</h1>
      <p class="lead">${esc(r.title)}</p>
    </header>
    ${r.needs_review ? `<div class="notice"><p>This document is a scan. Its text was read by OCR and has not been reviewed; the PDF has the authoritative wording.</p></div>` : ""}
    <div class="detail-grid">
      <div class="detail-main">
        ${sections}
        <details class="full-text"><summary>Full extracted text</summary><pre>${esc(r.full_text)}</pre></details>
      </div>
      <aside class="detail-aside" aria-label="About this resolution">
        <h2 class="aside-h">Record</h2>
        <dl class="facts">
          ${fact("Convention", esc(r.convention_name))}${fact("Year", esc(r.convention_year))}
          ${fact("Location", esc(r.convention_location))}${fact("Committee", committee.map(esc).join(", "))}
          ${fact("Adopted", esc(usDate(r.date_adopted)))}
          ${fact("Source PDF", urls.map(u => `<a href="${esc(u)}" rel="noopener">${esc(fileName(u))}</a>`).join("<br>") || "Not recorded")}
          ${fact("SHA-256", `<code class="sha">${esc(r.document_id)}</code>`)}
        </dl>
        ${cites.length ? `<h2 class="aside-h">Citations <span class="n">${cites.length}</span></h2>
          ${federal ? `<p class="meta">Look up opens a Policy Sentinel panel. A search there sends only the words shown in its box, never your draft.</p>` : ""}
          <ul class="squares cites">${cites.map(citeItem).join("")}</ul>` : ""}
        ${citedBy.length ? `<h2 class="aside-h">Cited By <span class="n">${citedBy.length}</span></h2>
          <ul class="squares cites">${citedBy.map(c => `<li><a href="#/r/${c.id}">${esc(c.resolution_number)}</a><span class="meta">${esc(c.title)}</span></li>`).join("")}</ul>` : ""}
      </aside>
    </div>
  </div>`;

  const byType = type => statements.filter(s => s.t === type);
  main.querySelectorAll("button.carry").forEach(b => b.addEventListener("click", () => {
    const s = byType(b.dataset.type)[Number(b.dataset.i)];
    if (store.isCarried(b.dataset.key)) { store.uncarry(b.dataset.key); toast("Removed from your draft"); }
    else if (store.carry(source(s))) toast("Added to your draft", { href: "#/draft", label: "Open draft" });
  }));
  main.querySelectorAll("button.bulk").forEach(b => b.addEventListener("click", () => {
    const word = b.dataset.type === "resolved" ? "RESOLVED" : "WHEREAS";
    const added = byType(b.dataset.type).filter(s => !isStandard(s.text) && store.carry(source(s))).length;
    toast(added ? `Added ${plural(added, `${word} clause`)} to your draft` : `Every ${word} clause is already in your draft`,
      { href: "#/draft", label: "Open draft" });
  }));
  main.querySelectorAll("button.lookup").forEach(b => b.addEventListener("click", () => {
    const c = cites[Number(b.dataset.cite)];
    openLookup({
      query: lookupWords(c.text, c.citation_type),
      onAddNote: note => { store.addNote(note); toast("Policy note added to your draft", { href: "#/draft", label: "Open draft" }); },
    });
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
        <p>Every word shown is ATNI's published text, quoted verbatim. Clauses are separated by fixed rules from the PDFs ATNI publishes at <a href="https://atnitribes.org/resolutions/" rel="noopener">atnitribes.org</a>. Each record links its PDF and shows the file's SHA-256. The PDF is authoritative.</p>
        <p>Nothing on this site is generated, summarized or paraphrased by AI.</p></section>
      <section><h2>Search in This Browser</h2>
        <p>The whole collection (${num(build.resolutions)} documents, ${build.year_min} to ${build.year_max}) downloads once and is searched here with SQLite full-text search, best matches first. Nothing you type is sent anywhere.</p></section>
      <section><h2>The Draft Tool</h2>
        <ul class="squares">
          <li>On any resolution, “Add to draft” carries a WHEREAS or RESOLVED clause into your draft, word for word, with a record of where it came from.</li>
          <li>The draft starts from ATNI's form text in the official resolution template. You can type your own clauses, reorder them and edit any of them; an edited clause is labelled “Edited”, and its original stays on record.</li>
          <li>“Download Word document” produces the resolution and the Resolution Submission Form in ATNI's format. Convention details that are not announced yet stay as fillable placeholders you can complete in Word.</li>
          <li>Your draft stays in this browser and in files you download. It is never sent anywhere. Nothing suggests, completes or rewrites clause text.</li>
        </ul></section>
      <section><h2>Policy Sentinel Lookups</h2>
        <p><a href="${SENTINEL_HOME}" rel="noopener">Policy Sentinel</a> is ATNI Climate's policy monitor. A lookup sends only the search words shown in its box, by default a public citation such as “Executive Order 13175” from a published resolution, to Policy Sentinel's service. Your draft is never sent.</p>
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
        <p>Code: <a href="${CODE}" rel="noopener">github.com/atniclimate/ResIST</a>, licensed AGPL-3.0-or-later.</p>
        <p class="meta">Built ${esc(usDate(build.built) || build.built)} from commit <code>${esc(build.commit)}</code>; database SHA-256 <code>${esc(String(build.db_sha256).slice(0, 16))}</code>.</p></section>
    </div>
  </div>`;
}

/* Start */
// "#main" is not a route: the skip link moves focus itself, so the router never sees it.
document.querySelector(".skip")?.addEventListener("click", e => { e.preventDefault(); main.focus(); });
addEventListener("hashchange", route);
route();
try {
  await load(f => {
    const pct = Math.round(f * 100), status = document.getElementById("status"), bar = document.getElementById("loadbar");
    if (status) status.textContent = `Loading ${build ? num(build.resolutions) + " resolutions" : "the resolutions"}, ${pct}%`;
    if (bar) bar.style.width = pct + "%";
  });
  allowLookup(caps?.sentinel === true); // the local face links out instead (D-059 item 5)
  ready = true;
  store.verifyWith(storedSource);
} catch (e) {
  loadError = `The resolution database did not load (${e.message}). Reload the page to try again.`;
}
if (parse().path !== "/draft") route(); // re-rendering an open draft would take focus from the person typing
