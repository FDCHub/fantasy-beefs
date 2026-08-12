/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · application shell wiring
 * Sprint 7 Packages 1–4
 *
 * The shell renders the five primary destinations, binds the persistent bottom
 * navigation, and owns the single shared pop-out. Each tab module builds and
 * binds its own panel.
 *
 * The pop-out is a STACK. Opening the Matchup Preview from inside the composer
 * pushes a level rather than replacing one, so closing the preview returns to
 * a composer that still holds the market, mode and stake the GM entered. The
 * close X always dismisses the ACTIVE sheet: one level up if there is one,
 * otherwise the overlay itself.
 *
 * SPRINT 8 PACKAGE 1 — THE SHELL NOW HAS TWO STATES, AND THE SERVER PICKS.
 * Mounting asks `/auth/me` who is acting. A signed-in answer mounts the
 * application; anything else mounts the sign-in gate. Both transitions run
 * through ONE subscription to the session module, so an expiry noticed
 * mid-request lands the GM on the gate by the same path a deliberate sign-out
 * does — there is no second way to change what the shell is showing, and
 * therefore no path that can get it wrong.
 *
 * Nothing in this file reads, derives, or writes protocol state. Identity is
 * not an exception: it is READ from the server and rendered, never decided
 * here, and the tab modules still draw their Sprint 7 illustrative view models
 * until the binding packages replace them.
 * ========================================================================== */

import {
  DEFAULT_DESTINATION_ID,
  NAV_DESTINATIONS,
  destinationById,
  selectDestination,
} from './nav.js';

import { escapeHtml, sheet } from './components.js';

import { ILLUSTRATIVE, MASTHEAD } from './demo-state.js';
import { bindLeague, buildLeaguePanel } from './league.js';
import { bindAction, buildActionPanel, setRespondHook } from './action.js';
// ALIASED, because `action.js` already exports a `bindAction` that wires the
// PANEL while this one binds the DATA. Importing both under one name is a
// syntax error, and the near-miss is exactly how the Ledger pair broke in P4B.
import {
  bindLeagueContext, bindWeekMatchups, currentWeek, markLeagueUnavailable,
  unbindLeague,
} from './league-model.js';
import {
  bindAction as bindActionModel,
  markActionUnavailable,
  unbindAction as unbindActionModel,
} from './action-model.js';
import { bindWeek, buildWeekPanel } from './week.js';
import { bindLedger, buildLedgerPanel } from './ledger.js';
import { bindRules, buildRulesPanel } from './rules.js';
import {
  beginSession, composerSheet, endSession, setIssueHook,
} from './composer.js';
import {
  ActionCommandError,
  acceptChallenge, counterChallenge, declineChallenge,
  explainRefusal as explainActionRefusal, issueChallenge, readActionState,
} from './action-command.js';
import { bindGate, bindIdentityBlock, buildGate, buildIdentityBlock } from './auth-view.js';
import {
  currentIdentity, isAuthenticated, onIdentityChange, refreshIdentity,
} from './session.js';
import { clearProductionData, loadProductionData, productionData } from './production-data.js';
// Aliased: `bindLedger` above is the Ledger PANEL's event binder; these are the
// MODEL's data binders. Two different jobs that wanted the same name.
import {
  bindLedger as bindLedgerModel,
  markLedgerUnavailable,
  unbindLedger as unbindLedgerModel,
} from './ledger-model.js';
import {
  bindCommissioner, markCommissionerUnavailable, unbindCommissioner,
} from './commissioner-model.js';
import {
  bindSettings, markSettingsUnavailable, unbindSettings,
} from './settings-model.js';
import {
  bindSlate, markSlateUnavailable, setSlateEntryCents, unbindSlate,
} from './pool-slate-model.js';
import {
  bindSkunk, markSkunkUnavailable, unbindSkunk,
} from './skunk-model.js';
import { bindPoolEntryForm, setCommissionerCapability, setSettingSheetMount } from './rules.js';
import {
  setLifecycleCapability, setLifecycleDispatch, setSeasonBlocker,
} from './lifecycle.js';
import {
  applyLeague as applyLifecycleLeague,
  bindLifecycle as bindLifecycleModel,
  claimAction,
  markLifecycleUnavailable,
  recordResult,
  releaseAction,
  seasonLifecycle,
  unbindLifecycle,
  weekLifecycle,
} from './lifecycle-model.js';
import {
  activatePoolSupport, closeSeason, closeWeek, collectPools,
  explainPrerequisite, explainRefusal as explainLifecycleRefusal,
  isWaitingState, openWeek, readLifecycle, settlePools,
} from './lifecycle-command.js';

/* ── Masthead ───────────────────────────────────────────────────────────── */

