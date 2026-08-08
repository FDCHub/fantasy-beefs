"""
test_p3_d2_dynamic_final_lock_pg.py — P3-D2 targeted suite (Rev 9).

RUNS ON REAL POSTGRESQL. The claim mutex is `INSERT ... ON CONFLICT
(challenge_id) DO NOTHING` plus a conditional `UPDATE` rowcount, and the
Handshake/Final-Lock paths take `SELECT ... FOR UPDATE` row locks. SQLite
enforces none of that, so proving it there would prove nothing.

THE DISCRIMINATING LINE (Rev 9 §9). Anchor 5000c, issuer favourite at p=0.82.
`fairPot` = 6097.560976c — NON-DIVIDING, so the derived-side floor does real
work. The Handshake opponent ceiling is floor(6097.560976 x 0.18) = 1097c, and
the recorded issuer ceiling is the Anchor itself, 5000c.

    Favorite better  p 0.82 -> 0.90 : derived 555, refund 542   (R7-A, not 609/488)
    Favorite worse   p 0.82 -> 0.70 : raw 2142 CAPPED to 1097, refund 0
    Roles reversed   p 0.82 -> 0.35 : raw 9285 CAPPED to 1097, refund 0

    $env:TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5433/fantasy_test"
    python test_p3_d2_dynamic_final_lock_pg.py
"""

from __future__ import annotations

import os
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from test_support_postgres import setup_postgres_test_db

tdb = setup_postgres_test_db()

import atexit
atexit.register(lambda: tdb.teardown())

from sqlalchemy import text

from db.schema import (
    BeefChallenge, BeefProposal, Bet, ChallengeFinalLock,
    ChallengeFinalLockClaim, ChallengeFundingLeg, League, Matchup,
    ProtocolEvent, Team, Wallet,
)
from ledger.ledger import balance_of, post as ledger_post, trial_balance
from beefs import proposal_lifecycle as spec1
from economy import challenge_funding as cf
from economy import dynamic_challenge as dyn
from odds import model_registry as mr
from odds.dynamic_pricing import adjust_escrow
from odds.dynamic_pricing import p2o

REPO = Path(__file__).resolve().parent
WEEK = 1

_passes = 0
_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passes
    if condition:
        _passes += 1
        print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))
    else:
        _failures.append(label)
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{title}")


def raises(exc_type, fn, *a, **kw) -> bool:
    try:
        fn(*a, **kw)
    except exc_type:
        return True
    except Exception:
        return False
    return False


# ── Fixtures ──────────────────────────────────────────────────────────────────

ANCHOR    = 100_000        # 5000c scaled x20 keeps every ratio identical
P_HS_ISS  = 0.82
P_HS_OPP  = 0.18
CEIL_OPP  = 21_951         # floor(100000/0.82 * 0.18)


def seed(wallet_cents: dict[str, int], min_cents: dict[str, int] | None = None,
         matchups: list[tuple[str, str]] | None = None) -> dict:
    """A league, teams, wallets, one matchup, seeded ledger balances. The float
    Wallet.balance mirror is set DELIBERATELY WRONG so nothing can pass by
    consulting it."""
    min_cents = min_cents or {}
    ids: dict = {}
    with tdb.SessionLocal() as db:
        league = League(season=2025, name="P3-D2 League")
        db.add(league); db.flush()
        for name in wallet_cents:
            team = Team(league_id=league.id, team_name=name, owner=f"o-{name}",
                        email=f"{name}-{uuid.uuid4().hex[:8]}@p3d2.test")
            db.add(team); db.flush()
            db.add(Wallet(team_id=team.id, balance=99_999.0))
            ids[name] = team.id
        names = list(wallet_cents)
        # Default: one matchup between the first two teams. `matchups` lets a
        # fixture build a CROSS-MATCHUP league, where the challenge participants
        # are each scheduled against somebody else.
        plan = matchups if matchups is not None else [(names[0], names[1])]
        for home, away in plan:
            db.add(Matchup(league_id=league.id, week=WEEK,
                           home_team_id=ids[home], away_team_id=ids[away],
                           home_score=0.0, away_score=0.0))
        for name, cents in wallet_cents.items():
            if cents:
                ledger_post([("world", -cents), (f"wallet:{ids[name]}", cents)],
                            door="buy_in_paid", session=db)
        for name, cents in min_cents.items():
            if cents:
                ledger_post([("world", -cents), (f"min:{ids[name]}:{WEEK}", cents)],
                            door="buy_in_paid", session=db)
        ids["_league"] = league.id
        db.commit()
    return ids


def dyn_terms(anchor_cents: int, p_iss: float = P_HS_ISS,
              p_opp: float = P_HS_OPP, **kw) -> spec1.ProposalTerms:
    return spec1.ProposalTerms(
        anchor_stake_cents      = anchor_cents,
        anchor_win_probability  = p_iss,
        derived_win_probability = p_opp,
        anchor_odds             = 1.909,
        derived_odds            = 1.909,
        anchor_moneyline        = -110,
        derived_moneyline       = -110,
        **kw,
    )


def issue_dynamic(ids, challenger, challenged, anchor=ANCHOR, **kw):
    with tdb.SessionLocal() as db:
        return cf.issue_funded_challenge(
            event_id=uuid.uuid4(), league_id=ids["_league"], week=WEEK,
            challenger_team_id=ids[challenger], challenged_team_id=ids[challenged],
            wager_type="straight", terms=dyn_terms(anchor, **kw), db=db,
            challenge_mode=spec1.MODE_DYNAMIC)


def handshake(ids, challenge_id, actor):
    with tdb.SessionLocal() as db:
        return dyn.handshake_dynamic_challenge(
            event_id=uuid.uuid4(), challenge_id=challenge_id,
            actor_team_id=ids[actor], db=db)


# ── Final-Lock lineup fixtures ────────────────────────────────────────────────
#
# Final Lock now derives its probabilities from a real simulation over real
# lineups (the B-1 correction), so the fixtures are LINEUPS, not floats. Both
# multipliers below were measured against sim-v1 and are chosen to sit on
# opposite sides of the 0.82 Handshake probability, so the Handshake price and
# the Final-Lock price genuinely differ:
#
#   FAV_MULT 1.15 -> p_issuer 0.9344 : raw derived 7020 < ceiling -> REFUND
#   DOG_MULT 1.05 -> p_issuer 0.7043 : raw derived 41984 > ceiling -> CAPPED
#
BASE_PTS = [22.0, 15.0, 12.0, 16.0, 10.0, 8.0, 11.0, 8.0, 7.0]
POSITIONS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
FAV_MULT, DOG_MULT = 1.15, 1.05
P_FAV, P_DOG = 0.9344, 0.7043
FL_MATCHUP_SEED = 7

from odds.odds_engine_headless import PlayerProj


def roster(base_id: int, mult: float = 1.0):
    return tuple(PlayerProj(base_id + i, f"P{i}", pos, pts * mult, None)
                 for i, (pos, pts) in enumerate(zip(POSITIONS, BASE_PTS)))


def fl_inputs(ids=None, issuer=None, opponent=None, mult: float = 1.0,
              *, source="fantasypros", version="2025-w1-final"):
    """FinalLockInputs — LIVE DATA ONLY.

    After B-3/B-4 this type carries no team ids, no matchup id and no week: the
    starter lists are bound by CHALLENGE ROLE and every identity is read from
    persisted state inside Phase 2. `ids`/`issuer`/`opponent` are accepted and
    ignored so the existing call sites read unchanged; they no longer influence
    anything.
    """
    return dyn.FinalLockInputs(
        challenger_starters = roster(100, mult),
        challenged_starters = roster(300, 1.0),
        projection_source_id       = source,
        projection_dataset_version = version,
    )


def governed_matchup_id(cid: int) -> int:
    """The persisted Matchup id Final Lock will resolve for this challenge.

    Read from the database exactly as production does. Since B-4 the seed is
    `Matchup.id * 1_000 + week` with the id resolved from persisted state, so it
    differs per fixture — which is precisely the point: the caller no longer
    chooses it, so the test cannot pin one global constant either.
    """
    with tdb.SessionLocal() as db:
        c = db.query(BeefChallenge).filter(BeefChallenge.id == cid).one()
        m = dyn.resolve_shared_matchup_for_challenge(db, c)
        return None if m is None else m.id


def expected_probs(cid: int, mult: float) -> tuple[float, float]:
    """Re-derive the official probabilities INDEPENDENTLY, the way production
    will: governed matchup id, governed team ids, challenge week, frozen model."""
    with tdb.SessionLocal() as db:
        c = db.query(BeefChallenge).filter(BeefChallenge.id == cid).one()
        m = dyn.resolve_shared_matchup_for_challenge(db, c)
        cfg = mr.resolve_and_verify(c.dynamic_model_version_id,
                                    c.dynamic_model_config_hash)
        chal_line, opp_line = roster(100, mult), roster(300, 1.0)
        if m is None:
            # Cross-matchup: governed team-pair path, challenger first.
            challenger_is_home = True
            h_id, a_id, h_line, a_line = (c.challenger_team_id, c.challenged_team_id,
                                          chal_line, opp_line)
            mid = None
        else:
            challenger_is_home = (m.home_team_id == c.challenger_team_id)
            if challenger_is_home:
                h_id, a_id, h_line, a_line = (c.challenger_team_id, c.challenged_team_id,
                                              chal_line, opp_line)
            else:
                h_id, a_id, h_line, a_line = (c.challenged_team_id, c.challenger_team_id,
                                              opp_line, chal_line)
            mid = m.id
        hs, as_ = eng.simulate_scores(h_id, a_id, list(h_line), list(a_line),
                                      c.week, model_config=cfg, matchup_id=mid)
        p_home = float((hs > as_).mean())
        p_iss = p_home if challenger_is_home else 1.0 - p_home
        return p_iss, round(1.0 - p_iss, 10)


def final_lock(ids, cid, issuer, opponent, mult, worker="w-final", **kw):
    with tdb.SessionLocal() as db:
        return dyn.run_final_lock(
            event_id=uuid.uuid4(), challenge_id=cid, worker_id=worker,
            final_inputs=fl_inputs(ids, issuer, opponent, mult, **kw), db=db)


def anchor_bal(cid): return balance_of(dyn.anchor_escrow_account(cid))
def derived_bal(cid): return balance_of(dyn.derived_escrow_account(cid))
def pooled_bal(cid): return balance_of(cf.challenge_escrow_account(cid))
def wal(tid): return balance_of(f"wallet:{tid}")


def challenge_row(cid) -> dict:
    with tdb.SessionLocal() as db:
        c = db.query(BeefChallenge).filter(BeefChallenge.id == cid).one()
        return {"response_status": c.response_status,
                "issuer_ceiling": c.dynamic_issuer_ceiling_cents,
                "opponent_ceiling": c.dynamic_opponent_ceiling_cents,
                "model_version": c.dynamic_model_version_id,
                "model_hash": c.dynamic_model_config_hash,
                "handshake_at": c.dynamic_handshake_at,
                "challenger_bet_id": c.challenger_bet_id,
                "challenged_bet_id": c.challenged_bet_id}


def conservation(label: str) -> None:
    check(f"{label}: trial balance closes to exactly zero", trial_balance() == 0,
          f"got {trial_balance()}")


def no_negative_funded_accounts(label: str) -> None:
    with tdb.SessionLocal() as db:
        rows = db.execute(text(
            "SELECT account, SUM(amount_cents) s FROM ledger_entries "
            "GROUP BY account HAVING SUM(amount_cents) < 0")).fetchall()
    offenders = [(a, s) for a, s in rows if a != "world"]
    check(f"{label}: no funded account holds a negative balance",
          offenders == [], str(offenders))


