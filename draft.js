// The draft workspace (SPEC 6.2, D-054). A draft holds only ATNI's fixed form text, words the person typed and
// clauses carried verbatim by a deliberate click, each with its provenance. Nothing here writes, suggests or completes
// resolution language. The draft lives in this browser's storage and in files the person saves; it is never sent.
import {
  STANDARD, COMMITTEES, CONVENTION_FIELDS, newDraft, newClause, compose, body, clauseState, isStandard,
  isNcaiTransmittal, hasPageHeader, removePageHeader, validDraft, safeUrl, usDate, resolvedLead, squash,
} from "./compose.js";
import { esc, local, toast, download } from "./ui.js";
import { buildDocx, docxName } from "./docx.js";
import { openLookup } from "./sentinel.js";

const KEY = "resist-draft-v1";
const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const carryKey = s => `${s?.documentId}:${s?.statementType}:${s?.index}`;

// ---- Store -------------------------------------------------------------------------------------------------------

function loadDraft() {
  try { return validDraft(JSON.parse(local.get(KEY))) || newDraft(); } catch { return newDraft(); }
}
let draft = loadDraft();
const subs = new Set();
let saved = null;   // { ok, at } from the last save attempt
let pending = 0;    // typing debounce timer
let view = null;    // the mounted workspace, if any

function save() {
  clearTimeout(pending); pending = 0;
  saved = { ok: local.set(KEY, JSON.stringify(draft)), at: new Date() };
}
function notify(except) {
  for (const fn of [...subs]) if (fn !== except) try { fn(draft); } catch (e) { console.error(e); }
}
const all = () => [...draft.whereas, ...draft.resolved];
// Where the trailing run of standard clauses (NCAI transmittal, policy closing) starts in a RESOLVED list.
function closingAt(list) { let i = list.length; while (i > 0 && isStandard(list[i - 1].text)) i--; return i; }
const isClosing = c => isStandard(c.text) && !isNcaiTransmittal(c.text);

export const store = {
  get draft() { return draft; },
  update(fn) { fn(draft); save(); notify(); },
  subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },
  carriedCount: () => all().filter(c => c.origin === "carried").length,
  isCarried: key => all().some(c => c.origin === "carried" && carryKey(c.source) === key),
  carry(source) {
    if (!source || store.isCarried(carryKey(source))) return null;
    const c = newClause(source.text, "carried", source);
    store.update(d => {
      if (source.statementType === "whereas") d.whereas.push(c);
      else d.resolved.splice(closingAt(d.resolved), 0, c);
    });
    return c;
  },
  uncarry(key) {
    const keep = c => !(c.origin === "carried" && carryKey(c.source) === key);
    store.update(d => { d.whereas = d.whereas.filter(keep); d.resolved = d.resolved.filter(keep); });
  },
  addNote(note) { if (note && typeof note === "object") store.update(d => { d.notes.push(note); }); },
  replace(next) {
    const v = validDraft(next);
    if (!v) return false;
    draft = v; save(); notify();
    return true;
  },
  reset() { draft = newDraft(); save(); notify(); },
};

// Typing changes the draft at once and repaints the sheet, but saves and tells other views about 300ms later.
function typed(fn) {
  fn(draft);
  clearTimeout(pending);
  pending = setTimeout(() => { save(); notify(view?.sub); view?.status(); }, 300);
  view?.live();
}
const flush = () => { if (pending) { save(); notify(view?.sub); } };
globalThis.addEventListener?.("pagehide", () => { if (pending) save(); });

// ---- Small renderers ----------------------------------------------------------------------------------------------

const s = v => squash(v);   // every untrusted field becomes a plain string before esc()
const part = p => typeof p === "string" ? esc(p) : p.value ? esc(p.value) : `<span class="fill">[${esc(p.fill)}]</span>`;
const line = l => l.map(part).join("");
const box = on => `<span class="s-box" aria-hidden="true">${on ? "☒" : "☐"}</span>` +
  `<span class="visually-hidden">${on ? "checked" : "not checked"}</span>`;
const resLink = src => {
  const id = Number(src?.resolutionId);
  return Number.isInteger(id) && id > 0 ? `<a href="#/r/${id}">${esc(s(src.number))}</a>` : esc(s(src?.number));
};
const outLink = (u, text) => safeUrl(u) ? `<a href="${esc(safeUrl(u))}" target="_blank" rel="noopener">${text}</a>` : "";
const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
const kindWord = kind => kind === "whereas" ? "WHEREAS" : "RESOLVED";
const hasWork = d => [...d.whereas, ...d.resolved].some(c => c.origin !== "standard") || Boolean(s(d.title)) ||
  d.notes.length > 0;

