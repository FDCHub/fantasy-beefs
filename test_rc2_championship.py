#!/usr/bin/env python3
"""RC2 Championship certification — snapshot lifecycle and tied 60/30/10 math.

SQLite is sufficient for this package's deterministic arithmetic, metadata
registration and immutable snapshot state machine. PostgreSQL migration behavior
is certified separately by the migration harness before RC2 is tagged.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone

_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_rc2_championship.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the RC2 model before create_all so the two additive tables are
# registered on Base.metadata exactly as they are during api startup.
from reports.championship_read_model import (  # noqa: E402
    ChampionshipRow,
    FantasyStakesChampionshipError,
    REASON_TOO_EARLY,
    freeze_fantasystakes_championship,
    get_fantasystakes_championship,
    tied_championship_distribution,
)
from db.schema import Base, League, SessionLocal, Team, Wallet, engine  # noqa: E402
from ledger.ledger import create_ledger_table  # noqa: E402

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _row(team_id: int, score: int) -> ChampionshipRow:
    return ChampionshipRow(
        team_id=team_id,
        team_name=f"Team {team_id}",
        owner=f"Owner {team_id}",
        matchup_net_cents=score,
        prop_pool_net_cents=0,
        championship_score_cents=score,
        place=0,
        tied=False,
    )


Base.metadata.create_all(engine)
create_ledger_table()


print("\nRC2-1 · tied FantasyStakes Championship distribution")

normal = tied_championship_distribution(
    96_000, [_row(1, 300), _row(2, 200), _row(3, 100), _row(4, 0)])
_assert("normal podium is 60/30/10",
        [(a.team_id, a.amount_cents) for a in normal]
        == [(1, 57_600), (2, 28_800), (3, 9_600)], str(normal))

first_tie = tied_championship_distribution(
    96_000, [_row(2, 300), _row(1, 300), _row(3, 100), _row(4, 0)])
_assert("two-way tie for first pools 60+30 and splits equally",
        [(a.team_id, a.place, a.amount_cents) for a in first_tie]
        == [(1, 1, 43_200), (2, 1, 43_200), (3, 3, 9_600)], str(first_tie))

second_tie = tied_championship_distribution(
    96_000, [_row(1, 400), _row(2, 200), _row(3, 200), _row(4, 0)])
_assert("two-way tie for second pools 30+10 and splits equally",
        [(a.team_id, a.place, a.amount_cents) for a in second_tie]
        == [(1, 1, 57_600), (2, 2, 19_200), (3, 2, 19_200)], str(second_tie))

three_first = tied_championship_distribution(
    96_000, [_row(3, 500), _row(1, 500), _row(2, 500), _row(4, 0)])
_assert("three-way tie for first splits the entire pot",
        [(a.team_id, a.place, a.amount_cents) for a in three_first]
        == [(1, 1, 32_000), (2, 1, 32_000), (3, 1, 32_000)], str(three_first))

four_first = tied_championship_distribution(
    96_001, [_row(4, 500), _row(3, 500), _row(2, 500), _row(1, 500)])
_assert("tie extending past third shares all occupied podium slots",
        sum(a.amount_cents for a in four_first) == 96_001
        and len(four_first) == 4
        and {a.place for a in four_first} == {1}, str(four_first))
_assert("indivisible tie remainder is deterministic by canonical team id only",
        [(a.team_id, a.amount_cents) for a in four_first]
        == [(1, 24_001), (2, 24_000), (3, 24_000), (4, 24_000)], str(four_first))


print("\nRC2-2 · championship freeze lifecycle")

with SessionLocal() as db:
    league = League(
        season=2026,
        name="RC2 Championship Test",
        projection_source="fantasypros",
        start_week=1,
        playoff_start_week=15,
        season_final_week=17,
        provider_current_week=14,
    )
    db.add(league)
    db.flush()
    league_id = league.id
    for i in range(4):
        team = Team(
            league_id=league_id,
            team_name=f"RC2 Team {i + 1}",
            owner=f"Owner {i + 1}",
            email=f"rc2-{i + 1}@example.test",
        )
        db.add(team)
        db.flush()
        db.add(Wallet(team_id=team.id, balance=0.0))
    db.commit()

with SessionLocal() as db:
    reason = None
    try:
        freeze_fantasystakes_championship(db, league_id=league_id)
    except FantasyStakesChampionshipError as exc:
        reason = exc.reason
        db.rollback()
    _assert("freeze refuses before Yahoo playoff boundary",
            reason == REASON_TOO_EARLY, str(reason))

freeze_at = datetime(2026, 12, 15, 12, 0, tzinfo=timezone.utc)
with SessionLocal() as db:
    league = db.query(League).filter(League.id == league_id).first()
    league.provider_current_week = 15
    db.commit()

with SessionLocal() as db:
    snapshot = freeze_fantasystakes_championship(
        db, league_id=league_id, now=freeze_at)
    db.commit()
    _assert("freeze captures every team", len(snapshot.rows) == 4, str(snapshot.rows))
    _assert("all-zero competitive results are a real four-way tie for first",
            all(r.place == 1 and r.tied and r.championship_score_cents == 0
                for r in snapshot.rows), str(snapshot.rows))
    _assert("cutoff is the final Yahoo regular-season week",
            snapshot.playoff_start_week == 15
            and snapshot.scoring_through_week == 14)

with SessionLocal() as db:
    replay = freeze_fantasystakes_championship(db, league_id=league_id)
    persisted = get_fantasystakes_championship(db, league_id=league_id)
    _assert("freeze replay returns the immutable original timestamp",
            replay.frozen_at == freeze_at and persisted is not None
            and persisted.frozen_at == freeze_at,
            f"replay={replay.frozen_at!r} persisted={getattr(persisted, 'frozen_at', None)!r}")
    _assert("freeze replay creates no duplicate team scores",
            len(replay.rows) == 4 and len({r.team_id for r in replay.rows}) == 4)


print(f"\n{'=' * 64}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for failure in _failures:
        print(f"  - {failure}")
    sys.exit(1)

print("PASS: RC2 championship snapshot and tied-podium certification")
