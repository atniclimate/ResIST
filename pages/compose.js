// The one place a draft becomes resolution text (D-054). The on-screen sheet and the Word file both read
// compose(draft), so what the preview shows is what the document contains. Pure: no DOM, no storage, no network.
// Only ATNI's fixed form text and words a person typed or deliberately carried appear in the output; nothing here
// writes, suggests or completes resolution language (DG-11).
//
// The layout and form text follow ATNI's official fillable template ("2026 ATNI Annual Convention Resolution
// Template_FILLABLE.docx"). A line is an array of parts: a string, or { fill, value } for a detail the person
// supplies. An empty value is still unknown (convention details often are): the sheet shows "[fill]" and the Word
// file carries a fillable placeholder there, so it can be completed later in Word or re-exported from ResIST.

export const SCHEMA = "resist-draft/1";
export const ATNI = "AFFILIATED TRIBES OF NORTHWEST INDIANS";

// ATNI's form text, verbatim from the official template.
export const STANDARD = {
  preamble: "We, the members of the Affiliated Tribes of Northwest Indians of the United States, invoking the divine " +
    "blessing of the Creator upon our efforts and purposes, in order to preserve for ourselves and our descendants " +
    "rights secured under Indian Treaties and benefits to which we are entitled under the laws and Constitution of " +
    "the United States and several states, to enlighten the public toward a better understanding of the Indian " +
    "people, to preserve Indian cultural values, and otherwise promote the welfare of the Indian people, do hereby " +
    "establish and submit the following Resolution:",
  whereas: [
    "the Affiliated Tribes of Northwest Indians (ATNI) are the representatives and advocates for national, regional, " +
      "and specific tribal concerns",
    "the ATNI is a regional organization comprised of American Indians/Alaska Natives and Indian tribal governments " +
      "in the states of Washington, Idaho, Oregon, Montana, Nevada, Northern California, and Alaska",
    "creating opportunities for Indian Nations, preservation of tribal sovereignty and protection of cultural and " +
      "natural resources are primary goals and objectives of ATNI",
  ],
  closing: "that this will be the policy of ATNI until it is withdrawn or modified by subsequent resolutions",
  // The template's instruction for a resolution to be advanced to NCAI.
  ncai: "that this resolution shall be transmitted to the National Congress of American Indians",
};
// Wordings of the same standard clauses in ATNI's published 2024 to 2026 resolutions; recognized, never inserted.
const VARIANTS = [
  "the Affiliated Tribes of Northwest Indians (ATNI) are the representatives and advocates for national, regional, " +
    "and specific Tribal concerns",
  "ATNI is a regional organization comprised of American Indians/Alaska Natives and Indian Tribal governments in " +
    "the states of Washington, Idaho, Oregon, Montana, Nevada, Northern California, and Alaska",
  "the health, safety, welfare, education, economic and employment opportunity, and preservation of cultural and " +
    "natural resources are primary goals and objectives of ATNI",
  "that this will be the policy of ATNI until it is withdrawn or modified by subsequent resolution(s)",
  "that this resolution shall be the policy of ATNI until it is withdrawn or modified by subsequent resolution",
  "that this resolution shall be the policy of ATNI until it is withdrawn or modified by a subsequent resolution",
];

// The submission form's committee checkboxes, in the template's grid (4 columns, read across).
export const COMMITTEE_GRID = [
  ["Culture/Elders", "Health", "Native Vote", "Transportation"],
  ["Drug Abuse & Prev.", "Housing", "Natural Resources/Lands", "Trust Reform"],
  ["Economic Development", "Human Resources", "TANF", "Veterans"],
  ["Education", "ICWA", "Taxation", "Youth"],
  ["Energy", "Internal. Affairs", "Telecommunication", "Other"],
  ["Gaming", "Law & Justice", "TERO", ""],
];
// Alphabetical: the grid read down its columns, without "Other" (typed instead) and the empty cell.
export const COMMITTEES = [0, 1, 2, 3].flatMap(col => COMMITTEE_GRID.map(row => row[col]))
  .filter(name => name && name !== "Other");

