/* ============================================================================
 * FantasyStakes — commissioner economy setup
 * WP3B · Rev 4.3 §16
 *
 * The configure → review → confirm → activate → frozen flow, as one sheet.
 *
 * THE FIVE STEPS ARE THE SERVER'S LIFECYCLE, NOT A WIZARD THIS FILE INVENTED:
 *
 *   1. configure    PUT  /league/{id}/economy-config
 *   2. review       the derived block, from that route's own response
 *   3. confirm      a deliberate second surface — see below
 *   4. activate     POST /league/{id}/season-allocation
 *   5. frozen       `frozen: true` on the next read
 *
 * WHY CONFIRMATION IS A SEPARATE SHEET LEVEL. Rev 4.3 §16.4 requires activation
 * to be a deliberate confirmation and forbids activating as a side effect of
 * editing. A `confirm()` dialog or an inline "are you sure" checkbox both leave
 * one tap between typing a number and issuing every GM's Credits. Pushing a
 * level onto the sheet stack means the commissioner must read a screen whose
 * only subject is the activation, and whose primary control names what it will
 * do. Activation posts real Credits to every GM in the league and freezes the
 * season's economy; it is not undoable, and the surface should feel that way.
 *
 * NOTHING HERE COMPUTES AN ALLOCATION. Every derived figure is read from the
 * bound configuration. Search this file for `*` — there is no arithmetic in it
 * beyond the dollars/cents boundary conversion on the way in and out of the
 * form inputs, which is display formatting, not economics. Rev 4.3 §16.2, §28.
 * ========================================================================== */

import { escapeHtml } from './components.js';
import { exactCentsAttr, formatCredits } from './credits.js';
import {
  ECONOMY_DERIVED,
  ECONOMY_INPUTS,
  canActivate,
  currentInputs,
  derivedValue,
  economyCapability,
  economyMode,
  isEditable,
  isFrozen,
  leagueAllocation,
  perPlayerAllocationCents,
  servedEconomy,
} from './economy-model.js';
import {
  activateSeason, explainRefusal, saveEconomyConfig,
} from './economy-command.js';

export const ECONOMY_TITLE = 'League Economy';

/** Whole Credits in, exact cents out — the one conversion boundary. */
function centsFromField(value) {
  const dollars = Number(value);
  if (!Number.isFinite(dollars)) return NaN;
  return Math.round(dollars * 100);
}

/** Exact cents in, a plain whole-Credit number out, for an input's value. */
function fieldFromCents(cents) {
  if (typeof cents !== 'number') return '';
  return String(Math.round(cents / 100));
}

/* ── The derived review block ───────────────────────────────────────────── */

/**
 * Season-Opening Allocation, per player, as the PRIMARY figure — Rev 4.3 §16.3.
 *
 * The league total sits beneath it as secondary informational context (OR-5),
 * and is labelled as a total so it cannot read as an amount FantasyStakes holds.
 * The note under it says so in as many words: §16.3 forbids any presentation
 * that implies FantasyStakes collects money or operates an account.
 *
 * @returns {string}
 */
function allocationBlock() {
  const perPlayer = perPlayerAllocationCents();
  const league = leagueAllocation();

  if (perPlayer === null) {
    return (
      '<div class="fs-econ__alloc is-unresolved" id="fs-econ-allocation">'
      + '<div class="fs-econ__alloc-label">SEASON-OPENING ALLOCATION</div>'
      + '<div class="fs-econ__alloc-value">—</div>'
      + '<p class="fs-econ__alloc-note">Not worked out yet. The season’s week '
      + 'boundaries have to be known before an allocation can be stated.</p>'
      + '</div>'
    );
  }

  const secondary = league
    ? '<div class="fs-econ__alloc-total">'
      + `League allocation total · ${escapeHtml(String(league.teams))} `
      + `team${league.teams === 1 ? '' : 's'} · `
      + `<span class="fs-money"${exactCentsAttr(league.cents)}>`
      + `${escapeHtml(formatCredits(league.cents))}</span>`
      + '</div>'
    : '';

  return (
    '<div class="fs-econ__alloc" id="fs-econ-allocation">'
    + '<div class="fs-econ__alloc-label">SEASON-OPENING ALLOCATION</div>'
    + `<div class="fs-econ__alloc-value fs-money"${exactCentsAttr(perPlayer)}>`
    + `${escapeHtml(formatCredits(perPlayer))} PER PLAYER</div>`
    + secondary
    + '<p class="fs-econ__alloc-note">Credits are virtual. FantasyStakes holds '
    + 'no money and collects none; the league total is shown for context only.'
    + '</p>'
    + '</div>'
  );
}

