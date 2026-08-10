/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · shared global components
 * Sprint 7 Package 1
 *
 * Every component is a pure function from data to an HTML string. Nothing here
 * touches the DOM, reads global state, or performs I/O, so the rules the POR
 * fixes — four cells and only four, one disclaimer per tab, the close control
 * upper-right — are enforced in code and testable directly.
 * ========================================================================== */

import {
  MIDDOT,
  assertIntegerCents,
  creditsTone,
  exactCentsAttr,
  formatCredits,
} from './credits.js';

/** The approved Credits disclaimer. Exact string — do not reword. */
export const CREDITS_DISCLAIMER = 'VIRTUAL CREDITS · $ IS DISPLAY ONLY · NO CASH VALUE';

/** Placeholder drawn where a real figure is not yet bound. */
export const PENDING_FIGURE = '—';

/**
 * Escape text for interpolation into markup.
 *
 * @param {unknown} value
 * @returns {string}
 */
export function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* ── Section heading ────────────────────────────────────────────────────── */

/**
 * Shared section heading with an optional right-side helper label.
 *
 * @param {string} text
 * @param {string} [helper]
 * @returns {string}
 */
export function sectionHeading(text, helper = '') {
  const helperHtml = helper
    ? `<span class="fs-heading__helper">${escapeHtml(helper)}</span>`
    : '';
  return (
    '<div class="fs-heading">' +
    `<span class="fs-heading__text">${escapeHtml(text)}</span>` +
    helperHtml +
    '</div>'
  );
}

/**
 * Lightweight eyebrow — the rail/grid label form.
 *
 * @param {string} text
 * @returns {string}
 */
export function eyebrow(text) {
  return `<div class="fs-eyebrow">${escapeHtml(text)}</div>`;
}

/* ── Four-cell summary strip ────────────────────────────────────────────── */

/**
 * @typedef {object} StripCell
 * @property {string} label        small grey label above the value
 * @property {number} [cents]      exact integer cents — drawn as whole dollars
 * @property {string} [text]       non-money value, used when `cents` is absent
 * @property {string} [context]    secondary-grey context after a middot
 * @property {boolean} [signed]    prefix `+` on a positive money value
 * @property {boolean} [anchor]    anchor treatment — at most one cell per strip
 * @property {boolean} [gold]      gold treatment — at most one cell per strip
 * @property {boolean} [pending]   draw as unresolved rather than as a figure
 */

/**
 * The four-cell summary strip shared by League, Action, The Week and Ledger.
 *
 * Exactly four cells. A strip with any other count is a construction error, not
 * a layout that degrades quietly: the grid is a fixed four columns, so a fifth
 * cell would silently wrap onto a second row and a third would leave a hole.
 *
 * @param {{cells: StripCell[], id?: string, label?: string}} spec
 * @returns {string}
 */
export function summaryStrip(spec) {
  const { cells, id = '', label = '' } = spec || {};

  if (!Array.isArray(cells)) {
    throw new TypeError('summaryStrip requires a cells array');
  }
  if (cells.length !== 4) {
    throw new RangeError(
      `the summary strip takes exactly four cells, got ${cells.length}`,
    );
  }

  const emphasised = cells.filter((c) => c.anchor || c.gold).length;
  if (emphasised > 1) {
    throw new RangeError(
      `at most one cell per strip may carry the anchor or gold treatment, got ${emphasised}`,
    );
  }

  const idAttr = id ? ` id="${escapeHtml(id)}"` : '';
  const labelAttr = label ? ` aria-label="${escapeHtml(label)}"` : '';

  return (
    `<div class="fs-strip"${idAttr} role="group"${labelAttr}>` +
    cells.map(stripCell).join('') +
    '</div>'
  );
}

/**
 * @param {StripCell} cell
 * @returns {string}
 */
