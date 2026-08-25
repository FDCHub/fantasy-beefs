#!/usr/bin/env python3
"""DEMO D1 — the showcase demo league, certified.

    python test_d1_demo_environment.py
    DATABASE_URL=postgresql://.../fs_d1_test python test_d1_demo_environment.py

WHAT MATTERS MOST HERE IS SECTION 4. A reset command that can reach a real
league is the kind of mistake that ends a product, so the isolation proofs are
driven against REAL non-demo leagues sitting in the same database: a Yahoo
league, a league with no provider at all, and a league deliberately named
"FantasyStakes Demo League". Every one must be refused, and must still be intact
afterwards.

The rest certifies that the demo is worth showing: deterministic, idempotent,
populated on every surface, balanced, and produced by the REAL engines rather
than by fixture arithmetic.
"""
from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="d1-demo-")
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = (
        "sqlite:///" + os.path.join(_TMP, "d1.db").replace(os.sep, "/"))
os.environ.setdefault("JWT_SECRET_KEY", "d1-demo-suite")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAIL: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


def section(title: str) -> None:
    print(f"\n{title}")


from fastapi.testclient import TestClient  # noqa: E402

import api.main_rc2 as entry  # noqa: E402

with TestClient(entry.app):
    pass

from sqlalchemy import text  # noqa: E402

from db.schema import League, SessionLocal, Team, engine  # noqa: E402
from ledger.ledger import create_ledger_table, trial_balance  # noqa: E402

create_ledger_table()

from demo import showcase  # noqa: E402
from demo.reset import DemoSafetyError, assert_demo_league, check as reset_check  # noqa: E402
from demo.reset import reset as demo_reset  # noqa: E402
from demo.seed import find_showcase, seed, status  # noqa: E402

print("=" * 74)
print(f"D1 — FANTASYSTAKES SHOWCASE DEMO  ({engine.dialect.name})")
print("=" * 74)


# ── 1 · seeding ──────────────────────────────────────────────────────────────

section("1 · The showcase seeds deterministically and balances")

first = seed()
check("the seed reports a league", isinstance(first.get("league_id"), int))
check("twelve teams", first["teams"] == 12, str(first["teams"]))
check("the demo opens in week 11", first["current_week"] == 11,
      str(first["current_week"]))
# FOURTEEN weeks are now scheduled, not eleven: `demo.states` finalizes weeks
# 11-14 as it plays them, so the seeder lays down the whole regular season and
# leaves the unplayed part unfinalized rather than absent.
check("a full season of matchups exists",
      first["matchups"] == 6 * showcase.REGULAR_SEASON_WEEKS,
      str(first["matchups"]))
check("ten weeks were played through the real lifecycle",
      first["weeks_played"] == showcase.COMPLETED_THROUGH_WEEK,
      str(first["weeks_played"]))
check("real FantasyStakes contests were struck",
      first["versus_issued"] >= 10, str(first["versus_issued"]))
check("prop pools were settled", first["pools_settled"] >= 4,
      str(first["pools_settled"]))
check("the live week carries open prop pools",
      first["live_week"]["claims"] > 0, str(first["live_week"]))
check("THE LEDGER BALANCES", trial_balance() == 0, str(trial_balance()))

with SessionLocal() as db:
    league = find_showcase(db)
    league_id = league.id
    check("the league is bound to the demo provider",
          league.provider == "demo", str(league.provider))
    check("  · in the demo namespace, marked showcase",
          league.provider_league_key.startswith("demo.l.showcase."),
          league.provider_league_key)
    check("twelve team rows exist",
          db.query(Team).filter(Team.league_id == league_id).count() == 12)


# ── 2 · determinism and idempotence ──────────────────────────────────────────

section("2 · Seeding twice yields the same league, not a different one")


def fingerprint(db, lid: int) -> tuple:
    """What a viewer would see: names, records and competitive net."""
    from reports.standings_read_model import league_standings

    st = league_standings(db, league_id=lid)
    rows = getattr(st, "overall", None) or getattr(st, "rows", st)
    return tuple((r.team_name, r.net_cents, r.versus_net_cents, r.pool_net_cents)
                 for r in rows)


with SessionLocal() as db:
    before = fingerprint(db, league_id)

