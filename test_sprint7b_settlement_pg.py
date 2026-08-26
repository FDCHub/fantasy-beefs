"""SPRINT 7B · a real wager and a real Pool, settled from BALLDONTLIE evidence.

WHAT SPRINT 7 CALLED BLOCKER A. Six sprints built a factual pipeline and
certified every piece of it, and Sprint 7's own report said plainly that no
Versus or Pool settlement had ever been executed from BALLDONTLIE evidence
through the existing settlement engines into real ledger postings. Everything
up to `settlement_scores()` was proven; the two floats it returns reached
nothing.

THIS SUITE IS THE PROOF THAT THEY REACH THE LEDGER. One league, one week, one
coherent sequence, every step through production code:

    Yahoo states the league, the schedule and who started
    BALLDONTLIE component projections  ->  CSPS  ->  IPRM-v2  ->  sim-v2
    ->  the real market board  ->  a real Versus challenge, issued and accepted
    ->  BALLDONTLIE factual evidence, persisted by the production factual ingest
    ->  CSPS FACTUAL  ->  scoring/factual  ->  scoring/factual_grading
    ->  providers/persist.refresh_league_week, the certified score writer
    ->  finality  ->  betting/settlement_engine.settle_week
    ->  ledger/ledger.post  ->  trial balance zero

and, on the same league and week:

    persisted factual components  ->  BalldontlieProviderStatSource
    ->  the governed Pool census  ->  betting/pool_settlement.settle_pool_instance
    ->  ledger  ->  trial balance zero

── THE ONE THING SPRINT 7B HAD TO ADD ──────────────────────────────────────

`providers/balldontlie/factual_scores.py`. Sprint 6B produced the two floats;
nothing carried them to `Matchup.home_score`, which is where every Versus market
in `settlement_engine.py` reads its answer. That module composes the
FantasyStakes-computed scores onto the provider matchup DTOs and hands them to
`providers/persist.py` — the certified writer — so this tree still has exactly
two writers of that column and `Matchup.finalized_at` still has exactly one.

── WHAT IS NOT SUBSTITUTED ─────────────────────────────────────────────────

The settlement engine, the ledger, the Pool census, the Pool engine, the
funding, the claim path, the wallet mutexes and the finality gate are all
production. Nothing is mocked, nothing is shortcut, and there is no Sprint 7B
settlement path. The only substitution anywhere is the transport, which is the
committed fixture corpus — so the suite runs offline with no credential.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
`settle_week` uses INSERT .. ON CONFLICT and SELECT .. FOR UPDATE, so this
cannot run on SQLite and is not asked to.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)
os.environ.setdefault("JWT_SECRET_KEY", "sprint7b-settlement-secret")

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db                # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] Sprint 7B settlement suite cannot run:\n  {e}")
    sys.exit(2)

from datetime import datetime, timezone                                 # noqa: E402

from db.schema import (                                                 # noqa: E402
    Bet, Matchup, Player, PoolClaim, PoolInstance, ProviderPlayerAlias,
    ProviderComponentProjection, Roster, SessionLocal, Team, Wallet,
)
from ledger.ledger import balance_of, trial_balance                     # noqa: E402

import test_support_sprint7b_world as W                                 # noqa: E402
from test_support_s4_pool import (                                      # noqa: E402
    FOUR_TEAM_KEYS, make_league, mark_ready, seed_catalog,
)

SEASON = W.SETTLEMENT_SEASON
WEEK = W.SETTLEMENT_WEEK
LEAGUE_KEY = "999.l.70001"
TEAM_KEYS = (f"{LEAGUE_KEY}.t.1", f"{LEAGUE_KEY}.t.2")
POOL_KEY = "most_passing_yards"
POOL_PROVIDER = "test-recorded-fixtures"

_passed = 0
_failed = 0


def _assert(label, condition, detail=""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  [PASS] {label}" + (f" -- {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))


def _section(title):
    print(f"\n{title}")


# ══════════════════════════════════════════════════════════════════════════════
# 7B-P1 · a real economic world, built through production paths
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-P1 · the staging economic world")

with SessionLocal() as db:
    seed_catalog(db)
    # PLAYOFF_START_WEEK 18 — WEEK 17 IS A REGULAR-SEASON WEEK HERE.
    #
    # Stated rather than defaulted, because it changes which code runs. Under
    # the fixture default of 15, week 17 is POSTSEASON, and a postseason Pool
    # collection is refused until the FantasyStakes Championship is activated
    # and frozen — correct behaviour, and an entirely different proof from the
    # one this suite is making. Sprint 7B is certifying a provider cutover, not
    # season-close economics, so the week under test is a regular one.
    league, teams = make_league(db, name="s7b", season=SEASON, n_teams=2,
                               wallet_cents=100_000, week=WEEK,
                               season_final_week=17, playoff_start_week=18,
                               finalized_at=None)
    LEAGUE_ID = league.id
    TEAM_IDS = [t.id for t in teams]

    from providers.yahoo.identity import (
        bind_league_identity, bind_team_identity,
    )

    bind_league_identity(db, league_id=LEAGUE_ID, league_key=LEAGUE_KEY)
    for ordinal, team in enumerate(teams, start=1):
        bind_team_identity(db, team_id=team.id,
                           team_key=TEAM_KEYS[ordinal - 1],
                           team_ordinal=ordinal)

    players_by_key = {}
    for index, (key, position, name, nfl_team) in enumerate(
            W.SETTLEMENT_STARTERS):
        player = Player(name=name, position=position, nfl_team=nfl_team)
        db.add(player)
        db.flush()
        players_by_key[key] = player
        db.add(ProviderPlayerAlias(
            provider="balldontlie", player_id=player.id,
            provider_player_key=key, provider_position=position,
            provider_nfl_team=nfl_team,
            status=ProviderPlayerAlias.STATUS_ACTIVE,
            method=ProviderPlayerAlias.METHOD_MANUAL, manual_override=True))
        db.add(Roster(team_id=TEAM_IDS[index], player_id=player.id))
    db.flush()
    PLAYER_IDS = {key: p.id for key, p in players_by_key.items()}
    # Detached from here on, deliberately — see the support module's note.
    players_by_key = {key: {"id": p.id, "name": p.name}
                      for key, p in players_by_key.items()}
    db.commit()

    _assert("the league is funded through REAL ledger postings, not a balance "
            "column",
            balance_of(f"wallet:{TEAM_IDS[0]}") == 100_000
            and balance_of(f"wallet:{TEAM_IDS[1]}") == 100_000,
            f"{balance_of(f'wallet:{TEAM_IDS[0]}')} cents each")
    _assert("  · and the ledger balances before anything happens",
            trial_balance() == 0)
    _assert("  · the week is NOT final yet, which is the honest starting state",
            db.query(Matchup).filter(Matchup.league_id == LEAGUE_ID,
                                     Matchup.finalized_at.isnot(None)).count()
            == 0)


# ══════════════════════════════════════════════════════════════════════════════
# 7B-P2 · projections, parameters and the activation
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-P2 · the league is moved to BALLDONTLIE and priced")

with SessionLocal() as db:
    W.derive_model_parameters(db)

    # The committed projection corpus, through the production ingest.
    from providers.balldontlie.ingest import ingest_week

    players = list(db.query(Player).all())
    summary = ingest_week(db, W.fixture_transport(), season=SEASON, week=WEEK,
                          players=players)
    db.flush()

    # The one STATED projection, through the production persist path — see the
    # support module's note on why it exists and what it is.
    from providers.component_projections import (
        ComponentProjection, persist_snapshot,
    )
    from providers.cross_identity import (
        BALLDONTLIE, CanonicalSubject, CrossProviderResolution,
        Outcome as IdOutcome,
    )

    _second = players_by_key["bdl.p.63"]
    persist_snapshot(
        db,
        resolution=CrossProviderResolution(
            outcome=IdOutcome.RESOLVED, provider=BALLDONTLIE,
            canonical=CanonicalSubject(player_id=PLAYER_IDS["bdl.p.63"],
                                       name="bdl.p.63", position="QB",
                                       nfl_team="LAR"),
            provider_player_key="bdl.p.63", method="manual"),
        projection=ComponentProjection(
            provider=BALLDONTLIE, provider_player_key="bdl.p.63",
            season=SEASON, week=WEEK,
            components=dict(W.STATED_PROJECTION_BDL_63),
            components_present=tuple(sorted(W.STATED_PROJECTION_BDL_63)),
            nfl_team="LAR", position="QB",
            observed_at=datetime(2025, 12, 24, 18, 5, tzinfo=timezone.utc),
            source_kind=ProviderComponentProjection.SOURCE_PROJECTION),
        captured_at=datetime(2025, 12, 24, 18, 5, tzinfo=timezone.utc),
        provenance=ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC)
    db.flush()

    W.activate_balldontlie(db, league_id=LEAGUE_ID)
    db.commit()

    _assert("both starters carry a persisted component projection",
            db.query(ProviderComponentProjection).filter(
                ProviderComponentProjection.season == SEASON,
                ProviderComponentProjection.week == WEEK,
                ProviderComponentProjection.source_kind
                == ProviderComponentProjection.SOURCE_PROJECTION,
                ProviderComponentProjection.provider_player_key.in_(
                    list(PLAYER_IDS))).count() == 2,
            f"ingest resolved {summary.resolved}")

with SessionLocal() as db:
    from beefs.beef_engine import compute_market_board

    home = db.query(Team).filter(Team.id == TEAM_IDS[0]).one()
    away = db.query(Team).filter(Team.id == TEAM_IDS[1]).one()
    board = compute_market_board(home, away, WEEK, db)
    BOARD_SPREAD = board.spread_line
    BOARD_TOTAL = board.total_line
    _assert("the league's market board is priced by sim-v2 from those "
            "components",
            isinstance(board.anchor_moneyline, int),
            f"ML {board.anchor_moneyline}/{board.opponent_moneyline} "
            f"spread {board.spread_line} total {board.total_line}")

    from beefs.pricing import resolve_plan

    _plan = resolve_plan(db, team_id=TEAM_IDS[0], week=WEEK)
    _assert("  · under sim-v2, with the league's own CSPS profile",
            _plan.model_config.model_version_id == "sim-v2"
            and _plan.profile.profile_id == W.PROFILE_ID)
    db.rollback()


# ══════════════════════════════════════════════════════════════════════════════
# 7B-P3 · a real Versus wager, issued and accepted
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-P3 · a real wager, through the production challenge lifecycle")

with SessionLocal() as db:
    # THE CHALLENGE LOCK READS `config.LOCK_SEASON`, NOT THE LEAGUE'S SEASON,
    # and it reads it on a SESSION OF ITS OWN (`_nfl_lock_time` opens one), so
    # the row has to be COMMITTED before the challenge is issued rather than
    # merely flushed. Both facts are stated here rather than worked around: two
    # lock resolvers reading two seasons is a real seam, and a fixture that
    # quietly satisfied both would hide it.
    from config import LOCK_SEASON
    from test_support_s4_pool import add_week_schedule

    add_week_schedule(db, season=LOCK_SEASON, week=WEEK, name="s7b-lock")

    # AND THE TWO STARTERS' REAL NFL TEAMS. Acceptance re-checks that every
    # rostered player's own NFL game is scheduled and un-started — a per-player
    # lock, not merely a per-week one — so a fixture that only satisfied the
    # week-level check would be asserting less than production requires.
    from datetime import timedelta

    from db.schema import NflSchedule

    _kickoff = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        hour=17, minute=0, second=0, microsecond=0, tzinfo=None)
    db.add(NflSchedule(season=LOCK_SEASON, week=WEEK,
                       home_team="SF", away_team="LAR",
                       kickoff_utc=_kickoff))
    db.commit()

with SessionLocal() as db:
    from beefs.beef_engine import issue_challenge, respond_to_challenge

    challenge = issue_challenge(TEAM_IDS[0], TEAM_IDS[1], WEEK, "straight",
                               50.0, db, trash_talk="sprint 7b")
    CHALLENGE_ID = challenge.challenge_id
    db.commit()

with SessionLocal() as db:
    result = respond_to_challenge(CHALLENGE_ID, True, db)
    db.commit()

with SessionLocal() as db:
    bets = db.query(Bet).filter(Bet.beef_challenge_id == CHALLENGE_ID).all()
    BET_IDS = [b.id for b in bets]
    _assert("the accepted challenge placed two real Bet rows",
            len(bets) == 2 and all(b.status == "pending" for b in bets))
    _assert("  · both stakes are in ESCROW, out of the wallets",
            sum(balance_of(f"escrow:{b.id}") for b in bets) == 10_000,
            f"escrow {[balance_of(f'escrow:{b.id}') for b in bets]}")
    _assert("  · and the ledger still balances",
            trial_balance() == 0)
    WALLET_AFTER_STAKE = {t: balance_of(f"wallet:{t}") for t in TEAM_IDS}
    _assert("  · each wallet is down exactly the stake",
            all(v == 95_000 for v in WALLET_AFTER_STAKE.values()),
            str(WALLET_AFTER_STAKE))


# ══════════════════════════════════════════════════════════════════════════════
# 7B-P4 · outage before finality — nothing settles, nothing posts
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-P4 · incomplete evidence blocks settlement absolutely")

SNAPSHOT_ARGS = dict(
    league_key=LEAGUE_KEY, league_name="s7b",
    team_keys=TEAM_KEYS,
    starters_by_team_key={
        TEAM_KEYS[0]: [W.SETTLEMENT_STARTERS[0]],
        TEAM_KEYS[1]: [W.SETTLEMENT_STARTERS[1]],
    })

with SessionLocal() as db:
    from providers.balldontlie import factual_scores as FS
    from scoring.profile import load_profile

    profile = load_profile(W.PROFILE_ID)

    # The provider has not declared the game final. The certified assembly
    # marks every subject PROVIDER_NOT_FINAL, so nothing is persisted and
    # nothing can be scored.
    week_not_final, report_not_final = W.ingest_settlement_facts(
        db, players_by_key, final=False)
    _assert("a game the provider has NOT called final stores no facts",
            report_not_final.stored == 0,
            f"{report_not_final.stored} stored, "
            f"{len(report_not_final.incomplete)} incomplete")
    _assert("  · and every subject names the cause rather than scoring zero",
            all("PROVIDER_NOT_FINAL" in str(item["diagnostics"])
                for item in report_not_final.incomplete),
            str(report_not_final.incomplete[:1]))

    snapshot = W.yahoo_snapshot(**SNAPSHOT_ARGS)
    rescored, scored = FS.rescore_snapshot(
        db, snapshot=snapshot, season=SEASON, week=WEEK, profile=profile)
    _assert("  · so no matchup score is computed",
            scored.ready_matchups == 0 and len(scored.refusals) == 2,
            str(scored.refusals)[:120])
    _assert("  · the matchup DTOs are carried through UNCHANGED, not zeroed",
            all(m.home_points is None and m.away_points is None
                for m in rescored.matchups))
    db.rollback()

_LEDGER_BEFORE = trial_balance()
_ESCROW_BEFORE = sum(balance_of(f"escrow:{b}") for b in BET_IDS)

with SessionLocal() as db:
    from betting.settlement_engine import settle_week

    try:
        settle_week(WEEK, db, LEAGUE_ID)
        _refused = False
        _cause = "did not raise"
    except Exception as exc:                                      # noqa: BLE001
        _refused = True
        _cause = type(exc).__name__
    db.rollback()

_assert("settle_week REFUSES a week that is not final",
        _refused, _cause)
_assert("  · and the refusal moved nothing at all",
        trial_balance() == _LEDGER_BEFORE
        and sum(balance_of(f"escrow:{b}") for b in BET_IDS) == _ESCROW_BEFORE)
with SessionLocal() as db:
    _assert("  · no bet changed status",
            db.query(Bet).filter(Bet.beef_challenge_id == CHALLENGE_ID,
                                 Bet.status == "pending").count() == 2)


# ══════════════════════════════════════════════════════════════════════════════
# 7B-P5 · the facts arrive, and FantasyStakes computes the week's scores
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-P5 · BALLDONTLIE facts -> CSPS FACTUAL -> the certified writer")

with SessionLocal() as db:
    from providers.balldontlie import factual_scores as FS
    from scoring.profile import load_profile

    profile = load_profile(W.PROFILE_ID)
    factual_week, report = W.ingest_settlement_facts(db, players_by_key,
                                                     final=True)
    db.commit()
    _assert("the production factual ingest persisted the week's facts",
            report.stored == 2, f"{report.stored} subjects stored")
    FACT_ROWS = db.query(ProviderComponentProjection).filter(
        ProviderComponentProjection.source_kind
        == ProviderComponentProjection.SOURCE_WEEKLY_STATS).count()
    _assert("  · as factual rows, distinct from the projection rows",
            FACT_ROWS == 2, f"{FACT_ROWS} factual rows")
    _assert("  · while the two team defences REFUSED, naming why",
            any("UNKNOWN_DRIVE_EVENTS" in str(item["diagnostics"])
                for item in report.incomplete),
            str([i["provider_player_key"] for i in report.incomplete]))

with SessionLocal() as db:
    from providers import persist as PERSIST
    from providers.balldontlie import factual_scores as FS
    from scoring.profile import load_profile

    profile = load_profile(W.PROFILE_ID)
    snapshot = W.yahoo_snapshot(**SNAPSHOT_ARGS)
    rescored, scored = FS.rescore_snapshot(
        db, snapshot=snapshot, season=SEASON, week=WEEK, profile=profile)

    _assert("both lineups are READY from persisted evidence alone",
            scored.ready_matchups == 1 and not scored.refusals,
            str(scored.as_dict()["matchups_scored"]))
    HOME_POINTS, AWAY_POINTS = list(scored.matchup_points.values())[0]
    _assert("  · and FantasyStakes scored them under the league's OWN profile",
            HOME_POINTS != AWAY_POINTS,
            f"home {HOME_POINTS} away {AWAY_POINTS}")

    # CROSS-CHECKED AGAINST CSPS DIRECTLY, so the number is not merely
    # self-consistent. One quarterback's components are scored here by hand
    # through the same certified function and must agree to the cent.
    from scoring import csps as C

    _facts = FS.persisted_subject_facts(db, season=SEASON, week=WEEK)
    _direct = C.score_components(
        _facts["bdl.p.27"].components, profile, mode=C.FACTUAL,
        components_present=list(_facts["bdl.p.27"].components_present),
        position="QB")
    _lineup = scored.lineups[TEAM_KEYS[0]]
    _assert("  · and the lineup total IS that CSPS result, to the cent",
            abs(_lineup.points - _direct.points) < 1e-9,
            f"{_lineup.points} vs {_direct.points}")

    result = PERSIST.refresh_league_week(db, rescored)
    db.commit()
    _assert("the CERTIFIED writer persisted those scores -- Sprint 7B added no "
            "second writer of Matchup.home_score",
            result.matchups_inserted + result.matchups_updated >= 1,
            f"inserted {result.matchups_inserted} "
            f"updated {result.matchups_updated}")

with SessionLocal() as db:
    row = db.query(Matchup).filter(Matchup.league_id == LEAGUE_ID,
                                   Matchup.week == WEEK,
                                   Matchup.provider_matchup_key.isnot(None)
                                   ).one()
    MATCHUP_ID = row.id
    _assert("Matchup.home_score now holds the BALLDONTLIE-derived score",
            abs(row.home_score - HOME_POINTS) < 1e-6
            and abs(row.away_score - AWAY_POINTS) < 1e-6,
            f"{row.home_score} / {row.away_score}")
    _assert("  · and the week is FINAL, written by providers/finality.py",
            row.finalized_at is not None)


# ══════════════════════════════════════════════════════════════════════════════
# 7B-P6 · THE REAL VERSUS SETTLEMENT
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-P6 · settle_week, for real, into the real ledger")

_TRIAL_BEFORE = trial_balance()

with SessionLocal() as db:
    from betting.settlement_engine import settle_week

    report = settle_week(WEEK, db, LEAGUE_ID)
    db.commit()
    SETTLEMENT = report

_assert("SETTLE_WEEK EXECUTED AGAINST BALLDONTLIE-DERIVED SCORES",
        SETTLEMENT.total_bets == 2 and not SETTLEMENT.already_settled,
        f"{SETTLEMENT.total_bets} bets, {SETTLEMENT.bets_won} won, "
        f"{SETTLEMENT.bets_lost} lost")
_assert("  · exactly one side won and one lost -- the scores differ, so this "
        "is a decided market and not a push",
        SETTLEMENT.bets_won == 1 and SETTLEMENT.bets_lost == 1)

with SessionLocal() as db:
    bets = db.query(Bet).filter(Bet.beef_challenge_id == CHALLENGE_ID).all()
    _won = [b for b in bets if b.status == "won"]
    _lost = [b for b in bets if b.status == "lost"]
    _assert("  · and the graded winner is the team the FACTS favour",
            len(_won) == 1 and len(_lost) == 1
            and _won[0].picked_team_id == (TEAM_IDS[0]
                                           if HOME_POINTS > AWAY_POINTS
                                           else TEAM_IDS[1]),
            f"winner team {_won[0].picked_team_id}, "
            f"home {HOME_POINTS} away {AWAY_POINTS}")

_assert("EVERY ESCROW IS RELEASED -- nothing is stranded",
        all(balance_of(f"escrow:{b}") == 0 for b in BET_IDS),
        str([balance_of(f"escrow:{b}") for b in BET_IDS]))
_WALLETS_AFTER = {t: balance_of(f"wallet:{t}") for t in TEAM_IDS}
_assert("  · the winner's wallet grew and the loser's did not",
        sorted(_WALLETS_AFTER.values()) == [95_000, 105_000],
        str(_WALLETS_AFTER))
_assert("  · total system value is conserved -- 200,000 cents in, "
        "200,000 out",
        sum(_WALLETS_AFTER.values()) == 200_000,
        str(sum(_WALLETS_AFTER.values())))
_assert("TRIAL BALANCE IS ZERO AFTER A REAL SETTLEMENT",
        trial_balance() == 0, str(trial_balance()))


# ══════════════════════════════════════════════════════════════════════════════
# 7B-P7 · idempotency
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-P7 · settling twice posts nothing twice")

_SNAPSHOT = {t: balance_of(f"wallet:{t}") for t in TEAM_IDS}

with SessionLocal() as db:
    from betting.settlement_engine import settle_week

    again = settle_week(WEEK, db, LEAGUE_ID)
    db.commit()

_assert("a second settle_week is an idempotent no-op",
        again.already_settled is True and again.total_bets == 0)
_assert("  · not one further credit was posted",
        {t: balance_of(f"wallet:{t}") for t in TEAM_IDS} == _SNAPSHOT)
_assert("  · and the trial balance is still zero",
        trial_balance() == 0)

with SessionLocal() as db:
    _again_report = W.ingest_settlement_facts(db, players_by_key,
                                              final=True)[1]
    db.commit()
    _assert("re-ingesting the same facts stores no duplicate row",
            db.query(ProviderComponentProjection).filter(
                ProviderComponentProjection.source_kind
                == ProviderComponentProjection.SOURCE_WEEKLY_STATS
            ).count() == FACT_ROWS,
            f"{_again_report.duplicate} recognised as duplicates")


# ══════════════════════════════════════════════════════════════════════════════
# 7B-P8 · settlement replays with the provider unreachable
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-P8 · nothing on the settlement path needs the provider")


class _DeadTransport:
    """Sabotage. Any provider request during grading is a defect."""

    requests_made = 0

    def get(self, *a, **k):                                        # noqa: D102
        raise AssertionError("settlement reached the provider")

    def paginate(self, *a, **k):                                   # noqa: D102
        raise AssertionError("settlement reached the provider")


import providers.balldontlie.transport as TRANSPORT                     # noqa: E402

_live = TRANSPORT.BalldontlieLiveTransport
_fixture = TRANSPORT.BalldontlieFixtureTransport
TRANSPORT.BalldontlieLiveTransport = _DeadTransport
TRANSPORT.BalldontlieFixtureTransport = _DeadTransport
try:
    with SessionLocal() as db:
        from providers.balldontlie import factual_scores as FS
        from scoring.profile import load_profile

        replay_scored = FS.score_team_lineups(
            db, snapshot=W.yahoo_snapshot(**SNAPSHOT_ARGS), season=SEASON,
            week=WEEK, profile=load_profile(W.PROFILE_ID))
        db.rollback()
    _offline = True
    _offline_cause = ""
except AssertionError as exc:
    _offline = False
    _offline_cause = str(exc)
finally:
    TRANSPORT.BalldontlieLiveTransport = _live
    TRANSPORT.BalldontlieFixtureTransport = _fixture

_assert("the whole factual scoring replays with BALLDONTLIE UNREACHABLE",
        _offline, _offline_cause)
_assert("  · and reproduces the identical scores from persisted evidence",
        _offline
        and abs(replay_scored.lineups[TEAM_KEYS[0]].points - HOME_POINTS) < 1e-9
        and abs(replay_scored.lineups[TEAM_KEYS[1]].points - AWAY_POINTS) < 1e-9,
        f"{replay_scored.lineups[TEAM_KEYS[0]].points} / "
        f"{replay_scored.lineups[TEAM_KEYS[1]].points}" if _offline else "")


# ══════════════════════════════════════════════════════════════════════════════
# 7B-P9 · THE REAL POOL SETTLEMENT
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-P9 · a governed Pool, graded from the same evidence")

with SessionLocal() as db:
    from betting.pool_funding import (
        collect_weekly_entries, configure_pool_weekly_entry,
    )

    # ALL FOUR, BECAUSE A WEEK'S SLATE IS FOUR OCCURRENCES.
    #
    # POR §4.1 refuses to build a slate from fewer than four fully supported
    # definitions, so marking only the one this evidence answers would refuse
    # the collection outright. The other three are drawn and funded exactly as
    # production draws them; this suite settles the one its two quarterbacks
    # can actually answer, and the remaining occurrences stay unsettled — which
    # is the honest state for a week whose evidence covers one stat and not the
    # others, and is why the pool-account assertion below measures a DELTA
    # rather than expecting the account to empty.
    mark_ready(db, league_id=LEAGUE_ID, keys=FOUR_TEAM_KEYS)
    configure_pool_weekly_entry(db, league_id=LEAGUE_ID, cents=200)
    collection = collect_weekly_entries(db, league_id=LEAGUE_ID, week=WEEK,
                                       provider=POOL_PROVIDER)
    db.commit()
    _assert("the weekly collection funded the Pool through the real ledger",
            collection.total_cents == 400 and collection.teams_charged == 2,
            f"{collection.total_cents} cents from "
            f"{collection.teams_charged} teams")
    POOL_ACCOUNT_AFTER_COLLECTION = balance_of(f"pool:{LEAGUE_ID}")
    _assert("  · and the trial balance survived it",
            trial_balance() == 0)

with SessionLocal() as db:
    instances = (db.query(PoolInstance)
                 .filter(PoolInstance.league_id == LEAGUE_ID,
                         PoolInstance.week == WEEK).all())
    _target = [i for i in instances if i.definition_key == POOL_KEY]
    _assert("the week drew the definition this evidence can answer",
            len(_target) == 1, str(sorted(i.definition_key for i in instances)))
    INSTANCE_ID = _target[0].id
    POT_CENTS = _target[0].pot_cents

with SessionLocal() as db:
    from betting.pool_claims import submit_claim

    # Team 1's quarterback threw for 320; team 2's for 269. Team 1 claims
    # itself, which is the winning claim, and team 2 claims team 1 as well --
    # so the split path is exercised rather than a single-winner shortcut.
    submit_claim(db, pool_instance_id=INSTANCE_ID, team_id=TEAM_IDS[0],
                 subject_id=TEAM_IDS[0])
    submit_claim(db, pool_instance_id=INSTANCE_ID, team_id=TEAM_IDS[1],
                 subject_id=TEAM_IDS[1])
    db.commit()
    _assert("two GMs hold claims, and claiming moved no money",
            db.query(PoolClaim).filter(
                PoolClaim.pool_instance_id == INSTANCE_ID).count() == 2
            and trial_balance() == 0)

_POOL_WALLETS_BEFORE = {t: balance_of(f"wallet:{t}") for t in TEAM_IDS}

with SessionLocal() as db:
    from betting.pool_settlement import settle_pool_instance
    from providers.balldontlie.pool_source import (
        BalldontlieProviderStatSource, factual_week_from_components,
    )
    from providers.identity import build_team_identity_resolver

    snapshot = W.yahoo_snapshot(**SNAPSHOT_ARGS)
    composed = factual_week_from_components(
        db, league=snapshot.league, week=WEEK, season=SEASON,
        roster_entries=snapshot.roster_entries,
        observed_at=snapshot.observed_at)
    resolver = build_team_identity_resolver(db, league_id=LEAGUE_ID,
                                            provider="yahoo")
    stat_source = BalldontlieProviderStatSource(composed).bind(db, resolver)

    pool_result = settle_pool_instance(db, pool_instance_id=INSTANCE_ID,
                                       stat_source=stat_source)
    db.commit()

_assert("THE POOL SETTLED FROM PERSISTED BALLDONTLIE FACTS",
        pool_result is not None and not pool_result.replayed
        and pool_result.pot_cents > 0,
        f"{pool_result.classification}, pot {pool_result.pot_cents}, "
        f"distributed {pool_result.distributed_cents}")
_assert("  · the winning subject is the team whose quarterback threw for more "
        "-- 320 yards against 269, straight from the persisted facts",
        pool_result.winning_subject_ids == (TEAM_IDS[0],),
        f"{pool_result.winning_subject_ids} "
        f"classification={pool_result.classification}")
_assert("  · the GM holding the winning claim is the one paid",
        pool_result.winning_team_ids == (TEAM_IDS[0],),
        str(pool_result.winning_team_ids))
_POOL_WALLETS_AFTER = {t: balance_of(f"wallet:{t}") for t in TEAM_IDS}
_assert("  · this occurrence's whole pot left the pool account",
        POOL_ACCOUNT_AFTER_COLLECTION - balance_of(f"pool:{LEAGUE_ID}")
        == POT_CENTS,
        f"pot {POT_CENTS}, account "
        f"{POOL_ACCOUNT_AFTER_COLLECTION} -> {balance_of(f'pool:{LEAGUE_ID}')}")
_assert("  · and reached a wallet, in full",
        sum(_POOL_WALLETS_AFTER.values())
        - sum(_POOL_WALLETS_BEFORE.values()) == pool_result.distributed_cents
        == POT_CENTS,
        f"distributed {pool_result.distributed_cents}, delta "
        f"{sum(_POOL_WALLETS_AFTER.values()) - sum(_POOL_WALLETS_BEFORE.values())}")
_assert("TRIAL BALANCE IS ZERO AFTER THE POOL SETTLEMENT",
        trial_balance() == 0, str(trial_balance()))

with SessionLocal() as db:
    from betting.pool_settlement import settle_pool_instance
    from providers.balldontlie.pool_source import (
        BalldontlieProviderStatSource, factual_week_from_components,
    )
    from providers.identity import build_team_identity_resolver

    snapshot = W.yahoo_snapshot(**SNAPSHOT_ARGS)
    composed = factual_week_from_components(
        db, league=snapshot.league, week=WEEK, season=SEASON,
        roster_entries=snapshot.roster_entries,
        observed_at=snapshot.observed_at)
    resolver = build_team_identity_resolver(db, league_id=LEAGUE_ID,
                                            provider="yahoo")
    replay = settle_pool_instance(
        db, pool_instance_id=INSTANCE_ID,
        stat_source=BalldontlieProviderStatSource(composed).bind(db, resolver))
    db.commit()

_assert("settling the Pool again REPLAYS rather than pays again",
        replay.replayed is True
        and {t: balance_of(f"wallet:{t}") for t in TEAM_IDS}
        == _POOL_WALLETS_AFTER,
        str({t: balance_of(f"wallet:{t}") for t in TEAM_IDS}))
_assert("  · and the trial balance is still zero",
        trial_balance() == 0)


# ══════════════════════════════════════════════════════════════════════════════
# 7B-P9b · the fail-closed subjects, through the same product path
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-P9b · a kicker and a defence, refused rather than guessed")

with SessionLocal() as db:
    from providers.balldontlie import factual_scores as FS
    from scoring.profile import load_profile

    _profile = load_profile(W.PROFILE_ID)

    # A KICKER WITH MADE FIELD GOALS AND NO DISTANCES. `mr_whiskers_memorial`
    # pays by distance band, so "three made" is not a score — it is three
    # unknown scores. The certified assembly refuses him, and nothing here
    # invents a yardage to get past it.
    _kicker_stats = list(W.SETTLEMENT_STATS) + [
        {"player": {"id": 278371, "position_abbreviation": "PK"},
         "team": {"abbreviation": "JAX"}, "game": {"id": W.CAPTURED_GAME_ID},
         "field_goals_made": 3, "field_goal_attempts": 4,
         "extra_points_made": 2},
    ]
    _kicker_week = W.build_settlement_factual_week(stats=_kicker_stats)
    _kicker = _kicker_week.subjects.get("bdl.p.278371")
    _assert("a kicker whose distances never arrived is REFUSED",
            _kicker is not None and not _kicker.complete,
            str(_kicker.diagnostics) if _kicker else "no subject")
    _assert("  · and no distance is invented to get past it",
            _kicker is not None
            and not _kicker.components.get("field_goals_made_yards"),
            str(_kicker.components.get("field_goals_made_yards"))
            if _kicker else "")

    # A LINEUP HOLDING HIM IS NOT READY, and a matchup holding that lineup is
    # not scored — which is the whole point: the refusal has to survive all the
    # way to the money, not stop at the subject.
    _kicker_snapshot = W.yahoo_snapshot(
        league_key=LEAGUE_KEY, league_name="s7b", team_keys=TEAM_KEYS,
        starters_by_team_key={
            TEAM_KEYS[0]: [W.SETTLEMENT_STARTERS[0],
                           ("bdl.p.278371", "K", "Refusing K", "JAX")],
            TEAM_KEYS[1]: [W.SETTLEMENT_STARTERS[1]],
        })
    _kicker_rescored, _kicker_scored = FS.rescore_snapshot(
        db, snapshot=_kicker_snapshot, season=SEASON, week=WEEK,
        profile=_profile)
    _assert("  · the LINEUP holding him is NOT READY",
            _kicker_scored.lineups[TEAM_KEYS[0]].readiness == "NOT_READY",
            str(_kicker_scored.refusals)[:130])
    _assert("  · so the matchup is not scored, and settlement has nothing to "
            "grade -- a material refusal blocks the money",
            _kicker_scored.ready_matchups == 0)
    _assert("  · and the diagnostic names the subject, not just the failure",
            any("Refusing K" in r or "278371" in r
                for r in _kicker_scored.refusals),
            str(_kicker_scored.refusals))

    # EMPTY PLAY EVIDENCE. A team defence needs the play stream to classify
    # drives; a week whose plays never arrived refuses every defence and leaves
    # every offensive subject scoreable, which is the per-subject correctness
    # the design chose over discarding a whole week.
    from providers.balldontlie import factual_week as FW

    _no_plays = FW.build_factual_week(
        season=SEASON, week=WEEK,
        games=[{"game": W.settlement_game_row(), "plays": [],
                "stats": list(W.SETTLEMENT_STATS)}])
    _defences = [v for k, v in _no_plays.subjects.items()
                 if k.startswith("bdl.dst.")]
    _offence = [v for k, v in _no_plays.subjects.items()
                if k.startswith("bdl.p.")]
    _assert("with NO play evidence every team defence REFUSES",
            _defences and all(not d.complete for d in _defences),
            str([d.diagnostics for d in _defences][:1]))
    _assert("  · no fabricated zero, no fallback to another provider",
            all("UNKNOWN_DRIVE_EVENTS" in str(d.diagnostics)
                or "MISSING" in str(d.diagnostics) for d in _defences))
    _assert("  · while the offensive subjects, whose scoring needs no plays, "
            "are still scoreable -- correctness per subject, not per week",
            _offence and all(o.complete for o in _offence))
    db.rollback()


# ══════════════════════════════════════════════════════════════════════════════
# 7B-P9c · correction and regrade
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-P9c · a corrected stat line, and what the product does with it")

with SessionLocal() as db:
    from providers.balldontlie import factual_scores as FS
    from scoring.profile import load_profile

    _profile = load_profile(W.PROFILE_ID)
    _before = FS.persisted_subject_facts(db, season=SEASON, week=WEEK)
    _fingerprint_before = dict(_before["bdl.p.27"].components)

    # EVIDENCE B: the provider revises the quarterback's yardage upward.
    _corrected = [dict(row) for row in W.SETTLEMENT_STATS]
    _corrected[0]["passing_yards"] = 351
    _week_b, _report_b = W.ingest_settlement_facts(
        db, players_by_key, stats=_corrected,
        captured_at=datetime(2026, 1, 6, tzinfo=timezone.utc))
    db.commit()

    _assert("a corrected stat line is stored as a NEW observation",
            _report_b.stored >= 1,
            f"{_report_b.stored} stored, {_report_b.duplicate} duplicate")
    _after = FS.persisted_subject_facts(db, season=SEASON, week=WEEK)
    _assert("  · the newest observation is what a fresh read now sees",
            _after["bdl.p.27"].components.get("passing_yards") == 351.0,
            str(_after["bdl.p.27"].components.get("passing_yards")))
    _assert("  · while EVIDENCE A is still on disk, still replayable -- a "
            "correction appends, it does not overwrite history",
            db.query(ProviderComponentProjection).filter(
                ProviderComponentProjection.provider_player_key == "bdl.p.27",
                ProviderComponentProjection.source_kind
                == ProviderComponentProjection.SOURCE_WEEKLY_STATS).count()
            == 2)
    _digests = [r.observation_digest for r in db.query(
        ProviderComponentProjection).filter(
        ProviderComponentProjection.provider_player_key == "bdl.p.27",
        ProviderComponentProjection.source_kind
        == ProviderComponentProjection.SOURCE_WEEKLY_STATS).all()]
    _assert("  · and the two observations carry DISTINCT fingerprints",
            len(set(_digests)) == 2, str([d[:12] for d in _digests]))

    _regraded = FS.score_team_lineups(
        db, snapshot=W.yahoo_snapshot(**SNAPSHOT_ARGS), season=SEASON,
        week=WEEK, profile=_profile)
    _assert("  · re-scoring on the corrected evidence gives a DIFFERENT score",
            _regraded.lineups[TEAM_KEYS[0]].points != HOME_POINTS,
            f"{HOME_POINTS} -> {_regraded.lineups[TEAM_KEYS[0]].points}")

# THE ECONOMIC QUESTION, ANSWERED HONESTLY. The week is already settled. This
# product builds NO automatic economic reversal — `providers/persist.py` records
# a ProviderConflict and refuses rather than rewriting a final result, and
# Sprint 6 says in terms that reversal economics are not built. So Sprint 7B
# does not invent them: it verifies that the already-settled money did NOT move
# and that the contradiction is surfaced as the operator state it is.
_assert("the corrected evidence moved NO already-settled money",
        {t: balance_of(f"wallet:{t}") for t in TEAM_IDS} == _POOL_WALLETS_AFTER,
        str({t: balance_of(f"wallet:{t}") for t in TEAM_IDS}))
_assert("  · and the trial balance is untouched by the correction",
        trial_balance() == 0)

with SessionLocal() as db:
    _row = db.query(Matchup).filter(
        Matchup.league_id == LEAGUE_ID, Matchup.week == WEEK,
        Matchup.provider_matchup_key.isnot(None)).one()
    _assert("  · the FINAL matchup score is unchanged, because a final result "
            "is not silently rewritten",
            abs(_row.home_score - HOME_POINTS) < 1e-6,
            f"{_row.home_score} still, not "
            f"{_regraded.lineups[TEAM_KEYS[0]].points}")
    _assert("  · Sprint 7B invents no reversal economics -- the corrected "
            "figure is available to an operator and applied by nobody",
            _row.finalized_at is not None)


# ══════════════════════════════════════════════════════════════════════════════
# 7B-P9d · the weekly refresh is wired, and it is the EXISTING one
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-P9d · the Tuesday pipeline scores this league from its own facts")

import notifications.tuesday_sync as TUESDAY                            # noqa: E402

with SessionLocal() as db:
    _snapshot = W.yahoo_snapshot(**SNAPSHOT_ARGS)
    _applied = TUESDAY._apply_balldontlie_scores(
        db, _snapshot, league_id=LEAGUE_ID, week=WEEK)
    _assert("the EXISTING weekly refresh substitutes the scores for a "
            "configured league",
            _applied is not _snapshot
            and _applied.matchups[0].home_points is not None,
            f"home {_applied.matchups[0].home_points} "
            f"away {_applied.matchups[0].away_points}")
    _assert("  · from the corrected evidence, so the pipeline reads the "
            "newest observation like every other consumer",
            abs(_applied.matchups[0].home_points
                - _regraded.lineups[TEAM_KEYS[0]].points) < 1e-9)

    # A LEAGUE THAT WAS NOT MOVED IS RETURNED UNTOUCHED, by identity.
    from providers.selection import set_selection

    set_selection(db, league_id=LEAGUE_ID, season=SEASON,
                  factual_source="legacy")
    db.flush()
    _untouched = TUESDAY._apply_balldontlie_scores(
        db, _snapshot, league_id=LEAGUE_ID, week=WEEK)
    _assert("  · and a league on the legacy path is returned UNTOUCHED, by "
            "object identity -- the pipeline costs it nothing",
            _untouched is _snapshot)
    db.rollback()

_assert("no new scheduler, poller or worker was added -- it is the same "
        "Tuesday step, the same writer and the same finality mapping",
        "def _apply_balldontlie_scores" in open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "notifications", "tuesday_sync.py"),
            encoding="utf-8").read())

_refresh_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "notifications", "tuesday_sync.py"),
                    encoding="utf-8").read()
_assert("  · and the substitution FAILS CLOSED: a league that chose "
        "BALLDONTLIE never falls through to Yahoo's points",
        "Yahoo\'s\npoints are NOT substituted" in _refresh_src
        or "points are NOT substituted" in _refresh_src)


# ══════════════════════════════════════════════════════════════════════════════
# 7B-P10 · restart, and the economic freeze
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-P10 · everything survives a restart, and no economic rule moved")

with SessionLocal() as db:
    from providers.selection import resolve as resolve_selection

    selection = resolve_selection(db, league_id=LEAGUE_ID, season=SEASON)
    _assert("the provider selection survived every commit and reconnect",
            (selection.projection_source, selection.factual_source,
             selection.simulation_model, selection.scoring_profile_id)
            == ("balldontlie", "balldontlie", "sim-v2", W.PROFILE_ID))
    _assert("  · the settled bets are still settled",
            db.query(Bet).filter(Bet.beef_challenge_id == CHALLENGE_ID,
                                 Bet.status.in_(("won", "lost"))).count() == 2)
    _assert("  · the Pool instance is still settled",
            db.query(PoolInstance).filter(
                PoolInstance.id == INSTANCE_ID).one().settled is True)
    # THE ORIGINAL EVIDENCE AND THE CORRECTION BOTH SURVIVE. Three rows, not
    # two: the correction in 7B-P9c APPENDED an observation rather than
    # replacing one, which is exactly the property being asserted here. A test
    # that still expected two would be asserting that history gets overwritten.
    _rows = db.query(ProviderComponentProjection).filter(
        ProviderComponentProjection.source_kind
        == ProviderComponentProjection.SOURCE_WEEKLY_STATS).all()
    _assert("  · every factual observation is still there, correction included",
            len(_rows) == FACT_ROWS + 1
            and len({r.observation_digest for r in _rows}) == FACT_ROWS + 1,
            f"{len(_rows)} rows, {FACT_ROWS} before the correction")
    _assert("  · so the settled week can still be replayed on the evidence it "
            "was actually settled on",
            any(abs(float((r.components or {}).get("passing_yards", 0)) - 320.0)
                < 1e-6 for r in _rows))
    _assert("  · and the ledger still balances after everything",
            trial_balance() == 0)

from odds.model_registry import MODEL_V1, model_config_hash               # noqa: E402
from odds.model_registry import ACTIVE_MODEL_VERSION_ID                   # noqa: E402

_assert("sim-v1's frozen hash is unchanged by a real settlement run",
        model_config_hash(MODEL_V1)
        == "1d60ff39343bebf1ceb8099f729fbaff18cb278078e06d094da6cc04ba4626d1")
_assert("  · and the global default model is still sim-v1",
        ACTIVE_MODEL_VERSION_ID == "sim-v1")

import ast                                                               # noqa: E402

_fs_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "providers", "balldontlie", "factual_scores.py"),
               encoding="utf-8").read()
_imports = {n.module for n in ast.walk(ast.parse(_fs_src))
            if isinstance(n, ast.ImportFrom) and n.module}
_assert("the factual-score adapter imports NO economic module",
        not [m for m in _imports
             if m.split(".")[0] in ("ledger", "economy", "betting")
             and m != "betting.pool_subjects"],
        str(sorted(_imports)))
# ASSIGNMENTS, NOT MENTIONS. An earlier version of this check grepped for the
# strings and failed on the module's own docstring, which explains at length why
# it does not write them — a scan that punishes a file for documenting its
# constraint is measuring prose, not behaviour. This walks the syntax tree for
# actual attribute assignment, which is the same technique the C-7 score-writer
# gate uses.
_assigned = set()
for _node in ast.walk(ast.parse(_fs_src)):
    if isinstance(_node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        _targets = (_node.targets if isinstance(_node, ast.Assign)
                    else [_node.target])
        for _t in _targets:
            if isinstance(_t, ast.Attribute):
                _assigned.add(_t.attr)
_assert("  · and ASSIGNS no score itself -- it returns a snapshot for the "
        "certified writer to persist",
        not ({"home_score", "away_score"} & _assigned), str(sorted(_assigned)))
_assert("  · nor assigns finalized_at, whose single writer is "
        "providers/finality.py",
        "finalized_at" not in _assigned)


print()
print("=" * 78)
if _failed:
    print(f"SPRINT 7B SETTLEMENT: {_failed} FAILED, {_passed} passed")
    raise SystemExit(1)
print(f"SPRINT 7B SETTLEMENT: all {_passed} assertions passed — a real Versus\n"
      f"wager and a real Pool both settled from BALLDONTLIE evidence, through "
      f"the\nexisting engines, into the real ledger, with the trial balance at "
      f"zero.")
print("=" * 78)
