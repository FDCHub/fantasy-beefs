/* ============================================================================
 * FantasyStakes — season results
 *
 * The end-of-season recognition surface: the FantasyStakes Championship podium
 * and its 60/30/10 payout, the Yahoo Championship podium, and the Grand
 * Champion.
 *
 * IT COMPUTES NO MONEY AND DECIDES NO PLACE. Every figure here is rendered from
 * `/league/{id}/championship/results`, which reports what the certified paths
 * already decided: the frozen snapshot supplies places and ties, the recorded
 * distribution run supplies the awards, and the podium order is the server's.
 * A payout recomputed in a browser is a second economic engine, and Rev 4.3 §28
 * forbids that for exactly the reason it would eventually disagree.
 *
 * GRAND CHAMPION IS COMPUTED ON THE SERVER, NOT HERE. Two component
 * championships each award 3 / 2 / 1, a tied component finish pools the point
 * values of the places it occupies, the arithmetic is exact Fractions, GMs
 * level on the highest total are separated by the higher FantasyStakes
 * Championship Score, and only a tie that survives that is a co-Grand
 * Championship. All of that lives in `reports/grand_champion.py`; this module
 * renders the result it returns and performs no points arithmetic of its own.
 * ========================================================================== */

import { escapeHtml, note, sectionHeading } from './components.js';
import { formatCredits, formatSignedCredits } from './credits.js';

const ORDINAL = Object.freeze({ 1: '1st', 2: '2nd', 3: '3rd' });

/**
 * The tiebreak line, shown ONLY when the tiebreak actually decided the result.
 *
 * `tiebreak_used` is the server's answer, not an inference from the data here:
 * it is true only when GMs were level on points AND the Championship Score
 * separated them. A tie that never happened, and a tie the score failed to
 * break, both leave it false — and in both cases showing a tiebreak line would
 * explain something that did not occur.
 */
function tiebreakLine(standing) {
  if (!standing || !standing.tiebreak_used) return '';
  const winner = (standing.champion_team_ids || [])[0];
  const row = (standing.rows || []).find((r) => r.team_id === winner);
  if (!row || row.fantasystakes_score_cents === null
      || row.fantasystakes_score_cents === undefined) return '';
  // Rendered through the shared note component rather than a bespoke class:
  // this is a footnote on a result, which the design system already has.
  return note(`Tiebreak: Championship Score ${formatSignedCredits(row.fantasystakes_score_cents)}`);
}


function podiumRow(place, name, detail, amountCents, tied) {
  const amount = (amountCents === null || amountCents === undefined)
    ? '' : `<span class="fs-sr__amount">${escapeHtml(formatCredits(amountCents))}</span>`;
  return (
    '<li class="fs-sr__place">'
    + `<span class="fs-sr__ordinal">${escapeHtml(ORDINAL[place] || String(place))}</span>`
    + `<span class="fs-sr__name">${escapeHtml(name)}`
    + (tied ? '<span class="fs-st__tie" title="Exact tie">T</span>' : '')
    + '</span>'
    + (detail ? `<span class="fs-sr__detail">${escapeHtml(detail)}</span>` : '')
    + amount
    + '</li>'
  );
}

/** The FantasyStakes Championship podium and its recorded 60/30/10 awards. */
export function fantasystakesPodiumSection(results) {
  if (!results || !Array.isArray(results.fantasystakes_podium)
      || results.fantasystakes_podium.length === 0) {
    return '';
  }
  const awards = new Map(
    (results.awards || []).map((a) => [Number(a.team_id), a]));
  const paid = Boolean(results.paid);

  const places = results.fantasystakes_podium
    .slice()
    .sort((a, b) => a.place - b.place)
    .map((row) => {
      const award = awards.get(Number(row.team_id));
      return podiumRow(
        row.place,
        row.team_name || `Team ${row.team_id}`,
        formatCredits(row.championship_score_cents),
        award ? award.amount_cents : null,
        row.tied);
    }).join('');

  const potLine = (results.pot_cents === null || results.pot_cents === undefined)
    ? ''
    : note(paid
      ? `Championship pot ${formatCredits(results.pot_cents)} — paid 60 / 30 / 10.`
      : `Championship pot ${formatCredits(results.pot_cents)} — pays 60 / 30 / 10 `
        + 'when the championship is settled.');

  return (
    sectionHeading('FantasyStakes Championship')
    + `<ol class="fs-sr__podium">${places}</ol>`
    + potLine
    + (paid ? '' : note('Final standings. The pot has not been distributed yet.'))
  );
}