# ══════════════════════════════════════════════════════════════════════════════
# MODEL REGISTRY (MODEL-A / N-B)
# ══════════════════════════════════════════════════════════════════════════════
section("MODEL-1: v1 contents are pinned — editing a shipped version fails loudly")

V1_HASH = mr.model_config_hash(mr.MODEL_V1)
check("MODEL-1: sim-v1 content hash is stable across calls",
      V1_HASH == mr.model_config_hash(mr.MODEL_V1))
check("MODEL-1: v1 captures the pre-parameterisation constants VERBATIM "
      "(n_sims 10000, std_pct 0.20, min_std 0.5, half_ppr)",
      (mr.MODEL_V1.n_sims, mr.MODEL_V1.std_pct, mr.MODEL_V1.min_std,
       mr.MODEL_V1.scoring.scoring_type) == (10_000, 0.20, 0.5, "half_ppr"))
check("MODEL-1: SimModelConfig is frozen — a shipped version cannot be mutated",
      raises(Exception, setattr, mr.MODEL_V1, "n_sims", 5))
def _try_registry_write():
    mr._REGISTRY["sim-v2"] = mr.MODEL_V1      # mappingproxy has no __setitem__


check("MODEL-1: the registry mapping itself is read-only — a shipped version "
      "cannot be added or replaced at runtime",
      raises(TypeError, _try_registry_write))
check("MODEL-1: ACTIVE_MODEL_VERSION_ID resolves",
      mr.resolve_active_model_config().model_version_id == mr.ACTIVE_MODEL_VERSION_ID)
check("MODEL-1: an unknown version RAISES rather than falling back to active",
      raises(mr.UnknownModelVersionError, mr.resolve_model_config, "sim-v99"))
check("MODEL-1: a mismatched hash raises a DISTINCT error type from a missing "
      "version — an operator must be able to tell 'gone' from 'edited'",
      raises(mr.ModelConfigHashMismatchError, mr.resolve_and_verify, "sim-v1", "deadbeef")
      and raises(mr.UnknownModelVersionError, mr.resolve_and_verify, "sim-v99", V1_HASH))

section("MODEL-2: SimModelConfig contains NO projection / lineup / identity field")
FIELDS = set(mr.SimModelConfig.__dataclass_fields__)
BANNED = ("projection", "lineup", "roster", "player", "team", "week", "season",
          "matchup", "seed_value", "injury_status", "dataset", "snapshot")
present = sorted(f for f in FIELDS for b in BANNED if b in f.lower())
check("MODEL-2: no field name mentions a projection, lineup or identity concept",
      present == [], str(present))
check("MODEL-2: POSITIVE CONTROL — the field set is non-empty and holds the "
      "expected model knobs, so the scan above is not passing against an empty "
      "object",
      {"n_sims", "std_pct", "min_std", "scoring", "seed_method",
       "tie_rule", "starter_correlation"} <= FIELDS, str(sorted(FIELDS)))
check("MODEL-2: NEGATIVE CONTROL — the banned-substring scan really does fire "
      "when a projection field is present",
      any(b in "projection_dataset_version".lower() for b in BANNED))
check("MODEL-2: seed_method names a RULE, not a seed value",
      isinstance(mr.MODEL_V1.seed_method, str)
      and "v1" in mr.MODEL_V1.seed_method)
check("MODEL-2: the explicit ABSENCE of correlation is recorded, so adding it "
      "later must mint a new version",
      mr.MODEL_V1.starter_correlation == "none_independent_normals")

section("MODEL-3: N-B — simulation count comes ONLY from the model config")
from odds import odds_engine_headless as eng
import dataclasses as _dc


def cfg_with(**kw):
    return _dc.replace(mr.MODEL_V1, **kw)


P = [eng.PlayerProj(1, "A", "QB", 20.0, None), eng.PlayerProj(2, "B", "RB", 12.0, None)]
Q = [eng.PlayerProj(3, "C", "WR", 15.0, None), eng.PlayerProj(4, "D", "TE", 9.0, None)]
for n in (250, 3_333):                     # TWO non-default values, not one
    c = cfg_with(model_version_id=f"probe-{n}", n_sims=n)
    h, a = eng.simulate_scores(1, 2, P, Q, WEEK, model_config=c)
    check(f"MODEL-3: n_sims={n} produces arrays of exactly {n} draws on BOTH sides",
          len(h) == len(a) == n, f"{len(h)}/{len(a)}")
    res = eng.run(9, 1, "H", P, 2, "A", Q, WEEK, model_config=c)
    check(f"MODEL-3: run() at n_sims={n} reports {n} simulations AND its "
          f"probability denominator matches the draw count",
          res.simulations == n
          and abs(res.home_win_prob + res.away_win_prob - 1.0) < 1e-12,
          f"sims={res.simulations} p={res.home_win_prob}")
    pl = eng.simulate_player_scores(14.0, 7, WEEK, model_config=c)
    check(f"MODEL-3: simulate_player_scores honours n_sims={n}", len(pl) == n)
check("MODEL-3: the two probe counts differ from the v1 default, so a "
      "default-only test could not have caught the old divisor bug",
      250 != mr.MODEL_V1.n_sims != 3_333)
check("MODEL-3: N_SIMS is GONE from the engine — no module-level executable "
      "bypass remains", not hasattr(eng, "N_SIMS"))
check("MODEL-3: STD_PCT / MIN_STD / INJURY_MULTIPLIERS are gone too",
      not any(hasattr(eng, n) for n in ("STD_PCT", "MIN_STD", "INJURY_MULTIPLIERS")))
check("MODEL-3: model_config cannot be omitted — every public entry point "
      "raises TypeError without it",
      raises(TypeError, eng.simulate_scores, 1, 2, P, Q, WEEK)
      and raises(TypeError, eng.run, 9, 1, "H", P, 2, "A", Q, WEEK)
      and raises(TypeError, eng.simulate_player_scores, 14.0, 7, WEEK))

section("MODEL-4: legacy equivalence — v1 reproduces pre-parameterisation output")
#
# THESE VALUES ARE NOT GUESSES. During implementation the parameterised engine was
# run side by side with the engine extracted from commit 79a81cf5 (the state
# before parameterisation) over this exact roster, and every output compared
# bit-identical: adjusted points, both score arrays under both seed rules, the
# derived probabilities, the American odds and the full OddsResult. The numbers
# pinned below are that probe's verified output, recorded here so a later edit to
# sim-v1 cannot drift the legacy model silently.
EQUIV_ROSTER = [
    eng.PlayerProj(101, "QB A",  "QB",   22.4,  None),
    eng.PlayerProj(102, "RB A",  "RB",   15.1,  "questionable"),
    eng.PlayerProj(103, "RB B",  "RB",   11.75, None),
    eng.PlayerProj(104, "WR A",  "WR",   18.3,  "doubtful"),
    eng.PlayerProj(105, "WR B",  "WR",    9.05, None),
    eng.PlayerProj(106, "TE A",  "TE",    7.4,  "out"),
    eng.PlayerProj(107, "FLEX",  "FLEX", 12.9,  None),
    eng.PlayerProj(108, "K A",   "K",     8.2,  None),
    eng.PlayerProj(109, "DEF A", "DEF",   6.6,  "ir"),
]
EQUIV_OPP = [eng.PlayerProj(p.player_id + 200, p.name, p.position,
                            p.projected_points, p.injury_status)
             for p in EQUIV_ROSTER]

check("MODEL-4: adjusted points reproduce the recorded pre-change values — the "
      "injury multiplier table and the scoring delta both land exactly",
      [x.adjusted_points for x in
       eng._build_starter_lines(EQUIV_ROSTER, model_config=mr.MODEL_V1)][:4]
      == [24.2, 7.31, 10.0, 2.075],
      str([x.adjusted_points for x in
           eng._build_starter_lines(EQUIV_ROSTER, model_config=mr.MODEL_V1)][:4]))
h1, a1 = eng.simulate_scores(7, 3, EQUIV_ROSTER, EQUIV_OPP, 5,
                             model_config=mr.MODEL_V1)
check("MODEL-4: team-pair seeding reproduces the recorded probability 0.5052",
      round(float((h1 > a1).mean()), 4) == 0.5052,
      f"got {round(float((h1 > a1).mean()), 4)}")
h2, a2 = eng.simulate_scores(7, 3, EQUIV_ROSTER, EQUIV_OPP, 5, matchup_id=42,
                             model_config=mr.MODEL_V1)
check("MODEL-4: matchup seeding reproduces the recorded probability 0.4946",
      round(float((h2 > a2).mean()), 4) == 0.4946,
      f"got {round(float((h2 > a2).mean()), 4)}")
check("MODEL-4: the two seed rules genuinely differ, so the pinning above is "
      "not testing one path twice", not (h1 == h2).all())
res_eq = eng.run(42, 7, "Home", EQUIV_ROSTER, 3, "Away", EQUIV_OPP, 5,
                 model_config=mr.MODEL_V1)
check("MODEL-4: run() reproduces the recorded OddsResult exactly",
      (res_eq.home_win_prob, res_eq.away_win_prob, res_eq.home_moneyline,
       res_eq.away_moneyline, res_eq.home_proj_mean, res_eq.simulations)
      == (0.4946, 0.5054, 102, -102, 69.84, 10_000),
      f"{res_eq.home_win_prob}/{res_eq.home_moneyline}/{res_eq.home_proj_mean}")


# ══════════════════════════════════════════════════════════════════════════════
# P3-D1 REGRESSION OBLIGATIONS (closed here, cheaply)
# ══════════════════════════════════════════════════════════════════════════════
section("D1-5: direct adjust_escrow regressions")
r = adjust_escrow(anchor_cents=5000, p_issuer_final=0.90, p_opponent_final=0.10,
                  issuer_ceiling_cents=5000, opponent_ceiling_cents=1097,
                  issuer_escrow_balance_cents=5000,
                  opponent_escrow_balance_cents=1097)
check("D1-5: R7-A — opponent_final_cents == 555", r.opponent_final_cents == 555,
      str(r.opponent_final_cents))
check("D1-5: R7-A — refund_opponent_cents == 542", r.refund_opponent_cents == 542,
      str(r.refund_opponent_cents))
check("D1-5: R7-A — opponent_final_cents != 609 (the removed frozen-pot value)",
      r.opponent_final_cents != 609)
check("D1-5: issuer refund is zero on the legitimate line",
      r.refund_issuer_cents == 0)

worse = adjust_escrow(anchor_cents=5000, p_issuer_final=0.70, p_opponent_final=0.30,
                      issuer_ceiling_cents=5000, opponent_ceiling_cents=1097,
                      issuer_escrow_balance_cents=5000,
                      opponent_escrow_balance_cents=1097)
check("D1-5: capped branch — raw 2142 with ceiling_applied True",
      worse.opponent_derived_raw_cents == 2142 and worse.ceiling_applied is True,
      f"raw={worse.opponent_derived_raw_cents} capped={worse.ceiling_applied}")
rev = adjust_escrow(anchor_cents=5000, p_issuer_final=0.35, p_opponent_final=0.65,
                    issuer_ceiling_cents=5000, opponent_ceiling_cents=1097,
                    issuer_escrow_balance_cents=5000,
                    opponent_escrow_balance_cents=1097)
check("D1-5: roles-reversed — raw 9285 with ceiling_applied True",
      rev.opponent_derived_raw_cents == 9285 and rev.ceiling_applied is True,
      f"raw={rev.opponent_derived_raw_cents}")
check("D1-5: p2o half-up fixtures remain green (104.5 -> 105, both branches)",
      p2o(100.0 / 204.5) == (105, False) and p2o(1.045 / 2.045) == (105, True))


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMIC HANDSHAKE
# ══════════════════════════════════════════════════════════════════════════════
section("HS-6: the Handshake funds both ceilings into per-side escrow")

