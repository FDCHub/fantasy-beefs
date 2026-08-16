/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · Rules and league configuration
 * Sprint 7 Package 4
 *
 * THE LEAGUE'S OPERATING MANUAL, TRANSCRIBED. Every rule below states a fact
 * that a governing module or specification already establishes, and each
 * carries the source it came from. Nothing here is policy invented for the UI,
 * and nothing is carried forward from the Rev4.1 prototype's copy.
 *
 * WHERE A RULE WOULD NEED INTERPRETATION, THE FACT IS STATED CONSERVATIVELY.
 * Several questions a GM might reasonably ask — what a league may reconfigure
 * mid-season, how a receivable is ever collected — are not settled by any
 * controlling authority. The manual says what IS governed and stops there
 * rather than resolving an open question in a rules sheet.
 *
 * BETTING VOCABULARY IS INTENTIONAL. wagers, bets, stake, pot, ML, Spread, O/U,
 * Locked, Dynamic. Rev 4.2 §2 keeps them, and the Virtual Credits distinction is
 * carried by the disclaimer context rather than by sanitising the language.
 *
 * The Locked and Dynamic explanations are NOT restated here — they are imported
 * from `wager-model.js`, which quotes the adopted ruling verbatim. One copy of
 * that text exists in this build, and the rules sheet shows that copy.
 * ========================================================================== */

import { MODE_COPY, MODE_DYNAMIC, MODE_LOCKED, MIN_STAKE_CENTS } from '../wager-model.js';
import { formatCredits } from '../credits.js';

/* ── Governed configuration ─────────────────────────────────────────────────
 * Transcribed from the governing sources, with the source named on each row.
 * These are the CURRENT values, not proposals: a settings surface that showed
 * an aspiration would be worse than one that showed nothing. */

/**
 * The league's Discrete-Stop Economy row.
 *
 * `payments/economy_config.py` certifies exactly five stops and this league is
 * on the default. The three exact invariants that module enforces at import
 * time are what make the parts add up, so they are shown rather than described:
 * min_reserve + reserve = buy-in, min_reserve = weekly_min × 14, and
 * reserve × 11 = buy-in × 4.
 */
export const ECONOMY_STOP = Object.freeze({
  weeklyMinCents: 1000,        // $10
  minReserveCents: 14000,      // $140
  reserveCents: 8000,          // $80
  buyinCents: 22000,           // $220
  source: 'League economy configuration',
});

/** Commissioner-set weekly Pool entry, bounded to $1–$5 by the schema. */
export const POOL_ENTRY = Object.freeze({
  cents: 100,                  // $1
  minCents: 100,
  maxCents: 500,
  source: 'League Pool settings',
});

/** Weekly Skunk contribution and its season ceiling. */
export const SKUNK = Object.freeze({
  weeklyCents: 1000,           // $10
  seasonMaximumCents: 14000,   // $140
  weeks: '1–14, regular season only',
  source: 'Skunk rules',
});

/** Championship payout split, by place. */
export const CHAMPIONSHIP_SPLIT = Object.freeze({
  split: Object.freeze([60, 30, 10]),
  source: 'Championship rules',
});

/** Exactly four active Pools per fantasy week. */
export const POOLS_PER_WEEK = 4;

/* ── Settings rows ──────────────────────────────────────────────────────────*/

/**
 * The four locked settings rows.
 *
 * `value` is the CURRENT governed figure. None of these is editable in this
 * build, and the reason is not shyness: no configuration command exists to call.
 * See `SETTINGS_SEAM`.
 */