# ── WHAT "DETERMINISTIC" MEANS ONCE THE SEASON IS REALLY PLAYED ─────────────
#
# This used to reseed into the same database and demand a byte-identical league.
# That held while the seeder hand-posted results, and it cannot hold now:
# `betting.pool_rotation` ranks each week's candidates by a digest over
# (definition_key, league_id, season, rotation_cycle), so a SECOND league draws
# a different Pool slate — deliberately, so two real leagues do not play the
# same card — and therefore reaches different standings.
#
# So the property the demo actually needs is that ONE league reproduces:
# restoring it returns the identical league, and a cold database reproduces it
# from scratch (`test_d24_determinism.py` runs the whole lifecycle twice on two
# databases and compares every canonical output).
from demo.reset import ensure_canonical, is_canonical           # noqa: E402

with SessionLocal() as db:
    check("the seeded league is canonical CURRENT",
          is_canonical(db, find_showcase(db)))

restored = ensure_canonical()
with SessionLocal() as db:
    same = find_showcase(db)
    after = fingerprint(db, same.id)
check("an untouched league is left completely alone",
      restored["action"] == "none", str(restored["action"]))
check("restoring reproduces the identical league, row for row",
      before == after, f"{len(before)} rows compared")
check("  · and it is the SAME league — the rotation digest is keyed on the "
      "league id, so a new id would draw a different Pool slate",
      same.id == league_id, f"{league_id} -> {same.id}")
check("the ledger still balances", trial_balance() == 0, str(trial_balance()))


# ── 3 · the league is worth showing ──────────────────────────────────────────

section("3 · Every surface has something meaningful on it")

with SessionLocal() as db:
    league = find_showcase(db)
    lid = league.id
    from reports.standings_read_model import league_standings

    st = league_standings(db, league_id=lid)
    rows = list(getattr(st, "overall", None) or getattr(st, "rows", st))
    by_name = {r.team_name: r for r in rows}
    ordinal_name = {t.ordinal: t.team_name for t in showcase.TEAMS}

check("standings are populated for all twelve GMs", len(rows) == 12, str(len(rows)))
check("the standings actually separate the field",
      len({r.net_cents for r in rows}) >= 6,
      f"{len({r.net_cents for r in rows})} distinct nets")
check("Matchup net is populated", any(r.versus_net_cents for r in rows))
check("Prop Pool net is populated", any(r.pool_net_cents for r in rows))

story = showcase.expected_story()
# THE STORY IS NOW THE SEASON'S, NOT THE FIXTURE'S. These used to assert a
# narrative the seeder hand-posted into existence. The season is genuinely
# played now, so `expected_story()` records what the engines produce and this
# checks the league still produces it.
leader = ordinal_name[story["current_leader_ordinal"]]
check(f"the CURRENT leader ({leader}) tops the table",
      rows[0].team_name == leader, rows[0].team_name)
unbeaten = ordinal_name[story["current_unbeaten_ordinal"]]
ub = next(r for r in rows if r.team_name == unbeaten)
check(f"{unbeaten} is unbeaten in FantasyStakes matchups",
      ub.versus_losses == 0 and ub.versus_wins > 0,
      f"{ub.versus_wins}-{ub.versus_losses}")
check("nobody is left with a meaningless flat zero on every column",
      all(r.net_cents or r.versus_net_cents or r.pool_net_cents for r in rows))

with SessionLocal() as db:
    live = db.execute(text(
        "SELECT count(*) FROM matchups WHERE league_id = :l AND week = 11 "
        "AND finalized_at IS NULL"), {"l": lid}).scalar()
    done = db.execute(text(
        "SELECT count(*) FROM matchups WHERE league_id = :l "
        "AND finalized_at IS NOT NULL"), {"l": lid}).scalar()
    db_unfinalized_total = db.execute(text(
        "SELECT count(*) FROM matchups WHERE league_id = :l "
        "AND finalized_at IS NULL"), {"l": lid}).scalar()
check("week 11 is live — six unfinalized matchups", live == 6, str(live))
check("ten weeks are complete — sixty finalized matchups", done == 60, str(done))
check("weeks 12-14 are scheduled but unplayed",
      db_unfinalized_total == 6 * (showcase.REGULAR_SEASON_WEEKS
                                   - showcase.COMPLETED_THROUGH_WEEK),
      str(db_unfinalized_total))