/**
 * The server-derived, read-only figures.
 * @returns {string}
 */
function derivedBlock() {
  const rows = ECONOMY_DERIVED.map((spec) => {
    const value = derivedValue(spec);
    const drawn = value === null
      ? '<span class="fs-econ__pending">—</span>'
      : (spec.cents
        ? `<span class="fs-money"${exactCentsAttr(value)}>`
          + `${escapeHtml(formatCredits(value))}</span>`
        : escapeHtml(String(value)));
    return (
      `<div class="fs-econ__row" data-derived="${escapeHtml(spec.field)}">`
      + `<span class="fs-econ__row-label">${escapeHtml(spec.label)}</span>`
      + `<span class="fs-econ__row-value">${drawn}</span>`
      + '</div>'
    );
  }).join('');

  return (
    '<section class="fs-econ__block" id="fs-econ-derived">'
    + '<h4 class="fs-econ__block-head">Worked out by FantasyStakes</h4>'
    + rows
    + '<p class="fs-econ__hint">These come from the league’s own record. They '
    + 'are not editable.</p>'
    + '</section>'
  );
}

/* ── The editable inputs ────────────────────────────────────────────────── */

/**
 * The three commissioner inputs.
 *
 * FROZEN RENDERS THE SAME FIGURES, NOT EDITABLE ONES (Rev 4.3 §16.4): after
 * activation the values remain visible and the fields are noneditable. They are
 * `disabled` AND redrawn as plain rows, so a frozen season has no input for a
 * script or a stale cached page to submit.
 *
 * @returns {string}
 */
function inputsBlock() {
  const values = currentInputs();
  const editable = isEditable();

  const rows = ECONOMY_INPUTS.map((input) => {
    const cents = values[input.key];
    if (!editable) {
      return (
        `<div class="fs-econ__row" data-input="${escapeHtml(input.field)}">`
        + `<span class="fs-econ__row-label">${escapeHtml(input.label)}</span>`
        + '<span class="fs-econ__row-value">'
        + (cents === null
          ? '<span class="fs-econ__pending">—</span>'
          : `<span class="fs-money"${exactCentsAttr(cents)}>`
            + `${escapeHtml(formatCredits(cents))}</span>`)
        + '</span></div>'
      );
    }
    return (
      `<label class="fs-econ__field" data-input="${escapeHtml(input.field)}">`
      + `<span class="fs-econ__field-label">${escapeHtml(input.label)}</span>`
      + '<span class="fs-econ__field-input">'
      + '<span class="fs-econ__cur">$</span>'
      + `<input type="number" inputmode="numeric" step="1" `
      + `min="${escapeHtml(fieldFromCents(input.minCents))}" `
      + `max="${escapeHtml(fieldFromCents(input.maxCents))}" `
      + `name="${escapeHtml(input.field)}" `
      + `value="${escapeHtml(fieldFromCents(cents))}">`
      + '</span>'
      + `<span class="fs-econ__field-help">${escapeHtml(input.help)} `
      + `${escapeHtml(formatCredits(input.minCents))}–`
      + `${escapeHtml(formatCredits(input.maxCents))}.</span>`
      + '</label>'
    );
  }).join('');

  return (
    '<section class="fs-econ__block" id="fs-econ-inputs">'
    + '<h4 class="fs-econ__block-head">'
    + (editable ? 'Set by the commissioner' : 'Set for this season')
    + '</h4>'
    + rows
    + '</section>'
  );
}

