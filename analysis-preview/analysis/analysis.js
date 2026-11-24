/* The Analysis preview: router, shared filter, list panel, events. The filter lives in the URL hash so a view can
   be linked and Back restores it. Nothing is sent anywhere: no request after the two data files (and, on the first
   visit to Issues, Laws and Wording, its module and its data), no storage but two per-viewer conveniences (theme,
   collected keys) behind try/catch. */
import { esc, fmt, plural } from "./charts.js";
import * as DT from "./data.js";
import * as V from "./views.js";
import { toggleAw, basisKey } from "./basis.js";
const { D, KINDS, ERAS } = DT;

const VIEWS = [
  ["overview", "Overview"],
  ["years", "Years and Conventions"],
  ["committees", "Committees"],
  ["people", "People"],
  ["words", "Words and Titles"],
  ["topics", "Issues, Laws and Wording"],
  ["record", "The Record"],
];
const FILTER_KEYS = ["y0", "y1", "k", "c", "names"];
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const mqWide = matchMedia("(min-width: 48rem)"), mqFull = matchMedia("(min-width: 64rem)");

let S = null, prevKey = "", prevFilterKey = "", pendingFocus = null, pendingScroll = null, lastTrigger = null, lastKey = null, closingByRoute = false;
let collected = new Set();
try { collected = new Set(JSON.parse(localStorage.getItem("resist-mockup-collected") || "[]")); } catch { /* storage unavailable */ }

