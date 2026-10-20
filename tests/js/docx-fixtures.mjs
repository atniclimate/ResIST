// Drafts for the Word export tests (D-054), built with compose.js. Clause text is ATNI's published text, verbatim from
// Resolution 26-51 (2026 Annual Convention) as stored in the resolution database; tests/test_pages_docx.py checks it
// against the database when one is built. The policy note is copied from a recorded Policy Sentinel response
// (federal-register, FR Doc. 2025-23880, read 2026-10-19). Run directly to write the documents:
//   node tests/js/docx-fixtures.mjs <out-dir>
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { newDraft, newClause, STANDARD, removePageHeader, body, insertCite } from "../../pages/compose.js";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
export const seal = new Uint8Array(readFileSync(join(ROOT, "pages", "atni-seal-color.jpg")));
const conventions = JSON.parse(readFileSync(join(ROOT, "pages", "conventions.json"), "utf8")).conventions;

const R2651 = {
  resolutionId: 409, number: "26-51", year: 2026, convention: "Annual Convention",
  title: "Supporting Responsible Governance of Youth Use of Artificial Intelligence Chatbots in Schools and Education",
  documentId: "5b62a9708e4081fd5baa676ba2ea0aae0c3dad1daf03f05dc4cab722fc193a91",
  url: "https://atnitribes.org/wp-content/uploads/2026/09/20260917_26-51_YOUTH%20USE%20OF%20ARTIFICIAL%20INTELLIGENCE%20CHATBOTS%20IN%20SCHOOLS.pdf",
};
// [statementType, index, text] exactly as stored.
export const STATEMENTS = [
  ["whereas", 3, "the ATNI Youth Committee expresses concern that overreliance on artificial intelligence (AI) in education may negatively affect critical thinking, creativity, writing, motor skills, learning strategies, traditional teaching practices, cultural transmission, language revitalization, and relationships with Indigenous knowledge keepers, educators, parents, and Elders; and"],
  ["resolved", 0, "that ATNI urges both Tribal and Public Schools to exercise caution and establish strong ethical safeguards governing the use of artificial intelligence (AI) in Tribal educational systems; and"],
  ["resolved", 3, "that ATNI urges State and Federal Governments to consult with Tribes in creating stronger safeguards to protect American Indian/ Alaska Native youth from potential harms associated with the use of AI in schools; and"],
];
const carried = ([statementType, index, text]) => newClause(text, "carried", { ...R2651, statementType, index, text });

// A carried citation (UI-2, D-077): a real citation-shaped span of a stored clause in the site export, chosen in code
// (the first WHEREAS by statement id with a page number holding an "Executive Order <number>" shape). `start`/`end`
// are UTF-16 offsets into `statement`, the stored clause text; tests/test_pages_docx.py checks both against the
// database when one is built.
export const CITE = {
  "resolutionId": 57,
  "number": "21-30",
  "title": "In Support Of Expanding Access To Impact Aid For Tribally Controlled Schools",
  "year": 2021,
  "convention": null,
  "documentId": "0b8af64acd4900785969710938775ec3b272a54e41eeff2493e3adf8d5dd0fcd",
  "statementType": "whereas",
  "index": 10,
  "position": 11,
  "page": 2,
  "start": 158,
  "end": 179,
  "text": "Executive Order 13175",
  "url": "https://atnitribes.org/wp-content/uploads/2021/10/Res-2021-30.pdf",
  "statement": "President Biden signed the Presidential Memorandum on Tribal Consultation and Strengthening Nation-to-Nation Relationships on January 26, 2021, which affirms Executive Order 13175 of November 6, 2000 (Consultation with Indian Tribal Governments) and charges all executive departments and agencies with engaging in regular, meaningful, and robust consultation with officials of Native nations in the development of federal policies that have Native implications"
};
// The draft's provenance for it, keys in the order app.js builds them (design D11).
export const CITE_SOURCE = (({ resolutionId, number, title, year, documentId, statementType, index, position, page,
  start, end, text, url }) => ({ resolutionId, number, title, year, documentId, statementType, index, position, page,
  start, end, text, url }))(CITE);

