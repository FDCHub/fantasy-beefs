/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · commissioner lifecycle controls
 * WP4
 *
 * Three sections inside Rules & Settings, between league configuration and the
 * commissioner's reporting surfaces:
 *
 *     LEAGUE SETUP      · whether Yahoo's data supports the weekly Pool slate
 *     THE WEEKLY CYCLE  · open the week, open the Pools, settle them, close it
 *     THE SEASON        · close the season
 *
 * WHY IT SITS HERE AND NOT IN A SIXTH TAB. Rules & Settings is already the
 * league's operating manual and the commissioner's control surface — the tab a
 * commissioner opens to change how the league runs. A lifecycle tab would have
 * been a sixth destination for one role, and the locked Rev 4.2 navigation is
 * five.
 *
 * WHY BEFORE THE COMMISSIONER AREA. What follows this region is reporting —
 * Top-Off requests, twelve GM cards, the league roll-up. Those are things a
 * commissioner READS; these are the things they DO, and putting the week's
 * operations behind twelve ledger cards would make the routine act the hardest
 * one to reach. The locked internal order of the commissioner area itself is
 * untouched.
 *
 * NO IMPLEMENTATION VOCABULARY REACHES THE PAGE. A commissioner is told whether
 * Yahoo's data supports the weekly Pools; they are not told about definitions,
 * gates, activation measurements or the stat vocabulary underneath. Same for
 * refusals: `weekly_minimum_expiry` becomes "at least one week has not been
 * closed". The mapping lives in `lifecycle-command.js`, and the raw code is
 * never drawn.
 *
 * EVERY DISABLED CONTROL SAYS WHY, and every reason is the SERVER'S. Readiness
 * comes from `GET /league/{id}/lifecycle`, which calls the same gate the slate
 * builder draws from and the same preconditions the close orchestrator runs.
 * Nothing here re-derives a rule: a control drawn disabled is a courtesy so a
 * commissioner is not offered an action that would be refused, and the route
 * refuses it regardless of what this surface shows.
 * ========================================================================== */

import { escapeHtml, note, sectionHeading } from './components.js';
import {
  LIFECYCLE_MODE_AUTHORITATIVE,
  POOL_SUPPORT_INSUFFICIENT,
  POOL_SUPPORT_NOT_MEASURED,
  POOL_SUPPORT_READY,
  actionResult,
  isInFlight,
  lifecycleLeagueId,
  lifecycleMode,
  poolSupport,
  seasonLifecycle,
  weekLifecycle,
} from './lifecycle-model.js';

/** Locked headings for this region. */
export const LIFECYCLE_HEADING = 'LEAGUE LIFECYCLE';
export const SETUP_HEADING = 'LEAGUE SETUP';
export const WEEKLY_HEADING = 'THE WEEKLY CYCLE';
export const SEASON_HEADING = 'THE SEASON';

/** The section order, asserted by the suites rather than assumed. */
export const LIFECYCLE_SECTIONS = Object.freeze(['setup', 'week', 'season']);

/**
 * Whether the acting session holds commissioner authority for the active
 * league. Set by the shell from /auth/me. PRESENTATION ONLY — every route
 * re-derives authority from the credential before it writes.
 */
let COMMISSIONER_CAPABILITY = false;

/** @param {boolean} value */
export function setLifecycleCapability(value) {
  COMMISSIONER_CAPABILITY = Boolean(value);
}

/** @returns {boolean} */
export function lifecycleCapability() {
  return COMMISSIONER_CAPABILITY;
}

/* ── Pieces ─────────────────────────────────────────────────────────────── */

/**
 * One lifecycle control: a titled row with its action button.
 *
 * `disabledBecause` is a SENTENCE or null. A disabled control with no stated
 * reason is the failure mode this whole region exists to avoid — a commissioner
 * looking at a greyed button with no idea what would ungrey it.
 *
 * @param {{action: string, title: string, blurb: string, label: string,
 *          disabledBecause: string|null}} spec
 * @returns {string}
 */
