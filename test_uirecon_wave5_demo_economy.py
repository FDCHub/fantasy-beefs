#!/usr/bin/env python3
"""
test_uirecon_wave5_demo_economy.py — what the Status enrichment cost, measured.

REQUIRES POSTGRESQL, and a disposable one. It seeds a whole showcase, answers a
challenge through the real command, and resets — none of which belongs anywhere
near a database anybody cares about. Point `DATABASE_URL` at a throwaway:

    DATABASE_URL=postgresql://.../fs_w5econ_test python test_uirecon_wave5_demo_economy.py

WHAT THIS PROVES.

  §18 of the Wave 5 brief asks for an explicit before/after on every economic
  figure the demo publishes, because the wave adds lifecycle records to a fixture
  whose standings, championship and Pool results are asserted elsewhere and must
  not move. The answer has to be measured rather than reasoned about: an offered
  challenge SHOULD be inert, and "should" is what this file replaces.

  THE COMPARISON IS AGAINST A LEAGUE THAT WAS PLAYED WITH. Seeding and measuring
  once would only prove the seeder is inert. The interesting question is whether
  the demo survives a visitor — so the run below accepts the incoming Matchup
  through `accept_funded_challenge`, the same command `/beef/respond` reaches,
  and then requires `ensure_canonical` to put every figure back WITHOUT
  rebuilding. A rebuild would answer with a new league id, a new Pool rotation
  and a different champion, which is the failure `demo/reset.py` exists to avoid.

  DECLINE AND COUNTER ARE ANSWERED TOO. They are different lifecycle exits with
  different ledger consequences — a decline refunds the issuer by exact reverse
  legs, a counter mints a second proposal version — and a restore that handled
  only acceptance would leave the demo degraded by either of the other two.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
    print("REQUIRES POSTGRESQL — set DATABASE_URL to a disposable database.")
    sys.exit(2)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


from db.schema import (  # noqa: E402
    Base, BeefChallenge, Bet, PoolClaim, PoolInstance, SessionLocal, Team, User,
    engine,
)
from demo import reset as reset_mod  # noqa: E402
from demo import showcase  # noqa: E402
from demo.seed import DEMO_USER_EMAIL, find_showcase, seed  # noqa: E402
from ledger.ledger import balance_of, trial_balance  # noqa: E402
from reports.action_read_model import gm_action_state  # noqa: E402
from reports.standings_read_model import league_standings  # noqa: E402


def _championship_scores() -> object:
    """The frozen FantasyStakes Championship scores, if the season froze any.

    IN ITS OWN SESSION. A season that has not reached the freeze has no table to
    read on some builds, and a failed statement poisons the transaction it ran
    in — so asking this inside the main snapshot took every figure after it down
    with it.
    """
    from sqlalchemy import text
    with SessionLocal() as db:
        try:
            return [tuple(r) for r in db.execute(text(
                "SELECT team_id, score_cents FROM "
                "fantasystakes_championship_score ORDER BY team_id")).fetchall()]
        except Exception:
            db.rollback()
            return "none frozen"


def snapshot() -> dict:
    """Every figure §18 names, from one session."""
    champ = _championship_scores()
    with SessionLocal() as db:
        league = find_showcase(db)
        teams = sorted(db.query(Team).filter(Team.league_id == league.id).all(),
                       key=lambda t: t.team_name)
        seat = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
        standings = league_standings(db, league_id=league.id).overall
        instances = (db.query(PoolInstance)
                     .filter(PoolInstance.league_id == league.id)
                     .order_by(PoolInstance.week, PoolInstance.slot).all())

        live = [i for i in instances if i.week == league.provider_current_week]
        open_pick = []
        for inst in sorted(live, key=lambda i: i.slot):
            mine = (db.query(PoolClaim)
                    .filter(PoolClaim.pool_instance_id == inst.id,
                            PoolClaim.team_id == seat.team_id).first())
            open_pick.append((inst.slot, inst.definition_key,
                              None if mine is None else mine.selected_subject_id))

        return {
            "league_id": league.id,
            "current_week": league.provider_current_week,
            "trial_balance": trial_balance(),
            "wallets": sorted((t.team_name, balance_of(f"wallet:{t.id}"))
                              for t in teams),
            "standings": [(r.team_name, r.versus_wins, r.versus_losses,
                           r.pool_wins, r.versus_net_cents, r.pool_net_cents,
                           r.net_cents) for r in standings],
            "championship_scores": champ,
            "pool_instances": len(instances),
            "pool_claims": (db.query(PoolClaim).join(
                PoolInstance, PoolClaim.pool_instance_id == PoolInstance.id)
                .filter(PoolInstance.league_id == league.id).count()),
            "pool_pots": sorted((i.week, i.slot, balance_of(f"pool:{i.id}"))
                                for i in instances),
            "pool_settlements": [
                (i.week, i.slot, i.definition_key, i.settlement_classification,
                 i.distributed_cents, i.rollover_cents, bool(i.settled))
                for i in instances],
            "matchup_settlements": sorted(
                (b.beef_challenge_id, b.wallet_id, float(b.amount),
                 float(b.odds), b.status)
                for b in db.query(Bet).filter(
                    Bet.beef_challenge_id.isnot(None)).all()),
            "week11_open_pick": open_pick,
            "fingerprint": reset_mod.canonical_fingerprint(db, league),
        }


def rails() -> dict:
    with SessionLocal() as db:
        league = find_showcase(db)
        seat = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
        state = gm_action_state(db, team_id=seat.team_id, league_id=league.id,
                                week=league.provider_current_week)
        out: dict = {}
        for card in state.cards:
            out[card.section] = out.get(card.section, 0) + 1
        return out


def incoming_challenge_id() -> int | None:
    with SessionLocal() as db:
        seat = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
        row = (db.query(BeefChallenge)
               .filter(BeefChallenge.challenged_team_id == seat.team_id,
                       BeefChallenge.response_status == "offered").first())
        return row.id if row else None


def acting_team_id() -> int:
    with SessionLocal() as db:
        return db.query(User).filter(
            User.email == DEMO_USER_EMAIL).first().team_id


def compare(before: dict, after: dict, tag: str) -> None:
    """Every figure, field by field. `fingerprint` is compared separately."""
    for key in sorted(k for k in before if k != "fingerprint"):
        _assert(f"{tag} — {key} is unchanged", before[key] == after[key],
                "" if before[key] == after[key]
                else f"{str(before[key])[:90]} -> {str(after[key])[:90]}")


# ── Build ───────────────────────────────────────────────────────────────────

Base.metadata.create_all(bind=engine)
print("seeding a showcase…")
seed()

_section("§1 · the pristine showcase")

PRISTINE = snapshot()
_assert("the trial balance is zero", PRISTINE["trial_balance"] == 0,
        str(PRISTINE["trial_balance"]))
with SessionLocal() as _db:
    _assert("the pristine showcase is canonical",
            reset_mod.is_canonical(_db, find_showcase(_db)),
            json.dumps(PRISTINE["fingerprint"], sort_keys=True))
_assert("the fingerprint carries the fixture's open-negotiation count",
        PRISTINE["fingerprint"]["offered_challenges"]
        == len(showcase.VISITOR_OPEN_NEGOTIATIONS),
        str(PRISTINE["fingerprint"]["offered_challenges"]))

RAILS = rails()
_assert("all four Status rails are populated",
        all(RAILS.get(r, 0) >= 1
            for r in ("action", "waiting", "live", "completed")),
        json.dumps(RAILS, sort_keys=True))
_assert("the Wave 4 Matchups are intact — one live, seven completed",
        RAILS.get("live") == 1 and RAILS.get("completed") == 7,
        json.dumps(RAILS, sort_keys=True))
_assert("the Wave 3 Prop Pool pick is still open",
        any(pick is None for _s, _k, pick in PRISTINE["week11_open_pick"]),
        str(PRISTINE["week11_open_pick"]))


# ── The three answers a visitor can give ────────────────────────────────────

def _cycle(name: str, answer) -> None:
    """Answer the incoming Matchup, reset, and require everything back."""
    _section(f"§2 · a visitor {name}s the incoming Matchup, then the demo resets")

    challenge_id = incoming_challenge_id()
    _assert(f"there is an incoming Matchup to {name}", challenge_id is not None,
            str(challenge_id))
    if challenge_id is None:
        return

    with SessionLocal() as db:
        answer(db, challenge_id, acting_team_id())

    after_answer = rails()
    _assert(f"{name} moved the card off ACTION REQUIRED",
            after_answer.get("action", 0) == 0, json.dumps(after_answer))
    _assert("and the trial balance still balances", trial_balance() == 0,
            str(trial_balance()))

    with SessionLocal() as db:
        _assert("the fingerprint notices the demo is no longer pristine",
                not reset_mod.is_canonical(db, find_showcase(db)))

    outcome = reset_mod.ensure_canonical()
    _assert("the reset restored in place rather than rebuilding",
            outcome.get("action") == "restored", str(outcome.get("action")))
    _assert("and the league kept its id",
            outcome.get("league_id") == PRISTINE["league_id"],
            f"{outcome.get('league_id')} vs {PRISTINE['league_id']}")

    with SessionLocal() as db:
        _assert("the showcase is canonical again",
                reset_mod.is_canonical(db, find_showcase(db)))
    _assert("the four rails are back",
            rails() == RAILS, json.dumps(rails(), sort_keys=True))

    compare(PRISTINE, snapshot(), f"after {name}+reset")


def _accept(db, challenge_id: int, team_id: int) -> None:
    from economy.challenge_funding import accept_funded_challenge
    accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=challenge_id,
                            actor_team_id=team_id, db=db)


def _decline(db, challenge_id: int, team_id: int) -> None:
    from economy.challenge_funding import decline_funded_challenge
    decline_funded_challenge(event_id=uuid.uuid4(), challenge_id=challenge_id,
                             actor_team_id=team_id, db=db)


def _counter(db, challenge_id: int, team_id: int) -> None:
    from beefs import proposal_lifecycle as spec1
    from economy.challenge_funding import counter_funded_challenge
    counter_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=challenge_id,
        actor_team_id=team_id,
        terms=spec1.ProposalTerms(
            anchor_stake_cents=700, quoted_derived_stake_cents=700,
            quoted_funded_pot_cents=1400, anchor_odds=2.0, derived_odds=2.0,
            anchor_moneyline=100, derived_moneyline=100,
            anchor_win_probability=0.5, derived_win_probability=0.5,
            pricing_model_id=spec1.MODE_LOCKED),
        db=db)


_cycle("accept", _accept)
_cycle("decline", _decline)
_cycle("counter", _counter)


# ── Repeat entry ────────────────────────────────────────────────────────────

_section("§3 · repeated entry keeps one league and does not rebuild it")

_ids = []
_actions = []
for _ in range(3):
    _out = reset_mod.ensure_canonical()
    _ids.append(_out.get("league_id"))
    _actions.append(_out.get("action"))

_assert("every entry answers with the same league id",
        len(set(_ids)) == 1 and _ids[0] == PRISTINE["league_id"], str(_ids))
_assert("and an untouched showcase is never rebuilt",
        all(a == "none" for a in _actions), str(_actions))
_assert("the trial balance is still zero", trial_balance() == 0,
        str(trial_balance()))

compare(PRISTINE, snapshot(), "after repeated entry")


# ── Result ─────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
if _failures:
    print(f"WAVE 5 DEMO ECONOMY — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
print("WAVE 5 DEMO ECONOMY — ALL PASSED")
