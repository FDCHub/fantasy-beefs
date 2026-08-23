/* ============================================================================
 * FantasyStakes — the secondary gear menu
 * WP3B · Rev 4.3 §3.1
 *
 * Rules & Settings loses its bottom-navigation position to Standings, and
 * everything that used to live behind it has to stay reachable (WP3B §20). This
 * is the way in.
 *
 * A GEAR IN THE MASTHEAD, NOT A SIXTH TAB. Rev 4.3 §3 fixes the bottom
 * navigation at five and §31 requires all five to fit without crowding; a
 * secondary control in the bottom bar would be the sixth tab under another
 * name. The masthead is present and identical on every tab, which is exactly
 * the property a secondary entry point needs.
 *
 * IT ROUTES; IT DOES NOT REIMPLEMENT. Rules, League Settings and the
 * commissioner surface are `panel-rules` and stay `panel-rules` — the menu
 * navigates to the destination that already exists rather than rebuilding its
 * content in a sheet. WP3B §20 is explicit that access is preserved rather than
 * refactored, and this is the smallest way to keep that true.
 *
 * NOTHING HERE INVENTS BACKEND FUNCTIONALITY (WP3B §4). An entry appears only
 * when the surface behind it exists in this build. Where a later package owns
 * the destination — the provider/admin detail is WP3D's, About and Legal are
 * WP3C's — the entry states that plainly rather than routing nowhere or
 * pretending to be finished.
 * ========================================================================== */

import { escapeHtml } from './components.js';
import { economyReachable } from './economy.js';

// UIRECON WAVE 2 — THE GEAR MEANS SETTINGS, AND NOW SAYS SO.
//
// It was labelled `Menu`, which named the WIDGET rather than the
// destination — and beside an account control that opens a sheet of its own,
// `Menu` stopped distinguishing the two at all. Everything behind it is a
// setting or a rule; the title and the accessible name say that now. The
// entries, the routing and the capability gating are untouched.
export const MENU_TITLE = 'Settings';

/** The gear control that lives in the masthead. */
export function menuButton() {
  return (
    '<button type="button" class="fs-gear" id="fs-gear" '
    + 'aria-label="Settings" aria-haspopup="dialog">'
    + '<svg class="fs-gear__icon" viewBox="0 0 18 18" fill="none" '
    + 'stroke="currentColor" stroke-width="1.4" stroke-linecap="round" '
    + 'stroke-linejoin="round" aria-hidden="true" focusable="false">'
    + '<circle cx="9" cy="9" r="2.6"/>'
    + '<path d="M9 1.6v2M9 14.4v2M1.6 9h2M14.4 9h2'
    + 'M3.8 3.8l1.4 1.4M12.8 12.8l1.4 1.4M14.2 3.8l-1.4 1.4M5.2 12.8l-1.4 1.4"/>'
    + '</svg></button>'
  );
}

/**
 * The menu's entries, decided from what this build actually has.
 *
 * `kind` says what an entry does, and the three kinds are deliberately
 * different things:
 *
 *   destination  navigates to a panel that exists now
 *   sheet        pushes a surface this package built
 *   pending      names a destination a later package owns, and says so
 *
 * A `pending` entry is drawn as text, not as a control. Rev 4.3 §27 asks for
 * intentional states rather than dead ends, and a button that does nothing when
 * pressed is a worse answer than a line that explains itself.
 *
 * @returns {Array<{id: string, label: string, help: string, kind: string}>}
 */