function renderMasthead(root) {
  // Each half of the tagline is held unbreakable, so a narrow viewport wraps at
  // the middot rather than mid-phrase — the same rule the POR applies to the
  // league identity.
  const tagline = MASTHEAD.tagline
    .split(' · ')
    .map((phrase) => `<span class="fs-nowrap">${escapeHtml(phrase)}</span>`)
    .join(' · ');

  // WHERE THE IDENTITY GOES, AND WHY IT IS INSIDE THE META COLUMN.
  //
  // The masthead is a two-item row: a shrinkable lockup and a fixed-width meta
  // column. Adding the identity as a THIRD item was measurably wrong — it took
  // 122px from the lockup, which forced the tagline from its certified two
  // lines onto three, grew the masthead by 15px, and cost the panel enough
  // height that every wager card on the League tab clipped its own content at
  // 375x667. That is not a styling nit; it is the precise failure the Sprint 7
  // geometry suite exists to catch, and it caught it.
  //
  // Stacking it under the revision and author lines costs nothing, because the
  // masthead's height is set by the taller of the two columns and that is the
  // lockup (56px) not the meta column (30px). A third meta line stays inside
  // that. The identity is right-aligned with the lines above it, the locked
  // Rev4.2 grammar is untouched, and it renders as nothing at all when no one
  // is signed in.
  root.innerHTML =
    '<div class="fs-mast__lockup">' +
    '<div class="fs-mast__word">' +
    '<span class="fs-word-a">Fantasy</span><span class="fs-word-b">Stakes</span>' +
    '</div>' +
    `<div class="fs-mast__tagline">${tagline}</div>` +
    '</div>' +
    '<div class="fs-mast__meta">' +
    `${escapeHtml(MASTHEAD.revision)}<br>${escapeHtml(MASTHEAD.author)}` +
    buildIdentityBlock() +
    '</div>';

  bindIdentityBlock(root);
}

/* ── Bottom navigation ──────────────────────────────────────────────────── */

function renderTabBar(root) {
  root.innerHTML = NAV_DESTINATIONS.map((d) => (
    `<button type="button" class="fs-tabbar__item" role="tab" ` +
    `id="fs-tab-${escapeHtml(d.id)}" data-destination="${escapeHtml(d.id)}" ` +
    `aria-controls="${escapeHtml(d.panelId)}" aria-selected="false">` +
    '<svg class="fs-tabbar__icon" viewBox="0 0 18 18" fill="none" ' +
    'stroke="currentColor" stroke-width="1.4" stroke-linecap="round" ' +
    `stroke-linejoin="round" aria-hidden="true" focusable="false">${d.icon}</svg>` +
    `<span class="fs-tabbar__label">${escapeHtml(d.label)}</span>` +
    '</button>'
  )).join('');
}

/* ── Panels ─────────────────────────────────────────────────────────────── */

function renderPanelHosts(root) {
  root.innerHTML = NAV_DESTINATIONS.map((d) => (
    `<section class="fs-panel" id="${escapeHtml(d.panelId)}" role="tabpanel" ` +
    `aria-labelledby="fs-tab-${escapeHtml(d.id)}" data-destination="${escapeHtml(d.id)}"></section>`
  )).join('');
}

/**
 * Content for each destination. All five are built by their own modules; this
 * function is the routing table and holds no markup of its own.
 *
 * @param {string} destinationId
 * @returns {string}
 */
export function buildPanelContent(destinationId) {
  if (destinationId === 'league') return buildLeaguePanel();
  if (destinationId === 'action') return buildActionPanel();
  if (destinationId === 'week') return buildWeekPanel();
  if (destinationId === 'ledger') return buildLedgerPanel();
  if (destinationId === 'rules') return buildRulesPanel();

  throw new Error(`no panel content defined for "${destinationId}"`);
}

/**
 * Ask for a counter stake, in exact cents.
 *
 * `window.prompt` deliberately: a counter is a stake entry the approved Rev 4.2
 * Response Card composition does not include a field for, and inventing one
 * would be a product change this package does not own. The value is parsed
 * strictly and sent unclamped — the server owns every bound, and a client that
 * quietly adjusted the number would report success for a stake the GM did not
 * choose.
 *
 * @param {object} card
 * @returns {Promise<number|null>} exact cents, or null if cancelled
 */
async function promptCounterStake(card) {
  const raw = window.prompt(
    `Counter ${card.opponent} with what stake, in Credits?`, '');
  if (raw === null) return null;
  const trimmed = String(raw).trim();
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) {
    throw new ActionCommandError(400, 'invalid_stake',
      'Enter a stake like 25 or 25.50.');
  }
  return Math.round(Number(trimmed) * 100);
}

