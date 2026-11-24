/* The visual language of the basis (D-083 item 5, design D18): a value is recorded or decided by ATNI (plain), likely
   (applied, counted, marked in the second colour with a 45-degree hatch and the word "likely", the text as written one
   step away) or open (kept as written, a dashed outline and the word "open"). Never colour alone: every mark carries
   its word. Every string that reaches markup passes through esc(). */
import { esc, fmt } from "./charts.js";

/** @typedef {"recorded"|"owner"|"likely"|"open"} Basis */

let uid = 0;
export const nextId = prefix => `${prefix}-${++uid}`;

export const WORD_LIKELY = `<span class="lk-w">likely</span>`;
export const WORD_OPEN = `<span class="op-w">open</span>`;

/** @param {string|null|undefined} b "likely" | "open" | "l" | "o" | anything else @returns {"likely"|"open"|""} */
export function basisOf(b) { return b === "likely" || b === "l" ? "likely" : b === "open" || b === "o" ? "open" : ""; }

/** The word that follows a marked value. */
export const word = b => (basisOf(b) === "likely" ? WORD_LIKELY : basisOf(b) === "open" ? WORD_OPEN : "");

/** Text with a basis. likely: the likely reading in a mark, the word, and a button that reveals the text as written in
 *  place. open: the text as written, with the word "open". Anything else: the plain text.
 *  @param {{text:string, basis?:string|null, asWritten?:string|null, none?:string}} o
 *  `asWritten` is the value as the record writes it (null or "" when the record writes nothing; `none` says so). */
export function uncertain(o) {
  const b = basisOf(o.basis);
  if (b === "likely") {
    const id = nextId("aw");
    const written = o.asWritten ? `As written: “${esc(o.asWritten)}”` : `As written: ${esc(o.none ?? "nothing in the record")}`;
    return `<span class="unc"><mark class="likely">${esc(o.text)}</mark> ${WORD_LIKELY} <button type="button" class="aw" aria-expanded="false" aria-controls="${id}">as written</button><span class="aw-text" id="${id}" hidden>${written}</span></span>`;
  }
  if (b === "open") {
    const shown = o.asWritten ? `“${esc(o.asWritten)}”` : esc(o.none ?? "nothing in the record");
    return `<span class="unc unc-open"><span class="open-text">${shown}</span> ${WORD_OPEN}</span>`;
  }
  return esc(o.text);
}

/** A likely or open mark with no as-written button (for a place where the text is already beside it). */
export function mark(text, basis) {
  const b = basisOf(basis);
  return b === "likely" ? `<mark class="likely">${esc(text)}</mark> ${WORD_LIKELY}` : b === "open" ? `<span class="open-text">${esc(text)}</span> ${WORD_OPEN}` : esc(text);
}

/** Opens or closes the as-written text a button controls. */
export function toggleAw(btn) {
  const el = document.getElementById(btn.getAttribute("aria-controls"));
  if (!el) return;
  const open = btn.getAttribute("aria-expanded") !== "true";
  btn.setAttribute("aria-expanded", String(open));
  el.hidden = !open;
}

/** "120 recorded, 14 likely": both numbers, never one total. Plain text (no buttons). */
export function splitText(solid, likely, solidWord = "recorded") {
  if (likely && solid) return `${fmt(solid)} ${solidWord}, ${fmt(likely)} likely`;
  if (likely) return `${fmt(likely)} likely`;
  return `${fmt(solid)} ${solidWord}`;
}

/** The key to the marks. `show` names the parts a chart has: "likely", "open", "nr" (not recorded). The solid entry is
 *  always there. */
export function basisKey(show = ["likely", "open", "nr"], solid = false) {
  const items = solid ? [`<li><span class="sw s-solid" aria-hidden="true"></span>As recorded or decided by ATNI</li>`] : [];
  if (show.includes("likely")) items.push(`<li><span class="sw s-likely" aria-hidden="true"></span>Likely: the most likely answer, applied and counted</li>`);
  if (show.includes("open")) items.push(`<li><span class="sw s-open" aria-hidden="true"></span>Open: kept as written</li>`);
  if (show.includes("nr")) items.push(`<li><span class="sw s-none" aria-hidden="true"></span>Not recorded</li>`);
  return `<ul class="key basis-key" aria-label="Key to the marks">${items.join("")}</ul>`;
}
