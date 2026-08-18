#!/usr/bin/env python3
"""RC2 NEW-1 certification — the FantasyStakes Versus product boundary.

THE LOCKED PRODUCT DECISION. FantasyStakes competition is GM-versus-GM matchups
and GM-entered prop pools. There is no house and no single-GM wagering product.
A plain wager created through the legacy `POST /bets/place` path
(`beef_challenge_id IS NULL`) is therefore NOT FantasyStakes competition.

WHAT WAS ACTUALLY WRONG. `wager_placed` and `wager_settled` are shared doors: a
governed matchup bet and a legacy plain wager both post under them, and the
Championship Score read model summed those doors broadly. Nothing durable in the
LEDGER separates the two — `ledger_entries` carries account, amount, door,
posting_id and batch_id, and no bet id. What does separate them is
`Bet.beef_challenge_id`, and the fact that every posting either path makes for a
bet carries that bet's own `escrow:{bet_id}` leg. That pair is what this suite
holds the implementation to.

Two independent guarantees are certified here:

  · the legacy route cannot create a new plain wager in a governed league
  · a plain wager that already exists contributes nothing competitive

The second matters on its own: refusing new wagers does not retroactively
un-count wagers a league placed before it adopted FantasyStakes.
"""
from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'rc2-boundary.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone  # noqa: E402

from db.schema import (  # noqa: E402
    Base, BeefChallenge, Bet, League, LeagueSeasonEconomyConfig, Matchup,
    SeasonAllocation, SessionLocal, Team, Wallet, engine,
)
from betting.bet_engine import _place_bet  # noqa: E402
from betting.versus_legacy_guard import (  # noqa: E402
    LegacyVersusPathRefused, assert_legacy_wager_path_allowed,
    fantasystakes_governance_markers,
)
from economy.fantasystakes_championship_allocation import pot_account  # noqa: E402
from economy.rc2_season_activation import (  # noqa: E402
    activate_fantasystakes_championship_stage,
)
from ledger.ledger import (  # noqa: E402
    APPROVED_BAB_TOPOFF_DOOR, SEASON_ALLOCATION_DOOR, balance_of,
    create_ledger_table, post as ledger_post, trial_balance,
)
from reports.championship_read_model import (  # noqa: E402
    FantasyStakesChampionshipError, FantasyStakesChampionshipFreeze,
    FantasyStakesChampionshipScore, REASON_POSTSEASON_CONTAMINATED,
    REASON_REGULAR_VERSUS_OPEN, freeze_fantasystakes_championship,
)
from reports.standings_read_model import league_standings  # noqa: E402

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


def build(name: str, *, governed: bool = True, activate: bool = True):
    """A league, optionally carrying FantasyStakes governance state."""
    with SessionLocal() as db:
        lg = League(season=SEASON, name=name, projection_source="fantasypros",
                    start_week=1, playoff_start_week=CUT, season_final_week=17,
                    provider_current_week=CUT)
        db.add(lg)
        db.flush()
        L = lg.id
        T = []
        for i in range(4):
            t = Team(league_id=L, team_name=f"{name}{i}", owner=f"Owner {i}",
                     email=f"{name.lower()}-{L}-{i}@example.test")
            db.add(t)
            db.flush()
            T.append(t.id)
            db.add(Wallet(team_id=t.id, balance=0.0))
            # Spendable Credits that are NOT competitive, so a wallet-funded
            # stake is possible without pre-loading any competitive result.
            ledger_post([(f"bab_issuance:{L}:{SEASON}", -50_000),
                         (f"wallet:{t.id}", 50_000)],
                        door=APPROVED_BAB_TOPOFF_DOOR, session=db)
        if governed:
            db.add(LeagueSeasonEconomyConfig(
                league_id=L, season=SEASON, weekly_bet_minimum_cents=1000,
                championship_contribution_cents=8000, skunk_fee_cents=1000,
                regular_season_week_count=14, active_team_count=4,
                start_week_used=1, playoff_start_week_used=CUT, frozen_at=None))
            for tid in T:
                db.add(SeasonAllocation(league_id=L, team_id=tid, season=SEASON,
                                        buyin_cents=22_000, min_reserve_cents=14_000,
                                        reserve_cents=8_000))
                ledger_post([(f"season_issuance:{L}:{SEASON}", -22_000),
                             (f"min_reserve:{tid}", 14_000),
                             (f"reserve:{tid}", 8_000)],
                            door=SEASON_ALLOCATION_DOOR, session=db)
        db.commit()
    if governed and activate:
        with SessionLocal() as db:
            activate_fantasystakes_championship_stage(L, db)
    return L, T


def matchup(L: int, T: list[int], week: int) -> int:
    with SessionLocal() as db:
        m = Matchup(league_id=L, week=week, home_team_id=T[0], away_team_id=T[1],
                    home_score=0, away_score=0)
        db.add(m)
        db.flush()
        mid = m.id
        db.commit()
    return mid


