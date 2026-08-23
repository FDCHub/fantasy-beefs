#!/usr/bin/env python3
"""FINAL POR · WP-14 certification — the Grand Championship as a VC total.

    F1  the FantasyStakes Championship can now be PAID (WP-8's terminal state)
    F2  a Grand Total is championship Credits, not 3/2/1 points
    F3  at least two FUNDED pillars are required
    F4  FUNDED counts a pillar that has already paid out
    F5  regular season is a PLACEHOLDER with NO ROWS
    F6  postseason is LIVE from FINALIZED components only
    F7  FINAL once every funded pillar has paid
    F8  a tied TOTAL is a dead heat with no tiebreak
    F9  nothing here posts — every Credit was already awarded
    F10 the retired 3/2/1 model is not consulted, and the legacy era is refused

WHY F4 IS ITS OWN ASSERTION. `funded_pillars` could plausibly have been written
as a balance test, and it would have passed every test that checks it before
distribution — then silently stopped counting a pillar at the exact moment it
paid out, which is the moment the Grand Championship needs it. The suite pays a
pillar and then requires it to still count.

WHY F2 PROVES THE WEIGHTING. Under 3/2/1 a GM who won a tiny pot and a GM who
won a huge one both scored 3. The fixture funds one pillar at 20x the other and
requires the Grand Champion to be the GM who won the larger one — which is the
whole behavioural difference between the two models.
"""
from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import economy.fantasystakes_championship_settlement  # noqa: F401
import ledger.ledger as ledger_module
from db.schema import (
    Base, League, LeagueSeasonEconomyConfig, Matchup, Team, Wallet,
)
from economy.championship_pots import (
    mint_fantasy_football_pot, pillar_awards, pillar_funded_cents,
)
from economy.economy_events import (
    PILLAR_FANTASY_FOOTBALL, PILLAR_FANTASYSTAKES, PILLAR_POINTS,
)
from economy.fantasystakes_championship_final import (
    FantasyStakesChampionshipFinalError, settle as settle_fs,
)
from economy.ff_championship_settlement import settle as settle_ff
from economy.grand_championship import (
    GRAND_FINAL, GRAND_LIVE, GRAND_PLACEHOLDER, GRAND_STATES,
    GrandChampionshipError, MINIMUM_FUNDED_PILLARS, funded_pillars,
    finalized_pillars, view,
)
from ledger.ledger import APPROVED_BAB_TOPOFF_DOOR, post as ledger_post
from ruleset import RULESET_FINAL_POR, stamp_ruleset

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
NAIVE = NOW.replace(tzinfo=None)

LEAGUE = 1
SEASON = 2026
PLAYOFF_START = 3          # weeks 1-2 regular, 3 postseason
TEAMS = (1, 2, 3, 4)
KEYS = {t: f"k{t}" for t in TEAMS}
FS_POT = 20_000            # the big pillar
FF_POT = 1_000             # the small one — 20x smaller


@dataclass(frozen=True)
class _Game:
    winner_team_key: str
    is_decided: bool = True


@dataclass(frozen=True)
class _Bracket:
    """A hand-stated Fantasy Football bracket. See WP-11's suite for why."""
    authority: str = "PROVIDER"
    insufficiency_reasons: tuple = ()
    complete: bool = True
    champion_team_key: str = KEYS[4]
    finalist_team_keys: tuple = (KEYS[4], KEYS[3])
    third_place_matchup: object = _Game(winner_team_key=KEYS[2])
    # A FOUR-TEAM OFFICIAL FIELD, so this bracket takes the standard 60/30/10.
    # Required since the two-team playoff ruling: the settlement decides the
    # structure from the declared field size BEFORE it looks for a third-place
    # game, precisely so a missing field cannot be read as a two-team format.
    championship_field_team_keys: frozenset = frozenset(
        {KEYS[1], KEYS[2], KEYS[3], KEYS[4]})


