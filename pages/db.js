// The resolution database, loaded once into the browser (D-053). No query ever leaves the device.
// Version pinned; FTS5 is required and the stock sql.js build lacks it. Vendored (@sqlite.org/sqlite-wasm
// 3.53.0-build1, SHA-256 in NOTICE), so loading the page makes no outbound request (D-074, closes D-070 item 7).
import sqlite3InitModule from "./vendor/sqlite-wasm/index.mjs";
import { useDatabase } from "./query.js";

let db;
export let build = null; // build.json: resolutions, year_min, year_max, needs_review, commit, built, db_sha256
export let caps = null; // capabilities.json: face, sentinel, index manifest (report 09 section 5, D-070)

// Before the first export the local face answers 503 with a one-line remediation; keep it (app.js escapes it).
async function json(name) {
  const r = await fetch(name);
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status} ${(await r.text().catch(() => "")).slice(0, 200)}`.trim());
  return r.json();
}

export async function load(onProgress = () => {}) {
  const [sqlite3, res, info, capabilities] = await Promise.all([
    sqlite3InitModule(), fetch("resolutions.db"), json("build.json"), json("capabilities.json")]);
  if (!res.ok) throw new Error(`resolutions.db: HTTP ${res.status}`);
  build = info;
  caps = capabilities;
  const total = Number(res.headers.get("content-length")) || 0, reader = res.body.getReader(), chunks = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value); got += value.length;
    if (total) onProgress(got / total);
  }
  const bytes = new Uint8Array(got);
  let off = 0; for (const c of chunks) { bytes.set(c, off); off += c.length; }
  const p = sqlite3.wasm.allocFromTypedArray(bytes);
  db = new sqlite3.oo1.DB();
  const rc = sqlite3.capi.sqlite3_deserialize(db.pointer, "main", p, bytes.length, bytes.length,
    sqlite3.capi.SQLITE_DESERIALIZE_FREEONCLOSE | sqlite3.capi.SQLITE_DESERIALIZE_READONLY);
  if (rc) throw new Error(`sqlite3_deserialize failed (${rc})`);
  useDatabase(rows, caps, build); // throws on a manifest or export tokenizer query.js does not speak; load() rejects
}

const rows = (sql, bind = []) => db.exec({ sql, bind, rowMode: "object", returnValue: "resultRows" });