// Lead words and joiners from compose(); an empty clause (left out of the document) gets its position's lead only.
function marks(model) {
  const map = new Map();
  for (const kind of ["whereas", "resolved"]) {
    const list = draft[kind];
    list.forEach((c, i) => map.set(c.id, { lead: kind === "whereas" ? "WHEREAS," : resolvedLead(i, list.length), joiner: "" }));
    for (const x of model[kind]) {
      const c = list.find(c => c.id === x.id);
      if (c) map.set(x.id, { lead: x.lead, joiner: x.text.slice(body(c.text).length) });
    }
  }
  return map;
}

function prov(c) {
  const state = clauseState(c);
  if (state === "standard") return `<span class="chip">ATNI standard text</span>`;
  if (state === "typed") return `<span class="chip">Typed</span>`;
  const from = resLink(c.source);
  if (state === "verbatim") return `<span class="chip carried">Verbatim from ${from}</span>`;
  if (state === "cleaned") return `<span class="chip carried">From ${from}, page header removed</span>`;
  return `<span class="chip carried">Edited from ${from}</span>` +
    `<details class="orig"><summary>Show original</summary><blockquote>${esc(s(c.source?.text))}</blockquote></details>`;
}

function clauseRow(kind, c, i, n, mk) {
  const id = esc(c.id), pos = `${kindWord(kind)} clause ${i + 1}`, m = mk.get(c.id);
  return `<li class="crow${c.origin === "carried" ? " carried" : ""}" data-id="${id}" data-kind="${kind}" data-state="${clauseState(c)}">
    <label class="crow-lead" for="t-${id}">${esc(m.lead)}</label>
    <div class="crow-main">
      <textarea id="t-${id}" data-clause="${id}" rows="2" aria-describedby="j-${id}">${esc(c.text)}</textarea>
      <p class="crow-joiner" id="j-${id}"><span class="visually-hidden">Ends with </span><span class="jtext">${esc(m.joiner)}</span></p>
      <div class="crow-ph notice"${hasPageHeader(c.text) ? "" : " hidden"}>
        <p>This clause includes page-header text from the PDF.</p>
        <button type="button" class="btn small" data-act="strip" id="ph-${id}">Remove page-header text</button>
      </div>
      <div class="crow-foot">
        <div class="crow-prov">${prov(c)}</div>
        <div class="crow-acts">
          <button type="button" class="btn quiet small" data-act="up" id="up-${id}" aria-label="Move up, ${pos}"${i === 0 ? " disabled" : ""}>Move up</button>
          <button type="button" class="btn quiet small" data-act="down" id="dn-${id}" aria-label="Move down, ${pos}"${i === n - 1 ? " disabled" : ""}>Move down</button>
          <button type="button" class="btn quiet small" data-act="rm" id="rm-${id}" aria-label="Remove, ${pos}">Remove</button>
        </div>
      </div>
    </div>
  </li>`;
}

const input = (id, label, bind, value, { hint, placeholder, mode } = {}) => `<div class="field">
  <label for="${id}">${label}</label>
  <input type="text" id="${id}" data-bind="${bind}" value="${esc(s(value))}"${placeholder ? ` placeholder="${placeholder}"` : ""}${mode ? ` inputmode="${mode}"` : ""}${hint ? ` aria-describedby="${id}-h"` : ""}>
  ${hint ? `<small id="${id}-h">${hint}</small>` : ""}</div>`;
const check = (id, label, path, on) =>
  `<label class="check" for="${id}"><input type="checkbox" id="${id}" data-check="${path}"${on ? " checked" : ""}><span>${label}</span></label>`;

let presets = null, presetsP = null, presetAt = 0;
const loadPresets = () => presetsP ??= fetch("conventions.json").then(r => r.ok ? r.json() : Promise.reject())
  .then(j => { presets = Array.isArray(j?.conventions) ? j.conventions.filter(c => c && typeof c === "object") : []; })
  .catch(() => { presets = []; });

