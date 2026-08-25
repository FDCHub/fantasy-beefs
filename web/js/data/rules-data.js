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

/* ── FINAL POR §24 · the four rule groups ──────────────────────────────────*/

/**
 * §24's four top-level groups, in §24's order.
 *
 * THIS REPLACED SIX RC2 GROUPS, and the replacement is a reorganisation rather
 * than a rewrite of the league's rules: what was scattered across The Money,
 * Weekly Grind, The Championships, Big Money, The Bets and The Fine Print is
 * now The Basics, Your Credits, Weekly Play and Season Play, which is how a GM
 * actually encounters the game. The rules themselves are the Final POR's, and
 * several of them could not have been stated under the old structure at all --
 * there was no Points Championship, no Grand Championship and no accepted-wager
 * void to describe.
 *
 * THREE PARAGRAPHS ARE APPROVED COPY AND APPEAR VERBATIM: what FantasyStakes
 * does, what a virtual credit is, and the Team/Matchup Prop Pool distinction.
 * They are marked at their sites. Do not paraphrase them for length.
 *
 * @type {ReadonlyArray<{id: string, title: string, blurb: string,
 *   rules: ReadonlyArray<{heading: string, body: string, source: string}>}>}
 */
export const RULE_GROUPS = Object.freeze([
  Object.freeze({
    id: 'basics',
    title: 'The Basics',
    blurb: 'What FantasyStakes is, and what it does with your league.',
    rules: Object.freeze([
      Object.freeze({
        heading: 'What FantasyStakes does',
        // APPROVED COPY, VERBATIM. This paragraph is the product's own
        // description of itself and is not paraphrased here.
        body:
          'FantasyStakes uses your league settings, scoring and projections to ' +
          'simulate matchups and generate real probabilities and Vegas-style ' +
          'odds. You use those odds to wager virtual credits on your team ' +
          'against other players.',
        source: 'Product definition',
      }),
      Object.freeze({
        heading: 'Your fantasy league is unchanged',
        body:
          'Lineups, scoring and matchup results come from your fantasy league ' +
          'through the provider gateway. FantasyStakes reads them and never ' +
          'writes to them: nothing here changes a fantasy result, a roster or ' +
          'a standing in the league you already play.',
        source: 'Provider rules',
      }),
      Object.freeze({
        heading: 'Wagers are public',
        body:
          'Every GM in the league can see the wagers you offer, accept and ' +
          'settle. There is no private betting and no quiet ledger — a ' +
          'league where some results are visible and others are not is not a ' +
          'league anyone can check.',
        source: 'League rules',
      }),
      Object.freeze({
        heading: 'The specifications win',
        body:
          'Where anything on a screen disagrees with the governing game, ' +
          'wager, accounting, settlement, economy or provider protocols, the ' +
          'protocol is right and the screen is wrong. This manual transcribes ' +
          'those rules; it does not create them.',
        source: 'Protocol safety',
      }),
    ]),
  }),

  Object.freeze({
    id: 'credits',
    title: 'Your Credits',
    blurb: 'What a Credit is, what you are advanced, and what you owe.',
    rules: Object.freeze([
      Object.freeze({
        heading: 'What a virtual credit is',
        // APPROVED COPY, VERBATIM.
        body:
          'FantasyStakes uses virtual credits to create its own differentiated ' +
          'scoring and accounting system, separate from the fantasy points ' +
          'used by your underlying league. Virtual credits have no real-world ' +
          'economic value outside FantasyStakes.',
        source: 'Credits display rules',
      }),
      Object.freeze({
        heading: 'There is no way to buy in and no way to cash out',
        // THE FUNDING DENIAL, KEPT WORD FOR WORD FROM THE RETIRED FINE PRINT
        // GROUP. It is the load-bearing sentence of the whole Credits model
        // and the one a regulator would read first; §24 reorganised where the
        // rules live and did not licence softening this one.
        body:
          'Credits cannot be deposited, withdrawn or redeemed. They are not ' +
          'currency, not tokens and not a stake in anything: they have no cash ' +
          'value inside FantasyStakes or outside it. There is no funding path ' +
          'into this league and none is planned.',
        source: 'Credits display rules',
      }),
      Object.freeze({
        heading: 'You are advanced credits, not given them',
        body:
          'At season open every GM is advanced their Season-Opening ' +
          'Allocation. It is an advance against the season, not a gift and not ' +
          'a purchase, and your Current Settle is the running answer to what ' +
          'you have been advanced against what you have earned.',
        source: 'League economy configuration',
      }),
      Object.freeze({
        heading: 'Current Settle: what you would owe if the season stopped now',
        // THE DEFINITION AND THE NEVER-STORED PROPERTY, both transcribed from
        // `economy/current_settle.py`. The second half is not a footnote: a
        // figure that were stored could drift from the ledger it describes, and
        // "derived on every read" is the reason this one cannot.
        body:
          'Current Settle is your settlement-relevant assets minus ' +
          'obligations. It is derived from the ledger on every read and is ' +
          'never stored, never incremented and never taken from a wallet ' +
          'balance — there is no Current Settle column anywhere, because a ' +
          'stored figure could disagree with the postings it describes.',
        source: 'Current Settle',
      }),
      Object.freeze({
        heading: 'Your FantasyStakes Score is what wins championships',
        // THE FORMULA, STATED ONCE AND IN THE SAME THREE TERMS THE STANDINGS
        // TABLE DRAWS. A rules sheet that phrased it differently from the
        // column headings would read as a second, slightly different rule.
        body:
          'FantasyStakes Score = Matchups + Prop Pools − Skunk Fees. Your ' +
          'Wallet balance is not part of it: a GM who holds credits and a GM ' +
          'who has wagered them stand in the same place until the wagers ' +
          'settle. The Score decides your championship standing; the Wallet ' +
          'decides what you can stake next.',
        source: 'FantasyStakes Score',
      }),
      Object.freeze({
        heading: 'Displayed dollars are rounded; the accounting is not',
        body:
          'FantasyStakes draws Credit values as whole Credits. The underlying ' +
          'figures are exact integer cents throughout, and every drawn figure ' +
          'carries its exact cents alongside it — the rounded string is ' +
          'never the accounting value.',
        source: 'Credits display rules',
      }),
      Object.freeze({
        heading: 'The ledger balances, always',
        body:
          'Every posting is double-entry and every batch sums to zero, so the ' +
          'trial balance across all accounts is zero at all times. That is the ' +
          'continuous integrity check the league rests on.',
        source: 'Ledger integrity',
      }),
    ]),
  }),

  Object.freeze({
    id: 'weekly',
    title: 'Weekly Play',
    blurb: 'Matchups, Prop Pools, the Skunk and Top-Offs.',
    rules: Object.freeze([
      Object.freeze({
        heading: 'Matchups',
        body:
          'Each week you may challenge another GM on your own matchup at the ' +
          'odds FantasyStakes generates. Both stakes are held in escrow until ' +
          'the fantasy result is final, and the Weekly Minimum is the least ' +
          'you must put into play across the week. The Weekly Minimum applies ' +
          'in the regular season only.',
        source: 'Wager rules',
      }),
      Object.freeze({
        heading: 'How the Weekly Minimum is released and spent',
        // MIN-FIRST, AND THE RELEASE CEILING. Both transcribed from
        // `economy/weekly_minimum.py`. A GM who does not know the spending
        // order cannot reconcile their own Wallet against their Min Left.
        body:
          'Your Weekly Play Reserve is released one week at a time, and a ' +
          'release can never exceed what is left of the reserve — a league ' +
          'cannot release more weeks than it bought. ' +
          'When you stake, the released minimum is spent first and your ' +
          'Wallet only after it: minimum first, then wallet. Whatever is left ' +
          'unspent at week close goes to the FantasyStakes Championship Pot ' +
          'rather than back to you.',
        source: 'Weekly Minimum rules',
      }),
      Object.freeze({
        heading: 'The three markets',
        // THE BETTING VOCABULARY IS INTENTIONAL (Rev 4.2 §2) -- wagers, bets,
        // stake, pot, ML, Spread, O/U. The Virtual Credits distinction is
        // carried by the disclaimer and by Your Credits above, not by
        // sanitising the language a bettor already knows.
        body:
          'Every matchup offers the same three bets. ML is the moneyline \u2014 ' +
          'who wins outright, priced by win probability rather than by margin. ' +
          'Spread gives one team a handicap in fantasy points, and your bet is ' +
          'whether they beat it. O/U is the total: whether the two teams ' +
          'combined finish over or under a posted number. Your stake goes into ' +
          'escrow when the wager is accepted and the pot settles when the ' +
          'fantasy result is final. The engine knows them as straight, spread ' +
          'and over_under, and there are no others.',
        source: 'Wager rules',
      }),
      Object.freeze({
        heading: 'A voided wager still counted as play',
        // THE ACCEPTED-WAGER VOID RULE. The half a GM cares about is the half
        // that is easy to get wrong in their favour and against them at once:
        // the stake comes back, and the week still counts as played.
        body:
          'If an accepted wager has to be voided, both stakes return to their ' +
          'Wallets in full and the wager scores nothing for either GM. The ' +
          'week still counts as played: accepting the wager satisfied your ' +
          'Weekly Minimum, and voiding it does not put that obligation back. ' +
          'A void is recorded as its own event, so it is always visible as a ' +
          'void rather than as a wager that quietly disappeared.',
        source: 'Wager rules',
      }),
      // THE TWO WAGER MODES, QUOTED FROM THE ADOPTED RULING. These bodies are
      // `MODE_COPY`'s own text, imported rather than transcribed, so ONE copy
      // of the ruling exists in this build and the rules sheet shows that copy.
      // They moved here from the retired "The Bets" group; the ruling itself is
      // unchanged and is not restated in this file.
      Object.freeze({
        heading: `${MODE_COPY[MODE_LOCKED].label} — ${
          MODE_COPY[MODE_LOCKED].headline}`,
        body: MODE_COPY[MODE_LOCKED].body,
        source: 'Locked vs Dynamic wager model ruling',
      }),
      Object.freeze({
        heading: `${MODE_COPY[MODE_DYNAMIC].label} — ${
          MODE_COPY[MODE_DYNAMIC].headline}`,
        body: MODE_COPY[MODE_DYNAMIC].body,
        source: 'Locked vs Dynamic wager model ruling',
      }),
      Object.freeze({
        heading: 'One counter, and no re-counter',
        body:
          `The least you may stake on a wager is ${formatCredits(
            MIN_STAKE_CENTS)}. An offer may be countered once; the original ` +
          'GM then accepts or declines, and there is no re-counter. A wager ' +
          'that is neither accepted nor declined simply expires.',
        source: 'Wager rules',
      }),
      Object.freeze({
        heading: 'Prop Pools',
        // APPROVED COPY, VERBATIM. Both sentences.
        body:
          'Team Prop Pools are based on the performance of individual fantasy ' +
          'teams or players across the league. Matchup Prop Pools are based on ' +
          'the combined results or performance of a specific fantasy football ' +
          'matchup.',
        source: 'Prop Pool rules',
      }),
      Object.freeze({
        heading: 'What a Prop Pool pays, and what happens when nobody wins',
        body:
          'Every GM who enters pays the same Prop Pool Entry, and the pot goes ' +
          'to whoever answers the Pool best. A Pool that nobody wins carries ' +
          'to the next week where its question allows it; where it cannot ' +
          'carry, or where the season runs out, the remainder goes to the ' +
          'FantasyStakes Championship Pot rather than back to the GMs who ' +
          'entered it.',
        source: 'Prop Pool rules',
      }),
      Object.freeze({
        heading: 'Skunk',
        // ONE ASSESSMENT, NOT CHARGED TWICE. Stated as a rule rather than as
        // an implementation note, because a GM who sees the fee reduce their
        // Score and also sees it as an obligation will otherwise reasonably
        // conclude they were charged for it twice.
        body:
          'Each completed regular-season week, the GM who lost their fantasy ' +
          'matchup by the largest margin is assessed the Weekly Skunk Fee. ' +
          'Tied largest losers split one fee between them. It is ONE ' +
          'assessment and you are never charged twice for it: the same fee ' +
          'that reduces your FantasyStakes Score is the fee you owe, not a ' +
          'second one. There is no postseason Skunk, and a league may set the ' +
          'fee to zero and play without it.',
        source: 'Skunk rules',
      }),
      Object.freeze({
        heading: 'Top-Offs',
        body:
          'If you run short, you may request a Top-Off from your commissioner ' +
          'up to your Season Top-Off Limit. An approved Top-Off adds credits ' +
          'to your Wallet and the same amount to the FantasyStakes ' +
          'Championship Pot — the pot you might win grows with the ' +
          'credits you took. What you owe rises by the Top-Off itself and not ' +
          'by twice it.',
        source: 'Top-Off rules',
      }),
      Object.freeze({
        heading: 'The postseason is Wallet only',
        // THE POSTSEASON WALLET-ONLY RULE. Placed here rather than under
        // Season Play because it is a rule about how you wager, and this is
        // the group a GM opens to find out how wagering works.
        body:
          'Once the fantasy postseason begins there is no Weekly Minimum and ' +
          'no Skunk. You wager from your Wallet alone, and those wagers score ' +
          'exactly as regular-season wagers do — the FantasyStakes ' +
          'Championship is still live and postseason results still move it.',
        source: 'Season phase rules',
      }),
    ]),
  }),

  Object.freeze({
    id: 'season',
    title: 'Season Play',
    blurb: 'The three championships, and the Grand Championship over them.',
    rules: Object.freeze([
      Object.freeze({
        heading: 'How every championship pot pays',
        // 60 / 30 / 10 IS STATED EXACTLY ONCE IN THIS MANUAL, here, because it
        // is one rule governing all three championships. Restating it under
        // each would invite the three copies to drift apart, and a reader who
        // found two of them would have to work out which was authoritative.
        body:
          'Every championship pot divides the same way: 60 to the champion, ' +
          '30 to the runner-up, 10 to third. Exact ties share the places they ' +
          'tie for and split the credits those places would have paid, to the ' +
          'cent, with the whole pot always paid out. Neither the split nor the ' +
          'tie rule is a commissioner setting.',
        source: 'Championship rules',
      }),
      Object.freeze({
        heading: 'Points Championship',
        body:
          'Funded by the Skunk Fees your league actually assessed, and it ' +
          'exists only if your league charges a Skunk Fee at all. It is won on ' +
          'total fantasy Points For across the regular season, and it settles ' +
          'once the regular season is final and any provider corrections have ' +
          'landed. The figure shown before then is a projection of what the ' +
          'pot could reach, not credits anyone holds.',
        source: 'Points Championship',
      }),
      Object.freeze({
        heading: 'Fantasy Football Championship',
        // THE TWO-TEAM PLAYOFF EXCEPTION -- OWNER RULING. The reason the copy
        // spends a sentence on WHY it is 67/33 rather than simply stating the
        // numbers is that a reader who works out 60/30 renormalised would get
        // a different answer, and would be right to ask which one their league
        // pays.
        body:
          'Funded by one league-level pot your commissioner sets, and won on ' +
          'your fantasy league’s own playoff bracket — champion, ' +
          'runner-up, and the winner of the official third-place game. Your ' +
          'fantasy provider is authoritative for all three; there is no ' +
          'commissioner override and no standings-based fallback. A league ' +
          'whose playoff format has exactly two teams has no third-place game ' +
          'to win, and that pot pays 67 to the champion and 33 to the ' +
          'runner-up instead. That exception is about the SHAPE of your ' +
          'playoff, never about missing information: a bracket that should ' +
          'have a third-place game and cannot show one waits until it can ' +
          'rather than paying the two-team split.',
        source: 'Fantasy Football Championship',
      }),
      Object.freeze({
        heading: 'FantasyStakes Championship',
        body:
          'The big one, and the only championship won on FantasyStakes play ' +
          'itself. Its Championship Base Pot opens at your league’s ' +
          'Weekly Minimum across the regular season, and it grows all year — every unspent Weekly ' +
          'Minimum, every approved Top-Off and every Prop Pool remainder that ' +
          'cannot carry goes into it. It is won on FantasyStakes Score across ' +
          'the whole season, postseason wagers included, and it pays once the ' +
          'season is final.',
        source: 'FantasyStakes Championship',
      }),
      Object.freeze({
        heading: 'Grand Championship',
        body:
          'Won on the credits you finish with across the championships your ' +
          'league actually funded — not on placings, and not on a points ' +
          'table. It needs at least two funded championships to exist at all: ' +
          'with only one, it would be that championship under another name. ' +
          'An exact tie on total credits makes co-champions, and there is no ' +
          'tiebreak beyond it.',
        source: 'Grand Championship',
      }),
    ]),
  }),
]);

