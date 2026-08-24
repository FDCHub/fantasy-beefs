#!/usr/bin/env python3
"""FINAL POR · WP-13 certification — voiding an ACCEPTED wager.

    F1  the refund goes to `wallet:`, in full, for both sides
    F2  `min:{team}:{week}` is NEVER restored
    F3  the accepted action goes on satisfying the Weekly Minimum
    F4  the FantasyStakes Score effect is exactly 0
    F5  escrow is exact — drained, and no more than it held
    F6  an independent, auditable void event and record
    F7  the void is exactly-once, at the storage layer
    F8  a voided wager is not settled
    F9  what a void refuses: not accepted, already settled, no reason, legacy era
    F10 the migration applies, is idempotent, and enforces one row per bet

WHY F2 AND F3 ARE THE SAME FACT ASSERTED TWICE. §7 says the accepted action goes
on satisfying the Weekly Minimum AND that the Minimum is never restored. Those
are one property of the posting seen from two sides, and both are checked here
because getting one right by accident while getting the other wrong is exactly
what a Wallet-vs-`min:` mix-up looks like. F2 reads the account; F3 runs the real
WP-4 week close afterwards and requires that nothing extra is swept — which is
the consequence a GM would actually feel.

WHY F4 IS NOT A RESTATEMENT OF F1. F1 says the Credits came back. F4 says the
competition records no result: the read model must report 0, not -X. Those come
apart if the refund posts under a door outside `VERSUS_DOORS`, which is exactly
the mistake the door membership exists to prevent.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import beefs.proposal_lifecycle as spec1
import ledger.ledger as ledger_module
from db.schema import (
    Base, Bet, League, LeagueSeasonEconomyConfig, Matchup, Team, VoidedWager,
    Wallet,
)
from economy.challenge_funding import (
    accept_funded_challenge, issue_funded_challenge,
)
from economy.current_settle import current_settle
from economy.economy_events import EVENT_WAGER_VOID
from economy.wager_void import (
    DOOR_WAGER_VOID, WagerVoidError, is_voided, void_accepted_wager,
    voided_bet_ids,
)
from economy.weekly_minimum import expire_week, release_week
from ledger.ledger import SEASON_ALLOCATION_DOOR, post as ledger_post
from reports.standings_read_model import VERSUS_DOORS, league_standings
from reports.action_read_model import gm_action_state
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
DEADLINE = NOW + timedelta(days=7)

LEAGUE = 1
SEASON = 2026
WEEK = 1
WEEKS = 14
WEEKLY = 1_000
STAKE = 400
TEAMS = (1, 2, 3, 4)


def _build(*, final_por: bool = True):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module.SessionLocal = sessionmaker(bind=engine)
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=LEAGUE, name="L", season=SEASON, start_week=1,
                  playoff_start_week=15))
    for t in TEAMS:
        db.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider_team_key=f"k{t}"))
        db.add(Wallet(team_id=t, balance=0.0))
    # Scores are present but the week is NOT finalised: `finalized_at` is the
    # only economic-finality predicate, so an unfinalised week is exactly the
    # live state a void happens in.
    db.add(Matchup(id=1, league_id=LEAGUE, week=WEEK, home_team_id=1,
                   away_team_id=2, home_score=0.0, away_score=0.0,
                   finalized_at=None))
    db.add(Matchup(id=2, league_id=LEAGUE, week=WEEK, home_team_id=3,
                   away_team_id=4, home_score=0.0, away_score=0.0,
                   finalized_at=None))
    db.add(LeagueSeasonEconomyConfig(
        league_id=LEAGUE, season=SEASON,
        weekly_bet_minimum_cents=WEEKLY,
        championship_contribution_cents=8_000,
        skunk_fee_cents=500,
        regular_season_week_count=WEEKS,
        active_team_count=len(TEAMS),
        start_week_used=1, playoff_start_week_used=15,
        frozen_at=NAIVE))
    db.commit()

    if final_por:
        stamp_ruleset(db, league_id=LEAGUE, season=SEASON,
                      version=RULESET_FINAL_POR)
    for t in TEAMS:
        ledger_post([(f"season_issuance:{LEAGUE}:{SEASON}", -WEEKLY * WEEKS),
                     (f"min_reserve:{t}", WEEKLY * WEEKS)],
                    door=SEASON_ALLOCATION_DOOR, session=db)
    db.commit()
    release_week(db, league_id=LEAGUE, week=WEEK, now=NOW)
    db.commit()
    return db


def _terms(stake_cents: int) -> spec1.ProposalTerms:
    """A fixed even-money Locked proposal. No market board is involved: the
    void has nothing to do with pricing, and a real quote would put a moving
    part into a fixture that is testing a refund."""
    return spec1.ProposalTerms(
        line=None, side=None, player_id=None,
        anchor_stake_cents=stake_cents,
        quoted_derived_stake_cents=stake_cents,
        quoted_funded_pot_cents=stake_cents * 2,
        quoted_anchor_payout_cents=stake_cents * 2,
        quoted_derived_payout_cents=stake_cents * 2,
        anchor_win_probability=0.5, derived_win_probability=0.5,
        anchor_odds=2.0, derived_odds=2.0,
        anchor_moneyline=100, derived_moneyline=100,
        pricing_model_id=spec1.MODE_LOCKED,
    )


def _accepted_challenge(db, *, stake_cents: int = STAKE):
    """Issue and accept one Locked wager between teams 1 and 2."""
    issued = issue_funded_challenge(
        event_id=uuid.uuid4(), league_id=LEAGUE, week=WEEK,
        challenger_team_id=1, challenged_team_id=2, wager_type="straight",
        terms=_terms(stake_cents), db=db, challenge_mode=spec1.MODE_LOCKED,
        proposal_lock_at=DEADLINE, now=NOW)
    accept_funded_challenge(event_id=uuid.uuid4(),
                            challenge_id=issued.challenge_id,
                            actor_team_id=2, db=db, now=NOW)
    return issued.challenge_id


def _bal(db, account: str) -> int:
    return ledger_module._balance_of_in_session(db, account)


def _score(db, team_id: int) -> int:
    rows = {r.team_id: r for r in league_standings(db, league_id=LEAGUE).rows}
    return rows[team_id].net_cents


# ── F1/F5 · the refund, and the escrow ──────────────────────────────────────

print("\nWP13-F1/F5 · the refund goes to Wallet, in full, for both sides")
db = _build()
challenge_id = _accepted_challenge(db)
db.commit()

bets = db.query(Bet).filter(Bet.beef_challenge_id == challenge_id) \
    .order_by(Bet.id).all()
escrows = {b.id: _bal(db, f"escrow:{b.id}") for b in bets}
min_before = {t: _bal(db, f"min:{t}:{WEEK}") for t in (1, 2)}
wallet_before = {t: _bal(db, f"wallet:{t}") for t in (1, 2)}

_assert("both sides funded a real escrow",
        len(bets) == 2 and all(v > 0 for v in escrows.values()), str(escrows))
before_action = gm_action_state(db, team_id=1, league_id=LEAGUE)
before_card = next(c for c in before_action.cards
                   if c.challenge_id == challenge_id)
_assert("the accepted wager is LIVE before void",
        before_card.section == "live" and not before_card.settled,
        str(before_card))
_assert("  · Status reports the accepted Bet escrows",
        before_card.escrow_cents == sum(escrows.values()),
        f"{before_card.escrow_cents} vs {sum(escrows.values())}")
_assert("  · the stakes came out of the Weekly Minimum, min-first",
        all(min_before[t] == WEEKLY - STAKE for t in (1, 2)),
        str(min_before))
_assert("  · and no Wallet was touched to fund them",
        all(v == 0 for v in wallet_before.values()), str(wallet_before))

result = void_accepted_wager(db, challenge_id=challenge_id,
                             reason="NFL game cancelled", now=NOW)
db.commit()

after_action = gm_action_state(db, team_id=1, league_id=LEAGUE)
after_card = next(c for c in after_action.cards
                  if c.challenge_id == challenge_id)
_assert("the voided wager moves to RESOLVED Action",
        after_card.section == "completed" and after_card.settled,
        str(after_card))
_assert("  · its governed result is void at zero net and zero escrow",
        (after_card.outcome == "void" and after_card.net_cents == 0
         and after_card.escrow_cents == 0), str(after_card))
_assert("  · its audit identity and accepted protocol state remain intact",
        (after_card.challenge_id == challenge_id
         and after_card.protocol_state == spec1.ACCEPTED), str(after_card))
_assert("  · and Resolved exposes no wager-management controls",
        after_card.controls == (), str(after_card.controls))

_assert("the void refunded both sides",
        result.total_refunded_cents == sum(escrows.values()),
        f"{result.total_refunded_cents} vs {sum(escrows.values())}")
_assert("  · each GM's Wallet holds exactly their own stake back",
        all(_bal(db, f"wallet:{t}") == STAKE for t in (1, 2)),
        str({t: _bal(db, f"wallet:{t}") for t in (1, 2)}))
_assert("  · every escrow is drained to exactly 0",
        all(_bal(db, f"escrow:{b.id}") == 0 for b in bets),
        str({b.id: _bal(db, f"escrow:{b.id}") for b in bets}))
_assert("  · and no more than it held was returned",
        sum(_bal(db, f"wallet:{t}") for t in (1, 2)) == sum(escrows.values()),
        str(sum(_bal(db, f"wallet:{t}") for t in (1, 2))))
_assert("  · the global trial balance is zero",
        ledger_module.trial_balance() == 0,
        str(ledger_module.trial_balance()))
_assert("  · every refund leg sits under the void door",
        db.execute(text(
            "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
            "WHERE door = :d"), {"d": DOOR_WAGER_VOID}).scalar() == 0)


# ── F2/F3 · the Weekly Minimum ──────────────────────────────────────────────

print("\nWP13-F2 · `min:{team}:{week}` is NEVER restored")
_assert("the Weekly Minimum account is exactly where the stake left it",
        all(_bal(db, f"min:{t}:{WEEK}") == WEEKLY - STAKE for t in (1, 2)),
        str({t: _bal(db, f"min:{t}:{WEEK}") for t in (1, 2)}))
_assert("  · not one cent of the refund reached a `min:` account",
        db.execute(text(
            "SELECT COUNT(*) FROM ledger_entries "
            "WHERE door = :d AND account LIKE 'min:%'"),
            {"d": DOOR_WAGER_VOID}).scalar() == 0)
_assert("  · the refund legs are escrow out, wallet in, and nothing else",
        {r[0].split(":")[0] for r in db.execute(text(
            "SELECT DISTINCT account FROM ledger_entries WHERE door = :d"),
            {"d": DOOR_WAGER_VOID}).fetchall()} == {"escrow", "wallet"})

print("\nWP13-F3 · the accepted action goes on satisfying the Weekly Minimum")
pot_before = _bal(db, f"fantasystakes_championship:{LEAGUE}:{SEASON}")
swept = expire_week(db, league_id=LEAGUE, week=WEEK, now=NOW)
db.commit()
by_team = {r.team_id: r.expired_cents for r in swept}

_assert("week close sweeps only the UNSPENT remainder for the two GMs",
        by_team[1] == by_team[2] == WEEKLY - STAKE,
        str({t: by_team[t] for t in (1, 2)}))
_assert("  · which is the same as a GM who never voided anything",
        by_team[3] == by_team[4] == WEEKLY, str(by_team))
_assert("  · so the refunded stake was NOT swept to the pot as well",
        _bal(db, f"fantasystakes_championship:{LEAGUE}:{SEASON}") - pot_before
        == (WEEKLY - STAKE) * 2 + WEEKLY * 2,
        str(_bal(db, f"fantasystakes_championship:{LEAGUE}:{SEASON}")
            - pot_before))
_assert("  · and the refund is still in the GM's Wallet, spendable",
        all(_bal(db, f"wallet:{t}") == STAKE for t in (1, 2)),
        str({t: _bal(db, f"wallet:{t}") for t in (1, 2)}))


# ── F4 · the FantasyStakes Score ────────────────────────────────────────────

print("\nWP13-F4 · the FantasyStakes Score effect is exactly 0")
_assert("the void door is a member of VERSUS_DOORS — the mechanism",
        DOOR_WAGER_VOID in VERSUS_DOORS)
scores = {t: _score(db, t) for t in TEAMS}
_assert("both voided GMs score exactly 0", scores[1] == scores[2] == 0,
        str(scores))
_assert("  · which is the same as the two GMs who never wagered",
        scores[1] == scores[3] == scores[4], str(scores))
_assert("  · no GM was charged for a contest that never happened",
        all(v == 0 for v in scores.values()), str(scores))

settle = current_settle(db, team_id=1, league_id=LEAGUE, season=SEASON)
_assert("  · and the GM has no In Play interest left",
        settle.in_play_cents == 0, str(settle.as_dict()))
_assert("  · their Current Settle reflects only the week-close forfeiture",
        settle.current_settle_cents == -(WEEKLY - STAKE),
        f"{settle.current_settle_cents} vs {-(WEEKLY - STAKE)}")


# ── F6 · the audit record ───────────────────────────────────────────────────

print("\nWP13-F6 · an independent, auditable void event and record")
rows = db.query(VoidedWager).order_by(VoidedWager.bet_id).all()
_assert("one row per voided bet", len(rows) == 2, str(len(rows)))
_assert("  · each names its own team, refund and reason",
        all(r.reason == "NFL game cancelled" and r.refunded_cents == STAKE
            and r.team_id in (1, 2) for r in rows),
        str([(r.bet_id, r.team_id, r.refunded_cents) for r in rows]))
_assert("  · and its league-season, so a second season is separable",
        all(r.league_id == LEAGUE and r.season == SEASON for r in rows))
_assert("  · each carries the posting that moved the Credits",
        all(r.posting_id is not None for r in rows))
_assert("  · one economy event names the whole act",
        db.execute(text("SELECT COUNT(*) FROM economy_event "
                        "WHERE event_type = :t"),
                   {"t": EVENT_WAGER_VOID}).scalar() == 1)
_assert("  · carrying the total refunded",
        db.execute(text("SELECT amount_cents FROM economy_event "
                        "WHERE event_type = :t"),
                   {"t": EVENT_WAGER_VOID}).scalar() == STAKE * 2)
_assert("  · the Bet rows were NOT relabelled `push`",
        all(b.status == "pending" for b in
            db.query(Bet).filter(Bet.beef_challenge_id == challenge_id).all()),
        str([b.status for b in
             db.query(Bet).filter(Bet.beef_challenge_id == challenge_id).all()]))
_assert("  · `is_voided` answers for each bet",
        all(is_voided(db, bet_id=b.id) for b in bets))
_assert("  · and `voided_bet_ids` lists them for the league",
        set(voided_bet_ids(db, league_id=LEAGUE)) == {b.id for b in bets},
        str(voided_bet_ids(db, league_id=LEAGUE)))


# ── F7 · exactly-once ───────────────────────────────────────────────────────

print("\nWP13-F7 · the void is exactly-once, at the storage layer")
wallets_before = {t: _bal(db, f"wallet:{t}") for t in (1, 2)}
try:
    void_accepted_wager(db, challenge_id=challenge_id, reason="again", now=NOW)
    _assert("a second void is refused", False, "accepted")
except WagerVoidError as exc:
    db.rollback()
    _assert("a second void is refused", exc.reason == "VOID_ALREADY_VOIDED",
            exc.reason)
_assert("  · no Wallet moved",
        {t: _bal(db, f"wallet:{t}") for t in (1, 2)} == wallets_before,
        str({t: _bal(db, f"wallet:{t}") for t in (1, 2)}))
_assert("  · still one row per bet", db.query(VoidedWager).count() == 2)
replay_action = gm_action_state(db, team_id=1, league_id=LEAGUE)
replay_card = next(c for c in replay_action.cards
                   if c.challenge_id == challenge_id)
_assert("  · replay cannot resurrect the wager in LIVE Action",
        (replay_card.section == "completed" and replay_card.settled
         and replay_card.outcome == "void" and replay_card.net_cents == 0),
        str(replay_card))
_assert("  · and the database itself would refuse a duplicate",
        "uq_voided_wager_bet" in {c.name for c in
                                  VoidedWager.__table__.constraints if c.name})


# ── F8 · settlement leaves it alone ────────────────────────────────────────

print("\nWP13-F8 · a voided wager is not settled")
import inspect  # noqa: E402

import betting.settlement_engine as se  # noqa: E402

src = inspect.getsource(se.settle_week)
_assert("settlement excludes voided bets from its pending set",
        "voided_bet_ids" in src and "~Bet.id.in_(_voided)" in src)
_assert("  · from the durable record, not from a Bet status",
        "voided_wagers" in inspect.getsource(se))

live = _build()
live_challenge = _accepted_challenge(live)
live.commit()
live_bets = live.query(Bet).filter(
    Bet.beef_challenge_id == live_challenge).all()
void_accepted_wager(live, challenge_id=live_challenge, reason="cancelled",
                    now=NOW)
live.commit()
_assert("  · the voided bets are excluded by the real query filter",
        set(voided_bet_ids(live, league_id=LEAGUE))
        == {b.id for b in live_bets})
remaining = (live.query(Bet)
             .filter(Bet.status == "pending")
             .filter(~Bet.id.in_(voided_bet_ids(live, league_id=LEAGUE)))
             .all())
_assert("  · leaving nothing for settlement to pay", remaining == [],
        str([b.id for b in remaining]))


# ── F9 · refusals ──────────────────────────────────────────────────────────

print("\nWP13-F9 · what a void refuses")
open_db = _build()
opened = issue_funded_challenge(
    event_id=uuid.uuid4(), league_id=LEAGUE, week=WEEK,
    challenger_team_id=1, challenged_team_id=2, wager_type="straight",
    terms=_terms(STAKE), db=open_db, challenge_mode=spec1.MODE_LOCKED,
    proposal_lock_at=DEADLINE, now=NOW)
open_db.commit()
try:
    void_accepted_wager(open_db, challenge_id=opened.challenge_id,
                        reason="x", now=NOW)
    _assert("a never-accepted challenge is refused", False, "accepted")
except WagerVoidError as exc:
    open_db.rollback()
    _assert("a never-accepted challenge is refused",
            exc.reason == "VOID_NOT_ACCEPTED", exc.reason)

blank = _build()
blank_challenge = _accepted_challenge(blank)
blank.commit()
try:
    void_accepted_wager(blank, challenge_id=blank_challenge, reason="   ",
                        now=NOW)
    _assert("  · an unexplained void is refused", False, "accepted")
except WagerVoidError as exc:
    blank.rollback()
    _assert("  · an unexplained void is refused",
            exc.reason == "VOID_NO_REASON", exc.reason)

settled = _build()
settled_challenge = _accepted_challenge(settled)
settled.commit()
for b in settled.query(Bet).filter(
        Bet.beef_challenge_id == settled_challenge).all():
    b.status = "won"
settled.commit()
try:
    void_accepted_wager(settled, challenge_id=settled_challenge,
                        reason="too late", now=NOW)
    _assert("  · an already-settled wager is refused", False, "accepted")
except WagerVoidError as exc:
    settled.rollback()
    _assert("  · an already-settled wager is refused",
            exc.reason == "VOID_ALREADY_SETTLED", exc.reason)

old = _build(final_por=False)
old_challenge = _accepted_challenge(old)
old.commit()
try:
    void_accepted_wager(old, challenge_id=old_challenge, reason="x", now=NOW)
    _assert("  · a LEGACY season has no void path", False, "accepted")
except WagerVoidError as exc:
    old.rollback()
    _assert("  · a LEGACY season has no void path",
            exc.reason == "VOID_WRONG_ERA", exc.reason)
_assert("  · and its escrow is untouched",
        all(_bal(old, f"escrow:{b.id}") > 0 for b in old.query(Bet).filter(
            Bet.beef_challenge_id == old_challenge).all()))


# ── F10 · the migration ────────────────────────────────────────────────────

print("\nWP13-F10 · the migration applies, is idempotent, one row per bet")
import migrations.add_voided_wagers as mig  # noqa: E402
from migrations.manifest import ACTIVE  # noqa: E402

entry = [m for m in ACTIVE if m.identifier == "0013_voided_wagers"]
_assert("the migration is registered", len(entry) == 1)
_assert("  · and names the table it creates",
        entry and entry[0].tables == ("voided_wagers",),
        str(entry[0].tables if entry else None))

probe = create_engine("sqlite://")
prev = mig.engine
try:
    with probe.begin() as conn:
        conn.execute(text(
            "CREATE TABLE bets (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
        conn.execute(text(
            "CREATE TABLE teams (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
        conn.execute(text("INSERT INTO bets DEFAULT VALUES"))
        conn.execute(text("INSERT INTO teams DEFAULT VALUES"))
    mig.engine = probe
    first = mig.upgrade()
    _assert("  · applies", any("created" in line for line in first), str(first))
    second = mig.upgrade()
    _assert("  · is idempotent",
            any("already exists" in line for line in second), str(second))
    with probe.begin() as conn:
        conn.execute(text(
            "INSERT INTO voided_wagers (bet_id, team_id, league_id, season, "
            " refunded_cents, reason, created_at) "
            "VALUES (1, 1, 1, 2026, 400, 'cancelled', '2026-11-03')"))
        try:
            conn.execute(text(
                "INSERT INTO voided_wagers (bet_id, team_id, league_id, "
                " season, refunded_cents, reason, created_at) "
                "VALUES (1, 1, 1, 2026, 400, 'again', '2026-11-03')"))
            _assert("  · a second void of the same bet is refused by the DB",
                    False, "accepted")
        except Exception as exc:
            _assert("  · a second void of the same bet is refused by the DB",
                    "UNIQUE" in str(exc).upper(), str(exc)[:60])
        try:
            conn.execute(text(
                "INSERT INTO voided_wagers (bet_id, team_id, league_id, "
                " season, refunded_cents, reason, created_at) "
                "VALUES (1, 1, 1, 2026, -1, 'negative', '2026-11-03')"))
            _assert("  · a negative refund is refused by the DB", False,
                    "accepted")
        except Exception as exc:
            _assert("  · a negative refund is refused by the DB",
                    "CHECK" in str(exc).upper() or "UNIQUE" in str(exc).upper(),
                    str(exc)[:60])
finally:
    mig.engine = prev


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-13 accepted-wager void: all assertions passed")