/* ---------------------------------------------------------------------------------------------------------- */
/* URL                                                                                                         */
function parse() {
  const h = location.hash.slice(1);
  const [path, qs = ""] = (h || "/overview").split("?");
  let view = path.replace(/^\//, "").split("/")[0];
  if (!VIEWS.some(v => v[0] === view)) view = "overview";
  return { view, q: new URLSearchParams(qs) };
}
function readFilters(q) {
  let y0 = +q.get("y0") || D.yMin, y1 = +q.get("y1") || D.yMax;
  y0 = Math.min(Math.max(y0, D.yMin), D.yMax); y1 = Math.min(Math.max(y1, D.yMin), D.yMax);
  if (y0 > y1) [y0, y1] = [y1, y0];
  const k = KINDS.some(x => x.key === q.get("k")) ? q.get("k") : "";
  const c = D.cm[q.get("c")] ? q.get("c") : "";
  return { y0, y1, k, c };
}
function buildHash(view, q, patch = {}) {
  const p = new URLSearchParams(q);
  for (const [k, v] of Object.entries(patch)) { if (v === undefined || v === "" || v === null) p.delete(k); else p.set(k, String(v)); }
  const f = readFilters(p);
  if (f.y0 === D.yMin) p.delete("y0"); if (f.y1 === D.yMax) p.delete("y1");
  const s = p.toString();
  return `#/${view}${s ? "?" + s : ""}`;
}
function makeS() {
  const { view, q } = parse();
  const s = { view, q, f: readFilters(q), names: q.get("names") !== "0", wide: mqWide.matches, full: mqFull.matches, sm: q.get("sm") === "1", ru: q.get("ru") === "1", wy: q.get("wy") === "1" };
  s.href = patch => buildHash(view, q, patch);
  s.hrefView = (v, patch = {}) => {
    const keep = new URLSearchParams(); for (const k of FILTER_KEYS) if (q.has(k)) keep.set(k, q.get(k));
    return buildHash(v, keep, patch);
  };
  s.listHref = spec => buildHash(view, q, { list: spec });
  return s;
}
const go = (hash, o = {}) => { pendingFocus = o.focus || null; pendingScroll = o.scroll ?? null; if (location.hash === hash) route(true); else location.hash = hash; };

/* ---------------------------------------------------------------------------------------------------------- */
/* page chrome                                                                                                  */
const filterSummary = f => `${f.y0 === f.y1 ? f.y0 : `${f.y0} to ${f.y1}`}, ${f.k ? DT.KIND_LABEL[f.k] : "all conventions"}, ${f.c ? D.cm[f.c].name : "all committees"}`;
function updateChrome() {
  const f = S.f, vname = VIEWS.find(v => v[0] === S.view)[1];
  $$("[data-tab]").forEach(a => { const on = a.dataset.tab === S.view; a.setAttribute("href", S.hrefView(a.dataset.tab)); if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  $("#view-name").textContent = vname;
  $("#filter-btn-text").textContent = filterSummary(f);
  const set = (id, v) => { const el = $(id); if (el && el.value !== String(v)) el.value = v; };
  set("#f-y0", f.y0); set("#f-y1", f.y1); set("#f-k", f.k); set("#f-c", f.c);
  const era = ERAS.find(e => e.y0 === f.y0 && e.y1 === f.y1);
  set("#f-era", era ? era.id : "");
  $("#names-sw").checked = S.names;
  const dflt = f.y0 === D.yMin && f.y1 === D.yMax && !f.k && !f.c;
  $("#clear-filters").hidden = dflt;
  $("#clear-filters-2").hidden = dflt;
  document.title = `${vname}, ATNI Resolutions in Numbers (preview)`;
}
function announce(msg) { const a = $("#announce"); a.textContent = ""; setTimeout(() => { a.textContent = msg; }, 30); }
/** Resolutions in the filter, recorded and likely together, for the announcement of a filter change. */
const countFor = f => DT.sumBy(DT.kindMatrix(f.c), f, r => (f.k ? r.s[f.k] + r.l[f.k] : r.sT + r.lT));
let toastTimer = 0;
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 7000); announce(msg); }

/* --stick is the height of whatever glass really sticks. The bars stop sticking on short viewports (analysis.css), so
   then it is 0. html { scroll-padding-top } reads it, so a focused control is never left under the bars. */
function setStick() {
  const hdr = $("#site-header"), fb = $("#fbar");
  const hs = getComputedStyle(hdr).position === "sticky", fs = getComputedStyle(fb).position === "sticky";
  document.documentElement.style.setProperty("--stick", `${(hs ? hdr.offsetHeight : 0) + (fs ? fb.offsetHeight : 0)}px`);
  document.documentElement.style.setProperty("--hdr", `${hdr.offsetHeight}px`);
}
function fillStatic() {
  $("#credit-line").textContent = D.agg.meta.credit;
  $("#banner-key").innerHTML = basisKey(["likely", "open", "nr"], true);
  const bid = D.agg.meta.inputs && D.agg.meta.inputs.library_build_id;
  $("#build-id").textContent = bid ? `Library build ${String(bid).slice(0, 12)}.` : "";
  setStick();
  $("#band-source").innerHTML = `Source: The Resolution Library, an ATNI spreadsheet of ${fmt(D.total)} numbered resolutions, ${D.yMin} to ${D.yMax}, built by Wyatt Ash-Milby at ATNI.${D.builtAt ? ` Counted ${esc(D.builtAt)}.` : ""}`;
  const opt = (v, l, sel) => `<option value="${esc(v)}"${sel ? " selected" : ""}>${esc(l)}</option>`;
  $("#f-y0").innerHTML = D.years.map(y => opt(y, y)).join("");
  $("#f-y1").innerHTML = D.years.map(y => opt(y, y)).join("");
  $("#f-k").innerHTML = opt("", "All conventions") + KINDS.map(k => opt(k.key, k.label)).join("");
  $("#f-c").innerHTML = opt("", "All committees") + D.cmList.map(c => opt(c.key, c.name)).join("");
  $("#f-era").innerHTML = opt("", "Any range") + ERAS.map(e => opt(e.id, e.label)).join("");
}

/* ---------------------------------------------------------------------------------------------------------- */
/* render                                                                                                       */
function mountCharts() {
  $$("[data-chart]", $("#view")).forEach(el => {
    try { V.drawers[el.dataset.chart](el, S); }
    catch (e) { el.innerHTML = `<p class="empty-line">This chart did not draw. The table below has the same numbers.</p>`; console.error(e); }
  });
  syncCollect(document);
}
function renderView() {
  const fn = V["view_" + S.view];
  $("#view").innerHTML = fn(S);
  mountCharts();
  if (S.view === "topics") mountTopics();
}

/* Issues, Laws and Wording. Nothing about it is requested before the first visit. On the first visit its module and its
   data load together; then topics.js draws inside #topics-root and owns every click inside it. Without the module or
   the data the tab says so and nothing else happens. */
let topicsMod = null, topicsData = null, topicsCss = false, topicsSeq = 0;
const siteBase = () => (location.pathname.includes("/analysis-preview/analysis/") ? "../../" : null);
async function loadTopics() {
  if (topicsMod && topicsData) return;
  const [mod, res] = await Promise.all([import("./topics.js"), fetch("../data/topics.json")]);
  if (!res.ok) throw new Error("topics.json not available");
  topicsData = await res.json(); topicsMod = mod;
  if (!topicsCss) { const l = document.createElement("link"); l.rel = "stylesheet"; l.href = "topics.css"; document.head.appendChild(l); topicsCss = true; }
}
async function mountTopics() {
  const root = $("#topics-root");
  if (!root) return;
  const seq = ++topicsSeq;
  try { await loadTopics(); }
  catch { if (seq === topicsSeq && root.isConnected) { root.innerHTML = `<div class="empty-state"><p>Not built yet.</p></div>`; root.dataset.state = "absent"; } return; }
  if (seq !== topicsSeq || !root.isConnected) return;
  root.innerHTML = ""; delete root.dataset.state;
  try {
    const f = S.f;
    await topicsMod.render(root, { data: topicsData, rows: D.rows, filters: { y0: f.y0, y1: f.y1, k: f.k, c: f.c }, names: S.names, listSpec: DT.makeSpec, esc, fmt, plural, siteBase: siteBase(), announce });
    root.dataset.state = "ready";
  } catch (e) { console.error(e); if (root.isConnected) root.innerHTML = `<div class="empty-state"><p>Not built yet.</p></div>`; }
}
/* A redraw replaces the elements it draws. Around a redraw that is not a change of view (a resize, a zoom, a change
   of breakpoint), remember the focused control, the open "Show table" panels and a typed name search, and put them
   back (WCAG 2.4.3, 2.4.7). The focused control is found again by the attribute that says what it opens. */
const FOCUS_ATTRS = ["data-list", "data-patch", "data-setc", "data-switch", "data-pick", "data-cov-pick", "data-csv", "data-goto", "data-find", "data-more", "data-copy"];
const usable = x => !x.closest("[aria-hidden='true']") && x.getClientRects().length > 0; // a roving tabindex of -1 still counts
function candidates(attr, val, tag) {
  const all = $$(`[${attr}="${CSS.escape(val)}"]`).filter(usable);
  const same = all.filter(x => x.tagName.toLowerCase() === tag);
  return same.length ? same : all;
}
function focusKey(el) {
  if (!el || el === document.body) return null;
  if (el.id) return { id: el.id };
  const tag = el.tagName.toLowerCase();
  if (tag === "summary") return { tag, i: $$("summary").indexOf(el) };
  for (const attr of FOCUS_ATTRS) {
    if (!el.hasAttribute(attr)) continue;
    const val = el.getAttribute(attr);
    return { attr, val, tag, i: Math.max(0, candidates(attr, val, tag).indexOf(el)) };
  }
  return null;
}
function refocus(key, was) {
  if (document.activeElement === was) return;
  let el = null;
  if (was && document.contains(was) && usable(was)) el = was;
  else if (key.id) el = document.getElementById(key.id);
  else if (key.tag === "summary") el = $$("summary")[key.i];
  else { const c = candidates(key.attr, key.val, key.tag); el = c[Math.min(key.i, c.length - 1)]; }
  if (!el) return;
  if (el.matches("button.hc")) { $$("table[data-grid] button.hc").forEach(b => { b.tabIndex = -1; }); el.tabIndex = 0; }
  el.focus({ preventScroll: true });
  // A filter that moved into the closed Filters sheet cannot hold focus; the Filters button now stands for it.
  if (document.activeElement !== el && el.closest("#filters")) { const fb = $("#filter-btn"); if (fb && fb.getClientRects().length) fb.focus({ preventScroll: true }); }
}
let lastOut = null; // a control that is hidden by a breakpoint loses focus before the change event fires; remember it
document.addEventListener("focusout", ev => { lastOut = { el: ev.target, to: ev.relatedTarget, t: performance.now() }; });
function keepState(redraw) {
  let was = document.activeElement;
  if ((!was || was === document.body) && lastOut && !lastOut.to && lastOut.el.isConnected && !lastOut.el.getClientRects().length && performance.now() - lastOut.t < 1000) was = lastOut.el;
  const key = focusKey(was);
  const open = $$("#view details").map(d => d.open);
  const find = $("[data-find]") ? $("[data-find]").value : "";
  redraw();
  const again = $$("#view details");
  if (again.length === open.length) again.forEach((d, i) => { d.open = open[i]; });
  const box = $("[data-find]");
  if (box && find) { box.value = find; box.dispatchEvent(new Event("input", { bubbles: true })); }
  if (key) refocus(key, was);
}
function route(force = false) {
  const prev = S;
  S = makeS();
  const key = S.view + "?" + [...S.q].filter(([k]) => k !== "list").map(([k, v]) => k + "=" + v).sort().join("&");
  const filterKey = [S.f.y0, S.f.y1, S.f.k, S.f.c].join("|");
  updateChrome();
  if (key !== prevKey || force) {
    const viewChanged = !prev || prev.view !== S.view;
    renderView();
    prevKey = key;
    const target = pendingScroll ? document.getElementById(pendingScroll) : null;
    if (target) { target.scrollIntoView(); target.setAttribute("tabindex", "-1"); target.focus({ preventScroll: true }); }
    else if (prev && viewChanged && !S.q.get("list")) {
      $("#main").scrollIntoView();
      const h = $("#view h2"); if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: true }); }
      announce(`Showing ${VIEWS.find(v => v[0] === S.view)[1]}.`);
    } else if (pendingFocus) {
      const el = $(pendingFocus); if (el) el.focus({ preventScroll: true });
    }
    if (prev && !viewChanged && !S.q.get("list") && filterKey !== prevFilterKey) announce(`Filters: ${filterSummary(S.f)}. ${plural(countFor(S.f), "resolution", "resolutions")}.`);
    pendingFocus = null; pendingScroll = null;
  }
  prevFilterKey = filterKey;
  syncList();
}
function patchHash(patch, o = {}) { go(S.href(patch), o); }

