/* ============================================================================
 * FantasyStakes — weekly Pool slate read-model
 * Sprint 8 Package 4B-3
 *
 * WHICH POOLS A WEEK HAS IS NOT A FRONTEND QUESTION. The Rev1.3 catalog holds
 * 80 active definitions, 64 of them Gate-1 runtime-eligible, and the governed
 * selector in `betting/pool_slate.py` draws four of them per week through a
 * rotation cycle. The four cards Rev 4.2 shows are that week's DRAW — not a
 * fixed launch set, and emphatically not the legacy three-pot
 * `POOL_BET_TYPES` list, which belongs to a retired subsystem and is not the
 * rotating catalog.
 *
 * So production reads the slate. It never composes one.
 *
 * FOUR MODES, AND THE FOURTH IS THE ONE THAT MATTERS.
 *
 *   demo           the POR's four illustrative Pools — component suites and
 *                  isolated review;
 *   drawn          a real slate exists and is bound;
 *   undrawn        the read succeeded and reported `drawn: false`;
 *   unavailable    the read failed or was refused.
 *
 * UNDRAWN IS AN ORDINARY STATE, NOT A BUG. A slate is drawn only when four
 * definitions pass BOTH gates, and gate 2 is a per-league, per-provider source
 * measurement. The catalog's own environment snapshot currently records
 * `selectable_now: 0` because provider access is refused at the application
 * level. The honest response is to say the week has no slate yet — not to
 * synthesise four Pools, not to fall back to the launch cards, and not to
 * weaken a gate so the row looks populated.
 *
 * CONTINUATIONS OCCUPY SLOTS. A carried pot is a slot state, never a fifth
 * Pool and never a second category. Nothing here adds a card for one.
 * ========================================================================== */

export const SLATE_MODE_DEMO = 'demo';
export const SLATE_MODE_DRAWN = 'drawn';
export const SLATE_MODE_UNDRAWN = 'undrawn';
export const SLATE_MODE_UNAVAILABLE = 'unavailable';

/** The governed weekly slot count — `betting/pool_rotation.DEFAULT_SLOT_COUNT`. */
export const GOVERNED_SLOT_COUNT = 4;

let MODE = SLATE_MODE_DEMO;
let SERVED = null;

/**
 * Bind an authoritative slate read.
 *
 * @param {object} body a PoolSlateOut from GET /league/{id}/pool/slate/{week}
 */
export function bindSlate(body) {
  SERVED = body;
  MODE = body && body.drawn ? SLATE_MODE_DRAWN : SLATE_MODE_UNDRAWN;
}

/** The read failed or was refused. */
export function markSlateUnavailable() {
  SERVED = null;
  MODE = SLATE_MODE_UNAVAILABLE;
}

/** Restore the illustrative source. */
export function unbindSlate() {
  SERVED = null;
  MODE = SLATE_MODE_DEMO;
}

/** @returns {'demo'|'drawn'|'undrawn'|'unavailable'} */
export function slateMode() {
  return MODE;
}

/** The served body, when bound. @returns {object|null} */
export function servedSlate() {
  return SERVED;
}

/**
 * The week's Pool rows, for the locked card presentation.
 *
 * Returns the authoritative slots when drawn, and an EMPTY array in every
 * other production state. An empty array is what makes the surface draw its
 * unresolved treatment; a non-empty fallback would be the failure this module
 * exists to prevent.
 *
 * Field names match the illustrative Pool shape so the card renderer is
 * unchanged — the presentation was never the thing that needed correcting.
 *
 * @returns {Array<object>}
 */
export function slateRows() {
  if (MODE !== SLATE_MODE_DRAWN || !SERVED) return [];

  return SERVED.slots.map((slot) => Object.freeze({
    slot: slot.slot,
    catalogNumber: slot.catalog_number,
    definitionKey: slot.definition_key,
    name: slot.display_name || slot.definition_key,
    scope: slot.scope,
    category: slot.category,
    potCents: slot.pot_cents,
    rolloverCents: slot.rollover_cents,
    // A carried pot is a slot STATE. The renderer badges it; it never adds a
    // card, which is what would turn four governed slots into five.
    continuation: slot.is_continuation,
    settled: slot.settled,
  }));
}

/**
 * Whether the drawn slate honours the governed four-slot contract.
 *
 * Reported rather than enforced client-side: if a server ever returned five
 * slots that is a protocol violation to surface, not something a renderer
 * should quietly truncate.
 *
 * @returns {boolean}
 */
export function slateHonoursSlotContract() {
  if (MODE !== SLATE_MODE_DRAWN || !SERVED) return true;
  return SERVED.slots.length <= (SERVED.slot_count || GOVERNED_SLOT_COUNT);
}
