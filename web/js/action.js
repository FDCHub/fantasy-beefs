/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · Action
 * Sprint 7 Package 2
 *
 * Four horizontal carousels — ACTION REQUIRED, WAITING, LIVE, COMPLETED — over
 * the same wager-card grammar League uses. Because each rail is one row, a card
 * can afford to say more; it does not become a different card.
 *
 * A COMPLETED card is the LIVE card that preceded it, showing later figures.
 * Same identity, same market row, same stakes — plus the final score and the
 * net. Nothing here re-skins a settled wager as a transaction row.
 *
 * ── REV 1.4 · THE RAILS BECAME CAROUSELS ────────────────────────────────────
 *
 * A rail whose items were a fixed 216px wide showed one and a half cards on a
 * phone, and the half card was the defect: it reads as a rendering accident
 * rather than as an invitation to swipe, and it costs the visible card a third
 * of the width it needs to say what it is. Four of those stacked to 929px of
 * content inside a 534px viewport at 390x844, so a GM meeting Status for the
 * first time saw two lifecycle states and had to discover the other two.
 *
 * The fix is the geometry Wrap Up's result carousels already use: each item is
 * exactly 100% of its rail's width, so ONE card fills the viewport by
 * construction — at any card height, at any viewport width — and
 * `scroll-snap-stop: always` parks on the next one. There is no pixel constant
 * here to go stale and no arrangement in which a second card is partly visible.
 *
 * WHAT THIS FILE DOES NOT DO ABOUT IT. It sets no width, no height and no
 * padding: the geometry and the density both live in `tabs.css`, because a
 * carousel that expressed its own width in JavaScript would be a second opinion
 * about a layout the stylesheet already owns. What changed here is the heading
 * grammar (see `railHeading`) and one class name on the rail.
 * ========================================================================== */

import { attributionFooter } from './attribution.js';
import {
  PENDING_FIGURE, PanelComposer, accordion, bindAccordions, escapeHtml,
  sectionHeading, tabHeader,
} from './components.js';
import { counterStakeSheet } from './counter-stake.js';
import { headingWithPhase } from './phase.js';
import { SWIPE_WORD } from './league.js';
import { formatCredits, formatSignedCredits } from './credits.js';
import {
  RAILS,
  betThisWeekCents,
  cardsFor,
  lifecycleOf,
  seasonRecordLabel,
  settledCents,
  upsideLeftCents,
} from './data/action-data.js';
import {
  ACTION_MODE_AUTHORITATIVE,
  ACTION_MODE_UNAVAILABLE,
  actionIsEmpty,
  actionMode,
  committedCentsForWeek,
  sectionCards,
  sectionCount,
} from './action-model.js';
import { currentWeek } from './league-model.js';
import { marketFor } from './market-model.js';
import { previousSlateRows, slateRows } from './pool-slate-model.js';
import { explainBoardRefusal, refreshPairingContext } from './play-odds-refresh.js';
// §3B — the approved Matchup Preview lineup treatment, reused here.
import { lineupsBody } from './preview.js';
import { bindPreview, servedPreview } from './preview-model.js';
import { apiFetch, currentIdentity } from './session.js';
import { formatOdds } from './wager-model.js';
import { moneyFigure, wagerCard } from './wagercard.js';
import { onActivate } from './interaction.js';

/** Header string, locked by the Rev 4.2 handoff. */
export const ACTION_HEADER = 'WEEK 5 · REGULAR SEASON ACTION';

/**
 * The header a signed-in GM actually reads.
 *
 * `WEEK 5` IS A FIXTURE CONSTANT. It is hard-coded above and was rendered to
 * every authenticated GM regardless of the real week — the same defect class as
 * the season record, and found by the same audit. A GM in week 9 was told they
 * were looking at week 5.
 *
 * The week is a Week/League-domain fact and P4C-3 owns binding it, so Action
 * cannot source one without doing work this package was told not to do. What it
 * can do is stop asserting a week it does not know. The tab keeps its name and
 * drops the claim; demo is unchanged, because there the fixture IS the subject.
 *
 * @returns {string}
 */
export function actionHeader() {
  if (actionMode() === 'demo') return ACTION_HEADER;
  // S8-P4C-3: THE WEEK IS AUTHORITATIVE NOW, so the header may state it again.
  // P4C-2R dropped it because `WEEK 5` was a fixture constant with no source;
  // the provider has always stated its current week and the gateway now
  // persists it. Where no refresh has stated one the header still drops the
  // claim rather than guessing — the repair is not undone, it is satisfied.
  // WP3C — THE PHASE IS READ TOO, not only the week. S8-P4C-3 bound the week
  // and left `REGULAR SEASON` as a literal, so a league in its championship
  // week read `WEEK 16 · REGULAR SEASON ACTION`. `phase.js` resolves both from
  // the league's own boundaries and this surface writes neither.
  //
  // `ACTION` STAYS. Rev 4.3 §12.2 keeps it as content terminology on this
  // heading even though the tab is now named Status — it describes what the
  // page holds, and the nav label describes where the page is.
  return headingWithPhase(currentWeek(), 'ACTION');
}

/**
 * How the Response Card reaches the live commands.
 *
 * INSTALLED BY THE SHELL, and null in `demo` for the same reason the composer's
 * is: an isolated render must never be one click from accepting a real wager.
 * When it is null the sheet draws no controls and says why, rather than drawing
 * dead buttons.
 *
 * WP3C REPLACED `promptStake` WITH `availableCents`. The stake is now collected
 * by `counter-stake.js` in a product sheet, so the hook no longer supplies a
 * way to ASK for one — it supplies what the sheet needs to show, which is the
 * GM's spendable Credits, and the command to send.
 *
 * @type {null|{accept: Function, counter: Function, decline: Function,
 *              refresh: Function, explain: Function,
 *              availableCents: number|null}}
 */
let RESPOND_HOOK = null;

/** @param {null|object} hook */
export function setRespondHook(hook) {
  RESPOND_HOOK = hook;
}