/* ---------------------------------------------------------------------------------------------------------- */
/* the list behind a number                                                                                     */
let listRows = [], listShown = 0;
function listActions(spec, rows) {
  const out = [];
  if (spec.has) { const m = DT.rowsFor({ ...spec, has: undefined, hasnt: spec.has }).length; if (m) out.push([`Show the ${fmt(m)} where ${DT.FIELDS[spec.has].name} is not recorded`, { ...spec, has: undefined, hasnt: spec.has }]); }
  if (spec.hasnt) { const m = DT.rowsFor({ ...spec, hasnt: undefined, has: spec.hasnt }).length; if (m) out.push([`Show the ${fmt(m)} where ${DT.FIELDS[spec.hasnt].name} is recorded`, { ...spec, hasnt: undefined, has: spec.hasnt }]); }
  if (spec.c && (spec.ly === "c" || !spec.ly)) { const m = DT.rowsFor({ ...spec, ly: "l" }).length; if (m) out.push([`Show the ${fmt(m)} likely`, { ...spec, ly: "l" }]); }
  if (spec.c && (spec.ly === "l" || spec.ly === "w")) { const m = DT.rowsFor({ ...spec, ly: "c" }).length; if (m) out.push([`Show the ${fmt(m)} recorded`, { ...spec, ly: "c" }]); }
  return out.map(([label, sp]) => `<button type="button" class="btn small quiet" data-list="${esc(DT.makeSpec(Object.fromEntries(Object.entries(sp).filter(([, v]) => v !== undefined))))}">${esc(label)}</button>`).join("");
}
function syncList() {
  const dlg = $("#list-dialog"), raw = S.q.get("list");
  if (!raw) { if (dlg.open) { closingByRoute = true; dlg.close(); closingByRoute = false; } $("#list-rows").innerHTML = ""; listRows = []; return; }
  const spec = DT.parseSpec(raw);
  listRows = DT.rowsFor(spec); listShown = 0;
  const heading = `${DT.describe(spec)}: ${plural(listRows.length, "resolution", "resolutions")}`;
  $("#list-title").textContent = heading;
  $("#list-date").textContent = `Counted${D.builtAt ? ` ${D.builtAt}` : ""} from The Resolution Library.`;
  $("#list-related").innerHTML = listActions(spec, listRows);
  $("#list-rows").innerHTML = "";
  $("#list-empty").hidden = listRows.length > 0;
  $("#list-csv").hidden = listRows.length === 0;
  moreRows();
  if (!dlg.open) { lastTrigger = document.activeElement; lastKey = focusKey(lastTrigger); dlg.showModal(); }
  announce(`List opened: ${heading}.`);
  $("#list-body").scrollTop = 0;
}
function moreRows() {
  $("#list-rows").insertAdjacentHTML("beforeend", V.lrows(listRows, S, listShown, 100));
  listShown = Math.min(listRows.length, listShown + 100);
  const more = $("#list-more"); more.hidden = listShown >= listRows.length;
  more.textContent = `Show more (${fmt(listRows.length - listShown)} left)`;
  syncCollect($("#list-rows"));
}