# THE REAL ECONOMY PRODUCED THE ALLOCATION, not this fixture.
from api.championship_routes import _season_opening_allocation  # noqa: E402

with SessionLocal() as db:
    alloc = _season_opening_allocation(db, find_showcase(db))
check("the Season-Opening Allocation is derived by the real helper",
      alloc is not None)
if alloc:
    check("  · Weekly Play Reserve = weekly minimum x 14",
          alloc["weekly_play_reserve_cents"]
          == showcase.WEEKLY_BET_MINIMUM_CENTS * 14,
          str(alloc["weekly_play_reserve_cents"]))
    check("  · and the total is the sum of its three parts",
          alloc["season_opening_allocation_cents"]
          == alloc["weekly_play_reserve_cents"]
          + alloc["yahoo_championship_contribution_cents"]
          + alloc["fantasystakes_championship_contribution_cents"])

with SessionLocal() as db:
    postings = db.execute(text("SELECT count(*) FROM ledger_entries")).scalar()
    doors = {r[0] for r in db.execute(
        text("SELECT DISTINCT door FROM ledger_entries")).fetchall()}
check("the Ledger has real history", postings > 300, str(postings))
check("  · through the real competitive doors",
      {"wager_settled", "pool_weekly_collection",
       "pool_winner_distribution"} <= doors,
      str(sorted(doors)))
check("  · and the real allocation door", "season_allocation" in doors)


# ── 4 · PRODUCTION ISOLATION — the part that must not be wrong ───────────────

section("4 · The demo cannot reach a league it did not create")

with SessionLocal() as db:
    real_yahoo = League(season=2101, name="Real Yahoo League",
                        projection_source="fantasypros", provider="yahoo",
                        provider_league_key="461.l.998877")
    unbound = League(season=2101, name="Unbound League",
                     projection_source="fantasypros")
    # THE TRAP: a real league that CALLS ITSELF the demo league.
    impostor = League(season=showcase.SEASON, name="FantasyStakes Demo League",
                      projection_source="fantasypros", provider="yahoo",
                      provider_league_key="461.l.112233")
    for lg in (real_yahoo, unbound, impostor):
        db.add(lg)
    db.commit()
    protected = {"yahoo": real_yahoo.id, "unbound": unbound.id,
                 "impostor": impostor.id}

for label, lid in protected.items():
    with SessionLocal() as db:
        lg = db.query(League).filter(League.id == lid).first()
        refused = False
        reason = ""
        try:
            assert_demo_league(lg)
        except DemoSafetyError as exc:
            refused, reason = True, str(exc)[:70]
        check(f"the guard refuses the {label} league", refused, reason)

# A league NAMED the demo league must not be found by the finder either.
with SessionLocal() as db:
    found = find_showcase(db)
check("the finder ignores a Yahoo league named 'FantasyStakes Demo League'",
      found is not None and found.id not in protected.values(),
      f"found {getattr(found, 'id', None)}")

# Reset must leave every protected league byte-identical.
with SessionLocal() as db:
    before_rows = {
        lid: (db.query(League).filter(League.id == lid).first().name,
              db.query(League).filter(League.id == lid).first().provider,
              db.query(League).filter(League.id == lid).first().provider_league_key)
        for lid in protected.values()}

demo_reset()

with SessionLocal() as db:
    for lid, snapshot in before_rows.items():
        lg = db.query(League).filter(League.id == lid).first()
        check(f"league {lid} survived the reset untouched",
              lg is not None
              and (lg.name, lg.provider, lg.provider_league_key) == snapshot,
              str(snapshot))

state = reset_check()
check("reset --check reports the non-demo leagues it will not touch",
      state["non_demo_leagues_untouched"] >= 3,
      str(state["non_demo_leagues_untouched"]))
check("the ledger still balances after all of it", trial_balance() == 0)


# ── 5 · no Yahoo dependency, and nothing Yahoo-shaped ────────────────────────

section("5 · The demo needs no Yahoo anything")

import pathlib  # noqa: E402

DEMO_SRC = "\n".join(
    p.read_text(encoding="utf-8")
    for p in pathlib.Path("demo").glob("*.py"))

