// Policy Sentinel lookup (D-054). On an explicit click, and only then, the search words shown in the panel go to
// ATNI Climate's public demo Worker. The draft itself is never sent. Policy Sentinel's flags are rule-based and quote
// the policy text; nothing here interprets them, and nothing writes resolution language.
// Response checks are ported from policy-sentinel/src/demo/validation.ts, trimmed to the fields this page reads.
import { safeUrl, squash, usDate } from "./compose.js";
import { esc } from "./ui.js";

export const SENTINEL_HOME = "https://atniclimate.github.io/policy-sentinel/";
export const API = "https://policy-sentinel-demo.atniclimate.workers.dev";
export const FEDERAL_TYPES = new Set(["executive_order", "usc", "public_law", "cfr"]);
export const TIMEOUT_MS = 30_000;
export const MAX_BYTES = 2_000_000;

// Only Federal Register policy text is read; the others return metadata (SPEC 6.3).
export const SOURCES = [
  { id: "federal-register", label: "Federal Register", name: "the Federal Register", hosts: ["www.federalregister.gov", "www.govinfo.gov"] },
  { id: "govinfo", label: "GovInfo (metadata only)", name: "GovInfo", hosts: ["www.govinfo.gov"] },
  { id: "regulations", label: "Regulations.gov (metadata only)", name: "Regulations.gov", hosts: ["www.regulations.gov"] },
  { id: "congress", label: "Congress.gov (metadata only)", name: "Congress.gov", hosts: ["www.congress.gov"] },
];
const ISSUE_TYPES = ["consultation_language", "consultation_absent", "tribal_reference", "date_or_deadline", "cross_reference", "status_signal"];

// ---- Search words for a citation found in a resolution ----
const FORMS = {
  executive_order: [/\b(?:Executive\s+Order|E\.?\s?O\.?)\s*(?:No\.?\s*)?(\d[\d,]*)/i, m => `Executive Order ${m[1].replace(/,/g, "")}`],
  public_law: [/\b(?:Public\s+Law|P\.?\s?L\.?)\s*(?:No\.?\s*)?(\d+\s*-\s*\d+)/i, m => `Public Law ${m[1].replace(/\s/g, "")}`],
  usc: [/\b(\d+)\s*U\.?\s?S\.?\s?C\.?\s*(?:§+\s*)?(\d[\w.()-]*)/i, m => `${m[1]} U.S.C. ${m[2]}`],
  cfr: [/\b(\d+)\s*C\.?\s?F\.?\s?R\.?\s*(?:Part\s*|§+\s*)?(\d[\w.()-]*)/i, m => `${m[1]} CFR ${m[2]}`],
};
export function lookupWords(text, citationType) {
  const t = squash(text).replace(/[‐-―]/g, "-");
  const [re, make] = FORMS[citationType] ?? [];
  const m = re?.exec(t);
  return (m ? make(m) : t).slice(0, 200).replace(/[\s.,;:]+$/, "");
}

// The id the policy endpoint accepts: the FR document number inside "90 FR 60570 (FR Doc. 2025-23880)".
export function policyId(citation) {
  if (citation.sourceId === "federal-register") {
    const m = /FR Doc\. ([A-Za-z0-9-]+)\)?$/.exec(citation.identifier);
    if (m) return m[1];
  }
  return citation.identifier;
}

// ---- Validation: every field shown or stored is bounded and typed ----
const bad = what => { throw new Error(`Invalid ${what}`); };
export const obj = v => (v && typeof v === "object" && !Array.isArray(v) ? v : bad("object"));
export const text = (v, max, empty = false) =>
  typeof v === "string" && v.length <= max && (empty || v.trim()) ? v : bad("text");