function controlRow(spec) {
  const busy = isInFlight(spec.action);
  const disabled = busy || Boolean(spec.disabledBecause);

  return (
    `<div class="fs-lcrow" data-lifecycle-row="${escapeHtml(spec.action)}">` +
    '<div class="fs-lcrow__main">' +
    `<div class="fs-lcrow__title">${escapeHtml(spec.title)}</div>` +
    `<div class="fs-lcrow__blurb">${escapeHtml(spec.blurb)}</div>` +
    '</div>' +
    `<button type="button" class="fs-btn fs-btn--gold fs-lcrow__btn" ` +
    `data-lifecycle-action="${escapeHtml(spec.action)}"` +
    `${disabled ? ' disabled' : ''}` +
    `${busy ? ' aria-busy="true"' : ''}>` +
    `${escapeHtml(busy ? 'Working…' : spec.label)}</button>` +
    '</div>' +
    (spec.disabledBecause && !busy
      ? `<div class="fs-lcwhy" data-lifecycle-why="${escapeHtml(spec.action)}">` +
        `${escapeHtml(spec.disabledBecause)}</div>`
      : '') +
    resultLine(spec.action)
  );
}

/**
 * The outcome of the last attempt at one action.
 *
 * THREE TONES, NOT TWO. `waiting` is the state a correct action lands in when
 * the week's results are not final yet — it is neither a success nor a fault,
 * and colouring it as a failure would teach a commissioner to distrust a
 * message that is telling them the system is working.
 *
 * @param {string} action
 * @returns {string}
 */
function resultLine(action) {
  const result = actionResult(action);
  if (!result) return '';

  const tone = result.status === 'success' ? 'is-success'
    : result.status === 'waiting' ? 'is-waiting' : 'is-refused';

  return (
    `<div class="fs-lcresult ${tone}" data-lifecycle-result="${escapeHtml(action)}" ` +
    `data-status="${escapeHtml(result.status)}" role="status" aria-live="polite">` +
    `${escapeHtml(result.message)}</div>`
  );
}

/** A short state chip: the answer, before any control. */
function stateChip(label, value, variant) {
  return (
    `<div class="fs-lcstate is-${escapeHtml(variant)}" data-lifecycle-state>` +
    `<span class="fs-lcstate__label">${escapeHtml(label)}</span>` +
    `<span class="fs-lcstate__value">${escapeHtml(value)}</span>` +
    '</div>'
  );
}

/* ── A · League setup ───────────────────────────────────────────────────── */

/**
 * The three Pool support states, in the league's own language.
 *
 * NOT MEASURED is not "off" and INSUFFICIENT is not "broken". The first means
 * nobody has checked yet; the second means the check was made and Yahoo did not
 * report enough for a full weekly slate. Collapsing them would hide which one a
 * commissioner is actually in, and they call for different actions.
 */
const SUPPORT_COPY = Object.freeze({
  [POOL_SUPPORT_NOT_MEASURED]: {
    value: 'Not measured',
    variant: 'pending',
    blurb: 'Nobody has checked yet whether Yahoo reports enough for this '
      + 'league to run its weekly Pools.',
    label: 'Activate Pool Support',
  },
  [POOL_SUPPORT_INSUFFICIENT]: {
    value: 'Insufficient',
    variant: 'warn',
    blurb: 'Yahoo is not reporting enough for this league to fill a weekly '
      + 'Pool slate. Check again once your league’s scoring settings or the '
      + 'week’s data have changed.',
    label: 'Re-measure Pool Support',
  },
  [POOL_SUPPORT_READY]: {
    value: 'Ready',
    variant: 'ok',
    blurb: 'Yahoo reports enough for this league to run its weekly Pools.',
    label: 'Re-measure Pool Support',
  },
});

export function setupSection() {
  const support = poolSupport();
  const week = weekLifecycle();

  if (!support) return unavailableSection('setup', SETUP_HEADING,
    'Pool support for this league is not available to this session.');

  const copy = SUPPORT_COPY[support.state] || SUPPORT_COPY[POOL_SUPPORT_NOT_MEASURED];

  // THE ROUTE REQUIRES A WEEK, so a league whose current week is unknown cannot
  // be measured. Said plainly rather than sending a guessed week: a measurement
  // of the wrong week is a confident answer about the wrong thing.
  const disabledBecause = (week && week.week_resolved)
    ? null
    : 'The league’s current week is not known yet, so there is no week to '
      + 'check Yahoo’s data against.';

  return (
    '<section class="fs-comsec" data-lifecycle="setup">' +
    sectionHeading(SETUP_HEADING) +
    stateChip('Pool support', copy.value, copy.variant) +
    controlRow({
      action: 'pool-support',
      title: 'Pool support',
      blurb: copy.blurb,
      label: copy.label,
      disabledBecause,
    }) +
    '<div class="fs-note">Checking asks Yahoo what it reports for your league '
    + 'and records the answer. It moves no Credits and changes no result.</div>' +
    '</section>'
  );
}