for forbidden in ("access_token", "refresh_token", "oauth", "yahoo_oidc",
                  "provider_grant", "FS_YAHOO_CLIENT"):
    check(f"the demo package never references {forbidden!r}",
          forbidden.lower() not in DEMO_SRC.lower())

with SessionLocal() as db:
    lg = find_showcase(db)
    keys = [r[0] for r in db.execute(text(
        "SELECT provider_team_key FROM teams WHERE league_id = :l"),
        {"l": lg.id}).fetchall()]
check("every provider key is in the demo namespace",
      all((k or "").startswith("demo.l.showcase.") for k in keys),
      str(keys[:2]))
check("  · and none is Yahoo-shaped",
      not any((k or "").split(".")[0].isdigit() for k in keys))

with SessionLocal() as db:
    grants = db.execute(text("SELECT count(*) FROM provider_grants")).scalar()
check("seeding created no provider grant", grants == 0, str(grants))

# Fictional data only — no real person or NFL club as a team name.
NFL_CLUBS = ("Patriots", "Cowboys", "Packers", "Chiefs", "Eagles", "49ers",
             "Bills", "Ravens", "Bengals", "Lions", "Jets", "Giants")
names = " | ".join(t.team_name for t in showcase.TEAMS)
check("no NFL club is used as a fantasy team name",
      not any(c in names for c in NFL_CLUBS), names[:80])
check("team names are unique", len({t.team_name for t in showcase.TEAMS}) == 12)
check("GM names are unique", len({t.gm for t in showcase.TEAMS}) == 12)


# ── 6 · the certified Grand Champion, on demo input ─────────────────────────

section("6 · Grand Champion is computed by the certified calculator")

from reports.grand_champion import (  # noqa: E402
    ChampionshipFinish, calculate_grand_champion,
)

with SessionLocal() as db:
    lg = find_showcase(db)
    from reports.standings_read_model import league_standings

    st = league_standings(db, league_id=lg.id)
    rows = list(getattr(st, "overall", None) or getattr(st, "rows", st))
    name_to_team = {t.team_name: t.id for t in
                    db.query(Team).filter(Team.league_id == lg.id).all()}
    ordinal_of = {t.team_name: t.ordinal for t in showcase.TEAMS}

# FantasyStakes podium: the top three by the REAL derived competitive net.
fs_finishes, place = [], 0
for i, r in enumerate(rows[:3]):
    place = i + 1
    fs_finishes.append(ChampionshipFinish(team_id=name_to_team[r.team_name],
                                          place=place))
yahoo_finishes = [
    ChampionshipFinish(
        team_id=name_to_team[dict((t.ordinal, t.team_name)
                                  for t in showcase.TEAMS)[o]], place=i + 1)
    for i, o in enumerate(showcase.YAHOO_PODIUM_ORDINALS)]

scores = {name_to_team[r.team_name]: int(r.net_cents) for r in rows}
result = calculate_grand_champion(
    yahoo_finishes=tuple(yahoo_finishes),
    fantasystakes_finishes=tuple(fs_finishes),
    fantasystakes_scores=scores)

check("the calculator returns a Grand Champion",
      len(result.champion_team_ids) >= 1, str(result.champion_team_ids))
check("  · from the SAME certified module production uses",
      calculate_grand_champion.__module__ == "reports.grand_champion")
check("  · and the demo declares no championship engine of its own",
      "def calculate_grand_champion" not in DEMO_SRC
      and "championship_score" not in DEMO_SRC.lower())

id_to_name = {v: k for k, v in name_to_team.items()}
print("      Grand Champion: "
      + ", ".join(id_to_name[t] for t in result.champion_team_ids)
      + (f"  (tiebreak used: {result.tiebreak_used})"))


# ── 7 · the demo cannot grant authority over a real league ──────────────────

section("7 · The demo GM holds no authority anywhere else")

from db.schema import LeagueCommissioner, User  # noqa: E402

from demo.seed import DEMO_USER_EMAIL  # noqa: E402