function stripCell(cell) {
  const classes = ['fs-strip__cell'];
  if (cell.anchor) classes.push('is-anchor');
  if (cell.gold) classes.push('is-gold');

  const valueClasses = ['fs-strip__value'];
  let valueHtml;
  let exactAttr = '';

  if (cell.pending) {
    valueClasses.push('is-pending');
    valueHtml = escapeHtml(cell.text || PENDING_FIGURE);
  } else if (typeof cell.cents === 'number') {
    assertIntegerCents(cell.cents, `strip cell "${cell.label}" cents`);
    // The drawn figure is whole dollars; the exact cents ride along in the DOM
    // so the display value is never mistaken for the accounting value.
    exactAttr = exactCentsAttr(cell.cents);
    const tone = creditsTone(cell.cents);
    if (cell.signed && tone) valueClasses.push(tone);
    valueHtml = escapeHtml(formatCredits(cell.cents, { signed: Boolean(cell.signed) }));
  } else if (cell.text != null && cell.text !== '') {
    valueHtml = escapeHtml(cell.text);
  } else {
    valueHtml = PENDING_FIGURE;
  }

  // Rank and similar context read as context, not as a second figure: the
  // separator itself is secondary grey.
  const contextHtml = cell.context
    ? `<span class="fs-strip__context"> ${MIDDOT} ${escapeHtml(cell.context)}</span>`
    : '';

  return (
    `<div class="${classes.join(' ')}">` +
    `<div class="fs-strip__label">${escapeHtml(cell.label)}</div>` +
    `<div class="${valueClasses.join(' ')}"${exactAttr}>${valueHtml}${contextHtml}</div>` +
    '</div>'
  );
}

/* ── Credits disclaimer ─────────────────────────────────────────────────── */

/**
 * The approved Credits disclaimer, verbatim.
 *
 * @returns {string}
 */
export function creditsDisclaimer() {
  return `<div class="fs-disclaimer">${CREDITS_DISCLAIMER}</div>`;
}

/**
 * Count disclaimers in a markup fragment — the guard behind "at most once per
 * tab".
 *
 * @param {string} html
 * @returns {number}
 */
export function countDisclaimers(html) {
  const matches = String(html).match(/class="fs-disclaimer"/g);
  return matches ? matches.length : 0;
}

/* ── Container primitives ───────────────────────────────────────────────── */

/**
 * @param {string} bodyHtml
 * @param {{tappable?: boolean, className?: string}} [options]
 * @returns {string}
 */
export function card(bodyHtml, options = {}) {
  const classes = ['fs-card'];
  if (options.tappable) classes.push('is-tappable');
  if (options.className) classes.push(options.className);
  return `<div class="${classes.join(' ')}">${bodyHtml}</div>`;
}

/**
 * @param {string} bodyHtml
 * @param {{className?: string}} [options]
 * @returns {string}
 */
export function tile(bodyHtml, options = {}) {
  const classes = ['fs-tile'];
  if (options.className) classes.push(options.className);
  return `<div class="${classes.join(' ')}">${bodyHtml}</div>`;
}

/**
 * Horizontal scroll-snap rail. Items are stretched to the rail height, so a
 * card gains lines of copy without gaining height.
 *
 * @param {string[]} itemsHtml
 * @param {{label?: string}} [options]
 * @returns {string}
 */
export function rail(itemsHtml, options = {}) {
  const labelAttr = options.label ? ` aria-label="${escapeHtml(options.label)}"` : '';
  return (
    `<div class="fs-rail is-stretch" role="list"${labelAttr}>` +
    itemsHtml
      .map((item) => `<div class="fs-rail__item" role="listitem">${item}</div>`)
      .join('') +
    '</div>'
  );
}

/**
 * Vertical snap list.
 *
 * @param {string[]} itemsHtml
 * @returns {string}
 */
export function vSnapList(itemsHtml) {
  return (
    '<div class="fs-vsnap">' +
    itemsHtml.map((item) => `<div class="fs-vsnap__item">${item}</div>`).join('') +
    '</div>'
  );
}

/**
 * Equal-billing zone parent — children receive identical height allocation.
 *
 * @param {string[]} zonesHtml
 * @returns {string}
 */
export function equalZones(zonesHtml) {
  return (
    '<div class="fs-zones">' +
    zonesHtml.map((zone) => `<div class="fs-zone">${zone}</div>`).join('') +
    '</div>'
  );
}

/**
 * @param {string} text
 * @param {{pending?: boolean}} [options]
 * @returns {string}
 */