const count = (v, max, min = 0) => (Number.isSafeInteger(v) && v >= min && v <= max ? v : bad("count"));
const list = (v, max) => (Array.isArray(v) && v.length <= max ? v : bad("list"));
const isoDate = v => {
  const s = text(v, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(s) && new Date(`${s}T00:00:00Z`).toISOString().slice(0, 10) === s ? s : bad("date");
};
const timestamp = v => {
  const s = text(v, 40);
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/.test(s) && Number.isFinite(Date.parse(s)) &&
    new Date(s).toISOString().slice(0, 10) === s.slice(0, 10) ? s : bad("timestamp");
};
const sha256 = v => (/^[a-f0-9]{64}$/.test(text(v, 64)) ? v : bad("digest"));

// An https address on a host the source publishes from, exactly as the URL parser reads it (no credentials, port,
// query or fragment), and a link safeUrl() would also render.
export function officialUrl(v, sourceId) {
  const s = text(v, 4096), hosts = SOURCES.find(x => x.id === sourceId)?.hosts ?? [];
  let u;
  try { u = new URL(s); } catch { return bad("URL"); }
  const ok = u.protocol === "https:" && !u.username && !u.password && !u.port && !u.search && !u.hash &&
    u.href === s && hosts.includes(u.hostname) && safeUrl(s);
  return ok ? s : bad("URL");
}

export function citationValue(value, sourceId) {
  const v = obj(value), id = text(v.sourceId, 40);
  if (id !== sourceId || !SOURCES.some(s => s.id === id)) bad("source");
  if (typeof v.textAvailable !== "boolean") bad("text availability");
  return {
    sourceId: id, identifier: text(v.identifier, 300), title: text(v.title, 4000), issuingBody: text(v.issuingBody, 4000),
    kind: text(v.kind, 200), date: v.date === null ? null : isoDate(v.date), officialUrl: officialUrl(v.officialUrl, id),
    textUrl: v.textUrl === null ? null : officialUrl(v.textUrl, id), retrievedAt: timestamp(v.retrievedAt),
    textAvailable: v.textAvailable,
  };
}

export function searchValue(value, source, query) {
  const v = obj(value);
  if (v.ok !== true || v.source !== source || v.query !== query || v.page !== 1) bad("search response");
  const seen = new Set();
  const results = list(v.results, 10).map(item => {
    const c = citationValue(item, source);
    if (seen.has(c.identifier)) bad("result");
    seen.add(c.identifier);
    return c;
  });
  return { results, total: v.total === null || v.total === undefined ? null : count(v.total, Number.MAX_SAFE_INTEGER) };
}

export function policyValue(value, expected) {
  const v = obj(value);
  if (v.ok !== true) bad("policy response");
  const citation = citationValue(v.citation, expected.source);
  if (policyId(citation) !== expected.id) bad("policy identity");
  const r = obj(v.receipt);
  const receipt = {
    sha256: sha256(r.sha256), bytes: count(r.bytes, 1_500_000, 1), retrievedAt: timestamp(r.retrievedAt),
    textUrl: officialUrl(r.textUrl, citation.sourceId),
  };
  if (!citation.textAvailable || citation.textUrl !== receipt.textUrl) bad("receipt");
  const ids = new Set();
  const issues = list(v.issues, 100).map(item => {
    const i = obj(item), id = text(i.id, 100), type = text(i.type, 40);
    if (!ISSUE_TYPES.includes(type) || ids.has(id) || !/^[a-z_]+-\d+$/.test(id)) bad("issue");
    ids.add(id);
    return {
      id, type, label: text(i.label, 300), quote: text(i.quote, 4000), locator: text(i.locator, 4000),
      rule: text(i.rule, 4000), limits: text(i.limits, 4000),
    };
  });
  return { citation, receipt, engine: { rulesVersion: text(obj(v.engine).rulesVersion, 100) }, issues };
}

// ---- Network ----
export class ApiFailure extends Error {
  // kind: "input" (refused before sending), "limited" (HTTP 429), "source" (Policy Sentinel answered with an error),
  // "service" (no answer, timeout, oversized or malformed response)
  constructor(message, kind) { super(message); this.name = "ApiFailure"; this.kind = kind; }
}

async function readJson(response) {
  if (Number(response.headers.get("Content-Length")) > MAX_BYTES || !response.body) throw new Error("Invalid response body");
  const reader = response.body.getReader(), chunks = [];
  let length = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > MAX_BYTES) throw new Error("Response is too large");
      chunks.push(value);
    }
  } catch (e) { await reader.cancel().catch(() => {}); throw e; }
  const bytes = new Uint8Array(length);
  let at = 0;
  for (const c of chunks) { bytes.set(c, at); at += c.length; }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
}