export const SETTINGS = Object.freeze([
  Object.freeze({
    id: 'economy-stop',
    label: 'Economy Stop',
    value: `${formatCredits(ECONOMY_STOP.weeklyMinCents)} / week · ${formatCredits(ECONOMY_STOP.buyinCents)} season`,
    exactCents: ECONOMY_STOP.buyinCents,
    detail:
      'One of five certified stops. This league is on the default: ' +
      `${formatCredits(ECONOMY_STOP.weeklyMinCents)} released each week for fourteen weeks ` +
      `(${formatCredits(ECONOMY_STOP.minReserveCents)}), plus a ` +
      `${formatCredits(ECONOMY_STOP.reserveCents)} championship reserve, advanced as ` +
      `${formatCredits(ECONOMY_STOP.buyinCents)} at season open. There is no freeform amount and ` +
      'no interpolation between stops.',
    source: ECONOMY_STOP.source,
  }),
  Object.freeze({
    id: 'pool-bet',
    label: 'Standard Pool Bet',
    value: formatCredits(POOL_ENTRY.cents),
    exactCents: POOL_ENTRY.cents,
    detail:
      'The weekly entry for each of the week’s four Pools, set by the ' +
      `commissioner and bounded to ${formatCredits(POOL_ENTRY.minCents)}–` +
      `${formatCredits(POOL_ENTRY.maxCents)}. It freezes for the season once the first ` +
      'week is built.',
    source: POOL_ENTRY.source,
  }),
  Object.freeze({
    id: 'skunk-fee',
    label: 'Skunk Fee',
    value: `${formatCredits(SKUNK.weeklyCents)} weekly · ${formatCredits(SKUNK.seasonMaximumCents)} max`,
    exactCents: SKUNK.weeklyCents,
    detail:
      `${formatCredits(SKUNK.weeklyCents)} a week, weeks ${SKUNK.weeks}, never in the ` +
      `playoffs, accumulating to at most ${formatCredits(SKUNK.seasonMaximumCents)} across a ` +
      'season. An assessment is a ledger obligation against the GM; the pot ' +
      'distributes at season close.',
    source: SKUNK.source,
  }),
  Object.freeze({
    id: 'championship-split',
    label: 'Championship split',
    value: CHAMPIONSHIP_SPLIT.split.join(' / '),
    detail:
      'How the championship pot divides by place. Amounts are integer cents: ' +
      'each ordinary place takes the floor of its percentage, and first place ' +
      'takes the remainder so the pot distributes exactly.',
    source: CHAMPIONSHIP_SPLIT.source,
  }),
]);

/**
 * The configuration-command seam.
 *
 * This one is emptier than the Ledger's. There, the computation existed and
 * only the HTTP surface was missing. Here there is no governed configuration
 * COMMAND at all: the economy stop, the Pool entry, the Skunk amount and the
 * payout split are set through league setup and migrations, and `api/main.py`
 * exposes no route that changes any of them. So these rows are read-only
 * because there is nothing to call — not merely because the session seam is
 * unresolved — and inventing a mutation path here would be inventing the
 * command as well as the wiring.
 */
export const SETTINGS_SEAM = Object.freeze({
  // S8-P4, per the accepted B2 narrowing. ONE of the four rows became
  // mutable — Standard Pool Bet, the one the POR says a commissioner sets,
  // and the only one whose governed setter already carried bounds and a
  // season freeze. The other three remain read-only for MVP: changing an
  // Economy Stop, a Skunk Fee or a Championship split mid-season re-prices
  // obligations GMs have already funded, so the absence of a command for them
  // is the ruling, not a gap.
  status: 'ONE GOVERNED COMMAND · THREE ROWS REMAIN READ-ONLY',
  endpoint: 'PUT /league/{league_id}/settings/pool-entry',
  readEndpoint: 'GET /league/{league_id}/settings',
  mutable: ['pool-bet'],
  readOnly: ['economy-stop', 'skunk-fee', 'championship-split'],
  readSource: 'League settings',
  uiState: 'read-only',
  needs: 'a governed, commissioner-authorised configuration command before any row can be edited',
});

/* ── The five rule groups ───────────────────────────────────────────────────*/

/**
 * The locked top-level groups, in the locked order.
 *
 * @type {ReadonlyArray<{id: string, title: string, blurb: string,
 *   rules: ReadonlyArray<{heading: string, body: string, source: string}>}>}
 */