function presetPicker() {
  if (presets === null) return `<p class="meta" id="preset-wait">Loading convention details.</p>`;
  if (!presets.length) return `<p class="meta">Convention details could not be loaded. Type them in the fields below.</p>`;
  const now = presets.findIndex(p => s(p.convention) && s(p.convention) === s(draft.header.convention));
  if (now >= 0) presetAt = now;
  return `<div class="preset">
    <div class="field"><label for="f-preset">Known conventions</label>
      <select id="f-preset">${presets.map((p, i) => `<option value="${i}"${i === presetAt ? " selected" : ""}>${esc(s(p.label))}</option>`).join("")}</select></div>
    <button type="button" class="btn" data-act="preset" id="b-preset">Use these details</button>
  </div>`;
}

function noteRow(n, i) {
  const title = esc(s(n.title));
  const facts = [n.issuingBody, n.kind, usDate(s(n.date))].map(s).filter(Boolean).map(esc).join(", ");
  const link = outLink(n.officialUrl, "Official source");
  const issues = n.issues.filter(x => x && typeof x === "object");
  return `<li class="pnote">
    <h3>${title}</h3>
    <p class="meta">${facts}${facts && link ? ", " : ""}${link}</p>
    ${issues.length ? `<ul class="squares">${issues.map(x => `<li><b>${esc(s(x.label))}:</b> “${esc(s(x.quote))}”${s(x.locator) ? ` <span class="meta">(${esc(s(x.locator))})</span>` : ""}<br><span class="meta">Rule: ${esc(s(x.rule))}</span></li>`).join("")}</ul>` : `<p class="meta">No flags selected.</p>`}
    <div class="field"><label for="nc-${i}">Your note</label>
      <textarea id="nc-${i}" data-note="${i}" rows="2">${esc(String(n.comment ?? ""))}</textarea></div>
    <button type="button" class="btn quiet small" data-act="rm-note" data-i="${i}" id="rn-${i}" aria-label="Remove note, ${title}">Remove note</button>
  </li>`;
}