/**
 * Redraw the Action panel from current model state.
 *
 * ONLY THE ACTION PANEL. A command changes what Action shows; re-mounting the
 * whole application would also tear down the sheet stack the GM is standing in
 * and lose their place. The Ledger figures a wager moves arrive on the next
 * full load — Ledger is never written locally, which is the rule that keeps
 * accounting single-sourced.
 */
function redrawActionPanel() {
  const panel = document.getElementById('panel-action');
  if (!panel) return;
  panel.innerHTML = buildPanelContent('action');
  bindAction(panel, { openSheet });
}

/**
 * Redraw Rules & Settings from current model state.
 *
 * ONLY THIS PANEL, for the same reason `redrawActionPanel` redraws only its
 * own: a lifecycle command changes what Rules & Settings shows, and remounting
 * the application would tear down whatever sheet the commissioner is standing
 * in. Rebuilding also REBINDS, which is what keeps the freshly drawn controls
 * live after every redraw.
 */
function redrawRulesPanel() {
  const panel = document.getElementById('panel-rules');
  if (!panel) return;
  panel.innerHTML = buildPanelContent('rules');
  bindRules(panel, { openSheet });
}

/* ── Pop-out / bottom sheet ─────────────────────────────────────────────── */

/**
 * Renderers, innermost last. Each is a function returning a sheet spec, so a
 * level re-renders from current state whenever the stack returns to it.
 * @type {Array<() => {title?: string, sub?: string, body?: string, onMount?: Function}>}
 */
const sheetStack = [];

let lastFocusedBeforeSheet = null;

const sheetApi = {
  push: pushSheet,
  pop: popSheet,
  close: closeSheet,
  rerender: renderTopSheet,
};

function renderTopSheet() {
  const overlay = document.getElementById('fs-overlay');
  const host = document.getElementById('fs-sheet');
  if (!overlay || !host || sheetStack.length === 0) return;

  const spec = sheetStack[sheetStack.length - 1]();
  host.innerHTML = sheet(spec);
  host.scrollTop = 0;
  overlay.classList.add('is-open');
  overlay.setAttribute('aria-hidden', 'false');

  if (typeof spec.onMount === 'function') spec.onMount(host, sheetApi);

  const closeBtn = host.querySelector('[data-fs-close]');
  if (closeBtn) closeBtn.focus();
}

/**
 * Push a level onto the sheet stack.
 *
 * @param {(() => object)|object} renderer a spec, or a function returning one
 */
export function pushSheet(renderer) {
  const fn = typeof renderer === 'function' ? renderer : () => renderer;
  if (sheetStack.length === 0) lastFocusedBeforeSheet = document.activeElement;
  sheetStack.push(fn);
  renderTopSheet();
}

/** Dismiss the active level, revealing the one beneath or closing the sheet. */
export function popSheet() {
  sheetStack.pop();
  if (sheetStack.length === 0) closeSheet();
  else renderTopSheet();
}

/**
 * Open a single-level sheet, replacing anything already open.
 *
 * @param {(() => object)|object} spec
 */
export function openSheet(spec) {
  sheetStack.length = 0;
  pushSheet(spec);
}

/** Close the sheet entirely and discard any composer session. */
export function closeSheet() {
  const overlay = document.getElementById('fs-overlay');
  sheetStack.length = 0;
  endSession();
  if (!overlay) return;
  overlay.classList.remove('is-open');
  overlay.setAttribute('aria-hidden', 'true');
  if (lastFocusedBeforeSheet && lastFocusedBeforeSheet.focus) lastFocusedBeforeSheet.focus();
  lastFocusedBeforeSheet = null;
}

/**
 * Open the unified Versus composer.
 *
 * @param {{matchupId: string, marketId?: string|null}} spec
 */
export function openComposer(spec) {
  beginSession({
    matchupId: spec.matchupId,
    marketId: spec.marketId ?? null,
    // THE STAKE CEILING THE COMPOSER VALIDATES AGAINST, from the bound Ledger
    // when there is one. The illustrative figure is a fixture number and would
    // let a production GM compose a stake their wallet cannot cover — the
    // server refuses it either way, but being told after sending is worse than
    // being told while typing.
    availableCents: boundAvailableCents() ?? ILLUSTRATIVE.availableCents,
    // THE AUTHORITATIVE TARGET LIST, handed to the composer whole.
    //
    // S8-P4C-2R REMOVED THE NAME BRIDGE that used to stand here. It took the
    // illustrative League matchup's DISPLAY NAME, matched it against the served
    // opponents, and used the result as the target of a real Credits command.
    // Two teams sharing a name, a renamed team, or a fixture that simply
    // drifted from production would have addressed the wrong GM's money — and
    // nothing on the page would have looked wrong while it happened.
    //
    // The composer now asks instead. That is one more tap than the locked flow,
    // and it is the smallest honest option while the League tab is still
    // illustrative: its cards carry no authoritative id to hand over, so there
    // is nothing to pass through except a name, and a name is not authority.
    opponents: authoritativeOpponents(),
    actingTeamName: actingTeamName(),
  });
  openSheet(() => composerSheet());
}

