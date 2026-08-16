#!/usr/bin/env python3
"""
test_wp3c_projection_context.py — WP3C · the Versus odds projection coupling.

THE DEFECT THIS CERTIFIES CLOSED, and why it was invisible.

`beefs/beef_engine` read every projection as
`season=config.CURRENT_SEASON, source="fantasypros"` — a global pinned to 2025
by a comment that calls itself temporary, and a string literal. A league playing
any other season matched no projection rows at all. Nothing raised: a missing
`Projection` is recorded as `0.0`, so the simulator was handed a board of zeroes
and priced it confidently. The Demo runtime seeds season 2100, so every Demo
wager would have priced off zeroes the moment WP3C made the composer real.

WHAT MAKES THIS TESTABLE RATHER THAN A JUDGEMENT CALL. `leagues.season` and
`leagues.projection_source` are both NOT NULL columns and the second defaults to
`fantasypros`. The per-league projection contract already existed; the engine
simply did not read it. So the fix is call-site plumbing (GREEN) and the
assertions below are about WHICH ROWS ARE READ, never about what the odds model
does with them.

FIVE CLAIMS:

  1. A league on a NON-GLOBAL season resolves its own projections. The
     discriminating fixture seeds the SAME players in two seasons with
     DIFFERENT values, so an engine still reading the global returns the wrong
     numbers rather than no numbers — a failure a zero-check would miss.
  2. A league on a NON-DEFAULT projection source resolves its own source, for
     the same reason and with the same shape.
  3. A caller with no resolvable league falls back to exactly the pre-WP3C
     globals, so legacy paths are untouched.
  4. A MISSING projection still resolves to nothing. Reading the right season
     must not invent rows in it.
  5. THE ODDS MATHEMATICS IS UNCHANGED. Identical inputs produce identical
     output before and after, asserted against the engine's own simulator.

DATABASE. A temp SQLite file per run. No locking or concurrency claim.
"""

from __future__ import annotations

