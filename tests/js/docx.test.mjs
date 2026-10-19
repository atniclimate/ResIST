// Word export (SPEC section 8): ZIP structure, CRCs, package parts and the OOXML that matters, checked in Node.
// tests/test_pages_docx.py opens the same documents with python-docx.
import test from "node:test";
import assert from "node:assert/strict";
import { crc32 as zlibCrc32 } from "node:zlib";
import { compose, newDraft } from "../../pages/compose.js";
import { buildDocx, docxName, crc32, zip } from "../../pages/docx.js";
import { emptyDraft, fullDraft, seal, CREATED } from "./docx-fixtures.mjs";

// Reads a STORE zip through its central directory and checks every local header against it.
function unzip(bytes) {
  const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), dec = new TextDecoder();
  const end = bytes.length - 22;
  assert.equal(v.getUint32(end, true), 0x06054b50, "end of central directory");
  const count = v.getUint16(end + 10, true), size = v.getUint32(end + 12, true);
  let at = v.getUint32(end + 16, true);
  assert.equal(at + size, end, "central directory ends where the end record starts");
  const files = new Map();
  for (let i = 0; i < count; i++) {
    assert.equal(v.getUint32(at, true), 0x02014b50);
    const flags = v.getUint16(at + 8, true), method = v.getUint16(at + 10, true), crc = v.getUint32(at + 16, true);
    const csize = v.getUint32(at + 20, true), usize = v.getUint32(at + 24, true), nlen = v.getUint16(at + 28, true);
    const off = v.getUint32(at + 42, true), name = dec.decode(bytes.subarray(at + 46, at + 46 + nlen));
    assert.equal(method, 0, `${name}: STORE`);
    assert.equal(flags & 0x0800, 0x0800, `${name}: UTF-8 name flag`);
    assert.equal(csize, usize);
    assert.equal(v.getUint32(off, true), 0x04034b50, `${name}: local header`);
    assert.equal(v.getUint32(off + 14, true), crc, `${name}: local CRC matches central`);
    const data = bytes.subarray(off + 30 + v.getUint16(off + 26, true), off + 30 + v.getUint16(off + 26, true) + usize);
    assert.equal(zlibCrc32(data), crc, `${name}: CRC-32 of the data`);
    files.set(name, data);
    at += 46 + nlen + v.getUint16(at + 30, true) + v.getUint16(at + 32, true);
  }
  return files;
}
const text = (files, name) => new TextDecoder().decode(files.get(name));
const build = (draft, opts = {}) => buildDocx(compose(draft), { created: CREATED, ...opts });

test("crc32 agrees with zlib, and the zip round-trips", () => {
  const data = new TextEncoder().encode("Affiliated Tribes of Northwest Indians, ĺ 𝓐");
  assert.equal(crc32(data), zlibCrc32(data));
  assert.equal(crc32(new Uint8Array()), 0);
  const files = unzip(zip([["a.txt", data], ["dir/ü.xml", new Uint8Array([1, 2, 3])]]));
  assert.deepEqual([...files.keys()], ["a.txt", "dir/ü.xml"]);
  assert.deepEqual([...files.get("dir/ü.xml")], [1, 2, 3]);
});