/**
 * The acting GM's spendable Credits, when the Ledger is bound.
 * @returns {number|null}
 */
function boundAvailableCents() {
  const data = productionData();
  if (!data || !data.ledger) return null;
  const cents = data.ledger.available_cents;
  return Number.isInteger(cents) ? cents : null;
}

/**
 * The authoritative current week, or null when none is bound.
 *
 * Reads the league model rather than a constant, so there is exactly one
 * answer to "what week is it" in the production shell.
 *
 * @returns {number|null}
 */
function authoritativeWeek() {
  return currentWeek();
}

/**
 * The acting GM's own team name, as the server names it.
 * @returns {string|null}
 */
function actingTeamName() {
  const identity = currentIdentity();
  const caps = (identity && identity.capabilities) || {};
  return caps.acting_context_ambiguous ? null : (caps.acting_team_name || null);
}

/**
 * The league's other teams, exactly as the server named them.
 *
 * Empty when nothing is bound, which leaves the composer with no authoritative
 * target and therefore no live send — the honest state for a page that could
 * not read who is in the league.
 *
 * @returns {Array<{team_id: number, team_name: string, owner: string}>}
 */
function authoritativeOpponents() {
  const data = productionData();
  if (!data || !data.action || !Array.isArray(data.action.opponents)) return [];
  return data.action.opponents;
}

function bindSheet() {
  const overlay = document.getElementById('fs-overlay');
  if (!overlay) return;

  // Scrim tap dismisses the active level; a tap inside the sheet does not.
  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) popSheet();
  });

  // One delegated handler serves every close control, present and future.
  overlay.addEventListener('click', (event) => {
    if (event.target.closest && event.target.closest('[data-fs-close]')) popSheet();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && overlay.classList.contains('is-open')) popSheet();
  });
}

/* ── Navigation binding ─────────────────────────────────────────────────── */

/**
 * Activate a destination: bottom-nav state and panel visibility move together.
 *
 * @param {string} destinationId
 */
export function goTo(destinationId) {
  const next = selectDestination(destinationId);

  next.forEach((d) => {
    const tab = document.querySelector(`.fs-tabbar__item[data-destination="${d.id}"]`);
    if (tab) {
      tab.classList.toggle('is-active', d.active);
      tab.setAttribute('aria-selected', d.active ? 'true' : 'false');
    }
    const panel = document.getElementById(d.panelId);
    if (panel) panel.classList.toggle('is-active', d.active);
  });

  // A destination change is a context change: the sheet does not survive it.
  closeSheet();
}

function bindNavigation() {
  const bar = document.getElementById('fs-tabbar');
  if (!bar) return;
  bar.addEventListener('click', (event) => {
    const item = event.target.closest('.fs-tabbar__item');
    if (item && item.dataset.destination) goTo(item.dataset.destination);
  });
}

/* ── Interactions defined by the POR ────────────────────────────────────── */

/* ── Authoritative data (S8-P4B-2) ──────────────────────────────────────── */

/**
 * The league this session acts in, from the server's own answer.
 *
 * NO FALLBACK, DELIBERATELY. An earlier attempt defaulted to League 1 when
 * /auth/me did not publish a league. P2's rule is that the real league being
 * acted upon must be identified authoritatively, and that applies to reads as
 * much as to writes. /auth/me now derives `acting_league_id` from the user's
 * own team row, so there is a real answer to read — and `null` is also a real
 * answer, meaning this account has no acting context. Guessing League 1 would
 * have shown someone a stranger's money.
 *
 * @returns {number|null}
 */
export function currentLeagueId() {
  const identity = currentIdentity();
  if (!identity || !identity.capabilities) return null;
  const caps = identity.capabilities;
  if (caps.acting_context_ambiguous) return null;
  return typeof caps.acting_league_id === 'number' ? caps.acting_league_id : null;
}

/**
 * Load the authoritative slices and put every model into a DEFINITE mode.
 *
 * THE INVARIANT: after this returns, no model is in demo mode. Each is either
 * bound to a real read or explicitly marked unavailable. That is what stops a
 * refused or failed request from revealing the prototype's money underneath —
 * there is no "unbound" state left to fall through to.
 *
 * A commissioner read returning 403 is an EXPECTED CAPABILITY STATE for an
 * ordinary GM, not a failure, and lands in the same unavailable mode as a
 * transport error. The GM's own Ledger is unaffected either way.
 */
