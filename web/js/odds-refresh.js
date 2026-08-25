/* ============================================================================
 * FantasyStakes — the small odds-refresh control
 * UIRECON · refine-refresh pass
 *
 * WHAT REPLACED WHAT. Rev 1.4 shipped one refresh affordance: a full-width
 * `↻ REFRESH ODDS` button on live Dynamic cards, with a stamp and a two-line
 * confirmation under it. The machinery under it was right and is untouched; the
 * SURFACE was wrong in two ways. It was the size of a decision — a GM reads a
 * button that wide as something that commits them — and it existed in exactly
 * one place, on a card a GM reaches only after a wager already exists, so the
 * screen where prices are actually shopped had no way to re-read them at all.
 *
 * SO THE CONTROL BECAME A GLYPH AND MOVED TO WHERE THE PRICES ARE. This module
 * is that glyph: one small button, four states, an accessible name that says
 * WHAT it refreshes, and a stamp that says when. It is used at two levels —
 * a heading control that re-reads a whole board, and a per-card control that
 * re-reads one pairing — and both are the same object so they cannot drift into
 * looking like different promises.
 *
 * ── WHY A GLYPH IS ENOUGH, AND WHERE THE WORDS WENT ─────────────────────────
 *
 * `↻` is the sportsbook convention for "re-read the market", and this product
 * already uses a bare glyph as a verb marker. What a glyph cannot carry is WHO
 * it applies to, so every control names its own subject in `aria-label` —
 * `Refresh odds for all matchups`, `Refresh odds for The Braintrust` — and the
 * label is the accessible name rather than a tooltip, because a tooltip is not
 * available to a keyboard or a screen reader.
 *
 * ── THE FOUR STATES, AND WHY `done` IS NOT A TOAST ──────────────────────────
 *
 *   idle     ↻
 *   working  ↻ spinning, `aria-busy`, control disabled
 *   done     ✓ briefly, then back to idle on its own
 *   error    ↻ again, with the refusal written into the status line
 *
 * `done` reverts itself because a refresh is a GM looking something up, not a
 * transaction. A persistent success state would leave the screen asserting that
 * something happened long after it stopped being news — and on a card whose
 * whole risk is reading as an economic event, a lingering green tick is exactly
 * the wrong lie.
 *
 * ── NOTHING HERE COMPUTES A PRICE ───────────────────────────────────────────
 *
 * The only arithmetic in this file is clock arithmetic. Every probability,
 * moneyline, spread and total is served, and the modules that call this one hand
 * it strings that already came off the wire.
 * ========================================================================== */

import { escapeHtml } from './components.js';

/** The idle glyph — "re-read this market". */
export const REFRESH_GLYPH = '↻';

/** The brief acknowledgement glyph. Replaced by `REFRESH_GLYPH` on its own. */
export const DONE_GLYPH = '✓';

/** How long `done` shows before the control returns to idle, in ms. */
export const DONE_MS = 1600;

/**
 * The status line Play's two controls share.
 *
 * ONE ID, BOUND BY BOTH SURFACES. It lives here rather than in `league.js`
 * because the module that BINDS the controls needs it too, and importing it
 * from the renderer would put a cycle between the two.
 */
export const BOARD_STAMP_ID = 'play-board';

/** The four states a control can be in. */
export const STATE_IDLE = 'idle';
export const STATE_WORKING = 'working';
export const STATE_DONE = 'done';
export const STATE_ERROR = 'error';

/**
 * `Odds updated 11:47 AM` — the shared stamp, or a neutral never-yet state.
 *
 * THE SERVER'S TIMESTAMP IS THE SUBJECT. Callers pass what the server said —
 * `computed_at` for a board, `refreshed_at` for a wager's shared refresh row —
 * and this only formats it. Nothing here reads the client clock, so a surface
 * can never print a time no process actually produced.
 *
 * A NAIVE TIMESTAMP IS TREATED AS UTC. `new Date('2026-08-21T11:47:03')` is,
 * per the language spec, the VIEWER's 11:47 — so a GM five hours behind would
 * be told the board priced five hours in the future. A missing offset is
 * supplied as `Z` before parsing and the result renders in the viewer's own
 * clock, which is the only clock `11:47 AM` can honestly mean on a phone.
 *
 * @param {string|Date|null} when
 * @param {string} [prefix] the leading words — the subject differs by surface
 * @returns {string}
 */
export function oddsStamp(when, prefix = 'Odds updated') {
  const time = clockTime(when);
  return time === null ? '' : `${prefix} ${time}`;
}

/**
 * `11:47 AM` from a server timestamp, or null when there isn't one.
 *
 * FORMATTED HERE RATHER THAN BY `toLocaleTimeString`, which renders
 * `11:47 am`, `11:47 AM` or `11.47` depending on the browser's locale data.
 * The copy is specified to the character and the certification asserts one
 * string.
 *
 * @param {string|Date|null} when
 * @returns {string|null}
 */