export const RULE_GROUPS = Object.freeze([
  Object.freeze({
    id: 'money',
    title: 'The Money',
    blurb: 'What you are advanced, what you owe, and what a Credit is.',
    rules: Object.freeze([
      Object.freeze({
        heading: 'You are advanced virtual stakes, not given them',
        body:
          `Every GM is advanced ${formatCredits(ECONOMY_STOP.buyinCents)} at season open: ` +
          `${formatCredits(ECONOMY_STOP.minReserveCents)} as the regular-season minimum reserve and ` +
          `${formatCredits(ECONOMY_STOP.reserveCents)} as the championship reserve. That advance is an ` +
          'obligation for the whole season. It is subtracted in Current Settle, ' +
          'so a GM who has wagered nothing sits at a deficit rather than at zero.',
        source: 'Season-Opening Allocation rules',
      }),
      Object.freeze({
        heading: 'The championship reserve is committed from the moment it lands',
        body:
          `The ${formatCredits(ECONOMY_STOP.reserveCents)} championship reserve is never spendable and ` +
          'never releasable. It is economically committed to the championship pot ' +
          'from activation, which is why it is not counted as one of your ' +
          'settlement-relevant assets — counting it would overstate every GM all season.',
        source: 'Current Settle rules',
      }),
      Object.freeze({
        heading: 'Current Settle is derived, never stored',
        body:
          'Your position is recomputed from posted ledger entries every time it ' +
          'is asked for: settlement-relevant assets minus obligations. Positive ' +
          'means the league owes you, negative means you owe. There is no ' +
          'Current Settle column anywhere and no cached total that could disagree ' +
          'with the money.',
        source: 'Current Settle rules',
      }),
      Object.freeze({
        heading: 'More stakes come from a Top-Off, and a Top-Off is approved',
        body:
          'A GM asks for additional virtual stakes; an authorised league ' +
          'commissioner approves or rejects; approval posts a balanced issuance ' +
          'to the ledger and the Credits land in the GM’s wallet. A Top-Off ' +
          'raises Total Virtual Stakes, so it lowers Current Settle by the same ' +
          'amount — it is an advance, not winnings.',
        source: 'Top-Off rules',
      }),
      Object.freeze({
        heading: 'Credits are virtual',
        body:
          'Credits display as dollars for legibility. They are not money, carry ' +
          'no cash value, and cannot be deposited, withdrawn or redeemed. There ' +
          'is no funding path into this league and none is planned.',
        source: 'League economy rules',
      }),
    ]),
  }),

  Object.freeze({
    id: 'weekly',
    title: 'Weekly Grind',
    blurb: 'The weekly minimum, how it is spent, and the Skunk.',
    rules: Object.freeze([
      Object.freeze({
        heading: `${formatCredits(ECONOMY_STOP.weeklyMinCents)} is released to you each week`,
        body:
          `Each week the league releases ${formatCredits(ECONOMY_STOP.weeklyMinCents)} from your ` +
          'minimum reserve into that week’s minimum — once per team per week, ' +
          'for fourteen regular-season weeks. A release can never exceed what ' +
          'remains in the reserve, so a fifteenth release posts nothing rather ' +
          'than driving the account negative.',
        source: 'Weekly Minimum rules',
      }),
      Object.freeze({
        heading: 'Wagers fund from the weekly minimum first, then your wallet',
        body:
          'Spending draws down the week’s minimum before it touches your wallet. ' +
          'That order is fixed, and it is why Weekly Min Left falls before ' +
          'Available does.',
        source: 'Weekly Minimum rules',
      }),
      Object.freeze({
        heading: 'Unspent minimum leaves circulation — it is not taken from you',
        body:
          'At week close whatever remains in that week’s minimum moves out of ' +
          'circulation. Both accounts are your own settlement-relevant assets, ' +
          'so your Current Settle moves by exactly zero. The Ledger shows it as ' +
          'Weekly Min · out of circulation.',
        source: 'Weekly Minimum rules',
      }),
      Object.freeze({
        heading: `The Skunk is ${formatCredits(SKUNK.weeklyCents)} a week, capped at ${formatCredits(SKUNK.seasonMaximumCents)}`,
        body:
          `Weeks ${SKUNK.weeks}, never in the playoffs. An assessment posts as a ` +
          'ledger obligation against the GM rather than seizing Credits, and the ' +
          'accumulated pot distributes at season close. Nothing collects a Skunk ' +
          'receivable automatically — no controlling authority provides for it.',
        source: 'Skunk rules',
      }),
    ]),
  }),

  Object.freeze({
    id: 'big-money',
    title: 'Big Money',
    blurb: 'Pools and the championship.',
    rules: Object.freeze([
      Object.freeze({
        heading: `Exactly ${POOLS_PER_WEEK} Pools run every fantasy week`,
        body:
          'Not three, not a variable count. Each is a governed definition from ' +
          'the Pool catalog with its own settling rule, and each is scoped to ' +
          'either one league team or one scheduled matchup.',
        source: 'Pool rules',
      }),
      Object.freeze({
        heading: 'A Pool that finds no qualifier carries its pot forward',
        body:
          'Rolling over is a modifier on a Pool, never a different kind of Pool. ' +
          'A continuation occupies one of the week’s four slots and carries its ' +
          'accumulated pot into it.',
        source: 'Pool rules',
      }),
      Object.freeze({
        heading: 'Pool entry is set by the commissioner and then frozen',
        body:
          `Between ${formatCredits(POOL_ENTRY.minCents)} and ${formatCredits(POOL_ENTRY.maxCents)} a week, ` +
          'fixed for the season once the first week is built. Entering a Pool ' +
          'genuinely reduces your Current Settle: the contribution has left you ' +
          'and funds an outcome that is not yet yours.',
        source: 'Pool entry rules',
      }),
      Object.freeze({
        heading: `The championship pot pays ${CHAMPIONSHIP_SPLIT.split.join(' / ')} by place`,
        body:
          'Every GM’s championship reserve sweeps into the league pot at season ' +
          'close, joined by the Skunk distribution. Payouts are integer cents: ' +
          'each ordinary place takes the floor of its share and first place takes ' +
          'the remainder, so the pot distributes exactly with nothing stranded.',
        source: 'Championship rules',
      }),
    ]),
  }),

  Object.freeze({
    id: 'bets',
    title: 'The Bets',
    blurb: 'Challenges, markets, stakes and terms.',
    rules: Object.freeze([
      Object.freeze({
        heading: 'Three markets: ML, Spread and O/U',
        body:
          'Every wager is one of the three. They persist as straight, spread and ' +
          'over_under respectively — ML is the display label for straight, not a ' +
          'fourth kind of bet.',
        source: 'Versus wager rules',
      }),
      Object.freeze({
        heading: `The minimum stake is ${formatCredits(MIN_STAKE_CENTS)}`,
        body:
          'Stakes are whole cents. A stake below the minimum, or one you cannot ' +
          'fund, is refused before it is offered — the composer applies the same ' +
          'rules in the same order the engine does.',
        source: 'Stake rules',
      }),
      Object.freeze({
        heading: `${MODE_COPY[MODE_LOCKED].label} — ${MODE_COPY[MODE_LOCKED].headline}`,
        // Quoted from the adopted ruling through wager-model, so this sheet and
        // the composer cannot drift apart.
        body: MODE_COPY[MODE_LOCKED].body,
        source: 'Locked and Dynamic wager rules',
      }),
      Object.freeze({
        heading: `${MODE_COPY[MODE_DYNAMIC].label} — ${MODE_COPY[MODE_DYNAMIC].headline}`,
        body: MODE_COPY[MODE_DYNAMIC].body,
        source: 'Locked and Dynamic wager rules',
      }),
      Object.freeze({
        heading: 'One counter, and then a decision',
        body:
          'A challenge holds at most the initial proposal and one counter. The ' +
          'counter may set its own stake and quote, but not the market, the ' +
          'terms, the participants or the week — and the issuer keeps the Anchor ' +
          'role. Once countered, the issuer accepts or declines; there is no ' +
          're-counter.',
        source: 'Versus lifecycle rules',
      }),
      Object.freeze({
        heading: 'An offer holds your Credits without spending them',
        body:
          'A pending offer reduces what you can spend while it is outstanding. ' +
          'It is not counted again in Current Settle until a proposal is ' +
          'accepted and the funds become escrow.',
        source: 'Versus funding rules',
      }),
    ]),
  }),

  Object.freeze({
    id: 'fine-print',
    title: 'The Fine Print',
    blurb: 'Sources of truth, and what this is not.',
    rules: Object.freeze([
      Object.freeze({
        heading: 'Yahoo decides what happened on the field',
        body:
          'Lineups, scoring and matchup results come from your Yahoo league ' +
          'through the provider gateway. FantasyStakes reads them and never ' +
          'writes to them: nothing here changes a fantasy result.',
        source: 'Provider rules',
      }),
      Object.freeze({
        heading: 'The ledger balances, always',
        body:
          'Every posting is double-entry and every batch sums to zero, so the ' +
          'trial balance across all accounts is zero at all times. That is the ' +
          'continuous integrity check the league rests on.',
        source: 'Ledger integrity',
      }),
      Object.freeze({
        heading: 'Displayed dollars are rounded; the accounting is not',
        body:
          'FantasyStakes draws Credit values as whole Credits. The underlying figures ' +
          'are exact integer cents throughout, and every drawn figure carries its ' +
          'exact cents alongside it — the rounded string is never the accounting ' +
          'value.',
        source: 'Credits display rules',
      }),
      Object.freeze({
        heading: 'The specifications win',
        body:
          'Where anything in this app disagrees with the governing game, wager, ' +
          'accounting, settlement, economy or provider protocols, the protocol is ' +
          'right and the screen is wrong. This manual transcribes those rules; it ' +
          'does not create them.',
        source: 'Protocol safety',
      }),
    ]),
  }),
]);

/** The locked legal line, shown once, at the bottom of this tab. */
export const LEGAL_LINE = '© 2026 Fraser D. Coleman. All Rights Reserved. FantasyStakes™.';