export function menuEntries() {
  const entries = [
    {
      id: 'rules',
      label: 'Rules',
      help: 'How FantasyStakes is played in this league.',
      kind: 'destination',
      destination: 'rules',
      zone: 'rules',
    },
    {
      id: 'settings',
      label: 'League Settings',
      help: 'The league’s configured values.',
      kind: 'destination',
      destination: 'rules',
      zone: 'settings',
    },
  ];

  // COMMISSIONER ENTRIES APPEAR ONLY FOR A COMMISSIONER, from the server's own
  // capability answer. WP3B §17: an ordinary member is never offered the
  // editing or activation surface. The routes refuse regardless — this is what
  // stops the app OFFERING something it knows will be refused.
  if (economyReachable()) {
    entries.push({
      id: 'commissioner',
      label: 'Commissioner controls',
      help: 'The season lifecycle and GM positions.',
      kind: 'destination',
      destination: 'rules',
      zone: 'commish',
    });
    entries.push({
      id: 'economy',
      label: 'Economy configuration',
      help: 'Weekly Bet Minimum, Yahoo Championship Contribution and Skunk Fee.',
      kind: 'sheet',
    });
  }

  entries.push({
    id: 'provider',
    // TITLE CASE, matching §23's own listing of the gear menu and the three
    // entries beside it. It was the only one in sentence case.
    label: 'Provider Information',
    help: 'Yahoo connection detail arrives with the provider package.',
    kind: 'pending',
  });
  entries.push({
    id: 'about',
    label: 'About & Legal',
    help: 'Product and legal information arrives with the next package.',
    kind: 'pending',
  });

  return entries;
}

/**
 * The menu sheet.
 *
 * @returns {{title: string, sub: string, body: string, onMount: Function}}
 */
export function menuSheet() {
  const rows = menuEntries().map((entry) => {
    const label = `<span class="fs-menu__label">${escapeHtml(entry.label)}</span>`
      + `<span class="fs-menu__help">${escapeHtml(entry.help)}</span>`;

    if (entry.kind === 'pending') {
      return (
        `<div class="fs-menu__row is-pending" data-menu="${escapeHtml(entry.id)}">`
        + `<span class="fs-menu__text">${label}</span>`
        + '<span class="fs-menu__soon">Not yet</span>'
        + '</div>'
      );
    }
    return (
      `<button type="button" class="fs-menu__row" `
      + `data-menu="${escapeHtml(entry.id)}" `
      + `data-menu-kind="${escapeHtml(entry.kind)}"`
      + (entry.destination
        ? ` data-menu-destination="${escapeHtml(entry.destination)}"` : '')
      + (entry.zone ? ` data-menu-zone="${escapeHtml(entry.zone)}"` : '')
      + '>'
      + `<span class="fs-menu__text">${label}</span>`
      + '<span class="fs-menu__chev" aria-hidden="true">›</span>'
      + '</button>'
    );
  }).join('');

  return {
    title: MENU_TITLE,
    sub: '',
    body: `<div class="fs-menu" id="fs-menu">${rows}</div>`,
    onMount: bindMenuSheet,
  };
}

/**
 * The shell installs how to navigate and how to open the economy sheet; this
 * module holds neither, so it cannot navigate a signed-out page.
 * @type {{goTo: Function, openEconomy: Function}|null}
 */
let HOOK = null;

/** @param {{goTo: Function, openEconomy: Function}|null} hook */
export function setMenuHook(hook) {
  HOOK = hook || null;
}

/**
 * @param {HTMLElement} host
 * @param {{close: Function, push: Function}} api
 */
function bindMenuSheet(host, api) {
  host.addEventListener('click', (event) => {
    const row = event.target.closest('[data-menu-kind]');
    if (!row || !HOOK) return;

    if (row.dataset.menuKind === 'sheet') {
      // The economy setup replaces the menu level rather than stacking on it:
      // the menu is a chooser, and closing the economy sheet should return the
      // commissioner to the app, not to the list they chose from.
      HOOK.openEconomy();
      return;
    }
    if (row.dataset.menuKind === 'destination') {
      // `goTo` closes the sheet as part of a destination change, so there is no
      // separate close here — a second one would fight it.
      HOOK.goTo(row.dataset.menuDestination, row.dataset.menuZone || null);
    }
  });
}

/**
 * Bind the gear control in the masthead.
 *
 * @param {HTMLElement} root the masthead element
 * @param {{openSheet: Function}} api
 */
export function bindMenu(root, api) {
  const gear = root.querySelector('#fs-gear');
  if (!gear) return;
  gear.addEventListener('click', () => { api.openSheet(() => menuSheet()); });
}