/** The Yahoo Championship podium, when the bracket is authoritative. */
export function yahooPodiumSection(results, nameFor) {
  const order = results && results.yahoo_podium;
  if (!Array.isArray(order) || order.length === 0) return '';
  const places = order.slice(0, 3).map((teamId, index) => podiumRow(
    index + 1, nameFor(teamId), '', null, false)).join('');
  return sectionHeading('Yahoo Championship') + `<ol class="fs-sr__podium">${places}</ol>`;
}

/**
 * Grand Champion recognition.
 *
 * RENDERS THE SERVER'S ANSWER AND COMPUTES NOTHING. The rule — 3/2/1 per
 * component, pooled point values for a tied component finish, exact Fraction
 * arithmetic, the higher FantasyStakes Championship Score breaking a tie on
 * the highest total, and co-Grand Champions only when that ties too — lives in
 * `reports/grand_champion.py` and is certified there. Reproducing the
 * fractional pooling here would be a second implementation of the one piece of
 * this product most likely to disagree with itself, so this module reads
 * `grand_champion` off `/championship/results` and draws it.
 */
export function grandChampionSection(results, nameFor) {
  if (!results) return '';
  const standing = results.grand_champion;
  if (!standing || !Array.isArray(standing.rows) || standing.rows.length === 0) {
    return sectionHeading('Grand Champion')
      + note('The Grand Champion is decided once both the Yahoo Championship '
             + 'and the FantasyStakes Championship are final.');
  }
  const winners = (standing.champion_team_ids || [])
    .map((teamId) => nameFor(teamId)).join(' · ');
  const table = standing.rows.map((row) => (
    '<tr class="fs-sr__gc-row">'
    + `<td class="fs-sr__name">${escapeHtml(nameFor(row.team_id))}</td>`
    + `<td class="fs-st__num">${escapeHtml(String(row.yahoo_points))}</td>`
    + `<td class="fs-st__num">${escapeHtml(String(row.fantasystakes_points))}</td>`
    + '<td class="fs-st__num fs-sr__gc-total">'
    + `${escapeHtml(String(row.combined_points))}</td>`
    + '</tr>'
  )).join('');

  return (
    sectionHeading(standing.co_champions ? 'Co-Grand Champions' : 'Grand Champion')
    + `<p class="fs-sr__winner">${escapeHtml(winners)}</p>`
    + '<table class="fs-sr__gc"><thead><tr>'
    + '<th>GM</th><th>Yahoo</th><th>FantasyStakes</th><th>Total</th>'
    + '</tr></thead><tbody>' + table + '</tbody></table>'
    + tiebreakLine(standing)
    + note('Yahoo + FantasyStakes finishes: 1st = 3 pts, 2nd = 2, 3rd = 1. '
           + 'Highest total wins. Ties go to the higher FantasyStakes '
           + 'Championship Score.'
           + (standing.co_champions ? ' Still tied = co-Grand Champions.' : ''))
  );
}

/** The whole season-results block, or '' when there is nothing decided yet. */
export function seasonResultsSection(results, nameFor) {
  if (!results) return '';
  const lifecycle = results.lifecycle;
  if (lifecycle !== 'FINAL' && lifecycle !== 'PAID') return '';
  const resolve = typeof nameFor === 'function'
    ? nameFor : (teamId) => `Team ${teamId}`;
  return (
    '<section class="fs-sr">'
    + fantasystakesPodiumSection(results)
    + yahooPodiumSection(results, resolve)
    + grandChampionSection(results, resolve)
    + '</section>'
  );
}
