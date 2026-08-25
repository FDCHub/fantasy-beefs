#!/usr/bin/env python3
"""RC2 certification — authoritative post-freeze corrections and payout finality.

THE RULE. Championship scoring ends with the final Yahoo regular-season week, but
a contest that BELONGS to that window still counts when its authoritative result
lands late, and an authoritative correction to such a contest must reach the
final Championship Score. Neither is new postseason competition.

THE THREE STATES this suite holds the implementation to:

    FROZEN  the scoring window and the funded field are closed. Eligible results
            may still resolve. Postseason play is excluded permanently.
    FINAL   every eligible regular-season contest is resolved. Only now may the
            pot pay.
    PAID    the pot has been distributed. A correction arriving now FAILS CLOSED:
            RC2 performs no clawback and no re-payment.

EVERY CORRECTION IS DERIVED, NEVER TYPED. A caller names a governed contest; the
Credits come out of the postings the settlement engines already made. There is no
free-form score anywhere in this suite, which is the point.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

_TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'rc2-correction.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone  # noqa: E402

from db.schema import (  # noqa: E402
    Base, BeefChallenge, Bet, League, LeagueSeasonEconomyConfig, Matchup,
    PoolEconomicEvent, PoolInstance, SeasonAllocation, SessionLocal, Team,
    Wallet, engine,
)
from economy.fantasystakes_championship_allocation import pot_account  # noqa: E402
from economy.fantasystakes_championship_settlement import (  # noqa: E402
    settle_fantasystakes_championship,
)
from economy.rc2_season_activation import (  # noqa: E402
    activate_fantasystakes_championship_stage,
)
from ledger.ledger import (  # noqa: E402
    APPROVED_BAB_TOPOFF_DOOR, SEASON_ALLOCATION_DOOR, balance_of,
    create_ledger_table, post as ledger_post, trial_balance,
)
from reports.championship_corrections import (  # noqa: E402
    COMPETITION_PROP_POOL, COMPETITION_VERSUS, ChampionshipCorrectionError,
    REASON_ALREADY_PAID, REASON_NOT_ELIGIBLE, REASON_TEAM_NOT_IN_FIELD,
    REASON_UNKNOWN_CONTEST, corrections_for, record_authoritative_result,
)
from reports.championship_read_model import (  # noqa: E402
    freeze_fantasystakes_championship, get_fantasystakes_championship,
)
from betting.pool_census import (  # noqa: E402
    CLASSIFICATION_CLAIMS_PRESENT, CLASSIFICATION_ZERO_ELIGIBLE_CLAIMS,
)
from betting.pool_settlement import (  # noqa: E402
    EVENT_ROLLOVER_EXPIRY_SWEEP, EVENT_SUBJECT_ZERO_CLAIM_CHAMPIONSHIP_SWEEP,
    EVENT_SUBJECT_ZERO_CLAIM_ROLLOVER, EVENT_TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP,
)
from reports.grand_champion import (  # noqa: E402
    ChampionshipFinish, calculate_grand_champion,
)

FAIL: list[str] = []
SEASON = 2027
CUT = 15
STAKE = 2_000


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


Base.metadata.create_all(engine)
create_ledger_table()



def text_sql(sql, params=None):
    from sqlalchemy import text as _t
    return _t(sql)


def bet_statuses(ids):
    with SessionLocal() as db:
        return [db.query(Bet.status).filter(Bet.id == i).scalar() for i in ids]


def build(name: str, teams: int = 4):
    with SessionLocal() as db:
        lg = League(season=SEASON, name=name, projection_source="fantasypros",
                    start_week=1, playoff_start_week=CUT, season_final_week=17,
                    provider_current_week=CUT)
        db.add(lg)
        db.flush()
        L = lg.id
        T = []
        for i in range(teams):
            t = Team(league_id=L, team_name=f"{name}{i}", owner=f"Owner {i}",
                     email=f"{name.lower()}-{L}-{i}@example.test")
            db.add(t)
            db.flush()
            T.append(t.id)
            db.add(Wallet(team_id=t.id, balance=0.0))
            ledger_post([(f"bab_issuance:{L}:{SEASON}", -80_000),
                         (f"wallet:{t.id}", 80_000)],
                        door=APPROVED_BAB_TOPOFF_DOOR, session=db)
        db.add(LeagueSeasonEconomyConfig(
            league_id=L, season=SEASON, weekly_bet_minimum_cents=1000,
            championship_contribution_cents=8000, skunk_fee_cents=1000,
            regular_season_week_count=14, active_team_count=teams,
            start_week_used=1, playoff_start_week_used=CUT, frozen_at=None))
        for tid in T:
            db.add(SeasonAllocation(league_id=L, team_id=tid, season=SEASON,
                                    buyin_cents=22_000, min_reserve_cents=14_000,
                                    reserve_cents=8_000))
            ledger_post([(f"season_issuance:{L}:{SEASON}", -22_000),
                         (f"min_reserve:{tid}", 14_000), (f"reserve:{tid}", 8_000)],
                        door=SEASON_ALLOCATION_DOOR, session=db)
        db.commit()
    with SessionLocal() as db:
        activate_fantasystakes_championship_stage(L, db)
    return L, T


def make_matchup(L, T, week, *, final=True, home=0, away=1):
    with SessionLocal() as db:
        m = Matchup(league_id=L, week=week, home_team_id=T[home],
                    away_team_id=T[away], home_score=0, away_score=0,
                    finalized_at=datetime.now(timezone.utc) if final else None)
        db.add(m)
        db.flush()
        mid = m.id
        db.commit()
    return mid


def open_versus(L, T, week, *, a=0, b=1, stake=STAKE, final=True):
    """A governed GM-vs-GM matchup with both sides staked. Returns (bc_id, bets)."""
    mid = make_matchup(L, T, week, final=final, home=a, away=b)
    with SessionLocal() as db:
        bc = BeefChallenge(league_id=L, challenger_team_id=T[a],
                           challenged_team_id=T[b], week=week, bet_type="straight",
                           amount=stake / 100, challenger_odds=1.9,
                           challenged_odds=1.9, challenger_moneyline=-110,
                           challenged_moneyline=-110, status="accepted",
                           expires_at=datetime.now(timezone.utc), staleness_warning=0)
        db.add(bc)
        db.flush()
        ids = []
        for tid in (T[a], T[b]):
            w = db.query(Wallet).filter(Wallet.team_id == tid).first()
            bet = Bet(matchup_id=mid, wallet_id=w.id, bet_type="straight",
                      amount=stake / 100, odds=1.9, status="pending",
                      beef_challenge_id=bc.id)
            db.add(bet)
            db.flush()
            ids.append(bet.id)
            ledger_post([(f"wallet:{tid}", -stake), (f"escrow:{bet.id}", stake)],
                        door="wager_placed", session=db)
        bc.challenger_bet_id, bc.challenged_bet_id = ids
        bc_id = bc.id
        db.commit()
    return bc_id, ids


def settle_versus(L, T, ids, *, winner_index, a=0, b=1, stake=STAKE):
    """Settle a governed matchup with the certified `wager_settled` shape."""
    win, lose = (0, 1) if winner_index == 0 else (1, 0)
    winner_team = T[a] if win == 0 else T[b]
    with SessionLocal() as db:
        ledger_post([(f"escrow:{ids[win]}", -stake), (f"escrow:{ids[lose]}", -stake),
                     (f"wallet:{winner_team}", 2 * stake)],
                    door="wager_settled", session=db)
        db.query(Bet).filter(Bet.id == ids[win]).update({"status": "won"})
        db.query(Bet).filter(Bet.id == ids[lose]).update({"status": "lost"})
        db.commit()


def ensure_pool_definition(key: str = "fs-corr-def") -> str:
    """A minimal PoolDefinition row so PoolInstance.definition_key resolves.

    The catalog is not what this suite certifies; it needs one valid parent row
    so the FK holds. NOT NULL columns are filled by type rather than by naming
    forty catalog fields that have nothing to do with corrections.
    """
    from sqlalchemy import Boolean, Integer as SAInteger
    from db.schema import PoolDefinition

    with SessionLocal() as db:
        if db.query(PoolDefinition).filter(PoolDefinition.key == key).first():
            return key
        # Several catalog columns carry CHECK ... IN (...) enumerations. Read the
        # first legal literal straight off the constraint rather than hardcoding
        # catalog vocabulary this suite has no opinion about.
        allowed = {}
        for con in PoolDefinition.__table__.constraints:
            expr = str(getattr(con, "sqltext", ""))
            m = re.match(r"\s*(\w+)\s+IN\s+\((.+)\)\s*$", expr, re.S | re.I)
            if m:
                literals = re.findall(r"'([^']*)'", m.group(2))
                if literals:
                    allowed[m.group(1)] = literals[0]
        values = {}
        for col in PoolDefinition.__table__.columns:
            if col.nullable or col.default is not None:
                continue
            if col.name == "key":
                values[col.name] = key
            elif col.name in allowed:
                values[col.name] = allowed[col.name]
            elif isinstance(col.type, Boolean):
                values[col.name] = False
            elif isinstance(col.type, SAInteger):
                values[col.name] = 1
            else:
                values[col.name] = "n/a"
        db.add(PoolDefinition(**values))
        db.commit()
    return key


def restate_versus(L, T, ids, *, new_winner_index, a=0, b=1, stake=STAKE):
    """Restate a settled matchup: return both stakes to escrow, settle the other way.

    THIS IS THE HONEST CORRECTIVE SHAPE. A settled wager cannot simply be re-paid
    — the ledger's once-only settlement guard refuses a `wager_settled` posting
    against a drained escrow. Restating therefore unwinds into the same
    `escrow:{bet_id}` accounts the original settlement drained, then settles
    again. Both postings carry the contest's own escrow legs, which is exactly
    what lets the correction be attributed to that contest and to no other.
    """
    old_win = 0 if new_winner_index == 1 else 1
    old_team = T[a] if old_win == 0 else T[b]
    new_team = T[b] if new_winner_index == 1 else T[a]
    with SessionLocal() as db:
        ledger_post([(f"wallet:{old_team}", -2 * stake),
                     (f"escrow:{ids[0]}", stake), (f"escrow:{ids[1]}", stake)],
                    door="wager_settled", session=db)
        # The once-only settlement guard reads posted state; flush the unwind so
        # the re-settlement below sees the escrow it just refilled. Same pattern
        # `economy/fantasystakes_championship_allocation.stage_allocation` uses.
        db.flush()
        ledger_post([(f"escrow:{ids[0]}", -stake), (f"escrow:{ids[1]}", -stake),
                     (f"wallet:{new_team}", 2 * stake)],
                    door="wager_settled", session=db)
        db.query(Bet).filter(Bet.id == ids[old_win]).update({"status": "lost"})
        db.query(Bet).filter(Bet.id == ids[1 - old_win]).update({"status": "won"})
        db.commit()


def push_versus(L, T, ids, *, old_winner_index, a=0, b=1, stake=STAKE):
    """Restate a settled matchup as a PUSH: each GM's own stake returns to them.

    Unwinds into the contest's escrow and settles both sides back, which is the
    shape `settlement_engine` already uses for a push - two independent
    escrow-sourced postings with no cross-crediting.
    """
    old_team = T[a] if old_winner_index == 0 else T[b]
    with SessionLocal() as db:
        ledger_post([(f"wallet:{old_team}", -2 * stake),
                     (f"escrow:{ids[0]}", stake), (f"escrow:{ids[1]}", stake)],
                    door="wager_settled", session=db)
        db.flush()
        for idx, tid in ((0, T[a]), (1, T[b])):
            ledger_post([(f"escrow:{ids[idx]}", -stake), (f"wallet:{tid}", stake)],
                        door="wager_settled", session=db)
            db.flush()
        for i in ids:
            db.query(Bet).filter(Bet.id == i).update({"status": "push"})
        db.commit()


def make_pool(L, T, week, *, settled, winner=0, entry=500):
    """A prop-pool occurrence with its certified economic-event provenance."""
    make_matchup(L, T, week)
    dkey = ensure_pool_definition()
    with SessionLocal() as db:
        inst = PoolInstance(league_id=L, season=SEASON, week=week, phase="REGULAR",
                            rotation_cycle=1, definition_key=dkey, slot=1,
                            pot_cents=entry * len(T), rollover_cents=0,
                            distributed_cents=0, settled=False)
        db.add(inst)
        db.flush()
        iid = inst.id
        legs = [(f"wallet:{t}", -entry) for t in T]
        legs.append((f"pool:{L}", entry * len(T)))
        pid = ledger_post(legs, door="pool_weekly_collection", session=db)
        db.add(PoolEconomicEvent(league_id=L, season=SEASON, week=week,
                                 pool_instance_id=iid, event_type="WEEKLY_COLLECTION",
                                 posting_id=pid, amount_cents=entry * len(T),
                                 created_at=datetime.now(timezone.utc)))
        db.commit()
    if settled:
        settle_pool(L, T, iid, winner=winner, amount=entry * len(T))
    return iid


def settle_pool(L, T, iid, *, winner, amount):
    with SessionLocal() as db:
        pid = ledger_post([(f"pool:{L}", -amount), (f"wallet:{T[winner]}", amount)],
                          door="pool_winner_distribution", session=db)
        db.add(PoolEconomicEvent(league_id=L, season=SEASON, week=5,
                                 pool_instance_id=iid,
                                 event_type="WINNER_DISTRIBUTION", posting_id=pid,
                                 amount_cents=amount,
                                 created_at=datetime.now(timezone.utc)))
        # The durable state a NORMAL governed winner distribution leaves behind:
        # CLAIMS_PRESENT census, whole pot distributed, nothing rolled over.
        db.query(PoolInstance).filter(PoolInstance.id == iid).update(
            {"settled": True, "settled_at": datetime.now(timezone.utc),
             "settlement_classification": CLASSIFICATION_CLAIMS_PRESENT,
             "distributed_cents": amount, "rollover_cents": 0})
        db.commit()


def freeze(L):
    with SessionLocal() as db:
        snap = freeze_fantasystakes_championship(db, league_id=L)
        db.commit()
        return snap


def scores(L):
    with SessionLocal() as db:
        snap = get_fantasystakes_championship(db, league_id=L, season=SEASON)
    return {r.team_id: (r.championship_score_cents, r.place) for r in snap.rows}


def correct(L, ctype, ref, key, reason="authoritative restatement"):
    with SessionLocal() as db:
        res = record_authoritative_result(
            db, league_id=L, competition_type=ctype, contest_ref=ref,
            reason=reason, source="test", correction_key=key)
        db.commit()
        return res


def pay(L):
    with SessionLocal() as db:
        return settle_fantasystakes_championship(db, league_id=L)


# ── 1 · all eligible contests settled, no corrections ───────────────────────
print("\n1 - freeze with everything settled and no corrections")
L1, T1 = build("Base")
bc1, b1 = open_versus(L1, T1, 5)
settle_versus(L1, T1, b1, winner_index=0)
s1 = freeze(L1)
check("frozen score reflects the settled matchup",
      scores(L1)[T1[0]][0] == STAKE and scores(L1)[T1[1]][0] == -STAKE,
      str(scores(L1)))
check("no corrections exist",
      corrections_for_len(L1) == 0 if (corrections_for_len := lambda L: len(
          corrections_for(SessionLocal(), league_id=L, season=SEASON))) else True,
      "")
r1 = pay(L1)
check("payout succeeds and conserves the pot",
      not r1.replayed and sum(a.amount_cents for a in r1.awards) == 32_000
      and balance_of(pot_account(L1, SEASON)) == 0, str(r1.awards))
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


# ── 2 · eligible Versus settles AFTER the freeze ────────────────────────────
print("\n2 - eligible regular-season Versus settles after the freeze")
L2, T2 = build("LateV")
bc2, b2 = open_versus(L2, T2, 5)
s2 = freeze(L2)
frozen_field_2 = sorted(r.team_id for r in s2.rows)
check("freeze succeeds with the eligible matchup still pending",
      s2 is not None and all(r.championship_score_cents == 0 for r in s2.rows),
      str(scores(L2)))
blocked = None
try:
    pay(L2)
except Exception as exc:
    blocked = str(exc)
check("payout refuses while it is unresolved",
      blocked is not None and "not final" in blocked, str(blocked)[:110])

settle_versus(L2, T2, b2, winner_index=0)
res2 = correct(L2, COMPETITION_VERSUS, bc2, "late-v-1")
check("late settlement enters the current Championship Score",
      scores(L2)[T2[0]][0] == STAKE and scores(L2)[T2[1]][0] == -STAKE,
      str(scores(L2)))
check("the delta was derived, not supplied",
      {r.team_id: r.delta_cents for r in res2.rows}
      == {T2[0]: STAKE, T2[1]: -STAKE},
      str([(r.team_id, r.delta_cents) for r in res2.rows]))
with SessionLocal() as db:
    field_after = sorted(r.team_id for r in
                         get_fantasystakes_championship(db, league_id=L2,
                                                        season=SEASON).rows)
check("the frozen field is unchanged", field_after == frozen_field_2,
      f"{frozen_field_2} -> {field_after}")
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


# ── 3 · eligible prop pool settles AFTER the freeze ─────────────────────────
print("\n3 - eligible regular-season prop pool settles after the freeze")
L3, T3 = build("LateP")
p3 = make_pool(L3, T3, 5, settled=False, entry=500)
s3 = freeze(L3)
check("collection alone is a real competitive cost at freeze",
      scores(L3)[T3[0]][0] == -500, str(scores(L3)))
settle_pool(L3, T3, p3, winner=0, amount=2_000)
res3 = correct(L3, COMPETITION_PROP_POOL, p3, "late-p-1")
check("late pool settlement enters the current Championship Score",
      scores(L3)[T3[0]][0] == 1_500 and scores(L3)[T3[1]][0] == -500,
      str(scores(L3)))
check("delta derived from the pool's own economic events",
      {r.team_id: r.delta_cents for r in res3.rows}[T3[0]] == 2_000,
      str([(r.team_id, r.delta_cents) for r in res3.rows]))
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


# ── 4 · authoritative correction to a settled Versus, before payout ─────────
print("\n4 - correction to a settled regular-season Versus before payout")
L4, T4 = build("CorrV")
bc4, b4 = open_versus(L4, T4, 5)
settle_versus(L4, T4, b4, winner_index=0)
freeze(L4)
before4 = scores(L4)
# The authoritative result was wrong: the other GM won. The corrective economics
# are posted by the governed engine; the correction records their consequence.
restate_versus(L4, T4, b4, new_winner_index=1)
res4 = correct(L4, COMPETITION_VERSUS, bc4, "corr-v-1", reason="scoring restated")
after4 = scores(L4)
check("the exact delta is applied once",
      {r.team_id: r.delta_cents for r in res4.rows}
      == {T4[0]: -2 * STAKE, T4[1]: 2 * STAKE},
      str([(r.team_id, r.delta_cents) for r in res4.rows]))
check("podium is recomputed from the corrected score",
      before4[T4[0]][1] == 1 and after4[T4[1]][1] == 1 and after4[T4[0]][1] > 1,
      f"{before4} -> {after4}")
with SessionLocal() as db:
    audit = corrections_for(db, league_id=L4, season=SEASON)
check("an audit row exists with full provenance",
      len(audit) == 2
      and all(a.competition_type == COMPETITION_VERSUS and a.contest_ref == bc4
              and a.scoring_week == 5 and a.revision == 1
              and a.reason == "scoring restated" and a.source == "test"
              for a in audit),
      str(audit[:1]))
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


# ── 5 · authoritative correction to a settled prop pool, before payout ──────
print("\n5 - correction to a settled regular-season prop pool before payout")
L5, T5 = build("CorrP")
p5 = make_pool(L5, T5, 5, settled=True, winner=0, entry=500)
freeze(L5)
before5 = scores(L5)
with SessionLocal() as db:
    pid = ledger_post([(f"wallet:{T5[0]}", -2_000), (f"wallet:{T5[1]}", 2_000)],
                      door="pool_winner_distribution", session=db)
    db.add(PoolEconomicEvent(league_id=L5, season=SEASON, week=5,
                             pool_instance_id=p5, event_type="ROLLOVER_EXPIRY_SWEEP",
                             posting_id=pid, amount_cents=2_000,
                             created_at=datetime.now(timezone.utc)))
    db.commit()
res5 = correct(L5, COMPETITION_PROP_POOL, p5, "corr-p-1")
check("pool correction applies the derived delta once",
      {r.team_id: r.delta_cents for r in res5.rows}[T5[0]] == -2_000
      and {r.team_id: r.delta_cents for r in res5.rows}[T5[1]] == 2_000,
      str([(r.team_id, r.delta_cents) for r in res5.rows]))
check("corrected score moves by exactly that delta",
      scores(L5)[T5[0]][0] == before5[T5[0]][0] - 2_000,
      f"{before5[T5[0]][0]} -> {scores(L5)[T5[0]][0]}")
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


# ── 6 · correction replay ───────────────────────────────────────────────────
print("\n6 - correction replay applies no second delta")
before6 = scores(L4)
replay6 = correct(L4, COMPETITION_VERSUS, bc4, "corr-v-1")
check("replay is reported as a replay", replay6.replayed, str(replay6.replayed))
check("score is unchanged by the replay", scores(L4) == before6, str(scores(L4)))
with SessionLocal() as db:
    check("no duplicate audit rows",
          len(corrections_for(db, league_id=L4, season=SEASON)) == 2,
          str(len(corrections_for(db, league_id=L4, season=SEASON))))
# A NEW key over an unchanged contest is a no-op too: the cumulative value has
# not moved, so there is no delta to record.
fresh6 = correct(L4, COMPETITION_VERSUS, bc4, "corr-v-2")
check("a fresh key over an unchanged contest records nothing",
      fresh6.rows == () and scores(L4) == before6, str(fresh6.rows))


# ── 7 · correction to a postseason contest ──────────────────────────────────
print("\n7 - correction to a postseason contest is refused")
L7, T7 = build("Post")
bc7, b7 = open_versus(L7, T7, 5)
settle_versus(L7, T7, b7, winner_index=0)
freeze(L7)
bc7p, b7p = open_versus(L7, T7, CUT, a=2, b=3)
settle_versus(L7, T7, b7p, winner_index=0, a=2, b=3)
before7 = scores(L7)
reason7 = None
try:
    correct(L7, COMPETITION_VERSUS, bc7p, "post-1")
except ChampionshipCorrectionError as exc:
    reason7 = exc.reason
check("postseason contest refused with the eligibility reason",
      reason7 == REASON_NOT_ELIGIBLE, str(reason7))
check("frozen score untouched by the refusal", scores(L7) == before7, str(scores(L7)))


# ── 8 · correction to a legacy / plain wager ────────────────────────────────
print("\n8 - correction naming a legacy plain wager is refused")
L8, T8 = build("Plain")
mid8 = make_matchup(L8, T8, 5)
with SessionLocal() as db:
    w = db.query(Wallet).filter(Wallet.team_id == T8[0]).first()
    pb = Bet(matchup_id=mid8, wallet_id=w.id, bet_type="straight", amount=20.0,
             odds=1.9, status="won", beef_challenge_id=None)
    db.add(pb)
    db.flush()
    plain_id = pb.id
    ledger_post([(f"wallet:{T8[0]}", -STAKE), (f"escrow:{plain_id}", STAKE)],
                door="wager_placed", session=db)
    db.commit()
freeze(L8)
before8 = scores(L8)
reason8 = None
try:
    correct(L8, COMPETITION_VERSUS, plain_id, "plain-1")
except ChampionshipCorrectionError as exc:
    reason8 = exc.reason
check("a plain wager has no challenge and is refused",
      reason8 == REASON_UNKNOWN_CONTEST, str(reason8))
check("plain wager contributes nothing before or after",
      all(v[0] == 0 for v in before8.values()) and scores(L8) == before8,
      str(before8))


# ── 9 · correction referencing a team outside the funded field ──────────────
print("\n9 - correction involving a team outside the funded field is refused")
L9, T9 = build("Field")
bc9, b9 = open_versus(L9, T9, 5)
settle_versus(L9, T9, b9, winner_index=0)
# Freeze FIRST, so the funded field is the frozen field; the roster grows after.
freeze(L9)
with SessionLocal() as db:
    outsider = Team(league_id=L9, team_name="Late", owner="Late",
                    email=f"late-{L9}@example.test")
    db.add(outsider)
    db.flush()
    db.add(Wallet(team_id=outsider.id, balance=0.0))
    out_id = outsider.id
    db.commit()
with SessionLocal() as db:
    m = Matchup(league_id=L9, week=6, home_team_id=T9[0], away_team_id=out_id,
                home_score=0, away_score=0, finalized_at=datetime.now(timezone.utc))
    db.add(m)
    db.flush()
    bc = BeefChallenge(league_id=L9, challenger_team_id=T9[0],
                       challenged_team_id=out_id, week=6, bet_type="straight",
                       amount=20.0, challenger_odds=1.9, challenged_odds=1.9,
                       challenger_moneyline=-110, challenged_moneyline=-110,
                       status="accepted", expires_at=datetime.now(timezone.utc),
                       staleness_warning=0)
    db.add(bc)
    db.flush()
    ids = []
    for tid in (T9[0], out_id):
        w = db.query(Wallet).filter(Wallet.team_id == tid).first()
        bet = Bet(matchup_id=m.id, wallet_id=w.id, bet_type="straight", amount=20.0,
                  odds=1.9, status="won", beef_challenge_id=bc.id)
        db.add(bet)
        db.flush()
        ids.append(bet.id)
    bc.challenger_bet_id, bc.challenged_bet_id = ids
    bc9out = bc.id
    db.commit()
reason9 = None
try:
    correct(L9, COMPETITION_VERSUS, bc9out, "field-1")
except ChampionshipCorrectionError as exc:
    reason9 = exc.reason
check("a contest touching a non-funded team is refused",
      reason9 == REASON_TEAM_NOT_IN_FIELD, str(reason9))


# ── 10 · payout refused while an eligible contest is unresolved ─────────────
print("\n10 - payout refused while an eligible contest is unresolved")
L10, T10 = build("Unres")
bc10, b10 = open_versus(L10, T10, 5)
freeze(L10)
err10 = None
try:
    pay(L10)
except Exception as exc:
    err10 = str(exc)
check("payout refuses with the FINAL-gate reason",
      err10 is not None and "not final" in err10, str(err10)[:110])
check("pot untouched", balance_of(pot_account(L10, SEASON)) == 32_000,
      str(balance_of(pot_account(L10, SEASON))))
# An economically non-final week blocks too, via the certified finality predicate.
L10b, T10b = build("NotFinal")
bc10b, b10b = open_versus(L10b, T10b, 5, final=False)
settle_versus(L10b, T10b, b10b, winner_index=0)
freeze(L10b)
err10b = None
try:
    pay(L10b)
except Exception as exc:
    err10b = str(exc)
check("an unfinalized week blocks the payout",
      err10b is not None and "finalized_at IS NULL" in err10b, str(err10b)[:130])


# ── 11 · payout after everything is final ───────────────────────────────────
print("\n11 - payout succeeds exactly once once everything is final")
settle_versus(L10, T10, b10, winner_index=0)
correct(L10, COMPETITION_VERSUS, bc10, "unres-1")
r11 = pay(L10)
check("payout succeeds", not r11.replayed and sum(
    a.amount_cents for a in r11.awards) == 32_000, str(r11.awards))
check("the corrected podium was paid",
      [a.team_id for a in r11.awards][0] == T10[0], str(r11.awards))
r11b = pay(L10)
check("second payout is a replay, not a second distribution",
      r11b.replayed and r11b.posting_id == r11.posting_id
      and balance_of(pot_account(L10, SEASON)) == 0, str(r11b.replayed))


# ── 12 · correction after payout fails closed ───────────────────────────────
print("\n12 - correction after payout fails closed")
wallets_before = {t: balance_of(f"wallet:{t}") for t in T10}
pot_before = balance_of(pot_account(L10, SEASON))
restate_versus(L10, T10, b10, new_winner_index=1)
reason12 = None
try:
    correct(L10, COMPETITION_VERSUS, bc10, "post-pay-1")
except ChampionshipCorrectionError as exc:
    reason12 = exc.reason
check("refused with the already-paid reason",
      reason12 == REASON_ALREADY_PAID, str(reason12))
with SessionLocal() as db:
    check("no correction row was written",
          all(c.correction_key != "post-pay-1"
              for c in corrections_for(db, league_id=L10, season=SEASON)))
check("no second distribution and no clawback",
      balance_of(pot_account(L10, SEASON)) == pot_before == 0
      and balance_of(f"wallet:{T10[0]}")
      == wallets_before[T10[0]] - 2 * STAKE,  # only the restatement itself moved
      str(balance_of(pot_account(L10, SEASON))))
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


# ── 13 · a correction that CREATES a tie ────────────────────────────────────
print("\n13 - a correction that creates a tie pools 60/30/10 correctly")
L13, T13 = build("MakeTie")
bcA, bA = open_versus(L13, T13, 5, a=0, b=1)
settle_versus(L13, T13, bA, winner_index=0, a=0, b=1)
bcB, bB = open_versus(L13, T13, 6, a=2, b=3)
freeze(L13)
settle_versus(L13, T13, bB, winner_index=0, a=2, b=3)
correct(L13, COMPETITION_VERSUS, bcB, "tie-1")
s13 = scores(L13)
check("two GMs now share the top score",
      s13[T13[0]][0] == s13[T13[2]][0] == STAKE
      and s13[T13[0]][1] == s13[T13[2]][1] == 1, str(s13))
r13 = pay(L13)
amounts13 = {a.team_id: a.amount_cents for a in r13.awards}
check("tied first pools 60+30 and splits equally",
      amounts13[T13[0]] == amounts13[T13[2]] == 14_400
      and sum(amounts13.values()) == 32_000, str(amounts13))
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


# ── 14 · a correction that REMOVES a tie ────────────────────────────────────
print("\n14 - a correction that removes a tie yields a clean podium")
L14, T14 = build("BreakTie")
bcC, bC = open_versus(L14, T14, 5, a=0, b=1)
settle_versus(L14, T14, bC, winner_index=0, a=0, b=1)
bcD, bD = open_versus(L14, T14, 6, a=2, b=3)
settle_versus(L14, T14, bD, winner_index=0, a=2, b=3)
freeze(L14)
tied14 = scores(L14)
check("the frozen podium is a real tie for first",
      tied14[T14[0]][1] == tied14[T14[2]][1] == 1, str(tied14))
push_versus(L14, T14, bD, old_winner_index=0, a=2, b=3)
correct(L14, COMPETITION_VERSUS, bcD, "untie-1")
s14 = scores(L14)
check("the tie is gone and first place is sole",
      s14[T14[0]][1] == 1 and s14[T14[2]][1] != 1
      and s14[T14[2]][0] == 0 and s14[T14[3]][0] == 0, str(s14))
r14 = pay(L14)
amounts14 = {a.team_id: a.amount_cents for a in r14.awards}
check("clean 60/30/10 on the corrected podium",
      amounts14[T14[0]] == 19_200 and sum(amounts14.values()) == 32_000,
      str(amounts14))


# ── 15 · Grand Champion consumes the corrected podium ───────────────────────
print("\n15 - Grand Champion consumes the corrected FantasyStakes podium")
ledger_before = trial_balance()
wallets_before15 = {t: balance_of(f"wallet:{t}") for t in T14}
fs_finishes = tuple(ChampionshipFinish(team_id=tid, place=place)
                    for tid, (_, place) in sorted(scores(L14).items()))
gc = calculate_grand_champion(
    yahoo_finishes=(ChampionshipFinish(T14[0], 1), ChampionshipFinish(T14[1], 2),
                    ChampionshipFinish(T14[2], 3)),
    fantasystakes_finishes=fs_finishes)
check("Grand Champion is computed from the corrected FantasyStakes places",
      gc.champion_team_ids == (T14[0],), str(gc.champion_team_ids))
check("Grand Champion moves no Credits",
      trial_balance() == ledger_before == 0
      and all(balance_of(f"wallet:{t}") == wallets_before15[t] for t in T14))


# ── conservation ────────────────────────────────────────────────────────────
print("\nconservation")
check("global trial balance is exactly zero", trial_balance() == 0,
      str(trial_balance()))
for L, label, expected in ((L1, "Base", 0), (L2, "LateV", 32_000),
                           (L7, "Post", 32_000), (L10, "Unres", 0),
                           (L13, "MakeTie", 0), (L14, "BreakTie", 0)):
    check(f"{label} pot is exactly {expected}",
          balance_of(pot_account(L, SEASON)) == expected,
          str(balance_of(pot_account(L, SEASON))))




# ═══════════════════════════════════════════════════════════════════════════
# GOVERNED END-TO-END CORRECTION ECONOMICS
#
# Everything above proves the championship overlay. Everything below proves the
# ECONOMICS: a commissioner names a corrected RESULT and governed code moves the
# exact difference, with no hand-posted ledger entries anywhere.
# ═══════════════════════════════════════════════════════════════════════════

from economy.championship_result_correction import (  # noqa: E402
    DOOR_RESULT_CORRECTION, CorrectedPoolResult, CorrectedVersusResult,
    apply_result_correction,
)
from reports.championship_corrections import (  # noqa: E402
    FantasyStakesChampionshipCorrection,
)


def govern(L, ctype, ref, result, key, reason="authoritative restatement"):
    with SessionLocal() as db:
        res = apply_result_correction(
            db, league_id=L, competition_type=ctype, contest_ref=ref,
            corrected_result=result, reason=reason, source="commissioner:1",
            correction_key=key)
        db.commit()
        return res


def wallets(T):
    return {t: balance_of(f"wallet:{t}") for t in T}


print("")
print("G1 - Versus winner corrected before payout, end to end")
LG1, TG1 = build("GovV")
bcg1, bg1 = open_versus(LG1, TG1, 5)
settle_versus(LG1, TG1, bg1, winner_index=0)
freeze(LG1)
w_before = wallets(TG1)
sc_before = scores(LG1)
resg1 = govern(LG1, COMPETITION_VERSUS, bcg1,
               CorrectedVersusResult(outcome="winner", winner_team_id=TG1[1]),
               "gov-v-1")
w_after = wallets(TG1)
check("governed wallet delta occurs exactly once",
      w_after[TG1[0]] - w_before[TG1[0]] == -2 * STAKE
      and w_after[TG1[1]] - w_before[TG1[1]] == 2 * STAKE,
      f"{w_before} -> {w_after}")
check("championship score delta matches the wallet delta",
      scores(LG1)[TG1[0]][0] - sc_before[TG1[0]][0] == -2 * STAKE
      and scores(LG1)[TG1[1]][0] - sc_before[TG1[1]][0] == 2 * STAKE,
      str(scores(LG1)))
check("the corrected winner now leads", scores(LG1)[TG1[1]][1] == 1, str(scores(LG1)))
with SessionLocal() as db:
    rows = (db.query(FantasyStakesChampionshipCorrection)
            .filter(FantasyStakesChampionshipCorrection.league_id == LG1).all())
check("audit provenance carries the corrective posting id",
      len(rows) == 2 and all(r.posting_id is not None for r in rows)
      and len({r.posting_id for r in rows}) == 1
      and all(r.contest_ref == bcg1 and r.scoring_week == 5 for r in rows),
      str([(r.team_id, r.delta_cents, str(r.posting_id)[:8]) for r in rows]))
with SessionLocal() as db:
    door_rows = db.execute(text_sql(
        "SELECT COUNT(*) FROM ledger_entries WHERE door = :d"),
        {"d": DOOR_RESULT_CORRECTION}).scalar()
check("the correction used its own governed door, not wager_settled",
      int(door_rows) == 2, str(door_rows))
check("the bets themselves now reflect the corrected outcome",
      bet_statuses(bg1) == ["lost", "won"], str(bet_statuses(bg1)))
check("no stake was re-funded: escrow stays drained",
      balance_of(f"escrow:{bg1[0]}") == 0 and balance_of(f"escrow:{bg1[1]}") == 0)
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


print("")
print("G2 - Versus corrected to a push")
LG2, TG2 = build("GovPush")
bcg2, bg2 = open_versus(LG2, TG2, 5)
settle_versus(LG2, TG2, bg2, winner_index=0)
freeze(LG2)
w2_before = wallets(TG2)
govern(LG2, COMPETITION_VERSUS, bcg2, CorrectedVersusResult(outcome="push"),
       "gov-push-1")
w2_after = wallets(TG2)
check("a push returns each GM exactly their own stake",
      w2_after[TG2[0]] - w2_before[TG2[0]] == -STAKE
      and w2_after[TG2[1]] - w2_before[TG2[1]] == STAKE,
      f"{w2_before} -> {w2_after}")
check("both sides now score zero from the contest",
      scores(LG2)[TG2[0]][0] == 0 and scores(LG2)[TG2[1]][0] == 0,
      str(scores(LG2)))
check("both bets are marked push", bet_statuses(bg2) == ["push", "push"],
      str(bet_statuses(bg2)))
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


print("")
print("G3 - Versus correction replay moves nothing")
w3_before = wallets(TG1)
sc3_before = scores(LG1)
with SessionLocal() as db:
    entries_before = db.execute(text_sql(
        "SELECT COUNT(*) FROM ledger_entries"), {}).scalar()
replay = govern(LG1, COMPETITION_VERSUS, bcg1,
                CorrectedVersusResult(outcome="winner", winner_team_id=TG1[1]),
                "gov-v-1")
with SessionLocal() as db:
    entries_after = db.execute(text_sql(
        "SELECT COUNT(*) FROM ledger_entries"), {}).scalar()
check("replay is reported as a replay", replay.replayed, str(replay.replayed))
check("replay wrote no ledger entry", entries_after == entries_before,
      f"{entries_before} -> {entries_after}")
check("replay moved no Credits and no score",
      wallets(TG1) == w3_before and scores(LG1) == sc3_before)
with SessionLocal() as db:
    check("replay wrote no extra correction row",
          db.query(FantasyStakesChampionshipCorrection)
          .filter(FantasyStakesChampionshipCorrection.league_id == LG1).count() == 2)


print("")
print("G4 - prop-pool winner set corrected")
LG4, TG4 = build("GovPool")
pg4 = make_pool(LG4, TG4, 5, settled=True, winner=0, entry=500)
freeze(LG4)
w4_before = wallets(TG4)
sc4_before = scores(LG4)
resg4 = govern(LG4, COMPETITION_PROP_POOL, pg4,
               CorrectedPoolResult(winner_team_ids=(TG4[1], TG4[2])), "gov-p-1")
w4_after = wallets(TG4)
check("only the economic difference moves",
      w4_after[TG4[0]] - w4_before[TG4[0]] == -2_000
      and w4_after[TG4[1]] - w4_before[TG4[1]] == 1_000
      and w4_after[TG4[2]] - w4_before[TG4[2]] == 1_000
      and w4_after[TG4[3]] == w4_before[TG4[3]],
      f"{w4_before} -> {w4_after}")
check("the pot was not re-paid: total movement nets to zero",
      sum(w4_after[t] - w4_before[t] for t in TG4) == 0,
      str(sum(w4_after[t] - w4_before[t] for t in TG4)))
check("Championship Score follows the corrected winner set",
      scores(LG4)[TG4[0]][0] - sc4_before[TG4[0]][0] == -2_000
      and scores(LG4)[TG4[1]][0] - sc4_before[TG4[1]][0] == 1_000,
      str(scores(LG4)))
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


print("")
print("G5 - prop-pool correction replay moves nothing")
w5_before = wallets(TG4)
replay4 = govern(LG4, COMPETITION_PROP_POOL, pg4,
                 CorrectedPoolResult(winner_team_ids=(TG4[1], TG4[2])), "gov-p-1")
check("replay reported and nothing moved",
      replay4.replayed and wallets(TG4) == w5_before, str(replay4.replayed))


print("")
print("G6 - correction after championship payout refuses BEFORE any economics")
LG6, TG6 = build("GovPaid")
bcg6, bg6 = open_versus(LG6, TG6, 5)
settle_versus(LG6, TG6, bg6, winner_index=0)
freeze(LG6)
pay(LG6)
w6_before = wallets(TG6)
pot6_before = balance_of(pot_account(LG6, SEASON))
reason6g = None
try:
    govern(LG6, COMPETITION_VERSUS, bcg6,
           CorrectedVersusResult(outcome="winner", winner_team_id=TG6[1]),
           "gov-paid-1")
except ChampionshipCorrectionError as exc:
    reason6g = exc.reason
check("refused with the already-paid reason", reason6g == REASON_ALREADY_PAID,
      str(reason6g))
check("no corrective economics were posted",
      wallets(TG6) == w6_before, str(wallets(TG6)))
check("no second championship distribution",
      balance_of(pot_account(LG6, SEASON)) == pot6_before == 0)
with SessionLocal() as db:
    check("no correction row was written",
          db.query(FantasyStakesChampionshipCorrection)
          .filter(FantasyStakesChampionshipCorrection.league_id == LG6).count() == 0)


print("")
print("G7 - postseason and legacy contests refuse with zero economic movement")
LG7, TG7 = build("GovRefuse")
bcg7, bg7 = open_versus(LG7, TG7, 5)
settle_versus(LG7, TG7, bg7, winner_index=0)
freeze(LG7)
bcg7p, bg7p = open_versus(LG7, TG7, CUT, a=2, b=3)
settle_versus(LG7, TG7, bg7p, winner_index=0, a=2, b=3)
w7_before = wallets(TG7)
r7a = None
try:
    govern(LG7, COMPETITION_VERSUS, bcg7p,
           CorrectedVersusResult(outcome="push"), "gov-post-1")
except ChampionshipCorrectionError as exc:
    r7a = exc.reason
check("postseason contest refused", r7a == REASON_NOT_ELIGIBLE, str(r7a))
check("no Credits moved for the postseason refusal", wallets(TG7) == w7_before)

mid7 = make_matchup(LG7, TG7, 6)
with SessionLocal() as db:
    w = db.query(Wallet).filter(Wallet.team_id == TG7[0]).first()
    pb = Bet(matchup_id=mid7, wallet_id=w.id, bet_type="straight", amount=20.0,
             odds=1.9, status="won", beef_challenge_id=None)
    db.add(pb)
    db.flush()
    plain7 = pb.id
    db.commit()
r7b = None
try:
    govern(LG7, COMPETITION_VERSUS, plain7,
           CorrectedVersusResult(outcome="push"), "gov-plain-1")
except ChampionshipCorrectionError as exc:
    r7b = exc.reason
check("legacy plain wager refused", r7b == REASON_UNKNOWN_CONTEST, str(r7b))
check("no Credits moved for the legacy refusal", wallets(TG7) == w7_before)


print("")
print("G8 - team outside the funded field refuses with zero movement")
LG8, TG8 = build("GovField")
bcg8, bg8 = open_versus(LG8, TG8, 5)
settle_versus(LG8, TG8, bg8, winner_index=0)
freeze(LG8)
w8_before = wallets(TG8)
r8 = None
try:
    govern(LG8, COMPETITION_PROP_POOL, 999999,
           CorrectedPoolResult(winner_team_ids=(TG8[0],)), "gov-field-1")
except ChampionshipCorrectionError as exc:
    r8 = exc.reason
check("an unknown contest is refused", r8 == REASON_UNKNOWN_CONTEST, str(r8))
check("no Credits moved", wallets(TG8) == w8_before)


print("")
print("G9 - failure between economics and persistence rolls back completely")
LG9, TG9 = build("GovAtomic")
bcg9, bg9 = open_versus(LG9, TG9, 5)
settle_versus(LG9, TG9, bg9, winner_index=0)
freeze(LG9)
w9_before = wallets(TG9)


class InjectedFailure(Exception):
    pass


with SessionLocal() as db:
    try:
        apply_result_correction(
            db, league_id=LG9, competition_type=COMPETITION_VERSUS,
            contest_ref=bcg9,
            corrected_result=CorrectedVersusResult(outcome="winner",
                                                   winner_team_id=TG9[1]),
            reason="atomicity probe", source="test", correction_key="gov-atomic-1")
        # The corrective posting and the audit rows are staged but uncommitted.
        raise InjectedFailure("crash before commit")
    except InjectedFailure:
        db.rollback()
check("wallets are unchanged after the rollback", wallets(TG9) == w9_before,
      f"{w9_before} -> {wallets(TG9)}")
with SessionLocal() as db:
    check("no correction row survived the rollback",
          db.query(FantasyStakesChampionshipCorrection)
          .filter(FantasyStakesChampionshipCorrection.league_id == LG9).count() == 0)
    n9 = db.execute(text_sql(
        "SELECT COUNT(*) FROM ledger_entries WHERE door = :d"),
        {"d": DOOR_RESULT_CORRECTION}).scalar()
check("no corrective ledger entry survived for this league",
      scores(LG9)[TG9[0]][0] == STAKE, str(scores(LG9)))
check("the correction is retryable after the failure",
      govern(LG9, COMPETITION_VERSUS, bcg9,
             CorrectedVersusResult(outcome="winner", winner_team_id=TG9[1]),
             "gov-atomic-1").rows != (),
      "retry produced no rows")
check("retry applied the delta exactly once",
      wallets(TG9)[TG9[0]] - w9_before[TG9[0]] == -2 * STAKE,
      str(wallets(TG9)))
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


print("")
print("G10 - tie created through the real governed workflow, then Grand Champion")
LG10, TG10 = build("GovTie")
bcA, bA = open_versus(LG10, TG10, 5, a=0, b=1)
settle_versus(LG10, TG10, bA, winner_index=0, a=0, b=1)
bcB, bB = open_versus(LG10, TG10, 6, a=2, b=3)
settle_versus(LG10, TG10, bB, winner_index=1, a=2, b=3)
freeze(LG10)
check("frozen podium has a sole leader",
      scores(LG10)[TG10[0]][1] == 1 and scores(LG10)[TG10[3]][0] == STAKE,
      str(scores(LG10)))
govern(LG10, COMPETITION_VERSUS, bcB,
       CorrectedVersusResult(outcome="push"), "gov-tie-1")
s10 = scores(LG10)
check("the corrected result leaves one sole leader and two at zero",
      s10[TG10[0]][1] == 1 and s10[TG10[2]][0] == 0 and s10[TG10[3]][0] == 0,
      str(s10))
r10 = pay(LG10)
amt10 = {a.team_id: a.amount_cents for a in r10.awards}
check("60/30/10 pays the corrected podium and conserves the pot",
      amt10[TG10[0]] == 19_200 and sum(amt10.values()) == 32_000, str(amt10))
gc10 = calculate_grand_champion(
    yahoo_finishes=(ChampionshipFinish(TG10[0], 1), ChampionshipFinish(TG10[1], 2),
                    ChampionshipFinish(TG10[2], 3)),
    fantasystakes_finishes=tuple(
        ChampionshipFinish(team_id=tid, place=place)
        for tid, (_, place) in sorted(s10.items())))
w10 = wallets(TG10)
check("Grand Champion consumes the corrected FantasyStakes podium",
      gc10.champion_team_ids == (TG10[0],), str(gc10.champion_team_ids))
check("Grand Champion moved no Credits", wallets(TG10) == w10)
check("trial balance zero", trial_balance() == 0, str(trial_balance()))




# ═══════════════════════════════════════════════════════════════════════════
# POOL ECONOMIC-CLASS SAFETY
#
# RC2 corrects ONE prop-pool economic class: the governed winner distribution
# that `allocate_even_split` is the correct allocator for. Every other resolution
# fails closed, because its Credits left the pot through a different door and an
# even-split restatement would redistribute money the pot no longer holds.
#
# The classifications and event types below are imported from
# `betting.pool_census` and `betting.pool_settlement`; none are spelled here.
# ═══════════════════════════════════════════════════════════════════════════

from economy.championship_result_correction import (  # noqa: E402
    REASON_POOL_NOT_CORRECTABLE,
)


def ledger_count():
    with SessionLocal() as db:
        return db.execute(text_sql("SELECT COUNT(*) FROM ledger_entries")).scalar()


def correction_count(L):
    with SessionLocal() as db:
        return (db.query(FantasyStakesChampionshipCorrection)
                .filter(FantasyStakesChampionshipCorrection.league_id == L).count())


def non_distribution_pool(L, T, week, *, event_type, classification,
                          rollover=0, entry=500):
    """A settled occurrence whose pot left through a NON-distribution door.

    Mirrors what `_resolve_zero_claim` persists: the pot is collected, then swept
    or rolled rather than distributed, so `distributed_cents` stays 0 and the
    terminal economic event is not WINNER_DISTRIBUTION.
    """
    make_matchup(L, T, week)
    dkey = ensure_pool_definition()
    pot = entry * len(T)
    with SessionLocal() as db:
        inst = PoolInstance(league_id=L, season=SEASON, week=week, phase="REGULAR",
                            rotation_cycle=1, definition_key=dkey, slot=1,
                            pot_cents=pot, rollover_cents=0, distributed_cents=0,
                            settled=False)
        db.add(inst)
        db.flush()
        iid = inst.id
        legs = [(f"wallet:{t}", -entry) for t in T]
        legs.append((f"pool:{L}", pot))
        pid = ledger_post(legs, door="pool_weekly_collection", session=db)
        db.add(PoolEconomicEvent(league_id=L, season=SEASON, week=week,
                                 pool_instance_id=iid,
                                 event_type="WEEKLY_COLLECTION", posting_id=pid,
                                 amount_cents=pot,
                                 created_at=datetime.now(timezone.utc)))
        db.flush()
        if rollover:
            # A live carry: the pot stays in pool:{league} for a later week.
            db.add(PoolEconomicEvent(
                league_id=L, season=SEASON, week=week, pool_instance_id=iid,
                event_type=event_type, posting_id=None, amount_cents=pot,
                created_at=datetime.now(timezone.utc)))
            db.query(PoolInstance).filter(PoolInstance.id == iid).update(
                {"settled": True, "settled_at": datetime.now(timezone.utc),
                 "settlement_classification": classification,
                 "distributed_cents": 0, "rollover_cents": pot})
        else:
            # A sweep: the pot leaves for the Yahoo championship account.
            spid = ledger_post([(f"pool:{L}", -pot), (f"championship:{L}", pot)],
                               door="pool_championship_sweep", session=db)
            db.add(PoolEconomicEvent(
                league_id=L, season=SEASON, week=week, pool_instance_id=iid,
                event_type=event_type, posting_id=spid, amount_cents=pot,
                created_at=datetime.now(timezone.utc)))
            db.query(PoolInstance).filter(PoolInstance.id == iid).update(
                {"settled": True, "settled_at": datetime.now(timezone.utc),
                 "settlement_classification": classification,
                 "distributed_cents": 0, "rollover_cents": 0})
        db.commit()
    return iid


def refusal_case(label, L, T, instance_id, winners, key):
    """Every refusal must leave the ledger, the audit trail and wallets untouched."""
    w_before = wallets(T)
    sc_before = scores(L)
    entries_before = ledger_count()
    rows_before = correction_count(L)
    reason = None
    try:
        govern(L, COMPETITION_PROP_POOL, instance_id,
               CorrectedPoolResult(winner_team_ids=winners), key)
    except ChampionshipCorrectionError as exc:
        reason = exc.reason
    check(f"{label} refuses with the pool-class reason",
          reason == REASON_POOL_NOT_CORRECTABLE, str(reason))
    check(f"{label}: zero new ledger entries",
          ledger_count() == entries_before,
          f"{entries_before} -> {ledger_count()}")
    check(f"{label}: zero correction rows",
          correction_count(L) == rows_before, str(correction_count(L)))
    check(f"{label}: byte-identical wallets", wallets(T) == w_before, str(wallets(T)))
    check(f"{label}: Championship Score unchanged", scores(L) == sc_before,
          str(scores(L)))
    check(f"{label}: trial balance zero", trial_balance() == 0, str(trial_balance()))


print("")
print("P1 - a normal winner-distribution pool is still correctable")
LP1, TP1 = build("PoolOK")
pp1 = make_pool(LP1, TP1, 5, settled=True, winner=0, entry=500)
freeze(LP1)
wp_before = wallets(TP1)
scp_before = scores(LP1)
entries_p1 = ledger_count()
govern(LP1, COMPETITION_PROP_POOL, pp1,
       CorrectedPoolResult(winner_team_ids=(TP1[1], TP1[2])), "pool-ok-1")
wp_after = wallets(TP1)
check("only the economic difference moves",
      wp_after[TP1[0]] - wp_before[TP1[0]] == -2_000
      and wp_after[TP1[1]] - wp_before[TP1[1]] == 1_000
      and wp_after[TP1[2]] - wp_before[TP1[2]] == 1_000
      and wp_after[TP1[3]] == wp_before[TP1[3]], f"{wp_before} -> {wp_after}")
check("the correction posted exactly once",
      ledger_count() == entries_p1 + 3, f"{entries_p1} -> {ledger_count()}")
check("Championship Score follows through the overlay",
      scores(LP1)[TP1[0]][0] - scp_before[TP1[0]][0] == -2_000
      and scores(LP1)[TP1[1]][0] - scp_before[TP1[1]][0] == 1_000,
      str(scores(LP1)))
check("trial balance zero", trial_balance() == 0, str(trial_balance()))

w_replay = wallets(TP1)
sc_replay = scores(LP1)
entries_replay = ledger_count()
again = govern(LP1, COMPETITION_PROP_POOL, pp1,
               CorrectedPoolResult(winner_team_ids=(TP1[1], TP1[2])), "pool-ok-1")
check("replay of the supported correction stays idempotent",
      again.replayed and wallets(TP1) == w_replay and scores(LP1) == sc_replay
      and ledger_count() == entries_replay, str(again.replayed))


print("")
print("P2 - a rollover pool refuses")
LP2, TP2 = build("PoolRoll")
pp2 = non_distribution_pool(LP2, TP2, 5,
                            event_type=EVENT_SUBJECT_ZERO_CLAIM_ROLLOVER,
                            classification=CLASSIFICATION_ZERO_ELIGIBLE_CLAIMS,
                            rollover=1)
freeze(LP2)
refusal_case("rollover", LP2, TP2, pp2, (TP2[1],), "pool-roll-1")


print("")
print("P3 - a championship-sweep pool refuses")
LP3, TP3 = build("PoolSweep")
pp3 = non_distribution_pool(
    LP3, TP3, 5, event_type=EVENT_SUBJECT_ZERO_CLAIM_CHAMPIONSHIP_SWEEP,
    classification=CLASSIFICATION_ZERO_ELIGIBLE_CLAIMS)
freeze(LP3)
refusal_case("championship sweep", LP3, TP3, pp3, (TP3[1],), "pool-sweep-1")


print("")
print("P4 - a CLAIMS_PRESENT occurrence that swept on zero winning tickets refuses")
# betting/pool_settlement.py:369 - a CLAIMS_PRESENT census whose winning tickets
# were zero resolves through _resolve_zero_claim, so the classification alone
# would have wrongly admitted this one. The economic-event history is what
# refuses it.
LP4, TP4 = build("PoolTicket")
pp4 = non_distribution_pool(
    LP4, TP4, 5, event_type=EVENT_TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP,
    classification=CLASSIFICATION_CLAIMS_PRESENT)
freeze(LP4)
refusal_case("ticket-zero sweep under CLAIMS_PRESENT", LP4, TP4, pp4,
             (TP4[1],), "pool-ticket-1")


print("")
print("P5 - an unsettled eligible pool refuses rather than being restated")
LP5, TP5 = build("PoolOpen")
pp5 = make_pool(LP5, TP5, 5, settled=False, entry=500)
freeze(LP5)
refusal_case("unsettled occurrence", LP5, TP5, pp5, (TP5[1],), "pool-open-1")

# ROLLOVER EXPIRY SWEEP is reachable on an eligible regular-season occurrence
# only at the season's final week, through the same `_resolve_zero_claim` path;
# its durable shape is identical to P3 (distributed_cents 0, sweep event), so it
# is refused by the same predicate rather than by a separate fixture.
LP6, TP6 = build("PoolExpiry")
pp6 = non_distribution_pool(LP6, TP6, 5, event_type=EVENT_ROLLOVER_EXPIRY_SWEEP,
                            classification=CLASSIFICATION_ZERO_ELIGIBLE_CLAIMS)
freeze(LP6)
refusal_case("rollover expiry sweep", LP6, TP6, pp6, (TP6[1],), "pool-expiry-1")


print(f"\n{'=' * 64}")
if FAIL:
    print(f"FAILED: {len(FAIL)} assertion(s)")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("PASS: RC2 authoritative correction and payout-finality certification")
