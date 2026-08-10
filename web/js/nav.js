/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · navigation model
 * Sprint 7 Package 1
 *
 * The five primary destinations and the pure state transition between them.
 * Kept free of DOM access so the navigation contract can be tested directly:
 * the order is fixed by the POR, and every destination must stay reachable.
 * ========================================================================== */

/**
 * Five primary tabs, in POR order (§1.2). There is no My Team primary tab, and
 * no `Wrap Up` label survives anywhere in the primary navigation (§5.1).
 *
 * Icons are inline SVG with `stroke:currentColor`, so the active-gold state
 * renders identically across operating systems. No emoji.
 *
 * @type {ReadonlyArray<{id: string, label: string, panelId: string, icon: string}>}
 */
export const NAV_DESTINATIONS = Object.freeze([
  {
    id: 'league',
    label: 'League',
    panelId: 'panel-league',
    icon: '<path d="M9 2 3 4v5.5c0 3.7 2.5 6.3 6 7.5 3.5-1.2 6-3.8 6-7.5V4L9 2z"/>',
  },
  {
    id: 'action',
    label: 'Action',
    panelId: 'panel-action',
    icon: '<rect x="4" y="3" width="10" height="13" rx="1.5"/><path d="M7 2.5h4v2H7z"/><path d="M6.5 8h5M6.5 11h3.5"/>',
  },
  {
    id: 'ledger',
    label: 'Ledger',
    panelId: 'panel-ledger',
    icon: '<path d="M3 4.5A1.5 1.5 0 0 1 4.5 3H8v12H4.5A1.5 1.5 0 0 1 3 13.5v-9z"/><path d="M15 4.5A1.5 1.5 0 0 0 13.5 3H10v12h3.5A1.5 1.5 0 0 0 15 13.5v-9z"/>',
  },
  {
    id: 'week',
    label: 'The Week',
    panelId: 'panel-week',
    icon: '<rect x="2.5" y="4" width="13" height="10.5" rx="1.5"/><path d="M5 7h5M5 9.5h5M5 12h3"/><path d="M12 7h1.5v3H12z"/>',
  },
  {
    id: 'rules',
    label: 'Rules & Settings',
    panelId: 'panel-rules',
    icon: '<path d="M9 3v12"/><path d="M4 6h10"/><path d="M4 6 2 10.5h4L4 6z"/><path d="M14 6l-2 4.5h4L14 6z"/><path d="M6 15h6"/>',
  },
]);

/** The destination the app opens on. */
export const DEFAULT_DESTINATION_ID = 'league';

/**
 * @param {string} id
 * @returns {{id: string, label: string, panelId: string, icon: string}}
 */
export function destinationById(id) {
  const found = NAV_DESTINATIONS.find((d) => d.id === id);
  if (!found) {
    throw new Error(
      `unknown navigation destination "${id}" — ` +
      `expected one of ${NAV_DESTINATIONS.map((d) => d.id).join(', ')}`,
    );
  }
  return found;
}

/**
 * Pure transition: select a destination.
 *
 * Returns a fresh array in which exactly one destination is active. An unknown
 * id throws rather than resolving to a blank app, so a mis-wired control fails
 * loudly instead of stranding the GM on an empty screen.
 *
 * @param {string} id destination to activate
 * @returns {Array<{id: string, label: string, panelId: string, active: boolean}>}
 */
export function selectDestination(id) {
  destinationById(id); // validates
  return NAV_DESTINATIONS.map((d) => ({
    id: d.id,
    label: d.label,
    panelId: d.panelId,
    active: d.id === id,
  }));
}