def _build(*, final_por: bool = True, postseason_played: bool = True):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=LEAGUE, name="L", season=SEASON, start_week=1,
                  playoff_start_week=PLAYOFF_START, provider="yahoo"))
    for t in TEAMS:
        db.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider="yahoo",
                    provider_team_key=KEYS[t]))
        db.add(Wallet(team_id=t, balance=0.0))
    last = PLAYOFF_START if postseason_played else PLAYOFF_START - 1
    mid = 0
    for week in range(1, last + 1):
        mid += 1
        db.add(Matchup(id=mid, league_id=LEAGUE, week=week, home_team_id=1,
                       away_team_id=2, home_score=100.0, away_score=90.0,
                       winner_team_id=1, finalized_at=NAIVE))
        mid += 1
        db.add(Matchup(id=mid, league_id=LEAGUE, week=week, home_team_id=3,
                       away_team_id=4, home_score=80.0, away_score=95.0,
                       winner_team_id=4, finalized_at=NAIVE))
    db.add(LeagueSeasonEconomyConfig(
        league_id=LEAGUE, season=SEASON,
        weekly_bet_minimum_cents=1_000,
        championship_contribution_cents=8_000,
        skunk_fee_cents=500,
        regular_season_week_count=PLAYOFF_START - 1,
        active_team_count=len(TEAMS),
        start_week_used=1, playoff_start_week_used=PLAYOFF_START,
        frozen_at=NAIVE))
    db.commit()
    if final_por:
        stamp_ruleset(db, league_id=LEAGUE, season=SEASON,
                      version=RULESET_FINAL_POR)
        db.commit()
    return db


def _fund_fs_pot(db, cents: int):
    """Credit the FantasyStakes pot the way a season really credits it.

    Through the canonical Top-Off door, which WP-6 made a real funding source
    for this pot — rather than by writing a balance, so the funded-balance guard
    is exercised exactly as in production."""
    ledger_post([(f"bab_issuance:{LEAGUE}:{SEASON}", -cents * 2),
                 (f"wallet:1", cents),
                 (f"fantasystakes_championship:{LEAGUE}:{SEASON}", cents)],
                door=APPROVED_BAB_TOPOFF_DOOR, session=db)
    db.commit()


def _win_versus(db, *, winner: int, loser: int, stake: int, bet_id: int,
                matchup_id: int):
    """A settled two-sided wager, so the FantasyStakes Score really separates."""
    from db.schema import BeefChallenge, Bet

    db.add(BeefChallenge(id=bet_id, league_id=LEAGUE, week=1,
                         challenger_team_id=winner, challenged_team_id=loser,
                         bet_type="straight", amount=stake / 100.0,
                         challenger_odds=2.0, challenged_odds=2.0,
                         challenger_moneyline=100, challenged_moneyline=100,
                         expires_at=NAIVE, status="accepted",
                         response_status="accepted", created_at=NAIVE))
    for offset, team in ((0, winner), (1, loser)):
        wallet = db.query(Wallet).filter(Wallet.team_id == team).first()
        db.add(Bet(id=bet_id + offset, matchup_id=matchup_id,
                   wallet_id=wallet.id, amount=stake / 100.0,
                   picked_team_id=team,
                   status=("won" if team == winner else "lost"),
                   placed_at=NAIVE, beef_challenge_id=bet_id))
    db.flush()
    # FUND BOTH WALLETS AND COMMIT BEFORE EITHER STAKE IS PLACED. The ledger's
    # funded-balance guard reads posted state, so a top-off still sitting
    # unflushed in the session is not yet capacity.
    for team in (winner, loser):
        ledger_post([(f"bab_issuance:{LEAGUE}:{SEASON}", -stake),
                     (f"wallet:{team}", stake)],
                    door=APPROVED_BAB_TOPOFF_DOOR, session=db)
    db.commit()
    for offset, team in ((0, winner), (1, loser)):
        ledger_post([(f"wallet:{team}", -stake),
                     (f"escrow:{bet_id + offset}", stake)],
                    door="wager_placed", session=db)
        db.flush()
    ledger_post([(f"escrow:{bet_id}", -stake),
                 (f"escrow:{bet_id + 1}", -stake),
                 (f"wallet:{winner}", stake * 2)],
                door="wager_settled", session=db)
    db.commit()