/** @returns {boolean} whether live response commands are installed. */
export function respondBound() {
  return RESPOND_HOOK !== null;
}

/**
 * @returns {string}
 */
export function buildActionPanel() {
  const composer = new PanelComposer('action');

  composer.add(tabHeader({
    title: actionHeader(),
    sub: 'Your wagers — the only place you manage them',
  }));

  // Every figure is derived from the cards below, so the strip and the rails
  // cannot disagree.
  // THE STRIP IS ILLUSTRATIVE IN DEMO AND UNRESOLVED IN PRODUCTION, and there
  // is no third option yet. Every one of these four figures is week-scoped or
  // season-scoped:
  //
  // REVISITED IN S8-P4C-3, FIELD BY FIELD, now that the current week is
  // authoritative. Each was unresolved for its own reason and each was re-asked
  // on its own evidence — a new source for one of them does not resolve the
  // others.
  //
  //   Bet this week      BOUND. It needed a current week to scope to, and now
  //                      there is one. Every other input was already served:
  //                      the GM's own stake, the week, and whether the wager is
  //                      still open. Summed in the model from served fields.
  //
  //   Season Bet Record  STILL UNRESOLVED. This is the GM's WAGER record —
  //                      how many bets they have won and lost — not their
  //                      fantasy matchup record. P4C-3 bound the latter, and
  //                      substituting it here would put a different number
  //                      under this label. No settled-wager history read
  //                      exists.
  //
  //   Upside left        STILL UNRESOLVED, and not for want of a week. It is
  //                      what open wagers can still return, which needs a
  //                      payout figure per wager — and a Dynamic wager has no
  //                      Derived stake until Final Lock, so the total is
  //                      unknowable while any Dynamic wager is open. A figure
  //                      that silently meant "Locked wagers only" would be
  //                      worse than none.
  //
  //   Settled            STILL UNRESOLVED. `net_cents` is served per settled
  //                      card, so a sum is available — but the label means THIS
  //                      WEEK's settled wagers, and a settled wager's card
  //                      carries the week it was FOR. That is sourceable and is
  //                      left to the package that owns settled-wager history
  //                      rather than added here on the last day.
  //
  // `pending` is the approved unresolved treatment the Ledger's Awards / Adj.
  // cell uses: the cell keeps its place and its label, and draws — instead of a
  // number nobody measured.
  const unresolved = actionMode() !== 'demo';
  const betThisWeek = unresolved
    ? committedCentsForWeek(currentWeek())
    : betThisWeekCents();
  composer.addStrip({
    id: 'fs-strip-action',
    label: 'Action summary',
    cells: [
      // UIRECON WAVE 1 — one line at 320px, measured. `Season Bet Record`
      // was 108.8px against a 68px cell and `Bet this week` 77.4px; both
      // wrapped and stretched the whole strip. The scope each label lost to
      // the rewrite is already carried by the strip's own accessible name
      // (`Action summary`) and by the tab it sits on.
      { label: 'Bet Record', text: seasonRecordLabel(),
        pending: unresolved },
      { label: 'Staked', cents: betThisWeek ?? 0,
        pending: unresolved && betThisWeek === null },
      { label: 'Upside Left', cents: upsideLeftCents(), signed: true,
        pending: unresolved },
      { label: 'Settled', cents: settledCents(), signed: true, anchor: true,
        pending: unresolved },
    ],
  });

  composer.addDisclaimer();

  composer.add(
    `<div class="fs-rails" data-action-mode="${actionMode()}">` +
    RAILS.map((rail) => {
      const cards = cardsForRail(rail);
      const body = railBody(rail, cards);
      // WP5 — `role="list"` ONLY WHEN THE RAIL HOLDS LISTITEMS. An empty or
      // unavailable rail draws an explanatory paragraph instead of cards, and a
      // `<p>` inside `role="list"` is an ARIA violation: a list may hold only
      // listitems, so a screen reader is handed a list whose one child it
      // cannot place. The prototype never reached this because the illustrative
      // league always had cards in all four rails; a bound league routinely has
      // empty ones.
      //
      // An empty LIST is fine; a list with a non-listitem child is not. So the
      // role is dropped in exactly the case where there is nothing to list, and
      // the note is then an ordinary paragraph, which is what it is.
      const isList = body.includes('role="listitem"');
      // REV 1.4 — `data-rail-count` IS THE HEADING'S NUMBER, MACHINE-READABLE.
      // The count in the heading is a rendered string, and a suite that reads
      // it back out of the string is asserting against its own parse. The
      // attribute carries the same `sectionCount` call, so a certification can
      // compare the surface against `/league/{id}/action/me` without either
      // side going through a regular expression.
      return (
        `<section class="fs-railsec" data-rail="${rail}"` +
        ` data-rail-count="${cards.length}">` +
        sectionHeading(RAIL_WORDS[rail], railHelper(rail, cards.length)) +
        `<div class="fs-rail is-stretch fs-rail--carousel"` +
        `${isList ? ' role="list"' : ''}>` +
        body +
        '</div></section>'
      );
    }).join('') +
    '</div>',
  );

  // WP3D — Status names the opponent on every wager card and is scoped to the
  // provider's current week, both of which are Yahoo Fantasy Information. The
  // wagers, their terms and their economics are FantasyStakes'; the footer
  // attributes the league facts and says nothing about them.
  composer.add(attributionFooter());

  return composer.toHTML();
}

/** The locked rail words. One spelling, one place, four rails. */
// FINAL POR §28 — THE FOUR LOCKED CATEGORY NAMES.
//
// `WAITING` / `LIVE` / `COMPLETED` named three different kinds of thing: a
// state of mind, a state of play and a state of record. The locked set names
// the same four rails by the ACTION each one holds, so the column reads as one
// sentence four times over and a GM can tell at a glance which rail wants them.
const RAIL_WORDS = Object.freeze({
  action: 'ACTION REQUIRED',
  waiting: 'PENDING ACTION',
  live: 'LOCKED ACTION',
  completed: 'RESOLVED ACTION',
});