export const NOTE = {
  id: "federal-register:2025-23880", sourceId: "federal-register", identifier: "90 FR 60570 (FR Doc. 2025-23880)",
  title: "Office of the Attorney General; Consolidation of the Office of the Executive Secretariat Into the Justice Management Division",
  issuingBody: "Justice Department", kind: "Rule", date: "2025-12-29",
  officialUrl: "https://www.federalregister.gov/d/2025-23880",
  textUrl: "https://www.govinfo.gov/content/pkg/FR-2025-12-29/html/2025-23880.htm",
  retrievedAt: "2026-10-19T19:12:31.359Z",
  receiptSha256: "b3ee0b8f7d68c5883adaab8020965fe2cde4f4223cb1749ce5e8a61352979683", rulesVersion: "demo-rules-1.0.2",
  issues: [
    {
      id: "consultation_language-1", type: "consultation_language", label: "Consultation wording",
      quote: "Executive Order 13175 (Consultation and Coordination With Indian Tribal Governments)",
      locator: "/html[1]/body[1]/pre[1]/paragraph[37]",
      rule: "The sentence contains consult, consultation, government-to-government, Tribal implications, or Executive Order 13175.",
      limits: "Wording only. It does not show that consultation happened, that it was adequate, or that any right attaches to it.",
    },
    {
      id: "date_or_deadline-1", type: "date_or_deadline", label: "Date or deadline", quote: "Effective December 29, 2025.",
      locator: "/html[1]/body[1]/pre[1]/paragraph[12]",
      rule: "The sentence contains a calendar date together with words such as effective, comments, due, compliance, must be received, or no later than.",
      limits: "Dates are read from the text as written. Extensions, corrections and later notices can change them.",
    },
  ],
  comment: "Check the consultation section before the committee meets.",
};

export function emptyDraft() { return newDraft(2026); }

// Known 2026 Annual Convention details, three carried clauses (one with its page header removed), a typed WHEREAS
// holding one carried citation, the NCAI transmittal clause, NCAI forwarding, two committees and Other, and one
// policy note.
export function fullDraft() {
  const d = newDraft(2026);
  const { id, label, ...details } = conventions.find(c => c.id === "2026-annual");
  Object.assign(d.header, details);
  d.title = R2651.title;
  const [w3, r0, r3] = STATEMENTS.map(carried);
  w3.text = body(removePageHeader(w3.text));
  d.whereas.push(w3);
  // A typed WHEREAS holding one carried citation, made as store.carryCite makes a new one.
  const typed = { id: "cite-clause", text: "", origin: "typed" };
  insertCite(typed, 0, { id: "cite-1", text: CITE.text, source: { ...CITE_SOURCE } });
  d.whereas.push(typed);
  d.resolved.splice(0, 0, r0, r3, newClause(STANDARD.ncai, "standard"));
  Object.assign(d.meta, { sponsorInGoodStanding: true, committees: ["Education", "Youth"], otherCommittee: "Climate" });
  d.meta.ncai.forward = true;
  d.notes.push(structuredClone(NOTE));
  return d;
}

export const CREATED = "2026-10-19T20:00:00.000Z";

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const { compose } = await import("../../pages/compose.js");
  const { buildDocx } = await import("../../pages/docx.js");
  const out = process.argv[2];
  mkdirSync(out, { recursive: true });
  writeFileSync(join(out, "empty.docx"), buildDocx(compose(emptyDraft()), { created: CREATED }));
  writeFileSync(join(out, "full.docx"), buildDocx(compose(fullDraft()), { seal, created: CREATED }));
  const { documentId, statementType, index, start, end, text, statement } = CITE;
  writeFileSync(join(out, "statements.json"), JSON.stringify({ documentId: R2651.documentId, statements: STATEMENTS,
    cite: { documentId, statementType, index, start, end, text, statement } }));
}
