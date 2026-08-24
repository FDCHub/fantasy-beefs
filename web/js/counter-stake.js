/* ============================================================================
 * FantasyStakes — the counter-stake sheet
 * WP3C · Rev 4.3 §12.4, WP3C §15
 *
 * WHAT THIS REPLACES. Countering a wager asked for the stake through
 * `window.prompt()`. That is a browser chrome dialog: it carries the origin's
 * hostname instead of the product's identity, it cannot show the GM what they
 * are countering, it cannot show what they can afford, it has no Credits
 * grammar, it cannot render a server refusal, and on several mobile browsers it
 * is suppressed entirely — in which case the control silently did nothing.
 * Rev 4.3 §12.4 names it as not Launch Ready, and it was the last
 * browser-native interaction in the product.
 *
 * WHAT REPLACES IT IS THE GRAMMAR ALREADY IN USE. This is an ordinary sheet
 * level, pushed on the stack, closing from the same upper-left control as
 * every other sheet (§25). It reuses `composer.js`'s stake-field conventions
 * rather than inventing a second way to type an amount.
 *
 * IT CREATES NO ECONOMIC RULE, AND THE VALIDATION HERE IS DELIBERATELY THIN.
 * Two checks run before sending: the field parses as a whole number of Credits,
 * and it is positive. Nothing else. In particular the stake is NOT clamped to
 * the GM's Available — the server owns every bound, a clamp would silently send
 * an amount the GM did not choose, and `explain()` renders the refusal properly
 * when one comes back. Available is DISPLAYED so the GM can decide; it is not
 * enforced here. This is the same rule `settings-command.js` and
 * `economy-command.js` follow.
 * ========================================================================== */

import { accordion, bindAccordions, escapeHtml } from './components.js';
import { formatCredits } from './credits.js';

/**
 * The counter sheet.
 *
 * A FUNCTION RETURNING A SPEC, so the sheet stack re-renders it from current
 * state whenever the stack returns to this level.
 *
 * @param {object} spec
 * @param {object} spec.card the Action card being countered
 * @param {number|null} spec.availableCents the GM's spendable Credits, or null
 * @param {(cents: number) => Promise<void>} spec.onSubmit sends the counter
 * @param {(error: unknown) => string} spec.explain renders a refusal
 * @returns {{title: string, sub: string, body: string, onMount: Function}}
 */
export function counterStakeSheet(spec) {
  const { card, availableCents = null } = spec;

  // WHAT IS BEING COUNTERED, RESTATED. `window.prompt` could not show any of
  // this, so a GM typing a number had only their memory of the card behind the
  // dialog. The opponent, the market and the current terms are all the Action
  // card's own served fields — nothing here derives a term.
  const terms = [card.marketLabel, card.termsLabel]
    .filter(Boolean).map(String).join(' · ');

  const affordance = availableCents === null
    ? '<p class="fs-cstake__hint">Your spendable Credits could not be read, so '
      + 'nothing is shown here. The server still checks what you can cover.</p>'
    : '<p class="fs-cstake__hint">Available '
      + `<span class="fs-money" data-exact-cents="${availableCents}">`
      + `${escapeHtml(formatCredits(availableCents))}</span>`
      + ' · whole Credits only.</p>';

  const preview = [
    accordion({ title: 'LINEUPS', bodyHtml:
      '<div class="fs-note">Current provider lineup detail remains analysis-only and does not alter this counter.</div>' }),
    accordion({ title: 'ON OFFER', bodyHtml:
      `<div class="fs-prev__row"><span class="fs-prev__label">Current terms</span><span class="fs-prev__value">${escapeHtml(terms || 'Unavailable')}</span></div>` }),
    accordion({ title: 'WHY THE LINE LOOKS THIS WAY', bodyHtml:
      '<div class="fs-note">The current market context comes from FantasyStakes projections; the incoming proposal remains locked.</div>' }),
    accordion({ title: 'THE READ', bodyHtml:
      `<div class="fs-note">${escapeHtml(card.copy || 'Review the locked offer before sending new terms.')}</div>` }),
  ].join('');

  return {
    title: 'Counter with a different stake',
    sub: card.opponent ? String(card.opponent) : '',
    body:
      '<div class="fs-cstake" id="fs-cstake">'
      + `<div class="fs-cstake__preview">${preview}</div>`
      + (terms
        ? `<div class="fs-cstake__terms">${escapeHtml(terms)}</div>` : '')
      + '<label class="fs-cstake__label" for="fs-cstake-input">Your stake</label>'
      + '<div class="fs-cstake__field">'
      + '<span class="fs-cstake__cur">$</span>'
      // `inputmode="numeric"` brings up the number pad without the `type=number`
      // spinner, and 16px in the stylesheet keeps mobile Safari from zooming on
      // focus — which matters now that WP3B restored pinch zoom.
      + '<input id="fs-cstake-input" class="fs-cstake__input" type="text" '
      + 'inputmode="numeric" autocomplete="off" value="">'
      + '</div>'
      + affordance
      + '<p class="fs-cstake__error" id="fs-cstake-error" role="alert" '
      + 'aria-live="polite"></p>'
      + '<button type="button" class="fs-cstake__send" id="fs-cstake-send">'
      + 'Send counter</button>'
      + '<button type="button" class="fs-cstake__cancel" id="fs-cstake-cancel">'
      + 'Cancel</button>'
      + '</div>',
    onMount: (host, api) => bindCounterStake(host, api, spec),
  };
}