def governed_matchup_bet(L, T, week, *, settle: bool, winner_first=True):
    """A GOVERNED FantasyStakes matchup: two GMs, one BeefChallenge, real money.

    Built with the certified posting shapes rather than by calling the challenge
    engine, so this suite stays about the product boundary and not about
    challenge negotiation. Both sides stake from wallet into their own escrow
    under `wager_placed`, exactly as `beefs/beef_engine` does.
    """
    mid = matchup(L, T, week)
    with SessionLocal() as db:
        bc = BeefChallenge(league_id=L, challenger_team_id=T[0],
                           challenged_team_id=T[1], week=week, bet_type="straight",
                           amount=STAKE / 100, challenger_odds=1.9, challenged_odds=1.9,
                           challenger_moneyline=-110, challenged_moneyline=-110,
                           status="accepted", expires_at=datetime.now(timezone.utc),
                           staleness_warning=0)
        db.add(bc)
        db.flush()
        ids = []
        for tid in (T[0], T[1]):
            w = db.query(Wallet).filter(Wallet.team_id == tid).first()
            b = Bet(matchup_id=mid, wallet_id=w.id, bet_type="straight",
                    amount=STAKE / 100, odds=1.9, status="pending",
                    beef_challenge_id=bc.id)
            db.add(b)
            db.flush()
            ids.append(b.id)
            ledger_post([(f"wallet:{tid}", -STAKE), (f"escrow:{b.id}", STAKE)],
                        door="wager_placed", session=db)
        bc.challenger_bet_id, bc.challenged_bet_id = ids
        db.commit()
    if not settle:
        return ids
    win_i, lose_i = (0, 1) if winner_first else (1, 0)
    with SessionLocal() as db:
        ledger_post([(f"escrow:{ids[win_i]}", -STAKE),
                     (f"escrow:{ids[lose_i]}", -STAKE),
                     (f"wallet:{T[win_i]}", 2 * STAKE)],
                    door="wager_settled", session=db)
        for i, st in ((win_i, "won"), (lose_i, "lost")):
            db.query(Bet).filter(Bet.id == ids[i]).update(
                {"status": st, "settled_at": datetime.now(timezone.utc)})
        db.commit()
    return ids


def plain_bet(L, T, week, *, tid=None):
    """A LEGACY plain wager: one GM, no BeefChallenge, the `wager_placed` door."""
    tid = tid if tid is not None else T[0]
    mid = matchup(L, T, week)
    with SessionLocal() as db:
        w = db.query(Wallet).filter(Wallet.team_id == tid).first()
        b = Bet(matchup_id=mid, wallet_id=w.id, bet_type="straight",
                amount=STAKE / 100, odds=1.9, status="pending",
                beef_challenge_id=None)
        db.add(b)
        db.flush()
        bid = b.id
        ledger_post([(f"wallet:{tid}", -STAKE), (f"escrow:{bid}", STAKE)],
                    door="wager_placed", session=db)
        db.commit()
    return bid


def net(L):
    with SessionLocal() as db:
        return {r.team_id: (r.versus_net_cents, r.net_cents, r.versus_wins,
                            r.versus_losses) for r in league_standings(db, league_id=L).rows}


def try_freeze(L):
    with SessionLocal() as db:
        try:
            s = freeze_fantasystakes_championship(db, league_id=L)
            db.commit()
            return s, None
        except FantasyStakesChampionshipError as exc:
            db.rollback()
            return None, exc.reason


# ── A · governed FantasyStakes matchup counts ────────────────────────────────
print("\nRC2-VB-A - governed FantasyStakes matchup counts in Versus net and Score")

La, Ta = build("Gov")
governed_matchup_bet(La, Ta, 5, settle=True)
na = net(La)
check("winner's governed matchup net is +stake",
      na[Ta[0]][0] == STAKE, str(na[Ta[0]]))
check("loser's governed matchup net is -stake",
      na[Ta[1]][0] == -STAKE, str(na[Ta[1]]))
check("governed matchup produces a Versus W/L record",
      na[Ta[0]][2:] == (1, 0) and na[Ta[1]][2:] == (0, 1),
      f"{na[Ta[0]][2:]} / {na[Ta[1]][2:]}")
sa, ra = try_freeze(La)
check("governed matchup result enters the frozen Championship Score",
      sa is not None
      and {r.team_id: r.championship_score_cents for r in sa.rows}[Ta[0]] == STAKE,
      str(ra))
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


# ── B · legacy plain wager contributes nothing ───────────────────────────────
print("\nRC2-VB-B - legacy plain wager is not FantasyStakes competition")