def _bal(db, account: str) -> int:
    return ledger_module._balance_of_in_session(db, account)


# ── F1 · the FantasyStakes Championship can be PAID ─────────────────────────

print("\nWP14-F1 · WP-8's terminal state is reachable — the FS pot can be PAID")
db = _build()
_fund_fs_pot(db, FS_POT)
_win_versus(db, winner=1, loser=2, stake=500, bet_id=1, matchup_id=1)

fs_result = settle_fs(db, league_id=LEAGUE, season=SEASON, now=NOW)
db.commit()
fs_by_team = {t: (place, amount) for t, place, amount, _s in fs_result.placements}

_assert("the FantasyStakes Championship pays without any frozen snapshot",
        fs_result.pot_cents == FS_POT, str(fs_result.pot_cents))
_assert("  · no freeze marker exists",
        db.execute(text("SELECT COUNT(*) FROM "
                        "fantasystakes_championship_freeze")).scalar() == 0)
_assert("  · ranked on the LIVE FantasyStakes Score",
        fs_by_team[1][0] == 1, str(fs_result.placements))
_assert("  · 60/30/10 of the pot", fs_by_team[1][1] == 12_000,
        str(fs_by_team[1][1]))
_assert("  · the pot is drained",
        _bal(db, f"fantasystakes_championship:{LEAGUE}:{SEASON}") == 0)
_assert("  · and the lifecycle now reports PAID",
        __import__("economy.fantasystakes_lifecycle", fromlist=["x"])
        .lifecycle_state(db, league_id=LEAGUE) == "PAID")
try:
    settle_fs(db, league_id=LEAGUE, season=SEASON, now=NOW)
    _assert("  · a second settlement is refused", False, "accepted")
except FantasyStakesChampionshipFinalError as exc:
    db.rollback()
    _assert("  · a second settlement is refused",
            exc.reason == "FS_FINAL_ALREADY_PAID", exc.reason)


# ── F2/F3/F4 · funded pillars, and VC weighting ────────────────────────────

print("\nWP14-F2 · a Grand Total is championship CREDITS, not 3/2/1 points")
mint_fantasy_football_pot(db, league_id=LEAGUE, season=SEASON,
                          amount_cents=FF_POT, now=NOW)
db.commit()
settle_ff(db, league_id=LEAGUE, state=_Bracket(), now=NOW)
db.commit()

grand = view(db, league_id=LEAGUE, season=SEASON)
rows = {r.team_id: r for r in grand.rows}

_assert("the FantasyStakes winner took 12000 and the FF winner 600",
        rows[1].by_pillar.get(PILLAR_FANTASYSTAKES) == 12_000
        and rows[4].by_pillar.get(PILLAR_FANTASY_FOOTBALL) == 600,
        str(grand.as_dict()["rows"]))
_assert("  · so the Grand Champion is the GM who won the BIGGER pillar",
        grand.champion_team_ids == (1,), str(grand.champion_team_ids))
_assert("  · which under 3/2/1 it would NOT have been",
        rows[4].by_pillar.get(PILLAR_FANTASY_FOOTBALL, 0) > 0
        and rows[1].total_cents > rows[4].total_cents,
        f"{rows[1].total_cents} vs {rows[4].total_cents}")
_assert("  · totals are the sum of that GM's pillar awards",
        all(r.total_cents == sum(r.by_pillar.values()) for r in grand.rows))
