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
import { bindAction, buildActionPanel } from './action.js';
import { bindWeek, buildWeekPanel } from './week.js';
import { bindLedger, buildLedgerPanel } from './ledger.js';
import { bindRules, buildRulesPanel } from './rules.js';
import { beginSession, composerSheet, endSession } from './composer.js';
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
import { CURRENT_WEEK } from './data/week-data.js';
import {
  bindSettings, markSettingsUnavailable, unbindSettings,
} from './settings-model.js';
import {
  bindSlate, markSlateUnavailable, unbindSlate,
} from './pool-slate-model.js';
import { bindPoolEntryForm, setCommissionerCapability, setSettingSheetMount } from './rules.js';

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
    availableCents: ILLUSTRATIVE.availableCents,
  });
  openSheet(() => composerSheet());
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
  if (leagueId === null) {
    markLedgerUnavailable();
    markCommissionerUnavailable();
    return;
  }

  try {
    await loadProductionData({ leagueId, week: CURRENT_WEEK });
  } catch {
    markLedgerUnavailable();
    markCommissionerUnavailable();
    return;
  }

  const data = productionData();

  if (data && data.ledger) bindLedgerModel(data.ledger, data.settings);
  else markLedgerUnavailable();

  if (data && data.positions) bindCommissioner(data.positions, data.reconciliation);
  else markCommissionerUnavailable();

  if (data && data.settings) bindSettings(data.settings);
  else markSettingsUnavailable();

  if (data && data.slate) bindSlate(data.slate);
  else markSlateUnavailable();

  // Presentation capability, from the server's own answer. It decides what is
  // DRAWN; the command is refused server-side regardless.
  const identity = currentIdentity();
  const caps = (identity && identity.capabilities) || {};
  setCommissionerCapability(
    Array.isArray(caps.commissioner_league_ids)
    && caps.commissioner_league_ids.includes(leagueId));

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
  unbindCommissioner();
  unbindSettings();
  unbindSlate();
  setCommissionerCapability(false);
  setSettingSheetMount(null);
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
  window.FantasyStakes = { goTo, openSheet, pushSheet, popSheet, closeSheet, openComposer };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
}