/**
 * The heading for one rail — `LABEL: N`, and nothing else.
 *
 * ── WHY THE FOUR HEADINGS NOW READ THE SAME WAY (Rev 1.4) ───────────────────
 *
 * Each rail is a CAROUSEL showing one card at a time, so the heading is the
 * only place a GM can learn how many cards are behind the one they are looking
 * at. That makes the count load-bearing rather than decorative, and a count a
 * reader has to hunt for in three different heading grammars is not one they
 * will trust. `LABEL: N` is the same sentence four times.
 *
 * WHAT THE COUNT IS. `sectionCount` and nothing else: in production the
 * server's own tally from `/league/{id}/action/me`, in demo the fixture's own
 * length. This module has never counted cards itself and still does not — if
 * the rendered rail and the served tally ever disagreed, the server is right
 * and the discrepancy is worth seeing.
 *
 * WHAT THE COMPLETED HEADING GAVE UP, AND WHY THAT IS NOT A LOSS. It used to
 * read `COMPLETED · 14–7 SEASON` in demo — a locked Rev 4.2 string whose season
 * record has been UNRESOLVED for signed-in GMs since S8-P4C-2, which is why
 * production already dropped it. Carrying it in demo alone meant the one rail
 * whose count a visitor most wants (seven settled Matchups) was the one rail
 * that did not state it, and it made the demo's heading grammar differ from the
 * product's. The record itself has not gone: `seasonRecordLabel()` still draws
 * it in the summary strip's Bet Record cell, which is a figure's slot rather
 * than a heading's.
 *
 * @param {string} rail
 * @returns {string}
 */
export function railHeading(rail) {
  const word = RAIL_WORDS[rail];
  if (!word) throw new Error(`unknown rail "${rail}"`);
  // FINAL POR §28 — `LABEL · N · SWIPE`.
  //
  // `LABEL: N` carried the count and said nothing about the affordance. Each
  // rail shows ONE card at a time, so a reader who does not know it swipes
  // cannot reach cards two and three at all — the count told them something
  // was there and not how to get to it. SWIPE is the same word Play and Wrap Up
  // already use, so the whole application states the affordance one way.
  return `${word} · ${sectionCount(rail)} · ${SWIPE_WORD}`;
}

/** Count/affordance slot shared with Play's canonical section heading. */
export function railHelper(rail, count = null) {
  if (!RAIL_WORDS[rail]) throw new Error(`unknown rail "${rail}"`);
  return `${count === null ? cardsForRail(rail).length : count} · ${SWIPE_WORD}`;
}

/**
 * The contents of one rail, in whichever production state applies.
 *
 * THE THREE STATES ARE DIFFERENT SENTENCES, and this is the only place that
 * decides which one a GM reads:
 *
 *   unavailable  the read failed — say so. Never illustrative cards, which
 *                would be indistinguishable from real wagers;
 *   empty        a real, successful read with nothing in it — a fact about the
 *                GM's week, not a failure;
 *   bound        the cards the server placed on this rail.
 *
 * @param {string} rail
 * @returns {string}
 */
function railBody(rail, cards = cardsForRail(rail)) {
  if (actionMode() === ACTION_MODE_UNAVAILABLE) {
    return '<p class="fs-rail__note" data-rail-state="unavailable">'
      + 'Your wagers could not be loaded. Nothing here is out of date — it is '
      + 'simply not available right now.</p>';
  }

  if (!cards.length) {
    const empty = actionMode() === ACTION_MODE_AUTHORITATIVE && actionIsEmpty();
    return '<p class="fs-rail__note" data-rail-state="empty">'
      + (empty ? 'No wagers yet this season.' : emptyRailCopy(rail))
      + '</p>';
  }
  return cards.map((card) => (
    `<div class="fs-rail__item" role="listitem">${card.kind === 'pool' ? poolLifecycleCard(card) : lifecycleCard(card)}</div>`
  )).join('');
}

function poolCardsForRail(rail) {
  if (actionMode() !== ACTION_MODE_AUTHORITATIVE) return [];
  const rows = rail === 'completed' ? previousSlateRows() : slateRows();
  return rows.filter((pool) => pool.mySubjectId != null)
    .filter((pool) => (pool.settled ? rail === 'completed' : rail === 'live'))
    .slice(0, 1)
    .map((pool) => ({ ...pool, kind: 'pool', id: `pool-${pool.poolInstanceId}` }));
}

function cardsForRail(rail) {
  return [...sectionCards(rail), ...poolCardsForRail(rail)];
}

function poolLifecycleCard(pool) {
  const picked = (pool.subjects || []).find((s) => s.subject_id === pool.mySubjectId);
  const result = pool.settled ? String(pool.myResult || 'settled').replace('_', ' ') : 'Entered';
  return wagerCard({
    identity: pool.name,
    context: `PROP POOL · ${result.toUpperCase()}`,
    badge: pool.settled ? 'RESOLVED' : 'LOCKED',
    badgeTone: pool.settled ? 'neutral' : 'positive',
    figures: [
      moneyFigure('Entry', pool.entryCents),
      moneyFigure('Pot', pool.potCents),
      ...(pool.settled ? [moneyFigure('Net', pool.myReturnCents || 0, { signed: true })] : []),
    ],
    copy: pool.settled ? 'Final Pool result.' : 'Entry locked until the Pool resolves.',
    footLabel: 'Your pick',
    footValue: picked ? picked.label : '—',
    accent: pool.settled ? 'done' : 'live',
    className: 'fs-wcard--lifecycle fs-wcard--pool-status',
    tapAction: 'pool-status',
    tapId: String(pool.poolInstanceId),
  });
}

