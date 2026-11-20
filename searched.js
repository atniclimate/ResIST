// What a search ran, in plain words (D-078, RM-2): every typed word as searched, and for an issue every name or reference
// added from the pinned Policy Sentinel table, with where it came from and the link to the other way of searching.
// Pure: it takes the result of broaden() and returns an HTML string; every dynamic value passes through esc().
// A hit is a text match, so nothing here says what a resolution is about or asserts a conflict.
import { esc } from "./ui.js";
import { usDate } from "./compose.js";

const BASIS = { "name:official": "an official name", "name:people_use": "a name people use",
  "rests_on:usc": "a reference the issue rests on", "rests_on:cfr": "a reference the issue rests on" };
const quote = t => `“${esc(t)}”`;

// b: the broaden() result. hrefExact is given only when the broad search differs from the exact one; hrefBroad only
// when broadening would change the words searched. "" when nothing was searched.
export function searchedHTML(b, { exact = false, hrefExact = "", hrefBroad = "" } = {}) {
  if (!b?.words?.length) return "";
  const typed = b.words.map(w => w.text).join(" ");
  const link = (href, label) => href ? `<p class="searched-mode"><a id="search-mode" href="${esc(href)}">${label}</a></p>` : "";
  const list = items => `<ul class="squares">${items.map(i => `<li>${i}</li>`).join("")}</ul>`;
  if (b.issue) {
    const { label, reviewedOn, added } = b.issue;
    return `<div class="searched" id="searched">
      <p id="searched-lead">Searched: resolutions that contain ${quote(typed)}, or any of the names and references below.</p>
      ${list(added.map(a => `${esc(a.text)} (${BASIS[a.from] ?? "a name from the table"})`))}
      <p class="meta">These names and references come from Policy Sentinel's reviewed issue table, issue ${quote(label)}, reviewed ${esc(usDate(reviewedOn))}. They are not taken from the resolutions. Every result is a text match; none is a finding about a resolution.</p>
      ${link(hrefExact, "Search only the words I typed")}</div>`;
  }
  if (exact) {
    return `<div class="searched" id="searched">
      <p id="searched-lead">Searched exactly: resolutions that contain every one of these words, as typed.</p>
      ${list(b.words.map(w => quote(w.text)))}
      ${link(hrefBroad, "Search with longer words and issue names")}</div>`;
  }
  return `<div class="searched" id="searched">
    <p id="searched-lead">Searched: resolutions that contain all of these words.</p>
    ${list(b.words.map(w => `${quote(w.text)}, ${w.prefix ? "or a word that starts with it" : "exactly"}`))}
    ${link(hrefExact, "Search only the exact words")}</div>`;
}