_assert("  · and rows are ordered by total descending",
        [r.total_cents for r in grand.rows]
        == sorted((r.total_cents for r in grand.rows), reverse=True),
        str([(r.team_id, r.total_cents) for r in grand.rows]))

print("\nWP14-F3/F4 · two funded pillars, and FUNDED survives distribution")
_assert("both pots have already been distributed",
        _bal(db, f"fantasystakes_championship:{LEAGUE}:{SEASON}") == 0
        and _bal(db, f"ff_championship:{LEAGUE}:{SEASON}") == 0)
_assert("  · yet both still count as FUNDED",
        set(funded_pillars(db, league_id=LEAGUE, season=SEASON))
        == {PILLAR_FANTASYSTAKES, PILLAR_FANTASY_FOOTBALL},
        str(funded_pillars(db, league_id=LEAGUE, season=SEASON)))
_assert("  · because funding is what the pot EVER held",
        pillar_funded_cents(db, pillar=PILLAR_FANTASYSTAKES,
                            league_id=LEAGUE, season=SEASON) == FS_POT,
        str(pillar_funded_cents(db, pillar=PILLAR_FANTASYSTAKES,
                                league_id=LEAGUE, season=SEASON)))
_assert("  · the unfunded Points pillar does not count",
        PILLAR_POINTS not in funded_pillars(db, league_id=LEAGUE,
                                            season=SEASON))
_assert("  · the §20 minimum is met", grand.meets_pillar_minimum,
        str(grand.funded_pillars))
_assert("  · and the minimum is a named constant, not a literal",
        MINIMUM_FUNDED_PILLARS == 2)

single = _build()
_fund_fs_pot(single, FS_POT)
_win_versus(single, winner=1, loser=2, stake=500, bet_id=1, matchup_id=1)
settle_fs(single, league_id=LEAGUE, season=SEASON, now=NOW)
single.commit()
one = view(single, league_id=LEAGUE, season=SEASON)
_assert("  · a league with ONE funded pillar does not meet the bar",
        not one.meets_pillar_minimum, str(one.funded_pillars))
_assert("  · though its rows are still readable",
        one.rows != (), str(one.as_dict()["rows"]))


# ── F5/F6/F7 · the three states ────────────────────────────────────────────

print("\nWP14-F5 · the regular season is a PLACEHOLDER with NO ROWS")
regular = _build(postseason_played=False)
_fund_fs_pot(regular, FS_POT)
placeholder = view(regular, league_id=LEAGUE, season=SEASON)
_assert("the state is PLACEHOLDER", placeholder.state == GRAND_PLACEHOLDER,
        placeholder.state)
_assert("  · with NO rows at all", placeholder.rows == (),
        str(placeholder.rows))
_assert("  · not rows of zeros — a table of GMs on 0 is a claim",
        placeholder.as_dict()["rows"] == [])
_assert("  · and no champion is named", placeholder.champion_team_ids == ())
_assert("  · while the funded pillar is still reported",
        placeholder.funded_pillars == (PILLAR_FANTASYSTAKES,),
        str(placeholder.funded_pillars))

print("\nWP14-F6 · postseason is LIVE from FINALIZED components only")
live = _build()
_fund_fs_pot(live, FS_POT)
_win_versus(live, winner=1, loser=2, stake=500, bet_id=1, matchup_id=1)
mint_fantasy_football_pot(live, league_id=LEAGUE, season=SEASON,
                          amount_cents=FF_POT, now=NOW)
live.commit()
partial = view(live, league_id=LEAGUE, season=SEASON)
_assert("two pillars are funded",
        len(partial.funded_pillars) == 2, str(partial.funded_pillars))
_assert("  · but NEITHER has finalized", partial.finalized_pillars == (),
        str(partial.finalized_pillars))
_assert("  · so the state is LIVE", partial.state == GRAND_LIVE,
        partial.state)
_assert("  · with no rows, because no Credit has been awarded",
        partial.rows == (), str(partial.rows))