function statusOddsAside(card) {
  if (actionMode() !== ACTION_MODE_AUTHORITATIVE) return '';
  if ((card.section || lifecycleOf(card)) !== 'action') return '';
  const locked = Number.isInteger(card.yourMoneyline) ? formatOdds(card.yourMoneyline) : '—';
  const current = marketFor(card.opponentTeamId);
  const now = current && current.available && Number.isInteger(current.acting_moneyline)
    ? formatOdds(current.acting_moneyline) : '—';
  return '<div class="fs-statusodds" data-status-odds>'
    + `<span>LOCKED <strong>${escapeHtml(locked)}</strong></span>`
    + `<span>NOW <strong data-status-current>${escapeHtml(now)}</strong></span>`
    + `<button type="button" data-status-refresh data-opponent-team-id="${escapeHtml(String(card.opponentTeamId))}" aria-label="Refresh current odds">↻</button>`
    + '</div>';
}

/** What an individual empty rail says when others have cards. */
function emptyRailCopy(rail) {
  switch (rail) {
    case 'action': return 'Nothing needs your decision.';
    case 'waiting': return 'Nothing waiting on anyone else.';
    case 'live': return 'No live wagers.';
    default: return 'Nothing completed yet.';
  }
}

/**
 * One wager card, in whichever lifecycle state it currently holds.
 *
 * @param {object} card
 * @returns {string}
 */
export function lifecycleCard(card) {
  // AN UNPRICED SIDE HAS NO FIGURE. In Dynamic the opponent's stake is set at
  // Final Lock, so before then there is no number to show — and the ceiling is
  // a BOUND, not the stake, so putting it in this slot would misreport it as
  // one. `pendingFigure` says what is true instead: it is set at kickoff.
  const figures = [
    moneyFigure('You', card.yourStakeCents),
    Number.isInteger(card.opponentStakeCents)
      ? moneyFigure('Them', card.opponentStakeCents)
      : pendingFigure('Them'),
    Number.isInteger(card.potCents)
      ? moneyFigure('Pot', card.potCents)
      : pendingFigure('Pot'),
  ];

  if (card.settled) {
    figures.push(moneyFigure('Net', card.netCents, {
      signed: true,
      tone: card.netCents >= 0 ? 'is-positive' : 'is-negative',
    }));
  }

  return wagerCard({
    identity: `vs ${card.opponent}`,
    // Mode is load-bearing on every card: the Locked/Dynamic distinction must
    // be visible before a GM acts, not in fine print (ruling §4).
    context: [card.marketLabel, card.line].filter(Boolean).join(' ')
      + ` · ${modeLabel(card)}`
      + (card.week ? ` · ${card.week}` : ''),
    figures,
    copy: card.copy || cardCopy(card),
    aside: statusOddsAside(card),
    badge: badgeFor(card),
    badgeTone: badgeToneFor(card),
    accent: accentFor(card),
    footLabel: footLabelFor(card),
    footValue: footValueFor(card),
    className: 'fs-wcard--lifecycle',
    interactiveAside: actionMode() === ACTION_MODE_AUTHORITATIVE
      && (card.section || lifecycleOf(card)) === 'action',
    tapAction: 'wager',
    tapId: card.id,
  });
}

/**
 * The card's sentence: what the wager is doing, and — in Dynamic — what is
 * still going to happen to it.
 *
 * THE MODE NOTE IS NOT OPTIONAL IN DYNAMIC, and that is a ruling rather than a
 * preference. S8-P4C-2R2 requires the Dynamic copy to name Final Lock as the
 * event and to stay neutral about WHOSE lineup supplies the earliest kickoff,
 * because the covered player who triggers the lock may be the opponent's — copy
 * that points at the GM's own players renders perfectly and is false for
 * exactly the GM whose starters all play late. So a Dynamic card keeps that
 * sentence and gains the state one; only a LOCKED card trades its mode note
 * away, and only because "Terms are frozen as offered. Neither side moves." is
 * the same true, inert sentence on all four rails.
 *
 * @param {object} card
 * @returns {string}
 */
function cardCopy(card) {
  const state = stateCopy(card);
  return card.mode === 'dynamic' ? `${state} ${modeCopy(card)}` : state;
}

/**
 * What this wager is DOING, in one sentence.
 *
 * ── WHY THE CARD STOPPED EXPLAINING THE MODE HERE ───────────────────────────
 *
 * This slot used to fall back to `modeCopy`, so in production every card on
 * every rail carried the same sentence — "Terms are frozen as offered. Neither
 * side moves." — whatever it was actually doing. Four rails exist to answer
 * four different questions, and a line that reads identically on all of them
 * answers none of them. The mode has NOT gone quiet: `modeLabel` puts FIXED or
 * FLOATING in the context line directly above, which is the ruling's
 * requirement that the distinction be visible before a GM acts, and the
 * Response Card still carries the full mode note in full.
 *
 * BUILT FROM SERVED VALUES, NEVER FROM A TEAM NAME THIS FILE KNOWS. The
 * opponent, the market and the week all arrive from the Action read model; this
 * only chooses the sentence frame. `card.copy` still wins where it is supplied,
 * which is how the illustrative fixture keeps its own per-state wording.
 *
 * @param {object} card
 * @returns {string}
 */
function stateCopy(card) {
  const opponent = card.opponent || 'your opponent';
  const market = card.marketLabel || 'Matchup';

  if (card.settled) {
    // The badge already says WON or LOST and the Net figure already says by how
    // much. This says where the Credits WENT, which neither of them does.
    if (card.outcome === 'won') {
      return 'Final. Credits posted to your Wallet.';
    }
    if (card.outcome === 'lost') {
      return 'Final. Your stake went to the pot.';
    }
    if (card.outcome === 'void') {
      return 'Voided. Your stake was returned.';
    }
    return 'Final. This Matchup is settled.';
  }

  if (card.protocolState === 'accepted') {
    // A Dynamic wager gets the plain sentence and lets `modeCopy` say what
    // Final Lock will do to it; a Locked one can say so itself, because there
    // is nothing still to happen to its terms.
    return card.mode === 'dynamic'
      ? 'This Matchup is live.'
      : 'Locked. This Matchup is live.';
  }

  if (card.protocolState === 'countered') {
    return card.viewerDecides
      ? `${opponent} countered. Accept it or decline — no re-counter.`
      : `You countered. It is with ${opponent} now.`;
  }

  if (card.protocolState === 'offered') {
    return card.viewerDecides
      ? `${opponent} sent you a ${market} Matchup.`
      : `Waiting for ${opponent} to respond.`;
  }

  if (card.protocolState === 'declined') return 'Declined. Nothing was staked.';
  if (card.protocolState === 'expired') {
    return 'Expired unanswered. Nothing was staked.';
  }
  return modeCopy(card);
}