/* ── States ─────────────────────────────────────────────────────────────── */

/**
 * The frozen banner — Rev 4.3 §16.4.
 * @returns {string}
 */
function frozenBanner() {
  const served = servedEconomy();
  const when = served && served.frozen_at
    ? String(served.frozen_at).slice(0, 10) : null;
  return (
    '<div class="fs-econ__frozen" id="fs-econ-frozen">'
    + '<div class="fs-econ__frozen-head">Locked for this season</div>'
    + '<p class="fs-econ__frozen-body">This season is active and its economy is '
    + 'set. It governs Credits that have already been issued, so it cannot '
    + 'change until next season.'
    + (when ? ` Activated ${escapeHtml(when)}.` : '')
    + '</p></div>'
  );
}

/* ── The sheet ──────────────────────────────────────────────────────────── */

/**
 * The economy setup sheet.
 *
 * A FUNCTION RETURNING A SPEC, so the sheet stack re-renders it from current
 * model state every time the stack returns to this level — which is what makes
 * the frozen presentation appear the moment activation succeeds, without this
 * module having to know it happened.
 *
 * @returns {{title: string, sub: string, body: string, onMount: Function}}
 */
export function economySheet() {
  const mode = economyMode();

  if (mode !== 'authoritative') {
    return {
      title: ECONOMY_TITLE,
      sub: 'Commissioner',
      body: '<div class="fs-econ__state" data-economy-state="unavailable">'
        + '<p>This league’s economy configuration could not be read for your '
        + 'session.</p></div>',
      onMount: () => {},
    };
  }

  const frozen = isFrozen();
  const body =
    (frozen ? frozenBanner() : '')
    + inputsBlock()
    + derivedBlock()
    + allocationBlock()
    + (isEditable()
      ? '<div class="fs-econ__error" id="fs-econ-error" role="alert"></div>'
        + '<div class="fs-econ__actions">'
        + '<button type="button" class="fs-econ__save" id="fs-econ-save">'
        + 'Save configuration</button>'
        + (canActivate()
          ? '<button type="button" class="fs-econ__activate" '
            + 'id="fs-econ-activate">Review &amp; activate season</button>'
          : '<p class="fs-econ__hint">Activation becomes available once the '
            + 'Season-Opening Allocation can be worked out.</p>')
        + '</div>'
      : '');

  return {
    title: ECONOMY_TITLE,
    sub: frozen ? 'Active season · locked' : 'Before activation',
    body,
    onMount: bindEconomySheet,
  };
}

/**
 * The activation confirmation — a deliberate, separate level.
 *
 * IT RESTATES WHAT WILL HAPPEN, IN FULL, before offering the control. The
 * figures are the ones just reviewed, so the commissioner confirms against the
 * same numbers they read rather than against a remembered version of them.
 *
 * @returns {{title: string, sub: string, body: string, onMount: Function}}
 */
export function activationSheet() {
  const perPlayer = perPlayerAllocationCents();
  const league = leagueAllocation();

  const figures = perPlayer === null ? '' : (
    '<div class="fs-econ__confirm-figures">'
    + '<div class="fs-econ__row"><span class="fs-econ__row-label">'
    + 'Issued to each GM</span><span class="fs-econ__row-value fs-money"'
    + `${exactCentsAttr(perPlayer)}>${escapeHtml(formatCredits(perPlayer))}`
    + '</span></div>'
    + (league
      ? '<div class="fs-econ__row"><span class="fs-econ__row-label">'
        + `Across ${escapeHtml(String(league.teams))} `
        + `team${league.teams === 1 ? '' : 's'}</span>`
        + `<span class="fs-econ__row-value fs-money"${exactCentsAttr(league.cents)}>`
        + `${escapeHtml(formatCredits(league.cents))}</span></div>`
      : '')
    + '</div>'
  );

  return {
    title: 'Activate the season',
    sub: 'This cannot be undone',
    body:
      '<div class="fs-econ__confirm" id="fs-econ-confirm">'
      + '<p class="fs-econ__confirm-body">Activating issues every GM their '
      + 'Season-Opening Allocation and locks this season’s economy. The Weekly '
      + 'Bet Minimum, Championship Pot Contribution and Skunk Fee cannot be '
      + 'changed afterwards.</p>'
      + figures
      + '<div class="fs-econ__error" id="fs-econ-confirm-error" role="alert">'
      + '</div>'
      + '<button type="button" class="fs-econ__confirm-go" '
      + 'id="fs-econ-confirm-go">Activate season</button>'
      + '<button type="button" class="fs-econ__confirm-back" data-fs-close>'
      + 'Not yet</button>'
      + '</div>',
    onMount: bindActivationSheet,
  };
}

