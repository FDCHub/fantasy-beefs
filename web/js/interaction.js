/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · shared interaction behaviour
 * Sprint 7 Package 5
 *
 * ONE ACTIVATION CONTRACT for every surface that is tappable but is not a
 * native control.
 *
 * A real `<button>` fires a click on Enter and Space for free. An element that
 * merely carries `role="button"` does not: the role tells assistive technology
 * what it is, and the keyboard behaviour has to be supplied. Wager cards are
 * `role="button"` containers — a card holds figures, copy and a foot, which a
 * `<button>` may not contain — so the behaviour lives here rather than being
 * re-typed, differently, in each of the three surfaces that render one.
 *
 * Space is prevented from its default page scroll before activating, which is
 * the behaviour a native button already has.
 * ========================================================================== */

/**
 * Bind a handler to pointer and keyboard activation.
 *
 * @param {HTMLElement} el
 * @param {(event: Event) => void} handler
 */
export function onActivate(el, handler) {
  el.addEventListener('click', handler);

  el.addEventListener('keydown', (event) => {
    // Only the element's own activation — a key pressed inside a nested control
    // belongs to that control.
    if (event.target !== el) return;
    if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
      event.preventDefault();
      handler(event);
    }
  });
}