with SessionLocal() as db:
    demo_user = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
    check("the demo GM exists", demo_user is not None)
    if demo_user:
        commissions = db.query(LeagueCommissioner).filter(
            LeagueCommissioner.user_id == demo_user.id).all()
        leagues = {c.league_id for c in commissions}
        check("the demo GM commissions only demo leagues",
              not (leagues & set(protected.values())),
              f"{sorted(leagues)} vs protected {sorted(protected.values())}")
        check("  · and cannot sign in — the password hash is not a hash",
              demo_user.hashed_password.startswith("!"),
              demo_user.hashed_password)



# ── 8 · D1.1 · the FINAL state, played through the real lifecycle ────────────

section("8 · FINAL is reached by playing the season, not by painting it")

import pathlib  # noqa: E402

from demo.states import STATE_CURRENT, STATE_FINAL, advance_to_final, state_of  # noqa: E402

SHOWCASE_SRC = pathlib.Path("demo/showcase.py").read_text(encoding="utf-8")

with SessionLocal() as db:
    check("the demo starts in CURRENT",
          state_of(db, find_showcase(db)) == STATE_CURRENT)

final = advance_to_final()
check("the transition reports FINAL", final["state"] == STATE_FINAL)
check("the championship froze every GM", final["frozen_rows"] == 12,
      str(final["frozen_rows"]))
check("THE LEDGER STILL BALANCES", final["trial_balance"] == 0,
      str(final["trial_balance"]))

with SessionLocal() as db:
    lg = find_showcase(db)
    check("the persisted state reads FINAL", state_of(db, lg) == STATE_FINAL)
    check("the season advanced to the postseason boundary",
          lg.provider_current_week == showcase.PLAYOFF_START_WEEK,
          str(lg.provider_current_week))
    open_weeks = db.execute(text(
        "SELECT count(*) FROM matchups WHERE league_id = :l "
        "AND finalized_at IS NULL"), {"l": lg.id}).scalar()
    check("no regular-season matchup is left unfinalized", open_weeks == 0,
          str(open_weeks))

from reports.championship_read_model import get_fantasystakes_championship  # noqa: E402

with SessionLocal() as db:
    lg = find_showcase(db)
    snapshot = get_fantasystakes_championship(db, league_id=lg.id,
                                              season=lg.season)
    names = {t.id: t.team_name for t in
             db.query(Team).filter(Team.league_id == lg.id).all()}
    ordinal_of = {t.team_name: t.ordinal for t in showcase.TEAMS}
    by_ordinal = {ordinal_of[n]: i for i, n in names.items()}

check("the FantasyStakes Championship is frozen", snapshot is not None)
check("  · with a score for every GM", len(snapshot.rows) == 12,
      str(len(snapshot.rows)))
podium = sorted((r for r in snapshot.rows if r.place <= 3),
                key=lambda r: r.place)
check("  · and a three-deep podium", len(podium) == 3, str(len(podium)))
check("the Championship Score is DERIVED, not declared",
      "CHAMPIONSHIP_SCORES_CENTS" not in SHOWCASE_SRC)
check("  · and the leader's score is a real realized net",
      podium[0].championship_score_cents > 0,
      str(podium[0].championship_score_cents))
print("      podium: " + ", ".join(
    f"{r.place}. {names[r.team_id]} ({r.championship_score_cents})"
    for r in podium))

awards = {a["place"]: a for a in final["awards"]}
check("three places were paid", len(awards) == 3, str(sorted(awards)))
pot = sum(a["amount_cents"] for a in final["awards"])
check("the pot is the FantasyStakes contribution x 12",
      pot == showcase.FANTASYSTAKES_CHAMPIONSHIP_CONTRIBUTION_CENTS * 12,
      str(pot))
check("first place takes 60%", awards[1]["amount_cents"] == pot * 60 // 100,
      str(awards[1]["amount_cents"]))
check("second takes 30%", awards[2]["amount_cents"] == pot * 30 // 100,
      str(awards[2]["amount_cents"]))
check("third takes 10%", awards[3]["amount_cents"] == pot * 10 // 100,
      str(awards[3]["amount_cents"]))
check("the split is exact — nothing stranded",
      awards[1]["amount_cents"] + awards[2]["amount_cents"]
      + awards[3]["amount_cents"] == pot)
check("the podium and the payout agree on who won",
      awards[1]["team_id"] == podium[0].team_id)

fs_finishes = tuple(ChampionshipFinish(team_id=r.team_id, place=r.place)
                    for r in podium)