async function get(path, validate, signal) {
  const ctl = new AbortController(), stop = () => ctl.abort();
  signal?.addEventListener("abort", stop, { once: true });
  if (signal?.aborted) stop();
  const timer = setTimeout(stop, TIMEOUT_MS);
  try {
    const r = await fetch(API + path, { headers: { Accept: "application/json" }, signal: ctl.signal, referrerPolicy: "no-referrer" });
    let body;
    try { body = obj(await readJson(r)); } catch (e) {
      if (r.status === 429) throw new ApiFailure("limited", "limited");
      throw e;
    }
    if (!r.ok || body.ok === false) {
      throw new ApiFailure(typeof body.message === "string" && body.message.length <= 2000 ? body.message : "The source did not answer.",
        r.status === 429 ? "limited" : "source");
    }
    return validate(body);
  } catch (e) {
    throw e instanceof ApiFailure ? e : new ApiFailure("service", "service");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", stop);
  }
}

// Topic search (relevance), not an exact lookup: Policy Sentinel decides what matches.
export async function searchPolicies(source, q, signal) {
  const query = squash(q);
  if (!SOURCES.some(s => s.id === source) || query.length < 2 || query.length > 200)
    throw new ApiFailure("Enter 2 to 200 characters of search words.", "input");
  const params = new URLSearchParams({ source, q: query, page: "1" });
  return get(`/api/search?${params}`, v => searchValue(v, source, query), signal);
}

export async function readPolicy(source, id, signal) {
  const key = text(id, 300);
  if (!SOURCES.some(s => s.id === source)) throw new ApiFailure("Unknown source.", "input");
  return get(`/api/policy?${new URLSearchParams({ source, id: key })}`, v => policyValue(v, { source, id: key }), signal);
}