async function bindAuthoritativeData() {
  const leagueId = currentLeagueId();

  // THE ACTIVE LEAGUE IS APPLIED FIRST, BEFORE ANYTHING IS READ. `applyLeague`
  // drops the previous league's lifecycle state and every recorded success or
  // refusal the moment the id differs, so there is no window in which the new
  // league's heading sits above the old league's answers. Doing it after the
  // load would leave exactly that window open for the length of a round trip.
  applyLifecycleLeague(leagueId);

  if (leagueId === null) {
    markLedgerUnavailable();
    markCommissionerUnavailable();
    markActionUnavailable();
    markSkunkUnavailable();
    markLifecycleUnavailable(null);
    setLifecycleCapability(false);
    setLifecycleDispatch(null);
    setSeasonBlocker(null);
    return;
  }

  try {
    // NO WEEK IS PASSED. The loader reads the league context first and takes
    // the provider's own current week from it. The shell used to hand in
    // `CURRENT_WEEK` — an illustrative constant — which made every week-scoped
    // production read ask for week 5 regardless of the real week.
    await loadProductionData({ leagueId });
  } catch {
    markLedgerUnavailable();
    markCommissionerUnavailable();
    markActionUnavailable();
    markSkunkUnavailable();
    markLifecycleUnavailable(leagueId);
    setLifecycleDispatch(null);
    setSeasonBlocker(null);
    return;
  }

  const data = productionData();

  if (data && data.ledger) bindLedgerModel(data.ledger, data.settings);
  else markLedgerUnavailable();

  if (data && data.positions) bindCommissioner(data.positions, data.reconciliation);
  else markCommissionerUnavailable();

  if (data && data.settings) bindSettings(data.settings);
  else markSettingsUnavailable();

  // The Entry a Pool card shows is the league's Standard Pool Bet, which lives
  // in settings rather than in the draw — so it is supplied before the slate
  // binds, from the same authoritative read the Settings tab uses.
  if (data && data.settings) setSlateEntryCents(data.settings.pool_entry.cents);

  if (data && data.slate) bindSlate(data.slate);
  else markSlateUnavailable();

  // WP6A — the week's Skunk. An UNASSESSED week is a successful read carrying
  // `assessed: false`, which the model reports as "no callout" rather than as a
  // failure; only a refused or failed read is unavailable.
  if (data && data.skunk) bindSkunk(data.skunk);
  else markSkunkUnavailable();

  // AN EMPTY ACTION TAB IS STILL A BOUND ONE. The read returns four empty
  // sections for a GM with no wagers, which is an answer; only a failed or
  // refused read is unavailable. Testing the body rather than its contents is
  // what keeps those two apart.
  if (data && data.action) bindActionModel(data.action);
  else markActionUnavailable();

  // LEAGUE CONTEXT, and the week every other surface is scoped to.
  if (data && data.context) bindLeagueContext(data.context);
  else markLeagueUnavailable();

  // The provider-backed matchups for that week, when there is a week.
  if (data && data.week !== null && data.weekMatchups) {
    bindWeekMatchups(data.week, data.weekMatchups);
  }

  // ── The live Action commands ──────────────────────────────────────────
  //
  // INSTALLED ONLY WHEN THE READ BOUND. If the Action state is unavailable the
  // hooks stay null and the surfaces draw no controls: a GM whose state could
  // not be read must not be offered an Accept button, because neither they nor
  // the page knows what they would be accepting.
  const identity = currentIdentity();
  const caps = (identity && identity.capabilities) || {};
  const actingTeamId = (!caps.acting_context_ambiguous
    && typeof caps.acting_team_id === 'number') ? caps.acting_team_id : null;

  if (data && data.action && actingTeamId !== null) {
    const refreshAction = async () => {
      // ONE WAY TO LEARN WHAT IS TRUE. Every command ends here, and so does a
      // plain page load — a second refresh path is a second chance to disagree.
      try {
        bindActionModel(await readActionState(leagueId));
      } catch {
        markActionUnavailable();
      }
      redrawActionPanel();
    };

    setIssueHook({
      leagueId,
      actingTeamId,
      // THE AUTHORITATIVE WEEK, or null. A composer that cannot name the week
      // cannot issue: the route requires one, and guessing it would post a real
      // wager into the wrong week.
      week: authoritativeWeek(),
      issue: issueChallenge,
      refresh: refreshAction,
      explain: explainActionRefusal,
    });
    setRespondHook({
      accept: acceptChallenge,
      decline: declineChallenge,
      counter: counterChallenge,
      refresh: refreshAction,
      explain: explainActionRefusal,
      promptStake: promptCounterStake,
    });
  } else {
    setIssueHook(null);
    setRespondHook(null);
  }

  // Presentation capability, from the server's own answer. It decides what is
  // DRAWN; the command is refused server-side regardless.
  const holdsCommission = Array.isArray(caps.commissioner_league_ids)
    && caps.commissioner_league_ids.includes(leagueId);
  setCommissionerCapability(holdsCommission);

  // ── The commissioner lifecycle (WP4) ──────────────────────────────────
  //
  // BOUND ONLY FOR A COMMISSIONER OF THIS LEAGUE. The read is refused for
  // anyone else by design, and asking anyway would put a 403 in the operator's
  // log on every ordinary GM's page load — noise that hides real refusals,
  // which is the same reason the positions read is asked for conditionally.
  setLifecycleCapability(holdsCommission);

  if (holdsCommission && data && data.lifecycle) {
    bindLifecycleModel(leagueId, data.lifecycle);
  } else {
    markLifecycleUnavailable(leagueId);
  }
  applySeasonBlocker();

  setLifecycleDispatch(holdsCommission
    ? (action) => { dispatchLifecycle(leagueId, action); }
    : null);

  // The settings sheet needs a league to write to and a way to re-render after
  // a save. Both are the shell's to know, so the hook is installed here rather
  // than reached for from inside the sheet.
  setSettingSheetMount((host, api) => {
    bindPoolEntryForm(host, {
      leagueId,
      onSaved: (settings) => {
        // The command returns the whole settings body, so this IS the
        // authoritative refresh — no second read to fall out of step with.
        bindSettings(settings);
        api.rerender();
        mountApplication();
      },
    });
  });
}