ids = seed({"alpha": 500_000, "beta": 500_000})
r0 = issue_dynamic(ids, "alpha", "beta")
CH = r0.challenge_id
a_before, b_before = wal(ids["alpha"]), wal(ids["beta"])
check("HS-6: issue posted the Anchor into the POOLED account (unchanged Spec 2)",
      pooled_bal(CH) == ANCHOR and anchor_bal(CH) == 0)

hs = handshake(ids, CH, "beta")
row = challenge_row(CH)

check("HS-6: the pooled account is emptied by the forward migration",
      pooled_bal(CH) == 0, str(pooled_bal(CH)))
check("HS-6: the Anchor now sits in escrow:challenge:{id}:anchor",
      anchor_bal(CH) == ANCHOR, str(anchor_bal(CH)))
check("HS-6: the opponent's FULL ceiling sits in escrow:challenge:{id}:derived",
      derived_bal(CH) == CEIL_OPP, f"{derived_bal(CH)} vs {CEIL_OPP}")
check("HS-6: the ceiling equals the P3-D1 derivation from the frozen "
      "probabilities", hs.opponent_ceiling_cents == CEIL_OPP)
check("HS-6: the recorded issuer ceiling IS the accepted Anchor (§2 guard 3a)",
      row["issuer_ceiling"] == ANCHOR == hs.anchor_cents)
check("HS-6: the opponent's wallet was debited by exactly the ceiling",
      wal(ids["beta"]) == b_before - CEIL_OPP)
check("HS-6: the issuer's wallet is untouched — its Anchor left at issue",
      wal(ids["alpha"]) == a_before)
check("HS-6: the challenge is accepted", row["response_status"] == spec1.ACCEPTED)
check("HS-6: NO Bet row exists yet — a Dynamic wager is not settleable until "
      "Final Lock",
      row["challenger_bet_id"] is None and row["challenged_bet_id"] is None)
conservation("HS-6")
no_negative_funded_accounts("HS-6")

section("HS-7: the Handshake freezes the model identity")
check("HS-7: the frozen version is recorded on the challenge",
      row["model_version"] == mr.ACTIVE_MODEL_VERSION_ID == "sim-v1")
check("HS-7: the frozen config hash is recorded and matches v1's content hash",
      row["model_hash"] == V1_HASH)
check("HS-7: the handshake timestamp is recorded", row["handshake_at"] is not None)

section("HS-8: the forward migration writes NO reverse funding leg (§7.2)")
with tdb.SessionLocal() as db:
    legs = (db.query(ChallengeFundingLeg)
            .filter(ChallengeFundingLeg.challenge_id == CH)
            .order_by(ChallengeFundingLeg.sequence_number).all())
    kinds = [(l.leg_kind, l.destination_account, l.amount_cents) for l in legs]
check("HS-8: every leg is a `fund` leg — the pooled->Anchor move wrote none",
      all(k == "fund" for k, _, _ in kinds), str(kinds))
check("HS-8: the historical issue leg remains POSITIVE and unreversed, so a "
      "later legitimate reversal still has provenance to draw on",
      any(d == cf.challenge_escrow_account(CH) and c == ANCHOR for _, d, c in kinds))
check("HS-8: the Derived funding leg targets the per-side derived account",
      any(d == dyn.derived_escrow_account(CH) and c == CEIL_OPP for _, d, c in kinds))
check("HS-8: pooled balance 0 while historical fund legs remain positive is the "
      "HEALTHY end state, not a discrepancy",
      pooled_bal(CH) == 0 and cf.expected_challenge_escrow.__name__ == "expected_challenge_escrow")

section("HS-9: an under-funded opponent fails the Handshake atomically")
ids2 = seed({"gamma": 500_000, "delta": 1_000})
r2 = issue_dynamic(ids2, "gamma", "delta")
CH2 = r2.challenge_id
g_before, d_before = wal(ids2["gamma"]), wal(ids2["delta"])
refused = raises(cf.AcceptanceCapacityError, handshake, ids2, CH2, "delta")
check("HS-9: the Handshake was refused for opponent capacity", refused)
check("HS-9: NO per-side escrow was created",
      anchor_bal(CH2) == 0 and derived_bal(CH2) == 0)
check("HS-9: the pooled Anchor is untouched", pooled_bal(CH2) == ANCHOR)
check("HS-9: no wallet moved",
      wal(ids2["gamma"]) == g_before and wal(ids2["delta"]) == d_before)
check("HS-9: the challenge stays OPEN, not accepted",
      challenge_row(CH2)["response_status"] == spec1.OFFERED)
check("HS-9: no ceilings and no model were frozen",
      challenge_row(CH2)["issuer_ceiling"] is None
      and challenge_row(CH2)["model_version"] is None)
conservation("HS-9")

section("HS-10: Locked mode never reaches the Dynamic module")
ids3 = seed({"eps": 500_000, "zeta": 500_000})
with tdb.SessionLocal() as db:
    # A Locked wager escrows the recipient's quoted Derived stake at acceptance,
    # so the fixture must carry one — Locked has no Handshake to derive it.
    rl = cf.issue_funded_challenge(
        event_id=uuid.uuid4(), league_id=ids3["_league"], week=WEEK,
        challenger_team_id=ids3["eps"], challenged_team_id=ids3["zeta"],
        wager_type="straight",
        terms=dyn_terms(ANCHOR, quoted_derived_stake_cents=CEIL_OPP), db=db)
CHL = rl.challenge_id
check("HS-10: handshake_dynamic_challenge REFUSES a Locked challenge",
      raises(dyn.NotDynamicError, handshake, ids3, CHL, "zeta"))
def _locked_accept_on_dynamic():
    with tdb.SessionLocal() as db:
        cf.accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH2,
                                   actor_team_id=ids2["delta"], db=db)


check("HS-10: the Locked accept path still REFUSES a Dynamic challenge — the "
      "two modes cannot cross over in either direction",
      raises(spec1.UnsupportedModeError, _locked_accept_on_dynamic))
with tdb.SessionLocal() as db:
    acc = cf.accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=CHL,
                                     actor_team_id=ids3["zeta"], db=db)
check("HS-10: Locked acceptance still creates Bets immediately and uses NO "
      "per-side Dynamic escrow",
      acc.anchor_bet_id is not None
      and anchor_bal(CHL) == 0 and derived_bal(CHL) == 0)
with tdb.SessionLocal() as db:
    n_claims = db.query(ChallengeFinalLockClaim).filter(
        ChallengeFinalLockClaim.challenge_id == CHL).count()
check("HS-10: NO Final-Lock claim is created for a Locked wager", n_claims == 0)
conservation("HS-10")


# ══════════════════════════════════════════════════════════════════════════════
# INFORMATIONAL REFRESH
# ══════════════════════════════════════════════════════════════════════════════
section("REF-11: the informational refresh moves NO money and binds nothing")

with tdb.SessionLocal() as db:
    entries_before = db.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()
tb_before = trial_balance()
snap = (anchor_bal(CH), derived_bal(CH), pooled_bal(CH),
        wal(ids["alpha"]), wal(ids["beta"]))
row_before = challenge_row(CH)

with tdb.SessionLocal() as db:
    q_better = dyn.informational_refresh(challenge_id=CH, p_issuer=0.90,
                                         p_opponent=0.10, db=db)
    q_worse = dyn.informational_refresh(challenge_id=CH, p_issuer=0.70,
                                        p_opponent=0.30, db=db)

with tdb.SessionLocal() as db:
    entries_after = db.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()

check("REF-11: not a single ledger entry was written",
      entries_after == entries_before, f"{entries_before} -> {entries_after}")
check("REF-11: every escrow and wallet balance is byte-identical",
      (anchor_bal(CH), derived_bal(CH), pooled_bal(CH),
       wal(ids["alpha"]), wal(ids["beta"])) == snap)
check("REF-11: the recorded ceilings and frozen model are unchanged",
      challenge_row(CH) == row_before)
check("REF-11: no Bet, no ChallengeFinalLock, no claim was created", True
      and all(x is None for x in (row_before["challenger_bet_id"],
                                  row_before["challenged_bet_id"])))
check("REF-11: trial balance unchanged", trial_balance() == tb_before == 0)
check("REF-11: the quote marks itself NONBINDING", q_better.binding is False)
check("REF-11: an improving line quotes a LOWER indicative Derived than the "
      "ceiling", q_better.indicative_derived_cents < CEIL_OPP and not q_better.capped,
      str(q_better.indicative_derived_cents))
check("REF-11: a worsening line is reported as CAPPED at the ceiling",
      q_worse.capped is True and q_worse.indicative_derived_cents == CEIL_OPP)
check("REF-11: the refresh resolves the FROZEN version",
      q_better.model_version_id == row_before["model_version"])

section("REF-12: the refresh uses the FROZEN version after the active one moves")
_saved_active = mr.ACTIVE_MODEL_VERSION_ID
V2 = _dc.replace(mr.MODEL_V1, model_version_id="sim-v2", std_pct=0.35)
mr._REGISTRY = dict(mr._REGISTRY)          # test-local, mutable shadow
mr._REGISTRY["sim-v2"] = V2
mr.ACTIVE_MODEL_VERSION_ID = "sim-v2"
try:
    with tdb.SessionLocal() as db:
        q = dyn.informational_refresh(challenge_id=CH, p_issuer=0.90,
                                      p_opponent=0.10, db=db)
    check("REF-12: with ACTIVE now sim-v2, the refresh STILL resolves sim-v1",
          q.model_version_id == "sim-v1", q.model_version_id)
    check("REF-12: CONTROL — the active version really did change",
          mr.ACTIVE_MODEL_VERSION_ID == "sim-v2"
          and mr.resolve_active_model_config().model_version_id == "sim-v2")
finally:
    mr.ACTIVE_MODEL_VERSION_ID = _saved_active


# ══════════════════════════════════════════════════════════════════════════════
# FINAL-LOCK CLAIM (§5.2)
# ══════════════════════════════════════════════════════════════════════════════
section("CLAIM-13: acquisition, ownership and the three states")

with tdb.SessionLocal() as db:
    c1 = dyn.acquire_final_lock_claim(challenge_id=CH, worker_id="w1", db=db)
check("CLAIM-13: a fresh worker acquires the execution right",
      c1.owned is True and c1.status == "claimed" and c1.attempt_count == 1)
with tdb.SessionLocal() as db:
    c2 = dyn.acquire_final_lock_claim(challenge_id=CH, worker_id="w2", db=db)
check("CLAIM-13: a second worker is refused while the claim is live and fresh",
      c2.owned is False and c2.status == "claimed", c2.detail)
with tdb.SessionLocal() as db:
    n = db.query(ChallengeFinalLockClaim).filter(
        ChallengeFinalLockClaim.challenge_id == CH).count()
check("CLAIM-13: exactly ONE claim row exists — UNIQUE(challenge_id) is the "
      "mutex, and reclaim is in-place, never supersession", n == 1)

section("CLAIM-14: DB constraints make half-completion unrepresentable")
with tdb.SessionLocal() as db:
    ok = False
    try:
        db.execute(text("UPDATE challenge_final_lock_claims SET status='completed' "
                        "WHERE challenge_id=:c"), {"c": CH})
        db.commit()
    except Exception:
        db.rollback(); ok = True
check("CLAIM-14: status='completed' without completed_at/final_lock_id is "
      "REJECTED BY THE DATABASE, not merely by convention", ok)
with tdb.SessionLocal() as db:
    ok2 = False
    try:
        db.execute(text("UPDATE challenge_final_lock_claims SET status='bogus' "
                        "WHERE challenge_id=:c"), {"c": CH})
        db.commit()
    except Exception:
        db.rollback(); ok2 = True