export function clockTime(when) {
  if (!when) return null;
  let date;
  if (when instanceof Date) {
    date = when;
  } else {
    const text = String(when);
    const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(text);
    date = new Date(hasZone ? text : `${text}Z`);
  }
  if (Number.isNaN(date.getTime())) return null;

  const hours24 = date.getHours();
  const meridiem = hours24 < 12 ? 'AM' : 'PM';
  const hours12 = hours24 % 12 === 0 ? 12 : hours24 % 12;
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours12}:${minutes} ${meridiem}`;
}

/**
 * One refresh control, as HTML.
 *
 * `scope` AND `target` ARE THE WHOLE CONTRACT between this markup and whatever
 * binds it. `scope` says what class of thing is being re-read — a board, one
 * pairing, one wager — and `target` names the subject within that scope. A
 * binder reads both off the element rather than from a closure, so a control
 * survives its panel being re-rendered underneath it.
 *
 * THE BUTTON IS `type="button"`, always. Play's cards sit inside no form today,
 * but the composer's do, and a control that submitted a form because someone
 * moved it would be a defect nobody would look for here.
 *
 * @param {{scope: string, target?: string|number, label: string,
 *          extraClass?: string}} options
 * @returns {string}
 */
export function refreshControl(options) {
  const { scope, target = '', label, extraClass = '' } = options || {};
  if (!scope || !label) return '';
  const classes = `fs-oddsref${extraClass ? ` ${extraClass}` : ''}`;
  return (
    `<button type="button" class="${escapeHtml(classes)}" data-odds-refresh `
    + `data-refresh-scope="${escapeHtml(String(scope))}" `
    + `data-refresh-target="${escapeHtml(String(target))}" `
    + `data-refresh-state="${STATE_IDLE}" `
    + `aria-label="${escapeHtml(label)}">`
    + `<span class="fs-oddsref__glyph" aria-hidden="true">${REFRESH_GLYPH}</span>`
    + '</button>'
  );
}

/**
 * The polite status line a control writes its stamp and refusals into.
 *
 * ONE LIVE REGION PER SUBJECT, not per control. Two controls that refresh the
 * same board share this, so a screen reader hears one sentence when the board
 * moves rather than one per affordance that happens to be on screen.
 *
 * @param {{id: string, text?: string, extraClass?: string}} options
 * @returns {string}
 */
export function refreshStatus(options) {
  const { id, text = '', extraClass = '' } = options || {};
  if (!id) return '';
  const classes = `fs-oddsref__stamp${extraClass ? ` ${extraClass}` : ''}`;
  return (
    `<span class="${escapeHtml(classes)}" data-odds-stamp="${escapeHtml(id)}" `
    + 'role="status" aria-live="polite">'
    + `${escapeHtml(text)}</span>`
  );
}

/**
 * Move one control into a state, glyph and ARIA together.
 *
 * DISABLED ONLY WHILE WORKING. An errored control must stay pressable — the
 * refusal it just reported may be a roster that has since arrived — and a
 * `done` control must stay pressable because a GM watching a line move has
 * every reason to ask again immediately.
 *
 * @param {Element|null} button a `[data-odds-refresh]` element
 * @param {string} state one of the STATE_* constants
 */
export function setRefreshState(button, state) {
  if (!button) return;
  const glyph = button.querySelector('.fs-oddsref__glyph');
  button.dataset.refreshState = state;
  if (state === STATE_WORKING) {
    button.setAttribute('aria-busy', 'true');
    button.disabled = true;
  } else {
    button.removeAttribute('aria-busy');
    button.disabled = false;
  }
  if (glyph) {
    glyph.textContent = state === STATE_DONE ? DONE_GLYPH : REFRESH_GLYPH;
  }
}

/**
 * Write a sentence into the status line a control is paired with.
 *
 * @param {Document|Element} root
 * @param {string} id the `data-odds-stamp` value
 * @param {string} text
 */
export function setRefreshStatus(root, id, text) {
  if (!root || !id) return;
  const node = root.querySelector(`[data-odds-stamp="${cssEscape(id)}"]`);
  if (node) node.textContent = text;
}

/** `CSS.escape` where it exists, and a conservative fallback where it does not. */
function cssEscape(value) {
  const text = String(value);
  if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') {
    return CSS.escape(text);
  }
  return text.replace(/["\\]/g, '\\$&');
}

/**
 * Run one refresh through the four states.
 *
 * THE STATE MACHINE IS HERE SO EVERY CALLER GETS THE SAME ONE. Two surfaces
 * bind this control and both need identical behaviour on a refusal — the
 * difference between them is only WHAT they re-read, which is the `work`
 * callback. Duplicating the transitions per surface is how one of them ends up
 * leaving a spinner running after an error.
 *
 * IT NEVER THROWS. A decoration that could break its host's event handling
 * would be a worse defect than the refusal it was reporting.
 *
 * @param {Element} button
 * @param {{work: Function, onDone?: Function, onError?: Function,
 *          explain?: Function,
 *          status?: {root: Document|Element, id: string}}} options
 * @returns {Promise<boolean>} whether the work succeeded
 */
export async function runRefresh(button, options) {
  const { work, onDone, onError, explain, status } = options || {};
  if (!button || typeof work !== 'function') return false;
  if (button.dataset.refreshState === STATE_WORKING) return false;

  setRefreshState(button, STATE_WORKING);
  try {
    const result = await work();
    setRefreshState(button, STATE_DONE);
    if (typeof onDone === 'function') onDone(result);
    // BACK TO IDLE ON ITS OWN. Guarded on the state it is leaving, so a second
    // refresh started inside the window is not reverted by the first's timer.
    setTimeout(() => {
      if (button.dataset.refreshState === STATE_DONE) {
        setRefreshState(button, STATE_IDLE);
      }
    }, DONE_MS);
    return true;
  } catch (error) {
    setRefreshState(button, STATE_ERROR);
    // THE CALLER SEES THE ERROR OBJECT, not a re-derived one. A surface with its
    // own place to put a refusal — a note under a card, say — needs the error
    // itself to explain it, and reaching for the last-thrown value from outside
    // would be a race the moment two controls are pressed together.
    if (typeof onError === 'function') onError(error);
    if (status) {
      setRefreshStatus(status.root, status.id,
                       typeof explain === 'function'
                         ? explain(error)
                         : 'Fresh odds are not available right now.');
    }
    setTimeout(() => {
      if (button.dataset.refreshState === STATE_ERROR) {
        setRefreshState(button, STATE_IDLE);
      }
    }, DONE_MS);
    return false;
  }
}