Lb, Tb = build("Plain")
before_b = net(Lb)
bid = plain_bet(Lb, Tb, 5)
after_b = net(Lb)
check("plain wager moved real Credits out of the wallet",
      balance_of(f"wallet:{Tb[0]}") == 50_000 - 22_000 + 8_000 - 8_000 - STAKE
      or balance_of(f"escrow:{bid}") == STAKE,
      f"wallet={balance_of(f'wallet:{Tb[0]}')} escrow={balance_of(f'escrow:{bid}')}")
check("plain wager does NOT change Versus competitive net",
      after_b[Tb[0]][0] == before_b[Tb[0]][0] == 0, str(after_b[Tb[0]]))
check("plain wager does NOT change Championship Score",
      after_b[Tb[0]][1] == before_b[Tb[0]][1] == 0, str(after_b[Tb[0]]))
check("plain wager creates no Versus W/L record",
      after_b[Tb[0]][2:] == (0, 0), str(after_b[Tb[0]][2:]))

# The legacy settlement path posts NOTHING to the ledger — it mutates the stale
# wallet column. Simulate BOTH shapes: today's, and the ledger posting it would
# make if that path were ever corrected. Neither may move the competitive total.
with SessionLocal() as db:
    db.query(Bet).filter(Bet.id == bid).update({"status": "won"})
    db.commit()
check("legacy settlement (no posting) still contributes nothing",
      net(Lb)[Tb[0]][0] == 0, str(net(Lb)[Tb[0]]))

with SessionLocal() as db:
    ledger_post([(f"escrow:{bid}", -STAKE), (f"wallet:{Tb[0]}", STAKE)],
                door="wager_settled", session=db)
    db.commit()
check("a ledger-posting legacy settlement STILL contributes nothing",
      net(Lb)[Tb[0]][0] == 0, str(net(Lb)[Tb[0]]))
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


# ── C · postseason plain wager cannot contaminate the frozen Score ───────────
print("\nRC2-VB-C - postseason plain wager cannot contaminate the frozen Score")

Lc, Tc = build("Post")
plain_bid = plain_bet(Lc, Tc, CUT)                       # postseason week
with SessionLocal() as db:                               # and it "wins"
    # The winning payout drains this bet's own escrow, which is the shape BOTH
    # `wager_settled` posting sites use. A payout under a competitive door that
    # carries no `escrow:{bet_id}` leg is deliberately NOT simulated: no
    # production path creates one (`betting/settlement_engine.py:585,632` are
    # the only two sites and both debit the bet's escrow), and asserting against
    # a shape the product cannot emit would be this suite testing its own
    # invention rather than the code.
    ledger_post([(f"escrow:{plain_bid}", -STAKE),
                 (f"wallet:{Tc[0]}", STAKE)],
                door="wager_settled", session=db)
    db.query(Bet).filter(Bet.id == plain_bid).update({"status": "won"})
    db.commit()
check("a postseason plain wager leaves Versus net untouched",
      net(Lc)[Tc[0]][0] == 0, str(net(Lc)[Tc[0]]))
sc, rc = try_freeze(Lc)
check("freeze is permitted - a plain wager is not postseason FantasyStakes play",
      sc is not None, str(rc))
check("no postseason plain-wager winnings appear in the frozen Score",
      sc is not None and all(r.championship_score_cents == 0 for r in sc.rows),
      str([(r.team_id, r.championship_score_cents) for r in (sc.rows if sc else ())]))
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


# ── D · the legacy route is refused for a governed league ────────────────────
print("\nRC2-VB-D - legacy wager path refused for a governed FantasyStakes league")

Ld, Td = build("Refuse")
with SessionLocal() as db:
    markers = fantasystakes_governance_markers(db, Ld)
check("governance markers identify the league as FantasyStakes-governed",
      len(markers) >= 3, str(markers))

mid_d = matchup(Ld, Td, 5)
bets_before = None
with SessionLocal() as db:
    bets_before = db.query(Bet).count()
entries_before = balance_of(f"wallet:{Td[0]}")
trial_before = trial_balance()

refused = None
with SessionLocal() as db:
    w = db.query(Wallet).filter(Wallet.team_id == Td[0]).first()
    try:
        _place_bet(db, w, STAKE / 100, "straight", mid_d, Td[1], None, None, None,
                   "legacy plain wager", 1.9)
        db.commit()
    except LegacyVersusPathRefused as exc:
        db.rollback()
        refused = exc
check("_place_bet refuses with LegacyVersusPathRefused",
      refused is not None, "no refusal raised")
check("the refusal is a ValueError so the route maps it to HTTP 400",
      isinstance(refused, ValueError))
with SessionLocal() as db:
    bets_after = db.query(Bet).count()
check("no Bet row was created", bets_after == bets_before,
      f"{bets_before} -> {bets_after}")
check("no ledger posting and no Credit movement",
      balance_of(f"wallet:{Td[0]}") == entries_before, str(entries_before))