function editorHTML() {
  const d = draft, h = d.header, m = d.meta, model = compose(d), mk = marks(model);
  const rows = kind => d[kind].map((c, i) => clauseRow(kind, c, i, d[kind].length, mk)).join("");
  const closing = d.resolved.some(isClosing);
  const transmittal = d.resolved.some(c => isNcaiTransmittal(c.text));
  return `
  <div class="draft-empty notice"${hasWork(d) ? " hidden" : ""}>
    <p>Carry clauses from ATNI's published resolutions: open one from search and choose Add to draft beside a clause. Or type your own WHEREAS and RESOLVED clauses below.</p>
    <p><a href="#/">Search resolutions</a></p>
  </div>

  <section class="dsec" aria-labelledby="h-conv">
    <h2 id="h-conv">Convention</h2>
    <p class="meta" id="conv-hint">Leave a detail empty if it is not announced yet. The Word file keeps a fillable placeholder.</p>
    <div class="preset-slot">${presetPicker()}</div>
    <div class="fgrid">
      ${input("f-convention", "Convention name", "header.convention", h.convention)}
      ${input("f-year", "Year", "header.year", h.year, { mode: "numeric" })}
      ${input("f-number", "Resolution number", "header.number", h.number, { hint: "DRFT-XX until ATNI assigns one." })}
      ${input("f-location", "City and state", "header.location", h.location)}
      ${input("f-venue", "Venue", "header.venue", h.venue)}
      ${input("f-dates", "Convention dates", "header.dates", h.dates)}
      ${input("f-draftDue", "Draft 1 due", "header.draftDue", h.draftDue)}
      ${input("f-finalDue", "Final draft due", "header.finalDue", h.finalDue)}
      ${input("f-formCode", "Form code", "header.formCode", h.formCode, { hint: "Printed at the foot of the submission form." })}
    </div>
  </section>

  <section class="dsec" aria-labelledby="h-title">
    <h2 id="h-title"><label for="f-title">Title</label></h2>
    <textarea id="f-title" data-bind="title" rows="2">${esc(s(d.title))}</textarea>
  </section>

  <section class="dsec" aria-labelledby="h-pre">
    <h2 id="h-pre">Preamble</h2>
    ${check("f-preamble", "Include the ATNI preamble", "preamble", d.preamble)}
    <details class="orig"><summary>Show the preamble text</summary><blockquote>${esc(STANDARD.preamble)}</blockquote></details>
  </section>

  <section class="dsec" aria-labelledby="h-whereas">
    <h2 id="h-whereas">Whereas</h2>
    <ol class="crows">${rows("whereas")}</ol>
    <div class="entry"><button type="button" class="btn" data-act="add-whereas" id="add-whereas">Add a WHEREAS clause</button></div>
  </section>

  <section class="dsec" aria-labelledby="h-resolved">
    <h2 id="h-resolved">Resolved</h2>
    <ol class="crows">${rows("resolved")}</ol>
    <div class="entry">
      <button type="button" class="btn" data-act="add-resolved" id="add-resolved">Add a RESOLVED clause</button>
      ${closing ? "" : `<button type="button" class="btn" data-act="add-closing" id="add-closing">Add ATNI's closing clause</button>`}
      ${m.ncai.forward && !transmittal ? `<button type="button" class="btn" data-act="add-ncai" id="add-ncai">Add ATNI's NCAI transmittal clause</button>` : ""}
      <a class="btn quiet" href="#/">Find precedent</a>
    </div>
  </section>

  <section class="dsec" aria-labelledby="h-cert">
    <h2 id="h-cert">Certification and Signatures</h2>
    ${check("f-quorum", "With a quorum present", "certification.quorum", d.certification.quorum)}
    <div class="fgrid">
      ${input("f-president", "President's name", "signatures.president", d.signatures.president, { placeholder: "Name" })}
      ${input("f-secretary", "Secretary's name", "signatures.secretary", d.signatures.secretary, { placeholder: "Name" })}
    </div>
  </section>

  <section class="dsec" aria-labelledby="h-form">
    <h2 id="h-form">Submission Form</h2>
    <div class="fgrid">
      ${input("f-author", "Author", "meta.author", m.author)}
      ${input("f-sponsor", "Sponsor", "meta.sponsor", m.sponsor, { hint: "Must be an ATNI Member in Good Standing" })}
    </div>
    ${check("f-standing", "The sponsor is an ATNI Member in Good Standing", "meta.sponsorInGoodStanding", m.sponsorInGoodStanding)}
    <fieldset class="cmte">
      <legend>ATNI committees</legend>
      <div class="cmte-list">${COMMITTEES.map((name, i) => `<button type="button" class="btn small" data-act="cmte" data-i="${i}" id="cm-${i}" aria-pressed="${m.committees.includes(name)}">${esc(name)}</button>`).join("")}</div>
    </fieldset>
    ${input("f-other", "Other committee", "meta.otherCommittee", m.otherCommittee)}
    ${check("f-ncai", "Request to forward this resolution to NCAI", "meta.ncai.forward", m.ncai.forward)}
    ${m.ncai.forward ? `<div class="field"><label for="f-emergency">Why is this resolution emergency in nature? (Winter and Midyear only)</label>
      <textarea id="f-emergency" data-bind="meta.ncai.emergency" rows="3">${esc(s(m.ncai.emergency))}</textarea></div>` : ""}
    <p class="meta">Phone numbers and email addresses are left blank for you to fill in Word. ResIST does not collect them.</p>
  </section>

  <section class="dsec" aria-labelledby="h-notes">
    <h2 id="h-notes">Policy Notes</h2>
    ${d.notes.length ? `<ol class="pnotes">${d.notes.map(noteRow).join("")}</ol>` : `<p class="meta">No policy notes yet. A note records what Policy Sentinel found in a federal policy; it goes in the Drafting Notes section of the Word file.</p>`}
    <button type="button" class="btn" data-act="lookup" id="b-lookup">Look up a policy</button>
  </section>

  <section class="dsec" aria-labelledby="h-check">
    <h2 id="h-check">Before You Download</h2>
    <div class="problems">${problemsHTML(model)}</div>
  </section>`;
}

const problemsHTML = model => model.problems.length
  ? `<ul class="squares">${model.problems.map(p => `<li>${esc(p)}</li>`).join("")}</ul><p class="meta">These are reminders only; the Word document downloads either way.</p>`
  : `<p class="meta">Nothing left on the checklist.</p>`;

// ---- The sheet: compose(draft) as the Word document will read ------------------------------------------------------

const STATE_TEXT = { verbatim: "Verbatim", cleaned: "Verbatim, page header removed", edited: "Edited by the drafter" };

function sheetHTML(m) {
  const clause = x => `<p class="s-cl" data-cid="${esc(x.id)}" data-state="${x.state}"><b>${esc(x.lead)}</b> ${esc(x.text)}</p>`;
  const f = m.form;
  const grid = f.committees.map(row => `<tr>${row.map(c => `<td>${c ? `${box(c.checked)} ${esc(c.name)}${c.name === "Other" && f.otherCommittee ? `: ${esc(f.otherCommittee)}` : ""}` : ""}</td>`).join("")}</tr>`).join("");
  let h = `<div class="pg">
    <p class="s-h1">${line(m.heading[0])}</p>
    <p class="s-h1 s-after">${line(m.heading[1])}</p>
    <p class="s-14 s-after">${esc(m.number).replace("[Year]", `<span class="fill">[Year]</span>`)}</p>
    <p class="s-14">${line(m.deadlines[0])}</p>
    <p class="s-14 s-after">${line(m.deadlines[1])}</p>
    <p class="s-14 s-after s-go" data-goto="f-title">${line(m.title)}</p>
    ${m.preamble ? `<p class="s-14 s-after">PREAMBLE</p><p class="s-pre s-after">${esc(m.preamble)}</p>` : ""}
    ${m.whereas.map(clause).join("")}${m.resolved.map(clause).join("")}
    <div class="s-cert">
      <p class="s-certh">CERTIFICATION</p>
      <p>${line(m.certification)}</p>
      <div class="s-sigs">${m.signatures.map(x => `<p><span class="s-rule"></span>${line(x)}</p>`).join("")}</div>
    </div>
  </div>
  <p class="pg-break"><span>Page break</span></p>
  <div class="pg s-form">
    <div class="s-fhead"><img src="atni-seal-color.jpg" alt="" width="56" height="56"><p>AFFILIATED TRIBES OF NORTHWEST INDIANS<br>RESOLUTION SUBMISSION FORM</p></div>
    <p><b>Resolution Title:</b> ${line(f.title)}</p>
    <p><b>Author of Resolution:</b> ${line(f.author)}</p>
    <p><b>Sponsor of Resolution*:</b> ${line(f.sponsor)}</p>
    <p><b>Request to Forward this Resolution to NCAI?</b> ${box(f.ncaiForward)} Yes ${box(!f.ncaiForward)} No</p>
    <table class="s-grid"><tbody>${grid}</tbody></table>
    <p><b>ATNI Committees (please select at least one)</b></p>
    <p class="s-small">Phone, email, committee chair and certification fields follow in the Word file, blank for you to fill in.</p>
    ${f.ncai ? `<p><b>NCAI Form</b> follows on its own page.${f.ncai.emergency ? ` Emergency in nature: ${esc(f.ncai.emergency)}` : ""}</p>` : ""}
    ${f.formCode ? `<p class="s-code">${esc(f.formCode)}</p>` : ""}
  </div>`;
  if (m.sources.length || m.notes.length) h += `<p class="pg-break"><span>Page break</span></p>
  <div class="pg s-notes">
    <p class="s-nh">DRAFTING NOTES, NOT PART OF THE RESOLUTION</p>
    <p><i>Prepared with ResIST. These notes record where carried clauses came from and what Policy Sentinel found. Delete this section before submitting if it is not wanted.</i></p>
    ${m.sources.length ? `<table class="s-src"><thead><tr><th>Position</th><th>ATNI resolution</th><th>Text</th><th>Source</th></tr></thead><tbody>${m.sources.map(x => `<tr>
      <td>${esc(x.position)}</td><td>${esc([x.number, x.title, x.year].map(s).filter(Boolean).join(", "))}</td>
      <td>${STATE_TEXT[x.state] ?? ""}</td><td>${outLink(x.url, "Source PDF")}<br>${esc(s(x.documentId).slice(0, 16))}</td></tr>`).join("")}</tbody></table>` : ""}
    ${m.notes.map(n => `<div class="s-note">
      <p><b>${esc(s(n.title))}</b></p>
      <p>${[n.issuingBody, n.kind, usDate(s(n.date))].map(s).filter(Boolean).map(esc).join(", ")}${outLink(n.officialUrl, "Official source") ? `, ${outLink(n.officialUrl, "Official source")}` : ""}</p>
      ${s(n.retrievedAt) ? `<p>Read by Policy Sentinel on ${esc(usDate(s(n.retrievedAt)))}; text SHA-256 ${esc(s(n.receiptSha256).slice(0, 16))}</p>` : ""}
      ${(Array.isArray(n.issues) ? n.issues : []).filter(x => x && typeof x === "object").map(x => `<p class="s-flag">${esc(s(x.label))}: “${esc(s(x.quote))}”${s(x.locator) ? ` (${esc(s(x.locator))})` : ""}<br><span class="s-rulet">Rule: ${esc(s(x.rule))}</span></p>`).join("")}
      ${s(n.comment) ? `<p>Drafter's note: ${esc(s(n.comment))}</p>` : ""}
    </div>`).join("")}
    ${m.notes.length ? `<p class="s-small"><i>Policy Sentinel's flags come from automated demo rules. They quote the policy text and are not legal conclusions.</i></p>` : ""}
  </div>`;
  return h;
}

// ---- The workspace -----------------------------------------------------------------------------------------------

const SHELL = `<div class="wrap wide draft-view" data-show="edit">
  <div class="draft-head">
    <div class="draft-title">
      <h1 tabindex="-1">Draft Resolution</h1>
      <p class="draft-status" id="draft-status"></p>
    </div>
    <div class="draft-tools">
      <button type="button" class="btn primary" data-tool="word">Download Word document</button>
      <button type="button" class="btn" data-tool="save">Save draft file</button>
      <button type="button" class="btn" data-tool="open">Open draft file</button>
      <button type="button" class="btn quiet" data-tool="new">Start a new draft</button>
      <input type="file" accept=".json,application/json" hidden id="draft-file">
    </div>
    <p class="draft-error" id="draft-error" role="alert" hidden></p>
    <div class="draft-confirm notice" id="draft-confirm" hidden></div>
  </div>
  <div class="draft-switch" role="group" aria-label="Show">
    <button type="button" class="btn" data-mode="edit" aria-pressed="true">Edit</button>
    <button type="button" class="btn" data-mode="preview" aria-pressed="false">Preview</button>
  </div>
  <div class="bench">
    <div class="editor"></div>
    <section class="desk" aria-labelledby="desk-h">
      <div class="desk-cap">
        <h2 id="desk-h">Preview</h2>
        <p>As the Word document will read. Select a clause to edit it. A red margin mark shows a carried clause; it is not printed.</p>
      </div>
      <div class="paper"><div class="sheet"></div></div>
    </section>
  </div>
</div>`;

let seal;
const sealBytes = () => seal ??= fetch("atni-seal-color.jpg")
  .then(r => r.ok ? r.arrayBuffer() : null).then(b => b && new Uint8Array(b), () => null);
const GROW = !globalThis.CSS?.supports?.("field-sizing", "content");
const grow = el => {
  if (!GROW) return;
  for (const t of el.matches?.("textarea") ? [el] : el.querySelectorAll("textarea")) {
    t.style.height = "auto"; t.style.height = `${t.scrollHeight + 2}px`;
  }
};
const setPath = (o, path, v) => { const ks = path.split("."), last = ks.pop(); ks.reduce((a, k) => a[k], o)[last] = v; };

export function renderDraft(main) {
  view?.unsub();
  main.innerHTML = SHELL;
  const $ = q => main.querySelector(q);
  const root = $(".draft-view"), editor = $(".editor"), sheet = $(".sheet"), statusEl = $("#draft-status");
  const errEl = $("#draft-error"), confirmEl = $("#draft-confirm"), fileEl = $("#draft-file");
  let raf = 0, nextFocus = "", busy = false;
  const find = id => all().find(c => c.id === id);

  function paintEditor() {
    const had = editor.contains(document.activeElement) ? document.activeElement.id : "";
    // Keep "Show original" and the preamble text open across a repaint.
    const where = d => d.closest("[data-id]")?.dataset.id ?? d.closest("section")?.getAttribute("aria-labelledby");
    const open = [...editor.querySelectorAll("details[open]")].map(where);
    editor.innerHTML = editorHTML();
    for (const d of editor.querySelectorAll("details")) if (open.includes(where(d))) d.open = true;
    grow(editor);
    const el = document.getElementById(nextFocus || had);
    nextFocus = "";
    if (el && editor.contains(el) && !el.disabled) el.focus({ preventScroll: true });
  }
  function paintLive() {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => {
      const model = compose(draft), mk = marks(model);
      sheet.innerHTML = sheetHTML(model);
      for (const li of editor.querySelectorAll(".crow")) {
        const m = mk.get(li.dataset.id);
        if (!m) continue;
        li.querySelector(".crow-lead").textContent = m.lead;
        li.querySelector(".jtext").textContent = m.joiner;
      }
      const p = editor.querySelector(".problems");
      if (p) p.innerHTML = problemsHTML(model);
      const empty = editor.querySelector(".draft-empty");
      if (empty) empty.hidden = hasWork(draft);
    });
  }
  function paintStatus() {
    if (saved && !saved.ok) {
      statusEl.className = "draft-status bad";
      statusEl.innerHTML = `This draft could not be saved in this browser. <button type="button" class="btn small" data-tool="save">Save draft file</button>`;
    } else {
      statusEl.className = "draft-status";
      statusEl.textContent = saved
        ? `Saved in this browser at ${saved.at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
        : "Saved in this browser as you work. Nothing is sent anywhere.";
    }
  }
  // A row's provenance chip and page-header notice follow the text as it is typed.
  function paintRow(li, c) {
    const state = clauseState(c);
    if (li.dataset.state !== state) { li.dataset.state = state; li.querySelector(".crow-prov").innerHTML = prov(c); }
    li.querySelector(".crow-ph").hidden = !hasPageHeader(c.text);
  }
  function setMode(mode) {
    root.dataset.show = mode;
    for (const b of root.querySelectorAll(".draft-switch [data-mode]")) b.setAttribute("aria-pressed", String(b.dataset.mode === mode));
    if (mode === "edit") grow(editor);
  }
  function ask(message, okLabel, onOk) {
    confirmEl.innerHTML = `<p>${esc(message)}</p><div class="draft-tools">
      <button type="button" class="btn primary" data-confirm="ok">${esc(okLabel)}</button>
      <button type="button" class="btn" data-confirm="cancel">Keep this draft</button></div>`;
    confirmEl.hidden = false;
    confirmEl._ok = onOk;
    confirmEl.querySelector('[data-confirm="cancel"]').focus();
  }
  const closeAsk = () => { confirmEl.hidden = true; confirmEl.innerHTML = ""; confirmEl._ok = null; };

  function lostText() {
    const kept = all().filter(c => c.origin !== "standard").length;
    const parts = [kept && plural(kept, "carried or typed clause"), draft.notes.length && plural(draft.notes.length, "policy note"),
      "the title and every detail you entered"].filter(Boolean);
    return parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}` : parts[0];
  }

  async function exportWord() {
    if (busy) return;
    busy = true; flush();
    try {
      const bytes = buildDocx(compose(draft), { seal: (await sealBytes()) || undefined, created: new Date().toISOString() });
      download(bytes, docxName(draft), DOCX);
      toast("Word document downloaded");
    } catch (e) {
      console.error(e);
      toast("The Word document could not be built. Save a draft file to keep your work.");
    } finally { busy = false; }
  }
  function saveFile() {
    flush();
    download(JSON.stringify(draft, null, 2), `resist-draft-${new Date().toLocaleDateString("en-CA")}.json`, "application/json");
    toast("Draft file saved");
  }
  async function openFile(file) {
    errEl.hidden = true; closeAsk();
    let v = null;
    if (file.size <= 5e6) try { v = validDraft(JSON.parse(await file.text())); } catch { v = null; }
    fileEl.value = "";
    if (!v) { errEl.textContent = "This file is not a ResIST draft."; errEl.hidden = false; return; }
    const open = () => { store.replace(v); toast("Draft file opened"); $("h1").focus(); };
    if (hasWork(draft)) ask(`Opening ${file.name} replaces the draft in this browser: ${lostText()}. Save a draft file first if you want to keep it.`, "Open this draft file", open);
    else open();
  }

  main.addEventListener("click", e => {
    const t = e.target.closest("[data-tool], [data-confirm], [data-mode], [data-act], [data-cid], [data-goto]");
    if (!t || !root.contains(t)) return;
    if (t.dataset.tool) {
      errEl.hidden = true;
      if (t.dataset.tool === "word") exportWord();
      else if (t.dataset.tool === "save") saveFile();
      else if (t.dataset.tool === "open") fileEl.click();
      else if (t.dataset.tool === "new") {
        if (!hasWork(draft)) { store.reset(); toast("New draft started"); return; }
        ask(`Starting a new draft clears this one from this browser: ${lostText()}. Save a draft file first if you want to keep it.`,
          "Clear and start a new draft", () => { store.reset(); toast("New draft started"); $("h1").focus(); });
      }
    } else if (t.dataset.confirm) {
      const ok = confirmEl._ok;
      closeAsk();
      if (t.dataset.confirm === "ok") ok?.(); else root.querySelector('[data-tool="new"]').focus();
    } else if (t.dataset.mode && t.matches("button")) setMode(t.dataset.mode);
    else if (t.dataset.cid || t.dataset.goto) {
      const target = document.getElementById(t.dataset.goto || `t-${t.dataset.cid}`);
      if (!target) return;
      setMode("edit");
      target.scrollIntoView({ block: "center" });
      target.focus({ preventScroll: true });
    } else act(t);
  });

  function act(b) {
    const a = b.dataset.act, li = b.closest(".crow");
    const kind = li?.dataset.kind, id = li?.dataset.id;
    const list = kind ? draft[kind] : null, i = list ? list.findIndex(c => c.id === id) : -1;
    if (a === "up" || a === "down") {
      const j = i + (a === "up" ? -1 : 1);
      if (i < 0 || j < 0 || j >= list.length) return;
      const edge = j === 0 || j === list.length - 1;
      nextFocus = edge ? `t-${id}` : b.id;
      store.update(d => { [d[kind][i], d[kind][j]] = [d[kind][j], d[kind][i]]; });
    } else if (a === "rm" && i >= 0) {
      nextFocus = list[i + 1] ? `t-${list[i + 1].id}` : list[i - 1] ? `t-${list[i - 1].id}` : `add-${kind}`;
      store.update(d => { d[kind].splice(i, 1); });
    } else if (a === "strip" && i >= 0) {
      nextFocus = `t-${id}`;
      store.update(() => { list[i].text = body(removePageHeader(list[i].text)); });
      toast("Page-header text removed");
    } else if (a === "add-whereas" || a === "add-resolved") {
      const c = newClause("", "typed");
      nextFocus = `t-${c.id}`;
      store.update(d => a === "add-whereas" ? d.whereas.push(c) : d.resolved.splice(closingAt(d.resolved), 0, c));
    } else if (a === "add-closing") {
      nextFocus = "add-resolved";
      store.update(d => { d.resolved.push(newClause(STANDARD.closing, "standard")); });
    } else if (a === "add-ncai") {
      nextFocus = "add-resolved";
      store.update(d => {
        const at = d.resolved.findLastIndex(isClosing);
        d.resolved.splice(at < 0 ? d.resolved.length : at, 0, newClause(STANDARD.ncai, "standard"));
      });
    } else if (a === "cmte") {
      const name = COMMITTEES[Number(b.dataset.i)];
      if (!name) return;
      store.update(d => {
        d.meta.committees = d.meta.committees.includes(name)
          ? d.meta.committees.filter(n => n !== name) : [...d.meta.committees, name];
      });
    } else if (a === "preset") {
      presetAt = Number(editor.querySelector("#f-preset")?.value);
      const p = presets?.[presetAt];
      if (!p) return;
      store.update(d => { for (const k of CONVENTION_FIELDS) d.header[k] = k === "year" ? (Number(p.year) || d.header.year) : s(p[k]); });
      toast("Convention details applied to your draft");
    } else if (a === "lookup") {
      openLookup({ query: "", onAddNote: n => { store.addNote(n); toast("Policy note added to your draft"); } });
    } else if (a === "rm-note") {
      const n = Number(b.dataset.i);
      nextFocus = "b-lookup";
      store.update(d => { d.notes.splice(n, 1); });
    }
  }

  editor.addEventListener("input", e => {
    const t = e.target;
    if (t.dataset.clause) {
      const c = find(t.dataset.clause);
      if (!c) return;
      typed(() => { c.text = t.value; if (c.origin === "standard" && !isStandard(c.text)) c.origin = "typed"; });
      paintRow(t.closest(".crow"), c);
    } else if (t.dataset.bind) typed(() => setPath(draft, t.dataset.bind, t.value));
    else if (t.dataset.note) { const n = draft.notes[Number(t.dataset.note)]; if (n) typed(() => { n.comment = t.value; }); }
    if (t.matches("textarea")) grow(t);
  });
  editor.addEventListener("change", e => {
    const t = e.target;
    if (t.dataset.check) store.update(d => setPath(d, t.dataset.check, t.checked));
    else if (t.dataset.clause) {
      // Lead words and joiners belong to the position; the stored text is the clause body only.
      const c = find(t.dataset.clause), b = body(t.value);
      if (c && b !== t.value) { t.value = b; typed(() => { c.text = b; }); grow(t); }
    }
  });
  fileEl.addEventListener("change", () => { if (fileEl.files?.[0]) openFile(fileEl.files[0]); });

  const sub = () => {
    if (!root.isConnected) { v.unsub(); return; }
    paintEditor(); paintLive(); paintStatus();
  };
  const unsub = store.subscribe(sub);
  const v = view = { sub, live: paintLive, status: paintStatus, unsub() { unsub(); if (view === v) view = null; } };

  paintEditor(); paintLive(); paintStatus();
  if (presets === null) loadPresets().then(() => {
    const slot = editor.querySelector(".preset-slot");
    if (slot && root.isConnected) slot.innerHTML = presetPicker();
  });
}