/* ── Binding ────────────────────────────────────────────────────────────── */

/**
 * The shell installs the league and the refresh path; this module holds neither.
 * @type {{leagueId: number, onChanged: Function}|null}
 */
let HOOK = null;

/**
 * @param {{leagueId: number, onChanged: (config: object) => void}|null} hook
 */
export function setEconomyHook(hook) {
  HOOK = hook || null;
}

/**
 * @param {HTMLElement} host
 * @param {{push: Function, rerender: Function, pop: Function}} api
 */
function bindEconomySheet(host, api) {
  const save = host.querySelector('#fs-econ-save');
  const activate = host.querySelector('#fs-econ-activate');
  const error = host.querySelector('#fs-econ-error');
  let inFlight = false;

  if (save) {
    save.addEventListener('click', async () => {
      if (inFlight || !HOOK) return;
      error.textContent = '';

      const inputs = {};
      let invalid = false;
      for (const spec of ECONOMY_INPUTS) {
        const field = host.querySelector(`input[name="${spec.field}"]`);
        const cents = centsFromField(field ? field.value : '');
        if (!Number.isFinite(cents)) invalid = true;
        inputs[spec.key] = cents;
      }
      if (invalid) {
        error.textContent = 'Enter a whole number of Credits in each field.';
        return;
      }

      inFlight = true;
      save.disabled = true;
      save.textContent = 'Saving…';
      try {
        // NOT CLAMPED. The server owns every bound; a value outside them is
        // sent and its refusal is shown.
        const config = await saveEconomyConfig(HOOK.leagueId, inputs);
        HOOK.onChanged(config);
        api.rerender();
      } catch (refusal) {
        error.textContent = explainRefusal(refusal);
      } finally {
        inFlight = false;
        save.disabled = false;
        save.textContent = 'Save configuration';
      }
    });
  }

  if (activate) {
    // PUSHES A LEVEL — it does not activate. The only control that activates
    // is on the confirmation sheet, which is the whole point of §16.4.
    activate.addEventListener('click', () => { api.push(() => activationSheet()); });
  }
}

/**
 * @param {HTMLElement} host
 * @param {{pop: Function, rerender: Function}} api
 */
function bindActivationSheet(host, api) {
  const go = host.querySelector('#fs-econ-confirm-go');
  const error = host.querySelector('#fs-econ-confirm-error');
  if (!go) return;
  let inFlight = false;

  go.addEventListener('click', async () => {
    if (inFlight || !HOOK) return;
    error.textContent = '';
    inFlight = true;
    go.disabled = true;
    go.textContent = 'Activating…';
    try {
      await activateSeason(HOOK.leagueId);
      // THE CONFIG IS RE-READ RATHER THAN ASSUMED FROZEN. Activation freezes it
      // server-side, and reading the result back is how this surface learns
      // that rather than deciding it locally — the same rule every other
      // command in this app follows.
      await HOOK.onActivated();
      // Back to the setup level, which re-renders from the refreshed model and
      // therefore draws the frozen presentation.
      api.pop();
    } catch (refusal) {
      error.textContent = explainRefusal(refusal);
      inFlight = false;
      go.disabled = false;
      go.textContent = 'Activate season';
    }
  });
}

/**
 * Whether the economy entry should appear in the secondary menu at all.
 *
 * @returns {boolean}
 */
export function economyReachable() {
  return economyCapability();
}