/**
 * How the mode reads on the card.
 *
 * PLAIN WORDS, GOVERNED MEANING. A GM should be able to tell the two apart
 * without knowing what an Anchor is, so the card says FIXED or FLOATING rather
 * than naming the engine. The distinction it draws is the true one: in Locked
 * every term on the card is final, and in Dynamic one side is not yet priced.
 *
 * @param {object} card
 * @returns {string}
 */
function modeLabel(card) {
  return card.mode === 'dynamic' ? 'FLOATING' : 'FIXED';
}

/**
 * The one sentence that says what the mode means for this GM.
 *
 * THREE THINGS IT MUST NOT SAY, each of which would be false:
 *   · that the issuer's own stake may move — the Anchor is fixed in BOTH modes;
 *   · that accepting reprices anything — acceptance never reprices;
 *   · that both sides float — only the Derived side does.
 *
 * And it shows no predicted future price. The ceiling below is an authoritative
 * bound the backend wrote at the Handshake; a "likely" number would be a client
 * calculating a price, which is the one thing this layer may never do.
 *
 * WHEN, EXACTLY. GE-901 / AP-212: Final Lock occurs immediately before the
 * EARLIEST scheduled NFL kickoff involving any player in EITHER final Yahoo
 * starting lineup covered by the wager — "once any covered starting player
 * locks in Yahoo, the entire wager SHALL Final Lock."
 *
 * TWO WRONG ANSWERS HAVE ALREADY BEEN WRITTEN HERE, and both were wrong in the
 * same direction: they made the lock sound later and more predictable than it
 * is, on the one card where the timing IS the product.
 *
 *   "at kickoff" (S8-P4C-2) invited a GM to picture their own fantasy matchup
 *   starting on Sunday, when a covered Thursday-night starter locks the whole
 *   wager days earlier.
 *
 *   "when the first of YOUR players takes the field" (S8-P4C-2R) fixed the
 *   day and broke the ownership: the earliest covered player may be the
 *   OPPONENT's. A GM whose own starters all play Sunday would have been told
 *   they had until Sunday while their opponent's Thursday starter had already
 *   triggered it.
 *
 * The trigger is the earliest covered kickoff across BOTH lineups, and the copy
 * now says exactly that — "the first covered player's game", which is neutral
 * as to whose player it is. `Final Lock` is named because it is the product's
 * own term for the event, not engine jargon.
 *
 * @param {object} card
 * @returns {string}
 */
function modeCopy(card) {
  if (card.mode !== 'dynamic') {
    return 'Terms are frozen as offered. Neither side moves.';
  }
  const when = 'at Final Lock, just before the first covered player’s game begins';
  if (card.derivedCeilingCents !== null && card.derivedCeilingCents !== undefined) {
    return `Your opponent’s stake is set ${when}, up to `
      + `${formatCredits(card.derivedCeilingCents)}. Yours does not move.`;
  }
  return `Your opponent’s stake is set ${when}. Yours does not move.`;
}

/**
 * The Response Card's controls, for the GM whose decision it is.
 *
 * DRAWN FROM THE SERVER'S `controls`, which follow the decision owner rather
 * than the card's direction — so a countered wager offers them to the ISSUER
 * and not to the GM who countered. The server re-checks legality on every call
 * regardless; this only avoids drawing a button that could not work.
 *
 * @param {object} card
 * @returns {string}
 */
function responseControls(card) {
  if (!RESPOND_HOOK) {
    return '<div class="fs-note" data-respond-state="unbound">'
      + 'Sign in to act on this wager.</div>';
  }
  const controls = card.controls || [];
  if (!controls.length) {
    return '<div class="fs-note" data-respond-state="read-only">'
      + (card.settled || card.protocolState === 'accepted'
        ? 'This wager is no longer open to a decision.'
        : 'Waiting on your opponent.')
      + '</div>';
  }
  return '<div class="fs-respond" data-respond-block>'
    + '<div class="fs-respond__why" data-respond-why></div>'
    + controls.map((control) => (
      `<button type="button" class="fs-btn fs-respond__btn" `
      + `data-respond="${control}" data-challenge-id="${card.challengeId}">`
      + `${escapeHtml(CONTROL_WORDS[control] || control)}</button>`
    )).join('')
    + '</div>';
}

/**
 * Wire the Response Card's controls to the live commands.
 *
 * NO OPTIMISTIC TRANSITION. Every handler awaits the server, then awaits the
 * authoritative refresh, then closes. Nothing moves the card between rails or
 * edits a figure locally — the refreshed read is the only thing that redraws.
 */