/**
 * Whole Credits in, exact cents out.
 *
 * WHOLE CREDITS ONLY, AND THAT IS A DISPLAY CONTRACT RATHER THAN A NEW RULE.
 * Rev 4.3 §6 makes whole-Credit the standard UI treatment; the ledger remains
 * cents-based underneath and this multiplies up to it exactly. A GM who types
 * `25.50` is told to enter whole Credits rather than having their input
 * silently rounded into a stake they did not choose.
 *
 * @param {string} raw
 * @returns {number|null} exact integer cents, or null when unparseable
 */
export function parseWholeCredits(raw) {
  const trimmed = String(raw == null ? '' : raw).trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const credits = Number(trimmed);
  if (!Number.isSafeInteger(credits) || credits <= 0) return null;
  return credits * 100;
}

/**
 * @param {HTMLElement} host
 * @param {{pop: Function, close: Function}} api
 * @param {object} spec
 */
function bindCounterStake(host, api, spec) {
  bindAccordions(host);
  const input = host.querySelector('#fs-cstake-input');
  const send = host.querySelector('#fs-cstake-send');
  const cancel = host.querySelector('#fs-cstake-cancel');
  const error = host.querySelector('#fs-cstake-error');
  let inFlight = false;

  if (input && input.focus) input.focus();

  // CANCEL POPS THE LEVEL, leaving the Response Card underneath exactly as it
  // was. `window.prompt` returning null used to mean the same thing, and the
  // difference is that a GM can now see what they are returning to.
  if (cancel) cancel.addEventListener('click', () => api.pop());

  const submit = async () => {
    if (inFlight) return;
    error.textContent = '';

    const cents = parseWholeCredits(input.value);
    if (cents === null) {
      error.textContent = 'Enter a whole number of Credits, like 25.';
      input.focus();
      return;
    }

    inFlight = true;
    send.disabled = true;
    send.textContent = 'Sending…';
    try {
      // NOT CLAMPED to Available. The server owns the bound and refuses with a
      // message this renders; clamping would report success for an amount the
      // GM did not choose.
      await spec.onSubmit(cents);
      // The caller closes or refreshes on success — it owns what happens next,
      // because it is the thing that knows whether the Response Card behind
      // this level still exists.
    } catch (refusal) {
      error.textContent = spec.explain(refusal);
      inFlight = false;
      send.disabled = false;
      send.textContent = 'Send counter';
    }
  };

  if (send) send.addEventListener('click', submit);

  // Enter submits, which is what the prompt did and what a one-field form
  // should do. It goes through the same path as the button, so the validation
  // and the in-flight guard cannot diverge between the two.
  if (input) {
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        submit();
      }
    });
  }
}
