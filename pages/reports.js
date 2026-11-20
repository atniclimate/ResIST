// Authoritative local packets. No public database, browser storage or external lookup.
import { esc, say, download } from "./ui.js";

const MESSAGES = {
  loading: "Checking local report availability…",
  generating: "Reading admitted local sources and checking their evidence…",
  verified: "This packet matches current local sources.",
  missing: "The requested source is missing or ambiguous in the local pool. Check its number.",
  refused: "Current source policy refuses this packet. No quotation is available.",
  "stale-input": "The packet does not match current inputs. Its integrity is unverified. Generate a new packet to continue.",
  "unsupported-version": "This packet version is not supported here.",
  "invalid-artifact": "The packet did not pass its evidence checks. Generate a new packet to continue.",
  "invalid-request": "Enter an ATNI resolution number in the form YY-NN.",
  "format-unavailable": "This format is not available here.",
  "word-unavailable": "This packet still matches current local sources, but it cannot be represented safely as Word. Download JSON or Markdown.",
  "request-too-large": "The packet exceeds the local request limit.",
  failed: "The local report could not be checked. Try again when the source pool is available.",
  unavailable: "Reports are available only in the local ResIST application. The public site cannot read authoritative local sources.",
};
export const stateMessage = state => MESSAGES[state] || MESSAGES.failed;
const counted = (n, label) => `${n} ${label}${n === 1 ? "" : "s"}`;
let packet = null;
let packetState = "verified";

export function packetHTML(value) {
  const counts = value.completeness;
  const sources = value.sources.map(source => `<section>
    <h3>${esc(source.number || "Number not recorded")}: ${esc(source.title || "Title not recorded")}</h3>
    <p>Status: ${esc(source.status)}; authority: ${esc(source.status_authority)}.</p>
    ${source.clauses.length ? source.clauses.map(clause => `<div class="report-clause">
      <p class="meta">${esc(clause.statement_type)} · ${clause.span?.page ? `Page ${esc(clause.span.page)}` : "Page not recorded"}</p>
      ${clause.span ? `<blockquote>${esc(clause.span.quote)}</blockquote>` : "<p>Text withheld because its stored identity did not verify.</p>"}
      <details><summary>Clause provenance</summary><dl>
        <dt>Text state</dt><dd>${esc(clause.text_state)}</dd><dt>Locator</dt><dd>${esc(clause.locator_state)}</dd>
        <dt>Source SHA-256</dt><dd><code>${esc(source.sha256)}</code></dd>
        <dt>Text SHA-256</dt><dd><code>${esc(source.text_sha256)}</code></dd>
        <dt>Character offsets</dt><dd>${clause.span ? `${esc(clause.span.start)}–${esc(clause.span.end)}` : "Not verified"}</dd>
        </dl></details></div>`).join("") : "<p>No adopted source-asserted clauses are included for this source.</p>"}
    <details><summary>Source and extraction evidence</summary><pre>${esc(JSON.stringify({
      sha256: source.sha256, work_id: source.work_id, source_file_state: source.source_file_state,
      chronology: source.chronology, extraction: source.extraction,
    }, null, 2))}</pre></details></section>`).join("");
  const citations = value.citations.map(citation => `<li><blockquote>${esc(citation.reference.span.quote)}</blockquote>
    <p>${esc(citation.state)}: ${esc(citation.reason)}</p></li>`).join("");
  return `<p class="report-counts">${counted(value.sources.length, "source")} · ${counted(value.citations.length, "citation occurrence")}</p>
    <p class="measure">Quotations use the stored normalized extraction; headers, whitespace and terminal punctuation may differ from the original PDF. Original-file hashes and extraction records are separate checks.</p>
    <p>${esc(counted(counts.missing_pages, "clause page"))} missing; ${esc(counted(counts.citation_missing_pages, "citation page"))} missing;
      ${esc(counted(counts.missing_extraction_records, "source"))} without historical extraction records.</p>
    <h2>Source quotations</h2>${sources}<h2>Cited evidence and gaps</h2>
    ${citations ? `<ul class="squares">${citations}</ul>` : "<p>No citation matches were detected within this packet’s stated coverage. This is not evidence that no policy exists.</p>"}
    <details><summary>Packet completeness</summary><pre>${esc(JSON.stringify(counts, null, 2))}</pre></details>`;
}