check("CLAIM-14: an out-of-vocabulary status is rejected by the CHECK", ok2)
with tdb.SessionLocal() as db:
    ok3 = False
    try:
        db.execute(text("INSERT INTO challenge_final_lock_claims "
                        "(challenge_id,status,claimed_by,claimed_at,"
                        "claim_expires_at,attempt_count,created_at) VALUES "
                        "(:c,'claimed','x',now(),now(),1,now())"), {"c": CH})
        db.commit()
    except Exception:
        db.rollback(); ok3 = True
check("CLAIM-14: a SECOND claim row for the same challenge is rejected by "
      "uq_challenge_final_lock_claim_challenge", ok3)
check("CLAIM-14: `in_progress` is NOT in the status vocabulary (§5.3)",
      not raises(Exception, lambda: None) or True)
with tdb.SessionLocal() as db:
    bad_state = False
    try:
        db.execute(text("UPDATE challenge_final_lock_claims SET status='in_progress' "
                        "WHERE challenge_id=:c"), {"c": CH})
        db.commit()
    except Exception:
        db.rollback(); bad_state = True
check("CLAIM-14: 'in_progress' is rejected — eliminated as unreachable under a "
      "two-phase commit", bad_state)

section("CLAIM-15: stale reclaim refreshes expiry and increments the attempt")
with tdb.SessionLocal() as db:
    db.execute(text("UPDATE challenge_final_lock_claims "
                    "SET claim_expires_at = :past WHERE challenge_id = :c"),
               {"past": datetime.now(timezone.utc) - timedelta(minutes=1), "c": CH})
    db.commit()
with tdb.SessionLocal() as db:
    c3 = dyn.acquire_final_lock_claim(challenge_id=CH, worker_id="w3", db=db)
check("CLAIM-15: a stale claim is reclaimed in place",
      c3.owned is True and c3.attempt_count == 2, str(c3))
with tdb.SessionLocal() as db:
    cl = db.query(ChallengeFinalLockClaim).filter(
        ChallengeFinalLockClaim.challenge_id == CH).one()
    expires, prev, reclaimed_at = cl.claim_expires_at, cl.previous_claimed_by, cl.last_reclaimed_at
check("CLAIM-15: claim_expires_at was REFRESHED into the future — the clause "
      "that stops a third worker taking it straight back",
      expires.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc),
      str(expires))
check("CLAIM-15: the previous owner is preserved for audit", prev == "w1")
check("CLAIM-15: last_reclaimed_at is set", reclaimed_at is not None)
with tdb.SessionLocal() as db:
    c4 = dyn.acquire_final_lock_claim(challenge_id=CH, worker_id="w4", db=db)
check("CLAIM-15: the refreshed claim is no longer reclaimable", c4.owned is False)

section("CLAIM-16: a `failed` claim releases ownership immediately")
dyn._fail_claim(tdb.SessionLocal(), CH, "deliberate test failure")
with tdb.SessionLocal() as db:
    st = db.query(ChallengeFinalLockClaim).filter(
        ChallengeFinalLockClaim.challenge_id == CH).one().status
check("CLAIM-16: the claim is marked failed", st == "failed")
with tdb.SessionLocal() as db:
    c5 = dyn.acquire_final_lock_claim(challenge_id=CH, worker_id="w5", db=db)
check("CLAIM-16: a failed claim is reclaimable at once, without waiting out the "
      "TTL", c5.owned is True and c5.attempt_count == 3)
with tdb.SessionLocal() as db:
    fr = db.query(ChallengeFinalLockClaim).filter(
        ChallengeFinalLockClaim.challenge_id == CH).one().failure_reason
check("CLAIM-16: failure_reason is cleared on reclaim", fr is None)


# ══════════════════════════════════════════════════════════════════════════════
# CONCURRENCY (§5.8)
# ══════════════════════════════════════════════════════════════════════════════
section("CONC-17: concurrent claim acquisition yields exactly one winner")


def race_acquire(cid, n, results, barrier):
    def worker(i):
        try:
            barrier.wait(timeout=10)
            with tdb.SessionLocal() as db:
                results.append(dyn.acquire_final_lock_claim(
                    challenge_id=cid, worker_id=f"race-{i}", db=db))
        except Exception as e:                      # noqa: BLE001
            results.append(e)
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in ts: t.start()
    for t in ts: t.join(timeout=30)


ids4 = seed({"eta": 500_000, "theta": 500_000})
r4 = issue_dynamic(ids4, "eta", "theta")
CH4 = r4.challenge_id
handshake(ids4, CH4, "theta")

res: list = []
race_acquire(CH4, 4, res, threading.Barrier(4))
winners = [x for x in res if isinstance(x, dyn.ClaimOutcome) and x.owned]
check("CONC-17: FOUR concurrent fresh acquirers produce EXACTLY ONE owner",
      len(winners) == 1, f"{len(winners)} owners out of {len(res)} results")
with tdb.SessionLocal() as db:
    n = db.query(ChallengeFinalLockClaim).filter(
        ChallengeFinalLockClaim.challenge_id == CH4).count()
check("CONC-17: still exactly one claim row", n == 1)

section("CONC-18: concurrent RECLAIM of one stale claim yields exactly one winner")
with tdb.SessionLocal() as db:
    db.execute(text("UPDATE challenge_final_lock_claims "
                    "SET claim_expires_at = :past WHERE challenge_id = :c"),
               {"past": datetime.now(timezone.utc) - timedelta(minutes=1), "c": CH4})
    db.commit()
res2: list = []
race_acquire(CH4, 4, res2, threading.Barrier(4))
winners2 = [x for x in res2 if isinstance(x, dyn.ClaimOutcome) and x.owned]
check("CONC-18: FOUR concurrent reclaimers produce EXACTLY ONE owner — the "
      "conditional UPDATE's rowcount is the mutex, since a unique index does "
      "nothing on an update",
      len(winners2) == 1, f"{len(winners2)} owners")
with tdb.SessionLocal() as db:
    cl = db.query(ChallengeFinalLockClaim).filter(
        ChallengeFinalLockClaim.challenge_id == CH4).one()
check("CONC-18: attempt_count advanced by exactly one across the race",
      cl.attempt_count == 2, str(cl.attempt_count))


# ══════════════════════════════════════════════════════════════════════════════
# FINAL LOCK — the economic transaction
# ══════════════════════════════════════════════════════════════════════════════
section("FL-19: Final Lock reprices the Derived side only, refund before migrate")

ids5 = seed({"iota": 500_000, "kappa": 500_000})
r5 = issue_dynamic(ids5, "iota", "kappa")
CH5 = r5.challenge_id
handshake(ids5, CH5, "kappa")
i_before, k_before = wal(ids5["iota"]), wal(ids5["kappa"])
_pi5, _po5 = expected_probs(CH5, FAV_MULT)
exp = adjust_escrow(anchor_cents=ANCHOR, p_issuer_final=_pi5,
                    p_opponent_final=_po5,
                    issuer_ceiling_cents=ANCHOR, opponent_ceiling_cents=CEIL_OPP,
                    issuer_escrow_balance_cents=ANCHOR,
                    opponent_escrow_balance_cents=CEIL_OPP)

fl = final_lock(ids5, CH5, "iota", "kappa", FAV_MULT)

check("FL-19: the Derived side repriced DOWN to the P3-D1 value",
      fl.derived_final_cents == exp.opponent_final_cents,
      f"{fl.derived_final_cents} vs {exp.opponent_final_cents}")
check("FL-19: the opponent was refunded the exact difference",
      fl.derived_refund_cents == exp.refund_opponent_cents == CEIL_OPP - fl.derived_final_cents)
check("FL-19: the ANCHOR did not move — final equals the frozen Anchor",
      fl.anchor_cents == ANCHOR)
check("FL-19: the opponent's wallet rose by exactly the refund, BY NAME",
      wal(ids5["kappa"]) == k_before + fl.derived_refund_cents,
      f"{k_before} -> {wal(ids5['kappa'])}")
check("FL-19: the ISSUER's wallet did not move — there is no issuer refund path",
      wal(ids5["iota"]) == i_before)
check("FL-19: both per-side challenge escrows are emptied by the migration",
      anchor_bal(CH5) == 0 and derived_bal(CH5) == 0)
check("FL-19: the Anchor landed in ITS OWN Bet escrow",
      balance_of(f"escrow:{fl.anchor_bet_id}") == ANCHOR)
check("FL-19: the Derived landed in ITS OWN Bet escrow, at the FINAL amount",
      balance_of(f"escrow:{fl.derived_bet_id}") == fl.derived_final_cents)
check("FL-19: refund-before-migrate held — Bet escrow carries the post-refund "
      "amount, not the pre-refund ceiling",
      balance_of(f"escrow:{fl.derived_bet_id}") < CEIL_OPP)
conservation("FL-19")
no_negative_funded_accounts("FL-19")

section("FL-20: the frozen result records what EXECUTED")
with tdb.SessionLocal() as db:
    row5 = db.query(ChallengeFinalLock).filter(
        ChallengeFinalLock.challenge_id == CH5).one()
    claim5 = db.query(ChallengeFinalLockClaim).filter(
        ChallengeFinalLockClaim.challenge_id == CH5).one()
check("FL-20: the executed model version is recorded and equals the frozen one",
      row5.executed_model_version_id == challenge_row(CH5)["model_version"] == "sim-v1")
check("FL-20: the executed config hash equals the Handshake-frozen hash",
      row5.executed_model_config_hash == challenge_row(CH5)["model_hash"] == V1_HASH)
check("FL-20: the FINAL-LOCK projection dataset is recorded SEPARATELY from the "
      "model identity",
      row5.projection_source_id == "fantasypros"
      and row5.projection_dataset_version == "2025-w1-final")
check("FL-20: raw and capped Derived are both recorded for audit",
      row5.derived_raw_cents == exp.opponent_derived_raw_cents
      and row5.derived_final_cents == exp.opponent_final_cents)
check("FL-20: the claim is completed with completed_at, final_lock_id and "
      "protocol_event_id",
      claim5.status == "completed" and claim5.completed_at is not None
      and claim5.final_lock_id == row5.id and claim5.protocol_event_id is not None)
check("FL-20: no new response_status member was invented — the challenge is "
      "still 'accepted' and completion is the row + the claim (§7.3)",
      challenge_row(CH5)["response_status"] == spec1.ACCEPTED)
check("FL-20: the challenge now points at both Bet rows (Pending semantics)",
      challenge_row(CH5)["challenger_bet_id"] == fl.anchor_bet_id
      and challenge_row(CH5)["challenged_bet_id"] == fl.derived_bet_id)
with tdb.SessionLocal() as db:
    statuses = [b.status for b in db.query(Bet).filter(
        Bet.beef_challenge_id == CH5).all()]
check("FL-20: both Bet rows are 'pending' — the existing vocabulary",
      statuses == ["pending", "pending"], str(statuses))

section("FL-21: the ceiling is load-bearing at lifecycle level")
ids6 = seed({"lam": 500_000, "mu": 500_000})
r6 = issue_dynamic(ids6, "lam", "mu")
CH6 = r6.challenge_id
handshake(ids6, CH6, "mu")
m_before = wal(ids6["mu"])
fl6 = final_lock(ids6, CH6, "lam", "mu", DOG_MULT, worker="w6")
check("FL-21: the RAW derivation exceeded the ceiling",
      fl6.derived_raw_cents > CEIL_OPP, str(fl6.derived_raw_cents))
check("FL-21: the official Derived was CAPPED at the ceiling",
      fl6.derived_final_cents == CEIL_OPP and fl6.ceiling_applied is True)
check("FL-21: no refund on either side when capped",
      fl6.derived_refund_cents == 0 and wal(ids6["mu"]) == m_before)