test("an empty draft makes a two-section document with placeholders for every unknown detail", () => {
  const files = unzip(build(emptyDraft()));
  assert.equal([...files.keys()][0], "[Content_Types].xml");
  for (const name of ["_rels/.rels", "docProps/core.xml", "docProps/app.xml", "word/document.xml", "word/styles.xml",
    "word/settings.xml", "word/_rels/document.xml.rels"]) assert.ok(files.has(name), name);
  assert.ok(!files.has("word/media/seal.jpg"), "no seal unless given");
  const doc = text(files, "word/document.xml");
  assert.equal(doc.match(/<w:sectPr>/g).length, 2);
  assert.match(doc, /mc:Ignorable="w14"/);
  for (const tag of ["Convention", "City, State", "Venue", "Convention dates", "Draft 1 due date", "Resolution title",
    "President's name", "Secretary's name", "Author", "Sponsor"])
    assert.ok(doc.includes(`<w:tag w:val="${tag}"/>`), `placeholder ${tag}`);
  assert.ok(doc.includes("[Convention dates]"));
  assert.ok(!doc.includes("this form must be completed in its entirety"), "NCAI form only when forwarding");
  assert.ok(!doc.includes("DRAFTING NOTES"));
  // Headers and footers referenced by the document exist and are typed.
  const types = text(files, "[Content_Types].xml"), rels = text(files, "word/_rels/document.xml.rels");
  for (const [, target] of rels.matchAll(/Target="((?:header|footer)\d+\.xml)"/g)) {
    assert.ok(files.has(`word/${target}`), target);
    assert.ok(types.includes(`PartName="/word/${target}"`), `${target} content type`);
  }
  const footer = text(files, "word/footer1.xml");
  assert.match(footer, /<w:tag w:val="Convention"\/>/, "running footer keeps the convention fillable");
  assert.match(footer, /w:instr=" PAGE "/);
  assert.match(text(files, "docProps/core.xml"), /<dc:creator>ResIST<\/dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">2026-10-19T20:00:00Z</);
});

test("the full draft carries known details, verbatim clauses, checkboxes, the NCAI form and Drafting Notes", () => {
  const draft = fullDraft(), model = compose(draft);
  const bytes = buildDocx(model, { seal, created: CREATED });
  assert.deepEqual(bytes, buildDocx(compose(draft), { seal, created: CREATED }), "deterministic");
  const files = unzip(bytes);
  assert.deepEqual([...files.get("word/media/seal.jpg")], [...seal]);
  const doc = text(files, "word/document.xml"), rels = text(files, "word/_rels/document.xml.rels");
  assert.equal(doc.match(/<w:sectPr>/g).length, 3);
  for (const known of ["Convention", "City, State", "Venue", "Convention dates", "Draft 1 due date", "Resolution title"])
    assert.ok(!doc.includes(`<w:tag w:val="${known}"/>`), `no placeholder for known ${known}`);
  assert.ok(doc.includes("2026 Annual Convention"));
  assert.ok(doc.includes(" that ATNI urges both Tribal and Public Schools to exercise caution"));
  assert.ok(!doc.includes("PAGE 2 motor skills"), "the removed page header stays removed");
  // Lead words in their own bold run, then the text in a regular run.
  assert.match(doc, /<w:r><w:rPr><w:b\/><w:bCs\/><\/w:rPr><w:t xml:space="preserve">THEREFORE, BE IT RESOLVED,<\/w:t><\/w:r><w:r><w:t xml:space="preserve"> that ATNI urges/);
  const box = tag => doc.match(new RegExp(`<w:tag w:val="${tag}"/><w:id w:val="\\d+"/><w14:checkbox><w14:checked w14:val="(\\d)"/>`))?.[1];
  assert.equal(box("Forward to NCAI: Yes"), "1");
  assert.equal(box("Forward to NCAI: No"), "0");
  assert.equal(box("Committee: Education"), "1");
  assert.equal(box("Committee: Youth"), "1");
  assert.equal(box("Committee: Other"), "1");
  assert.equal(box("Committee: Health"), "0");
  assert.ok(doc.includes("this form must be completed in its entirety"), "NCAI form");
  assert.ok(doc.includes('<w:tag w:val="Why is this resolution emergency in nature?"/>'), "empty emergency text is fillable");
  assert.match(rels, /Target="https:\/\/atnitribes\.org\/wp-content\/uploads\/2026\/09\/20260917_26-51_[^"]+" TargetMode="External"/);
  assert.match(rels, /Target="https:\/\/www\.federalregister\.gov\/d\/2025-23880" TargetMode="External"/);
  assert.ok(doc.includes("SHA-256 5b62a9708e4081fd"));
  assert.ok(doc.includes("Read by Policy Sentinel on 10/19/2026; text SHA-256 b3ee0b8f7d68c588"));
  assert.ok(doc.includes("Drafter's note: Check the consultation section"));
  assert.ok(text(files, "word/_rels/header3.xml.rels").includes("media/seal.jpg"));
  for (const [name, data] of files) if (/\.(xml|rels)$/.test(name)) {
    const s = new TextDecoder().decode(data);
    assert.ok(!s.includes("\u2014"), `${name}: no em dash`);
    assert.ok(!s.includes("@"), `${name}: no email address`);
  }
});

test("text is escaped and XML-invalid characters are dropped", () => {
  const d = newDraft(2026);
  d.title = "A & B <c> \u0001\u0008 lone \uD800 surrogate \uFFFE end 𝓐";
  const doc = text(unzip(build(d)), "word/document.xml");
  assert.ok(doc.includes("A &amp; B &lt;c&gt;  lone  surrogate  end 𝓐"));
  assert.ok(!/[\u0001\u0008\uFFFE]/.test(doc));
  assert.ok(!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/.test(doc), "no lone high surrogate");
});

test("an unsafe link is shown as text, never linked", () => {
  const d = fullDraft();
  d.notes[0].officialUrl = "javascript:alert(1)";
  const files = unzip(build(d));
  assert.ok(!text(files, "word/_rels/document.xml.rels").includes("javascript:"));
  assert.ok(text(files, "word/document.xml").includes("javascript:alert(1)"));
});

test("docxName uses safe characters only", () => {
  assert.equal(docxName(newDraft(2026)), "ATNI-Resolution-2026-DRFT-XX.docx");
  const d = newDraft(2026); d.header.number = "DRFT 07/<x>";
  assert.equal(docxName(d), "ATNI-Resolution-2026-DRFT-07-x-.docx");
});
