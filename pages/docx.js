// Word export (SPEC section 8, D-054): compose(draft) becomes a .docx laid out like ATNI's official fillable template
// ("2026 ATNI Annual Convention Resolution Template_FILLABLE.docx"). Pure: no DOM, no fetch, no dependency; the
// OOXML is written by hand and zipped here (STORE method, CRC-32, fixed timestamp, so the same draft always gives the
// same bytes). Every word in the file is ATNI's form text, the person's own words, or text they carried verbatim.
// An unknown detail becomes a fillable plain-text content control, and checkboxes stay clickable in Word.
import { lineText, usDate, safeUrl, ATNI } from "./compose.js";

const NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' +
  'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ' +
  'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" ' +
  'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' +
  'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" ' +
  'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" ' +
  'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" mc:Ignorable="w14"';
const XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
const REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml";

// Clause text comes from OCR: drop what XML 1.0 forbids (C0 controls, lone surrogates, U+FFFE/U+FFFF), then escape.
const clean = s => String(s ?? "").replace(/[^\t\n\r -퟿-�\u{10000}-\u{10FFFF}]/gu, "");
export const xml = s => clean(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---- runs and paragraphs ----------------------------------------------------------------------------------------
// f: { b, i, u, caps, sz, color, style } in schema order.
function rPr(f = {}) {
  const x = (f.style ? `<w:rStyle w:val="${f.style}"/>` : "") + (f.font ? `<w:rFonts w:ascii="${f.font}" w:eastAsia="${f.font}" w:hAnsi="${f.font}" w:hint="eastAsia"/>` : "") +
    (f.b ? "<w:b/><w:bCs/>" : "") + (f.i ? "<w:i/><w:iCs/>" : "") + (f.caps ? "<w:caps/>" : "") +
    (f.color ? `<w:color w:val="${f.color}"/>` : "") + (f.sz ? `<w:sz w:val="${f.sz}"/><w:szCs w:val="${f.sz}"/>` : "") +
    (f.u ? '<w:u w:val="single"/>' : "");
  return x ? `<w:rPr>${x}</w:rPr>` : "";
}
const run = (text, f) => `<w:r>${rPr(f)}<w:t xml:space="preserve">${xml(text)}</w:t></w:r>`;
const tab = f => `<w:r>${rPr(f)}<w:tab/></w:r>`;
// p: { jc, ind, firstLine, after, line, keep, pageBreak, tabs: [[kind, pos]], border: "top"|"bottom", style, sz }
function para(content, p = {}) {
  const x = (p.style ? `<w:pStyle w:val="${p.style}"/>` : "") + (p.keep ? "<w:keepNext/><w:keepLines/>" : "") +
    (p.pageBreak ? "<w:pageBreakBefore/>" : "") +
    (p.border ? `<w:pBdr><w:${p.border} w:val="single" w:sz="18" w:space="1" w:color="auto"/></w:pBdr>` : "") +
    (p.tabs ? `<w:tabs>${p.tabs.map(([k, pos]) => `<w:tab w:val="${k}" w:pos="${pos}"/>`).join("")}</w:tabs>` : "") +
    (p.after !== undefined || p.line ? `<w:spacing${p.before ? ` w:before="${p.before}"` : ""}${p.after !== undefined ? ` w:after="${p.after}"` : ""}${p.line ? ` w:line="${p.line}" w:lineRule="auto"` : ""}/>` : "") +
    (p.ind !== undefined || p.firstLine ? `<w:ind${p.ind !== undefined ? ` w:left="${p.ind}"` : ""}${p.firstLine ? ` w:firstLine="${p.firstLine}"` : ""}/>` : "") +
    (p.jc ? `<w:jc w:val="${p.jc}"/>` : "") + (p.sz ? rPr({ sz: p.sz }) : "") + (p.sect || "");
  return `<w:p>${x ? `<w:pPr>${x}</w:pPr>` : ""}${content}</w:p>`;
}
const blank = (p = {}) => para("", { after: 0, ...p });
// The forms are set in 11pt, as in the template, through the "Form" paragraph style.
const formPara = (content, p = {}) => para(content, { style: "Form", ...p });
const formBlank = (p = {}) => formPara("", { after: 0, ...p });

// Builds the parts of one document; ids and relationships are counted so the output is deterministic.
function writer() {
  let sdt = 100, drawing = 0;
  const rels = [];
  const w = {
    rels,
    rel(type, target, external) {
      const id = `rId${rels.length + 1}`;
      rels.push(`<Relationship Id="${id}" Type="${REL}/${type}" Target="${xml(target)}"${external ? ' TargetMode="External"' : ""}/>`);
      return id;
    },
    // An unknown detail: a plain-text control whose placeholder "[name]" Word replaces when the person types.
    fill(name, f = {}) {
      const tag = xml(name);
      return `<w:sdt><w:sdtPr>${rPr(f)}<w:alias w:val="${tag}"/><w:tag w:val="${tag}"/><w:id w:val="${++sdt}"/>` +
        `<w:showingPlcHdr/><w:text/></w:sdtPr><w:sdtContent>${run(`[${name}]`, { ...f, style: "PlaceholderText" })}</w:sdtContent></w:sdt>`;
    },
    // A clickable checkbox (w14), tagged so it can be found; checked U+2612, unchecked U+2610 in MS Gothic.
    box(tagName, checked, f = {}) {
      return `<w:sdt><w:sdtPr>${rPr(f)}<w:alias w:val="${xml(tagName)}"/><w:tag w:val="${xml(tagName)}"/><w:id w:val="${++sdt}"/>` +
        `<w14:checkbox><w14:checked w14:val="${checked ? 1 : 0}"/><w14:checkedState w14:val="2612" w14:font="MS Gothic"/>` +
        `<w14:uncheckedState w14:val="2610" w14:font="MS Gothic"/></w14:checkbox></w:sdtPr><w:sdtContent>` +
        `${run(checked ? "☒" : "☐", { ...f, font: "MS Gothic" })}</w:sdtContent></w:sdt>`;
    },
    // A line from compose(): strings as runs, known values as runs, unknown values as fillable controls.
    line(parts, f = {}) {
      return parts.map(part => typeof part === "string" ? (part ? run(part, f) : "")
        : part.value ? run(part.value, f) : w.fill(part.fill, f)).join("");
    },
    link(url, f = {}) {
      const safe = safeUrl(url);
      if (!safe) return run(String(url ?? ""), f);
      return `<w:hyperlink r:id="${w.rel("hyperlink", safe, true)}" w:history="1">${run(safe, { ...f, style: "Hyperlink" })}</w:hyperlink>`;
    },
    picture(relId, emu, anchor) {
      const id = ++drawing;
      const graphic = `<wp:docPr id="${id}" name="ATNI seal ${id}" descr="Seal of the Affiliated Tribes of Northwest Indians"/>` +
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>' +
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>' +
        `<pic:nvPicPr><pic:cNvPr id="${id}" name="seal.jpg"/><pic:cNvPicPr/></pic:nvPicPr>` +
        `<pic:blipFill><a:blip r:embed="${relId}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>` +
        `<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="${emu}" cy="${emu}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>` +
        "</pic:pic></a:graphicData></a:graphic>";
      const extent = `<wp:extent cx="${emu}" cy="${emu}"/><wp:effectExtent l="0" t="0" r="0" b="0"/>`;
      // The form header places the seal at the top left beside the centered title, as the template does.
      const body = anchor
        ? `<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="251659264" behindDoc="1" locked="0" layoutInCell="1" allowOverlap="1">` +
          `<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="column"><wp:posOffset>${anchor.x}</wp:posOffset></wp:positionH>` +
          `<wp:positionV relativeFrom="paragraph"><wp:posOffset>${anchor.y}</wp:posOffset></wp:positionV>${extent}<wp:wrapNone/>${graphic}</wp:anchor>`
        : `<wp:inline distT="0" distB="0" distL="0" distR="0">${extent}${graphic}</wp:inline>`;
      return `<w:r><w:rPr><w:noProof/></w:rPr><w:drawing>${body}</w:drawing></w:r>`;
    },
  };
  return w;
}

// shortcut: the seal is drawn square (ATNI's seal file is 362 x 362); read the JPEG size if another image is used.
const INCH = 914400;

// ---- section 1: the resolution ----------------------------------------------------------------------------------
function resolution(m, w, sealRel) {
  const TNR12 = { sz: 24 }, center = { jc: "center", after: 0, line: 240 };
  const out = [
    sealRel ? para(w.picture(sealRel, Math.round(1.75 * INCH)), { jc: "center" }) : blank({ jc: "center" }),
    ...m.heading.map(l => para(w.line(l, { b: true, sz: 32 }), center)),
    blank(),
    para(run(m.number, { b: true, sz: 28 }), center),
    blank(),
    para(w.line(m.deadlines[0], { b: true, i: true, sz: 28 }), center),
    blank(),
    para(w.line(m.deadlines[1], { b: true, i: true, sz: 28 }), center),
    blank(),
    para(w.line(m.title), { style: "ResTitle" }),
    blank(),
  ];
  if (m.preamble) out.push(para(run("PREAMBLE", { b: true, sz: 28 }), center), blank(),
    para(run(m.preamble, TNR12), { after: 0, line: 240 }), blank());
  for (const c of [...m.whereas, ...m.resolved])
    out.push(para(run(c.lead, { b: true }) + run(` ${c.text}`), { firstLine: 720, line: 240 }));
  const keep = { after: 0, line: 240, keep: true };
  out.push(blank(),
    para(run("CERTIFICATION", { b: true, u: true }), { ...keep, jc: "center" }),
    blank({ keep: true }),
    para(w.line(m.certification), keep),
    blank({ keep: true }), blank({ keep: true }), blank({ keep: true }),
    para(run("______________________________") + tab() + run("______________________________"), { ...keep, tabs: [["left", 5040]] }),
    para(w.line(m.signatures[0]) + tab() + w.line(m.signatures[1]), { after: 0, line: 240, tabs: [["left", 5040]] }));
  return out.join("");
}

// ---- section 2: the Resolution Submission Form and, when forwarding, the NCAI Form ----------------------------------
function form(m, w) {
  const para = formPara, blank = formBlank;
  const f = m.form, B = { b: true }, P = { ind: -630, after: 120 };
  const label = (text, value) => run(text, B) + run(" ") + value;
  const pair = (a, b) => para(a + run("    ") + b, P);
  const choice = (tag, yes) => w.box(`${tag}: Yes`, yes === true, B) + run(" Yes   ", B) + w.box(`${tag}: No`, yes === false, B) + run(" No", B);
  const bi13 = { b: true, i: true, sz: 26 };
  // The box glyph is never italic (MS Gothic has no italic; Word would slant it).
  const check = (tag, text, fmt = {}) => para(w.box(tag, false, { ...fmt, i: false }) + run(" ") + (Array.isArray(text) ? text.map(([t, x]) => run(t, { ...fmt, ...x })).join("") : run(text, fmt)), { after: 120 });
  const heading = text => para(run(text, { b: true, sz: 32 }), { ind: -630, before: 240, after: 80, keep: true });
  const cell = c => `<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>${para(c ? w.box(`Committee: ${c.name}`, c.checked, { b: true, color: "595959" }) +
    run(` ${c.name}`, { b: true, color: "595959" }) + (c.name === "Other" && f.otherCommittee ? run(`: ${f.otherCommittee}`, { b: true }) : "") : "", { after: 60 })}</w:tc>`;
  const cols = [2770, 2917, 2768, 2323];
  const grid = `<w:tbl><w:tblPr><w:tblStyle w:val="FormGrid"/><w:tblW w:w="${cols.reduce((a, b) => a + b)}" w:type="dxa"/><w:jc w:val="center"/>` +
    '<w:tblLayout w:type="fixed"/><w:tblLook w:val="0000" w:firstRow="0" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" w:noHBand="1" w:noVBand="1"/></w:tblPr>' +
    `<w:tblGrid>${cols.map(c => `<w:gridCol w:w="${c}"/>`).join("")}</w:tblGrid>` +
    f.committees.map(row => `<w:tr><w:trPr><w:trHeight w:val="270"/></w:trPr>${row.map(cell).join("")}</w:tr>`).join("") + "</w:tbl>";

  const out = [
    blank(), blank({ sz: 16 }),
    para(run("Resolution Title:", { b: true, sz: 24 }) + run(" ") + w.line(f.title, { sz: 24 }), { ind: -630, after: 240 }),
    pair(label("Author of Resolution:", w.line(f.author)), label("Cell Phone:", w.fill("Author's cell phone"))),
    para(label("Author’s Email:", w.fill("Author's email")), P),
    blank(),
    para(run("Sponsor must be an ATNI Member in Good Standing.", B), { ind: -630, after: 0 }),
    pair(label("Sponsor of Resolution*:", w.line(f.sponsor)), label("Cell Phone:", w.fill("Sponsor's cell phone"))),
    para(label("Sponsor’s Email:", w.fill("Sponsor's email")), P),
    blank(),
    para(run("Does this resolution have attachments to be included ", B) + run("(if yes, please attach)") + tab() +
      choice("Attachments", null), { ind: -630, after: 200, tabs: [["left", 7200]] }),
    para(run("Request to Forward this Resolution to NCAI", { b: true, u: true }) + run("?", B) + tab() +
      choice("Forward to NCAI", f.ncaiForward), { ind: -630, after: 60, tabs: [["left", 7200]] }),
    para(run("IF YES, you must complete the NCAI Form at the end of this document", { b: true, i: true }) + run(".", { i: true }), { ind: -630 }),
    para(run("ATNI Committees ", B) + run("(please select at least one)"), { ind: -630, after: 60, keep: true }),
    grid,
    blank(),
    pair(label("Committee Chair:", w.fill("Committee Chair")), label("Cell Phone:", w.fill("Committee Chair's cell phone"))),
    pair(label("Committee Co-Chair:", w.fill("Committee Co-Chair")), label("Cell Phone:", w.fill("Committee Co-Chair's cell phone"))),
    blank(),
    para(run("Electronic Copy of Final resolution was submitted by:", B), { ind: -630 }),
    check("Submitted by: Email", "Email (to the ATNI Workroom)", bi13),
    check("Submitted by: Committee Thumb Drive", "Committee Thumb Drive", bi13),
    para(w.box("Submitted by: Other", false, { ...bi13, i: false }) + run(" Other ", bi13) + w.fill("Other way submitted"), { after: 120 }),
    heading("Certification"),
    check("Chair verifies: no edits outside Committee", "Committee Chair verifies that no additional edits or changes were made to this resolution outside of the Committee", bi13),
    check("Chair verifies: final version", "Committee Chair verifies that this is the final version of the Resolution", bi13),
    check("Chair verifies: not duplicative", "Committee Chair verifies that they have reviewed the ATNI Resolutions Table and that this Resolution is not duplicative of an ATNI Standing Resolution", bi13),
    check("Chair verifies: correct and complete", "Committee Chair verifies that the information provided herein is correct and complete.", bi13),
    blank(),
    para(run("Name of Committee Chair submitting this Resolution", bi13) + run(": ") + w.fill("Name of Committee Chair submitting"), { after: 120 }),
    para(run("Cell Phone", bi13) + run(": ") + w.fill("Submitting Chair's cell phone"), { after: 120 }),
  ];
  if (f.ncai) out.push(ncaiForm(m, w));
  return out.join("");
}

function ncaiForm(m, w) {
  const para = formPara, blank = formBlank;
  const f = m.form, P = { ind: -630 }, I = { i: true }, BU = { b: true, u: true };
  const heading = text => para(run(text, { b: true, sz: 32 }), { ind: -630, before: 360, after: 80, keep: true });
  const check = (tag, parts, fmt = {}) => para(w.box(tag, false, { ...fmt, i: false }) + run(" ") + parts.map(([t, x]) => run(t, { ...fmt, ...x })).join(""));
  const field = (text, name) => para(run(`${text}: `) + w.fill(name));
  return [
    para(run("NCAI Form", { b: true, u: true, sz: 34 }), { ...P, pageBreak: true }),
    blank(),
    para(run("If this resolution is requested to go to NCAI, this form must be completed in its entirety.", { b: true }), P),
    para(run("Note that NCAI will only accept resolutions that are emergency in nature at its Executive Council Winter Session (February) and the Mid-year (June) Conventions.", I), P),
    heading("Confirm that the Resolution is In-Order"),
    para(run("NCAI Resolution Sponsors must be NCAI Individual Indian Members in good standing. Tribal Nations, organizations, institutions, and individual Associate Members cannot be Sponsors."), P),
    check("NCAI: Member in Good Standing", [["Sponsor verifies that they are currently an NCAI Member in Good Standing"]]),
    check("NCAI: will attend Convention", [["Sponsor verifies that they (or a designee) will register for and attend the upcoming NCAI Convention"]]),
    check("NCAI: will attend committee meetings", [["Sponsor verifies that they (or a designee) will attend the appropriate sub-committee and committee meetings to introduce and speak to the Resolution."]]),
    para(w.box("NCAI: not duplicative", false) + run(" Sponsor verifies that they have searched prior adopted Resolutions to ensure that it is not duplicative (visit ") +
      w.link("https://www.ncai.org/resolutions") + run(").")),
    para(run("If this Resolution is intended to amend or supersede a standing resolution, please list the Resolution number and Title here: ") +
      w.fill("Resolution number and title")),
    check("NCAI: general and national", [["Sponsor verifies that the resolution is “"], ["general in nature", I], ["” and “"], ["national in scope", I], [".”"]]),
    para(run("FOR ECWS AND MIDYEAR ONLY", { b: true, i: true, u: true })),
    check("NCAI: emergency in nature", [["Sponsor verifies that the Resolution is “"], ["emergency in nature", I], ["”."]]),
    para(run("Please describe how this resolution meets the “") + run("emergency in nature", I) + run("” threshold:")),
    para(f.ncai.emergency ? run(f.ncai.emergency) : w.fill("Why is this resolution emergency in nature?")),
    heading("Contact Information"),
    para(run("NCAI will coordinate directly with the Resolution Sponsor for any questions about the Resolution.", I)),
    para(run("Sponsor Contact Information", BU)),
    para(run("Name: ") + w.line(f.sponsor)),
    field("Tribal Nation", "Sponsor's Tribal Nation"),
    field("Email", "Sponsor's email for NCAI"),
    field("Phone Number", "Sponsor's phone number"),
    blank(),
    para(run("Designee Contact Information (optional)", BU)),
    para(run("If someone other than the sponsor will be attending as a proxy representative and can speak to the Resolution on behalf of the Sponsor, please complete this section.", I)),
    field("Name", "Designee's name"),
    field("Email", "Designee's email"),
    field("Phone Number", "Designee's phone number"),
    blank(), blank(),
    check("NCAI: Sponsor verifies information", [["By clicking this box, Sponsor verifies that the information provided herein is correct and complete."]], { b: true, i: true, sz: 26 }),
  ].join("");
}

// ---- section 3: Drafting Notes ----------------------------------------------------------------------------------
const TEXT_STATE = { verbatim: "Verbatim", cleaned: "Verbatim, page header removed", edited: "Edited by the drafter" };
const sha16 = s => String(s ?? "").slice(0, 16);
function notes(m, w) {
  const S = { sz: 20 }, grey = { sz: 20, color: "595959" };
  const out = [para(run("Prepared with ResIST. These notes record where carried clauses came from and what Policy Sentinel found. " +
    "Delete this section before submitting if it is not wanted.", { i: true }))];
  if (m.sources.length) {
    const cols = [1500, 3400, 1500, 2960];
    const cell = (content, width) => `<w:tc><w:tcPr><w:tcW w:w="${width}" w:type="dxa"/></w:tcPr>${para(content, { after: 40 })}</w:tc>`;
    const row = (cells, head) => `<w:tr>${head ? "<w:trPr><w:tblHeader/></w:trPr>" : ""}${cells.map((c, i) => cell(c, cols[i])).join("")}</w:tr>`;
    const H = { b: true, sz: 20 };
    out.push(para(run("Sources of Carried Clauses", { b: true }), { keep: true, after: 80 }),
      `<w:tbl><w:tblPr><w:tblStyle w:val="NotesTable"/><w:tblW w:w="9360" w:type="dxa"/><w:tblLayout w:type="fixed"/>` +
      '<w:tblLook w:val="0000" w:firstRow="0" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" w:noHBand="1" w:noVBand="1"/></w:tblPr>' +
      `<w:tblGrid>${cols.map(c => `<w:gridCol w:w="${c}"/>`).join("")}</w:tblGrid>` +
      row([run("Position", H), run("ATNI resolution", H), run("Text", H), run("Source", H)], true) +
      m.sources.map(s => row([
        run(s.position, S),
        run([s.number, s.title, s.year].map(x => String(x ?? "")).filter(Boolean).join(", "), S),
        run(TEXT_STATE[s.state] || "Verbatim", S),
        w.link(s.url, S) + `<w:r><w:br/></w:r>` + run(`SHA-256 ${sha16(s.documentId)}`, grey),
      ])).join("") + "</w:tbl>", blank({ after: 160 }));
  }
  for (const n of m.notes) {
    const meta = [n.issuingBody, n.kind, usDate(n.date)].map(x => String(x ?? "")).filter(Boolean).join(", ");
    out.push(para(run(String(n.title ?? ""), { b: true }), { keep: true, after: 40 }));
    if (meta) out.push(para(run(meta), { after: 40 }));
    if (n.officialUrl) out.push(para(w.link(n.officialUrl), { after: 40 }));
    const on = usDate(n.retrievedAt) || "an unrecorded date";
    out.push(para(run(n.receiptSha256 ? `Read by Policy Sentinel on ${on}; text SHA-256 ${sha16(n.receiptSha256)}`
      : `Details from Policy Sentinel on ${on}; no policy text was read.`), { after: 120 }));
    for (const i of (Array.isArray(n.issues) ? n.issues : []).filter(x => x && typeof x === "object")) {
      out.push(para(run(`${String(i.label ?? "")}: “${String(i.quote ?? "")}”`) + (i.locator ? run(` (${String(i.locator)})`) : ""), { after: 0, ind: 360, keep: true }));
      if (i.rule) out.push(para(run(`Rule: ${String(i.rule)}`, grey), { after: 120, ind: 360 }));
    }
    if (String(n.comment ?? "").trim()) out.push(para(run(`Drafter's note: ${String(n.comment).trim()}`), { after: 120 }));
    out.push(blank({ after: 120 }));
  }
  if (m.notes.length) out.push(para(run("Policy Sentinel's flags come from automated demo rules. They quote the policy text and are not legal conclusions.", { sz: 20, i: true })));
  return out.join("");
}

// ---- headers, footers, styles, package --------------------------------------------------------------------------
const hdr = body => `${XML}<w:hdr ${NS}>${body || "<w:p/>"}</w:hdr>`;
const ftr = body => `${XML}<w:ftr ${NS}>${body || "<w:p/>"}</w:ftr>`;

function styles() {
  return `${XML}<w:styles ${NS}><w:docDefaults><w:rPrDefault><w:rPr>` +
    '<w:rFonts w:ascii="Times New Roman" w:eastAsia="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>' +
    '<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="en-US" w:eastAsia="en-US" w:bidi="ar-SA"/></w:rPr></w:rPrDefault>' +
    '<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>' +
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>' +
    '<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont"><w:name w:val="Default Paragraph Font"/><w:uiPriority w:val="1"/><w:semiHidden/><w:unhideWhenUsed/></w:style>' +
    '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:uiPriority w:val="99"/><w:semiHidden/><w:unhideWhenUsed/>' +
    '<w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>' +
    '<w:style w:type="paragraph" w:customStyle="1" w:styleId="Form"><w:name w:val="Form"/><w:basedOn w:val="Normal"/><w:qFormat/><w:rPr><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>' +
    '<w:style w:type="paragraph" w:customStyle="1" w:styleId="ResTitle"><w:name w:val="ResTitle"/><w:basedOn w:val="Normal"/><w:qFormat/>' +
    '<w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/><w:jc w:val="center"/></w:pPr><w:rPr><w:b/><w:bCs/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>' +
    '<w:style w:type="paragraph" w:styleId="Header"><w:name w:val="header"/><w:basedOn w:val="Normal"/><w:pPr><w:tabs><w:tab w:val="center" w:pos="4680"/><w:tab w:val="right" w:pos="9360"/></w:tabs><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:style>' +
    '<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/><w:pPr><w:tabs><w:tab w:val="center" w:pos="4680"/><w:tab w:val="right" w:pos="9360"/></w:tabs><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:style>' +
    '<w:style w:type="character" w:styleId="PlaceholderText"><w:name w:val="Placeholder Text"/><w:basedOn w:val="DefaultParagraphFont"/><w:uiPriority w:val="99"/><w:semiHidden/><w:rPr><w:color w:val="666666"/></w:rPr></w:style>' +
    '<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:basedOn w:val="DefaultParagraphFont"/><w:uiPriority w:val="99"/><w:unhideWhenUsed/><w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style>' +
    // Borderless, for layout tables; the committee grid and the notes table add the template's thin rules.
    '<w:style w:type="table" w:customStyle="1" w:styleId="PlainTable"><w:name w:val="Plain Table"/><w:basedOn w:val="TableNormal"/><w:tblPr><w:tblBorders>' +
    ["top", "left", "bottom", "right", "insideH", "insideV"].map(b => `<w:${b} w:val="nil"/>`).join("") + "</w:tblBorders></w:tblPr></w:style>" +
    ["FormGrid", "NotesTable"].map(id => `<w:style w:type="table" w:customStyle="1" w:styleId="${id}"><w:name w:val="${id === "FormGrid" ? "Form Grid" : "Notes Table"}"/><w:basedOn w:val="PlainTable"/><w:tblPr><w:tblBorders>` +
      ["top", "left", "bottom", "right", "insideH", "insideV"].map(b => `<w:${b} w:val="single" w:sz="4" w:space="0" w:color="${id === "FormGrid" ? "000000" : "A6A6A6"}"/>`).join("") +
      '</w:tblBorders><w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="40" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>').join("") +
    "</w:styles>";
}

const SETTINGS = `${XML}<w:settings ${NS}><w:zoom w:percent="100"/><w:defaultTabStop w:val="720"/>` +
  '<w:characterSpacingControl w:val="doNotCompress"/><w:compat><w:compatSetting w:name="compatibilityMode" ' +
  'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>';

const sectPr = (refs, titlePg) => "<w:sectPr>" +
  refs.map(([kind, type, id]) => `<w:${kind}Reference w:type="${type}" r:id="${id}"/>`).join("") +
  '<w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>' +
  `<w:pgNumType w:start="1"/><w:cols w:space="720"/>${titlePg ? "<w:titlePg/>" : ""}</w:sectPr>`;

export function buildDocx(model, { seal, created } = {}) {
  const m = model, w = writer(), parts = [], types = [];
  const part = (name, body, type) => { parts.push([name, body]); if (type) types.push([name, type]); };
  const sealBytes = seal instanceof Uint8Array && seal.length ? seal : null;
  // Relationship ids are assigned in a fixed order: styles, settings, then each header and footer, then the seal.
  w.rel("styles", "styles.xml"); w.rel("settings", "settings.xml");
  const count = { header: 0, footer: 0 };
  const headerPart = (kind, body, rels) => {
    const name = `${kind}${++count[kind]}.xml`;
    part(`word/${name}`, kind === "header" ? hdr(body) : ftr(body), `${DOCX_TYPE}.${kind}+xml`);
    if (rels) part(`word/_rels/${name}.rels`, rels);
    return w.rel(kind, name);
  };
  const sealRel = sealBytes ? w.rel("image", "media/seal.jpg") : null;

  // Section 1 headers: pages 2+ carry the running header and footer; the first page has neither.
  const runFmt = { b: true };
  const conventionPart = m.heading?.[0]?.find(p => typeof p !== "string");
  const footerLabel = conventionPart && !conventionPart.value ? w.fill(conventionPart.fill, { b: true, caps: true }) : run(m.runningFooter, runFmt);
  const s1 = [
    ["header", "default", headerPart("header", para(run(m.runningHeader, runFmt), { jc: "center", after: 0, border: "bottom" }))],
    ["footer", "default", headerPart("footer", para(footerLabel + tab(runFmt) + run("PAGE ", runFmt) +
      `<w:fldSimple w:instr=" PAGE "><w:r>${rPr(runFmt)}<w:t>1</w:t></w:r></w:fldSimple>`, { border: "top", tabs: [["right", 9360]], after: 0 }))],
    ["header", "first", headerPart("header", "")],
    ["footer", "first", headerPart("footer", "")],
  ];
  // Section 2 headers: the form's first page carries the seal and the form title, as in the template.
  const sealHeaderRel = sealBytes ? `${XML}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
    `<Relationship Id="rId1" Type="${REL}/image" Target="media/seal.jpg"/></Relationships>` : null;
  const H13 = { b: true, sz: 26 }, hc = { jc: "center", after: 0 };
  const s2 = [
    ["header", "first", headerPart("header",
      para((sealBytes ? w.picture("rId1", Math.round(1.1 * INCH), { x: -603885, y: -328295 }) : "") + run(ATNI, H13), hc) +
      para(run("RESOLUTION SUBMISSION FORM", H13), hc) + blank(), sealHeaderRel)],
    ["footer", "first", headerPart("footer",
      para(run("* If different than the author. Sponsor must be an ATNI Member in good standing.", { sz: 22 }), { ind: -630, after: 0 }) +
      (m.form.formCode ? para(run(m.form.formCode, { i: true, sz: 18 }), { ind: -630, jc: "right", after: 0 }) : ""))],
    ["header", "default", headerPart("header", "")],
    ["footer", "default", headerPart("footer", "")],
  ];
  const hasNotes = m.sources.length > 0 || m.notes.length > 0;
  const s3 = hasNotes ? [
    ["header", "default", headerPart("header", para(run("DRAFTING NOTES, NOT PART OF THE RESOLUTION", { b: true, sz: 20 }), hc))],
    ["footer", "default", headerPart("footer", "")],
  ] : null;

  let body = resolution(m, w, sealRel) + para("", { sect: sectPr(s1, true) }) + form(m, w);
  body += hasNotes ? para("", { sect: sectPr(s2, true) }) + notes(m, w) + sectPr(s3, false) : sectPr(s2, true);
  // The section-2 seal is referenced from its header's own relationships, so the header ids above stay valid.

  const title = lineText(m.form.title).replace(/^\[.*\]$/, "");
  const author = m.form.author.every(p => typeof p === "string" || p.value) ? lineText(m.form.author) : "";
  const when = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(created ?? "") ? `${created.slice(0, 19)}Z` : "";
  part("word/document.xml", `${XML}<w:document ${NS}><w:body>${body}</w:body></w:document>`, `${DOCX_TYPE}.document.main+xml`);
  part("word/styles.xml", styles(), `${DOCX_TYPE}.styles+xml`);
  part("word/settings.xml", SETTINGS, `${DOCX_TYPE}.settings+xml`);
  part("word/_rels/document.xml.rels", `${XML}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${w.rels.join("")}</Relationships>`);
  part("docProps/core.xml", `${XML}<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" ` +
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' +
    `<dc:title>${xml(title)}</dc:title><dc:creator>${xml(author || "ResIST")}</dc:creator>` +
    (when ? `<dcterms:created xsi:type="dcterms:W3CDTF">${when}</dcterms:created>` : "") + "</cp:coreProperties>",
  "application/vnd.openxmlformats-package.core-properties+xml");
  part("docProps/app.xml", `${XML}<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>ResIST</Application></Properties>`,
    "application/vnd.openxmlformats-officedocument.extended-properties+xml");
  part("_rels/.rels", `${XML}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
    `<Relationship Id="rId1" Type="${REL}/officeDocument" Target="word/document.xml"/>` +
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>' +
    `<Relationship Id="rId3" Type="${REL}/extended-properties" Target="docProps/app.xml"/></Relationships>`);
  const contentTypes = `${XML}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">` +
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
    '<Default Extension="xml" ContentType="application/xml"/><Default Extension="jpg" ContentType="image/jpeg"/>' +
    types.map(([name, type]) => `<Override PartName="/${name}" ContentType="${type}"/>`).join("") + "</Types>";
  const enc = new TextEncoder();
  const files = [["[Content_Types].xml", enc.encode(contentTypes)], ...parts.map(([name, text]) => [name, enc.encode(text)])];
  if (sealBytes) files.push(["word/media/seal.jpg", sealBytes]);
  return zip(files);
}

export const docxName = d =>
  `ATNI-Resolution-${String(d?.header?.year ?? "") || "Year"}-${String(d?.header?.number ?? "") || "DRFT-XX"}.docx`
    .replace(/[^\w.-]+/g, "-").replace(/-{2,}/g, "-");

// ---- ZIP (STORE) ------------------------------------------------------------------------------------------------
const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
export function crc32(bytes) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}
// files: [name, Uint8Array][]; names are UTF-8 (flag bit 11); every entry dated 1980-01-01 00:00 so output is stable.
export function zip(files) {
  const enc = new TextEncoder(), DOS_DATE = 0x21, local = [], central = [];
  let offset = 0;
  for (const [name, data] of files) {
    const nm = enc.encode(name), crc = crc32(data);
    const head = (sig, size) => { const b = new DataView(new ArrayBuffer(size)); b.setUint32(0, sig, true); return b; };
    const l = head(0x04034b50, 30);
    l.setUint16(4, 20, true); l.setUint16(6, 0x0800, true); l.setUint16(8, 0, true); l.setUint16(10, 0, true);
    l.setUint16(12, DOS_DATE, true); l.setUint32(14, crc, true); l.setUint32(18, data.length, true);
    l.setUint32(22, data.length, true); l.setUint16(26, nm.length, true); l.setUint16(28, 0, true);
    const c = head(0x02014b50, 46);
    c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint16(8, 0x0800, true); c.setUint16(10, 0, true);
    c.setUint16(12, 0, true); c.setUint16(14, DOS_DATE, true); c.setUint32(16, crc, true);
    c.setUint32(20, data.length, true); c.setUint32(24, data.length, true); c.setUint16(28, nm.length, true);
    c.setUint32(42, offset, true);
    local.push(new Uint8Array(l.buffer), nm, data);
    central.push(new Uint8Array(c.buffer), nm);
    offset += 30 + nm.length + data.length;
  }
  const size = central.reduce((s, b) => s + b.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
  end.setUint32(12, size, true); end.setUint32(16, offset, true);
  const chunks = [...local, ...central, new Uint8Array(end.buffer)];
  const out = new Uint8Array(chunks.reduce((s, b) => s + b.length, 0));
  let at = 0; for (const b of chunks) { out.set(b, at); at += b.length; }
  return out;
}
