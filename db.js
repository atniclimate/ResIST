// The resolution database, loaded once into the browser (D-053). No query ever leaves the device.
// Version pinned; FTS5 is required and the stock sql.js build lacks it.
import sqlite3InitModule from "https://cdn.jsdelivr.net/npm/@sqlite.org/sqlite-wasm@3.53.0-build1/dist/index.mjs";

let db;
export let build = null; // build.json: resolutions, year_min, year_max, needs_review, commit, built, db_sha256

export async function load(onProgress = () => {}) {
  const [sqlite3, res, info] = await Promise.all([
    sqlite3InitModule(), fetch("resolutions.db"), fetch("build.json").then(r => r.json())]);
  if (!res.ok) throw new Error(`resolutions.db: HTTP ${res.status}`);
  build = info;
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
}

export const rows = (sql, bind = []) => db.exec({ sql, bind, rowMode: "object", returnValue: "resultRows" });

// User text becomes quoted FTS5 terms (implicit AND), so no query syntax can error or inject.
export function ftsQuery(q) {
  const terms = String(q ?? "").match(/[\p{L}\p{N}][\p{L}\p{N}'’\-]*/gu) || [];
  return terms.map(t => `"${t.replace(/"/g, "")}"`).join(" ");
}
