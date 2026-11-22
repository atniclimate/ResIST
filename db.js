// The resolution database, loaded once into the browser (D-053). No query ever leaves the device.
// Version pinned; FTS5 is required and the stock sql.js build lacks it. Vendored (@sqlite.org/sqlite-wasm
// 3.53.0-build1, SHA-256 in NOTICE), so loading the page makes no outbound request (D-074, closes D-070 item 7).
import sqlite3InitModule from "./vendor/sqlite-wasm/index.mjs";
import { useDatabase, issuesFrom } from "./query.js";

let db;
export let issues = []; // pages/issues.json (the pinned Policy Sentinel issue names, D-078) after issuesFrom(); [] when absent or refused
export let issuesOk = false; // issues.length > 0
export let issuesRefused = false; // the file was served and failed its checks; a file that holds null, as the public build writes, is only absent
export let build = null; // build.json: resolutions, year_min, year_max, needs_review, commit, built, db_sha256
export let caps = null; // capabilities.json: face, sentinel, index manifest (report 09 section 5, D-070)

// Before the first export the local face answers 503 with a one-line remediation; keep it (app.js escapes it).
async function json(name) {
  const r = await fetch(name);
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status} ${(await r.text().catch(() => "")).slice(0, 200)}`.trim());
  return r.json();
}

export async function verifyDatabase(bytes, manifest) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  const hex = Array.from(digest, b => b.toString(16).padStart(2, "0")).join("");
  if (hex !== manifest.db_sha256) throw new Error("Database does not match build.json. Reload to fetch the current export.");
}

export async function load(onProgress = () => {}) {
  // The issue names are optional: a missing, unreadable or refused file only means no names are added to a search.
  const [sqlite3, res, info, capabilities, pinned] = await Promise.all([
    sqlite3InitModule(), fetch("resolutions.db"), json("build.json"), json("capabilities.json"),
    fetch("issues.json").then(r => (r.ok ? r.json() : null)).catch(() => undefined)]); // null: absent, undefined: unreadable
  if (!res.ok) throw new Error(`resolutions.db: HTTP ${res.status}`);
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
  await verifyDatabase(bytes, info);
  const p = sqlite3.wasm.allocFromTypedArray(bytes);
  db = new sqlite3.oo1.DB();
  const rc = sqlite3.capi.sqlite3_deserialize(db.pointer, "main", p, bytes.length, bytes.length,
    sqlite3.capi.SQLITE_DESERIALIZE_FREEONCLOSE | sqlite3.capi.SQLITE_DESERIALIZE_READONLY);
  if (rc) throw new Error(`sqlite3_deserialize failed (${rc})`);
  useDatabase(rows, capabilities, info);
  build = info;
  caps = capabilities;
  issues = issuesFrom(pinned);
  issuesOk = issues.length > 0;
  issuesRefused = pinned !== null && !issuesOk;
}

const rows = (sql, bind = []) => db.exec({ sql, bind, rowMode: "object", returnValue: "resultRows" });