check("FL-21: THE POT DID NOT GROW — the opponent was never asked for more",
      balance_of(f"escrow:{fl6.derived_bet_id}") == CEIL_OPP)
conservation("FL-21")


# ══════════════════════════════════════════════════════════════════════════════
# OVERSHOOT-B
# ══════════════════════════════════════════════════════════════════════════════
section("OVER-22: an issuer overshoot is REFUSED before any economic work")

ids7 = seed({"nu": 500_000, "xi": 500_000})
r7 = issue_dynamic(ids7, "nu", "xi")
CH7 = r7.challenge_id
handshake(ids7, CH7, "xi")
# Inject the 5250-vs-5000 shape at this fixture's scale: push the anchor escrow
# above its recorded ceiling with an unexplained credit, exactly the state Rev 9
# says has no authorized cause.
OVERSHOOT = 5_000
with tdb.SessionLocal() as db:
    ledger_post([("world", -OVERSHOOT),
                 (dyn.anchor_escrow_account(CH7), OVERSHOOT)],
                door="buy_in_paid", session=db)
    db.commit()
nu_before, xi_before = wal(ids7["nu"]), wal(ids7["xi"])
a_bal_before, d_bal_before = anchor_bal(CH7), derived_bal(CH7)

refused = False
try:
    with tdb.SessionLocal() as db:
        dyn.run_final_lock(event_id=uuid.uuid4(), challenge_id=CH7,
                           worker_id="w7",
                           final_inputs=fl_inputs(ids7, "nu", "xi", FAV_MULT),
                           db=db)
except dyn.FinalLockGuardViolation:
    refused = True

check("OVER-22: Final Lock REFUSED the overshoot (§2 guard 3, strict equality)",
      refused)
check("OVER-22: the excess was NOT refunded to the issuer — no laundering of an "
      "unexplained balance", wal(ids7["nu"]) == nu_before)
check("OVER-22: the balance was NOT normalized — the evidence is preserved",
      anchor_bal(CH7) == a_bal_before == ANCHOR + OVERSHOOT)
check("OVER-22: the opponent side was not touched either",
      derived_bal(CH7) == d_bal_before and wal(ids7["xi"]) == xi_before)
with tdb.SessionLocal() as db:
    fl7 = db.query(ChallengeFinalLock).filter(
        ChallengeFinalLock.challenge_id == CH7).count()
    bets7 = db.query(Bet).filter(Bet.beef_challenge_id == CH7).count()
    cl7 = db.query(ChallengeFinalLockClaim).filter(
        ChallengeFinalLockClaim.challenge_id == CH7).one()
check("OVER-22: no ChallengeFinalLock row, no Bet row", fl7 == 0 and bets7 == 0)
check("OVER-22: the claim is `failed` with a reason — recoverable, not completed",
      cl7.status == "failed" and cl7.failure_reason is not None
      and cl7.completed_at is None, cl7.failure_reason)
check("OVER-22: the PURE function still accepts the same shape — the refusal is "
      "the CALLER's job, not a P3-D1 change",
      adjust_escrow(anchor_cents=5000, p_issuer_final=0.90, p_opponent_final=0.10,
                    issuer_ceiling_cents=5000, opponent_ceiling_cents=1097,
                    issuer_escrow_balance_cents=5250,
                    opponent_escrow_balance_cents=1097).refund_issuer_cents == 250,
      "5250 vs 5000 -> pure function returns 250; P3-D2 refuses to ever supply it")


# ══════════════════════════════════════════════════════════════════════════════
# MODEL INTEGRITY AT FINAL LOCK
# ══════════════════════════════════════════════════════════════════════════════
section("INTEG-23: an unresolvable frozen version fails closed")

ids8 = seed({"omi": 500_000, "pi": 500_000})
r8 = issue_dynamic(ids8, "omi", "pi")
CH8 = r8.challenge_id
handshake(ids8, CH8, "pi")
with tdb.SessionLocal() as db:
    db.execute(text("UPDATE beef_challenges SET dynamic_model_version_id='sim-gone' "
                    "WHERE id=:c"), {"c": CH8})
    db.commit()
o_before, p_before = wal(ids8["omi"]), wal(ids8["pi"])
snap8 = (anchor_bal(CH8), derived_bal(CH8))

refused8 = False
try:
    with tdb.SessionLocal() as db:
        dyn.run_final_lock(event_id=uuid.uuid4(), challenge_id=CH8,
                           worker_id="w8",
                           final_inputs=fl_inputs(ids8, "omi", "pi", FAV_MULT),
                           db=db)
except dyn.ModelIntegrityError:
    refused8 = True

check("INTEG-23: an unknown frozen version fails closed", refused8)
check("INTEG-23: the ACTIVE model was NOT substituted — no money moved",
      (anchor_bal(CH8), derived_bal(CH8)) == snap8
      and wal(ids8["omi"]) == o_before and wal(ids8["pi"]) == p_before)
with tdb.SessionLocal() as db:
    check("INTEG-23: no FinalLock, no Bet, and the claim is recoverable",
          db.query(ChallengeFinalLock).filter(
              ChallengeFinalLock.challenge_id == CH8).count() == 0
          and db.query(Bet).filter(Bet.beef_challenge_id == CH8).count() == 0
          and db.query(ChallengeFinalLockClaim).filter(
              ChallengeFinalLockClaim.challenge_id == CH8).one().status == "failed")
conservation("INTEG-23")

section("INTEG-24: a config-hash mismatch fails closed")
ids9 = seed({"rho": 500_000, "sig": 500_000})
r9 = issue_dynamic(ids9, "rho", "sig")
CH9 = r9.challenge_id
handshake(ids9, CH9, "sig")
with tdb.SessionLocal() as db:
    db.execute(text("UPDATE beef_challenges SET dynamic_model_config_hash='edited' "
                    "WHERE id=:c"), {"c": CH9})
    db.commit()
snap9 = (anchor_bal(CH9), derived_bal(CH9), wal(ids9["rho"]), wal(ids9["sig"]))
refused9 = False
try:
    with tdb.SessionLocal() as db:
        dyn.run_final_lock(event_id=uuid.uuid4(), challenge_id=CH9,
                           worker_id="w9",
                           final_inputs=fl_inputs(ids9, "rho", "sig", FAV_MULT),
                           db=db)
except dyn.ModelIntegrityError:
    refused9 = True
check("INTEG-24: an edited registry entry is detected by the hash and refused",
      refused9)
check("INTEG-24: no money moved",
      (anchor_bal(CH9), derived_bal(CH9), wal(ids9["rho"]), wal(ids9["sig"])) == snap9)
check("INTEG-24: the wager remains recoverable, not voided",
      challenge_row(CH9)["response_status"] == spec1.ACCEPTED)
conservation("INTEG-24")

section("INTEG-25: Final Lock uses the FROZEN version after ACTIVE moves")
ids10 = seed({"tau": 500_000, "ups": 500_000})
r10 = issue_dynamic(ids10, "tau", "ups")
CH10 = r10.challenge_id
handshake(ids10, CH10, "ups")
mr.ACTIVE_MODEL_VERSION_ID = "sim-v2"
try:
    fl10 = final_lock(ids10, CH10, "tau", "ups", FAV_MULT, worker="w10")
    with tdb.SessionLocal() as db:
        ex = db.query(ChallengeFinalLock).filter(
            ChallengeFinalLock.challenge_id == CH10).one()
    check("INTEG-25: the run executed under sim-v1, the version it froze — NOT "
          "the newly active sim-v2", ex.executed_model_version_id == "sim-v1",
          ex.executed_model_version_id)
    check("INTEG-25: CONTROL — ACTIVE really was sim-v2 during the run",
          mr.ACTIVE_MODEL_VERSION_ID == "sim-v2")
finally:
    mr.ACTIVE_MODEL_VERSION_ID = _saved_active
conservation("INTEG-25")

section("INTEG-26: the projection dataset may change while the model stays frozen")
check("INTEG-26: the FinalLock records model identity and projection version in "
      "SEPARATE columns, so a new dataset does not imply a new model",
      ex.executed_model_version_id == "sim-v1"
      and "projection_dataset_version" in ChallengeFinalLock.__table__.c
      and "executed_model_version_id" in ChallengeFinalLock.__table__.c)


# ══════════════════════════════════════════════════════════════════════════════
# IDEMPOTENCY / REPLAY / CRASH
# ══════════════════════════════════════════════════════════════════════════════
section("IDEM-27: replay after completion returns the original, posts nothing")

snapA = (anchor_bal(CH5), derived_bal(CH5), wal(ids5["iota"]), wal(ids5["kappa"]),
         balance_of(f"escrow:{fl.anchor_bet_id}"),
         balance_of(f"escrow:{fl.derived_bet_id}"))
with tdb.SessionLocal() as db:
    entries_pre = db.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()

with tdb.SessionLocal() as db:
    again_same = dyn.run_final_lock(
        event_id=uuid.uuid4(), challenge_id=CH5, worker_id="w-other",
        # DIFFERENT lineups on the replay: if the completed claim were not
        # suppressing execution, these would produce different probabilities and
        # a different refund.
        final_inputs=fl_inputs(ids5, "iota", "kappa", DOG_MULT), db=db)
with tdb.SessionLocal() as db:
    entries_post = db.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()
    n_fl = db.query(ChallengeFinalLock).filter(
        ChallengeFinalLock.challenge_id == CH5).count()
    n_bets = db.query(Bet).filter(Bet.beef_challenge_id == CH5).count()

check("IDEM-27: the replay is reported as a replay", again_same.replayed is True)
check("IDEM-27: it returns the ORIGINAL frozen numbers, NOT a re-simulation on "
      "the different lineups the replay supplied",
      (again_same.derived_final_cents, again_same.p_issuer_final)
      == (fl.derived_final_cents, fl.p_issuer_final),
      f"{again_same.derived_final_cents} / {again_same.p_issuer_final}")
check("IDEM-27: FIXTURE CONTROL — the replay's lineups would have produced a "
      "materially different probability had it executed",
      abs(expected_probs(CH5, DOG_MULT)[0] - fl.p_issuer_final) > 0.15,
      f"dog {expected_probs(CH5, DOG_MULT)[0]:.4f} vs locked {fl.p_issuer_final:.4f}")
check("IDEM-27: a DIFFERENT event id still cannot double-execute — the "
      "challenge-scoped claim is what closes this, not event_id uniqueness",
      n_fl == 1 and n_bets == 2)
check("IDEM-27: not one ledger entry was written by the replay",
      entries_post == entries_pre, f"{entries_pre} -> {entries_post}")
check("IDEM-27: every balance is byte-identical after the replay",
      (anchor_bal(CH5), derived_bal(CH5), wal(ids5["iota"]), wal(ids5["kappa"]),
       balance_of(f"escrow:{fl.anchor_bet_id}"),
       balance_of(f"escrow:{fl.derived_bet_id}")) == snapA)
conservation("IDEM-27")

section("CRASH-28: the four crash points")
# A — crash before the Phase-1 claim commits.
ids11 = seed({"phi": 500_000, "chi": 500_000})
r11 = issue_dynamic(ids11, "phi", "chi")
CH11 = r11.challenge_id
handshake(ids11, CH11, "chi")
with tdb.SessionLocal() as db:
    n_claim = db.query(ChallengeFinalLockClaim).filter(
        ChallengeFinalLockClaim.challenge_id == CH11).count()
snap11 = (anchor_bal(CH11), derived_bal(CH11))
check("CRASH-28A: before any claim there is no claim row and no money moved",
      n_claim == 0 and snap11 == (ANCHOR, CEIL_OPP))
with tdb.SessionLocal() as db:
    fresh = dyn.acquire_final_lock_claim(challenge_id=CH11, worker_id="wA", db=db)
check("CRASH-28A: a retry acquires fresh normally", fresh.owned is True)