/** The locked legal line, shown once, at the bottom of this tab. */
export const LEGAL_LINE = '© 2026 Fraser D. Coleman. All Rights Reserved. FantasyStakes™.';
/* ── FINAL POR §23 · the VC ALLOCATION table, illustratively ────────────────*/

/**
 * §23's seven rows as the DEMO fixture holds them.
 *
 * ILLUSTRATIVE, AND SAID SO. Every figure here belongs to one example league;
 * a bound session reads its own through `settings-model.js` and never sees
 * these. They exist so the component suites and an unbound reviewer have a
 * table to look at, for the same reason `ECONOMY_STOP` exists above.
 *
 * THE RATIOS ARE WRITTEN OUT, NOT COMPUTED. §16.2 forbids reimplementing the
 * economic formula in the browser, and that applies to the demo copy of it too
 * — a division here would be exactly the second definition the server-side
 * `format_ratio` exists to prevent. These are transcribed from the arithmetic
 * beside them, and the certification suite checks them against it.
 */
export const VC_ALLOCATION_DEMO = Object.freeze({
  available: true,
  weeklyMinimumCents: ECONOMY_STOP.weeklyMinCents,
  allocation: Object.freeze([
    Object.freeze({
      id: 'weekly-minimum', label: 'Weekly Minimum',
      amountCents: 1000, state: 'CONFIGURED', ratio: '1\u00d7',
      source: 'League economy configuration',
    }),
    Object.freeze({
      id: 'prop-pool-entry', label: 'Prop Pool Entry',
      amountCents: 100, state: 'CONFIGURED', ratio: '0.1\u00d7',
      source: 'League Pool settings',
    }),
    Object.freeze({
      id: 'weekly-skunk-fee', label: 'Weekly Skunk Fee',
      amountCents: 1000, state: 'CONFIGURED', ratio: '1\u00d7',
      source: 'Skunk rules',
    }),
    Object.freeze({
      id: 'projected-points-pot', label: 'Projected Points Championship Pot',
      amountCents: 14000, state: 'CONFIGURED', ratio: '14\u00d7',
      source: 'Projected \u2014 Skunk Fee across the regular season',
    }),
    Object.freeze({
      id: 'fantasystakes-base-pot', label: 'FantasyStakes Championship Base Pot',
      amountCents: 14000, state: 'CONFIGURED', ratio: '14\u00d7',
      source: 'Weekly Minimum across the regular season',
    }),
    Object.freeze({
      id: 'ff-championship-pot', label: 'Fantasy Football Championship Pot',
      amountCents: 8000, state: 'CONFIGURED', ratio: '8\u00d7',
      source: 'League economy configuration',
    }),
    Object.freeze({
      id: 'season-top-off-limit', label: 'Season Top-Off Limit',
      amountCents: 7000, state: 'CONFIGURED', ratio: '7\u00d7',
      source: 'Frozen top-off multiplier',
    }),
  ]),
  inSeason: Object.freeze([
    Object.freeze({ id: 'unspent-minimum-sweeps',
      label: 'Unspent Minimum Sweeps', amountCents: 0,
      source: 'Swept at week close' }),
    Object.freeze({ id: 'topoffs-added-to-fs-pot',
      label: 'Top-Offs Added to FS Pot', amountCents: 0,
      source: 'Added when a Top-Off is approved' }),
    Object.freeze({ id: 'terminal-pool-remainders',
      label: 'Terminal Prop Pool Remainders', amountCents: 0,
      source: 'Swept when a Pool cannot carry' }),
    Object.freeze({ id: 'current-fs-pot',
      label: 'Current FS Championship Pot', amountCents: 14000,
      source: 'Ledger balance' }),
  ]),
  seasonRules: Object.freeze([
    Object.freeze({ label: 'Weekly Minimum', value: 'Regular season only' }),
    Object.freeze({ label: 'Skunk Fees', value: 'Regular season only' }),
    Object.freeze({ label: 'Postseason play', value: 'Wallet only' }),
    Object.freeze({ label: 'Championship split', value: '60 / 30 / 10' }),
    Object.freeze({ label: 'Wagers', value: 'Public' }),
  ]),
});
