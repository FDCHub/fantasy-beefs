/* ============================================================================
 * FantasyStakes — `↻ REFRESH ODDS` on a live Dynamic Matchup card
 * UIRECON Rev 1.4 · Simulation Engine Rev 9 §5 · Locked-vs-Dynamic ruling §§3–4
 *
 * THE DEFECT THIS CLOSES. A Dynamic Matchup is the mode whose lineups,
 * projections and odds stay LIVE until Final Lock. The card said so — "Your
 * opponent's stake is set at Final Lock…" — and then showed a price frozen at
 * the moment the wager was agreed, with no way to see where the live line had
 * actually gone. The one mode whose defining property is movement was the one
 * mode a GM could not watch move.
 *
 * WHAT THE CONTROL PROMISES, AND WHAT IT MUST NOT. It promises FRESH ODDS. It
 * must not imply the wager repriced, because it did not and cannot: Rev 9 §5
 * makes these refreshes nonbinding, the ruling §3 says they "move no money",
 * and the opponent's Derived Stake is set once, at Final Lock, bounded by the
 * ceiling agreed at the Handshake. So the confirmation is two short lines and
 * the second one is the important one:
 *
 *     Fresh odds from current projections
 *     Wager unchanged
 *
 * It is deliberately not a success toast, not a green tick and not an animated
 * figure change. A refresh is a GM looking something up; feedback louder than
 * the act would read as a transaction, which is the one thing this must never
 * read as.
 *
 * IT NEVER APPEARS ON A LOCKED CARD. Not disabled, not greyed, not present with
 * an explanation — absent. A Locked wager's terms froze when it was OFFERED
 * (ruling §§1–2) and acceptance merely SELECTS a frozen proposal; there is no
 * live line behind it to reveal. The Locked answer to "I want different terms"
 * is Refresh & Relock, which is a COUNTER that puts a new frozen proposal on the
 * table, and it lives in the response controls where it belongs. Drawing a
 * lookalike control beside it would put two very different verbs on one card:
 * one that changes nothing and one that replaces the wager.
 *
 * ELIGIBILITY IS THE SERVER'S ANSWER. `canRefreshOdds` is a PRE-CHECK that
 * decides whether to draw a control at all; the route re-decides on every call
 * and refuses with a governed reason code regardless of what this concluded. It
 * exists to avoid drawing a button that could not work — not to be an authority.
 *
 * NOTHING HERE COMPUTES A PRICE. The only arithmetic in this file is clock
 * arithmetic for `Updated 10:42 AM`. Every probability, moneyline and cent
 * figure is served, issuer-anchored, and rendered as it arrived.
 * ========================================================================== */

import { escapeHtml } from './components.js';
import { refreshControl, runRefresh } from './odds-refresh.js';
// `refreshControl` still draws the Dynamic card's own glyph; the Locked
// comparison below deliberately draws none.
import { formatOdds } from './wager-model.js';

/**
 * The control's label.
 *
 * THE GLYPH IS CARRIED, NOT DECORATIVE. `↻` is the one-character statement that
 * this control re-reads rather than changes, and the card grammar already uses
 * a bare glyph as a verb marker (`Challenge ›`). The words are set in caps to
 * match the card's other machine-state vocabulary — `FLOATING`, `FIXED`, and
 * the rail headings — rather than the sentence-case response verbs (`Accept`,
 * `Counter`, `Decline`), because this is not a decision on the wager and should
 * not sit in the same visual register as the three controls that are.
 */
export const REFRESH_LABEL = 'Refresh odds for this Matchup';

/* ── THE WIDE BUTTON IS GONE ────────────────────────────────────────────────
 *
 * Rev 1.4 drew `↻ REFRESH ODDS` as a full-width control. It worked and it read
 * wrong: a button that wide is the size this product uses for DECISIONS —
 * Accept, Counter, Submit Pick — and a refresh is a GM looking something up.
 * The affordance is now the same small glyph Play uses, from `odds-refresh.js`,
 * so one gesture means one thing everywhere in the product.
 *
 * THE WORDS MOVED INTO THE ACCESSIBLE NAME rather than disappearing. `↻` cannot
 * say WHAT it refreshes, so `REFRESH_LABEL` is the button's `aria-label` — which
 * a keyboard and a screen reader both reach, and a tooltip is not.
 */

