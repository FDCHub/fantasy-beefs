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
import { isAuthenticated, onIdentityChange, refreshIdentity } from './session.js';

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
    if (identity) mountApplication();
    else mountGate();
  });

  try {
    await refreshIdentity();
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