function bindResponseControls(host, api, card) {
  if (!RESPOND_HOOK) return;
  const why = host.querySelector('[data-respond-why]');
  const buttons = [...host.querySelectorAll('[data-respond]')];

  buttons.forEach((button) => {
    button.addEventListener('click', async () => {
      const control = button.dataset.respond;
      // ALL OF THEM, not just the one clicked: while a decision is in flight no
      // other decision on the same wager may be started.
      buttons.forEach((b) => { b.disabled = true; });
      if (why) why.textContent = 'Sending…';
      try {
        if (control === 'accept') {
          await RESPOND_HOOK.accept(card.challengeId);
        } else if (control === 'decline') {
          await RESPOND_HOOK.decline(card.challengeId);
        } else {
          // COUNTER OPENS A SHEET LEVEL — Rev 4.3 SS12.4, WP3C SS15. It used to
          // call `window.prompt`, which showed the origin's hostname, could not
          // restate what was being countered, had no Credits grammar, and is
          // suppressed outright by several mobile browsers — where the control
          // then silently did nothing.
          //
          // THE SEND LIVES INSIDE THE SHEET, so this handler does not await a
          // stake and then send it. It hands the sheet the command and the
          // refresh; the sheet owns the exchange from there, which is what lets
          // a refusal be rendered beside the field the GM must correct rather
          // than behind a dialog that has already closed.
          buttons.forEach((b) => { b.disabled = false; });
          if (why) why.textContent = '';
          api.push(() => counterStakeSheet({
            card,
            availableCents: RESPOND_HOOK.availableCents ?? null,
            explain: RESPOND_HOOK.explain,
            onSubmit: async (cents) => {
              await RESPOND_HOOK.counter(card.challengeId, cents);
              await RESPOND_HOOK.refresh();
              api.close();
            },
          }));
          return;
        }
        await RESPOND_HOOK.refresh();
        api.close();
      } catch (error) {
        buttons.forEach((b) => { b.disabled = false; });
        if (why) why.textContent = RESPOND_HOOK.explain(error);
      }
    });
  });
}

/**
 * A figure that has no authoritative value yet.
 *
 * NOT ZERO, and not a guess. `$0` would assert that the opponent stakes
 * nothing, which is false; a projected number would be this layer pricing a
 * wager. The em dash is the approved unresolved treatment and carries no
 * `exactCents`, so nothing downstream can mistake it for a figure.
 */
function pendingFigure(label) {
  return { label, value: '—', exactCents: null };
}

function badgeFor(card) {
  if (card.settled && card.outcome === 'void') return 'VOIDED';
  if (card.settled) return card.won ? 'WON' : 'LOST';
  if (card.protocolState === 'accepted') return String(card.status || 'live').toUpperCase();
  if (card.protocolState === 'countered') return 'COUNTERED';
  if (card.protocolState === 'declined') return 'DECLINED';
  if (card.protocolState === 'expired') return 'EXPIRED';
  return card.role === 'recipient' ? 'INCOMING' : 'SENT';
}

function badgeToneFor(card) {
  if (card.settled && card.outcome === 'void') return 'neutral';
  if (card.settled) return card.won ? 'positive' : 'negative';
  if (card.protocolState === 'accepted') {
    return ['ahead', 'covering'].includes(card.status) ? 'positive'
      : (['behind'].includes(card.status) ? 'negative' : 'neutral');
  }
  return 'gold';
}

/**
 * The left-edge accent follows the rail, and the rail follows the protocol
 * state through `lifecycleOf` — the one place that mapping lives. Re-deriving
 * it here would let a card's colour disagree with the rail it sits on.
 */
const ACCENT_BY_RAIL = Object.freeze({
  action: 'action',
  waiting: 'waiting',
  live: 'live',
  completed: 'done',
});

function accentFor(card) {
  // THE SERVED SECTION FIRST. A production card already knows which rail it is
  // on — the backend decided — and asking the illustrative classifier again
  // would both duplicate the rule and fail outright on the terminal states a
  // fixture never reaches. `lifecycleOf` remains for the demo cards, which
  // carry no section of their own.
  return ACCENT_BY_RAIL[card.section || lifecycleOf(card)];
}

function footLabelFor(card) {
  if (card.settled) return card.score || 'Final';
  if (card.protocolState === 'accepted') return card.score || 'Live';
  // A production card carries real escrow rather than a `held` flag, and Held
  // is exactly what an open challenge's escrow IS.
  if (card.escrowCents) return `Held · ${formatCredits(card.escrowCents)}`;
  return card.held ? 'Held · ' + card.expiresIn : (card.expiresIn || '');
}

function footValueFor(card) {
  if (card.settled) return formatSignedCredits(card.netCents);
  if (card.protocolState === 'accepted') return String(card.status || '').toUpperCase();
  if (card.actions) return card.actions.join(' · ');
  // WHAT THIS GM MAY DO, from the server's own `controls`. Derived from the
  // decision owner rather than from direction, so a countered card correctly
  // offers the ISSUER the controls and the counterer none.
  if (card.controls && card.controls.length) {
    return card.controls.map((c) => CONTROL_WORDS[c] || c).join(' · ');
  }
  return 'Read-only';
}

/** The product's words for the three governed commands. */
const CONTROL_WORDS = Object.freeze({
  accept: 'Take it', counter: 'Counter', decline: 'Decline',
});

/**
 * Wire Action's cards. Tapping a card opens its detail in the shared sheet.
 *
 * @param {HTMLElement} panel
 * @param {{openSheet: Function}} api
 */
export function bindAction(panel, api) {
  panel.querySelectorAll('[data-status-refresh]').forEach((button) => {
    button.addEventListener('click', async (event) => {
      event.preventDefault();
      event.stopPropagation();
      button.disabled = true;
      try {
        await refreshPairingContext(Number(button.dataset.opponentTeamId));
        const row = marketFor(Number(button.dataset.opponentTeamId));
        const value = button.closest('[data-status-odds]')?.querySelector('[data-status-current]');
        if (value) value.textContent = row && row.available && Number.isInteger(row.acting_moneyline)
          ? formatOdds(row.acting_moneyline) : '—';
      } finally {
        button.disabled = false;
      }
    });
  });

  panel.querySelectorAll('[data-card-action="pool-status"]').forEach((el) => {
    onActivate(el, () => {
      const pool = [...slateRows(), ...previousSlateRows()]
        .find((row) => String(row.poolInstanceId) === el.dataset.cardId);
      if (pool) api.openSheet(poolStatusSheet(pool));
    });
  });
  panel.querySelectorAll('[data-card-action="wager"]').forEach((el) => {
    onActivate(el, () => {
      // THE BOUND CARDS, not the fixture's. In production `sectionCards`
      // returns the served rows, so tapping opens the real wager's detail;
      // reading `cardsFor` here would have opened an illustrative sheet over a
      // production card, which is the exact confusion the modes exist to stop.
      const card = RAILS.flatMap((r) => sectionCards(r))
        .find((c) => c.id === el.dataset.cardId);
      if (card) api.openSheet(wagerSheet(card));
    });
  });
}