/** The label on a LOCKED card's frozen price. */
export const LOCKED_ODDS_LABEL = 'LOCKED ODDS';

/** The label on the live market line for the same pairing. */
export const CURRENT_ODDS_LABEL = 'CURRENT ODDS';

/** What `CURRENT ODDS` reads when no live line can be quoted. */
export const CURRENT_ODDS_UNAVAILABLE = 'Unavailable';

/** The two lines shown after a successful refresh, in order. Copy of record. */
export const REFRESH_CONFIRMATION = Object.freeze([
  'Fresh odds from current projections',
  'Wager unchanged',
]);

/** What the stamp reads before anyone has ever refreshed this Matchup. */
export const NEVER_REFRESHED = 'Not refreshed yet';

/** Live command binding — see `setRefreshHook`. @type {object|null} */
let REFRESH_HOOK = null;

/**
 * Bind the control to the live commands.
 *
 * UNBOUND MEANS UNDRAWN, not "drawn and inert". A component suite rendering a
 * card in isolation must not produce a button that silently does nothing when a
 * GM presses it.
 *
 * @param {{read: Function, refresh: Function, explain: Function}|null} hook
 */
export function setRefreshHook(hook) {
  REFRESH_HOOK = hook || null;
}

/** @returns {boolean} */
export function refreshHookBound() {
  return REFRESH_HOOK !== null;
}

/**
 * Whether this card may offer the control.
 *
 * THE FOUR CONDITIONS ARE THE SERVER'S OWN WINDOW, asked in the client's
 * vocabulary: Dynamic mode, an accepted wager, a Handshake that has happened
 * (`derivedRepriced` is the Action contract's name for "this Dynamic challenge
 * has Handshaken"), and nothing settled. A wager past Final Lock fails the
 * server's check even when it passes this one, which is why the response's
 * `refresh_eligible` is what the mounted control actually obeys.
 *
 * @param {object} card a normalised Action card
 * @returns {boolean}
 */
export function canRefreshOdds(card) {
  if (!card || card.mode !== 'dynamic') return false;
  if (card.settled) return false;
  if (card.protocolState !== 'accepted') return false;
  return card.derivedRepriced === true;
}

/**
 * `Updated 10:42 AM` — the concise last-refreshed stamp.
 *
 * THE SERVER'S TIMESTAMP IS NAIVE UTC and JavaScript would read it as LOCAL.
 * `new Date('2026-08-21T10:42:03')` is, per the language spec, the viewer's own
 * 10:42 — so a GM five hours behind would be told the line was refreshed five
 * hours in the future. A missing offset is therefore supplied as `Z` before
 * parsing, and the result is rendered in the viewer's own clock, which is the
 * only clock `10:42 AM` can honestly mean on a phone.
 *
 * THE HOUR IS FORMATTED HERE RATHER THAN BY `toLocaleTimeString`. The locale
 * function is right for a product that wants the viewer's convention and wrong
 * for one whose copy is specified to the character: the same call renders
 * `10:42 am`, `10:42 AM` or `10.42` depending on the browser's locale data, and
 * the certification asserts one string.
 *
 * @param {string|Date|null} when an ISO timestamp, or null
 * @returns {string}
 */
export function refreshStamp(when) {
  if (!when) return NEVER_REFRESHED;
  let date;
  if (when instanceof Date) {
    date = when;
  } else {
    const text = String(when);
    const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(text);
    date = new Date(hasZone ? text : `${text}Z`);
  }
  if (Number.isNaN(date.getTime())) return NEVER_REFRESHED;

  const hours24 = date.getHours();
  const meridiem = hours24 < 12 ? 'AM' : 'PM';
  const hours12 = hours24 % 12 === 0 ? 12 : hours24 % 12;
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `Updated ${hours12}:${minutes} ${meridiem}`;
}

/**
 * The control and its stamp, as HTML.
 *
 * RETURNS THE EMPTY STRING FOR AN INELIGIBLE CARD. Not a disabled button and
 * not an explanation: a Locked Matchup's card should look like a Locked
 * Matchup's card, with nothing on it hinting at a behaviour it does not have.
 *
 * @param {object} card a normalised Action card
 * @param {{refreshedAt?: string|null, eligible?: boolean}} [state]
 * @returns {string}
 */