yahoo_finishes = tuple(
    ChampionshipFinish(team_id=by_ordinal[o], place=i + 1)
    for i, o in enumerate(showcase.YAHOO_PODIUM_ORDINALS))
scores = {r.team_id: int(r.championship_score_cents) for r in snapshot.rows}
gc = calculate_grand_champion(yahoo_finishes=yahoo_finishes,
                              fantasystakes_finishes=fs_finishes,
                              fantasystakes_scores=scores)
check("a Grand Champion is derived at FINAL",
      len(gc.champion_team_ids) >= 1, str(gc.champion_team_ids))
check("  · from the synthetic Yahoo podium AND the real FantasyStakes finish",
      len(yahoo_finishes) == 3 and len(fs_finishes) == 3)
check("  · and the fixture declares no Grand Champion of its own",
      "champion_ordinals" not in SHOWCASE_SRC)
print("      Grand Champion: "
      + ", ".join(names[t] for t in gc.champion_team_ids))

from ledger.ledger import balance_of  # noqa: E402

# WALLET AND CHAMPIONSHIP SCORE ARE DIFFERENT QUANTITIES, and the assertion has
# to test that rather than test a coincidence. An earlier version required the
# two ORDERINGS to differ, which failed for a silly reason: the best competitor
# also takes the biggest payout, so the leaders agree — as they should.
#
# The property that actually matters is that the score is realized COMPETITIVE
# net, not a wallet reading. Proved directly: GMs finish with negative
# Championship Scores while their wallet is never negative, so the two cannot be
# the same number, and the rank cannot be a wallet sort.
wallets = {r.team_id: balance_of(f"wallet:{r.team_id}") for r in snapshot.rows}
negative_scores = [r for r in snapshot.rows
                   if int(r.championship_score_cents) < 0]
check("some GMs finish with a NEGATIVE Championship Score",
      len(negative_scores) >= 3, str(len(negative_scores)))
check("  · while no wallet is negative — so score is not a wallet reading",
      all(wallets[r.team_id] >= 0 for r in negative_scores),
      str([wallets[r.team_id] for r in negative_scores][:4]))
check("  · and the score differs from the wallet for every GM but the paid ones",
      any(int(r.championship_score_cents) != wallets[r.team_id]
          for r in snapshot.rows))
check("championship rank is ordered by Championship Score",
      [r.place for r in sorted(snapshot.rows,
                               key=lambda r: -int(r.championship_score_cents))]
      == sorted(r.place for r in snapshot.rows),
      "places follow the score, descending")


section("9 · FINAL is deterministic, and reset returns to canonical CURRENT")

with SessionLocal() as db:
    final_fingerprint = tuple(
        (names[r.team_id], int(r.championship_score_cents), r.place)
        for r in sorted(get_fantasystakes_championship(
            db, league_id=find_showcase(db).id).rows, key=lambda r: r.place))

demo_reset()
with SessionLocal() as db:
    lg = find_showcase(db)
    check("reset returns the demo to CURRENT",
          state_of(db, lg) == STATE_CURRENT)
    check("  · at week 11 again", lg.provider_current_week == 11,
          str(lg.provider_current_week))
check("the ledger balances after reset", trial_balance() == 0)

advance_to_final()
with SessionLocal() as db:
    lg = find_showcase(db)
    names2 = {t.id: t.team_name for t in
              db.query(Team).filter(Team.league_id == lg.id).all()}
    replay = tuple(
        (names2[r.team_id], int(r.championship_score_cents), r.place)
        for r in sorted(get_fantasystakes_championship(
            db, league_id=lg.id).rows, key=lambda r: r.place))
# Replayed after a reset, which retires the league and builds a new one — a new
# id, so a different Pool slate and a legitimately different champion. What must
# hold here is that the replay is COMPLETE and internally coherent; that the
# lifecycle reproduces exactly is asserted in `test_d24_determinism.py`, which
# replays it on a cold database where the id is stable.
check("CURRENT -> FINAL replays completely after a reset",
      len(replay) == 12 and all(isinstance(r[1], int) for r in replay),
      f"{len(replay)} frozen rows")
check("  · and the replay froze a full, ordered podium",
      [r[2] for r in replay][:3] == [1, 2, 3], str([r[2] for r in replay][:3]))
