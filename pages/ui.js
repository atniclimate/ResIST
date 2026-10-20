// Small helpers every view shares. Everything shown that came from the database, a draft file or Policy Sentinel
// passes through esc() before it reaches innerHTML.
export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Browser storage can be absent or throw (private windows, blocked site data), so every access is guarded.
export const local = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); return true; } catch { return false; } },
  remove(key) { try { localStorage.removeItem(key); } catch { /* nothing kept */ } },
};

const byId = id => globalThis.document?.getElementById(id) ?? null;

let sayTimer;
// The page's one polite live region (#announce). Clearing first and writing 50 ms later makes a repeated message
// heard again.
export function say(text) {
  const el = byId("announce");
  if (!el) return;
  clearTimeout(sayTimer);
  el.textContent = "";
  sayTimer = setTimeout(() => { el.textContent = String(text); }, 50);
}

// The dock shows when it has a message, the draft link or the insert point to show.
export function refreshDock() {
  const dock = byId("dock");
  if (!dock) return;
  dock.hidden = !byId("toast")?.textContent && (byId("dock-draft")?.hidden ?? true) && (byId("dock-ins")?.hidden ?? true);
}

let toastTimer;
// A short message: announced through say(), shown as plain text in the dock (#toast is aria-hidden) for 5 s.
export function toast(text) {
  say(text);
  const el = byId("toast");
  if (!el) return;
  clearTimeout(toastTimer);
  el.textContent = String(text);
  refreshDock();
  toastTimer = setTimeout(() => { el.textContent = ""; refreshDock(); }, 5000);
}

// Saves bytes as a file the person keeps; nothing is uploaded.
export function download(bytes, name, type) {
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