export function refreshOddsControl(card, state = {}) {
  if (!canRefreshOdds(card)) return '';
  if (state.eligible === false) return '';
  if (!REFRESH_HOOK) return '';

  const stamp = refreshStamp(state.refreshedAt || null);
  return (
    `<div class="fs-refresh" data-refresh-block data-challenge-id="${escapeHtml(String(card.challengeId))}">`
    + refreshControl({
      scope: 'wager',
      target: card.challengeId,
      label: REFRESH_LABEL,
      extraClass: 'fs-oddsref--card',
    })
    + `<span class="fs-refresh__stamp" data-refresh-stamp>${escapeHtml(stamp)}</span>`
    + '<div class="fs-refresh__note" data-refresh-note aria-live="polite"></div>'
    + '</div>'
  );
}

/**
 * Whether this card may show a LOCKED-versus-CURRENT comparison.
 *
 * LOCKED ONLY, AND ONLY WHILE IT IS STILL A WAGER. A Dynamic card has its own
 * live figures and a refresh that updates them; a settled card's price is
 * history, and a live line beside it would invite a comparison nobody can act
 * on. The frozen price itself has to exist, because a comparison with one side
 * missing is not a comparison.
 *
 * @param {object} card a normalised Action card
 * @returns {boolean}
 */
export function canCompareLockedOdds(card) {
  if (!card || card.mode !== 'locked') return false;
  if (card.settled) return false;
  return Number.isInteger(card.yourMoneyline);
}

/**
 * `LOCKED ODDS -118 / CURRENT ODDS -135`, as HTML.
 *
 * ── THE LOCKED FIGURE IS THE WAGER; THE CURRENT FIGURE IS THE WEATHER ───────
 *
 * A Locked wager's terms froze when it was OFFERED, and acceptance merely
 * SELECTS a frozen proposal (Locked-vs-Dynamic ruling §§1–2). Nothing on this
 * surface can move them, and this block is careful never to suggest otherwise:
 * the two rows are LABELLED differently, the current figure is drawn quieter,
 * and there is no arrow, delta or colour implying one is becoming the other.
 *
 * WHAT `CURRENT` IS. The live market line for the SAME PAIRING, from the same
 * board Play prices its cards from — not a re-quote of this wager, which cannot
 * be re-quoted. It answers "what would this matchup cost today", which is a
 * fair question with an honest answer, and it is exactly why the Locked reply
 * to wanting different terms is Refresh & Relock: a COUNTER that puts a new
 * frozen proposal on the table.
 *
 * AN ABSENT CURRENT LINE SAYS SO. `Unavailable` rather than a dash, because a
 * dash in this product is an unresolved FIGURE and this is an unresolved
 * QUESTION — the board could not price the pairing, or was priced for another
 * week. Nothing is fabricated to fill the row.
 *
 * @param {object} card a normalised Action card
 * @param {{moneyline?: number|null, available?: boolean}} [current]
 * @returns {string}
 */
