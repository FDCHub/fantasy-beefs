/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.3 · navigation model
 * WP3B
 *
 * The primary destinations and the pure state transition between them. Kept
 * free of DOM access so the navigation contract can be tested directly: the
 * order is fixed by the POR, and every destination must stay reachable.
 *
 * REV 4.3 §3. Five primary tabs, in this exact order:
 *
 *     Standings · Play · Status · Wrap Up · Account
 *
 * Standings is the default landing tab. Rules & Settings is NO LONGER PRIMARY
 * (§3.1) — it moves behind the secondary gear/menu.
 *
 * THE IDS ARE DELIBERATELY UNCHANGED, and that is a compatibility decision
 * rather than an oversight. Rev 4.3 §2.2 rules out renaming internal
 * identifiers for branding, and every panel id, module name, test selector and
 * browser suite in the tree addresses these five by their Rev 4.2 ids. Renaming
 * `league` to `play` would touch some hundreds of call sites to change nothing
 * a user can see, and each of those is a chance to break a binding. What a user
 * reads is the LABEL, and the labels are the POR's.
 *
 *     id        Rev 4.2 label      Rev 4.3 label
 *     ────────  ─────────────────  ─────────────
 *     standings  —                 Standings      (new)
 *     league     League            Play
 *     action     Action            Status
 *     week       The Week          Wrap Up
 *     ledger     Ledger            Account
 *     rules      Rules & Settings  — secondary, off the tab bar
 *
 * Icons are inline SVG with `stroke:currentColor`, so the active-gold state
 * renders identically across operating systems. No emoji.
 * ========================================================================== */

/**
 * The five primary tabs, in POR order (Rev 4.3 §3).
 *
 * @type {ReadonlyArray<{id: string, label: string, panelId: string, icon: string}>}
 */
export const NAV_DESTINATIONS = Object.freeze([
  {
    id: 'standings',
    label: 'Standings',
    panelId: 'panel-standings',
    // A ranked list: three bars, longest at the top.
    icon: '<path d="M3 4.5h12"/><path d="M3 9h8.5"/><path d="M3 13.5h5"/>',
  },
  {
    id: 'league',
    label: 'Play',
    panelId: 'panel-league',
    icon: '<path d="M9 2 3 4v5.5c0 3.7 2.5 6.3 6 7.5 3.5-1.2 6-3.8 6-7.5V4L9 2z"/>',
  },
  {
    id: 'action',
    label: 'Status',
    panelId: 'panel-action',
    icon: '<rect x="4" y="3" width="10" height="13" rx="1.5"/><path d="M7 2.5h4v2H7z"/><path d="M6.5 8h5M6.5 11h3.5"/>',
  },
  {
    id: 'week',
    label: 'Wrap Up',
    panelId: 'panel-week',
    icon: '<rect x="2.5" y="4" width="13" height="10.5" rx="1.5"/><path d="M5 7h5M5 9.5h5M5 12h3"/><path d="M12 7h1.5v3H12z"/>',
  },
  {
    id: 'ledger',
    label: 'Account',
    panelId: 'panel-ledger',
    icon: '<path d="M3 4.5A1.5 1.5 0 0 1 4.5 3H8v12H4.5A1.5 1.5 0 0 1 3 13.5v-9z"/><path d="M15 4.5A1.5 1.5 0 0 0 13.5 3H10v12h3.5A1.5 1.5 0 0 0 15 13.5v-9z"/>',
  },
]);

/**
 * Destinations reachable from the secondary gear/menu, never from the tab bar.
 *
 * REV 4.3 §15 AND §20 TOGETHER. Rules & Settings loses its bottom-navigation
 * position and keeps everything else — the rules, the league settings and the
 * whole commissioner surface stay exactly where they were and stay reachable.
 * It is still a real destination with a real panel; only the way in changed.
 *
 * Keeping it a DESTINATION rather than folding its content into a sheet is what
 * makes that true cheaply: `goTo('rules')` still works, the panel still builds
 * from `rules.js`, and every existing binding and test that addresses
 * `panel-rules` is untouched.
 *
 * @type {ReadonlyArray<{id: string, label: string, panelId: string, icon: string}>}
 */
export const SECONDARY_DESTINATIONS = Object.freeze([
  {
    id: 'rules',
    label: 'Rules & Settings',
    panelId: 'panel-rules',
    icon: '<path d="M9 3v12"/><path d="M4 6h10"/><path d="M4 6 2 10.5h4L4 6z"/><path d="M14 6l-2 4.5h4L14 6z"/><path d="M6 15h6"/>',
  },
]);

/**
 * Every destination that has a panel — primary and secondary together.
 *
 * The tab bar renders `NAV_DESTINATIONS`; the panel hosts and the selection
 * transition use this. A secondary destination that had no panel host would
 * navigate to nothing.
 *
 * @type {ReadonlyArray<{id: string, label: string, panelId: string, icon: string}>}
 */
export const ALL_DESTINATIONS = Object.freeze([
  ...NAV_DESTINATIONS, ...SECONDARY_DESTINATIONS,
]);

/** The destination the app opens on — Rev 4.3 §3. */
export const DEFAULT_DESTINATION_ID = 'standings';

/**
 * @param {string} id
 * @returns {{id: string, label: string, panelId: string, icon: string}}
 */
export function destinationById(id) {
  const found = ALL_DESTINATIONS.find((d) => d.id === id);
  if (!found) {
    throw new Error(
      `unknown navigation destination "${id}" — ` +
      `expected one of ${ALL_DESTINATIONS.map((d) => d.id).join(', ')}`,
    );
  }
  return found;
}

/**
 * Whether a destination appears in the bottom navigation.
 *
 * @param {string} id
 * @returns {boolean}
 */
export function isPrimary(id) {
  return NAV_DESTINATIONS.some((d) => d.id === id);
}

/**
 * Pure transition: select a destination.
 *
 * Returns a fresh array covering EVERY destination, in which at most one is
 * active. An unknown id throws rather than resolving to a blank app, so a
 * mis-wired control fails loudly instead of stranding the GM on an empty screen.
 *
 * SECONDARY DESTINATIONS ARE INCLUDED, which is what makes navigating to Rules
 * & Settings deactivate all five primary tabs. If the transition covered only
 * the primary five, opening Rules would leave the previous tab's panel showing
 * underneath it and its bottom-nav item still lit.
 *
 * @param {string} id destination to activate
 * @returns {Array<{id: string, label: string, panelId: string, active: boolean}>}
 */
export function selectDestination(id) {
  destinationById(id); // validates
  return ALL_DESTINATIONS.map((d) => ({
    id: d.id,
    label: d.label,
    panelId: d.panelId,
    active: d.id === id,
  }));
}
