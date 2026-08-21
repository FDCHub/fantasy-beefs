/* ============================================================================
 * FantasyStakes — mounting `↻ REFRESH ODDS` onto the Status tab's live cards
 * UIRECON Rev 1.4
 *
 * WHY THIS IS A SEPARATE MODULE FROM `refresh-odds.js`. That file is the
 * affordance: pure markup, one binder, one decorator, all testable without a
 * browser. This file is the only part that knows the app exists — where the
 * cards land, when they are redrawn, and which league is on screen. Keeping the
 * two apart is what lets the certification exercise the control's copy,
 * eligibility and timestamp without booting a shell.
 *
 * IT DECORATES; IT DOES NOT RENDER. The Status surface draws its four rails
 * through the shared card grammar and owns every figure on them. This attaches
 * one affordance to cards that already exist, so a Matchup keeps ONE card,
 * with one identity and one set of terms, from ACTION REQUIRED through
 * COMPLETED — which is the property the shared grammar exists to protect.
 *
 * WHY A `MutationObserver` RATHER THAN A RENDER HOOK. The rails are redrawn on
 * every authoritative refresh — after an accept, a counter, a decline, a tab
 * change — and each redraw replaces the card elements. Anything mounted onto
 * the previous elements is gone, and there is no event announcing the replace.
 * Observing the panel is the one mechanism that survives all of those without
 * the Status surface having to know this feature exists.
 *
 * IT IS IDEMPOTENT AND IT IS QUIET. `mountRefreshOdds` skips a card that
 * already carries the control, so re-entry after an unrelated DOM change costs
 * one query per eligible card. A card whose read is refused gains nothing and
 * says nothing: a GM did not ask, so a refusal they did not provoke is noise.
 *
 * NOTHING HERE PRICES, MOVES CREDITS OR TOUCHES THE WAGER. It reads the served
 * Action state for the card list and the league id, and hands both to the
 * affordance. Every economic figure the control shows came from the refresh
 * route, issuer-anchored, and is identical for both GMs.
 * ========================================================================== */

import { actionMode, sectionCards, servedAction } from './action-model.js';
import { mountRefreshOdds, setRefreshHook } from './refresh-odds.js';
import {
  explainRefreshRefusal, readOddsRefresh, requestOddsRefresh,
} from './refresh-odds-command.js';

setRefreshHook({
  read: readOddsRefresh,
  refresh: requestOddsRefresh,
  explain: explainRefreshRefusal,
});

/** The rails a live Dynamic Matchup can be sitting on. */
const RAILS = ['live', 'waiting', 'action'];

let scheduled = false;

async function sweep() {
  scheduled = false;
  // AUTHORITATIVE READS ONLY. The illustrative fixture has no challenge the
  // refresh route could resolve, so mounting against it would draw a control
  // whose first press is a 404.
  if (actionMode() !== 'authoritative') return;
  const served = servedAction();
  const panel = document.getElementById('panel-action');
  if (!served || !panel || !Number.isFinite(Number(served.league_id))) return;

  const cards = RAILS.flatMap((rail) => sectionCards(rail));
  if (!cards.length) return;
  await mountRefreshOdds(panel, { leagueId: served.league_id, cards });
}

function schedule() {
  if (scheduled) return;
  scheduled = true;
  // Coalesced to a microtask-ish tick: one redraw fires many mutation records,
  // and each would otherwise start its own pass over the same cards.
  setTimeout(() => { sweep().catch(() => { /* decoration never blocks */ }); }, 0);
}

/**
 * Start watching the Status panel.
 *
 * SAFE TO CALL BEFORE THE PANEL EXISTS. The panel host is created by the shell
 * when a GM first opens Status, so the observer is placed on `document.body`
 * and filters by id — the alternative, polling for `#panel-action`, would keep
 * a timer alive for a surface a GM may never open.
 */
export function startRefreshOddsMount() {
  if (typeof document === 'undefined' || !document.body) return;
  new MutationObserver(schedule).observe(document.body, {
    childList: true, subtree: true,
  });
  schedule();
}

startRefreshOddsMount();
