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
import { marketFor, marketWeek } from './market-model.js';
import { mountRefreshOdds, setRefreshHook } from './refresh-odds.js';
import {
  explainRefreshRefusal, readOddsRefresh, requestOddsRefresh,
} from './refresh-odds-command.js';

setRefreshHook({
  read: readOddsRefresh,
  refresh: requestOddsRefresh,
  explain: explainRefreshRefusal,
});

/** The rails a live Matchup — Dynamic or Locked — can be sitting on. */
const RAILS = ['action'];

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

  const cards = RAILS.flatMap((rail) => sectionCards(rail))
    .filter((card) => card.mode === 'dynamic')
    .filter((card) => !panel.querySelector(
      `[data-card-id="${CSS.escape(card.id)}"] [data-status-refresh]`));
  if (!cards.length) return;
  await mountRefreshOdds(panel, {
    leagueId: served.league_id, cards, currentOddsFor,
  });
}

/**
 * The live market line for a Locked card's pairing, or nothing.
 *
 * ── THE WEEK GUARD IS THE WHOLE HONESTY OF THIS FUNCTION ────────────────────
 *
 * The bound board was priced for ONE week. A Locked wager sitting on the LIVE
 * rail from an earlier week has no current price on that board, and quoting one
 * anyway would put this week's market beside last week's frozen odds and call
 * the pair a comparison. When the weeks disagree the row reads `Unavailable`,
 * which is true.
 *
 * `acting_moneyline` IS THE COMPARABLE FIGURE. The board is anchored on the
 * acting GM as challenger, and `yourMoneyline` on the card is this GM's own
 * odds of record — the same side of the same pairing, so the two are the same
 * question asked at two moments.
 *
 * NOTHING IS COMPUTED. The board row arrived over the wire; this reads two
 * fields off it and returns them.
 *
 * @param {object} card a normalised Action card
 * @returns {{available: boolean, moneyline: number|null}}
 */
function currentOddsFor(card) {
  // NULL MEANS "NO COMPARISON IS POSSIBLE HERE"; `{available: false}` means
  // "comparable, but this pairing has no line". The difference decides whether
  // a block is drawn at all.
  //
  // WITHOUT A BOARD FOR THIS CARD'S WEEK THERE IS NOTHING TO COMPARE, and a
  // block whose second row read `Unavailable` forever would be a permanent
  // apology rather than information. The illustrative fixture is exactly that
  // case — it has no market board — which is why Status's demo cards gain
  // nothing, and why the lifecycle card keeps the height it was certified at.
  if (!card || !Number.isInteger(card.weekNumber)) return null;
  if (marketWeek() !== card.weekNumber) return null;

  // NO SERVED ROW, NO COMPARISON. `marketFor` answers null unless an
  // AUTHORITATIVE board is bound and carries this pairing, so this is the one
  // check that cannot be satisfied by an unbound model, a stale week or a
  // fixture. It is deliberately separate from the `available` test below: a row
  // that exists and cannot be priced is a real answer worth showing, and a row
  // that was never served is not an answer at all.
  const row = marketFor(card.opponentTeamId);
  if (!row) return null;

  const unavailable = { available: false, moneyline: null };
  if (row.available !== true) return unavailable;
  return {
    available: Number.isInteger(row.acting_moneyline),
    moneyline: Number.isInteger(row.acting_moneyline)
      ? row.acting_moneyline : null,
  };
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
