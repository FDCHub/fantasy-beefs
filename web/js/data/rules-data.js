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
 * The league economy, as the DEMO fixture holds it.
 *
 * WP3C — THESE ARE FIXTURE FIGURES, NOT PRODUCT CONSTANTS. Rev 4.3 §15 replaced
 * the five-stop ladder with a configurable economy: a commissioner sets the
 * Weekly Bet Minimum, the Yahoo Championship Contribution and the Skunk Fee,
 * and
 * the server derives the Season-Opening Allocation from them and the league's
 * own regular-season week count. A bound session reads all of that through
 * `settings-model.js`; these values are what an UNBOUND one draws, and the only
 * league they describe is the illustrative one.
 *
 * The old note here recorded three invariants of the retired model, including
 * `min_reserve = weekly_min × 14`. That is no longer true of anything — a
 * league playing thirteen weeks derives thirteen — and it is gone with it.
 */
export const ECONOMY_STOP = Object.freeze({
  weeklyMinCents: 1000,        // $10
  // DERIVED, NOT FIXED. The commissioner sets the weekly minimum; FantasyStakes
  // reads the league's number of Yahoo regular-season weeks and multiplies. The
  // $140 here is this demo league's answer to 10 x 14, not a universal reserve.
  minReserveCents: 14000,      // $140  = weeklyMinCents x regular-season weeks
  reserveCents: 8000,          // $80   Yahoo Championship Contribution
  // RC2 — THE SECOND CHAMPIONSHIP CONTRIBUTION. FantasyStakes runs its own
  // championship with its own fixed pot, funded only by this contribution and
  // independently configurable before activation. It defaults to the Yahoo
  // amount, which is why both read $80 here.
  fantasystakesReserveCents: 8000,   // $80  FantasyStakes Championship Contribution
  // THE BASE STAGE, unchanged. `payments/economy_config.py`'s stop is Weekly
  // Play Reserve + Yahoo Championship Contribution, and the demo ledger
  // arithmetic in this app is built on it. RC2's FantasyStakes contribution is
  // advanced by its own activation stage, so the GM's TOTAL season advance is
  // the field below — that is what `rc2_season_activation` reports and what
  // Current Settle charges.
  regularSeasonWeeks: 14,      // this demo league's schedule
  buyinCents: 22000,           // $220  base stage (Weekly Play + Yahoo)
  seasonOpeningTotalCents: 30000,  // $300 total advance per GM, all three parts
  source: 'League economy configuration',
});

/** Commissioner-set weekly Prop Pool entry, bounded to $1–$5 by the schema. */
export const POOL_ENTRY = Object.freeze({
  cents: 100,                  // $1
  minCents: 100,
  maxCents: 500,
  source: 'League Prop Pool settings',
});

/**
 * The Skunk Fee, as the DEMO fixture holds it.
 *
 * WP3C REMOVED `seasonMaximumCents` AND `weeks`. Rev 4.3 §19 and WP3C §24: the
 * fee is configured per league, there is NO enforced season maximum, and the
 * span is "every completed regular-season week" rather than a literal 1–14.
 * The old `$140 max` was a conceptual ceiling nothing enforces, displayed as
 * though it capped a GM's exposure; the old `1–14` was wrong for any league
 * that does not play fourteen weeks.
 */