/* ---------------------------------------------------------------------------------------------------------- */
/* collect toggles, CSV, tooltips                                                                               */
function syncCollect(root) { $$("button.collect[data-rkey]", root).forEach(b => b.setAttribute("aria-pressed", String(collected.has(b.dataset.rkey)))); }
function toggleCollect(b) {
  const k = b.dataset.rkey;
  if (collected.has(k)) collected.delete(k); else collected.add(k);
  try { localStorage.setItem("resist-mockup-collected", JSON.stringify([...collected])); } catch { /* storage unavailable */ }
  $$(`button.collect[data-rkey="${CSS.escape(k)}"]`).forEach(x => x.setAttribute("aria-pressed", String(collected.has(k))));
  announce(collected.has(k) ? "Collected (this preview only)." : "Removed (this preview only).");
}
const csvCell = v => { let s = String(v ?? "").replace(/\s+/g, " ").trim(); if (/^[=+@\t\r-]/.test(s) && !/^-?[\d.,]+$/.test(s)) s = "'" + s; return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function tableCsv(table) {
  const cellText = c => { const k = c.cloneNode(true); k.querySelectorAll(".sr-only").forEach(x => x.remove()); return k.textContent; };
  return [...table.querySelectorAll("tr")].map(tr => [...tr.children].map(c => csvCell(cellText(c))).join(",")).join("\n") + "\n";
}
function listCsv() {
  const head = ["Number", "Title", "Title as written, where marked", "Committee as written", "Counted under", "Convention as recorded", ...(S.names ? ["Prepared By as written"] : []), "Origin", "Marks", "Text on this site", "ATNI permalink"];
  const lines = [head.join(",")];
  for (const r of listRows) {
    const mk = DT.marksOf(r), marks = [mk.likely && "likely", mk.open && "open"].filter(Boolean).join(" and ");
    lines.push([r.n, DT.titleText(r) ?? "No title in the record", r.tb ? (r.tw ?? "No title in the record") : "", r.cl ?? "not recorded", r.cs.map(([k, b]) => D.cm[k].name + (b === "l" ? " (likely)" : "")).join("; "), r.cv ?? "not recorded", ...(S.names ? [r.pb ?? ""] : []), r.og ? DT.ORIGIN_LABEL[r.og] + (r.ogb === "l" ? " (likely)" : "") : r.ogb === "o" ? "open" : "", marks, r.s ? "yes" : "no", r.u ?? ""].map(csvCell).join(","));
  }
  lines.push(csvCell(`Counted${D.builtAt ? ` ${D.builtAt}` : ""} from The Resolution Library. ${$("#list-title").textContent}`));
  return lines.join("\n") + "\n";
}
const tip = () => $("#tip");
function showTip(el, ev) {
  const t = tip(); t.textContent = el.dataset.tip; t.hidden = false;
  const pad = 12, w = t.offsetWidth, h = t.offsetHeight;
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + w > innerWidth - 8) x = ev.clientX - w - pad; if (y + h > innerHeight - 8) y = ev.clientY - h - pad;
  t.style.left = Math.max(8, x) + "px"; t.style.top = Math.max(8, y) + "px";
}