check("trial balance unchanged and zero",
      trial_balance() == trial_before == 0, str(trial_balance()))

# The guard is an interlock, not a retirement: a league with no FantasyStakes
# governance state is untouched, which is what keeps the RC1 suites valid.
Le, Te = build("Legacy", governed=False)
with SessionLocal() as db:
    check("an ungoverned league carries no markers",
          fantasystakes_governance_markers(db, Le) == (), "markers present")
    assert_legacy_wager_path_allowed(db, Le)
mid_e = matchup(Le, Te, 5)
with SessionLocal() as db:
    w = db.query(Wallet).filter(Wallet.team_id == Te[0]).first()
    b = _place_bet(db, w, STAKE / 100, "straight", mid_e, Te[1], None, None, None,
                   "legacy plain wager", 1.9)
    db.commit()
    legacy_bid = b.id
check("the legacy path still works for an ungoverned league",
      legacy_bid is not None and balance_of(f"escrow:{legacy_bid}") == STAKE,
      str(balance_of(f"escrow:{legacy_bid}")))


# ── E · governed postseason matchup keeps its existing behaviour ─────────────
print("\nRC2-VB-E - governed postseason matchup still gated, still moves Credits")

Lf, Tf = build("PostGov")
governed_matchup_bet(Lf, Tf, 5, settle=True)             # a regular-season result
sf, rf = try_freeze(Lf)
check("championship freezes on the regular-season result",
      sf is not None, str(rf))
frozen_scores = {r.team_id: r.championship_score_cents for r in sf.rows}
wallet_before = balance_of(f"wallet:{Tf[0]}")
governed_matchup_bet(Lf, Tf, CUT, settle=True)           # a POSTSEASON matchup
check("postseason governed matchup moves wallet Credits",
      balance_of(f"wallet:{Tf[0]}") == wallet_before + STAKE,
      f"{wallet_before} -> {balance_of(f'wallet:{Tf[0]}')}")
with SessionLocal() as db:
    reread = {r.team_id: r.championship_score_cents
              for r in freeze_fantasystakes_championship(db, league_id=Lf).rows}
check("frozen Championship Score is unchanged by postseason play",
      reread == frozen_scores, f"{frozen_scores} -> {reread}")

# A late freeze must still refuse while postseason GOVERNED results exist.
Lg, Tg = build("LateFreeze")
governed_matchup_bet(Lg, Tg, CUT, settle=True)
sg, rg = try_freeze(Lg)
check("a late freeze still refuses on postseason governed contamination",
      sg is None and rg == REASON_POSTSEASON_CONTAMINATED, str(rg))
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


# ── F · pending governed regular-season matchup still blocks the freeze ──────
print("\nRC2-VB-F - pending governed regular-season matchup blocks the freeze")

Lh, Th = build("Pending")
governed_matchup_bet(Lh, Th, 5, settle=False)
sh, rh = try_freeze(Lh)
check("freeze refuses while a governed regular-season matchup is unsettled",
      sh is None and rh == REASON_REGULAR_VERSUS_OPEN, str(rh))
with SessionLocal() as db:
    markers_h = (db.query(FantasyStakesChampionshipFreeze)
                 .filter(FantasyStakesChampionshipFreeze.league_id == Lh).count())
    scores_h = (db.query(FantasyStakesChampionshipScore)
                .filter(FantasyStakesChampionshipScore.league_id == Lh).count())
check("refusal wrote no marker and no score rows",
      markers_h == 0 and scores_h == 0, f"{markers_h}/{scores_h}")

# A pending PLAIN wager is not FantasyStakes competition, so it must NOT block.
Li, Ti = build("PendPlain")
plain_bet(Li, Ti, 5)
si, ri = try_freeze(Li)
check("a pending plain wager does not block the freeze",
      si is not None, str(ri))
check("and contributes nothing to the frozen Score",
      si is not None and all(r.championship_score_cents == 0 for r in si.rows),
      str([(r.team_id, r.championship_score_cents) for r in (si.rows if si else ())]))


# ── G · conservation ─────────────────────────────────────────────────────────
print("\nRC2-VB-G - conservation across the whole suite")

check("global trial balance is exactly zero", trial_balance() == 0, str(trial_balance()))
for L, label in ((La, "Gov"), (Lb, "Plain"), (Lc, "Post"), (Ld, "Refuse"),
                 (Lf, "PostGov"), (Lg, "LateFreeze"), (Lh, "Pending"), (Li, "PendPlain")):
    pot = balance_of(pot_account(L, SEASON))
    check(f"{label} pot is the funded 4 x 8000 and was never grown",
          pot == 32_000, str(pot))


print(f"\n{'=' * 64}")
if FAIL:
    print(f"FAILED: {len(FAIL)} assertion(s)")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("PASS: RC2 FantasyStakes Versus product boundary certification")