const EN_DASH = "–";
export const squash = s => String(s ?? "").replace(/\s+/g, " ").trim();

// A page's running header ("AFFILIATED TRIBES OF NORTHWEST INDIANS RESOLUTION #2026 - 051 2026 ANNUAL CONVENTION
// PAGE 3") is extracted into about 11% of stored clauses that cross a page break. Matched case-sensitively, so the
// name in ordinary prose never matches.
const PAGE_HEADER = new RegExp(
  "\\s*" + ATNI + "\\s+RESOLUTION\\s*#\\s*\\d{2,4}\\s*[-–—�]?\\s*\\d{1,3}" +
  "(?:\\s+\\d{4}(?:\\s+[A-Z][A-Z-]*){0,3}?\\s+(?:CONVENTION|CONFERENCE))?(?:\\s+PAGE\\s+\\d+)?", "g");
export const hasPageHeader = text => new RegExp(PAGE_HEADER.source).test(text);
export const removePageHeader = text => squash(String(text ?? "").replace(PAGE_HEADER, " "));

// The lead words ("WHEREAS,", "BE IT FURTHER RESOLVED,") and the joiners ("; and", "; now", ".") belong to a
// clause's position, not its text, so they are stripped here and added back by compose().
const LEAD = /^(?:(?:now,?\s+)?(?:therefore,?\s+)?be\s+it\s+(?:further\s+|finally\s+)?resolved|whereas)\s*[,:]?\s*/i;
const JOINER = /\s*[;,]\s*(?:and\s+now|and|now)?\s*[,;]?\s*$/i;
// The next clause's "THEREFORE" sometimes lands at the end of the last WHEREAS in extraction.
const NEXT_LEAD = /\s*\b(?:now,?\s+)?therefore\s*[,:]?\s*$/i;
const ABBREVIATION = /(?:^|[\s(])(?:[A-Za-z]\.){2,}$|\b(?:etc|Inc|Co|Corp|Jr|Sr|No|Sec|Ch)\.$/;
export function body(text) {
  let s = squash(text).replace(LEAD, "");
  for (let prev = null; prev !== s;) {
    prev = s;
    s = s.replace(NEXT_LEAD, "").replace(JOINER, "");
    if (s.endsWith(".") && !ABBREVIATION.test(s)) s = s.slice(0, -1).trimEnd();
  }
  return s;
}

const same = (a, b) => body(a).toLowerCase() === body(b).toLowerCase();
export const isStandard = text =>
  [...STANDARD.whereas, STANDARD.closing, STANDARD.ncai, ...VARIANTS].some(s => same(s, text));
export const isNcaiTransmittal = text => same(STANDARD.ncai, text);

// "standard" ATNI form text | "typed" by a person | "verbatim" as carried | "cleaned" carried, with only a leaked
// page header removed | "edited" carried, then changed by a person.
export function clauseState(clause) {
  if (clause.origin !== "carried") return clause.origin === "standard" ? "standard" : "typed";
  const now = body(clause.text), was = body(clause.source?.text);
  if (now === was) return "verbatim";
  return now === body(removePageHeader(clause.source?.text)) ? "cleaned" : "edited";
}

export const newId = () => globalThis.crypto?.randomUUID?.() ?? `c${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
export function newClause(text, origin, source) {
  const id = newId();
  return source ? { id, text: body(text), origin, source } : { id, text: body(text), origin };
}

// ---- Carried citations (UI-2, D-077) ------------------------------------------------------------------------------
// clause.cites: [{ id, start, end, text, source }], sorted, non-overlapping; start/end are UTF-16 offsets into
// clause.text and text === clause.text.slice(start, end) === squash(source.text). A clause without one has no key.

// Plain and span pieces of a text, each with its whitespace collapsed; spans that do not fit are ignored.
export function segments(text, spans = []) {
  const t = String(text ?? ""), out = [];
  let at = 0;
  const push = (a, b, span) => out.push({ text: t.slice(a, b).replace(/\s+/g, " "), span });
  for (const sp of spans) {
    if (!(Number.isInteger(sp?.start) && Number.isInteger(sp?.end) && at <= sp.start && sp.start < sp.end && sp.end <= t.length)) continue;
    push(at, sp.start, null); push(sp.start, sp.end, sp); at = sp.end;
  }
  push(at, t.length, null);
  out[0].text = out[0].text.trimStart();
  out.at(-1).text = out.at(-1).text.trimEnd();
  return out.filter(p => p.span || p.text);
}

const isInt = v => Number.isInteger(v);
const okSource = s => s && typeof s === "object" && typeof s.documentId === "string" && typeof s.text === "string" &&
  ["whereas", "resolved"].includes(s.statementType) && isInt(s.index) && isInt(s.position) && isInt(s.start) &&
  isInt(s.end) && (s.page === null || isInt(s.page));
// A draft file is untrusted: only well-formed entries that still slice their clause survive (design D16).
export function cleanCites(clause) {
  if (!clause || !("cites" in clause)) return clause;
  const list = Array.isArray(clause.cites) ? clause.cites : [], text = clause.text, keep = [];
  for (const c of list) {
    const end = keep.at(-1)?.end ?? 0;
    if (c && typeof c.id === "string" && isInt(c.start) && isInt(c.end) && end <= c.start && c.start < c.end &&
      c.end <= text.length && typeof c.text === "string" && c.text === text.slice(c.start, c.end) &&
      okSource(c.source) && squash(c.source.text) === c.text) keep.push(c);
  }
  if (keep.length === list.length && list.length) return clause;
  const { cites, ...rest } = clause;
  return keep.length ? { ...rest, cites: keep } : rest;
}

// After the text changed: a citation still in place stays; a moved one follows its words (the occurrence nearest its
// old start); one whose words changed loses its mark and the words stay as typed text (D14). -> number dropped.
export function anchorCites(clause) {
  const list = clause?.cites;
  if (!Array.isArray(list)) return 0;
  const t = String(clause.text ?? "");
  const kept = list.filter(c => t.slice(c.start, c.end) === c.text);
  const free = (a, b) => kept.every(k => b <= k.start || a >= k.end);
  let dropped = 0;
  for (const c of list) if (!kept.includes(c)) {
    let best = -1;
    for (let i = t.indexOf(c.text); c.text && i >= 0; i = t.indexOf(c.text, i + 1))
      if (free(i, i + c.text.length) && (best < 0 || Math.abs(i - c.start) < Math.abs(best - c.start))) best = i;
    if (best < 0) { dropped++; continue; }
    c.start = best; c.end = best + c.text.length; kept.push(c);
  }
  kept.sort((a, b) => a.start - b.start);
  if (kept.length) clause.cites = kept; else delete clause.cites;
  return dropped;
}

// The Drafting Notes "From" cell of a compose() citation.
export const citeFrom = x =>
  `ATNI ${squash(x.number)}, ${x.clause}, ${Number.isInteger(x.page) ? `page ${x.page}` : "page unknown"}`;

// Splices a citation's words into a clause at a position (clamped, and moved past a citation it falls inside), with
// one separating space only where needed; later citations shift (D13). Mutates the clause. -> { start, end }.
export function insertCite(clause, at, cite) {
  const t = String(clause.text ?? ""), cites = clause.cites ?? [];
  let p = isInt(at) ? Math.max(0, Math.min(at, t.length)) : t.length;
  for (const c of cites) if (c.start < p && p < c.end) p = c.end;
  const before = p > 0 && !/\s/.test(t[p - 1]) ? " " : "";
  const after = p < t.length && !/[\s.,;:)]/.test(t[p]) ? " " : "";
  const add = before + cite.text + after, start = p + before.length, end = start + cite.text.length;
  clause.text = t.slice(0, p) + add + t.slice(p);
  for (const c of cites) if (c.start >= p) { c.start += add.length; c.end += add.length; }
  clause.cites = [...cites, { id: cite.id, start, end, text: cite.text, source: cite.source }].sort((a, b) => a.start - b.start);
  return { start, end };
}

// Convention details: every one may be unknown when a draft starts.
export const CONVENTION_FIELDS = ["convention", "year", "location", "venue", "dates", "draftDue", "finalDue", "formCode"];

export function newDraft(year = new Date().getFullYear()) {
  return {
    schema: SCHEMA,
    header: {
      convention: "", year, number: "DRFT-XX", location: "", venue: "", dates: "", draftDue: "", finalDue: "",
      formCode: "",
    },
    title: "",
    preamble: true,
    whereas: STANDARD.whereas.map(t => newClause(t, "standard")),
    resolved: [newClause(STANDARD.closing, "standard")],
    certification: { quorum: true },
    signatures: { president: "", secretary: "" },
    meta: {
      author: "", sponsor: "", sponsorInGoodStanding: false, committees: [], otherCommittee: "",
      ncai: { forward: false, emergency: "" },
    },
    notes: [],
  };
}

export function resolvedLead(i, n) {
  if (i === 0) return "THEREFORE, BE IT RESOLVED,";
  return i === n - 1 ? "BE IT FINALLY RESOLVED," : "BE IT FURTHER RESOLVED,";
}

const fill = (name, value) => ({ fill: name, value: squash(value) });
// A line as plain text, with unknown details shown as "[name]".
export const lineText = line => line.map(p => typeof p === "string" ? p : p.value || `[${p.fill}]`).join("");
export const usDate = iso => /^\d{4}-\d{2}-\d{2}/.test(iso ?? "") ? `${iso.slice(5, 7)}/${iso.slice(8, 10)}/${iso.slice(0, 4)}` : "";

export function compose(draft) {
  const h = draft.header, m = draft.meta, problems = [];
  const year = squash(h.year), number = squash(h.number) || "DRFT-XX";
  const live = list => list.filter(c => body(c.text));
  const whereas = live(draft.whereas), resolved = live(draft.resolved);
  const skipped = draft.whereas.length + draft.resolved.length - whereas.length - resolved.length;
  const position = (kind, i) => `${kind === "whereas" ? "WHEREAS" : "RESOLVED"} ${i + 1}`;
  const sources = [], citations = [];
  const lines = (kind, list) => list.map((c, i) => {
    const n = list.length, last = i === n - 1;
    const lead = kind === "whereas" ? "WHEREAS," : resolvedLead(i, n);
    const joiner = kind === "whereas" ? (last ? "; now" : "; and") : (last ? "." : "; and");
    const state = clauseState(c), text = body(c.text), cites = c.cites ?? [];
    if (hasPageHeader(c.text)) problems.push(`${position(kind, i)} contains page-header text from the source PDF.`);
    if (c.origin === "carried") sources.push({
      position: position(kind, i), state, number: c.source.number, title: c.source.title, year: c.source.year,
      convention: c.source.convention, url: c.source.url, documentId: c.source.documentId,
    });
    for (const x of cites) citations.push({
      position: position(kind, i), text: x.text, number: x.source.number, title: x.source.title, year: x.source.year,
      documentId: x.source.documentId, clause: position(x.source.statementType, x.source.position - 1),
      page: Number.isInteger(x.source.page) ? x.source.page : null, url: x.source.url,
    });
    // Offsets index the line only while the stored text is already its own body.
    const marks = text === c.text ? cites.map(x => ({ start: x.start, end: x.end })) : [];
    return { id: c.id, lead, text: text + joiner, state, marks };
  });
  const convention = fill("Convention", h.convention);
  const others = squash(m.otherCommittee);
  const out = {
    heading: [["ATNI ", convention], [fill("City, State", h.location)]],
    number: `RESOLUTION # ${year || "[Year]"} ${EN_DASH} ${number}`,
    deadlines: [
      ["Draft 1 Due to the ATNI Workroom by ", fill("Draft 1 due date", h.draftDue)],
      ["Final Draft passed by Committee due to the ATNI Workroom by ", fill("Final draft due date and time", h.finalDue)],
    ],
    title: ["“", fill("Resolution title", draft.title), "”"],
    preamble: draft.preamble ? STANDARD.preamble : null,
    whereas: lines("whereas", whereas),
    resolved: lines("resolved", resolved),
    certification: [
      "The foregoing Resolution was adopted at the Affiliated Tribes of Northwest Indians ", convention,
      " held at the ", fill("Venue", h.venue), " in ", fill("City, State", h.location), " on ",
      fill("Convention dates", h.dates), draft.certification.quorum ? ", with a quorum present." : ".",
    ],
    signatures: [[fill("President's name", draft.signatures.president), ", President"],
      [fill("Secretary's name", draft.signatures.secretary), ", Secretary"]],
    runningHeader: `${ATNI} RESOLUTION #${year || "[Year]"}-${number}`,
    runningFooter: lineText([convention]).toUpperCase(),
    form: {
      title: [fill("Resolution title", draft.title)],
      author: [fill("Author", m.author)],
      sponsor: [fill("Sponsor", m.sponsor)],
      ncaiForward: Boolean(m.ncai.forward),
      committees: COMMITTEE_GRID.map(row => row.map(name => name && {
        name, checked: name === "Other" ? Boolean(others) : m.committees.includes(name),
      })),
      otherCommittee: others,
      formCode: squash(h.formCode),
      ncai: m.ncai.forward ? { emergency: squash(m.ncai.emergency) } : null,
    },
    sources,
    citations,
    notes: draft.notes,
    problems,
  };
  if (!squash(draft.title)) problems.unshift("Add a title.");
  if (!resolved.some(c => !isStandard(c.text))) problems.push("Add at least one RESOLVED clause of your own.");
  if (m.ncai.forward && !resolved.some(c => isNcaiTransmittal(c.text)))
    problems.push("A resolution forwarded to NCAI needs ATNI's transmittal clause.");
  if (!squash(m.sponsor)) problems.push("Name the sponsor.");
  if (!m.sponsorInGoodStanding) problems.push("Confirm the sponsor is an ATNI Member in Good Standing.");
  if (!m.committees.length && !others) problems.push("Select at least one ATNI committee.");
  if (skipped) problems.push(`${skipped} empty clause${skipped === 1 ? " is" : "s are"} left out.`);
  const unknown = ["convention", "location", "venue", "dates"].filter(k => !squash(h[k]));
  if (unknown.length) problems.push("Convention details still to fill in: " +
    unknown.map(k => ({ convention: "name", location: "city and state", venue: "venue", dates: "dates" })[k]).join(", ") +
    ". The Word file keeps fillable placeholders for them.");
  return out;
}