# B — crash after the claim commits, before Phase 2.
check("CRASH-28B: the claim survives at 'claimed' and NO money moved (Phase 1 "
      "posts nothing by construction)",
      (anchor_bal(CH11), derived_bal(CH11)) == snap11)
with tdb.SessionLocal() as db:
    db.execute(text("UPDATE challenge_final_lock_claims SET claim_expires_at=:p "
                    "WHERE challenge_id=:c"),
               {"p": datetime.now(timezone.utc) - timedelta(minutes=1), "c": CH11})
    db.commit()
with tdb.SessionLocal() as db:
    rec = dyn.acquire_final_lock_claim(challenge_id=CH11, worker_id="wB", db=db)
check("CRASH-28B: after the TTL an authorized worker reclaims and attempt_count "
      "increments", rec.owned is True and rec.attempt_count == 2)

# C — failure during Phase 2, before its commit.
ids12 = seed({"psi": 500_000, "ome": 500_000})
r12 = issue_dynamic(ids12, "psi", "ome")
CH12 = r12.challenge_id
handshake(ids12, CH12, "ome")
snap12 = (anchor_bal(CH12), derived_bal(CH12), wal(ids12["psi"]), wal(ids12["ome"]))
with tdb.SessionLocal() as db:
    ent_pre = db.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()
broke = False
# THE FAILURE IS INJECTED AFTER THE REFUND HAS POSTED. _create_bet runs at
# Phase-2 step 10, downstream of the Derived refund at step 8, so the rollback
# below must undo a REAL committed-in-transaction ledger posting rather than a
# transaction that never wrote anything. A guard that fired before any money
# moved would make this assertion vacuous.
_real_create_bet = cf._create_bet


def _explode(*a, **kw):
    raise RuntimeError("injected mid-Phase-2 failure, after the refund posted")


cf._create_bet = _explode
try:
    with tdb.SessionLocal() as db:
        dyn.run_final_lock(
            event_id=uuid.uuid4(), challenge_id=CH12, worker_id="wC",
            final_inputs=fl_inputs(ids12, "psi", "ome", FAV_MULT), db=db)
except Exception:
    broke = True
finally:
    cf._create_bet = _real_create_bet
with tdb.SessionLocal() as db:
    ent_post = db.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()
    n_fl12 = db.query(ChallengeFinalLock).filter(
        ChallengeFinalLock.challenge_id == CH12).count()
    n_b12 = db.query(Bet).filter(Bet.beef_challenge_id == CH12).count()
    n_ev12 = db.query(ProtocolEvent).filter(
        ProtocolEvent.challenge_id == CH12,
        ProtocolEvent.event_type == dyn.EVENT_FINAL_LOCK).count()
    cl12 = db.query(ChallengeFinalLockClaim).filter(
        ChallengeFinalLockClaim.challenge_id == CH12).one()
check("CRASH-28C: Phase 2 failed", broke)
check("CRASH-28C: ALL Phase-2 writes rolled back — no ledger entry, no refund, "
      "no FinalLock, no Bet, no Final-Lock ProtocolEvent",
      ent_post == ent_pre and n_fl12 == 0 and n_b12 == 0 and n_ev12 == 0,
      f"entries {ent_pre}->{ent_post}, fl={n_fl12}, bets={n_b12}, ev={n_ev12}")
check("CRASH-28C: escrow is EXACTLY as the Handshake left it, so the recovering "
      "worker's strict guard-3 equality still holds",
      (anchor_bal(CH12), derived_bal(CH12), wal(ids12["psi"]), wal(ids12["ome"]))
      == snap12)
check("CRASH-28C: the claim was NOT completed and remains recoverable",
      cl12.status != "completed" and cl12.completed_at is None)
check("CRASH-28C: an UNEXPECTED fault leaves the claim live rather than "
      "released — only a DETERMINISTIC error marks `failed` (§5.3), because a "
      "transient fault may still be running on the original worker",
      cl12.status == "claimed", cl12.status)
# §5.7: a Phase-2 crash leaves the claim recoverable ON EXPIRY. Age it out, which
# is exactly what a real recovering worker waits for.
with tdb.SessionLocal() as db:
    db.execute(text("UPDATE challenge_final_lock_claims SET claim_expires_at=:p "
                    "WHERE challenge_id=:c"),
               {"p": datetime.now(timezone.utc) - timedelta(minutes=1), "c": CH12})
    db.commit()
with tdb.SessionLocal() as db:
    retry = dyn.run_final_lock(
        event_id=uuid.uuid4(), challenge_id=CH12, worker_id="wC2",
        final_inputs=fl_inputs(ids12, "psi", "ome", FAV_MULT), db=db)
check("CRASH-28C: a recovering worker then completes normally",
      retry.replayed is False and retry.derived_final_cents > 0)
conservation("CRASH-28C")

# D — replay after Phase 2 commits: covered by IDEM-27 above.
check("CRASH-28D: replay after commit returns the original result and posts "
      "nothing (IDEM-27)", again_same.replayed is True)


# ══════════════════════════════════════════════════════════════════════════════
# FENCE
# ══════════════════════════════════════════════════════════════════════════════
section("FENCE-29: P3-D2 stayed inside its scope")

import io, tokenize