export const SKUNK = Object.freeze({
  feeCents: 1000,              // $10 — the fixture's configured fee
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
    label: 'Season-Opening Allocation',
    exampleOnly: true,
    value: formatCredits(ECONOMY_STOP.seasonOpeningTotalCents),
    exactCents: ECONOMY_STOP.seasonOpeningTotalCents,
    detail:
      'EXAMPLE CONFIGURATION. The figure beside this row is one league' +
      String.fromCharCode(8217) + 's arithmetic, shown while live settings are ' +
      'unavailable; your league reports its own. ' +
      'Your Season-Opening Allocation is the sum of three parts, and all of ' +
      'them come from your league' + String.fromCharCode(8217) + 's own ' +
      'settings rather than being fixed by FantasyStakes. ' +
      'The Weekly Play Reserve is derived: your commissioner sets the weekly ' +
      'minimum, FantasyStakes reads how many Yahoo regular-season weeks your ' +
      'league plays, and multiplies the two. The Yahoo Championship ' +
      'Contribution and the FantasyStakes Championship Contribution are each ' +
      'set by your commissioner, independently of one another. ' +
      `In this league that works out as ${formatCredits(ECONOMY_STOP.weeklyMinCents)} ` +
      `x ${ECONOMY_STOP.regularSeasonWeeks} weeks = ` +
      `${formatCredits(ECONOMY_STOP.minReserveCents)}, plus ` +
      `${formatCredits(ECONOMY_STOP.reserveCents)} and ` +
      `${formatCredits(ECONOMY_STOP.fantasystakesReserveCents)}, for ` +
      `${formatCredits(ECONOMY_STOP.seasonOpeningTotalCents)}. A league with a ` +
      'different weekly minimum or a different schedule gets a different ' +
      'figure. Both championship contributions lock at activation. The Skunk ' +
      'Fee is contingent and is not part of this allocation.',
    source: ECONOMY_STOP.source,
  }),
  Object.freeze({
    id: 'pool-bet',
    label: 'Standard Pool Bet',
    value: formatCredits(POOL_ENTRY.cents),
    exactCents: POOL_ENTRY.cents,
    detail:
      'The weekly entry for each of the week’s four Prop Pools, set by the ' +
      `commissioner and bounded to ${formatCredits(POOL_ENTRY.minCents)}–` +
      `${formatCredits(POOL_ENTRY.maxCents)}. It freezes for the season once the first ` +
      'week is built.',
    source: POOL_ENTRY.source,
  }),
  Object.freeze({
    id: 'skunk-fee',
    label: 'Skunk Fee',
    value: formatCredits(SKUNK.feeCents),
    exactCents: SKUNK.feeCents,
    detail:
      `${formatCredits(SKUNK.feeCents)} per completed regular-season week, ` +
      'charged to the team that lost its Yahoo matchup by the largest margin. ' +
      'Tied largest losers split one fee. There is no postseason Skunk and no ' +
      'enforced season maximum. An assessment is a ledger obligation against ' +
      'the GM; the whole pot distributes at regular-season close.',
    source: SKUNK.source,
  }),
  Object.freeze({
    id: 'championship-split',
    label: 'Championship split',
    value: CHAMPIONSHIP_SPLIT.split.join(' / '),
    detail:
      'How a championship pot divides: 60 to the champion, 30 to the ' +
      'runner-up, 10 to third place. This is the split for BOTH championships — ' +
      'Yahoo is authoritative for the Yahoo podium, and the FantasyStakes ' +
      'Championship pays its own fixed pot on FantasyStakes Championship Score. ' +
      'Amounts are integer cents. Exact ties are real ties: the prize shares for ' +
      'the places a tied group occupies are pooled and split evenly among them, ' +
      'and the pot still distributes to the cent.',
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
  // S8-P4, per the accepted B2 narrowing, as WP3B and WP3C revised it.
  //
  // STANDARD POOL BET IS MUTABLE HERE, in-season, and always was. The other
  // three are read-only ON THIS SURFACE because changing them mid-season would
  // re-price obligations GMs have already funded — but WP3B built the
  // commissioner economy setup, so the Weekly Bet Minimum, the Championship Pot
  // Contribution and the Skunk Fee ARE configurable BEFORE activation, through
  // the gear menu. "Read-only" here means "locked for the active season", not
  // "no command exists".
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
          'At season open every GM is advanced their Season-Opening Allocation: ' +
          'the league’s Weekly Bet Minimum across its regular-season weeks, held ' +
          'as the Weekly Play Reserve, plus its Yahoo Championship ' +
          'Contribution and its FantasyStakes Championship Contribution, each ' +
          'held as a committed championship reserve. The commissioner ' +
          'configures all three before activation and the server derives the ' +
          'total — ' +
          'see League Settings for your league’s own figures. That advance is an ' +
          'obligation for the whole season. It is subtracted in Current Settle, ' +
          'so a GM who has wagered nothing sits at a deficit rather than at zero.',
        source: 'Season-Opening Allocation rules',
      }),
      Object.freeze({
        heading: 'The championship reserve is committed from the moment it lands',
        body:
          'The championship reserve is never spendable and ' +
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
        heading: 'Your Weekly Bet Minimum is released to you each week',
        body:
          'Each week the league releases your configured Weekly Bet Minimum ' +
          'from your minimum reserve into that week’s minimum — once per team ' +
          'per week, for each of the league’s regular-season weeks. A release ' +
          'can never exceed what remains in the reserve, so a release beyond the ' +
          'season’s last week posts nothing rather than driving the account ' +
          'negative. There is no Weekly Minimum in the postseason.',
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
        heading: 'The Skunk is charged to the week’s widest loss',
        body:
          'Every completed regular-season week, the team that lost its Yahoo ' +
          'matchup by the largest margin owes one Skunk Fee at the amount the ' +
          'commissioner configured. Tied largest losers split one fee between ' +
          'them — the league is charged one fee per week, never one per loser. ' +
          'There is no Skunk in the postseason, and no enforced season maximum.',
        source: 'Skunk rules',
      }),
      Object.freeze({
        heading: 'An assessment is an obligation, not a seizure',
        body:
          'A Skunk posts as a ledger obligation against the GM rather than ' +
          'taking Credits out of their Wallet, so it can be assessed whatever ' +
          'their balance is and it lowers Current Settle without touching what ' +
          'they can spend. Nothing collects a Skunk receivable automatically. ' +
          'The Skunk Fee is contingent and is not part of the Season-Opening ' +
          'Allocation.',
        source: 'Skunk rules',
      }),
      Object.freeze({
        heading: 'The whole Skunk Pot goes to the Points For leader',
        body:
          'Every Skunk Fee assessed during the regular season accumulates into ' +
          'one Skunk Pot. At regular-season close the entire Pot is awarded to ' +
          'the team with the highest cumulative Yahoo regular-season Points For ' +
          '— not the best record, not the champion, not a seed. Postseason ' +
          'points are excluded. A Points For tie is split by the governed ' +
          'deterministic rule.',
        source: 'Skunk rules',
      }),
    ]),
  }),

  Object.freeze({
    id: 'championships',
    title: 'The Championships',
    blurb: 'How the two championships are won, scored and paid.',
    rules: Object.freeze([
      Object.freeze({
        heading: 'Championship Score is what you have WON, not what you hold',
        body:
          'Your FantasyStakes Championship Score is your total realized net ' +
          'winnings from championship-counting FantasyStakes competition: ' +
          'matchups against other GMs and prop pools. Your wallet balance is ' +
          'not your Championship Score. Credits you were advanced at season ' +
          'open, a Top-Off, a released Weekly Minimum, a refund or a ' +
          'championship payout all move your wallet without anybody winning ' +
          'anything, so none of them move your Championship Score. Credits ' +
          'decide how much you can play; results decide whether you are winning.',
        source: 'FantasyStakes Championship POR',
      }),
      Object.freeze({
        heading: 'Scoring ends with the final Yahoo regular-season week',
        body:
          'The FantasyStakes Championship race runs through the Yahoo regular ' +
          'season. At the playoff boundary the standings freeze: the field and ' +
          'the scoring window are closed and neither reopens. FantasyStakes ' +
          'play continues in the postseason and those wagers still move real ' +
          'Credits — they simply no longer change Championship Score or the ' +
          'Grand Champion.',
        source: 'FantasyStakes Championship POR',
      }),
      Object.freeze({
        heading: 'A regular-season contest still counts if it settles late',
        body:
          'Eligibility belongs to the contest, not to the clock. A matchup or ' +
          'prop pool from the regular season counts even if its result lands ' +
          'after the freeze. That is why the championship is FROZEN before it ' +
          'is FINAL: frozen means the field is closed, final means every ' +
          'eligible result is in. The pot is never paid before FINAL.',
        source: 'FantasyStakes Championship POR',
      }),
      Object.freeze({
        heading: 'The FantasyStakes Championship pot is fixed and pays 60 / 30 / 10',
        body:
          'The pot is fixed at activation and funded only by the FantasyStakes ' +
          'Championship Contributions. It never grows from Top-Offs, Weekly ' +
          'Minimum amounts, pool remainders or anything else. It pays 60 to ' +
          'the champion, 30 to the runner-up and 10 to third. Exact ties are ' +
          'real ties: the shares for the places a tied group occupies are ' +
          'pooled and split evenly, and no wallet balance, wager count or team ' +
          'id ever breaks a tie for money.',
        source: 'FantasyStakes Championship POR',
      }),
      Object.freeze({
        heading: 'How the Grand Champion is selected',
        body:
          'The Grand Champion combines each GM’s Yahoo Championship and ' +
          'FantasyStakes Championship finish. 1st = 3 points, 2nd = 2, and ' +
          '3rd = 1. Highest total wins. If tied, the higher FantasyStakes ' +
          'Championship Score wins — that is your realized net winnings from ' +
          'FantasyStakes matchups and prop pools, not your wallet balance. If ' +
          'still tied, they are co-Grand Champions. Grand Champion rewards ' +
          'overall performance across both championships, not combined dollars ' +
          'or credits won. It is a season-ending recognition: there is no ' +
          'Grand Champion pot and it moves no Credits.',
        source: 'Grand Champion POR',
      }),
      Object.freeze({
        heading: 'An authoritative correction can restate a result, never a score',
        body:
          'If an eligible regular-season contest was settled on the wrong ' +
          'result, the commissioner can file an authoritative correction. The ' +
          'correction names the contest and its corrected result — who won, or ' +
          'that it was a push — and the server derives the Credits from that ' +
          'contest’s own economics. Nobody types an amount, and no championship ' +
          'score is ever edited directly. Corrections are append-only and ' +
          'visible to the whole league. Postseason contests can never be ' +
          'corrected into the championship, and once the pot has been paid a ' +
          'correction is refused outright — there is no clawback and no second ' +
          'distribution.',
        source: 'FantasyStakes Championship POR',
      }),
    ]),
  }),
  Object.freeze({
    id: 'big-money',
    title: 'Big Money',
    blurb: 'Prop Pools and the championship.',
    rules: Object.freeze([
      Object.freeze({
        heading: `Exactly ${POOLS_PER_WEEK} FantasyStakes Prop Pools run every fantasy week`,
        body:
          'Not three, not a variable count. Each is a governed definition from ' +
          'the Prop Pool catalog with its own settling rule, and each is scoped to ' +
          'either one league team or one scheduled matchup.',
        source: 'Prop Pool rules',
      }),
      Object.freeze({
        heading: 'A Prop Pool that finds no qualifier carries its pot forward',
        body:
          'Rolling over is a modifier on a Prop Pool, never a different kind of ' +
          'Prop Pool. ' +
          'A continuation occupies one of the week’s four slots and carries its ' +
          'accumulated pot into it.',
        source: 'Prop Pool rules',
      }),
      Object.freeze({
        heading: 'Prop Pool entry is set by the commissioner and then frozen',
        body:
          `Between ${formatCredits(POOL_ENTRY.minCents)} and ${formatCredits(POOL_ENTRY.maxCents)} a week, ` +
          'fixed for the season once the first week is built. Entering a Prop Pool ' +
          'genuinely reduces your Current Settle: the contribution has left you ' +
          'and funds an outcome that is not yet yours.',
        source: 'Prop Pool entry rules',
      }),
      Object.freeze({
        heading: `The championship pot pays ${CHAMPIONSHIP_SPLIT.split.join(' / ')} by place`,
        body:
          'Every GM’s Yahoo Championship Contribution sweeps into the Yahoo ' +
          'championship pot ' +
          'at season close. It pays the champion, the runner-up and the official ' +
          'third place. Payouts are integer cents: each ordinary place takes the ' +
          'floor of its share and first place takes the remainder, so the pot ' +
          'distributes exactly with nothing stranded.',
        source: 'Championship rules',
      }),
      Object.freeze({
        heading: 'Yahoo decides the podium, and nothing else does',
        body:
          'Champion, runner-up and official third place are Yahoo’s postseason ' +
          'result. There is no commissioner override, no standings-based ' +
          'fallback and no FantasyStakes tiebreaker. If the official third place ' +
          'cannot be classified, the payout does not proceed on a guess — it ' +
          'waits.',
        source: 'Championship rules',
      }),
      Object.freeze({
        heading: 'Who can play in the postseason',
        body:
          'FantasyStakes Matchups are limited to teams still alive on the ' +
          'championship track, plus the official third-place participants ' +
          'during championship week. A team playing a consolation or placement ' +
          'game is not a Matchup subject, however many fixtures it has left. ' +
          'Prop Pools are different: every league member keeps entering them ' +
          'after their own team is eliminated, subject to the ordinary Prop ' +
          'Pool rules.',
        source: 'Prop Pool rules',
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
        source: 'Matchup wager rules',
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
        source: 'Matchup lifecycle rules',
      }),
      Object.freeze({
        heading: 'An offer holds your Credits without spending them',
        body:
          'A pending offer reduces what you can spend while it is outstanding. ' +
          'It is not counted again in Current Settle until a proposal is ' +
          'accepted and the funds become escrow.',
        source: 'Matchup funding rules',
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