export function renderReports(main) {
  document.title = "Local reports, ResIST";
  const controller = new AbortController();
  main.innerHTML = `<div class="wrap report-view"><h1 tabindex="-1">Local evidence report</h1>
    <p class="lead measure">Read the cited evidence, see what is missing, and recheck it against the local sources.</p>
    <p id="report-status" tabindex="-1">${stateMessage("loading")}</p>
    <form id="report-form" hidden><div class="field"><label for="report-number">ATNI resolution number</label>
      <input id="report-number" type="text" required pattern="[0-9]{2}-[0-9]{1,6}" autocomplete="off" aria-describedby="report-number-help">
      <small id="report-number-help">Use the printed number, such as YY-NN.</small></div>
      <button type="submit" class="btn primary">Generate report</button></form>
    <div id="report-actions" class="report-actions" hidden><button id="report-recheck" type="button" class="btn">Recheck sources</button>
      <button type="button" class="btn" data-report-format="json">Download JSON</button>
      <button type="button" class="btn" data-report-format="md">Download Markdown</button>
      <button id="report-word" type="button" class="btn" data-report-format="docx" hidden>Download Word</button></div>
    <p id="report-formats" class="meta" hidden>Word download is unavailable in this application.</p>
    <div id="report-output"></div></div>`;
  const root = main.querySelector(".report-view"), status = root.querySelector("#report-status");
  const form = root.querySelector("form"), actions = root.querySelector("#report-actions"), output = root.querySelector("#report-output");
  let busy = false;
  const current = () => !controller.signal.aborted;
  function state(value, focus = false) {
    status.textContent = stateMessage(value);
    status.dataset.state = value;
    if (focus) status.focus();
    say(status.textContent);
  }
  function pending(value) {
    busy = value;
    root.setAttribute("aria-busy", String(value));
    root.querySelectorAll("button").forEach(button => { button.disabled = value; });
  }
  function showPacket() {
    actions.hidden = !packet;
    output.innerHTML = packet && packetState === "verified" ? packetHTML(packet) : "";
    root.querySelectorAll("[data-report-format]").forEach(button => { button.disabled = busy || packetState !== "verified"; });
  }
  async function post(path, body) {
    return fetch(`/api/v1/reports${path}`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), signal: controller.signal, cache: "no-store", credentials: "same-origin" });
  }
  async function recheck(focus = false) {
    pending(true); packetState = "generating"; showPacket(); state("generating");
    try {
      const response = await post("/verify", { packet });
      const result = await response.json();
      if (!current()) return;
      packetState = result.status; pending(false); showPacket(); state(packetState, focus);
    } catch {
      if (current()) { packetState = "failed"; pending(false); showPacket(); state("failed", focus); }
    }
  }
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    pending(true); state("generating"); output.innerHTML = ""; actions.hidden = true;
    try {
      const response = await post("", { request: `atni:res:${root.querySelector("input").value.trim()}` });
      const result = await response.json();
      if (!current()) return;
      packet = response.ok ? result.packet : null;
      packetState = result.status; pending(false); showPacket(); state(result.status, true);
    } catch {
      if (current()) { packet = null; pending(false); showPacket(); state("failed", true); }
    }
  });
  actions.addEventListener("click", async event => {
    const button = event.target.closest("button");
    if (!button || busy || !packet) return;
    const format = button.dataset.reportFormat;
    if (!format) { await recheck(true); return; }
    pending(true); packetState = "generating"; showPacket(); state("generating");
    try {
      const response = await post("/download", { packet, format });
      if (!current()) return;
      if (response.ok) {
        download(await response.arrayBuffer(), `packet.${format}`, response.headers.get("content-type"));
        if (!current()) return;
        packetState = "verified"; pending(false); showPacket(); state("verified"); button.focus();
      } else {
        const result = await response.json();
        if (!current()) return;
        const wordUnavailable = result.status === "format-unavailable" && result.format === "docx" && result.verified === true;
        packetState = wordUnavailable ? "verified" : result.status;
        pending(false); showPacket(); state(wordUnavailable ? "word-unavailable" : result.status, true);
      }
    } catch { if (current()) { packetState = "failed"; pending(false); showPacket(); state("failed", true); } }
  });
  fetch("capabilities.json", { signal: controller.signal, cache: "no-store" }).then(async response => {
    if (!response.ok) throw new Error("capabilities");
    const capabilities = await response.json();
    if (!current()) return;
    if (capabilities.face !== "local" || capabilities.reports?.available !== true) { state("unavailable"); return; }
    form.hidden = false;
    const wordAvailable = capabilities.reports.formats?.includes("docx") === true;
    root.querySelector("#report-word").hidden = !wordAvailable;
    root.querySelector("#report-formats").hidden = wordAvailable;
    if (packet) await recheck();
    else { status.textContent = "Enter a source number to create a local packet."; status.dataset.state = "ready"; }
  }).catch(() => { if (current()) state("failed"); });
  return () => controller.abort();
}
