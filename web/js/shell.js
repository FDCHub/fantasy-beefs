/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · application shell wiring
 * Sprint 7 Package 1
 *
 * The only module in the foundation that touches the DOM. It renders the five
 * primary destinations, binds the persistent bottom navigation, and owns the
 * single shared pop-out. Tab CONTENT is not built here — later packages fill
 * each panel through `mountPanelContent`.
 *
 * Nothing in this file reads, derives, or writes protocol state. Figures shown
 * in Package 1 are the POR's illustrative dataset, marked as such in
 * `demo-state.js`, and are exact integer cents right up to the moment they are
 * drawn.
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

import { ILLUSTRATIVE, LEAGUE_IDENTITY, MASTHEAD } from './demo-state.js';

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
 * Package 1 content for each destination.
 *
 * Each panel receives its POR-defined frame: the tab header, the shared
 * four-cell strip where the POR defines one, and the Credits disclaimer under
 * that strip. Figures the POR has not yet given are drawn as unresolved rather
 * than invented.
 *
 * @param {string} destinationId
 * @returns {string}
 */
export function buildPanelContent(destinationId) {
  const composer = new PanelComposer(destinationId);

  switch (destinationId) {
    case 'league':
      composer.add(tabHeader({
        title: LEAGUE_IDENTITY.name,
        sub: LEAGUE_IDENTITY.week,
        asideValue: ILLUSTRATIVE.kickoffCountdown,
        asideLabel: 'FIRST KICKOFF',
      }));
      composer.addStrip({
        id: 'fs-strip-league',
        label: 'League summary',
        cells: [
          {
            label: 'Net Winnings',
            cents: ILLUSTRATIVE.netWinningsCents,
            signed: true,
            context: ILLUSTRATIVE.netWinningsRank,
          },
          { label: 'Wallet', cents: ILLUSTRATIVE.walletCents },
          { label: 'Weekly Min Left', cents: ILLUSTRATIVE.weeklyMinLeftCents },
          { label: 'Available', cents: ILLUSTRATIVE.availableCents, anchor: true },
        ],
      });
      composer.addDisclaimer();
      break;

    case 'action':
      composer.add(tabHeader({
        title: 'Action',
        sub: 'Your wagers',
      }));
      composer.addStrip({
        id: 'fs-strip-action',
        label: 'Action summary',
        cells: [
          { label: 'Season Bet Record', pending: true },
          { label: 'Bet this week', pending: true },
          { label: 'Upside left', pending: true },
          { label: 'Downside', pending: true },
        ],
      });
      composer.addDisclaimer();
      break;

    case 'ledger':
      composer.add(tabHeader({
        title: 'Ledger',
        sub: 'Transaction history and account breakdown',
      }));
      composer.add('<div class="fs-eyebrow" style="margin-left:14px">YOUR POSITION</div>');
      composer.addStrip({
        id: 'fs-strip-ledger',
        label: 'Your position',
        cells: [
          { label: 'Wallet', cents: ILLUSTRATIVE.walletCents },
          { label: 'Available', cents: ILLUSTRATIVE.availableCents },
          { label: 'In Play', pending: true },
          { label: 'Current Settle', pending: true, gold: true },
        ],
      });
      composer.addDisclaimer();
      break;

    case 'week':
      composer.add(tabHeader({
        title: 'The Week',
        sub: LEAGUE_IDENTITY.name,
      }));
      // The POR carries a four-cell strip on The Week, but has not yet defined
      // its four cells. The component is ready; the cells are not invented here.
      break;

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

let lastFocusedBeforeSheet = null;

/**
 * Open the shared bottom sheet.
 *
 * @param {{title?: string, sub?: string, body?: string}} spec
 */
export function openSheet(spec) {
  const overlay = document.getElementById('fs-overlay');
  const host = document.getElementById('fs-sheet');
  if (!overlay || !host) return;

  lastFocusedBeforeSheet = document.activeElement;
  host.innerHTML = sheet(spec);
  overlay.classList.add('is-open');
  overlay.setAttribute('aria-hidden', 'false');

  const closeBtn = host.querySelector('[data-fs-close]');
  if (closeBtn) closeBtn.focus();
}

/** Close the shared bottom sheet. */
export function closeSheet() {
  const overlay = document.getElementById('fs-overlay');
  if (!overlay) return;
  overlay.classList.remove('is-open');
  overlay.setAttribute('aria-hidden', 'true');
  if (lastFocusedBeforeSheet && lastFocusedBeforeSheet.focus) {
    lastFocusedBeforeSheet.focus();
  }
  lastFocusedBeforeSheet = null;
}

function bindSheet() {
  const overlay = document.getElementById('fs-overlay');
  if (!overlay) return;

  // Scrim tap closes; a tap inside the sheet does not.
  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) closeSheet();
  });

  // One delegated handler serves every close control, present and future.
  overlay.addEventListener('click', (event) => {
    if (event.target.closest && event.target.closest('[data-fs-close]')) closeSheet();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && overlay.classList.contains('is-open')) closeSheet();
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

/* ── Package 1 interactions defined by the POR ──────────────────────────── */

function bindCurrentSettle() {
  const strip = document.getElementById('fs-strip-ledger');
  if (!strip) return;
  const cell = strip.querySelector('.fs-strip__cell.is-gold');
  if (!cell) return;

  cell.classList.add('is-tappable');
  cell.setAttribute('role', 'button');
  cell.setAttribute('tabindex', '0');

  const open = () => openSheet({
    title: 'The Sheet',
    sub: 'Authoritative season reconciliation',
    body: note(
      'The Sheet is built in a later Sprint 7 package. Current Settle is ' +
      'reconciled here; the Ledger records transaction history and does not ' +
      'prove this figure.',
      { pending: true },
    ),
  });

  cell.addEventListener('click', open);
  cell.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      open();
    }
  });
}

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

  bindNavigation();
  bindSheet();
  bindCurrentSettle();

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
  window.FantasyStakes = { goTo, openSheet, closeSheet, mountPanelContent };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
}