/* ── B · The weekly cycle ───────────────────────────────────────────────── */

export function weekSection() {
  const week = weekLifecycle();
  if (!week) return unavailableSection('week', WEEKLY_HEADING,
    'The weekly cycle is not available to this session.');

  if (!week.week_resolved) {
    return (
      '<section class="fs-comsec" data-lifecycle="week" data-state="no-week">' +
      sectionHeading(WEEKLY_HEADING) +
      note('The league’s current week has not been read from Yahoo yet, so '
           + 'there is no week to operate. Nothing is offered here rather than '
           + 'a guessed week being acted on.', { pending: true }) +
      '</section>'
    );
  }

  const n = week.week;
  const rows = [
    {
      action: 'week-open',
      title: 'Week Open',
      blurb: `Release every GM’s weekly allowance for week ${n}.`,
      label: `Open week ${n}`,
      disabledBecause: !week.is_release_week
        ? `Week ${n} is not a regular-season week for this league, so there is `
          + 'no weekly allowance to release.'
        : week.opened
          ? `Week ${n} is already open — every GM’s allowance has been released.`
          : null,
    },
    {
      action: 'pool-collect',
      title: 'Open the week’s Pools',
      blurb: `Charge every GM the Standard Pool Bet and open week ${n}’s four `
        + 'Pools.',
      label: `Open week ${n} Pools`,
      disabledBecause: week.collected
        ? `Week ${n}’s Pools are already open — every GM was charged once.`
        : null,
    },
    {
      action: 'pool-settle',
      title: 'Settle the week’s Pools',
      blurb: `Work out who won week ${n}’s Pools from Yahoo’s final scores and `
        + 'pay them.',
      label: `Settle week ${n} Pools`,
      disabledBecause: !week.collected
        ? `Week ${n}’s Pools have not been opened yet, so there is nothing to `
          + 'settle.'
        : week.settled
          ? `Week ${n}’s Pools are settled.`
          : null,
    },
    {
      action: 'week-close',
      title: 'Week Close',
      blurb: `Take any unspent weekly allowance out of circulation for week ${n}.`,
      label: `Close week ${n}`,
      disabledBecause: week.closed
        ? `Week ${n} is already closed.`
        : null,
    },
  ];

  return (
    '<section class="fs-comsec" data-lifecycle="week" ' +
    `data-week="${escapeHtml(String(n))}">` +
    sectionHeading(WEEKLY_HEADING, `week ${n}`) +
    rows.map(controlRow).join('') +
    '<div class="fs-note">Run in order across the week: open it, open the '
    + 'Pools, settle them once Yahoo’s scores are final, then close it. '
    + 'Repeating any of them is safe — a second attempt does the same work '
    + 'once and charges nobody twice.</div>' +
    '</section>'
  );
}

/* ── C · The season ─────────────────────────────────────────────────────── */

/**
 * The translated sentence for the outstanding season-close prerequisite.
 *
 * Held in a module variable rather than imported into `seasonSection` from the
 * command module, so `lifecycle.js` keeps no dependency on the refusal table
 * and the suites can drive the section with a known sentence.
 * @type {string|null}
 */
let SEASON_BLOCKER = null;

/** @param {string|null} sentence */
export function setSeasonBlocker(sentence) {
  SEASON_BLOCKER = sentence || null;
}

export function seasonSection() {
  const season = seasonLifecycle();
  if (!season) return unavailableSection('season', SEASON_HEADING,
    'Season close is not available to this session.');

  if (season.closed) {
    return (
      '<section class="fs-comsec" data-lifecycle="season" data-state="closed">' +
      sectionHeading(SEASON_HEADING) +
      stateChip('Season', 'Closed', 'ok') +
      '<div class="fs-note">This season is closed. The championship pot has '
      + 'been paid out and every GM’s final position is settled. It cannot be '
      + 'reopened.</div>' +
      '</section>'
    );
  }

  // THE PREREQUISITE SENTENCE IS THE SERVER'S ANSWER, TRANSLATED — never a
  // rule this surface applied. `blocking_message` names which prerequisite is
  // outstanding; the mapping turns the engine's step name into a sentence.
  const blocked = !season.ready;

  return (
    '<section class="fs-comsec" data-lifecycle="season">' +
    sectionHeading(SEASON_HEADING) +
    stateChip('Season', blocked ? 'Not ready to close' : 'Ready to close',
              blocked ? 'warn' : 'ok') +
    controlRow({
      action: 'season-close',
      title: 'Season Close',
      blurb: 'Settle the season: pay out the championship, reconcile every '
        + 'GM’s position and close the books.',
      label: 'Close the season',
      disabledBecause: blocked
        ? (SEASON_BLOCKER || 'The season is not ready to close yet.')
        : null,
    }) +
    '<div class="fs-note">Season close happens once and cannot be undone. It '
    + 'stays unavailable until everything it depends on is finished, and the '
    + 'server checks that again when the button is pressed.</div>' +
    '</section>'
  );
}

