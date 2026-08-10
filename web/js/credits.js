/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · Credits display formatting
 * Sprint 7 Package 1
 *
 * THIS MODULE IS PRESENTATION ONLY.
 *
 * The accounting value of a Credit amount is an exact integer number of cents.
 * That integer is the only thing the ledger, escrow, settlement and pool
 * protocols ever operate on, and nothing in this file changes it. What this
 * module does is decide how that exact integer is DRAWN: Rev4.2 displays Credit
 * values as whole dollars, rounded to the nearest dollar for presentation.
 *
 * Two rules follow, and both are enforced rather than documented:
 *
 *   1. Input must already be an exact integer count of cents. A float is
 *      rejected outright, because accepting one would mean some upstream code
 *      had already lost precision and this module would quietly launder the
 *      loss into a plausible-looking figure.
 *
 *   2. A rounded figure must never travel back into calculation. Rendering
 *      helpers carry the original integer alongside the drawn text in
 *      `data-exact-cents`, so the exact value remains available to any reader
 *      and the displayed string is never the source of truth.
 * ========================================================================== */

/** U+2212 MINUS SIGN — the negative-money glyph used throughout the POR. */
export const MINUS = '−';

/** U+00B7 MIDDLE DOT — the POR separator. */
export const MIDDOT = '·';

/**
 * Throw unless `cents` is an exact, safe integer count of cents.
 *
 * @param {unknown} cents
 * @param {string} [label] identifies the offending call site in the message
 * @returns {number} the same integer, unchanged
 */
export function assertIntegerCents(cents, label = 'cents') {
  if (typeof cents !== 'number' || !Number.isFinite(cents)) {
    throw new TypeError(`${label} must be a finite number of cents, got ${String(cents)}`);
  }
  if (!Number.isSafeInteger(cents)) {
    throw new TypeError(
      `${label} must be an exact integer number of cents, got ${cents}. ` +
      'A fractional cent means precision was already lost upstream; ' +
      'the display layer will not round it away.',
    );
  }
  return cents;
}

/**
 * Round an exact cent amount to whole dollars for presentation.
 *
 * Half rounds AWAY FROM ZERO, so the rule is symmetric about zero and a debit
 * is never made to look smaller than the matching credit: 150 -> 2, -150 -> -2.
 *
 * @param {number} cents exact integer cents
 * @returns {number} integer dollars — a presentation figure, never an input to
 *   further accounting
 */
export function roundCentsToWholeDollars(cents) {
  assertIntegerCents(cents);
  const sign = cents < 0 ? -1 : 1;
  return sign * Math.floor((Math.abs(cents) + 50) / 100);
}

/**
 * Draw an exact cent amount as a whole-dollar Credit figure.
 *
 * @param {number} cents exact integer cents
 * @param {object} [options]
 * @param {boolean} [options.signed=false] prefix `+` on positive amounts
 * @param {boolean} [options.grouped=true] thousands separators
 * @returns {string} e.g. `$126`, `+$126`, `−$94`
 */
export function formatCredits(cents, options = {}) {
  const { signed = false, grouped = true } = options;
  const dollars = roundCentsToWholeDollars(cents);
  const magnitude = Math.abs(dollars);
  const digits = grouped ? magnitude.toLocaleString('en-US') : String(magnitude);

  // Zero takes no sign in either direction: a rounded-to-zero amount must not
  // claim a direction the figure no longer shows.
  if (dollars === 0) return `$${digits}`;
  if (dollars < 0) return `${MINUS}$${digits}`;
  return signed ? `+$${digits}` : `$${digits}`;
}

/**
 * Signed form — the money grammar used wherever direction matters.
 *
 * @param {number} cents exact integer cents
 * @returns {string}
 */
export function formatSignedCredits(cents) {
  return formatCredits(cents, { signed: true });
}

/**
 * Tone class for a money figure, for the caller to apply.
 *
 * The tone follows the ROUNDED figure, not the exact one: an amount that draws
 * as `$0` must not be painted green or red, because the drawn figure shows no
 * direction to justify the colour.
 *
 * @param {number} cents exact integer cents
 * @returns {'is-positive'|'is-negative'|''}
 */
export function creditsTone(cents) {
  const dollars = roundCentsToWholeDollars(cents);
  if (dollars > 0) return 'is-positive';
  if (dollars < 0) return 'is-negative';
  return '';
}

/**
 * True when rounding for display loses a non-zero remainder.
 *
 * Surfaces exist that must not imply exactness they do not have; this lets a
 * caller decide whether to disclose the rounding. It never changes the figure.
 *
 * @param {number} cents exact integer cents
 * @returns {boolean}
 */
export function isRoundedForDisplay(cents) {
  assertIntegerCents(cents);
  return cents % 100 !== 0;
}

/**
 * The attribute pair that carries the exact value alongside its drawn form.
 *
 * Returns an attribute STRING for the string-building components, so every
 * rendered Credit figure keeps its exact cents in the DOM.
 *
 * @param {number} cents exact integer cents
 * @returns {string} e.g. ` data-exact-cents="12649"`
 */
export function exactCentsAttr(cents) {
  assertIntegerCents(cents);
  return ` data-exact-cents="${cents}"`;
}

/**
 * Read an exact cent value back off a rendered element.
 *
 * @param {{getAttribute: (name: string) => string | null}} el
 * @returns {number} exact integer cents
 */
export function readExactCents(el) {
  const raw = el && el.getAttribute ? el.getAttribute('data-exact-cents') : null;
  if (raw === null || raw === '') {
    throw new Error('element carries no data-exact-cents value');
  }
  const cents = Number(raw);
  return assertIntegerCents(cents, 'data-exact-cents');
}