/* ── The commissioner lifecycle (WP4) ───────────────────────────────────── */

/**
 * Publish the outstanding season-close prerequisite as a sentence.
 *
 * The SERVER decided that the season is not ready and named which prerequisite
 * is outstanding; this only turns its step name into product language. The raw
 * code never reaches the page.
 */
function applySeasonBlocker() {
  const season = seasonLifecycle();
  setSeasonBlocker(season && !season.ready
    ? explainPrerequisite(season.blocking_reason_code)
    : null);
}

/**
 * Re-read the lifecycle and redraw Rules & Settings.
 *
 * ONE WAY TO LEARN WHAT IS TRUE, exactly as the Action panel has: every command
 * ends here and so does a plain page load, because a second refresh path is a
 * second chance to disagree with the server about what just happened.
 *
 * @param {number} leagueId
 */
async function refreshLifecycle(leagueId) {
  try {
    // `bindLifecycle` ignores a body whose league is no longer the active one,
    // so a reply that lands after a switch cannot repaint the old league's
    // state under the new league's heading.
    bindLifecycleModel(leagueId, await readLifecycle(leagueId));
  } catch {
    markLifecycleUnavailable(leagueId);
  }
  applySeasonBlocker();
  redrawRulesPanel();
}

/**
 * What a successful lifecycle call actually did, in the league's language.
 *
 * READ OFF THE ROUTE'S OWN RETURN VALUE, never assumed from the fact that it
 * returned 200. `already_open`, `already_closed`, `replayed` and `all_settled`
 * are each the difference between "this call did the work" and "the work was
 * already done" — and a commissioner who pressed a button is entitled to know
 * which of those happened.
 *
 * @param {string} action
 * @param {object} body
 * @param {number|null} week
 * @returns {string}
 */
function describeSuccess(action, body, week) {
  const w = week === null || week === undefined ? 'this week' : `week ${week}`;

  if (action === 'pool-support') {
    return body.sufficient_for_slate
      ? 'Checked. Yahoo reports enough for this league to run its weekly Pools.'
      : 'Checked. Yahoo is not reporting enough for a full weekly Pool slate '
        + 'yet, so the weekly Pools cannot run.';
  }
  if (action === 'week-open') {
    return body.already_open
      ? `${capitalise(w)} was already open. Nothing was released twice.`
      : `${capitalise(w)} is open — every GM’s weekly allowance has been `
        + 'released.';
  }
  if (action === 'pool-collect') {
    return `${capitalise(w)}’s Pools are open. ${body.teams_charged} GM`
      + `${body.teams_charged === 1 ? '' : 's'} paid the entry.`;
  }
  if (action === 'pool-settle') {
    return body.all_settled
      ? `${capitalise(w)}’s Pools are settled and paid out.`
      : `${body.settled.length} of ${w}’s Pools settled. The rest could not be `
        + 'settled yet.';
  }
  if (action === 'week-close') {
    return body.already_closed
      ? `${capitalise(w)} was already closed.`
      : `${capitalise(w)} is closed. Any unspent allowance has left `
        + 'circulation.';
  }
  if (action === 'season-close') {
    return body.replayed
      ? 'The season was already closed. Nothing was paid out again.'
      : 'The season is closed. The championship has been paid out and every '
        + 'GM’s final position is settled.';
  }
  return 'Done.';
}