_assert("  · and an unpaid pot contributes NOTHING — not a projection",
        all(PILLAR_FANTASYSTAKES not in r.by_pillar for r in partial.rows))

settle_ff(live, league_id=LEAGUE, state=_Bracket(), now=NOW)
live.commit()
half = view(live, league_id=LEAGUE, season=SEASON)
_assert("  · once ONE pillar pays, it appears and the other still does not",
        half.finalized_pillars == (PILLAR_FANTASY_FOOTBALL,),
        str(half.finalized_pillars))
_assert("  · the state is still LIVE", half.state == GRAND_LIVE, half.state)
_assert("  · totals count only the finalized pillar",
        all(set(r.by_pillar) == {PILLAR_FANTASY_FOOTBALL} for r in half.rows),
        str(half.as_dict()["rows"]))

print("\nWP14-F7 · FINAL once every funded pillar has paid")
settle_fs(live, league_id=LEAGUE, season=SEASON, now=NOW)
live.commit()
done = view(live, league_id=LEAGUE, season=SEASON)
_assert("every funded pillar has finalized",
        set(done.finalized_pillars) == set(done.funded_pillars),
        f"{done.finalized_pillars} vs {done.funded_pillars}")
_assert("  · so the state is FINAL", done.state == GRAND_FINAL, done.state)
_assert("  · and the states are exactly the three §20 names",
        GRAND_STATES == (GRAND_PLACEHOLDER, GRAND_LIVE, GRAND_FINAL),
        str(GRAND_STATES))


# ── F8 · the dead heat ─────────────────────────────────────────────────────

print("\nWP14-F8 · a tied TOTAL is a dead heat with no tiebreak")
tie = _build()
# ── THE TIE IS CONSTRUCTED, NOT HOPED FOR ────────────────────────────────────
#
# Both pots are 1000. The Fantasy Football bracket ranks 4 > 3 > 2, paying
# 600/300/100. The FantasyStakes Score is arranged to rank 2 > 3 > 4 > 1, paying
# 600/300/100/0. The two orderings are deliberately near-opposite, so:
#
#     team 2   100 (FF, third) + 600 (FS, first)  = 700
#     team 4   600 (FF, first) + 100 (FS, third)  = 700
#     team 3   300             + 300              = 600
#
# Two GMs on the TOP total, having won different pillars. The first version of
# this fixture paid both pillars in the same order and produced no tie at all —
# which the suite correctly reported rather than passing on a near miss.
mint_fantasy_football_pot(tie, league_id=LEAGUE, season=SEASON,
                          amount_cents=1_000, now=NOW)
tie.commit()
settle_ff(tie, league_id=LEAGUE, state=_Bracket(), now=NOW)
tie.commit()
_fund_fs_pot(tie, 1_000)
# Scores: 2 = +500, 3 = +100, 4 = -100, 1 = -500.
_win_versus(tie, winner=2, loser=1, stake=500, bet_id=1, matchup_id=1)
_win_versus(tie, winner=3, loser=4, stake=100, bet_id=11, matchup_id=2)
settle_fs(tie, league_id=LEAGUE, season=SEASON, now=NOW)
tie.commit()

tied = view(tie, league_id=LEAGUE, season=SEASON)
totals = {r.team_id: r.total_cents for r in tied.rows}
_assert("the top total is shared by two GMs",
        len([t for t, v in totals.items() if v == max(totals.values())]) == 2,
        str(totals))
_assert("  · both are named champions", len(tied.champion_team_ids) == 2,
        str(tied.champion_team_ids))
_assert("  · reported as co-champions", tied.co_champions is True)
_assert("  · and nothing was consulted to separate them",
        "fantasystakes_score" not in inspect.getsource(
            __import__("economy.grand_championship", fromlist=["x"])),
        "a tiebreak input is referenced")
