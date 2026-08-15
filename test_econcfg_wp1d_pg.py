#!/usr/bin/env python3
"""
test_econcfg_wp1d_pg.py — the combined economy parameterization + WP1D package.

THREE LIVE MONEY AUTHORITIES MOVED IN ONE PACKAGE, and this suite exists because
they moved together:

    1. the Season-Opening Allocation is funded from the league's frozen economy
       configuration instead of the fixed five-stop table;
    2. the weekly Skunk fee is the configured fee instead of a constant;
    3. the Championship Pot is paid to the POSTSEASON PODIUM instead of to the
       top three by regular-season Points For.

WHY ONE SUITE AND NOT THREE. The failure mode that matters is not any one of
these being wrong on its own — each is small and legible — it is a HYBRID: a
league funded from its configuration but releasing the legacy weekly minimum,
or charged a configured Skunk fee against a legacy allocation, or paid a
configured pot to the wrong three teams. A hybrid is only visible when the three
are asserted against each other in the same fixture, which is what §1-§3 below
do with two leagues that differ in exactly one fact: whether they configured.

THE DISCRIMINATING FIXTURE, stated once here because every section reuses it:

    League A  CONFIGURED    $25/wk x 14 weeks + $1,000  ->  $1,350 / $350 / $1,000
    League B  UNCONFIGURED  the certified legacy stop   ->  $220 / $140 / $80

If the authority had not moved, A would be issued B's numbers. If it moved too
far, B would be issued A's. Both are asserted, in both directions.

WHAT THIS SUITE DOES NOT RE-PROVE. `test_wp3_season_close_pg.py` proves the
PRODUCTION ROUTE derives a podium and pays it — a commissioner's HTTP close,
through the real orchestrator, to real wallets. This suite proves the podium's
own derivation and every way it refuses, which a route-level suite cannot reach
without constructing a dozen broken brackets.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.

Runs as: python test_econcfg_wp1d_pg.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP1D suite cannot run:\n  {e}")
    sys.exit(2)

import config  # noqa: E402
from providers.base import (  # noqa: E402
    Finality, MatchupBracket, ProviderMatchup, derive_matchup_key, orient,
)
from ledger.ledger import balance_of, trial_balance  # noqa: E402

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


SEASON = config.ALLOCATION_SEASON

#: League A's configuration. $25 a week, $1,000 to the Championship, $100 Skunk.
#: Chosen to be different from every legacy stop in all three inputs, so no
#: assertion below can pass by coincidence.
CFG_WEEKLY_CENTS = 2_500
CFG_CHAMPIONSHIP_CENTS = 100_000
CFG_SKUNK_CENTS = 10_000

#: The league's own provider boundaries. 14 regular-season weeks is DERIVED from
#: these two — 15 minus 1 — and is deliberately never written as a literal in
#: any production path this suite exercises.
START_WEEK = 1
PLAYOFF_START_WEEK = 15
SEASON_FINAL_WEEK = 17
EXPECTED_WEEK_COUNT = PLAYOFF_START_WEEK - START_WEEK

#: The certified legacy stop for a league that configures nothing.
LEGACY_BUYIN, LEGACY_MIN_RESERVE, LEGACY_RESERVE = 22_000, 14_000, 8_000

FIXTURE_FINAL = datetime(2025, 12, 30, 12, 0, tzinfo=timezone.utc)


# ── Fixture construction ─────────────────────────────────────────────────────

def make_league(db, *, name: str, teams: int = 4, configured: bool = False,
                playoff_start_week: int = PLAYOFF_START_WEEK,
                season_final_week: int = SEASON_FINAL_WEEK):
    """A league with provider boundaries, teams, wallets and provider identity.

    Teams are bound to the SYNTHETIC provider, never to Yahoo. Yahoo has no
    registered postseason bracket capability and must not acquire one by way of a
    fixture; binding synthetic material under Yahoo's name would certify a
    capability the product does not have.
    """
    from db.schema import League, Team, Wallet
    from economy.league_economy_config import set_draft
    from test_support_postseason import SYNTHETIC_PROVIDER

    league_key = f"synthetic.l.{name}"
    league = League(season=SEASON, name=name, projection_source="fantasypros",
                    start_week=START_WEEK,
                    playoff_start_week=playoff_start_week,
                    season_final_week=season_final_week,
                    provider=SYNTHETIC_PROVIDER, provider_league_key=league_key)
    db.add(league)
    db.flush()
    for i in range(teams):
        team = Team(league_id=league.id, team_name=f"{name}-t{i}",
                    owner=f"owner-{i}", email=f"{name}-{i}@x.test",
                    provider=SYNTHETIC_PROVIDER,
                    provider_team_key=f"{league_key}.t.{i}",
                    provider_team_id=i)
        db.add(team)
        db.flush()
        db.add(Wallet(team_id=team.id, balance=0.0))
    if configured:
        set_draft(db, league_id=league.id,
                  weekly_bet_minimum_cents=CFG_WEEKLY_CENTS,
                  championship_contribution_cents=CFG_CHAMPIONSHIP_CENTS,
                  skunk_fee_cents=CFG_SKUNK_CENTS)
    db.flush()
    return league


def team_ids(db, league_id: int) -> list[int]:
    from db.schema import Team

    return [t.id for t in db.query(Team).filter(Team.league_id == league_id)
            .order_by(Team.id).all()]


def synthetic_matchup(league_key: str, week: int, a: str, b: str, *,
                      bracket, winner=None, final=True, tied=False):
    """One normalized matchup, oriented and keyed the way production does it."""
    home, away = orient([a, b])
    return ProviderMatchup(
        provider="synthetic", league_key=league_key,
        matchup_key=derive_matchup_key(league_key, week, home, away),
        week=week, home_team_key=home, away_team_key=away,
        home_points=120.0, away_points=100.0,
        finality=Finality.FINAL if final else Finality.NOT_FINAL,
        winner_team_key=winner, is_tied=tied, bracket=bracket)


def bracket_state(league_key: str, keys, *, third_place: bool = True,
                  third_decided: bool = True, complete: bool = True,
                  classify: bool = True, season: int = SEASON):
    """A four-team championship as WP1A would determine it.

    `keys` is [champion, runner_up, third, fourth]. Every knob turns exactly one
    fact off so a refusal can be attributed to that fact and nothing else.
    """
    from season.championship_track import (
        ChampionshipFieldDeclaration, ChampionshipTrackInput,
        ChampionshipWeekInput, derive_championship_track_state,
    )

    champ, runner, third, fourth = keys[:4]
    semi_week, final_week = PLAYOFF_START_WEEK, PLAYOFF_START_WEEK + 1
    champ_bracket = (MatchupBracket.CHAMPIONSHIP if classify
                     else MatchupBracket.UNKNOWN)

    semis = (
        synthetic_matchup(league_key, semi_week, champ, third,
                          bracket=champ_bracket, winner=champ),
        synthetic_matchup(league_key, semi_week, runner, fourth,
                          bracket=champ_bracket, winner=runner),
    )
    finals = [synthetic_matchup(league_key, final_week, champ, runner,
                                bracket=champ_bracket,
                                winner=champ if complete else None,
                                final=complete)]
    if third_place:
        finals.append(synthetic_matchup(
            league_key, final_week, third, fourth,
            bracket=(MatchupBracket.NON_CHAMPIONSHIP if classify
                     else MatchupBracket.UNKNOWN),
            winner=third if third_decided else None,
            final=third_decided))

    return derive_championship_track_state(
        ChampionshipTrackInput(
            league_key=league_key, season=season,
            playoff_start_week=semi_week, season_final_week=final_week,
            weeks=(ChampionshipWeekInput(week=semi_week, matchups=semis),
                   ChampionshipWeekInput(week=final_week,
                                         matchups=tuple(finals))),
            field_declaration=ChampionshipFieldDeclaration(
                team_keys=frozenset(keys[:4]))),
        week=final_week)


class KeyResolver:
    def __init__(self, by_key):
        self._by_key = dict(by_key)

    def to_internal(self, team_key: str):
        return self._by_key.get(team_key)


def podium_reason(state, resolver):
    from economy.championship_podium import ChampionshipPodiumError, resolve_podium

    try:
        resolve_podium(state, resolver)
        return None
    except ChampionshipPodiumError as exc:
        return exc.reason


# ── 1 · The Season-Opening Allocation follows the configuration ──────────────

def case_allocation_authority(db) -> None:
    _section("WP1D-1 · Season-Opening Allocation — the inverted fence")
    from db.schema import SeasonAllocation
    from economy.season_allocation import activate_season_allocation

    a = make_league(db, name="wp1d-cfg", configured=True)
    b = make_league(db, name="wp1d-plain", configured=False)
    db.commit()

    activate_season_allocation(a.id, db)
    activate_season_allocation(b.id, db)

    def amounts(lid):
        return {(r.buyin_cents, r.min_reserve_cents, r.reserve_cents)
                for r in db.query(SeasonAllocation)
                .filter(SeasonAllocation.league_id == lid).all()}

    cfg, plain = amounts(a.id), amounts(b.id)
    expected_min = CFG_WEEKLY_CENTS * EXPECTED_WEEK_COUNT
    expected_buyin = expected_min + CFG_CHAMPIONSHIP_CENTS

    _assert("1a: League A is issued its OWN economy — $1,350 Season-Opening "
            "Allocation from $25/wk x 14 weeks plus a $1,000 Championship "
            "contribution",
            cfg == {(expected_buyin, expected_min, CFG_CHAMPIONSHIP_CENTS)}
            == {(135_000, 35_000, 100_000)}, detail=str(cfg))
    _assert("1b: League B, which configured nothing, is issued the CERTIFIED "
            "LEGACY STOP — $220 / $140 / $80, exactly as before this package",
            plain == {(LEGACY_BUYIN, LEGACY_MIN_RESERVE, LEGACY_RESERVE)},
            detail=str(plain))
    _assert("1c: and the two are DIFFERENT — a configuration that funded "
            "nothing would make these equal",
            cfg != plain, detail=f"{cfg} vs {plain}")

    _assert("1d: the Weekly Minimum reserve is EXACTLY the weekly amount times "
            "the derived week count — no week literal reaches the ledger",
            next(iter(cfg))[1] == CFG_WEEKLY_CENTS * EXPECTED_WEEK_COUNT,
            detail=str(next(iter(cfg))[1]))
    _assert("1e: and the allocation is exhaustive — reserve plus championship "
            "IS the allocation, with nothing issued outside the two",
            next(iter(cfg))[0] == next(iter(cfg))[1] + next(iter(cfg))[2])

    _assert("1f: the ledger balances after both activations",
            trial_balance() == 0, detail=str(trial_balance()))

    # ── NO MID-SEASON SWITCH, AND THE REFUSAL IS THE PROOF ───────────────────
    #
    # THE SCENARIO THAT WOULD PRODUCE A HYBRID: a league activated before this
    # package exists — legacy amounts, no configuration — whose commissioner
    # then configures one and re-runs activation. If the freeze took effect, the
    # league would be RELEASING $25 a week against a reserve funded at $10 a
    # week and would run dry two-thirds of the way through its season.
    #
    # It cannot happen, and not because anything special-cases it: activation's
    # own state machine compares the amounts it would issue against the amounts
    # already issued, finds them different, and refuses without mutating. The
    # frozen row written moments earlier in the same transaction goes with it.
    from economy.season_allocation import ConflictingAllocationError
    from economy.league_economy_config import read_frozen, set_draft
    from economy.skunk import resolve_skunk_fee_cents
    from economy.weekly_minimum import weekly_minimum_cents
    from db.schema import LeagueSeasonEconomyConfig

    set_draft(db, league_id=b.id, weekly_bet_minimum_cents=CFG_WEEKLY_CENTS,
              championship_contribution_cents=CFG_CHAMPIONSHIP_CENTS,
              skunk_fee_cents=CFG_SKUNK_CENTS)
    db.commit()

    hybrid = None
    try:
        activate_season_allocation(b.id, db)
        db.commit()
    except ConflictingAllocationError:
        hybrid = "REFUSED"
        db.rollback()

    _assert("1g: a league already issued at legacy amounts CANNOT be switched "
            "to a configured economy by re-running activation — it refuses "
            "rather than funding half a season on each basis",
            hybrid == "REFUSED", detail=str(hybrid))
    # THE DRAFT SURVIVES AND THE FREEZE DOES NOT, which is the right pair of
    # outcomes and not an accident of the rollback. The draft row is the
    # commissioner's own edit, committed before activation was ever attempted;
    # discarding it would throw away work they did. The STAMP is what would have
    # made it authoritative, and it is what the refusal took back — so
    # `read_frozen` still returns None and every path that resolves this
    # league's economy still resolves it as legacy.
    _assert("1h: and the refusal left NO FROZEN configuration behind — the "
            "stamp rolled back with the transaction that attempted it, so "
            "every path that reads this league still reads it as legacy",
            read_frozen(db, league_id=b.id, season=SEASON) is None)
    _assert("1h2: while the commissioner's DRAFT is still there, unstamped — "
            "a refused activation does not discard their edit",
            db.query(LeagueSeasonEconomyConfig).filter(
                LeagueSeasonEconomyConfig.league_id == b.id,
                LeagueSeasonEconomyConfig.frozen_at.is_(None)).count() == 1)
    _assert("1h3: and the league's live weekly minimum and Skunk fee are still "
            "the legacy amounts — the draft governs nothing",
            weekly_minimum_cents(db, b.id) == 1_000
            and resolve_skunk_fee_cents(db, league_id=b.id, season=SEASON)
            == 1_000,
            detail=f"{weekly_minimum_cents(db, b.id)} / "
                   f"{resolve_skunk_fee_cents(db, league_id=b.id, season=SEASON)}")
    _assert("1i: its allocation is untouched and still the legacy stop",
            amounts(b.id) == plain, detail=str(amounts(b.id)))
    return a, b


# ── 2 · The Weekly Minimum releases what it was funded for ───────────────────

def case_weekly_minimum(db, configured, plain) -> None:
    _section("WP1D-2 · Weekly Minimum — exhaustion-bounded, not week-counted")
    from economy.economy_events import min_reserve_account
    from economy.weekly_minimum import (
        WeeklyMinimumError, release_week, weekly_minimum_cents,
    )

    _assert("2a: the configured league's weekly release amount is its OWN $25, "
            "read through the same resolution that funded the reserve",
            weekly_minimum_cents(db, configured.id) == CFG_WEEKLY_CENTS,
            detail=str(weekly_minimum_cents(db, configured.id)))
    _assert("2b: the unconfigured league still releases the legacy stop's "
            "weekly amount",
            weekly_minimum_cents(db, plain.id) == 1_000,
            detail=str(weekly_minimum_cents(db, plain.id)))

    # RELEASE UNTIL IT IS EMPTY. The loop is bounded by the reserve running out,
    # not by a week count — the same discipline the production release has. If
    # the allocation and the release disagreed, this would stop at the wrong
    # week and the assertion below would name it.
    tids = team_ids(db, configured.id)
    released_weeks = 0
    refusal = None
    for week in range(START_WEEK, PLAYOFF_START_WEEK + 5):
        try:
            release_week(db, league_id=configured.id, week=week)
            # COMMITTED each week, because `balance_of` opens its own
            # connection and would not see an uncommitted release.
            db.commit()
            released_weeks += 1
        except WeeklyMinimumError as exc:
            db.rollback()
            refusal = exc.reason
            break

    _assert("2c: the reserve is EXHAUSTED after exactly the derived number of "
            "regular-season weeks — funded for 14, releases 14",
            released_weeks == EXPECTED_WEEK_COUNT,
            detail=f"{released_weeks} vs {EXPECTED_WEEK_COUNT}")
    _assert("2d: and min_reserve is EMPTY for every GM — the bound is the "
            "reserve running out, not a week number written anywhere",
            all(balance_of(min_reserve_account(t)) == 0 for t in tids),
            detail=str([balance_of(min_reserve_account(t)) for t in tids]))
    _assert("2d2: the loop stopped because week 15 is not a governed "
            "regular-season week — and the reserve was already exactly empty "
            "when it did, which is the two bounds agreeing rather than one "
            "hiding the other",
            refusal == "NOT_APPLICABLE_WEEK", detail=str(refusal))
    _assert("2e: the ledger still balances", trial_balance() == 0,
            detail=str(trial_balance()))


# ── 3 · The Skunk fee follows the configuration ──────────────────────────────

def case_skunk_fee(db, configured, plain) -> None:
    _section("WP1D-3 · the weekly Skunk fee")
    from economy.skunk import (
        DEFAULT_SKUNK_CONTRIBUTION_CENTS, resolve_skunk_fee_cents,
    )

    _assert("3a: the configured league is charged its own $100 weekly fee",
            resolve_skunk_fee_cents(db, league_id=configured.id,
                                    season=SEASON) == CFG_SKUNK_CENTS,
            detail=str(resolve_skunk_fee_cents(db, league_id=configured.id,
                                               season=SEASON)))
    _assert("3b: the unconfigured league is charged the certified $10 default",
            resolve_skunk_fee_cents(db, league_id=plain.id, season=SEASON)
            == DEFAULT_SKUNK_CONTRIBUTION_CENTS == 1_000,
            detail=str(resolve_skunk_fee_cents(db, league_id=plain.id,
                                               season=SEASON)))


# ── 4 · The podium is derived from the bracket ──────────────────────────────

def case_podium_derivation(db) -> None:
    _section("WP1D-4 · the podium — champion, runner-up, third-place winner")
    from economy.championship_podium import derive_podium_keys, resolve_podium

    lk = "synthetic.l.podium-ok"
    keys = [f"{lk}.t.{i}" for i in range(4)]
    state = bracket_state(lk, keys)

    _assert("4a: the podium keys are champion, runner-up and the THIRD-PLACE "
            "GAME's winner — in that order",
            derive_podium_keys(state) == (keys[0], keys[1], keys[2]),
            detail=str(derive_podium_keys(state)))
    _assert("4b: the fourth team — the third-place game's LOSER — is not on it",
            keys[3] not in derive_podium_keys(state))

    resolver = KeyResolver({k: 100 + i for i, k in enumerate(keys)})
    podium = resolve_podium(state, resolver)
    _assert("4c: resolving through the league-scoped identity seam gives three "
            "internal ids in the same order",
            podium.team_ids == (100, 101, 102), detail=str(podium.team_ids))
    _assert("4d: and the provider keys are carried alongside, so a refusal or "
            "an audit line can name the teams without a second lookup",
            podium.provider_keys == (keys[0], keys[1], keys[2]))
    _assert("4e: the named accessors agree with the ordered tuple",
            (podium.champion_team_id, podium.runner_up_team_id,
             podium.third_place_team_id) == podium.team_ids)


# ── 5 · Every way the podium refuses ────────────────────────────────────────

def case_podium_refusals(db) -> None:
    _section("WP1D-5 · fail closed — every refusal, by name")
    from economy.championship_podium import (
        REASON_DUPLICATE_RECIPIENT, REASON_NO_THIRD_PLACE_GAME,
        REASON_NOT_COMPLETE, REASON_NO_TRACK_STATE, REASON_THIRD_PLACE_UNDECIDED,
        REASON_TRACK_UNKNOWN, REASON_UNRESOLVED_TEAM,
    )

    lk = "synthetic.l.podium-refuse"
    keys = [f"{lk}.t.{i}" for i in range(4)]
    full = KeyResolver({k: 200 + i for i, k in enumerate(keys)})

    _assert("5a: NO STATE AT ALL refuses — there is no standings, seed or "
            "scoring order to fall back to",
            podium_reason(None, full) == REASON_NO_TRACK_STATE,
            detail=str(podium_reason(None, full)))

    unclassified = bracket_state(lk, keys, classify=False)
    _assert("5b: AN UNCLASSIFIED BRACKET refuses — this is exactly what a live "
            "Yahoo league produces today, and it must not pay anyone",
            podium_reason(unclassified, full) == REASON_TRACK_UNKNOWN,
            detail=str(podium_reason(unclassified, full)))

    unfinished = bracket_state(lk, keys, complete=False)
    _assert("5c: AN UNDECIDED FINAL refuses — no champion, no payout",
            podium_reason(unfinished, full) in (REASON_NOT_COMPLETE,
                                                REASON_TRACK_UNKNOWN),
            detail=str(podium_reason(unfinished, full)))

    no_third = bracket_state(lk, keys, third_place=False)
    _assert("5d: NO OFFICIAL THIRD-PLACE GAME refuses rather than substituting "
            "a fourth recipient of its own choosing",
            podium_reason(no_third, full) == REASON_NO_THIRD_PLACE_GAME,
            detail=str(podium_reason(no_third, full)))

    undecided_third = bracket_state(lk, keys, third_decided=False)
    _assert("5e: AN UNDECIDED THIRD-PLACE GAME refuses the WHOLE podium — not "
            "just its third place — because a partial payout would strand 10%",
            podium_reason(undecided_third, full) == REASON_THIRD_PLACE_UNDECIDED,
            detail=str(podium_reason(undecided_third, full)))

    good = bracket_state(lk, keys)
    partial = KeyResolver({k: 200 + i for i, k in enumerate(keys[:2])})
    _assert("5f: A PODIUM TEAM WITH NO INTERNAL IDENTITY refuses — two of "
            "three paid is not a governed outcome",
            podium_reason(good, partial) == REASON_UNRESOLVED_TEAM,
            detail=str(podium_reason(good, partial)))

    collided = KeyResolver({k: 999 for k in keys})
    _assert("5g: A RESOLVER THAT COLLAPSES TWO TEAMS ONTO ONE ID refuses — the "
            "same wallet cannot hold two places",
            podium_reason(good, collided) == REASON_DUPLICATE_RECIPIENT,
            detail=str(podium_reason(good, collided)))

    cross = KeyResolver({f"other.l.x.t.{i}": 300 + i for i in range(4)})
    _assert("5h: A CROSS-LEAGUE RESOLVER resolves nothing and refuses — a "
            "league-scoped resolver cannot pay a stranger",
            podium_reason(good, cross) == REASON_UNRESOLVED_TEAM,
            detail=str(podium_reason(good, cross)))


# ── 6 · The distribution: recipients change, arithmetic does not ────────────

def case_distribution(db) -> None:
    _section("WP1D-6 · 60/30/10 is untouched; only WHO receives it moved")
    from economy.championship import championship_distribution
    from economy.economy_events import championship_account, wallet_account
    from economy.season_reconciliation import (
        SeasonReconciliationError, distribute_championship,
    )
    from ledger.ledger import post as ledger_post

    league = make_league(db, name="wp1d-dist", teams=4)
    db.commit()
    tids = team_ids(db, league.id)
    lk = league.provider_league_key
    keys = [f"{lk}.t.{i}" for i in range(4)]

    # A pot the split cannot divide evenly, so the remainder rule is exercised
    # rather than assumed: 1001 -> 600/300/100 leaves 1 cent, all to first.
    pot = 1_001
    ledger_post([("world", -pot), (championship_account(league.id), pot)],
                door="pool_championship_sweep", session=db)
    # COMMITTED, because `balance_of` opens its own connection: an uncommitted
    # posting is invisible to it and every balance assertion below would read a
    # confident zero. The engine under test is unaffected either way.
    db.commit()

    # THE PODIUM IS t2, t3, t0 — deliberately NOT ascending id and NOT the first
    # three teams, so an implementation that paid by insertion order or by id
    # would produce a different, plausible-looking answer.
    order_keys = [keys[2], keys[3], keys[0], keys[1]]
    state = bracket_state(lk, order_keys)
    resolver = KeyResolver({f"{lk}.t.{i}": tids[i] for i in range(4)})

    before = {t: balance_of(wallet_account(t)) for t in tids}
    result = distribute_championship(db, league_id=league.id,
                                     podium_source=lambda: (state, resolver))
    db.commit()

    placements = [(p, t, pct, cents) for p, t, pct, cents in result.placements]
    _assert("6a: the recipients are the CHAMPION, RUNNER-UP and THIRD-PLACE "
            "winner — not ascending team id, not the first three teams",
            [t for _, t, _, _ in placements] == [tids[2], tids[3], tids[0]]
            != sorted(tids)[:3],
            detail=str([t for _, t, _, _ in placements]))

    # BYTE-EQUIVALENT ARITHMETIC. The accepted pure function is called with the
    # SAME pot and the SAME split, and its output is compared against what the
    # distribution actually posted. A change to the percentages or the remainder
    # rule fails here even if every recipient is right.
    expected = championship_distribution(pot, [60, 30, 10],
                                         [tids[2], tids[3], tids[0]])
    _assert("6b: the placements are EXACTLY what the accepted pure "
            "`championship_distribution` produces for that pot and order",
            placements == list(expected), detail=f"{placements} vs {expected}")
    _assert("6c: 60/30/10 with the WHOLE indivisible remainder to first place",
            [c for _, _, _, c in placements] == [601, 300, 100],
            detail=str([c for _, _, _, c in placements]))
    _assert("6d: the split is exhaustive — the pot is conserved to the cent",
            sum(c for _, _, _, c in placements) == pot == result.pot_cents)

    after = {t: balance_of(wallet_account(t)) for t in tids}
    _assert("6e: each placed GM's own wallet moved by exactly their share",
            [after[t] - before[t] for t in (tids[2], tids[3], tids[0])]
            == [601, 300, 100],
            detail=str([after[t] - before[t] for t in tids]))
    _assert("6f: the unplaced GM received nothing",
            after[tids[1]] - before[tids[1]] == 0)
    _assert("6g: the Championship account is drained and the ledger balances",
            balance_of(championship_account(league.id)) == 0
            and trial_balance() == 0)

    # AND THERE IS NO FALLBACK. The same league, an unclassifiable bracket: the
    # distribution refuses rather than reverting to regular-season order.
    second = make_league(db, name="wp1d-dist-refuse", teams=4)
    db.commit()
    stids = team_ids(db, second.id)
    slk = second.provider_league_key
    skeys = [f"{slk}.t.{i}" for i in range(4)]
    ledger_post([("world", -500), (championship_account(second.id), 500)],
                door="pool_championship_sweep", session=db)
    db.commit()
    unknown = bracket_state(slk, skeys, classify=False)
    sresolver = KeyResolver({k: stids[i] for i, k in enumerate(skeys)})

    from economy.championship_podium import ChampionshipPodiumError

    refused = None
    try:
        distribute_championship(db, league_id=second.id,
                                podium_source=lambda: (unknown, sresolver))
    except ChampionshipPodiumError as exc:
        refused = exc.reason
    _assert("6h: an unclassifiable bracket REFUSES the distribution — it does "
            "NOT fall back to regular-season Points For",
            refused == "PODIUM_STATE_UNKNOWN", detail=str(refused))
    _assert("6i: and the pot is untouched — nothing was paid to anyone",
            balance_of(championship_account(second.id)) == 500,
            detail=str(balance_of(championship_account(second.id))))

    # AN EMPTY POT STILL DOES NOT NEED A PODIUM, which is what lets a league
    # whose bracket was never classified still close when it owes nobody.
    third = make_league(db, name="wp1d-dist-empty", teams=4)
    db.commit()
    empty_reason = None
    try:
        distribute_championship(db, league_id=third.id,
                                podium_source=lambda: (None, None))
    except SeasonReconciliationError as exc:
        empty_reason = exc.reason
        db.rollback()
    _assert("6j: an EMPTY pot refuses with EMPTY_POT before the podium is ever "
            "consulted — the close of a league that owes nobody is not held "
            "hostage to a bracket",
            empty_reason == "EMPTY_POT", detail=str(empty_reason))


# ── 7 · Refusal, rollback, retry ────────────────────────────────────────────

def case_refusal_and_retry() -> None:
    _section("WP1D-7 · a refused close writes nothing and stays retryable")
    from db.schema import League, Matchup, SessionLocal
    from economy.championship_podium import ChampionshipPodiumError
    from economy.economy_events import championship_account
    from economy.season_allocation import activate_season_allocation
    from economy.season_close_orchestrator import close_season_economy
    from economy.skunk import assess_weekly_skunk
    from economy.weekly_minimum import expire_week, release_week
    from ledger.ledger import post as ledger_post

    # A league driven to the brink of a legitimate close. Its postseason weeks
    # are irrelevant to the preconditions — the Weekly Minimum and Skunk cutoff
    # is `min(final_week, playoff_start_week - 1)` — so a short season keeps the
    # fixture small without weakening anything the close checks.
    with SessionLocal() as db:
        league = make_league(db, name="wp1d-retry", teams=4,
                             playoff_start_week=6, season_final_week=7)
        db.commit()
        lid = league.id
        lk = league.provider_league_key
        tids = team_ids(db, lid)

    with SessionLocal() as s:
        activate_season_allocation(lid, s)
    with SessionLocal() as s:
        for week in (3, 4):
            s.add(Matchup(league_id=lid, week=week, home_team_id=tids[0],
                          away_team_id=tids[1], home_score=120.0,
                          away_score=100.0, finalized_at=FIXTURE_FINAL))
            s.add(Matchup(league_id=lid, week=week, home_team_id=tids[2],
                          away_team_id=tids[3], home_score=110.0,
                          away_score=105.0, finalized_at=FIXTURE_FINAL))
        s.commit()
    with SessionLocal() as s:
        for week in (3, 4):
            release_week(s, league_id=lid, week=week)
            expire_week(s, league_id=lid, week=week)
            assess_weekly_skunk(s, league_id=lid, week=week)
        s.commit()

    from economy.economy_events import reserve_account

    # THE POT DOES NOT EXIST YET, AND THAT IS THE SHAPE OF THE TEST. Every GM's
    # Championship contribution sits in `reserve:{team}` until step 11 of the
    # close sweeps it into `championship:{league}`. So what a refusal must leave
    # untouched is the RESERVES — if the sweep were not rolled back with the rest
    # of the close, this money would be sitting in a pot nobody was paid from.
    reserves_before = sum(balance_of(reserve_account(t)) for t in tids)
    pot_before = balance_of(championship_account(lid))
    _assert("7a: the league has Championship reserves the close will sweep, and "
            "no pot yet",
            reserves_before > 0 and pot_before == 0,
            detail=f"reserves={reserves_before} pot={pot_before}")

    keys = [f"{lk}.t.{i}" for i in range(4)]
    resolver = KeyResolver({k: tids[i] for i, k in enumerate(keys)})
    unknown = bracket_state(lk, keys, classify=False)
    good = bracket_state(lk, keys)

    refused = None
    with SessionLocal() as s:
        try:
            close_season_economy(s, league_id=lid, final_week=7,
                                 podium_source=lambda: (unknown, resolver))
            s.commit()
        except ChampionshipPodiumError as exc:
            refused = exc.reason
            s.rollback()

    _assert("7b: the close REFUSES on an unclassifiable bracket, naming the "
            "condition an operator must wait for",
            refused == "PODIUM_STATE_UNKNOWN", detail=str(refused))

    with SessionLocal() as s:
        still_open = (s.query(League).filter(League.id == lid).first()
                      .season_closed_at is None)
        s.rollback()
    _assert("7c: the season is STILL OPEN — the refusal rolled back the reserve "
            "sweep and the Skunk distribution that ran before it, so the league "
            "is exactly as it was",
            still_open)
    _assert("7d: EVERY GM'S RESERVE IS INTACT TO THE CENT — the reserve sweep "
            "that ran before the podium refusal was rolled back with it, so no "
            "money is stranded in a pot that was never distributed",
            sum(balance_of(reserve_account(t)) for t in tids) == reserves_before
            and balance_of(championship_account(lid)) == 0,
            detail=f"{sum(balance_of(reserve_account(t)) for t in tids)} vs "
                   f"{reserves_before}")
    _assert("7e: and the ledger balances after the refusal",
            trial_balance() == 0, detail=str(trial_balance()))

    # THE RETRY. Nothing about the league changed except that its bracket became
    # authoritative — which is precisely the operational situation the refusal
    # exists to wait for.
    with SessionLocal() as s:
        report = close_season_economy(s, league_id=lid, final_week=7,
                                      podium_source=lambda: (good, resolver))
        s.commit()

    _assert("7f: THE RETRY CLOSES — the same league, the same money, the same "
            "call, once the bracket is authoritative",
            report.closed_now is True)
    _assert("7g: and the pot went to the podium, first place first",
            [t for _, t, _, _ in report.championship_placements]
            == [tids[0], tids[1], tids[2]],
            detail=str([t for _, t, _, _ in report.championship_placements]))
    _assert("7h: the pot is drained, the reserves are swept and the ledger "
            "balances after the close",
            balance_of(championship_account(lid)) == 0
            and sum(balance_of(reserve_account(t)) for t in tids) == 0
            and trial_balance() == 0, detail=str(trial_balance()))
    _assert("7h2: and what was distributed IS the reserves the refusal "
            "preserved — the same money, paid on the retry",
            report.championship_pot_cents == reserves_before,
            detail=f"{report.championship_pot_cents} vs {reserves_before}")

    # AND THE CLOSE IS STILL IDEMPOTENT. A second call replays rather than
    # re-paying, and it does so WITHOUT needing the bracket at all.
    with SessionLocal() as s:
        again = close_season_economy(s, league_id=lid, final_week=7,
                                     podium_source=lambda: (None, None))
        s.commit()
    _assert("7i: a repeated close REPLAYS and re-posts nothing — and needs no "
            "podium to do it, because it returns before distribution",
            again.replayed is True and again.closed_now is False)
    _assert("7j: no GM gained a second payout", trial_balance() == 0)


# ── 8 · No hidden bypass survives ───────────────────────────────────────────

def case_no_bypass(db) -> None:
    _section("WP1D-8 · the recipient order cannot be named from outside")
    import inspect

    import economy.season_close_orchestrator as orch
    import economy.season_reconciliation as recon

    close_params = inspect.signature(orch.close_season_economy).parameters
    _assert("8a: `close_season_economy` accepts NO recipient order — the "
            "parameter was removed, not defaulted",
            "standings_order" not in close_params,
            detail=str(list(close_params)))
    _assert("8b: it accepts a podium SOURCE instead, from which an order is "
            "derived rather than stated",
            "podium_source" in close_params)

    _assert("8c: `distribute_championship` no longer calls "
            "`default_standings_order` on any path",
            "default_standings_order"
            not in inspect.getsource(recon.distribute_championship))
    _assert("8d: and it does call the podium",
            "resolve_podium" in inspect.getsource(recon.distribute_championship))

    _assert("8e: `default_standings_order` is GONE from the module entirely — "
            "after the authority moved it had no caller, and an uncalled "
            "function that computes a payout order is how a defect gets "
            "re-wired by someone reaching for the obvious name",
            getattr(recon, "default_standings_order", None) is None)

    from economy.skunk import season_points_for

    _assert("8e2: and regular-season Points For still ranks the SKUNK Pot, "
            "through its own function — the two authorities are separate "
            "code, not one function with two callers",
            callable(season_points_for)
            and "season_points_for" in inspect.getsource(
                __import__("economy.skunk", fromlist=["x"])
                .distribute_season_skunk))

    # THE DOCSTRING IS NOT THE CODE, and scanning it would have failed on the
    # very sentences that explain WHY these authorities are refused. Only NAME
    # tokens are compared — identifiers and attributes the function actually
    # reads — so prose about seeds and scores cannot make this pass or fail.
    import io
    import tokenize

    from economy.championship_podium import derive_podium_keys

    names = set()
    src = inspect.getsource(derive_podium_keys)
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.NAME:
            names.add(tok.string.lower())

    for forbidden in ("points", "score", "scores", "seed", "seeds",
                      "standings", "standings_order", "home_points",
                      "away_points"):
        _assert(f"8f: the podium derivation reads no '{forbidden}' — it "
                f"consults the provider's declared winners and nothing else",
                forbidden not in names, detail=sorted(names & {forbidden}))


# ── 9 · The configured-state consistency guard ──────────────────────────────

def case_consistency_guard(db) -> None:
    _section("WP1D-9 · a league cannot be half-configured")
    from db.schema import LeagueSeasonEconomyConfig, SeasonAllocation
    from economy.season_allocation import activate_season_allocation
    from payments.economy_config import (
        InconsistentEconomyStateError, assert_consistent_configured_state,
    )

    league = make_league(db, name="wp1d-guard", configured=True)
    db.commit()
    activate_season_allocation(league.id, db)
    db.commit()

    _assert("9a: a configured, activated league is consistent",
            assert_consistent_configured_state(db, league_id=league.id,
                                               season=SEASON) is True)

    # Delete the frozen row out from under an allocation that was funded from
    # it. Nothing in the product can do this; the guard exists because a
    # restore, a manual repair or a migration error can.
    (db.query(LeagueSeasonEconomyConfig)
     .filter(LeagueSeasonEconomyConfig.league_id == league.id).delete())
    db.flush()

    caught = None
    try:
        assert_consistent_configured_state(db, league_id=league.id,
                                           season=SEASON)
    except InconsistentEconomyStateError as exc:
        caught = str(exc)
    _assert("9b: an allocation matching NO certified stop with NO frozen "
            "configuration behind it FAILS CLOSED — it is not silently read as "
            "a legacy league",
            caught is not None, detail=str(caught)[:120])

    _assert("9c: and the allocation rows are still there — the guard reads, it "
            "does not repair",
            db.query(SeasonAllocation)
            .filter(SeasonAllocation.league_id == league.id).count() == 4)
    db.rollback()


def main() -> None:
    from db.schema import SessionLocal

    with SessionLocal() as db:
        configured, plain = case_allocation_authority(db)
        case_weekly_minimum(db, configured, plain)
        case_skunk_fee(db, configured, plain)
        db.commit()
    with SessionLocal() as db:
        case_podium_derivation(db)
        case_podium_refusals(db)
        case_distribution(db)
        db.commit()
    with SessionLocal() as db:
        case_consistency_guard(db)
    case_refusal_and_retry()
    with SessionLocal() as db:
        case_no_bypass(db)


if __name__ == "__main__":
    print("\n=== ECONCFG + WP1D certification suite (PostgreSQL) ===")
    try:
        main()
    finally:
        tdb.teardown()
    print(f"\n{'-' * 70}")
    if _failures:
        print(f"RESULT: {len(_failures)} assertion(s) FAILED")
        for f in _failures:
            print(f"  - {f}")
        sys.exit(1)
    print("RESULT: all assertions PASSED")