export function lockedOddsComparison(card, current = {}) {
  if (!canCompareLockedOdds(card)) return '';

  const live = current && current.available === true
    && Number.isInteger(current.moneyline)
    ? formatOdds(current.moneyline)
    : CURRENT_ODDS_UNAVAILABLE;

  const row = (label, value, quiet) => (
    `<span class="fs-oddscmp__row${quiet ? ' is-quiet' : ''}">`
    + `<span class="fs-oddscmp__label">${escapeHtml(label)}</span>`
    + `<span class="fs-oddscmp__value"${quiet ? ' data-current-odds' : ''}>`
    + `${escapeHtml(value)}</span>`
    + '</span>'
  );

  // ── IT IS A READING, NOT A CONTROL, AND THAT IS TWO DECISIONS ─────────────
  //
  // THE FIRST IS SPACE, AND IT WAS MEASURED. A Status lifecycle card is a
  // fixed-height carousel item and Rev 1.4 Part 11 tuned all four rails to fit
  // one mobile viewport. Adding a refresh glyph to this block took it to 36px,
  // and the card then needed 142px inside 136 and clipped its own foot at every
  // certified viewport. A block that annotates a card may not break it.
  //
  // THE SECOND IS MEANING, and it is the better reason. Rev 1.4's own note
  // argued at length that a refresh affordance on a Locked card would put two
  // very different verbs side by side: one that changes nothing, and Refresh &
  // Relock, which replaces the wager. A read-only pair of figures cannot be
  // mistaken for either.
  //
  // THE FIGURE STILL MOVES. `CURRENT ODDS` is read from the same market board
  // Play prices its cards from, so refreshing on Play updates what this card
  // reports the next time Status draws — one board, one line, two surfaces.
  return (
    '<div class="fs-oddscmp" data-locked-odds '
    + `data-challenge-id="${escapeHtml(String(card.challengeId))}" `
    + `data-opponent-team-id="${escapeHtml(String(card.opponentTeamId))}">`
    + row(LOCKED_ODDS_LABEL, formatOdds(card.yourMoneyline), false)
    + row(CURRENT_ODDS_LABEL, live, true)
    + '</div>'
  );
}

/**
 * The confirmation block, as HTML.
 *
 * TWO LINES, THE SECOND SUBORDINATE TO THE FIRST. `Wager unchanged` is the
 * claim that has to survive a GM skimming, so it is its own line rather than a
 * clause; and it is the LAST thing read, which is where a reassurance belongs.
 *
 * @returns {string}
 */
export function refreshConfirmation() {
  return REFRESH_CONFIRMATION
    .map((line, index) => (
      `<span class="fs-refresh__line${index ? ' is-quiet' : ''}">`
      + `${escapeHtml(line)}</span>`
    ))
    .join('');
}

/**
 * Fill one already-rendered control with the served figures and wire it.
 *
 * NO OPTIMISTIC UPDATE. The stamp is not advanced and the note is not written
 * until the server has answered, because the whole value of the stamp is that
 * it reports when the SHARED figures were produced. A client-set timestamp
 * would be this GM's guess about a fact the other GM also reads.
 *
 * @param {Element} block a `[data-refresh-block]` element
 * @param {number} leagueId
 */
export function bindRefreshControl(block, leagueId) {
  if (!block || !REFRESH_HOOK) return;
  const button = block.querySelector('[data-refresh-odds]');
  const stamp = block.querySelector('[data-refresh-stamp]');
  const note = block.querySelector('[data-refresh-note]');
  const challengeId = Number(block.dataset.challengeId);
  if (!button || !Number.isFinite(challengeId)) return;

  // THE SHARED STATE MACHINE drives the glyph — idle, working, done, error —
  // so this control and Play's behave identically on a refusal. What is local
  // to this surface is WHERE the two outcomes are written: the stamp and the
  // two-line confirmation under the card, which Play has no equivalent of.
  button.addEventListener('click', (event) => {
    // The lifecycle card is tappable in its own right; a refresh must not also
    // be whatever the card behind it does.
    event.preventDefault();
    event.stopPropagation();
    runRefresh(button, {
      work: async () => {
        if (note) note.textContent = '';
        const served = await REFRESH_HOOK.refresh(leagueId, challengeId);
        if (stamp) stamp.textContent = refreshStamp(served && served.refreshed_at);
        if (note) note.innerHTML = refreshConfirmation();
        return served;
      },
      // THE MATCHUP IS STILL FINE, AND THE COPY SAYS SO. A refusal here means
      // the DISPLAY could not be refreshed; nothing about the wager moved, and
      // `explainRefreshRefusal` is written so no sentence suggests otherwise.
      onError: (error) => {
        if (!note) return;
        note.textContent = REFRESH_HOOK.explain
          ? REFRESH_HOOK.explain(error)
          : 'Fresh odds are not available right now. Your Matchup is unchanged.';
      },
    });
  });
}