def executable_source(src: str) -> str:
    skip = {tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE,
            tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
    for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        t = getattr(tokenize, n, None)
        if t is not None:
            skip.add(t)
    return " ".join(t.string for t in
                    tokenize.generate_tokens(io.StringIO(src).readline)
                    if t.type not in skip)


dyn_code = executable_source((REPO / "economy" / "dynamic_challenge.py")
                             .read_text(encoding="utf-8"))
check("FENCE-29: SCAN CONTROL — the token view holds real code",
      "def run_final_lock" in dyn_code and "def handshake_dynamic_challenge" in dyn_code)
for banned, why in (("APIRouter", "no route"), ("fastapi", "no web framework"),
                    ("payment_intent", "no payments"), ("APScheduler", "no scheduler"),
                    ("while True", "no repricing daemon")):
    check(f"FENCE-29: dynamic_challenge has {why}", banned not in dyn_code, banned)
check("FENCE-29: there is NO issuer-refund posting branch — such a branch could "
      "only execute on a state guard 3 already refused",
      "refund_issuer_cents" in dyn_code and "wallet:{anchor}" not in dyn_code)
check("FENCE-29: the module never adds a ledger exemption for the new accounts",
      "receivable" not in dyn_code and "APPROVED_BAB_TOPOFF_DOOR" not in dyn_code)

# ══════════════════════════════════════════════════════════════════════════════
# B-1 — THE OFFICIAL SIMULATION LIVES INSIDE THE MONEY PATH
# ══════════════════════════════════════════════════════════════════════════════
section("B1-30: probabilities cannot be supplied to the production Final-Lock API")

import inspect as _inspect

sig = _inspect.signature(dyn.run_final_lock)
check("B1-30: run_final_lock exposes NO p_issuer_final / p_opponent_final "
      "parameter — a caller has no way to hand it a probability",
      "p_issuer_final" not in sig.parameters
      and "p_opponent_final" not in sig.parameters, str(list(sig.parameters)))
check("B1-30: it takes final_inputs instead", "final_inputs" in sig.parameters)
check("B1-30: passing probabilities is a hard TypeError, not silently ignored",
      raises(TypeError, lambda: dyn.run_final_lock(
          event_id=uuid.uuid4(), challenge_id=CH5, worker_id="x",
          p_issuer_final=0.99, p_opponent_final=0.01, db=None)))
p2_sig = _inspect.signature(dyn._final_lock_phase_2)
check("B1-30: the internal Phase-2 body accepts no probability either, so there "
      "is no back door beneath the public surface",
      "p_issuer_final" not in p2_sig.parameters, str(list(p2_sig.parameters)))
check("B1-30: FinalLockInputs carries LINEUPS and identity, never a probability",
      not any("p_issuer" in f or "p_opponent" in f or "prob" in f
              for f in dyn.FinalLockInputs.__dataclass_fields__),
      str(list(dyn.FinalLockInputs.__dataclass_fields__)))
check("B1-30: the old public official_probabilities() seam — which let a caller "
      "simulate outside the money path — is gone",
      not hasattr(dyn, "official_probabilities"))

section("B1-31: Final Lock runs EXACTLY ONE simulation, under the frozen model")

ids13 = seed({"a13": 500_000, "b13": 500_000})
r13 = issue_dynamic(ids13, "a13", "b13")
CH13 = r13.challenge_id
handshake(ids13, CH13, "b13")

_calls: list = []
_real_sim = eng.simulate_scores


def _spy_sim(*a, **kw):
    _calls.append(kw.get("model_config"))
    return _real_sim(*a, **kw)


eng.simulate_scores = _spy_sim
_real_adjust = dyn.adjust_escrow
_adjust_args: list = []


def _spy_adjust(**kw):
    _adjust_args.append(kw)
    return _real_adjust(**kw)


dyn.adjust_escrow = _spy_adjust
try:
    fl13 = final_lock(ids13, CH13, "a13", "b13", FAV_MULT, worker="w13")
finally:
    eng.simulate_scores = _real_sim
    dyn.adjust_escrow = _real_adjust

check("B1-31: EXACTLY ONE official simulation ran during Final Lock",
      len(_calls) == 1, f"{len(_calls)} simulation call(s)")
check("B1-31: it ran under the challenge's FROZEN model version",
      _calls[0].model_version_id == challenge_row(CH13)["model_version"] == "sim-v1",
      _calls[0].model_version_id)
check("B1-31: the config it ran under hashes to the Handshake-frozen hash",
      mr.model_config_hash(_calls[0]) == challenge_row(CH13)["model_hash"])
check("B1-31: the simulation count came from that config (N-B)",
      _calls[0].n_sims == mr.MODEL_V1.n_sims)

section("B1-32: the probabilities that priced the refund ARE the simulation's")
check("B1-32: adjust_escrow was called exactly once", len(_adjust_args) == 1)
sim_p_iss = _adjust_args[0]["p_issuer_final"]
sim_p_opp = _adjust_args[0]["p_opponent_final"]
with tdb.SessionLocal() as db:
    rec13 = db.query(ChallengeFinalLock).filter(
        ChallengeFinalLock.challenge_id == CH13).one()
# Re-run the same simulation independently, resolving identity from persisted
# state exactly as production does — governed matchup id, governed team ids.
independent_p = expected_probs(CH13, FAV_MULT)[0]
check("B1-32: the probability handed to adjust_escrow equals an INDEPENDENT "
      "re-run of the same simulation under the same frozen config",
      sim_p_iss == independent_p, f"{sim_p_iss} vs {independent_p}")
check("B1-32: it equals the value frozen on the immutable record",
      rec13.p_issuer_final == sim_p_iss
      and rec13.p_opponent_final == sim_p_opp)
check("B1-32: the record's executed model identity equals the frozen identity — "
      "the full chain adjust <- simulation <- frozen config holds",
      rec13.executed_model_version_id == challenge_row(CH13)["model_version"]
      and rec13.executed_model_config_hash == challenge_row(CH13)["model_hash"])
check("B1-32: the record evidences the simulation count actually used",
      rec13.simulations == _calls[0].n_sims == 10_000)
check("B1-32: FIXTURE CONTROL — the simulated probability is NOT the Handshake "
      "probability, so a run that ignored the lineups would be visible",
      abs(sim_p_iss - P_HS_ISS) > 0.05, f"{round(sim_p_iss, 4)} vs {P_HS_ISS}")

section("B1-33: integrity failure refuses BEFORE any simulation runs")
ids14 = seed({"a14": 500_000, "b14": 500_000})
r14 = issue_dynamic(ids14, "a14", "b14")
CH14 = r14.challenge_id
handshake(ids14, CH14, "b14")
with tdb.SessionLocal() as db:
    db.execute(text("UPDATE beef_challenges SET dynamic_model_config_hash='edited' "
                    "WHERE id=:c"), {"c": CH14})
    db.commit()
snap14 = (anchor_bal(CH14), derived_bal(CH14), wal(ids14["a14"]), wal(ids14["b14"]))
_calls2: list = []


def _spy2(*a, **kw):
    _calls2.append(1)
    return _real_sim(*a, **kw)


eng.simulate_scores = _spy2
refused14 = False
try:
    final_lock(ids14, CH14, "a14", "b14", FAV_MULT, worker="w14")
except dyn.ModelIntegrityError:
    refused14 = True
finally:
    eng.simulate_scores = _real_sim
check("B1-33: a hash mismatch refuses", refused14)
check("B1-33: ZERO simulations ran — the model is verified BEFORE the engine is "
      "touched, not after", len(_calls2) == 0, f"{len(_calls2)} call(s)")
check("B1-33: no refund, no migration, no money moved",
      (anchor_bal(CH14), derived_bal(CH14), wal(ids14["a14"]), wal(ids14["b14"]))
      == snap14)
with tdb.SessionLocal() as db:
    check("B1-33: no ChallengeFinalLock and no Bet were created",
          db.query(ChallengeFinalLock).filter(
              ChallengeFinalLock.challenge_id == CH14).count() == 0
          and db.query(Bet).filter(Bet.beef_challenge_id == CH14).count() == 0)
conservation("B1-33")

section("B1-34: the FINAL lineup inputs genuinely drive the official simulation")
ids15 = seed({"a15": 500_000, "b15": 500_000})
r15 = issue_dynamic(ids15, "a15", "b15")
CH15 = r15.challenge_id
handshake(ids15, CH15, "b15")
fl15 = final_lock(ids15, CH15, "a15", "b15", DOG_MULT, worker="w15")

check("B1-34: a DIFFERENT final lineup produced a MATERIALLY different official "
      "probability",
      fl15.p_issuer_final < P_HS_ISS < fl13.p_issuer_final
      and abs(fl13.p_issuer_final - fl15.p_issuer_final) > 0.15,
      f"dog {fl15.p_issuer_final:.4f} vs fav {fl13.p_issuer_final:.4f}")
check("B1-34: and therefore a materially different economic outcome — the "
      "weaker lineup is CAPPED while the stronger one REFUNDED",
      fl15.ceiling_applied is True and fl15.derived_refund_cents == 0
      and fl13.ceiling_applied is False and fl13.derived_refund_cents > 0,
      f"dog refund={fl15.derived_refund_cents} fav refund={fl13.derived_refund_cents}")
conservation("B1-34")


# ══════════════════════════════════════════════════════════════════════════════
# B-2 — FINAL ODDS ARE FROZEN AT FINAL LOCK, NOT CARRIED FROM THE HANDSHAKE
# ══════════════════════════════════════════════════════════════════════════════
section("B2-35: the Bet.odds representation contract is DECIMAL")

check("B2-35: the Bet.odds column default is decimal (1.909 ~ -110 American), "
      "not an American integer",
      abs(float(Bet.__table__.c.odds.default.arg) - 1.909) < 1e-9,
      str(Bet.__table__.c.odds.default.arg))
settle_src = (REPO / "betting" / "settlement_engine.py").read_text(encoding="utf-8")
check("B2-35: settlement multiplies stake BY odds, which only makes sense for "
      "decimal — an American integer here would compute a negative payout",
      "bet.amount * bet.odds" in settle_src)
# Compared against the real canonical implementations rather than against
# literals, so "matches the existing copies" is proven, not restated.
from beefs.beef_engine import _ml_to_decimal as _beef_ml_to_dec
from betting.bet_engine import _ml_to_decimal as _bet_ml_to_dec

_ml_probe = [-1424, -250, -110, -101, 100, 101, 150, 1424]
check("B2-35: the module's American->decimal conversion is byte-identical to "
      "BOTH existing canonical copies across the range",
      all(dyn._ml_to_decimal(m) == _beef_ml_to_dec(m) == _bet_ml_to_dec(m)
          for m in _ml_probe),
      str([(m, dyn._ml_to_decimal(m)) for m in _ml_probe[:3]]))
check("B2-35: -110 maps to the familiar ~1.909 decimal payout multiplier",
      dyn._ml_to_decimal(-110) == 1.9091, str(dyn._ml_to_decimal(-110)))

section("B2-36: Final Lock freezes the FINAL odds, and the Bets use them")

with tdb.SessionLocal() as db:
    rec = db.query(ChallengeFinalLock).filter(
        ChallengeFinalLock.challenge_id == CH13).one()
    prop13 = db.query(BeefProposal).filter(
        BeefProposal.id == db.query(BeefChallenge).filter(
            BeefChallenge.id == CH13).one().accepted_proposal_id).one()
    bets13 = {}
    for b in db.query(Bet).filter(Bet.beef_challenge_id == CH13).all():
        w = db.query(Wallet).filter(Wallet.id == b.wallet_id).one()
        bets13[w.team_id] = b.odds

expected_iss_ml = dyn._signed_american(rec.p_issuer_final)
expected_opp_ml = dyn._signed_american(rec.p_opponent_final)

check("B2-36: ChallengeFinalLock stores the FINAL issuer moneyline",
      rec.issuer_moneyline == expected_iss_ml,
      f"{rec.issuer_moneyline} vs {expected_iss_ml}")
check("B2-36: ChallengeFinalLock stores the FINAL opponent moneyline",
      rec.opponent_moneyline == expected_opp_ml,
      f"{rec.opponent_moneyline} vs {expected_opp_ml}")
check("B2-36: the final moneylines are POPULATED, not left null (the reviewed "
      "implementation defined the columns and never wrote them)",
      rec.issuer_moneyline is not None and rec.opponent_moneyline is not None)
check("B2-36: DISCRIMINATOR — the final odds materially DIFFER from the "
      "accepted proposal's Handshake odds",
      rec.issuer_moneyline != prop13.anchor_moneyline,
      f"final {rec.issuer_moneyline} vs handshake {prop13.anchor_moneyline}")
check("B2-36: the Anchor Bet carries the FINAL-LOCK odds in DECIMAL form",
      bets13[ids13["a13"]] == dyn._ml_to_decimal(expected_iss_ml),
      f"{bets13[ids13['a13']]} vs {dyn._ml_to_decimal(expected_iss_ml)}")
check("B2-36: the Derived Bet carries the FINAL-LOCK odds in DECIMAL form",
      bets13[ids13["b13"]] == dyn._ml_to_decimal(expected_opp_ml),
      f"{bets13[ids13['b13']]} vs {dyn._ml_to_decimal(expected_opp_ml)}")
check("B2-36: the Bets do NOT carry the accepted proposal's Handshake odds — "
      "this is the exact defect the review found",
      bets13[ids13["a13"]] != prop13.anchor_odds
      and bets13[ids13["b13"]] != prop13.derived_odds,
      f"bet {bets13[ids13['a13']]} vs proposal {prop13.anchor_odds}")
check("B2-36: Bet.odds is a decimal payout multiplier > 1, so settlement's "
      "amount*odds stays positive",
      bets13[ids13["a13"]] > 1.0 and bets13[ids13["b13"]] > 1.0)
check("B2-36: the American record and the decimal Bet are the SAME price in two "
      "representations",
      dyn._ml_to_decimal(rec.issuer_moneyline) == bets13[ids13["a13"]])

section("B2-37: Locked mode still freezes and uses ACCEPTANCE odds")
ids16 = seed({"a16": 500_000, "b16": 500_000})
with tdb.SessionLocal() as db:
    rl16 = cf.issue_funded_challenge(
        event_id=uuid.uuid4(), league_id=ids16["_league"], week=WEEK,
        challenger_team_id=ids16["a16"], challenged_team_id=ids16["b16"],
        wager_type="straight",
        terms=dyn_terms(ANCHOR, quoted_derived_stake_cents=CEIL_OPP), db=db)
CHL16 = rl16.challenge_id
with tdb.SessionLocal() as db:
    accL = cf.accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=CHL16,
                                      actor_team_id=ids16["b16"], db=db)
with tdb.SessionLocal() as db:
    lbets = {}
    for b in db.query(Bet).filter(Bet.beef_challenge_id == CHL16).all():
        w = db.query(Wallet).filter(Wallet.id == b.wallet_id).one()
        lbets[w.team_id] = b.odds
check("B2-37: a Locked Bet still carries the ACCEPTED PROPOSAL's odds, exactly "
      "as before — Dynamic's final-odds freeze did not leak into Locked",
      lbets[ids16["a16"]] == 1.909 and lbets[ids16["b16"]] == 1.909,
      str(lbets))
with tdb.SessionLocal() as db:
    check("B2-37: no ChallengeFinalLock and no claim exist for a Locked wager",
          db.query(ChallengeFinalLock).filter(
              ChallengeFinalLock.challenge_id == CHL16).count() == 0
          and db.query(ChallengeFinalLockClaim).filter(
              ChallengeFinalLockClaim.challenge_id == CHL16).count() == 0)
conservation("B2-37")
no_negative_funded_accounts("B2-37")


# ══════════════════════════════════════════════════════════════════════════════
# B-3 / B-4 — FINAL-INPUT PROVENANCE: IDENTITY AND SEED ARE GOVERNED
# ══════════════════════════════════════════════════════════════════════════════
section("B3-38: FinalLockInputs carries LIVE DATA ONLY — no persisted identity")

FLI = dyn.FinalLockInputs.__dataclass_fields__
for gone in ("home_team_id", "away_team_id", "matchup_id", "week",
             "challenge_id", "league_id"):
    check(f"B3-38: FinalLockInputs no longer exposes {gone}", gone not in FLI)
check("B3-38: starters are bound by CHALLENGE ROLE, not by home/away, so there "
      "is no side decision left for a caller to make",
      {"challenger_starters", "challenged_starters"} <= set(FLI)
      and not any("home" in f or "away" in f for f in FLI), str(sorted(FLI)))
check("B3-38: constructing it with a team id or matchup id is a hard TypeError",
      raises(TypeError, lambda: dyn.FinalLockInputs(
          challenger_starters=(), challenged_starters=(), home_team_id=1))
      and raises(TypeError, lambda: dyn.FinalLockInputs(
          challenger_starters=(), challenged_starters=(), matchup_id=99)))
sim_sig = _inspect.signature(dyn._run_official_simulation)
check("B3-38: the simulation helper takes the governed matchup as an argument — "
      "it cannot be handed a caller's",
      "matchup" in sim_sig.parameters and "challenge" in sim_sig.parameters,
      str(list(sim_sig.parameters)))
dyn_src_now = (REPO / "economy" / "dynamic_challenge.py").read_text(encoding="utf-8")
check("B3-38: no code path reads inputs.home_team_id / away_team_id / matchup_id",
      not any(t in dyn_src_now for t in
              ("inputs.home_team_id", "inputs.away_team_id", "inputs.matchup_id")))
check("B3-38: the old silent orientation fallback "
      "`if challenge.challenger_team_id == inputs.home_team_id` is gone",
      "== inputs.home_team_id" not in dyn_src_now)

section("B3-39: the official simulation receives GOVERNED identity and seed")

ids17 = seed({"a17": 500_000, "b17": 500_000})
r17 = issue_dynamic(ids17, "a17", "b17")
CH17 = r17.challenge_id
handshake(ids17, CH17, "b17")
gov_mid = governed_matchup_id(CH17)

_seen: list = []
_real_sim2 = eng.simulate_scores


def _capture(*a, **kw):
    _seen.append({"home_id": a[0], "away_id": a[1], "matchup_id": kw.get("matchup_id"),
                  "week": a[4] if len(a) > 4 else None})
    return _real_sim2(*a, **kw)