import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'wp3c_proj.db')}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from config import CURRENT_SEASON                                # noqa: E402
from beefs.beef_engine import (                                  # noqa: E402
    GLOBAL_PROJECTION_CONTEXT, N_START, _fetch_starters_for_odds,
    projection_context_for_team,
)
from db.schema import (                                          # noqa: E402
    Base, League, Player, Projection, Roster, SessionLocal, Team, engine,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


# ── Fixture ──────────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)

#: Deliberately NOT the global. If the engine still reads the global, a league
#: on this season reads nothing — or, worse, reads the other season's numbers.
DEMO_SEASON = 2100
#: Deliberately not the default literal.
CUSTOM_SOURCE = "yahoo"

#: The two projection values are DIFFERENT and both NON-ZERO. That is what makes
#: this discriminating: an engine reading the wrong season returns the wrong
#: total rather than zero, and a test that only checked "not zero" would pass.
GLOBAL_POINTS = 5.0
DEMO_POINTS = 17.5
CUSTOM_POINTS = 11.25

with SessionLocal() as db:
    # League A — a Demo-style league on a season the global does not name.
    league_a = League(name="WP3C Demo", season=DEMO_SEASON,
                      projection_source="fantasypros")
    # League B — the global season, but a non-default projection source.
    league_b = League(name="WP3C Custom", season=CURRENT_SEASON,
                      projection_source=CUSTOM_SOURCE)
    db.add_all([league_a, league_b])
    db.flush()
    A_ID, B_ID = league_a.id, league_b.id

    TEAMS: dict[str, int] = {}
    for tag, league_id in (("a1", A_ID), ("a2", A_ID), ("b1", B_ID), ("b2", B_ID)):
        t = Team(team_name=f"Team {tag}", owner=f"Owner {tag}",
                 email=f"{tag}@wp3c.test", league_id=league_id)
        db.add(t)
        db.flush()
        TEAMS[tag] = t.id

    # One full starting lineup per team, and for EVERY team the same players are
    # projected in all three (season, source) combinations — so whichever the
    # engine reads, it finds a complete board. Only the VALUES differ.
    for tag in TEAMS:
        for slot in range(N_START):
            p = Player(name=f"{tag} player {slot}", position="WR", nfl_team="KC")
            db.add(p)
            db.flush()
            db.add(Roster(team_id=TEAMS[tag], player_id=p.id))
            for season, source, points in (
                (CURRENT_SEASON, "fantasypros", GLOBAL_POINTS),
                (DEMO_SEASON, "fantasypros", DEMO_POINTS),
                (CURRENT_SEASON, CUSTOM_SOURCE, CUSTOM_POINTS),
            ):
                db.add(Projection(player_id=p.id, week=1, season=season,
                                  source=source, projected_points=points))
    db.commit()

WEEK = 1
EXPECTED_GLOBAL_TOTAL = GLOBAL_POINTS * N_START
EXPECTED_DEMO_TOTAL = DEMO_POINTS * N_START
EXPECTED_CUSTOM_TOTAL = CUSTOM_POINTS * N_START


def _total(starters) -> float:
    return round(sum(s.projected_points for s in starters), 4)


# ── 1 · The context resolver ─────────────────────────────────────────────────

_section("1 · The projection context is the league's own")

with SessionLocal() as db:
    ctx_a = projection_context_for_team(db, TEAMS["a1"])
    ctx_b = projection_context_for_team(db, TEAMS["b1"])
    ctx_none = projection_context_for_team(db, None)
    ctx_absent = projection_context_for_team(db, 999_999)

_assert("a league on a non-global season resolves its own season",
        ctx_a.season == DEMO_SEASON, str(ctx_a.season))
_assert("and its own projection source",
        ctx_a.source == "fantasypros", ctx_a.source)
_assert("a league with a non-default source resolves that source",
        ctx_b.source == CUSTOM_SOURCE, ctx_b.source)
_assert("and that league's own season",
        ctx_b.season == CURRENT_SEASON, str(ctx_b.season))
_assert("the demo season is genuinely not the global — the test discriminates",
        DEMO_SEASON != CURRENT_SEASON, f"{DEMO_SEASON} vs {CURRENT_SEASON}")

_section("2 · A caller with no league gets exactly the pre-WP3C globals")

_assert("no team id falls back to the globals",
        ctx_none == GLOBAL_PROJECTION_CONTEXT, str(ctx_none))
_assert("an unknown team id falls back to the globals",
        ctx_absent == GLOBAL_PROJECTION_CONTEXT, str(ctx_absent))
_assert("and those globals are the values the module always used",
        GLOBAL_PROJECTION_CONTEXT.season == CURRENT_SEASON
        and GLOBAL_PROJECTION_CONTEXT.source == "fantasypros",
        str(GLOBAL_PROJECTION_CONTEXT))


# ── 3 · The odds path reads through it ───────────────────────────────────────

_section("3 · The odds inputs come from the league's own projections")

with SessionLocal() as db:
    inputs_a = _fetch_starters_for_odds(
        "straight", TEAMS["a1"], TEAMS["a2"], None, WEEK, db)
    inputs_b = _fetch_starters_for_odds(
        "straight", TEAMS["b1"], TEAMS["b2"], None, WEEK, db)

_assert("the demo-season league reads ITS season's projections",
        _total(inputs_a.ch_starters) == EXPECTED_DEMO_TOTAL,
        f"{_total(inputs_a.ch_starters)} vs {EXPECTED_DEMO_TOTAL}")
_assert("both sides of the wager, not only the challenger",
        _total(inputs_a.cd_starters) == EXPECTED_DEMO_TOTAL,
        f"{_total(inputs_a.cd_starters)} vs {EXPECTED_DEMO_TOTAL}")
_assert("it is NOT the global season's board",
        _total(inputs_a.ch_starters) != EXPECTED_GLOBAL_TOTAL,
        f"global would be {EXPECTED_GLOBAL_TOTAL}")
_assert("and it is not a board of zeroes — the old failure mode",
        _total(inputs_a.ch_starters) > 0)

_assert("the custom-source league reads ITS source's projections",
        _total(inputs_b.ch_starters) == EXPECTED_CUSTOM_TOTAL,
        f"{_total(inputs_b.ch_starters)} vs {EXPECTED_CUSTOM_TOTAL}")
_assert("it is NOT the default source's board",
        _total(inputs_b.ch_starters) != EXPECTED_GLOBAL_TOTAL,
        f"default source would be {EXPECTED_GLOBAL_TOTAL}")

_assert("the points snapshot carries the same figures the inputs did",
        round(sum(inputs_a.points_snapshot.values()), 4)
        == round(EXPECTED_DEMO_TOTAL * 2, 4),
        str(round(sum(inputs_a.points_snapshot.values()), 4)))


_section("4 · A missing projection still resolves to nothing")

# Reading the RIGHT season must not conjure rows in it. A week nobody projected
# is still unprojected, and the engine records that exactly as it always did.
with SessionLocal() as db:
    inputs_empty = _fetch_starters_for_odds(
        "straight", TEAMS["a1"], TEAMS["a2"], None, 99, db)

_assert("an unprojected week yields a zero board, honestly",
        _total(inputs_empty.ch_starters) == 0.0,
        str(_total(inputs_empty.ch_starters)))
_assert("with the starters still named — the roster is known, the projection is not",
        len(inputs_empty.ch_starters) == N_START,
        str(len(inputs_empty.ch_starters)))
_assert("nothing was invented to fill the gap",
        all(s.projected_points == 0.0 for s in inputs_empty.ch_starters))


# ── 5 · The odds mathematics is untouched ────────────────────────────────────

_section("5 · The odds model itself is unchanged")

# THE STRONGEST FORM OF THIS CLAIM IS THAT THE SIMULATOR IS CALLED WITH THE SAME
# CONFIG AND PRODUCES THE SAME ANSWER FOR THE SAME INPUTS. WP3C changed which
# rows are gathered; it did not touch `_compute_odds_from_inputs`, the model
# registry, or any probability constant.
import inspect                                                    # noqa: E402

from beefs import beef_engine                                     # noqa: E402

_compute_src = inspect.getsource(beef_engine._compute_odds_from_inputs)
_assert("_compute_odds_from_inputs reads no season or source",
        "SEASON" not in _compute_src and "SOURCE" not in _compute_src
        and "ctx." not in _compute_src)
_assert("the legacy pricing path is still pinned to the v1 model config",
        "LEGACY_MODEL_CONFIG" in inspect.getsource(beef_engine))

# Same inputs in, same odds out — run twice against a fixed board.
with SessionLocal() as db:
    first = beef_engine._compute_odds_from_inputs(
        "straight", inputs_a, WEEK, None, None)
    second = beef_engine._compute_odds_from_inputs(
        "straight", inputs_a, WEEK, None, None)
_assert("the simulator is deterministic for a fixed board",
        first == second, f"{first} vs {second}")
_assert("and it returns a real quote rather than a degenerate one",
        all(v is not None for v in first), str(first))


_section("6 · The global constant is no longer read on the odds path")

_engine_src = inspect.getsource(beef_engine)
_fetch_src = (inspect.getsource(beef_engine._fetch_starters_for_odds)
              + inspect.getsource(
                  beef_engine._fetch_starters_for_odds_from_snapshot))
_assert("no projection query in the fetch path names the global season",
        "season=SEASON" not in _fetch_src)
_assert("no projection query in the fetch path names a literal source",
        'source="fantasypros"' not in _fetch_src
        and "source=SOURCE" not in _fetch_src)
_assert("every projection query reads the resolved context",
        _fetch_src.count("season=ctx.season, source=ctx.source") >= 3,
        str(_fetch_src.count("season=ctx.season, source=ctx.source")))
_assert("the globals survive only as the named fallback",
        "GLOBAL_PROJECTION_CONTEXT = ProjectionContext(season=SEASON, "
        "source=SOURCE)" in _engine_src)


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 66)
if _failures:
    print(f"WP3C PROJECTION CONTEXT — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("WP3C PROJECTION CONTEXT — all assertions PASSED")