/**
 * The wager-detail sheet. Exported so The Week opens the SAME detail for the
 * same wager rather than growing a second, drifting description of it.
 *
 * @param {object} card
 * @returns {{title: string, sub: string, body: string}}
 */
/* ── FINAL POR (FREEZE) §3 · THE DECISION WORKSPACE ─────────────────────────
 *
 * The three FantasyStakes markets, priced two ways, above the lineups the
 * price rests on, above the three things a GM can do about it.
 *
 * WHY TWO COLUMNS RATHER THAN ONE THAT CHANGES. A single set of numbers that
 * silently became "current" after a refresh is exactly the failure this
 * structure exists to prevent: the reader could no longer see what they had
 * been offered. Both are always on screen, the selected one is marked, and the
 * offer column is rendered from the served card every time. */
const ODDS_VIEWS = Object.freeze({ original: 'ORIGINAL OFFER', refreshed: 'REFRESHED ODDS' });

/** A market's three rows, for one pricing view. */
function marketLines(card, board) {
  const dash = PENDING_FIGURE;
  const ml = (v) => (Number.isInteger(v) ? formatOdds(v) : dash);
  const num = (v) => (typeof v === 'number' ? (v > 0 ? `+${v}` : String(v)) : dash);
  const tot = (v) => (typeof v === 'number' ? String(v) : dash);

  // THE OFFER COLUMN IS THE CARD, NOT THE BOARD. `card.yourMoneyline` is what
  // the proposal locked; the spread and total it was sent with are the card's
  // own line where the offered market is that market, and unquoted otherwise —
  // an offer prices ONE market, and inventing the other two would be inventing
  // terms nobody sent.
  const offeredIs = (kind) => String(card.marketId || card.marketLabel || '')
    .toLowerCase().includes(kind);

  return {
    original: [
      ['Moneyline', ml(card.yourMoneyline)],
      ['Spread', offeredIs('spread') ? String(card.line || dash) : dash],
      ['Over/Under', offeredIs('total') || offeredIs('over') || offeredIs('under')
        ? String(card.line || dash) : dash],
    ],
    refreshed: [
      ['Moneyline', board ? ml(board.acting_moneyline) : dash],
      ['Spread', board ? num(board.acting_spread) : dash],
      ['Over/Under', board ? tot(board.total_line) : dash],
    ],
  };
}

function oddsAndMarkets(card) {
  const board = marketFor(card.opponentTeamId);
  const lines = marketLines(card, board);

  const column = (view) => lines[view].map(([label, value]) => (
    '<div class="fs-odds__row">'
    + `<span class="fs-odds__market">${escapeHtml(label)}</span>`
    + `<span class="fs-odds__value fs-money">${escapeHtml(value)}</span>`
    + '</div>'
  )).join('');

  const tab = (view) => (
    `<button type="button" class="fs-odds__tab" data-odds-view="${view}"`
    + `${view === 'original' ? ' aria-pressed="true" data-selected="true"' : ' aria-pressed="false"'}>`
    + `${escapeHtml(ODDS_VIEWS[view])}</button>`
  );

  return collapsibleSection('ODDS & MARKETS',
    '<div class="fs-odds__tabs" role="group" aria-label="Pricing view">'
    + tab('original') + tab('refreshed')
    + '</div>'
    + '<div class="fs-odds__panel" data-odds-panel="original">' + column('original') + '</div>'
    + '<div class="fs-odds__panel" data-odds-panel="refreshed" hidden>' + column('refreshed') + '</div>'
    + '<div class="fs-odds__foot">'
    + '<button type="button" class="fs-odds__refresh" data-odds-refresh '
    + `data-opponent-team-id="${escapeHtml(String(card.opponentTeamId))}">REFRESH ODDS</button>`
    + '<span class="fs-odds__asof" data-odds-asof>'
    + escapeHtml(board && board.available ? 'Current board' : 'Not refreshed yet')
    + '</span>'
    + '</div>'
    // THE RULE, ON THE SURFACE. A GM must not have to infer that refreshing is
    // safe, and must not believe that Take it follows the refreshed number.
    + '<div class="fs-note">Take it always accepts the original offer above. '
    + 'Refreshed odds are for information — to act on them, send a Counter.</div>',
    { open: true });
}

/** One accordion, in the Preview family — the same shell §3's two sections use. */
function collapsibleSection(title, bodyHtml, options = {}) {
  return accordion({
    title,
    bodyHtml,
    open: options.open === true,
    className: 'fs-prev',
  });
}

/* §3B — THE APPROVED MATCHUP PREVIEW LINEUPS, REUSED RATHER THAN REBUILT.
 *
 * Drawn from whatever preview is bound when the sheet opens, and repainted in
 * place once this pairing's own read lands. The unbound state is Preview's own
 * sentence, not a placeholder roster. */
function lineupsAccordion(card) {
  return collapsibleSection('LINEUPS',
    `<div data-lineups-body>${lineupsBody(servedPreview(), {
      you: 'You', them: card.opponent,
    })}</div>`, { open: false });
}

/** Fetch this pairing's preview and repaint the lineups in place. */
function loadLineups(host, card) {
  const slot = host.querySelector('[data-lineups-body]');
  if (!slot) return;
  /* THE LEAGUE AND THE WEEK, WITHOUT IMPORTING THE SHELL. `shell.js` imports
   * this module, so reaching back into it for `currentLeagueId` would close an
   * import cycle. Both facts are available from the models this file already
   * depends on: the week is the league's authoritative one, and the acting
   * league is the identity's own — the same two values the shell reads. */
  const identity = currentIdentity();
  const caps = (identity && identity.capabilities) || {};
  const leagueId = caps.acting_context_ambiguous
    ? null
    : (typeof caps.acting_league_id === 'number' ? caps.acting_league_id : null);
  const week = currentWeek();
  if (leagueId === null || week === null || !Number.isInteger(card.opponentTeamId)) return;
  apiFetch(`/league/${leagueId}/versus/preview`
    + `?week=${week}&opponent_team_id=${card.opponentTeamId}`)
    .then((view) => {
      bindPreview(view);
      slot.innerHTML = lineupsBody(servedPreview(), { you: 'You', them: card.opponent });
    })
    .catch(() => { /* the unbound sentence already standing is the honest state */ });
}