/* ── Assembly ───────────────────────────────────────────────────────────── */

function unavailableSection(id, heading, message) {
  return (
    `<section class="fs-comsec" data-lifecycle="${escapeHtml(id)}" ` +
    'data-state="unavailable">' +
    sectionHeading(heading) +
    note(message, { pending: true }) +
    '</section>'
  );
}

/**
 * The whole lifecycle region.
 *
 * A NON-COMMISSIONER GETS NO CONTROLS AT ALL — not disabled ones. A greyed
 * "Close the season" on an ordinary GM's settings page invites them to wonder
 * what they are missing, and there is nothing here for them to do. The region
 * still renders, and still says who operates it, because a blank space would
 * read as a fault. THE HIDING IS NOT THE SECURITY: every route resolves league
 * commissioner authority from the credential and refuses regardless.
 *
 * @returns {string}
 */
export function lifecycleArea() {
  const leagueId = lifecycleLeagueId();
  // `data-league` is what makes active-league isolation OBSERVABLE. Every
  // figure and every message in this region belongs to the league named here,
  // and the suites assert the pair rather than trusting that they match.
  const leagueAttr = leagueId === null ? '' : ` data-league="${escapeHtml(String(leagueId))}"`;

  if (!COMMISSIONER_CAPABILITY) {
    return (
      `<section class="fs-lifecycle" id="fs-lifecycle"${leagueAttr} ` +
      'data-state="not-commissioner">' +
      `<div class="fs-lifecycle__head">${escapeHtml(LIFECYCLE_HEADING)}</div>` +
      note('Your league’s commissioner opens and closes each week, opens and '
           + 'settles the weekly Pools, and closes the season. Your session '
           + 'does not hold commissioner authority for this league.') +
      '</section>'
    );
  }

  if (lifecycleMode() !== LIFECYCLE_MODE_AUTHORITATIVE) {
    return (
      `<section class="fs-lifecycle" id="fs-lifecycle"${leagueAttr} ` +
      `data-state="${escapeHtml(lifecycleMode())}">` +
      `<div class="fs-lifecycle__head">${escapeHtml(LIFECYCLE_HEADING)}</div>` +
      note('The league’s lifecycle state could not be read for this session. '
           + 'No control is offered rather than one being offered against a '
           + 'state nobody knows.', { pending: true }) +
      '</section>'
    );
  }

  return (
    `<section class="fs-lifecycle" id="fs-lifecycle"${leagueAttr} ` +
    'data-state="authoritative">' +
    `<div class="fs-lifecycle__head">${escapeHtml(LIFECYCLE_HEADING)}</div>` +
    setupSection() +
    weekSection() +
    seasonSection() +
    '</section>'
  );
}

/* ── Binding ────────────────────────────────────────────────────────────── */

/**
 * The command hook, installed by the shell.
 *
 * Left null in demo mode and for a signed-out page, which is what leaves the
 * controls inert rather than reaching for a league that is not there.
 * @type {((action: string) => void)|null}
 */
let DISPATCH = null;

/** @param {((action: string) => void)|null} fn */
export function setLifecycleDispatch(fn) {
  DISPATCH = typeof fn === 'function' ? fn : null;
}

/**
 * Bind the lifecycle controls.
 *
 * ONE DELEGATED HANDLER, and it does not read `disabled` to decide. The
 * duplicate-click guard is `claimAction` inside the dispatch, because a
 * disabled attribute is presentation: two clicks in the same frame both see an
 * enabled button, and the second would be sent.
 *
 * @param {HTMLElement} panel
 */
export function bindLifecycle(panel) {
  panel.querySelectorAll('[data-lifecycle-action]').forEach((el) => {
    el.addEventListener('click', () => {
      if (!DISPATCH) return;
      DISPATCH(el.dataset.lifecycleAction);
    });
  });
}