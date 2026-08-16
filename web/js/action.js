/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · Action
 * Sprint 7 Package 2
 *
 * Four single-row horizontal rails — ACTION REQUIRED, WAITING, LIVE,
 * COMPLETED — over the same wager-card grammar League uses. Because each rail
 * is one row, a card can afford to be taller and say more; it does not become
 * a different card.
 *
 * A COMPLETED card is the LIVE card that preceded it, showing later figures.
 * Same identity, same market row, same stakes — plus the final score and the
 * net. Nothing here re-skins a settled wager as a transaction row.
 * ========================================================================== */

import { attributionFooter } from './attribution.js';
import { PanelComposer, escapeHtml, sectionHeading, tabHeader } from './components.js';
import { counterStakeSheet } from './counter-stake.js';
import { headingWithPhase } from './phase.js';
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
      { label: 'Season Bet Record', text: seasonRecordLabel(),
        pending: unresolved },
      { label: 'Bet this week', cents: betThisWeek ?? 0,
        pending: unresolved && betThisWeek === null },
      { label: 'Upside left', cents: upsideLeftCents(), signed: true,
        pending: unresolved },
      { label: 'Settled', cents: settledCents(), signed: true, anchor: true,
        pending: unresolved },
    ],
  });

  composer.addDisclaimer();

  composer.add(
    `<div class="fs-rails" data-action-mode="${actionMode()}">` +
    RAILS.map((rail) => {
      const body = railBody(rail);
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
      return (
        `<section class="fs-railsec" data-rail="${rail}">` +
        sectionHeading(railHeading(rail)) +
        `<div class="fs-rail is-stretch"${isList ? ' role="list"' : ''}>` +
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

/**
 * The heading for one rail, counting BOUND state.
 *
 * The illustrative `2 / 2 / 4` are the fixture's counts and are correct only
 * for the fixture. In production the count comes from the server's own tally —
 * see `sectionCount`.
 *
 * @param {string} rail
 * @returns {string}
 */
export function railHeading(rail) {
  switch (rail) {
    case 'action': return `ACTION REQUIRED ${sectionCount('action')}`;
    case 'waiting': return `WAITING ${sectionCount('waiting')}`;
    case 'live': return `LIVE ${sectionCount('live')}`;
    // COMPLETED CARRIES THE SEASON RECORD ONLY IN DEMO.
    //
    // The locked Rev 4.2 heading is `COMPLETED · 14–7 SEASON`, and 14–7 is a
    // fixture constant with no authoritative source — S8-P4C-2 classified it
    // UNRESOLVED and then went on rendering it to signed-in GMs, which is the
    // seam this repair closes. A GM reading their own Action tab would have
    // seen someone else's season record presented as theirs.
    //
    // In production the heading keeps its place in the hierarchy and drops the
    // claim. NOT `0–0`, which asserts a real record of no games; not a card
    // count relabelled as a record, which would be a different figure wearing
    // this one's name. P4C-3 may restore a real record if a provider or history
    // source turns out to supply one.
    case 'completed':
      return actionMode() === 'demo'
        ? `COMPLETED · ${seasonRecordLabel()} SEASON`
        : 'COMPLETED';
    default: throw new Error(`unknown rail "${rail}"`);
  }
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
function railBody(rail) {
  if (actionMode() === ACTION_MODE_UNAVAILABLE) {
    return '<p class="fs-rail__note" data-rail-state="unavailable">'
      + 'Your wagers could not be loaded. Nothing here is out of date — it is '
      + 'simply not available right now.</p>';
  }

  const cards = sectionCards(rail);
  if (!cards.length) {
    const empty = actionMode() === ACTION_MODE_AUTHORITATIVE && actionIsEmpty();
    return '<p class="fs-rail__note" data-rail-state="empty">'
      + (empty ? 'No wagers yet this season.' : emptyRailCopy(rail))
      + '</p>';
  }
  return cards.map((card) => (
    `<div class="fs-rail__item" role="listitem">${lifecycleCard(card)}</div>`
  )).join('');
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
    context: `${card.marketLabel} ${card.line} · ${modeLabel(card)}` +
      (card.week ? ` · ${card.week}` : ''),
    figures,
    copy: card.copy || modeCopy(card),
    badge: badgeFor(card),
    badgeTone: badgeToneFor(card),
    accent: accentFor(card),
    footLabel: footLabelFor(card),
    footValue: footValueFor(card),
    className: 'fs-wcard--lifecycle',
    tapAction: 'wager',
    tapId: card.id,
  });
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
  if (card.settled) return card.won ? 'WON' : 'LOST';
  if (card.protocolState === 'accepted') return String(card.status || 'live').toUpperCase();
  if (card.protocolState === 'countered') return 'COUNTERED';
  if (card.protocolState === 'declined') return 'DECLINED';
  if (card.protocolState === 'expired') return 'EXPIRED';
  return card.role === 'recipient' ? 'INCOMING' : 'SENT';
}

function badgeToneFor(card) {
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
export function wagerSheet(card) {
  // A DERIVED STAKE THAT IS NOT YET PRICED HAS NO NUMBER. In Dynamic the
  // opponent's side is set at Final Lock, so the sheet says so rather than
  // printing a placeholder that would read as a quote. The wording matches
  // `modeCopy` — see the note there on why "at kickoff" was wrong.
  const SET_AT_LOCK = 'Set at Final Lock';
  const theirStake = (card.opponentStakeCents === null
    || card.opponentStakeCents === undefined)
    ? SET_AT_LOCK
    : formatCredits(card.opponentStakeCents);
  const pot = (card.potCents === null || card.potCents === undefined)
    ? SET_AT_LOCK
    : formatCredits(card.potCents);

  const rows = [
    ['Market', `${card.marketLabel} ${card.line}`],
    ['Terms', card.mode.toUpperCase()],
    ['Your stake', formatCredits(card.yourStakeCents)],
    ['Their stake', theirStake],
    ['Pot', pot],
  ];
  if (card.mode === 'dynamic' && Number.isInteger(card.derivedCeilingCents)) {
    // THE CEILING IS AUTHORITATIVE — the backend wrote it at the Handshake. It
    // is the most a GM's opponent can end up staking, and it is a bound rather
    // than a prediction.
    rows.push(['Their stake ceiling', formatCredits(card.derivedCeilingCents)]);
  }
  if (card.score) rows.push([card.settled ? 'Final' : 'Live', card.score]);
  if (card.settled) rows.push(['Net', formatSignedCredits(card.netCents)]);
  if (card.expiresIn) rows.push(['Expires', card.expiresIn]);

  // The protocol state is shown as itself. A rail name is where a card sits,
  // not what it is.
  rows.push(['Protocol state', card.protocolState]);
  // The locked Response Card word — served as `status` in production, carried
  // as `responseCard` by the illustrative fixture. Same five-word vocabulary.
  rows.push(['Response card', card.responseCard || card.status || '—']);

  return {
    title: `vs ${card.opponent}`,
    sub: `${card.marketLabel} ${card.line} · ${card.mode.toUpperCase()}`,
    body:
      rows.map(([label, value]) => (
        '<div class="fs-prev__row">' +
        `<span class="fs-prev__label">${escapeHtml(label)}</span>` +
        `<span class="fs-prev__value fs-money">${escapeHtml(value)}</span>` +
        '</div>'
      )).join('') +
      `<div class="fs-note">${escapeHtml(card.copy || modeCopy(card))}</div>` +
      responseControls(card),
    onMount: (host, api) => bindResponseControls(host, api, card),
  };
}