/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · shared wager-card grammar
 * Sprint 7 Package 2
 *
 * ONE card grammar for every wager surface. League's FantasyStakes Bets
 * carousel and all four Action lifecycle rails render the same element
 * structure in the same order:
 *
 *     identity  →  context  →  market row  →  figures  →  line of copy  →  foot
 *
 * A wager therefore keeps its identity from the moment it is offered to the
 * moment it settles. That is the point of putting this in one place: a
 * COMPLETED card is the same card as the LIVE card that preceded it, showing
 * later figures — not an unrelated transaction row.
 *
 * Pure functions to HTML. No DOM, no state.
 * ========================================================================== */

import { PENDING_FIGURE, escapeHtml } from './components.js';
import { formatCredits, formatSignedCredits } from './credits.js';
import { MARKETS, formatOdds } from './wager-model.js';
import { formatSpread, hasQuotedMoneyline } from './narrative.js';

/**
 * @typedef {object} MarketCell
 * @property {string} id      market id — ml | spread | ou
 * @property {string} label   ML | SPR | O/U
 * @property {string} value   the drawn line
 * @property {string} [tone]  fav | dog | neu
 * @property {boolean} [selected]
 */

/**
 * The three-cell market row.
 *
 * When `interactive` is set each cell is a button carrying `data-market`, so a
 * market tap is distinguishable from a whole-card tap by the surface that
 * binds them — and both reach the same composer.
 *
 * @param {MarketCell[]} cells
 * @param {{interactive?: boolean}} [options]
 * @returns {string}
 */
export function marketRow(cells, options = {}) {
  const { interactive = false } = options;
  return (
    '<div class="fs-markets">' +
    cells.map((cell) => {
      const classes = ['fs-market'];
      if (cell.tone) classes.push(`is-${cell.tone}`);
      if (cell.selected) classes.push('is-selected');
      const inner =
        `<span class="fs-market__label">${escapeHtml(cell.label)}</span>` +
        `<span class="fs-market__value">${escapeHtml(cell.value)}</span>`;
      return interactive
        ? `<button type="button" class="${classes.join(' ')}" data-market="${escapeHtml(cell.id)}">${inner}</button>`
        : `<div class="${classes.join(' ')}">${inner}</div>`;
    }).join('') +
    '</div>'
  );
}

/**
 * Market cells for a League matchup, from your side of the line.
 *
 * @param {object} m
 * @returns {MarketCell[]}
 */
/** The card-cell abbreviation for one market — one spelling, one place. */
function shortLabel(id) {
  const market = MARKETS.find((x) => x.id === id);
  return market ? market.short : id.toUpperCase();
}

export function matchupMarketCells(m) {
  // The moneyline is the one cell that may be unquoted: it comes from the
  // pricing engine, while the spread and total are arithmetic on projections
  // this build already holds. An unquoted cell draws as unresolved.
  //
  // WP3C — ALL THREE MAY NOW BE UNRESOLVED. Rev 4.2's carousel was eleven
  // fixture opponents, so the spread and the total were always present; Play
  // now discovers real opponents (§4) and no read model publishes a board of
  // lines per pairing. A quote exists once the composer prices the market the
  // GM chooses, and until then the honest cell is a dash — not a zero, and not
  // a number computed here from nothing.
  const quoted = hasQuotedMoneyline(m);
  const hasSpread = typeof m.spread === 'number';
  const hasTotal = typeof m.total === 'number';
  return [
    {
      id: 'ml',
      label: shortLabel('ml'),
      value: quoted ? formatOdds(m.ml) : PENDING_FIGURE,
      tone: quoted ? (m.ml < 0 ? 'fav' : 'dog') : 'neu',
    },
    { id: 'spread',
      label: shortLabel('spread'),
      value: hasSpread ? formatSpread(m.spread) : PENDING_FIGURE,
      tone: hasSpread ? (m.spread < 0 ? 'fav' : 'dog') : 'neu' },
    { id: 'ou',
      label: shortLabel('ou'),
      value: hasTotal ? m.total.toFixed(1) : PENDING_FIGURE,
      tone: 'neu' },
  ];
}

/**
 * The shared card.
 *
 * @param {object} spec
 * @param {string} spec.identity        e.g. `Your Team vs CULV Destroyers`
 * @param {string} [spec.context]       records, ranks, or lifecycle context
 * @param {MarketCell[]} [spec.markets]
 * @param {boolean} [spec.interactiveMarkets]
 * @param {Array<{label: string, value: string, tone?: string, exactCents?: number}>} [spec.figures]
 * @param {string} [spec.copy]          one short line — teaser or status
 * @param {string} [spec.aside]         UIRECON Rev 1.4 — see the note below
 * @param {string} [spec.footLabel]
 * @param {string} [spec.footValue]
 * @param {string} [spec.badge]
 * @param {string} [spec.badgeTone]
 * @param {string} [spec.accent]        left-edge accent: live | waiting | action | done
 * @param {string} [spec.tapAction]     value for data-card-action
 * @param {string} [spec.tapId]         value for data-card-id
 * @param {string} [spec.className]
 * @returns {string}
 */