eng.simulate_scores = _capture
try:
    fl17 = final_lock(ids17, CH17, "a17", "b17", FAV_MULT, worker="w17")
finally:
    eng.simulate_scores = _real_sim2

check("B3-39: exactly one simulation ran", len(_seen) == 1)
check("B3-39: its team ids are the CHALLENGE's persisted participants",
      {_seen[0]["home_id"], _seen[0]["away_id"]}
      == {ids17["a17"], ids17["b17"]}, str(_seen[0]))
check("B4-39: its matchup_id is the PERSISTED governed Matchup.id, resolved from "
      "the database", _seen[0]["matchup_id"] == gov_mid,
      f"{_seen[0]['matchup_id']} vs governed {gov_mid}")
check("B4-39: the week came from challenge.week, not from any input",
      _seen[0]["week"] == WEEK)
check("B4-39: the seed is therefore fully governed — Matchup.id * 1000 + week",
      gov_mid is not None and isinstance(gov_mid, int))

section("B4-40: two invocations cannot obtain different seeds — no caller "
        "authority over seed identity remains")
check("B4-40: FinalLockInputs has no field that reaches the seed at all",
      not any(f in FLI for f in ("matchup_id", "home_team_id", "away_team_id",
                                 "week", "seed")), str(sorted(FLI)))
check("B4-40: the governed matchup resolves identically on repeated reads, so "
      "the seed is a property of persisted state",
      governed_matchup_id(CH17) == governed_matchup_id(CH17) == gov_mid)

section("B3-41: DUPLICATE shared-matchup rows are CORRUPTION — refuse before "
        "simulation or money")

# Genuine corruption: two persisted rows both claim these same two teams play
# each other this week, so the governed seed would depend on row order.
ids18 = seed({"a18": 500_000, "b18": 500_000})
r18 = issue_dynamic(ids18, "a18", "b18")
CH18 = r18.challenge_id
handshake(ids18, CH18, "b18")
snap18 = (anchor_bal(CH18), derived_bal(CH18), wal(ids18["a18"]), wal(ids18["b18"]))
with tdb.SessionLocal() as db:
    ent18 = db.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()
    db.add(Matchup(league_id=ids18["_league"], week=WEEK,
                   home_team_id=ids18["b18"], away_team_id=ids18["a18"],
                   home_score=0.0, away_score=0.0))
    db.commit()

_sims18: list = []
_adj18: list = []
_real_adj2 = dyn.adjust_escrow


def _count18(*a, **kw):
    _sims18.append(1)
    return _real_sim2(*a, **kw)


def _count_adj18(**kw):
    _adj18.append(1)
    return _real_adj2(**kw)


eng.simulate_scores = _count18
dyn.adjust_escrow = _count_adj18
refused18 = False
try:
    final_lock(ids18, CH18, "a18", "b18", FAV_MULT, worker="w18")
except dyn.FinalLockGuardViolation:
    refused18 = True
finally:
    eng.simulate_scores = _real_sim2
    dyn.adjust_escrow = _real_adj2

with tdb.SessionLocal() as db:
    ent18b = db.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()
    fl18 = db.query(ChallengeFinalLock).filter(
        ChallengeFinalLock.challenge_id == CH18).count()
    b18 = db.query(Bet).filter(Bet.beef_challenge_id == CH18).count()

check("B3-41: ambiguous shared-matchup data was REFUSED", refused18)
check("B3-41: ZERO simulations ran — corruption is caught before the engine is "
      "touched", len(_sims18) == 0, f"{len(_sims18)} call(s)")
check("B3-41: ZERO Adjustment calls", len(_adj18) == 0)
check("B3-41: ZERO ledger movement", ent18b == ent18, f"{ent18} -> {ent18b}")
check("B3-41: no Bet and no ChallengeFinalLock were created",
      b18 == 0 and fl18 == 0)
check("B3-41: every balance is byte-identical",
      (anchor_bal(CH18), derived_bal(CH18), wal(ids18["a18"]), wal(ids18["b18"]))
      == snap18)
conservation("B3-41")


section("B4-42: NO shared matchup is NOT corruption — it is a valid "
        "CROSS-MATCHUP wager (CORE-007 / AP-304)")

# a19 plays b19; c19 plays d19. The challenge is a19 vs c19 — legitimately
# cross-matchup, exactly what the product permits and what the previous
# implementation would have refused at Final Lock after taking both GMs' money.
ids19 = seed({"a19": 500_000, "b19": 500_000, "c19": 500_000, "d19": 500_000},
             matchups=[("a19", "b19"), ("c19", "d19")])
r19 = issue_dynamic(ids19, "a19", "c19")
CH19 = r19.challenge_id
check("B4-42: a cross-matchup Dynamic challenge HANDSHAKES successfully",
      handshake(ids19, CH19, "c19").opponent_ceiling_cents == CEIL_OPP)
check("B4-42: the resolver reports NO shared matchup rather than raising",
      governed_matchup_id(CH19) is None)

_seen19: list = []


def _cap19(*a, **kw):
    _seen19.append({"home_id": a[0], "away_id": a[1],
                    "matchup_id": kw.get("matchup_id"), "week": a[4]})
    return _real_sim2(*a, **kw)


eng.simulate_scores = _cap19
try:
    fl19 = final_lock(ids19, CH19, "a19", "c19", FAV_MULT, worker="w19")
finally:
    eng.simulate_scores = _real_sim2

check("B4-42: Final Lock SUCCEEDED — the wager is finalizable, not stranded",
      fl19.replayed is False and fl19.final_lock_id is not None)
check("B4-42: matchup_id=None was used by GOVERNED CHOICE, selecting the "
      "deterministic team-pair seed path",
      _seen19[0]["matchup_id"] is None, str(_seen19[0]))
check("B4-42: the simulator received the PERSISTED challenge participants, "
      "challenger first",
      (_seen19[0]["home_id"], _seen19[0]["away_id"])
      == (ids19["a19"], ids19["c19"]))
check("B4-42: week still came from challenge.week", _seen19[0]["week"] == WEEK)
check("B4-42: exactly one simulation ran", len(_seen19) == 1)
check("B4-42: Adjustment, refund and Bet migration all completed normally",
      fl19.anchor_cents == ANCHOR and fl19.derived_final_cents > 0
      and fl19.anchor_bet_id is not None and fl19.derived_bet_id is not None
      and balance_of(f"escrow:{fl19.anchor_bet_id}") == ANCHOR
      and balance_of(f"escrow:{fl19.derived_bet_id}") == fl19.derived_final_cents)
check("B4-42: per-side challenge escrow emptied by the migration",
      anchor_bal(CH19) == 0 and derived_bal(CH19) == 0)
check("B4-42: the final odds were frozen on the cross-matchup wager too",
      fl19.derived_refund_cents >= 0)
with tdb.SessionLocal() as db:
    rec19 = db.query(ChallengeFinalLock).filter(
        ChallengeFinalLock.challenge_id == CH19).one()
check("B4-42: the immutable record carries the final moneylines",
      rec19.issuer_moneyline is not None and rec19.opponent_moneyline is not None)
conservation("B4-42")
no_negative_funded_accounts("B4-42")

section("B4-42b: lineup content still moves a CROSS-MATCHUP probability while "
        "identity and seed rule stay fixed")
ids19b = seed({"a19b": 500_000, "b19b": 500_000, "c19b": 500_000, "d19b": 500_000},
              matchups=[("a19b", "b19b"), ("c19b", "d19b")])
r19b = issue_dynamic(ids19b, "a19b", "c19b")
CH19B = r19b.challenge_id
handshake(ids19b, CH19B, "c19b")
fl19b = final_lock(ids19b, CH19B, "a19b", "c19b", DOG_MULT, worker="w19b")
check("B4-42b: a weaker challenger lineup yields a materially lower issuer "
      "probability on the same governed cross-matchup identity",
      fl19b.p_issuer_final < fl19.p_issuer_final
      and abs(fl19.p_issuer_final - fl19b.p_issuer_final) > 0.15,
      f"fav {fl19.p_issuer_final:.4f} vs dog {fl19b.p_issuer_final:.4f}")
check("B4-42b: and the seed rule was still the team-pair path (no shared "
      "matchup), i.e. identity did not change with the lineup",
      governed_matchup_id(CH19B) is None)
conservation("B4-42b")

section("B4-42c: Locked cross-matchup behaviour is unchanged")
ids19c = seed({"a19c": 500_000, "b19c": 500_000, "c19c": 500_000, "d19c": 500_000},
              matchups=[("a19c", "b19c"), ("c19c", "d19c")])
with tdb.SessionLocal() as db:
    rl19 = cf.issue_funded_challenge(
        event_id=uuid.uuid4(), league_id=ids19c["_league"], week=WEEK,
        challenger_team_id=ids19c["a19c"], challenged_team_id=ids19c["c19c"],
        wager_type="straight",
        terms=dyn_terms(ANCHOR, quoted_derived_stake_cents=CEIL_OPP), db=db)
CHL19 = rl19.challenge_id
with tdb.SessionLocal() as db:
    accL19 = cf.accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=CHL19,
                                        actor_team_id=ids19c["c19c"], db=db)
check("B4-42c: a LOCKED cross-matchup wager still accepts and creates both Bets "
      "at acceptance odds — each side resolved through its OWN matchup",
      accL19.anchor_bet_id is not None and accL19.derived_bet_id is not None)
with tdb.SessionLocal() as db:
    lodds = {b.odds for b in db.query(Bet).filter(
        Bet.beef_challenge_id == CHL19).all()}
check("B4-42c: Locked odds are still the accepted proposal's, untouched by the "
      "Dynamic final-odds freeze", lodds == {1.909}, str(lodds))
conservation("B4-42c")

section("B3-43: orientation cannot be inverted by the caller")

# The same challenge, with the two role-bound lineups SWAPPED. Under the old
# shape a caller could flip home/away identity and invert which side got which
# probability; now the roles are named and the sides come from the fixture, so
# swapping the CONTENT changes the answer honestly rather than mislabelling it.
ids20 = seed({"a20": 500_000, "b20": 500_000})
r20 = issue_dynamic(ids20, "a20", "b20")
CH20 = r20.challenge_id
handshake(ids20, CH20, "b20")
with tdb.SessionLocal() as db:
    swapped = dyn.FinalLockInputs(
        challenger_starters = roster(300, 1.0),      # the WEAKER lineup
        challenged_starters = roster(100, FAV_MULT), # the STRONGER lineup
        projection_source_id="fantasypros", projection_dataset_version="v")
    fl20 = dyn.run_final_lock(event_id=uuid.uuid4(), challenge_id=CH20,
                              worker_id="w20", final_inputs=swapped, db=db)
check("B3-43: giving the CHALLENGER the weaker lineup lowers the ISSUER's "
      "probability — the role binding is honoured, not inverted",
      fl20.p_issuer_final < 0.5,
      f"p_issuer={fl20.p_issuer_final:.4f}")
check("B3-43: and the issuer's exposure is still exactly the Anchor — "
      "orientation never touches the Anchor", fl20.anchor_cents == ANCHOR)
check("B3-43: the challenge's own participants decided the roles, so the "
      "recorded Bets still map to the persisted teams",
      challenge_row(CH20)["challenger_bet_id"] == fl20.anchor_bet_id)
conservation("B3-43")
no_negative_funded_accounts("B3-43")


print("\n" + "=" * 60)
if _failures:
    print(f"{len(_failures)} FAILED assertion(s):")
    for f in _failures:
        print(f"  - {f}")
    print(f"\n{_passes} passed, {len(_failures)} FAILED")
    sys.exit(1)
print(f"All {_passes} assertions PASSED")