export function note(text, options = {}) {
  const classes = ['fs-note'];
  if (options.pending) classes.push('fs-note--pending');
  return `<div class="${classes.join(' ')}">${escapeHtml(text)}</div>`;
}

/* ── Pop-out / bottom sheet ─────────────────────────────────────────────── */

/**
 * The universal close control: an upper-right X on the active sheet or card.
 * Rev4.2 — this supersedes any older upper-left treatment.
 *
 * @returns {string}
 */
export function closeControl() {
  return (
    '<button type="button" class="fs-sheet__close" data-fs-close aria-label="Close">' +
    '&times;' +
    '</button>'
  );
}

/**
 * Sheet body markup. The close control is emitted first so it is the first
 * focusable element inside the sheet, and positioned upper-right by
 * `.fs-sheet__close`.
 *
 * @param {{title?: string, sub?: string, body?: string}} spec
 * @returns {string}
 */
export function sheet(spec = {}) {
  const { title = '', sub = '', body = '' } = spec;
  const titleHtml = title
    ? `<h3 class="fs-sheet__title" id="fs-sheet-title">${escapeHtml(title)}</h3>`
    : '';
  const subHtml = sub ? `<div class="fs-sheet__sub">${escapeHtml(sub)}</div>` : '';
  return closeControl() + titleHtml + subHtml + body;
}

/* ── Panel composition ──────────────────────────────────────────────────── */

/**
 * Assembles one tab's above-the-scroll region and enforces the POR's structural
 * rules for it.
 *
 * The disclaimer rule is the reason this is a composer rather than a plain
 * concatenation: it appears under the applicable four-cell strip, at most once
 * per tab. Both halves are enforced — a second call throws, and a disclaimer
 * with no strip above it throws.
 */
export class PanelComposer {
  /**
   * @param {string} destinationId
   */
  constructor(destinationId) {
    this.destinationId = destinationId;
    this.parts = [];
    this.stripCount = 0;
    this.disclaimerCount = 0;
  }

  /**
   * @param {string} html
   * @returns {PanelComposer}
   */
  add(html) {
    this.parts.push(html);
    return this;
  }

  /**
   * @param {{cells: StripCell[], id?: string, label?: string}} spec
   * @returns {PanelComposer}
   */
  addStrip(spec) {
    this.parts.push(summaryStrip(spec));
    this.stripCount += 1;
    return this;
  }

  /**
   * The Credits disclaimer, under the applicable strip, once per tab.
   *
   * @returns {PanelComposer}
   */
  addDisclaimer() {
    if (this.stripCount === 0) {
      throw new Error(
        `tab "${this.destinationId}": the Credits disclaimer appears under a ` +
        'four-cell strip — none has been added',
      );
    }
    if (this.disclaimerCount > 0) {
      throw new Error(
        `tab "${this.destinationId}": the Credits disclaimer appears at most ` +
        'once per tab',
      );
    }
    this.parts.push(creditsDisclaimer());
    this.disclaimerCount += 1;
    return this;
  }

  /**
   * @returns {string}
   */
  toHTML() {
    return this.parts.join('');
  }
}

/**
 * Tab header block — identity left, context right.
 *
 * @param {{title: string, sub?: string, asideValue?: string, asideLabel?: string}} spec
 * @returns {string}
 */
export function tabHeader(spec) {
  const { title, sub = '', asideValue = '', asideLabel = '' } = spec || {};
  const asideHtml = asideValue || asideLabel
    ? '<div class="fs-tabhead__aside">' +
      (asideValue ? `<div class="fs-money">${escapeHtml(asideValue)}</div>` : '') +
      (asideLabel ? `<div class="fs-tabhead__sub">${escapeHtml(asideLabel)}</div>` : '') +
      '</div>'
    : '';
  return (
    '<div class="fs-tabhead">' +
    '<div class="fs-tabhead__main">' +
    `<div class="fs-tabhead__title">${escapeHtml(title)}</div>` +
    (sub ? `<div class="fs-tabhead__sub">${escapeHtml(sub)}</div>` : '') +
    '</div>' +
    asideHtml +
    '</div>'
  );
}