/* ---------------------------------------------------------------------------------------------------------- */
/* events                                                                                                       */
function bind() {
  document.addEventListener("click", ev => {
    const t = ev.target;
    // Inside the Issues, Laws and Wording root the module owns every click. Only an element that asks for the list
    // panel by data-list (the contract of TopicsCtx.listSpec) is handled here; nothing else is touched.
    const tr = t.closest("#topics-root");
    if (tr) { const l = t.closest("[data-list]"); if (l && tr.contains(l)) { ev.preventDefault(); lastTrigger = l.closest("button, a") || l; go(S.listHref(l.dataset.list)); } return; }
    const aw = t.closest("button.aw");
    if (aw) { toggleAw(aw); return; }
    const lst = t.closest("[data-list]");
    if (lst) { ev.preventDefault(); lastTrigger = lst.closest("button, a") || lst; go(S.listHref(lst.dataset.list)); return; }
    const setc = t.closest("[data-setc]");
    if (setc) { ev.preventDefault(); patchHash({ c: setc.dataset.setc }, { focus: "[data-setc]" }); return; }
    const patch = t.closest("[data-patch]");
    if (patch) { const [k, v] = patch.dataset.patch.split("="); patchHash({ [k]: v }, { focus: `[data-patch="${patch.dataset.patch}"]` }); return; }
    const col = t.closest("button.collect[data-rkey]");
    if (col) { toggleCollect(col); return; }
    const csv = t.closest("[data-csv]");
    if (csv) { const tb = document.getElementById(csv.dataset.csv); if (tb) download(`resist-${csv.dataset.csvName || "table"}-${S.f.y0}-${S.f.y1}.csv`, tableCsv(tb)); return; }
    const cp = t.closest("[data-copy]");
    if (cp) { const txt = document.getElementById(cp.dataset.copy).textContent; const done = () => { const o = cp.parentElement.querySelector("[data-copied]"); if (o) o.textContent = "Copied."; }; (navigator.clipboard ? navigator.clipboard.writeText(txt).then(done, () => { const r = document.createRange(); r.selectNodeContents(document.getElementById(cp.dataset.copy)); getSelection().removeAllRanges(); getSelection().addRange(r); done(); }) : done()); return; }
    const more = t.closest("[data-more]");
    if (more) { const rows = DT.personRows(more.dataset.key), from = +more.dataset.from; document.getElementById(more.dataset.more).insertAdjacentHTML("beforeend", V.lrows(rows, S, from, 100)); more.dataset.from = from + 100; if (from + 100 >= rows.length) more.remove(); else more.textContent = `Show more (${fmt(rows.length - from - 100)})`; syncCollect(document); return; }
    const gt = t.closest("[data-goto]");
    if (gt) { ev.preventDefault(); go(S.hrefView("record"), { scroll: gt.dataset.goto }); return; }
    const live = t.closest("a[data-live]");
    if (live) { ev.preventDefault(); toast(`On the ResIST site this goes to ${live.dataset.live}. This preview does not include that page yet.`); return; }
    const a = t.closest("a[href^='#']");
    if (a && !a.getAttribute("href").startsWith("#/")) { ev.preventDefault(); const el = document.getElementById(a.getAttribute("href").slice(1)); if (el) { el.setAttribute("tabindex", "-1"); el.scrollIntoView(); el.focus({ preventScroll: true }); } return; }
    if (t.closest("#list-close")) { $("#list-dialog").close(); return; }
    if (t.closest("#list-more")) { moreRows(); return; }
    if (t.closest("#list-csv")) { download(`resist-list-${slugify($("#list-title").textContent)}.csv`, listCsv()); return; }
    if (t.closest("#filter-btn")) { $("#filter-sheet").showModal(); return; }
    if (t.closest("#filter-close")) { $("#filter-sheet").close(); return; }
    if (t.closest("#clear-filters, #clear-filters-2")) { go(buildHash(S.view, S.q, { y0: undefined, y1: undefined, k: undefined, c: undefined }), { focus: "#filter-btn" }); return; }
    if (t.closest("#theme-btn")) { const cur = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light"; setTheme(cur); return; }
    if (t === $("#list-dialog") || t === $("#filter-sheet")) t.close(); // a click on the scrim
  });
  document.addEventListener("change", ev => {
    const t = ev.target;
    if (t.matches("#f-y0, #f-y1")) { let a = +$("#f-y0").value, b = +$("#f-y1").value; if (t.id === "f-y0" && a > b) b = a; if (t.id === "f-y1" && b < a) a = b; patchHash({ y0: a, y1: b, list: undefined }, { focus: "#" + t.id }); }
    else if (t.matches("#f-era")) { const e = ERAS.find(x => x.id === t.value); if (e) patchHash({ y0: e.y0, y1: e.y1, list: undefined }, { focus: "#f-era" }); }
    else if (t.matches("#f-k")) patchHash({ k: t.value, list: undefined }, { focus: "#f-k" });
    else if (t.matches("#f-c")) patchHash({ c: t.value, list: undefined }, { focus: "#f-c" });
    else if (t.matches("#names-sw")) patchHash({ names: t.checked ? undefined : "0", p: undefined }, { focus: "#names-sw" });
    else if (t.matches("[data-switch]")) patchHash({ [t.dataset.switch]: t.checked ? "1" : undefined }, { focus: `[data-switch="${t.dataset.switch}"]` });
    else if (t.matches("[data-pick]")) patchHash({ [t.dataset.pick]: t.value }, { focus: "#" + t.id });
    else if (t.matches("[data-cov-pick]")) { V.setCovPick(t.value); mountCharts(); const el = document.getElementById(t.id); if (el) el.focus(); }
  });
  document.addEventListener("submit", ev => {
    if (ev.target.matches("[data-wordform]")) {
      ev.preventDefault();
      const v = ev.target.querySelector("input").value.trim();
      const next = buildHash(S.view, S.q, { w: v || undefined });
      history.pushState(null, "", next); S = makeS();
      $$("[data-wordout]").forEach(o => { o.innerHTML = V.wordAnswer(S); });
      $$("[data-wordform] input").forEach(i => { i.value = v; });
      syncCollect(document);
    }
  });
  document.addEventListener("input", ev => {
    const t = ev.target;
    if (t.matches("[data-find]")) {
      const q = t.value.trim().toLowerCase(); let n = 0;
      $$("[data-people] li").forEach(li => { const on = !q || li.dataset.name.includes(q); li.hidden = !on; if (on) n++; });
      $("[data-findcount]").textContent = q ? `${plural(n, "name matches", "names match")} “${t.value.trim()}”.` : `${fmt(n)} names.`;
    }
  });
  document.addEventListener("keydown", ev => {
    if (ev.key === "Escape" && !tip().hidden) tip().hidden = true; // WCAG 1.4.13: dismiss extra content without moving the pointer
    const b = ev.target.closest && ev.target.closest("table[data-grid] button.hc");
    if (b && ["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Home", "End"].includes(ev.key)) {
      const td = b.closest("td"), tr = td.parentElement, rows = [...tr.parentElement.rows], r = rows.indexOf(tr), c = [...tr.cells].indexOf(td);
      let nr = r, nc = c;
      if (ev.key === "ArrowRight") nc++; if (ev.key === "ArrowLeft") nc--; if (ev.key === "ArrowDown") nr++; if (ev.key === "ArrowUp") nr--;
      if (ev.key === "Home") nc = 1; if (ev.key === "End") nc = tr.cells.length - 1;
      nr = Math.min(Math.max(nr, 0), rows.length - 1); nc = Math.min(Math.max(nc, 1), tr.cells.length - 1);
      const nb = rows[nr].cells[nc].querySelector("button");
      if (nb) { ev.preventDefault(); b.tabIndex = -1; nb.tabIndex = 0; nb.focus(); }
    }
  });
  document.addEventListener("pointerover", ev => { if (ev.pointerType === "touch") return; const el = ev.target.closest && ev.target.closest("[data-tip]"); if (el) showTip(el, ev); });
  document.addEventListener("pointermove", ev => { if (!tip().hidden) { const el = ev.target.closest && ev.target.closest("[data-tip]"); if (el) showTip(el, ev); } });
  document.addEventListener("pointerout", ev => { if (ev.target.closest && ev.target.closest("[data-tip]")) tip().hidden = true; });
  document.addEventListener("scroll", () => { tip().hidden = true; }, { passive: true });
  $("#list-dialog").addEventListener("close", () => {
    if (!closingByRoute && S.q.get("list")) { history.pushState(null, "", S.href({ list: undefined })); S = makeS(); $("#list-rows").innerHTML = ""; listRows = []; }
    if (lastTrigger && document.contains(lastTrigger)) lastTrigger.focus();
    else if (lastKey) setTimeout(() => refocus(lastKey, null), 0); // the chart was redrawn while the list was open: find the control again
    else $("#view h2")?.focus();
  });
  window.addEventListener("hashchange", () => route());
  window.addEventListener("popstate", () => route());
  let printing = false; // the print layout changes the media queries; do not redraw the view while a print is under way
  const rel = () => { if (!printing) keepState(() => { relocateFilters(); S.wide = mqWide.matches; S.full = mqFull.matches; renderView(); }); };
  mqWide.addEventListener("change", rel); mqFull.addEventListener("change", rel);
  matchMedia("(max-height: 36rem)").addEventListener("change", setStick);
  let timer = 0, lastW = 0;
  new ResizeObserver(() => { setStick(); const w = $("#view").clientWidth; if (Math.abs(w - lastW) < 6) return; lastW = w; clearTimeout(timer); timer = setTimeout(() => { if (!printing && $("#view").children.length) keepState(mountCharts); }, 120); }).observe($("#view"));
  // Printing: open every "Show table" panel so a printed chart keeps its table, then put each panel back.
  let wasOpen = [];
  window.addEventListener("beforeprint", () => { printing = true; if (!wasOpen.length) wasOpen = $$("details.tbl").map(d => d.open); $$("details.tbl").forEach(d => { d.open = true; }); });
  window.addEventListener("afterprint", () => {
    printing = false;
    $$("details.tbl").forEach((d, i) => { d.open = !!wasOpen[i]; });
    wasOpen = [];
    if (S.wide !== mqWide.matches || S.full !== mqFull.matches) rel();
  });
}
const slugify = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);