# THE TIE IS REAL BECAUSE THE TOTALS ARE ASSEMBLED DIFFERENTLY, not because
# the two GMs drew on different pillars — both drew on both. One led the
# Fantasy Football pillar and took a minor share of FantasyStakes; the other
# did the reverse. That is a genuine dead heat between two different seasons,
# which is exactly the case §20 refuses to separate.
_champ_rows = {r.team_id: r for r in tied.rows
               if r.team_id in tied.champion_team_ids}
_assert("  · the two champions reached the same total by opposite routes",
        {r.by_pillar[PILLAR_FANTASY_FOOTBALL] for r in _champ_rows.values()}
        == {r.by_pillar[PILLAR_FANTASYSTAKES] for r in _champ_rows.values()}
        and len({r.by_pillar[PILLAR_FANTASY_FOOTBALL]
                 for r in _champ_rows.values()}) == 2,
        str({t: dict(r.by_pillar) for t, r in _champ_rows.items()}))
_assert("  · one led Fantasy Football, the other led FantasyStakes",
        max(_champ_rows.values(),
            key=lambda r: r.by_pillar[PILLAR_FANTASY_FOOTBALL]).team_id
        != max(_champ_rows.values(),
               key=lambda r: r.by_pillar[PILLAR_FANTASYSTAKES]).team_id,
        str({t: dict(r.by_pillar) for t, r in _champ_rows.items()}))


# ── F9/F10 · no posting, no 3/2/1, no legacy ──────────────────────────────

print("\nWP14-F9 · nothing here posts — every Credit was already awarded")
import economy.grand_championship as gc  # noqa: E402

gc_src = inspect.getsource(gc)
_assert("no ledger posting is made",
        "ledger_post" not in gc_src and "post as" not in gc_src)
_assert("  · nothing is added to the session",
        "db.add(" not in gc_src and "db.commit()" not in gc_src)
_assert("  · no economy event is recorded", "record_event" not in gc_src)

before = {t: _bal(db, f"wallet:{t}") for t in TEAMS}
view(db, league_id=LEAGUE, season=SEASON)
view(db, league_id=LEAGUE, season=SEASON)
_assert("  · and reading it twice moves no Wallet",
        {t: _bal(db, f"wallet:{t}") for t in TEAMS} == before,
        str({t: _bal(db, f"wallet:{t}") for t in TEAMS}))

print("\nWP14-F10 · the retired 3/2/1 model is not consulted")
_assert("no POINTS_BY_PLACE is imported or referenced",
        "POINTS_BY_PLACE" not in gc_src)
# WALKED AS AN AST. The module's era refusal NAMES `reports.grand_champion` to
# tell a caller where the legacy recognition lives, so a text search finds the
# sentence rather than an import — which is how this first failed while the
# code was correct.
import ast  # noqa: E402

_gc_tree = ast.parse(gc_src)
_gc_imports = {getattr(n, "module", "") or ""
               for n in ast.walk(_gc_tree) if isinstance(n, ast.ImportFrom)}
_gc_imports |= {a.name for n in ast.walk(_gc_tree)
                if isinstance(n, ast.Import) for a in n.names}
_assert("  · and `reports.grand_champion` is not imported",
        not any(m == "reports.grand_champion" for m in _gc_imports),
        str(sorted(_gc_imports)))
from reports.grand_champion import POINTS_BY_PLACE  # noqa: E402

_assert("  · the retired module still exists for legacy seasons",
        POINTS_BY_PLACE == {1: 3, 2: 2, 3: 1}, str(POINTS_BY_PLACE))

old = _build(final_por=False)
try:
    view(old, league_id=LEAGUE, season=SEASON)
    _assert("  · and a LEGACY season is refused", False, "accepted")
except GrandChampionshipError as exc:
    _assert("  · and a LEGACY season is refused",
            exc.reason == "GRAND_WRONG_ERA", exc.reason)


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-14 Grand Championship as a virtual-credit total: all assertions passed")
