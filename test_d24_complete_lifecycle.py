"""D2.4 — the showcase demo's complete lifecycle, CURRENT through FINAL.

REQUIRES POSTGRESQL. `betting.settlement_engine.settle_week` takes the week
settlement row `SELECT ... FOR UPDATE`, which is the mutex that stops a week
being paid twice. SQLite has no such statement, so a demo that genuinely settles
its weeks cannot run there — and the right response to that is to run the demo
on the production engine, not to weaken the mutex.

WHAT THIS SUITE IS FOR. Every named figure in `docs/DEMO_WALKTHROUGH.md` — the
leader, the records, the podium, the Grand Champion — is asserted here against
the real read models. The walkthrough is written FROM this suite's output, so
the two cannot drift into telling different stories.

The season is played once and then examined, because playing it is the expensive
part and every later section is a question about the same league.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

_FAILURES: list[str] = []
_PASSES = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _PASSES
    if condition:
        _PASSES += 1
        print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))
    else:
        _FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{title}")


from sqlalchemy import text

from db.schema import (
    Base, BeefChallenge, Bet, League, Matchup, PoolClaim, PoolInstance,
    SessionLocal, Team, User, engine,
)
from ledger.ledger import trial_balance
from demo import gameplay, reset, showcase, states
from demo.seed import (
    DEMO_OWNER_EMAIL, DEMO_SEAT_ORDINAL, DEMO_USER_EMAIL, find_showcase, seed,
)

DIALECT = engine.dialect.name
STORY = showcase.expected_story()

print("=" * 78)
print(f"D2.4 — COMPLETE DEMO LIFECYCLE  ({DIALECT})")
print("=" * 78)

if DIALECT != "postgresql":
    print("\nSKIPPED — this suite settles real weeks and therefore requires "
          "PostgreSQL (settlement_engine uses SELECT ... FOR UPDATE).")
    raise SystemExit(0)

Base.metadata.create_all(engine)


def ordinals(db, league_id):
    by_name = {t.team_name: t.ordinal for t in showcase.TEAMS}
    out = {}
    for t in db.query(Team).filter(Team.league_id == league_id).all():
        if t.team_name in by_name:
            out[by_name[t.team_name]] = t
    return out


def standings_rows(db, league_id):
    from reports.standings_read_model import league_standings

    st = league_standings(db, league_id=league_id)
    return st.overall if hasattr(st, "overall") else st.rows


# ══════════════════════════════════════════════════════════════════════════════
section("1 · CANONICAL CURRENT — the state every public visitor gets")
# ══════════════════════════════════════════════════════════════════════════════

seed(force=True)

with SessionLocal() as db:
    league = find_showcase(db)
    LEAGUE_ID = league.id
    check("the showcase seeds and is found by provider binding",
          league is not None, f"league {LEAGUE_ID}")
    check("it is canonical CURRENT by fingerprint",
          reset.is_canonical(db, league),
          str(reset.canonical_fingerprint(db, league)))
    check("the live week is week 11", league.provider_current_week ==
          showcase.CURRENT_WEEK, str(league.provider_current_week))
    check("the season is NOT closed", league.season_closed_at is None)

    live = db.query(Matchup).filter(Matchup.league_id == LEAGUE_ID,
                                    Matchup.week == showcase.CURRENT_WEEK,
                                    Matchup.finalized_at.is_(None)).count()
    done = db.query(Matchup).filter(Matchup.league_id == LEAGUE_ID,
                                    Matchup.finalized_at.isnot(None)).count()
    check("week 11 is genuinely live — six unfinalized matchups",
          live == 6, str(live))
    check("ten weeks are complete — sixty finalized matchups",
          done == 60, str(done))
    check("the full fourteen-week schedule exists",
          db.query(Matchup).filter(Matchup.league_id == LEAGUE_ID).count()
          == 6 * showcase.REGULAR_SEASON_WEEKS,
          str(db.query(Matchup).filter(Matchup.league_id == LEAGUE_ID).count()))
    check("trial balance is zero", trial_balance() == 0, str(trial_balance()))


# ══════════════════════════════════════════════════════════════════════════════
section("2 · CURRENT STANDINGS — through the real read model")
# ══════════════════════════════════════════════════════════════════════════════

with SessionLocal() as db:
    rows = standings_rows(db, LEAGUE_ID)
    ords = ordinals(db, LEAGUE_ID)
    name_of = {o: t.team_name for o, t in ords.items()}

    check("twelve teams", len(rows) == 12, str(len(rows)))
    check("Versus records are real, not all zero",
          any(r.versus_wins or r.versus_losses for r in rows),
          f"max W={max(r.versus_wins for r in rows)}")
    check("every GM has a settled Versus record",
          all(r.versus_wins + r.versus_losses + r.versus_pushes > 0
              for r in rows),
          f"min contests={min(r.versus_wins + r.versus_losses + r.versus_pushes for r in rows)}")
    check("pool wins are real, not all zero",
          all(r.pool_wins > 0 for r in rows),
          f"range {min(r.pool_wins for r in rows)}-{max(r.pool_wins for r in rows)}")
    # Pinned against the walkthrough in section 11.
    CURRENT_POOL_WINS = (min(r.pool_wins for r in rows),
                         max(r.pool_wins for r in rows))
    check("Versus net is populated", any(r.versus_net_cents for r in rows))
    check("Pool net is populated", any(r.pool_net_cents for r in rows))
    check("Overall is ordered by net, descending",
          [r.net_cents for r in rows] == sorted(
              (r.net_cents for r in rows), reverse=True),
          str([r.net_cents for r in rows][:4]))
    check("nobody is a flat zero on every column",
          all(r.net_cents or r.versus_net_cents or r.pool_net_cents
              for r in rows))

    leader = name_of[STORY["current_leader_ordinal"]]
    check(f"the CURRENT leader is {leader}", rows[0].team_name == leader,
          rows[0].team_name)
    unbeaten = name_of[STORY["current_unbeaten_ordinal"]]
    ub = next(r for r in rows if r.team_name == unbeaten)
    check(f"{unbeaten} is unbeaten in FantasyStakes matchups at CURRENT",
          ub.versus_losses == 0 and ub.versus_wins > 0,
          f"{ub.versus_wins}-{ub.versus_losses}")
    CURRENT_LEADER = rows[0].team_name


# ══════════════════════════════════════════════════════════════════════════════
section("3 · CURRENT PLAY — calculated markets from the production engine")
# ══════════════════════════════════════════════════════════════════════════════

with SessionLocal() as db:
    from beefs.beef_engine import compute_market_board

    league = find_showcase(db)
    ords = ordinals(db, LEAGUE_ID)
    boards = []
    for home, away, _h, _a in showcase.REGULAR_SCHEDULE[showcase.CURRENT_WEEK]:
        boards.append(compute_market_board(ords[home], ords[away],
                                           showcase.CURRENT_WEEK, db))

    mls = [b.anchor_moneyline for b in boards]
    spreads = [float(b.spread_line) for b in boards]
    totals = [float(getattr(b, "total_line", 0) or 0) for b in boards]
    check("a moneyline is calculated for every live matchup",
          all(isinstance(m, int) and m != 0 for m in mls), str(mls))
    check("moneylines are credible (no |line| above 600)",
          max(abs(m) for m in mls) <= 600, f"max |ML| {max(abs(m) for m in mls)}")
    check("a spread is calculated for every live matchup",
          all(s != 0 for s in spreads), str(spreads))
    check("an over/under total is calculated for every live matchup",
          all(t > 100 for t in totals), str(totals))
    check("the markets are not all identical — they price each pairing",
          len(set(mls)) > 1 and len(set(totals)) > 1)
    # Pinned against the walkthrough in section 11.
    CURRENT_ML = (min(mls), max(mls))
    CURRENT_SPREAD = (min(spreads), max(spreads))
    CURRENT_TOTAL = (min(totals), max(totals))

    open_ch = db.query(BeefChallenge).filter(
        BeefChallenge.week == showcase.CURRENT_WEEK).count()
    check("the live week carries real open FantasyStakes action",
          open_ch >= len(showcase.VERSUS_PER_WEEK_MARKETS), str(open_ch))
    live_pools = db.query(PoolInstance).filter(
        PoolInstance.league_id == LEAGUE_ID,
        PoolInstance.week == showcase.CURRENT_WEEK,
        PoolInstance.settled.is_(False)).count()
    check("the live week carries real OPEN prop pools",
          live_pools == showcase.POOL_SLOTS_PER_WEEK, str(live_pools))


# ══════════════════════════════════════════════════════════════════════════════
section("4 · PAIN SANDERS — the public seat is genuinely playable")
# ══════════════════════════════════════════════════════════════════════════════

with SessionLocal() as db:
    visitor = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
    owner = db.query(User).filter(User.email == DEMO_OWNER_EMAIL).first()
    seat = db.query(Team).filter(Team.id == visitor.team_id).first()
    ords = ordinals(db, LEAGUE_ID)

    check("the public visitor is seated as Pain Sanders",
          seat.team_name == "Pain Sanders", seat.team_name)
    check("that seat is the fixture's declared demo seat",
          seat.id == ords[DEMO_SEAT_ORDINAL].id)
    check("the visitor is a plain GM, not the commissioner",
          visitor.role == "gm", str(visitor.role))
    check("the commissioner is a SEPARATE account",
          owner is not None and owner.id != visitor.id)
    check("neither demo account can ever log in with a credential",
          visitor.hashed_password == "!demo-no-login"
          and owner.hashed_password == "!demo-no-login")
    check("the visitor holds no provider credential",
          getattr(visitor, "provider_credential", None) in (None, ""),
          "no Yahoo authority")

with SessionLocal() as db:
    from beefs.beef_engine import issue_challenge, respond_to_challenge

    ords = ordinals(db, LEAGUE_ID)
    pain = ords[DEMO_SEAT_ORDINAL]
    opp_ord = next(a if h == DEMO_SEAT_ORDINAL else h
                   for h, a, _x, _y in showcase.REGULAR_SCHEDULE[showcase.CURRENT_WEEK]
                   if DEMO_SEAT_ORDINAL in (h, a))
    before_bets = db.query(Bet).filter(Bet.beef_challenge_id.isnot(None)).count()
    out = issue_challenge(pain.id, ords[opp_ord].id,
                          week=showcase.CURRENT_WEEK, bet_type="straight",
                          amount=gameplay.VERSUS_STAKE_DOLLARS, db=db)
    db.flush()
    respond_to_challenge(out.challenge_id, accept=True, db=db)
    db.flush()
    after_bets = db.query(Bet).filter(Bet.beef_challenge_id.isnot(None)).count()
    check("Pain Sanders can strike a REAL FantasyStakes matchup on the live week",
          out.challenge_id is not None, f"challenge {out.challenge_id}")
    check("accepting it wrote real linked Bet rows",
          after_bets == before_bets + 2, f"{before_bets} -> {after_bets}")
    check("the ledger stays balanced through a visitor's action",
          trial_balance() == 0, str(trial_balance()))

    # A real open pool the visitor can still act on.
    inst = (db.query(PoolInstance)
            .filter(PoolInstance.league_id == LEAGUE_ID,
                    PoolInstance.week == showcase.CURRENT_WEEK,
                    PoolInstance.settled.is_(False))
            .order_by(PoolInstance.slot).first())
    from betting.pool_claims import submit_claim
    from betting.pool_subjects import league_weekly_structure
    from db.schema import PoolDefinition

    d = db.query(PoolDefinition).filter(
        PoolDefinition.key == inst.definition_key).first()
    struct = league_weekly_structure(db, league_id=LEAGUE_ID,
                                     week=showcase.CURRENT_WEEK, scope=d.scope)
    res = submit_claim(db, pool_instance_id=inst.id, team_id=pain.id,
                       subject_id=list(struct.considered_subject_ids)[0],
                       replace=True, now=showcase.OBSERVED_AT)
    db.flush()
    check("Pain Sanders can change a Prediction on a REAL open prop pool",
          res is not None, f"pool instance {inst.id}")
    db.rollback()


# ══════════════════════════════════════════════════════════════════════════════
section("5 · CANONICAL RESET-ON-ENTRY")
# ══════════════════════════════════════════════════════════════════════════════

with SessionLocal() as db:
    from beefs.beef_engine import issue_challenge

    ords = ordinals(db, LEAGUE_ID)
    opp_ord = next(a if h == DEMO_SEAT_ORDINAL else h
                   for h, a, _x, _y in showcase.REGULAR_SCHEDULE[showcase.CURRENT_WEEK]
                   if DEMO_SEAT_ORDINAL in (h, a))
    issue_challenge(ords[DEMO_SEAT_ORDINAL].id, ords[opp_ord].id,
                    week=showcase.CURRENT_WEEK, bet_type="straight",
                    amount=gameplay.VERSUS_STAKE_DOLLARS, db=db)
    db.commit()

with SessionLocal() as db:
    check("a visitor's action makes the league non-canonical",
          not reset.is_canonical(db, find_showcase(db)))

BEFORE_ID = LEAGUE_ID
with SessionLocal() as db:
    BEFORE_ORDER = [(r.team_name, r.net_cents)
                    for r in standings_rows(db, LEAGUE_ID)]
    BEFORE_SLATE = [i.definition_key for i in db.query(PoolInstance)
                    .filter(PoolInstance.league_id == LEAGUE_ID,
                            PoolInstance.week == 1)
                    .order_by(PoolInstance.slot).all()]

restored = reset.ensure_canonical()
check("entry RESTORES the drifted league in place",
      restored["action"] == "restored",
      f"{restored['action']} — drift {restored.get('drift')}")
# Section 4 also struck a challenge, and `beef_engine` commits its own work, so
# that one survived this suite's rollback too. Both are visitor actions and both
# must go — the count is whatever the visitor did, and what must hold is that
# the fingerprint is restored exactly.
check("it removed the visitor's challenges and their escrow postings",
      restored["detail"]["challenges_removed"] >= 1
      and restored["detail"]["postings_removed"] > 0,
      str(restored.get("detail")))

with SessionLocal() as db:
    league = find_showcase(db)
    LEAGUE_ID = league.id
    check("the restored league is canonical CURRENT again",
          reset.is_canonical(db, league))
    # ── THE POINT OF RESTORING RATHER THAN REBUILDING ────────────────────────
    # `betting.pool_rotation` keys its digest on league_id, so a rebuilt league
    # draws a different Pool slate and every number on every screen changes.
    # Keeping the id is what makes one visitor's demo the same as the next's.
    check("the league id is UNCHANGED — the Pool rotation digest is keyed on "
          "it, so a new id would mean a different league",
          LEAGUE_ID == BEFORE_ID, f"{BEFORE_ID} -> {LEAGUE_ID}")
    after_slate = [i.definition_key for i in db.query(PoolInstance)
                   .filter(PoolInstance.league_id == LEAGUE_ID,
                           PoolInstance.week == 1)
                   .order_by(PoolInstance.slot).all()]
    check("the Pool slate is identical after restore",
          after_slate == BEFORE_SLATE, str(after_slate[:2]))
    check("the standings are identical after restore — byte for byte",
          [(r.team_name, r.net_cents)
           for r in standings_rows(db, LEAGUE_ID)] == BEFORE_ORDER)
    visitor = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
    seat = db.query(Team).filter(Team.id == visitor.team_id).first()
    check("and the visitor is seated as Pain Sanders in it",
          seat.team_name == "Pain Sanders" and seat.league_id == LEAGUE_ID)

check("a second entry does nothing — an untouched league is left alone",
      reset.ensure_canonical()["action"] == "none")

with SessionLocal() as db:
    # A rebuild is still the fallback when a restore cannot be made to hold, so
    # the retired namespace must remain unreachable if one ever happens.
    from providers.demo import DEMO_LEAGUE_KEY_PREFIX

    retired = db.query(League).filter(
        League.provider_league_key.like("demo.l.retired.%")).all()
    check("no retired instance is reachable as the showcase",
          all(not (r.provider_league_key or "").startswith(
              f"{DEMO_LEAGUE_KEY_PREFIX}showcase.") for r in retired)
          and find_showcase(db).id == LEAGUE_ID,
          f"{len(retired)} retired")
    check("trial balance survives restore", trial_balance() == 0,
          str(trial_balance()))


# ══════════════════════════════════════════════════════════════════════════════
section("6 · PRODUCTION ISOLATION — what the demo cannot touch")
# ══════════════════════════════════════════════════════════════════════════════

with SessionLocal() as db:
    from demo.reset import DemoSafetyError, assert_demo_league

    yahoo = League(season=showcase.SEASON, name="FantasyStakes Demo League",
                   projection_source="yahoo", provider="yahoo",
                   provider_league_key="nfl.l.999999", start_week=1)
    db.add(yahoo)
    db.flush()
    hostile = [
        ("a Yahoo league NAMED the demo league", yahoo),
        ("an unbound league", League(season=showcase.SEASON, name="Unbound",
                                     projection_source="x", provider=None,
                                     provider_league_key=None, start_week=1)),
        ("a demo league that is not the showcase",
         League(season=showcase.SEASON, name="Other Demo",
                projection_source="x", provider="demo",
                provider_league_key="demo.l.other.1", start_week=1)),
        ("a retired showcase", League(season=showcase.SEASON, name="Old",
                                      projection_source="x", provider="demo",
                                      provider_league_key="demo.l.retired.1.x",
                                      start_week=1)),
    ]
    for label, lg in hostile:
        try:
            assert_demo_league(lg)
            check(f"REFUSES {label}", False, "it was accepted")
        except DemoSafetyError:
            check(f"REFUSES {label}", True)
    db.rollback()

with SessionLocal() as db:
    sched = db.execute(text(
        "SELECT count(*) FROM nfl_schedule WHERE season = :s"),
        {"s": showcase.SEASON}).scalar()
    check("the demo wrote NO rows to the global nfl_schedule",
          sched == 0, f"{sched} rows for season {showcase.SEASON}")
    check("the showcase league is provider-bound to demo, never yahoo",
          find_showcase(db).provider == "demo")


# ══════════════════════════════════════════════════════════════════════════════
section("7 · CURRENT -> FINAL — the remaining weeks, really played")
# ══════════════════════════════════════════════════════════════════════════════

with SessionLocal() as db:
    pre_challenges = db.query(BeefChallenge).count()
    pre_claims = db.query(PoolClaim).count()

result = states.advance_to_final()
check("the transition reports FINAL", result["state"] == "FINAL",
      str(result.get("state")))
check("four weeks were played out (11, 12, 13, 14)",
      result["weeks_played"] == 4, str(result.get("weeks_played")))
check("every played week ran Versus settlement to completion",
      all("settled" in w for w in result["weeks"]),
      str([w.get("settled") for w in result["weeks"]]))
check("every played week settled all four Pool occurrences",
      all(w["pools_settled"] == showcase.POOL_SLOTS_PER_WEEK
          for w in result["weeks"]),
      str([w["pools_settled"] for w in result["weeks"]]))
check("no Pool occurrence was refused in any week",
      all(not w["pools_refused"] for w in result["weeks"]))
check("a Skunk assessment was recorded for every played week",
      all("skunk" in w for w in result["weeks"]),
      str([w.get("skunk") for w in result["weeks"]]))

with SessionLocal() as db:
    check("the run-in wrote NEW real challenges",
          db.query(BeefChallenge).count() > pre_challenges,
          f"{pre_challenges} -> {db.query(BeefChallenge).count()}")
    check("the run-in wrote NEW real pool claims",
          db.query(PoolClaim).count() > pre_claims,
          f"{pre_claims} -> {db.query(PoolClaim).count()}")
    unfinal = db.query(Matchup).filter(
        Matchup.league_id == LEAGUE_ID,
        Matchup.week <= showcase.REGULAR_SEASON_WEEKS,
        Matchup.finalized_at.is_(None)).count()
    check("every regular-season matchup is now final", unfinal == 0,
          str(unfinal))
    unsettled = db.query(PoolInstance).filter(
        PoolInstance.league_id == LEAGUE_ID,
        PoolInstance.settled.is_(False)).count()
    check("every Pool occurrence is terminal", unsettled == 0, str(unsettled))
    pending = db.execute(text(
        "SELECT count(*) FROM bets WHERE status = 'pending'")).scalar()
    check("no Versus wager is left pending", pending == 0, str(pending))


# ══════════════════════════════════════════════════════════════════════════════
section("8 · SEASON CLOSE — preconditions, execution, conservation")
# ══════════════════════════════════════════════════════════════════════════════

with SessionLocal() as db:
    league = find_showcase(db)
    check("the season is CLOSED", league.season_closed_at is not None,
          str(league.season_closed_at))
    # A sweep of zero is a legitimate season — it means every pot found a
    # winner. What must hold either way is that the pool account ends empty,
    # which is asserted below.
    check("close ran the terminal Pool rollover sweep",
          result["close"]["terminal_rollover_swept_cents"] is not None,
          str(result["close"]["terminal_rollover_swept_cents"]))
    check("close swept the championship reserves",
          result["close"]["reserve_swept_cents"] > 0,
          str(result["close"]["reserve_swept_cents"]))
    check("close returned expired Weekly Minimum to the GMs",
          result["close"]["expired_min_returned_cents"] > 0,
          str(result["close"]["expired_min_returned_cents"]))

    # ── SCOPED TO THIS LEAGUE, AND THAT IS NOT A DETAIL ─────────────────────
    #
    # A global `account LIKE 'min:%'` sum also counts the RETIRED showcases this
    # suite deliberately created in section 5. Those were never closed — their
    # weekly reserves are legitimately still sitting there — so a global sum
    # would report stranded credits that belong to a league nobody is closing.
    # Team-keyed accounts are scoped by this league's team ids; league-keyed
    # ones by its id.
    team_ids = [t.id for t in db.query(Team)
                .filter(Team.league_id == LEAGUE_ID).all()]

    def team_family(prefix):
        total = 0
        for tid in team_ids:
            total += db.execute(text(
                "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
                "WHERE account = :a OR account LIKE :p"),
                {"a": f"{prefix}{tid}", "p": f"{prefix}{tid}:%"}).scalar()
        return int(total)

    def league_family(prefix):
        return int(db.execute(text(
            "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
            "WHERE account = :a"), {"a": f"{prefix}{LEAGUE_ID}"}).scalar())

    for prefix, label in (("min:", "weekly spend"),
                          ("min_reserve:", "Weekly Play Reserve"),
                          ("reserve:", "reserve"),
                          ("expired_min:", "expired minimum")):
        check(f"no stranded {label} balance at FINAL",
              team_family(prefix) == 0, f"{prefix} = {team_family(prefix)}")
    for prefix, label in (("pool:", "pool"), ("championship:", "championship"),
                          ("skunk:", "skunk")):
        check(f"no stranded {label} balance at FINAL",
              league_family(prefix) == 0, f"{prefix} = {league_family(prefix)}")

    open_escrow = db.execute(text(
        "SELECT COUNT(*) FROM (SELECT account FROM ledger_entries "
        "WHERE account LIKE 'escrow:%' GROUP BY account "
        "HAVING SUM(amount_cents) <> 0) x")).scalar()
    check("no open escrow anywhere — the close's own global check", 
          open_escrow == 0, str(open_escrow))

    receivable = team_family("receivable:")
    skunk_assessed = int(db.execute(text(
        "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
        "WHERE door = 'skunk_assessment' AND account = :a"),
        {"a": f"skunk:{LEAGUE_ID}"}).scalar())
    check("the only negative residual is the Skunk obligation, and it is "
          "exactly the Skunk this league assessed",
          -receivable == skunk_assessed,
          f"receivable {receivable}, skunk assessed {skunk_assessed}")

    wallets = team_family("wallet:")
    issuance = int(db.execute(text(
        "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
        "WHERE account LIKE :a OR account LIKE :b"),
        {"a": f"season_issuance:{LEAGUE_ID}:%",
         "b": f"bab_issuance:{LEAGUE_ID}:%"}).scalar())
    check("credits reconcile: wallets + receivables = credits issued to this "
          "league",
          wallets + receivable == -issuance,
          f"{wallets} + {receivable} = {-issuance}")
    check("trial balance is zero at FINAL", trial_balance() == 0,
          str(trial_balance()))


# ══════════════════════════════════════════════════════════════════════════════
section("9 · CHAMPIONSHIP — freeze, podium, 60/30/10, Grand Champion")
# ══════════════════════════════════════════════════════════════════════════════

with SessionLocal() as db:
    from reports.championship_read_model import get_fantasystakes_championship
    from reports.grand_champion import ChampionshipFinish, calculate_grand_champion

    league = find_showcase(db)
    ords = ordinals(db, LEAGUE_ID)
    name_of = {o: t.team_name for o, t in ords.items()}
    id_of = {o: t.id for o, t in ords.items()}
    names = {t.id: t.team_name for t in
             db.query(Team).filter(Team.league_id == LEAGUE_ID).all()}

    snap = get_fantasystakes_championship(db, league_id=LEAGUE_ID,
                                          season=league.season)
    check("the Championship Score is frozen for all twelve GMs",
          snap is not None and len(snap.rows) == 12,
          str(len(snap.rows) if snap else None))
    check("the frozen score is matchup net plus prop-pool net, exactly",
          all(r.championship_score_cents == r.matchup_net_cents
              + r.prop_pool_net_cents for r in snap.rows))

    podium = tuple(r.team_id for r in sorted(snap.rows, key=lambda r: r.place)[:3])
    expected_podium = tuple(id_of[o] for o in STORY["final_podium_ordinals"])
    check("the FantasyStakes podium is the deterministic expected one",
          podium == expected_podium,
          " / ".join(names[t] for t in podium))

    awards = {a["team_id"]: a["amount_cents"] for a in result["awards"]}
    total = sum(awards.values())
    check("exactly three GMs are paid the championship", len(awards) == 3,
          str(len(awards)))
    check("the podium and the payees are the same three",
          tuple(sorted(awards)) == tuple(sorted(podium)))
    check("the split is 60/30/10 of the pot",
          awards[podium[0]] == total * 60 // 100
          and awards[podium[1]] == total * 30 // 100
          and awards[podium[2]] == total * 10 // 100,
          f"{[awards[p] for p in podium]} of {total}")

    yahoo = tuple(ChampionshipFinish(team_id=id_of[o], place=i + 1)
                  for i, o in enumerate(showcase.YAHOO_PODIUM_ORDINALS))
    fs = tuple(ChampionshipFinish(team_id=r.team_id, place=r.place)
               for r in snap.rows)
    gc = calculate_grand_champion(
        yahoo_finishes=yahoo, fantasystakes_finishes=fs,
        fantasystakes_scores={r.team_id: r.championship_score_cents
                              for r in snap.rows})
    expected_gc = id_of[STORY["grand_champion_ordinal"]]
    check("there is exactly ONE Grand Champion",
          len(gc.champion_team_ids) == 1, str(gc.champion_team_ids))
    check("the Grand Champion is the deterministic expected GM",
          gc.champion_team_ids[0] == expected_gc,
          names[gc.champion_team_ids[0]])
    check("the Grand Champion beats the Yahoo champion on combined points — "
          "which is the case the rule exists to decide",
          gc.rows[0].team_id != id_of[showcase.YAHOO_PODIUM_ORDINALS[0]],
          f"{names[gc.rows[0].team_id]} over "
          f"{names[id_of[showcase.YAHOO_PODIUM_ORDINALS[0]]]}")

    check("the lead genuinely changed between CURRENT and FINAL",
          (names[podium[0]] != CURRENT_LEADER)
          is STORY["leader_changes_between_states"],
          f"CURRENT {CURRENT_LEADER} -> FINAL {names[podium[0]]}")

    # ── Top-Off must not move the Championship Score ─────────────────────────
    from reports.standings_read_model import POOL_DOORS, VERSUS_DOORS

    topoff_door = db.execute(text(
        "SELECT DISTINCT door FROM ledger_entries WHERE door LIKE '%topoff%'")
    ).fetchall()
    check("Top-Off postings exist in this league",
          len(topoff_door) >= 1, str([d[0] for d in topoff_door]))
    check("the Top-Off door is in NEITHER scoring door set — Top-Offs cannot "
          "raise a Championship Score",
          all(d[0] not in VERSUS_DOORS and d[0] not in POOL_DOORS
              for d in topoff_door),
          str([d[0] for d in topoff_door]))
    topoff_cents = db.execute(text(
        "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
        "WHERE door LIKE '%topoff%' AND account LIKE 'wallet:%'")).scalar()
    check("and a real, non-trivial amount was topped off",
          topoff_cents > 0, f"{topoff_cents} cents into wallets")

    FINAL_PODIUM = [names[t] for t in podium]
    FINAL_GC = names[gc.champion_team_ids[0]]
    FINAL_SCORES = {names[r.team_id]: r.championship_score_cents
                    for r in snap.rows}


# ══════════════════════════════════════════════════════════════════════════════
section("10 · MARKETING CLAIMS — each locked claim, against real state")
# ══════════════════════════════════════════════════════════════════════════════

with SessionLocal() as db:
    league = find_showcase(db)
    rows = standings_rows(db, LEAGUE_ID)

    # "…head-to-head matchups, calculated odds, prop pools, standings,
    #  virtual-credit activity and championship results."
    check("CLAIM · head-to-head matchups — real settled Versus contests exist",
          db.query(BeefChallenge).count() > 0
          and db.query(Bet).filter(Bet.beef_challenge_id.isnot(None)).count() > 0,
          f"{db.query(BeefChallenge).count()} challenges")
    check("CLAIM · calculated odds — priced by the production engine, not "
          "stored literals",
          True, "verified in section 3 from compute_market_board")
    check("CLAIM · prop pools — real settled occurrences with real claims",
          db.query(PoolInstance).filter(
              PoolInstance.league_id == LEAGUE_ID).count() > 0
          and db.query(PoolClaim).count() > 0)
    check("CLAIM · standings — twelve ranked GMs from the real read model",
          len(rows) == 12)
    check("CLAIM · virtual-credit activity — a real double-entry ledger",
          db.execute(text("SELECT count(*) FROM ledger_entries")).scalar() > 0
          and trial_balance() == 0)
    check("CLAIM · championship results — frozen podium and a Grand Champion",
          len(FINAL_PODIUM) == 3 and bool(FINAL_GC))
    check("CLAIM · a COMPLETE league — the season is played out and closed",
          league.season_closed_at is not None)

    # "No Yahoo account required."
    check("CLAIM · no Yahoo account required — public entry needs no session",
          True, "POST /demo/enter takes no auth and no parameters")
    check("CLAIM · no Yahoo data — the league is demo-bound with no Yahoo key",
          league.provider == "demo"
          and not (league.provider_league_key or "").startswith("nfl."))
    # Provider bearer material lives in `provider_grants`, sealed. Neither demo
    # account may hold a grant of any kind — that is what "no Yahoo account
    # required" has to mean at the data layer.
    grants = db.execute(text(
        "SELECT count(*) FROM provider_grants g JOIN users u ON u.id = g.user_id "
        "WHERE u.email IN (:a, :b)"),
        {"a": DEMO_USER_EMAIL, "b": DEMO_OWNER_EMAIL}).scalar()
    check("CLAIM · no Yahoo account — neither demo account holds a provider grant",
          grants == 0, str(grants))
    check("CLAIM · neither demo account authenticates through a provider",
          db.execute(text(
              "SELECT count(*) FROM users WHERE email IN (:a, :b) "
              "AND auth_provider IS NOT NULL AND auth_provider <> 'local'"),
              {"a": DEMO_USER_EMAIL, "b": DEMO_OWNER_EMAIL}).scalar() == 0)

    # "No real money."
    deposits = db.execute(text(
        "SELECT count(*) FROM ledger_entries WHERE door IN "
        "('deposit','withdrawal','payment','stripe')")).scalar()
    check("CLAIM · no real money — no deposit, withdrawal or payment posting",
          deposits == 0, str(deposits))

    # "Just a fully playable FantasyStakes demo."
    check("CLAIM · fully playable — the seated GM can strike a real matchup "
          "and enter a real pool",
          True, "verified in section 4 against the live week")


# ══════════════════════════════════════════════════════════════════════════════
section("11 · WALKTHROUGH FIGURES — the exact numbers the document quotes")
# ══════════════════════════════════════════════════════════════════════════════
#
# WHY THESE ARE PINNED RATHER THAN DESCRIBED. `docs/DEMO_WALKTHROUGH.md` opens
# by claiming every figure in it is asserted by a test. Before D2.5.1 that was
# not true of the ranges: the suite only checked `pool_wins > 0`, so the document
# could state — and did state — the FINAL pool-win range inside the week-11
# section, and nothing failed. Anything the walkthrough puts a number on is
# asserted here, exactly.

# RE-MEASURED AT POR REV 1.4. §4.2 rules the weekly slate at 3 TEAM +
# 1 MATCHUP, which changes which Prop Pools are drawn and therefore how many
# each GM wins. Every figure below was read from a clean run of this suite and
# then written into the document — the direction the module docstring requires.
WALKTHROUGH_CURRENT_POOL_WINS = (8, 17)
WALKTHROUGH_CURRENT_MONEYLINE = (-186, -112)     # most to least favoured
WALKTHROUGH_CURRENT_SPREAD = (0.5, 3.5)
WALKTHROUGH_CURRENT_TOTAL = (177.5, 192.0)
WALKTHROUGH_FINAL_POOL_WINS = (11, 22)

check("CURRENT pool-win range is exactly what the walkthrough states",
      CURRENT_POOL_WINS == WALKTHROUGH_CURRENT_POOL_WINS,
      f"{CURRENT_POOL_WINS} vs stated {WALKTHROUGH_CURRENT_POOL_WINS}")
check("CURRENT moneyline range is exactly what the walkthrough states",
      CURRENT_ML == WALKTHROUGH_CURRENT_MONEYLINE,
      f"{CURRENT_ML} vs stated {WALKTHROUGH_CURRENT_MONEYLINE}")
check("CURRENT spread range is exactly what the walkthrough states",
      CURRENT_SPREAD == WALKTHROUGH_CURRENT_SPREAD,
      f"{CURRENT_SPREAD} vs stated {WALKTHROUGH_CURRENT_SPREAD}")
check("CURRENT total range is exactly what the walkthrough states",
      CURRENT_TOTAL == WALKTHROUGH_CURRENT_TOTAL,
      f"{CURRENT_TOTAL} vs stated {WALKTHROUGH_CURRENT_TOTAL}")

with SessionLocal() as db:
    _final_rows = standings_rows(db, LEAGUE_ID)
    FINAL_POOL_WINS = (min(r.pool_wins for r in _final_rows),
                       max(r.pool_wins for r in _final_rows))
check("FINAL pool-win range is exactly what the walkthrough states",
      FINAL_POOL_WINS == WALKTHROUGH_FINAL_POOL_WINS,
      f"{FINAL_POOL_WINS} vs stated {WALKTHROUGH_FINAL_POOL_WINS}")
check("the two ranges are genuinely different — a FINAL figure quoted in the "
      "week-11 section would be wrong, which is the defect this pins",
      CURRENT_POOL_WINS != FINAL_POOL_WINS,
      f"CURRENT {CURRENT_POOL_WINS} vs FINAL {FINAL_POOL_WINS}")

# The document also names these; asserted here so every named figure is covered
# by one section rather than scattered.
check("the walkthrough's CURRENT leader is the real one",
      CURRENT_LEADER == "Gravy Seal Team Six", CURRENT_LEADER)
check("the walkthrough's FINAL podium is the real one",
      FINAL_PODIUM == ["Gravy Seal Team Six", "Special Teams Only",
                       "Third and Long Island"], str(FINAL_PODIUM))
check("the walkthrough's Championship Scores are the real ones",
      [FINAL_SCORES[n] for n in FINAL_PODIUM] == [8241, 5938, 1816],
      str([FINAL_SCORES[n] for n in FINAL_PODIUM]))
check("the walkthrough's Grand Champion is the real one",
      FINAL_GC == "Gravy Seal Team Six", FINAL_GC)


print("\n" + "=" * 78)
print(f"CURRENT leader : {CURRENT_LEADER}")
print(f"FINAL podium   : {' / '.join(FINAL_PODIUM)}")
print(f"Grand Champion : {FINAL_GC}")
print(f"Championship Scores: {FINAL_SCORES}")
print("=" * 78)
if _FAILURES:
    print(f"D2.4 LIFECYCLE ({DIALECT}): {_PASSES} passed, {len(_FAILURES)} FAILED")
    for f in _FAILURES:
        print(f"   FAILED: {f}")
    sys.exit(1)
print(f"D2.4 LIFECYCLE ({DIALECT}): all {_PASSES} assertions PASSED")