export function wagerCard(spec) {
  const {
    identity,
    context = '',
    markets = null,
    interactiveMarkets = false,
    figures = [],
    copy = '',
    // UIRECON REV 1.4 — THE ONE SLOT THAT TAKES HTML RATHER THAN TEXT.
    //
    // Every other field on this spec is escaped here, which is what keeps the
    // grammar safe by construction. `aside` is the exception because it exists
    // for a card-level AFFORDANCE — currently `↻ REFRESH ODDS` on a live
    // Dynamic Matchup — and an affordance is a button and a stamp, not a
    // string. The alternative was a second card function that differed from
    // this one by a `<button>`, and two card grammars is precisely what this
    // module exists to prevent.
    //
    // THE CALLER OWNS THE ESCAPING, and that obligation is not hypothetical:
    // `refresh-odds.js` escapes every value it interpolates. Nothing may be
    // passed here that came from a server string or a GM's typing without going
    // through `escapeHtml` first.
    //
    // IT SITS BETWEEN THE COPY AND THE FOOT, so the documented order —
    // identity → context → markets → figures → copy → foot — is extended rather
    // than broken: the affordance reads after the card has said what it is and
    // before the card says what to do next.
    aside = '',
    footLabel = '',
    footValue = '',
    badge = '',
    badgeTone = '',
    accent = '',
    tapAction = '',
    tapId = '',
    className = '',
  } = spec || {};

  if (!identity) throw new TypeError('a wager card needs an identity');

  const classes = ['fs-wcard'];
  if (accent) classes.push(`is-${accent}`);
  if (tapAction) classes.push('is-tappable');
  if (className) classes.push(className);

  // A card that carries its OWN nested controls — League's market cells — stays
  // a plain container and puts a real button in its foot. A card whose only
  // action is the card itself becomes the button. Either way there is exactly
  // one keyboard path per action, and no button is ever nested inside a button.
  const nestedControls = Boolean(markets && interactiveMarkets);
  const activation = tapAction && !nestedControls ? ' role="button" tabindex="0"' : '';

  const attrs =
    (tapAction ? ` data-card-action="${escapeHtml(tapAction)}"` : '') +
    (tapId ? ` data-card-id="${escapeHtml(tapId)}"` : '') +
    activation;

  const badgeHtml = badge
    ? `<span class="fs-wcard__badge${badgeTone ? ` is-${escapeHtml(badgeTone)}` : ''}">${escapeHtml(badge)}</span>`
    : '';

  const figuresHtml = figures.length
    ? '<div class="fs-wcard__figures">' +
      figures.map((f) => {
        const exact = Number.isSafeInteger(f.exactCents)
          ? ` data-exact-cents="${f.exactCents}"`
          : '';
        const tone = f.tone ? ` is-${escapeHtml(f.tone)}` : '';
        return (
          '<div class="fs-wcard__figure">' +
          `<span class="fs-wcard__figlabel">${escapeHtml(f.label)}</span>` +
          `<span class="fs-wcard__figvalue${tone}"${exact}>${escapeHtml(f.value)}</span>` +
          '</div>'
        );
      }).join('') +
      '</div>'
    : '';

  // The foot value is the keyboard path on a card that could not become a
  // button itself. It keeps the same class either way, so surfaces reading the
  // foot do not have to know which form they got.
  const footValueHtml = tapAction && nestedControls
    ? `<button type="button" class="fs-wcard__footvalue fs-wcard__cta">${escapeHtml(footValue)}</button>`
    : `<span class="fs-wcard__footvalue">${escapeHtml(footValue)}</span>`;

  const footHtml = footLabel || footValue
    ? '<div class="fs-wcard__foot">' +
      `<span class="fs-wcard__footlabel">${escapeHtml(footLabel)}</span>` +
      footValueHtml +
      '</div>'
    : '';

  return (
    `<div class="${classes.join(' ')}"${attrs}>` +
    '<div class="fs-wcard__head">' +
    `<span class="fs-wcard__identity">${escapeHtml(identity)}</span>` +
    badgeHtml +
    '</div>' +
    (context ? `<div class="fs-wcard__context">${escapeHtml(context)}</div>` : '') +
    (markets ? marketRow(markets, { interactive: interactiveMarkets }) : '') +
    figuresHtml +
    (copy ? `<div class="fs-wcard__copy">${escapeHtml(copy)}</div>` : '') +
    (aside ? `<div class="fs-wcard__aside">${aside}</div>` : '') +
    footHtml +
    '</div>'
  );
}

/**
 * A League matchup card — the rich card the vertical carousel presents one at
 * a time.
 *
 * The whole card is the tap target and each market cell is its own; both reach
 * the unified composer, the card with no market selected and the cell with
 * that market selected.
 *
 * @param {object} m a matchup from league-data
 * @returns {string}
 */
export function matchupCard(m) {
  return wagerCard({
    identity: `${m.you.name} vs ${m.name}`,
    context: `${m.you.record} · ${m.you.rank}   ·   ${m.record} · ${m.rank}`,
    markets: matchupMarketCells(m),
    interactiveMarkets: true,
    figures: [
      { label: 'Projected', value: `${m.yourProjection.toFixed(1)} — ${m.opponentProjection.toFixed(1)}` },
      { label: 'Total', value: m.total.toFixed(1) },
    ],
    copy: m.teaser,
    footLabel: 'Tap to challenge',
    footValue: 'Challenge ›',
    tapAction: 'challenge',
    tapId: m.id,
    className: 'fs-wcard--matchup',
  });
}

/**
 * Money figure helper for lifecycle cards: draws whole dollars and keeps the
 * exact cents on the element.
 *
 * @param {string} label
 * @param {number} cents
 * @param {{signed?: boolean, tone?: string}} [options]
 * @returns {{label: string, value: string, tone: string|undefined, exactCents: number}}
 */
export function moneyFigure(label, cents, options = {}) {
  const { signed = false, tone } = options;
  return {
    label,
    value: signed ? formatSignedCredits(cents) : formatCredits(cents),
    tone,
    exactCents: cents,
  };
}