// ---- The note a draft keeps (SPEC 7) ----
// `policy` is a validated readPolicy() result, or { citation, receipt: null, engine: null, issues: [] } for a source
// that returns metadata only. Only the issues whose ids were chosen are kept, in the policy's own order.
export function noteFromPolicy(policy, issueIds, comment = "") {
  const c = policy.citation, chosen = new Set(issueIds);
  const id = globalThis.crypto?.randomUUID?.() ?? `n${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  return {
    id, sourceId: c.sourceId, identifier: c.identifier, title: c.title, issuingBody: c.issuingBody, kind: c.kind,
    date: c.date, officialUrl: c.officialUrl, textUrl: policy.receipt?.textUrl ?? c.textUrl ?? "",
    retrievedAt: policy.receipt?.retrievedAt ?? c.retrievedAt, receiptSha256: policy.receipt?.sha256 ?? "",
    rulesVersion: policy.engine?.rulesVersion ?? "",
    issues: policy.issues.filter(i => chosen.has(i.id)).map(({ id: iid, type, label, quote, locator, rule, limits }) =>
      ({ id: iid, type, label, quote, locator, rule, limits })),
    comment: String(comment ?? "").trim().slice(0, 2000),
  };
}

// ---- The panel ----
const MESSAGES = {
  limited: "Policy Sentinel is limiting requests. Try again in a minute.",
  service: "Policy Sentinel did not answer. The link below opens it directly.",
};
const meta = parts => parts.filter(Boolean).map(esc).join(", ");
const link = (url, label) => url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}<span class="visually-hidden"> (opens in a new tab)</span></a>` : "";

let allowed = false; // fail closed until capabilities.json says sentinel: true (D-059 item 5)
export function allowLookup(on) { allowed = on === true; }

export function openLookup({ query = "", onAddNote } = {}) {
  const dlg = document.createElement("dialog");
  if (!allowed || typeof dlg.showModal !== "function") { window.open(SENTINEL_HOME, "_blank", "noopener"); return; }
  const opener = document.activeElement;
  dlg.className = "sentinel";
  dlg.setAttribute("aria-labelledby", "sn-title");
  dlg.innerHTML = `
    <div class="dialog-head"><h2 id="sn-title">Look Up a Policy in Policy Sentinel</h2>
      <button type="button" class="btn quiet small" data-close>Close</button></div>
    <div class="dialog-body">
      <form class="sn-form" novalidate>
        <div class="field"><label for="sn-source">Source</label>
          <select id="sn-source">${SOURCES.map(s => `<option value="${esc(s.id)}">${esc(s.label)}</option>`).join("")}</select></div>
        <div class="field"><label for="sn-q">Search words</label>
          <input type="search" id="sn-q" maxlength="200" autocomplete="off" value="${esc(query)}"></div>
        <div class="sn-submit"><button type="submit" class="btn primary" aria-describedby="sn-privacy">Search Policy Sentinel</button>
          <p class="meta" id="sn-privacy"></p></div>
      </form>
      <p class="visually-hidden" role="status" id="sn-status"></p>
      <div class="sn-out"></div>
      <div class="sn-detail"></div>
      <p class="sn-links">${link(SENTINEL_HOME, "Open in Policy Sentinel")}</p>
    </div>`;
  document.body.append(dlg);
  const $ = s => dlg.querySelector(s);
  const form = $(".sn-form"), src = $("#sn-source"), input = $("#sn-q"), out = $(".sn-out"), detail = $(".sn-detail");
  let ctl = null, run = 0, found = [], chosen = 0;
  const say = s => { $("#sn-status").textContent = s; };
  const privacy = () => {
    const s = SOURCES.find(x => x.id === src.value);
    $("#sn-privacy").textContent = `Sends only these search words to Policy Sentinel, which searches ${s.name}. Your draft is never sent.`;
  };
  const problem = (target, e) => {
    const msg = e instanceof ApiFailure ? MESSAGES[e.kind] ?? e.message : MESSAGES.service;
    target.innerHTML = `<div class="notice" role="alert"><p>${esc(msg)}</p></div>`;
    say("");
  };
  const begin = (s) => { ctl?.abort(); ctl = new AbortController(); say(s); return ++run; };

  const results = total => {
    out.innerHTML = `<p class="meta">${found.length < (total ?? 0)
      ? `Showing the first ${found.length} of ${total.toLocaleString("en-US")} matches, best match first.`
      : `${found.length} ${found.length === 1 ? "policy" : "policies"} found.`}</p>
      <ul class="sn-list">${found.map((c, i) => `<li class="sn-item"><p class="sn-title">${esc(c.title)}</p>
        <p class="meta">${meta([c.identifier, c.issuingBody, c.kind, usDate(c.date)])}</p>
        <p class="sn-actions"><button type="button" class="btn small" data-read="${i}" aria-label="${esc(c.textAvailable ? "Read this policy" : "Use this policy")}: ${esc(c.identifier)}">${c.textAvailable ? "Read this policy" : "Use this policy, metadata only"}</button>
        ${link(c.officialUrl, "Official source")}</p></li>`).join("")}</ul>`;
    say(`${found.length} ${found.length === 1 ? "policy" : "policies"} found.`);
  };

  const flags = p => {
    const c = p.citation;
    out.hidden = true;
    detail.innerHTML = `<p><button type="button" class="btn small" data-back>Back to results</button></p>
      <h3 tabindex="-1">${esc(c.title)}</h3>
      <p class="meta">${meta([c.identifier, c.issuingBody, c.kind, usDate(c.date)])}</p>
      <p class="sn-actions">${link(c.officialUrl, "Official source")}${p.receipt ? link(p.receipt.textUrl, "Policy text") : ""}</p>
      <p class="meta">${p.receipt
        ? `Read by Policy Sentinel on ${esc(usDate(p.receipt.retrievedAt))}; text SHA-256 ${esc(p.receipt.sha256.slice(0, 16))}.`
        : "Policy Sentinel returns details only for this source, so no policy text was read and there are no flags."}</p>
      ${p.issues.length ? `<fieldset class="sn-flags"><legend>Flags to keep in your drafting notes</legend>
        ${p.issues.map(i => `<label class="check sn-flag"><input type="checkbox" value="${esc(i.id)}"><span>
          <strong>${esc(i.label)}:</strong> “${esc(i.quote)}”<br>
          <span class="meta">Location <code>${esc(i.locator)}</code></span><br>
          <span class="meta">Rule: ${esc(i.rule)}</span></span></label>`).join("")}</fieldset>
        <p class="meta">Flags come from automated demo rules (${esc(p.engine.rulesVersion)}). They quote the policy text and are not legal conclusions.</p>`
        : p.receipt ? "<p>No flags were found in this policy's text.</p>" : ""}
      <div class="field"><label for="sn-note">Your note</label><textarea id="sn-note" rows="3" maxlength="2000"></textarea></div>
      <button type="button" class="btn primary" data-add>Add note to draft</button>`;
    detail.querySelector("h3").focus();
    detail.querySelector("[data-add]").onclick = () => {
      const ids = [...detail.querySelectorAll(".sn-flag input:checked")].map(x => x.value);
      if (typeof onAddNote === "function") onAddNote(noteFromPolicy(p, ids, detail.querySelector("#sn-note").value));
      dlg.close();
    };
  };

  form.onsubmit = async e => {
    e.preventDefault();
    detail.innerHTML = ""; out.innerHTML = ""; out.hidden = false;
    const mine = begin("Searching Policy Sentinel");
    try {
      const r = await searchPolicies(src.value, input.value, ctl.signal);
      if (mine !== run) return;
      found = r.results;
      if (found.length) results(r.total);
      else { out.innerHTML = `<div class="notice"><p>No policies matched these words. Try the instrument's name or number.</p></div>`; say("No policies matched."); }
    } catch (err) { if (mine === run) problem(out, err); }
  };
  dlg.addEventListener("click", async e => {
    if (e.target.closest("[data-close]")) return dlg.close();
    if (e.target.closest("[data-back]")) {
      run++; ctl?.abort(); detail.innerHTML = ""; out.hidden = false; say("");
      return out.querySelector(`[data-read="${chosen}"]`)?.focus();
    }
    const i = e.target.closest("[data-read]")?.dataset.read;
    if (i === undefined) return;
    chosen = Number(i);
    const c = found[chosen];
    detail.innerHTML = "";
    if (!c.textAvailable) return flags({ citation: c, receipt: null, engine: null, issues: [] });
    const mine = begin("Reading the policy text");
    try {
      const p = await readPolicy(c.sourceId, policyId(c), ctl.signal);
      if (mine !== run) return;
      say("");
      flags(p);
    } catch (err) { if (mine === run) problem(detail, err); }
  });
  src.onchange = privacy;
  dlg.addEventListener("close", () => {
    run++; ctl?.abort(); dlg.remove();
    // Adding a note repaints the draft editor, which replaces the opener with a new button of the same id.
    const back = opener?.isConnected ? opener : opener?.id ? document.getElementById(opener.id) : null;
    try { back?.focus(); } catch { /* the opener is gone */ }
  });
  privacy();
  dlg.showModal();
  input.focus();
}