// Accepts a parsed draft file only if it has the shape compose() reads; returns it with any missing fields filled.
export function validDraft(value) {
  const d = value && typeof value === "object" ? value : null;
  if (!d || d.schema !== SCHEMA || !Array.isArray(d.whereas) || !Array.isArray(d.resolved)) return null;
  const okClause = c => c && typeof c.id === "string" && typeof c.text === "string" &&
    ["standard", "typed", "carried"].includes(c.origin) && (c.origin !== "carried" || (c.source && typeof c.source.text === "string"));
  if (![...d.whereas, ...d.resolved].every(okClause)) return null;
  const base = newDraft(Number(d.header?.year) || undefined);
  const meta = { ...base.meta, ...d.meta, ncai: { ...base.meta.ncai, ...d.meta?.ncai } };
  meta.committees = Array.isArray(meta.committees) ? meta.committees.filter(c => COMMITTEES.includes(c)) : [];
  // A file can label any text "standard"; only ATNI's own form text keeps that label.
  const label = c => c.origin === "standard" && !isStandard(c.text) ? { ...c, origin: "typed" } : c;
  const clean = c => cleanCites(label(c));
  return {
    ...base, ...d,
    whereas: d.whereas.map(clean), resolved: d.resolved.map(clean),
    header: { ...base.header, ...d.header },
    certification: { ...base.certification, ...d.certification },
    signatures: { ...base.signatures, ...d.signatures },
    meta,
    notes: Array.isArray(d.notes) ? d.notes.filter(n => n && typeof n.title === "string" && Array.isArray(n.issues)) : [],
  };
}

// A draft file is untrusted input: only plain https links are ever rendered as links.
export const safeUrl = u => /^https:\/\/[^\s"'<>\\]+$/.test(String(u ?? "")) ? String(u) : "";
