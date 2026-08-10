/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · application shell wiring
 * Sprint 7 Packages 1–3
 *
 * The only module that touches the DOM directly. It renders the five primary
 * destinations, binds the persistent bottom navigation, and owns the single
 * shared pop-out.
 *
 * The pop-out is a STACK. Opening the Matchup Preview from inside the composer
 * pushes a level rather than replacing one, so closing the preview returns to
 * a composer that still holds the market, mode and stake the GM entered. The
 * close X always dismisses the ACTIVE sheet: one level up if there is one,
 * otherwise the overlay itself.
 *
 * Nothing in this file reads, derives, or writes protocol state.
 * ========================================================================== */

import {
  DEFAULT_DESTINATION_ID,
  NAV_DESTINATIONS,
  destinationById,
  selectDestination,
} from './nav.js';

import {
  PanelComposer,
  escapeHtml,
  note,
  sheet,
  tabHeader,
} from './components.js';

import { ILLUSTRATIVE, MASTHEAD } from './demo-state.js';
import { bindLeague, buildLeaguePanel } from './league.js';
import { bindAction, buildActionPanel } from './action.js';
import { bindWeek, buildWeekPanel } from './week.js';
import { bindLedger, buildLedgerPanel } from './ledger.js';
import { beginSession, composerSheet, endSession } from './composer.js';

/* ── Masthead ───────────────────────────────────────────────────────────── */

function renderMasthead(root) {
  // Each half of the tagline is held unbreakable, so a narrow viewport wraps at
  // the middot rather than mid-phrase — the same rule the POR applies to the
  // league identity.
  const tagline = MASTHEAD.tagline
    .split(' · ')
    .map((phrase) => `<span class="fs-nowrap">${escapeHtml(phrase)}</span>`)
    .join(' · ');

  root.innerHTML =
    '<div class="fs-mast__lockup">' +
    '<div class="fs-mast__word">' +
    '<span class="fs-word-a">Fantasy</span><span class="fs-word-b">Stakes</span>' +
    '</div>' +
    `<div class="fs-mast__tagline">${tagline}</div>` +
    '</div>' +
    '<div class="fs-mast__meta">' +
    `${escapeHtml(MASTHEAD.revision)}<br>${escapeHtml(MASTHEAD.author)}` +
    '</div>';
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
 * Content for each destination. Four of the five are built by their own
 * modules; Rules & Settings carries its POR frame and lands in Package 4.
 *
 * @param {string} destinationId
 * @returns {string}
 */
export function buildPanelContent(destinationId) {
  if (destinationId === 'league') return buildLeaguePanel();
  if (destinationId === 'action') return buildActionPanel();
  if (destinationId === 'week') return buildWeekPanel();
  if (destinationId === 'ledger') return buildLedgerPanel();

  const composer = new PanelComposer(destinationId);

  switch (destinationId) {
    case 'rules':
      composer.add(tabHeader({
        title: 'Rules & Settings',
        sub: 'Rules sheets · League settings · Commish',
      }));
      // Rules & Settings summarises no position, so it carries no strip and,
      // therefore, no Credits disclaimer.
      break;

    default:
      throw new Error(`no panel content defined for "${destinationId}"`);
  }

  const label = destinationById(destinationId).label;
  composer.add(
    '<div class="fs-panel__scroll">' +
    note(
      `${label} content is built in a later Sprint 7 package. ` +
      'This release establishes the shared shell, navigation and global components.',
    ) +
    '</div>',
  );

  return composer.toHTML();
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

/* Package 1 bound the Ledger strip's gold cell to a placeholder sheet promising
 * that Current Settle would be reconciled "in a later Sprint 7 package". This
 * IS that package: the Ledger now carries the whole reconciliation on the tab,
 * so the placeholder is gone rather than left pointing at a page that exists. */

/* ── Mount ──────────────────────────────────────────────────────────────── */

/** Render the shell and bind every shared interaction. */
export function mount() {
  const mast = document.getElementById('fs-mast');
  const panels = document.getElementById('fs-panels');
  const tabbar = document.getElementById('fs-tabbar');
  if (!mast || !panels || !tabbar) {
    throw new Error('shell mount points missing from the document');
  }

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

  bindNavigation();
  bindSheet();

  goTo(DEFAULT_DESTINATION_ID);
}

/**
 * Replace one panel's content. The seam later packages build against.
 *
 * @param {string} destinationId
 * @param {string} html
 */
export function mountPanelContent(destinationId, html) {
  const panel = document.getElementById(destinationById(destinationId).panelId);
  if (!panel) throw new Error(`panel host missing for "${destinationId}"`);
  panel.innerHTML = html;
}

if (typeof document !== 'undefined') {
  // Exposed for later packages and for manual inspection in the browser.
  window.FantasyStakes = {
    goTo, openSheet, pushSheet, popSheet, closeSheet, openComposer, mountPanelContent,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
}