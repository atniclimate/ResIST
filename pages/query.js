// The wasm query adapter (report 09 section 5): every SQL statement the page runs. The http adapter is R5.
// No imports, so node --test loads it. The match string and every user value are bound parameters; only the fixed
// ORDER map and fixed fragments are interpolated. Columns are exactly scripts/build_pages.py ALLOW (D-070 item 4).
export const INDEX = Object.freeze({ adapter: "fts5", version: "1",
  tokenizer: "unicode61 remove_diacritics 0 categories 'L* N* Co Mn Mc' tokenchars '''\u2019'" });

export function requireIndex(index) {
  if (!index || typeof index !== "object") throw new Error("index manifest not supported: index");
  for (const k of ["adapter", "version", "tokenizer"]) {
    if (index[k] !== INDEX[k]) throw new Error(`index manifest not supported: ${k}`);
  }
}

// The one grammar (D-070 item 3), identical to resist.index.fts_match: NFC, split on Python's str.split()
// whitespace set (not JS \s), drop '"', quote each non-empty word, join with one space (implicit AND).
const PY_SPACE = /[\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/;
export function ftsMatch(q) {
  return String(q ?? "").normalize("NFC").split(PY_SPACE)
    .map(w => w.replace(/"/g, "")).filter(Boolean).map(w => `"${w}"`).join(" ");
}

let exec = null; // exec(sql, bind) -> array of row objects
// built is the export's build.json. On the local face capabilities.json comes from live code while the database is
// the last export, so the export's own record of its tokenizer must match too (a stale export is refused).
export function useDatabase(fn, capabilities, built) {
  exec = null; // a refused manifest leaves no open database behind
  requireIndex(capabilities?.index);
  if (built?.fts_tokenize !== INDEX.tokenizer) throw new Error("index manifest not supported: export tokenizer");
  exec = fn;
}
const run = (sql, bind = []) => {
  if (!exec) throw new Error("database not open");
  return exec(sql, bind);
};
const count = n => {
  if (!Number.isInteger(n) || n < 0) throw new Error("limit and offset must be non-negative integers");
  return n;
};

// Committee names are noisy (93 distinct); the ones used on 15 or more resolutions make a usable filter.
export function committees() {
  return run(`select name from sponsor where sponsor_type = 'committee' group by name
    having count(*) >= 15 order by name`).map(r => r.name);
}

// f = { match, convention, committee, year }; match is ftsMatch() output, convention a convention name.
function filtered(f, withYear) {
  const where = [], bind = [];
  if (f.match) { where.push("resolution_fts match ?"); bind.push(f.match); }
  if (f.convention) { where.push("r.convention_name = ?"); bind.push(String(f.convention)); }
  if (f.committee) {
    where.push("exists (select 1 from sponsor s where s.resolution_id = r.id and s.sponsor_type = 'committee' and s.name = ?)");
    bind.push(String(f.committee));
  }
  if (withYear && f.year !== "" && f.year != null) {
    const y = Number(f.year);
    if (!Number.isInteger(y)) throw new Error("year must be an integer");
    where.push("r.convention_year = ?"); bind.push(y);
  }
  const from = f.match ? "resolution_fts join resolution r on r.id = resolution_fts.rowid" : "resolution r";
  return { from, cond: where.length ? "where " + where.join(" and ") : "", bind };
}

// The year strip counts everything the other filters match, so it shows when ATNI resolved on these words.
export function yearCounts(f) {
  const { from, cond, bind } = filtered(f, false);
  return new Map(run(`select r.convention_year y, count(*) n from ${from} ${cond}
    group by y`, bind).map(r => [r.y, r.n]));
}

export function searchTotal(f) {
  const { from, cond, bind } = filtered(f, true);
  return run(`select count(*) n from ${from} ${cond}`, bind)[0].n;
}

const ORDER = { best: "bm25(resolution_fts)",
  new: "r.convention_year is null, r.convention_year desc, r.resolution_number desc",
  old: "r.convention_year is null, r.convention_year, r.resolution_number" };

export function search(f, { sort, limit, offset }) {
  if (!Object.hasOwn(ORDER, sort) || (sort === "best" && !f.match)) throw new Error(`unsupported sort: ${sort}`);
  const { from, cond, bind } = filtered(f, true);
  const snip = f.match ? "snippet(resolution_fts, 2, char(2), char(3), ' ... ', 24)" : "null";
  return run(`select r.id, r.resolution_number, r.title, r.convention_name, r.convention_year,
      r.convention_location, r.needs_review, ${snip} snip,
      (select group_concat(name, ', ') from sponsor s where s.resolution_id = r.id and s.sponsor_type = 'committee') committee
      from ${from} ${cond} order by ${ORDER[sort]} limit ? offset ?`, [...bind, count(limit), count(offset)]);
}

export function resolution(id) {
  return run(`select id, document_id, resolution_number, title, date_adopted, convention_name, convention_location,
    convention_year, needs_review, full_text from resolution where id = ?`, [id])[0] ?? null;
}

export function statements(id) {
  return run(`select statement_type t, "index" i, text from statement where resolution_id = ?
    order by "index"`, [id]);
}

export function citations(id) {
  return run(`select c.text, c.citation_type, c.linked_resolution_id l, t.resolution_number n, t.title tt
    from citation c left join resolution t on t.id = c.linked_resolution_id where c.resolution_id = ?`, [id]);
}

export function citedBy(id) {
  return run(`select distinct r.id, r.resolution_number, r.title, r.convention_year from citation c
    join resolution r on r.id = c.resolution_id where c.linked_resolution_id = ? and r.id != ?
    order by r.convention_year desc, r.resolution_number desc`, [id, id]);
}

export function committeesOf(id) {
  return run("select name from sponsor where resolution_id = ? and sponsor_type = 'committee'", [id]).map(s => s.name);
}

// The build inserts the atni-table URL first, so rowid order puts it first.
export function sourceUrls(documentId) {
  return run("select url from source where document_id = ? order by rowid", [documentId]).map(s => s.url);
}

// The database's statements for a claimed source: same type and text in the same ATNI document.
export function storedStatements(statementType, text, documentId) {
  return run(`select resolution_id, statement_type t, "index" i, text from statement where statement_type = ?
    and text = ? and resolution_id in (select id from resolution where document_id = ?) order by "index"`,
  [statementType, text, documentId]);
}

export function datedCount() {
  return run("select count(date_adopted) n from resolution")[0].n;
}
