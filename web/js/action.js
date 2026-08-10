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

import { PanelComposer, escapeHtml, sectionHeading, tabHeader } from './components.js';
import { formatCredits, formatSignedCredits } from './credits.js';
import {
  RAILS,
  betThisWeekCents,
  cardsFor,
  lifecycleOf,
  railHeading,
  seasonRecordLabel,
  settledCents,
  upsideLeftCents,
} from './data/action-data.js';
import { moneyFigure, wagerCard } from './wagercard.js';
import { onActivate } from './interaction.js';

/** Header string, locked by the Rev 4.2 handoff. */
export const ACTION_HEADER = 'WEEK 5 · REGULAR SEASON ACTION';

/**
 * @returns {string}
 */
export function buildActionPanel() {
  const composer = new PanelComposer('action');

  composer.add(tabHeader({
    title: ACTION_HEADER,
    sub: 'Your wagers — the only place you manage them',
  }));

  // Every figure is derived from the cards below, so the strip and the rails
  // cannot disagree.
  composer.addStrip({
    id: 'fs-strip-action',
    label: 'Action summary',
    cells: [
      { label: 'Season Bet Record', text: seasonRecordLabel() },
      { label: 'Bet this week', cents: betThisWeekCents() },
      { label: 'Upside left', cents: upsideLeftCents(), signed: true },
      { label: 'Settled', cents: settledCents(), signed: true, anchor: true },
    ],
  });

  composer.addDisclaimer();

  composer.add(
    '<div class="fs-rails">' +
    RAILS.map((rail) => (
      `<section class="fs-railsec" data-rail="${rail}">` +
      sectionHeading(railHeading(rail)) +
      `<div class="fs-rail is-stretch" role="list">` +
      cardsFor(rail).map((card) => (
        `<div class="fs-rail__item" role="listitem">${lifecycleCard(card)}</div>`
      )).join('') +
      '</div></section>'
    )).join('') +
    '</div>',
  );

  return composer.toHTML();
}

/**
 * One wager card, in whichever lifecycle state it currently holds.
 *
 * @param {object} card
 * @returns {string}
 */
export function lifecycleCard(card) {
  const figures = [
    moneyFigure('You', card.yourStakeCents),
    moneyFigure('Them', card.opponentStakeCents),
    moneyFigure('Pot', card.potCents),
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
    context: `${card.marketLabel} ${card.line} · ${card.mode.toUpperCase()}` +
      (card.week ? ` · ${card.week}` : ''),
    figures,
    copy: card.copy,
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

function badgeFor(card) {
  if (card.settled) return card.won ? 'WON' : 'LOST';
  if (card.protocolState === 'accepted') return String(card.status || 'live').toUpperCase();
  if (card.protocolState === 'countered') return 'COUNTERED';
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
  return ACCENT_BY_RAIL[lifecycleOf(card)];
}

function footLabelFor(card) {
  if (card.settled) return card.score;
  if (card.protocolState === 'accepted') return card.score;
  return card.held ? 'Held · ' + card.expiresIn : card.expiresIn;
}

function footValueFor(card) {
  if (card.settled) return formatSignedCredits(card.netCents);
  if (card.protocolState === 'accepted') return String(card.status || '').toUpperCase();
  return card.actions ? card.actions.join(' · ') : 'Read-only';
}

/**
 * Wire Action's cards. Tapping a card opens its detail in the shared sheet.
 *
 * @param {HTMLElement} panel
 * @param {{openSheet: Function}} api
 */
export function bindAction(panel, api) {
  panel.querySelectorAll('[data-card-action="wager"]').forEach((el) => {
    onActivate(el, () => {
      const card = RAILS.flatMap((r) => cardsFor(r)).find((c) => c.id === el.dataset.cardId);
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
  const rows = [
    ['Market', `${card.marketLabel} ${card.line}`],
    ['Terms', card.mode.toUpperCase()],
    ['Your stake', formatCredits(card.yourStakeCents)],
    ['Their stake', formatCredits(card.opponentStakeCents)],
    ['Pot', formatCredits(card.potCents)],
  ];
  if (card.score) rows.push([card.settled ? 'Final' : 'Live', card.score]);
  if (card.settled) rows.push(['Net', formatSignedCredits(card.netCents)]);
  if (card.expiresIn) rows.push(['Expires', card.expiresIn]);

  // The protocol state is shown as itself. A rail name is where a card sits,
  // not what it is.
  rows.push(['Protocol state', card.protocolState]);
  rows.push(['Response card', card.responseCard]);

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
      `<div class="fs-note">${escapeHtml(card.copy)}</div>` +
      '<div class="fs-note">Deciding on a wager binds to the proposal lifecycle ' +
      'when the session seam lands. Nothing here moves Credits.</div>',
  };
}