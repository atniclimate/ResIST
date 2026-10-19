// Small helpers every view shares. Everything shown that came from the database, a draft file or Policy Sentinel
// passes through esc() before it reaches innerHTML.
export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Browser storage can be absent or throw (private windows, blocked site data), so every access is guarded.
export const local = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); return true; } catch { return false; } },
  remove(key) { try { localStorage.removeItem(key); } catch { /* nothing kept */ } },
};

let timer;
// One message at a time in the page's role="status" region (#toast), with an optional link such as "Open draft".
export function toast(text, link) {
  const el = document.getElementById("toast");
  if (!el) return;
  clearTimeout(timer);
  el.innerHTML = `<span>${esc(text)}</span>${link ? `<a href="${esc(link.href)}">${esc(link.label)}</a>` : ""}`;
  timer = setTimeout(() => { el.textContent = ""; }, 7000);
}

// Saves bytes as a file the person keeps; nothing is uploaded.
export function download(bytes, name, type) {
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