function relocateFilters() {
  const form = $("#filters"), slot = mqFull.matches ? $("#filter-slot") : $("#filter-sheet-slot");
  if (form.parentElement !== slot) slot.appendChild(form);
  if (mqFull.matches && $("#filter-sheet").open) $("#filter-sheet").close();
}
function setTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  $("#theme-btn").textContent = t === "light" ? "Dark theme" : "Light theme";
  try { localStorage.setItem("resist-mockup-theme", t); } catch { /* storage unavailable */ }
}

/* ---------------------------------------------------------------------------------------------------------- */
async function boot() {
  let t = "dark";
  try { t = localStorage.getItem("resist-mockup-theme") || "dark"; } catch { /* storage unavailable */ }
  setTheme(t === "light" ? "light" : "dark");
  try { await DT.load(); }
  catch (e) {
    $("#view").innerHTML = `<div class="empty-state"><h2>The Counts Did Not Load</h2><p>Reload the page to try again.</p></div>`;
    $("#loading").hidden = true; console.error(e); return;
  }
  $("#loading").hidden = true;
  fillStatic(); relocateFilters(); bind();
  window.__analysis = { D, selfTest: DT.selfTest, route, state: () => S, collected: () => [...collected] };
  route(true);
  if (new URLSearchParams(location.search).has("selftest")) console.log("SELFTEST " + JSON.stringify(DT.selfTest()));
  document.documentElement.setAttribute("data-ready", "1");
}
boot();