/** @param {string} text @returns {string} */
function capitalise(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * Send one lifecycle command.
 *
 * THE DUPLICATE-CLICK GUARD IS `claimAction`, NOT THE DISABLED ATTRIBUTE. Two
 * clicks dispatched in the same frame both see an enabled button, so the second
 * would be sent if the DOM were the guard. `claimAction` returns false for the
 * second caller and the request never leaves the browser. The routes are safe
 * to repeat regardless — every one of them is idempotent by construction — but
 * "the server would have coped" is not a reason to send a command twice.
 *
 * THE LEAGUE IS CAPTURED, NOT RE-READ. `leagueId` is the league the command was
 * sent for, and it is what the result is recorded against; if the active league
 * changed while the request was in flight, `recordResult` drops the reply
 * rather than showing one league's outcome under another's heading.
 *
 * @param {number} leagueId
 * @param {string} action
 */
async function dispatchLifecycle(leagueId, action) {
  if (!claimAction(action)) return;

  // Drawn busy immediately, so the control is visibly out of service for the
  // length of the round trip rather than looking untouched.
  redrawRulesPanel();

  const week = weekLifecycle() ? weekLifecycle().week : null;

  try {
    const body = await runLifecycleAction(leagueId, action, week);
    recordResult(leagueId, action, {
      status: 'success',
      message: describeSuccess(action, body, week),
    });
  } catch (error) {
    // RESULTS_NOT_READY IS NOT A FAULT. It is the ordinary state of a week
    // whose games are still being played, and it is recorded as `waiting` so
    // the surface draws it as a normal "not yet" rather than as a server error.
    recordResult(leagueId, action, {
      status: isWaitingState(error) ? 'waiting' : 'refused',
      message: explainLifecycleRefusal(error),
    });
  } finally {
    releaseAction(action);
  }

  await refreshLifecycle(leagueId);
}

/**
 * The six governed routes, named once.
 *
 * @param {number} leagueId
 * @param {string} action
 * @param {number|null} week
 * @returns {Promise<object>}
 */
function runLifecycleAction(leagueId, action, week) {
  if (action === 'pool-support') return activatePoolSupport(leagueId, week);
  if (action === 'week-open') return openWeek(leagueId, week);
  if (action === 'pool-collect') return collectPools(leagueId, week);
  if (action === 'pool-settle') return settlePools(leagueId, week);
  if (action === 'week-close') return closeWeek(leagueId, week);
  if (action === 'season-close') return closeSeason(leagueId);
  return Promise.reject(new Error(`unknown lifecycle action "${action}"`));
}

/**
 * Make another league the active one.
 *
 * THE PRODUCT SEAM FOR A LEAGUE SWITCH. There is no switcher control in the
 * locked Rev 4.2 navigation, and WP4 adds none — but the lifecycle is scoped to
 * one league, so the switch has to be a real operation rather than an
 * assumption that a session only ever has one. Everything the previous league
 * produced is dropped before the new league is read, and the panel is redrawn
 * from the new state.
 *
 * @param {number|null} leagueId
 * @returns {Promise<void>}
 */
export async function switchLeague(leagueId) {
  // Stale state goes FIRST, so a slow or refused read cannot leave the previous
  // league's success banner sitting under the new league's name.
  applyLifecycleLeague(leagueId);
  setSeasonBlocker(null);
  redrawRulesPanel();

  if (leagueId === null) {
    setLifecycleDispatch(null);
    return;
  }

  setLifecycleDispatch((action) => { dispatchLifecycle(leagueId, action); });
  await refreshLifecycle(leagueId);
}

/**
 * Drop every authoritative figure and return the models to demo.
 *
 * Sign-out must leave no trace of the previous user. The models return to DEMO
 * rather than UNAVAILABLE because the next thing rendered is the gate, which
 * draws no money at all, and a component suite importing these modules
 * afterwards should find them in their documented default.
 */
function clearAuthoritativeData() {
  clearProductionData();
  unbindLedgerModel();
  unbindActionModel();
  unbindLeague();
  // The commands go with the session. Leaving them installed after sign-out
  // would leave a signed-out page holding a live wagering command.
  setIssueHook(null);
  setRespondHook(null);
  unbindCommissioner();
  unbindSettings();
  unbindSlate();
  unbindSkunk();
  setCommissionerCapability(false);
  setSettingSheetMount(null);
  // The lifecycle goes with the session, controls and recorded outcomes alike.
  // Leaving a "Week 5 is open" banner or a live dispatch behind a sign-out
  // would leave a signed-out page holding a commissioner's command.
  unbindLifecycle();
  setLifecycleCapability(false);
  setLifecycleDispatch(null);
  setSeasonBlocker(null);
}

/* ── Mount ──────────────────────────────────────────────────────────────── */

function mountPoints() {
  const mast = document.getElementById('fs-mast');
  const panels = document.getElementById('fs-panels');
  const tabbar = document.getElementById('fs-tabbar');
  const gate = document.getElementById('fs-gate');
  if (!mast || !panels || !tabbar || !gate) {
    throw new Error('shell mount points missing from the document');
  }
  return { mast, panels, tabbar, gate };
}

/**
 * Mount the five-tab application for a signed-in GM.
 *
 * The panels still draw their Sprint 7 illustrative view models. Package 1 is
 * authentication infrastructure and binds no league, action, ledger or
 * commissioner data — replacing those sources is the binding package's work,
 * and doing it here would spread it across two.
 */
function mountApplication() {
  const { mast, panels, tabbar, gate } = mountPoints();

  gate.hidden = true;
  gate.innerHTML = '';
  panels.hidden = false;
  tabbar.hidden = false;

  renderMasthead(mast);
  renderPanelHosts(panels);
  renderTabBar(tabbar);

  NAV_DESTINATIONS.forEach((d) => {
    const panel = document.getElementById(d.panelId);
    if (panel) panel.innerHTML = buildPanelContent(d.id);
  });

  const leaguePanel = document.getElementById('panel-league');
  if (leaguePanel) bindLeague(leaguePanel, { openComposer, openSheet });

  const actionPanel = document.getElementById('panel-action');
  if (actionPanel) bindAction(actionPanel, { openSheet });

  const weekPanel = document.getElementById('panel-week');
  if (weekPanel) bindWeek(weekPanel, { openSheet });

  const ledgerPanel = document.getElementById('panel-ledger');
  if (ledgerPanel) bindLedger(ledgerPanel, { openSheet });

  const rulesPanel = document.getElementById('panel-rules');
  if (rulesPanel) bindRules(rulesPanel, { openSheet });

  bindNavigation();

  goTo(DEFAULT_DESTINATION_ID);
}

/**
 * Mount the sign-in gate.
 *
 * The panels and the navigation are emptied, not merely hidden. A hidden panel
 * is still in the document, and leaving twelve GMs' worth of league state in
 * the DOM of a signed-out page would mean the sign-out control had tidied the
 * view without removing the data.
 */
function mountGate() {
  const { mast, panels, tabbar, gate } = mountPoints();

  closeSheet();

  panels.innerHTML = '';
  panels.hidden = true;
  tabbar.innerHTML = '';
  tabbar.hidden = true;

  renderMasthead(mast);          // renders with no identity block

  gate.hidden = false;
  gate.innerHTML = buildGate();
  bindGate(gate);

  const email = gate.querySelector('#fs-gate-email');
  if (email && email.focus) email.focus();
}

/**
 * Render the shell and bind every shared interaction.
 *
 * Async because the first thing the shell needs is an answer it does not have:
 * who is acting. Nothing is drawn on a guess in the meantime.
 */
export async function mount() {
  bindSheet();

  let rendered = false;

  // ONE subscription drives every transition. A deliberate sign-in, a
  // deliberate sign-out, and a session that expired under a request in flight
  // all arrive here, so they cannot diverge.
  onIdentityChange((identity) => {
    rendered = true;
    if (identity) {
      // A sign-in mid-session. The application mounts from the promise so the
      // panels are never built against a half-bound source, and the models are
      // put into a definite mode first on either outcome.
      bindAuthoritativeData().then(mountApplication, mountApplication);
    } else {
      clearAuthoritativeData();
      mountGate();
    }
  });

  try {
    await refreshIdentity();
    // BEFORE THE FIRST AUTHORITATIVE PAINT. Panels are built synchronously from
    // the view models, so binding must complete before the first render —
    // otherwise the first frame is prototype money that is then replaced,
    // which is worse than a moment of loading.
    if (isAuthenticated()) await bindAuthoritativeData();
  } catch {
    // A transport failure is not an identity. The gate is the honest state:
    // we could not establish who is acting, so nothing is shown as though we
    // had. The gate reports the real error if a sign-in is then attempted.
  }

  // The subscription has already drawn the right thing in both the signed-in
  // and the expired-session cases, because each set identity and therefore
  // fired. `rendered` is what stops that becoming a second, redundant mount —
  // and covers the one path that sets nothing at all, a transport failure.
  if (!rendered) {
    if (isAuthenticated()) mountApplication();
    else mountGate();
  }
}

if (typeof document !== 'undefined') {
  // Exposed for manual inspection in the browser console.
  window.FantasyStakes = {
    goTo, openSheet, pushSheet, popSheet, closeSheet, openComposer, switchLeague,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
}