/**
 * Put the control on every eligible Dynamic card already rendered under `root`.
 *
 * A DECORATOR, NOT A RENDERER. The lifecycle card is drawn by the Status
 * surface through the shared card grammar, and this attaches to what that drew
 * rather than reproducing any of it — so a card keeps one identity, one shell
 * and one set of figures however many surfaces enhance it.
 *
 * IT ASKS THE SERVER PER CARD, and only for cards that pass the client
 * pre-check. The GET carries the shared `refreshed_at`, so the stamp is right
 * the moment the card appears — including for the GM who did not press the
 * button. A card whose read is refused simply does not gain the control.
 *
 * ── IT ALSO DECORATES LOCKED CARDS, AND WITH SOMETHING ELSE ────────────────
 *
 * A Locked wager gets no refresh control: its terms froze when it was OFFERED
 * and there is no live line behind them to reveal. What it DOES get, when the
 * caller can supply one, is a read-only `LOCKED ODDS / CURRENT ODDS` block —
 * the frozen price beside the live market line for the same pairing. That is a
 * comparison, not an affordance, and nothing about it can be pressed.
 *
 * `currentOddsFor` IS THE CALLER'S, because this module must not know that a
 * market board exists. It is handed a function from card to `{available,
 * moneyline}` and asks it once per Locked card; a caller with no board omits it
 * and every row reads `Unavailable`, which is the honest answer.
 *
 * @param {Element} root the panel the cards were rendered into
 * @param {{leagueId: number, cards: object[],
 *          currentOddsFor?: Function}} options
 * @returns {Promise<number>} how many decorations were mounted
 */
export async function mountRefreshOdds(root, options = {}) {
  const { leagueId, cards = [], currentOddsFor } = options;
  if (!root || !REFRESH_HOOK || !Number.isFinite(Number(leagueId))) return 0;

  let mounted = 0;
  for (const card of cards) {
    if (canCompareLockedOdds(card)) {
      const host = root.querySelector(`[data-card-id="${CSS.escape(card.id)}"]`);
      if (!host || host.querySelector('[data-locked-odds]')) continue;
      // NO SOURCE FOR `CURRENT`, NO BLOCK. `currentOddsFor` answers null when
      // no market board covers this card's week, and a comparison with nothing
      // to compare against is not a comparison — it is a card made taller by an
      // apology. The Dynamic control takes the same position two branches down.
      const current = typeof currentOddsFor === 'function'
        ? currentOddsFor(card) : null;
      if (!current) continue;
      const html = lockedOddsComparison(card, current);
      if (!html) continue;
      asideOf(host).insertAdjacentHTML('beforeend', html);
      mounted += 1;
      continue;
    }
    if (!canRefreshOdds(card)) continue;
    const host = root.querySelector(`[data-card-id="${CSS.escape(card.id)}"]`);
    if (!host || host.querySelector('[data-refresh-block]')) continue;

    let served = null;
    try {
      served = await REFRESH_HOOK.read(leagueId, card.challengeId);
    } catch (error) {
      // A read that was refused is the server declining to offer the control.
      // Nothing is drawn and nothing is explained on the card: a GM did not ask
      // for this, so a refusal they did not provoke is noise.
      continue;
    }
    if (!served || served.refresh_eligible !== true) continue;

    const html = refreshOddsControl(card, {
      refreshedAt: served.refreshed_at,
      eligible: true,
    });
    if (!html) continue;
    const slot = asideOf(host);
    slot.insertAdjacentHTML('beforeend', html);
    const block = slot.querySelector('[data-refresh-block]');
    bindRefreshControl(block, leagueId);
    mounted += 1;
  }
  return mounted;
}

/**
 * The card's `aside` slot, created if the grammar has not drawn one.
 *
 * BETWEEN THE COPY AND THE FOOT, which is where the shared grammar puts it.
 * Appending to the card element instead would land after the foot's call to
 * action, and read as a second, later verb — and neither decoration is a next
 * step. One is context and the other is a comparison.
 *
 * @param {Element} host a card element
 * @returns {Element}
 */
function asideOf(host) {
  let slot = host.querySelector('.fs-wcard__aside');
  if (!slot) {
    slot = host.ownerDocument.createElement('div');
    slot.className = 'fs-wcard__aside';
    const foot = host.querySelector('.fs-wcard__foot');
    if (foot) host.insertBefore(slot, foot);
    else host.appendChild(slot);
  }
  return slot;
}