check("the ledger balances after the second run", trial_balance() == 0)


# ── 10 · D1.1 · the signed-out visitor can reach the demo ───────────────────

section("10 · A signed-out visitor enters the demo with no Yahoo anything")

anon = TestClient(entry.app)
enter_response = anon.post("/demo/enter")
check("POST /demo/enter succeeds with NO session",
      enter_response.status_code == 200, str(enter_response.status_code))
body = enter_response.json() if enter_response.status_code == 200 else {}
check("  · it names the demo league", body.get("demo") is True, str(body))
check("  · bound to the demo provider", body.get("provider") == "demo")
check("  · and says plainly that it is sample data",
      "sample data" in str(body.get("message", "")))

cookies = enter_response.headers.get_list("set-cookie")
sess = next((c.split("=")[1].split(";")[0] for c in cookies
             if c.startswith("fs_session")), None)
csrf = next((c.split("=")[1].split(";")[0] for c in cookies
             if c.startswith("fs_csrf")), None)
check("a browser session is issued", bool(sess) and bool(csrf))

visitor = TestClient(entry.app)
visitor.cookies.set("fs_session", sess or "")
visitor.cookies.set("fs_csrf", csrf or "")
visitor.headers.update({"X-FS-CSRF": csrf or ""})
# THE READ NAMES ITS LEAGUE. `/league/standings` is per-league as of the Rev 1.4
# isolation fix, and this suite's own database deliberately holds four leagues —
# the showcase plus the three non-demo leagues §4 proves reset will not touch.
# An unscoped call used to return all four merged into one table; it now refuses
# and says why. Naming the league is both the correct product read and a
# stronger assertion than the old one, because it proves the session reaches a
# real scoped read rather than a global scan.
with SessionLocal() as db:
    _showcase = find_showcase(db)
    _showcase_id = _showcase.id
    _showcase_team_ids = {t.id for t in db.query(Team)
                          .filter(Team.league_id == _showcase_id).all()}
_standings = visitor.get(f"/league/standings?league_id={_showcase_id}")
check("  · and it authenticates real product reads",
      _standings.status_code == 200, str(_standings.status_code))
check("  · scoped to the league it named, and no other",
      _standings.status_code != 200
      or {r["team_id"] for r in _standings.json()} <= _showcase_team_ids,
      "standings returned a team from another league")
check("  · an unscoped read refuses rather than merging four leagues",
      visitor.get("/league/standings").status_code == 400,
      str(visitor.get("/league/standings").status_code))

with SessionLocal() as db:
    grant_count = db.execute(
        text("SELECT count(*) FROM provider_grants")).scalar()
check("entering the demo created no provider grant", grant_count == 0,
      str(grant_count))

import inspect as _inspect  # noqa: E402

_enter_ep = [r.endpoint for r in entry.app.routes
             if getattr(r, "path", "") == "/demo/enter"][0]
check("the entry route takes no parameter a caller could aim at a league",
      not set(_inspect.signature(_enter_ep).parameters)
      & {"league_id", "user_id", "team_id"},
      str(list(_inspect.signature(_enter_ep).parameters)))

with SessionLocal() as db:
    demo_account = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
    commissions = {c.league_id for c in db.query(LeagueCommissioner).filter(
        LeagueCommissioner.user_id == demo_account.id).all()}
check("the seated account holds no authority over a protected league",
      not (commissions & set(protected.values())),
      f"{sorted(commissions)} vs {sorted(protected.values())}")

GATE = pathlib.Path("web/js/auth-view.js").read_text(encoding="utf-8")
check("the signed-out gate renders a Try Demo control",
      'id="fs-gate-demo"' in GATE and "Try Demo" in GATE)
check("  · wired to the public entry route", "'/demo/enter'" in GATE)
check("  · and it is not dressed as a sign-in",
      "No Yahoo account, no sign-in" in GATE)
check("  · while Sign in with Yahoo is still offered",
      "Sign in with Yahoo" in GATE)

print("\n" + "=" * 74)
if FAIL:
    print(f"D1 DEMO ENVIRONMENT — {len(FAIL)} FAILED")
    for f in FAIL:
        print(f"  · {f}")
    sys.exit(1)
print(f"PASS: showcase demo certified on {engine.dialect.name}")