export function wagerSheet(card) {
  // A DERIVED STAKE THAT IS NOT YET PRICED HAS NO NUMBER. In Dynamic the
  // opponent's side is set at Final Lock, so the sheet says so rather than
  // printing a placeholder that would read as a quote.
  const SET_AT_LOCK = 'Set at Final Lock';
  const theirStake = (card.opponentStakeCents === null
    || card.opponentStakeCents === undefined)
    ? SET_AT_LOCK
    : formatCredits(card.opponentStakeCents);
  const pot = (card.potCents === null || card.potCents === undefined)
    ? SET_AT_LOCK
    : formatCredits(card.potCents);

  const rowHtml = ([label, value]) => (
    '<div class="fs-prev__row">' +
    `<span class="fs-prev__label">${escapeHtml(label)}</span>` +
    `<span class="fs-prev__value fs-money">${escapeHtml(value)}</span>` +
    '</div>'
  );

  const termRows = [
    ['Terms', String(card.mode || 'locked').toUpperCase()],
    ['Your stake', formatCredits(card.yourStakeCents)],
    ['Their stake', theirStake],
    ['Pot', pot],
  ];
  if (card.mode === 'dynamic' && Number.isInteger(card.derivedCeilingCents)) {
    termRows.push(['Their stake ceiling', formatCredits(card.derivedCeilingCents)]);
  }
  if (card.settled) termRows.push(['Net', formatSignedCredits(card.netCents)]);
  if (card.expiresIn) termRows.push(['Expires', card.expiresIn]);

  const decidable = (card.section || lifecycleOf(card)) === 'action';

  return {
    title: `vs ${card.opponent}`,
    sub: `${card.marketLabel} ${card.line} · ${String(card.mode || 'locked').toUpperCase()}`,
    body:
      // §3 — ODDS & MARKETS FIRST, LINEUPS SECOND, CONTROLS LAST.
      (decidable ? oddsAndMarkets(card) : '')
      + (decidable ? lineupsAccordion(card) : '')
      + collapsibleSection('THIS OFFER',
        termRows.map(rowHtml).join('')
        + `<div class="fs-note">${escapeHtml(card.copy || modeCopy(card))}</div>`,
        { open: !decidable })
      + responseControls(card),
    onMount: (host, api) => {
      bindResponseControls(host, api, card);
      bindOddsView(host, card);
      bindAccordions(host);
      loadLineups(host, card);
    },
  };
}

/* The pricing-view toggle and REFRESH ODDS, bound.
 *
 * REFRESH REPAINTS THE REFRESHED COLUMN AND NOTHING ELSE. It does not touch
 * `card`, it does not touch the original column, and it does not re-render the
 * sheet — so the offer a GM is looking at cannot change underneath them. */
function bindOddsView(host, card) {
  const panels = {
    original: host.querySelector('[data-odds-panel="original"]'),
    refreshed: host.querySelector('[data-odds-panel="refreshed"]'),
  };
  const select = (view) => {
    Object.entries(panels).forEach(([name, el]) => {
      if (el) el.hidden = name !== view;
    });
    host.querySelectorAll('[data-odds-view]').forEach((b) => {
      const on = b.dataset.oddsView === view;
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      if (on) b.setAttribute('data-selected', 'true');
      else b.removeAttribute('data-selected');
    });
  };
  host.querySelectorAll('[data-odds-view]').forEach((b) => {
    b.addEventListener('click', () => select(b.dataset.oddsView));
  });

  const refresh = host.querySelector('[data-odds-refresh]');
  if (!refresh) return;
  refresh.addEventListener('click', async () => {
    const asOf = host.querySelector('[data-odds-asof]');
    refresh.disabled = true;
    if (asOf) asOf.textContent = 'Refreshing…';
    try {
      await refreshPairingContext(Number(refresh.dataset.opponentTeamId));
      const board = marketFor(card.opponentTeamId);
      const lines = marketLines(card, board);
      const panel = panels.refreshed;
      if (panel) {
        panel.innerHTML = lines.refreshed.map(([label, value]) => (
          '<div class="fs-odds__row">'
          + `<span class="fs-odds__market">${escapeHtml(label)}</span>`
          + `<span class="fs-odds__value fs-money">${escapeHtml(value)}</span>`
          + '</div>'
        )).join('');
      }
      if (asOf) asOf.textContent = board && board.available ? 'Refreshed just now' : 'No board available';
      select('refreshed');
    } catch (error) {
      if (asOf) asOf.textContent = explainBoardRefusal(error);
    } finally {
      refresh.disabled = false;
    }
  });
}

function poolStatusSheet(pool) {
  const picked = (pool.subjects || []).find((s) => s.subject_id === pool.mySubjectId);
  return {
    title: pool.name,
    sub: pool.settled ? 'Resolved Prop Pool' : 'Locked Prop Pool entry',
    body: '<div class="fs-prev__row"><span class="fs-prev__label">Your pick</span>'
      + `<span class="fs-prev__value">${escapeHtml(picked ? picked.label : '—')}</span></div>`
      + '<div class="fs-prev__row"><span class="fs-prev__label">Pot</span>'
      + `<span class="fs-prev__value fs-money">${escapeHtml(formatCredits(pool.potCents))}</span></div>`
      + '<div class="fs-note">Status is read from the governed Pool entry and settlement record. Pool picks are made on Play.</div>',
  };
}
