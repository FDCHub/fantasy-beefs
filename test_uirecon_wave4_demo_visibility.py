#!/usr/bin/env python3
"""
test_uirecon_wave4_demo_visibility.py — the demo's Matchups, made visible.

Run:  python test_uirecon_wave4_demo_visibility.py
With PostgreSQL (the functional tier):
      UIRECON_W4V_PG_URL=postgresql://... python test_uirecon_wave4_demo_visibility.py

THE DEFECT.

  `beefs/beef_engine.issue_challenge` never filled `beef_challenges.league_id`,
  though both `Team` rows — whose `league_id` is NOT NULL — were already loaded
  two lines above the constructor. Every matchup the showcase played was
  therefore a wager that no league owned. `reports/action_read_model` filters a
  GM's Action by league, correctly, so the demo's acting GM read zero Matchups
  while holding seven settled wagers and one live one in the database. Wave 4's
  FANTASYSTAKES MATCHUPS carousel had nothing real to draw, and Wave 5's Status
  would have had no lifecycle to demonstrate.

WHAT THIS WAVE CHANGED, AND WHAT IT DELIBERATELY DID NOT.

  1 · THE LEAGUE IS DERIVED, NOT SUPPLIED. `issue_challenge` reads it off the
      participants, and refuses a pair that disagrees — which is the rule
      `api/main.py`'s governed route already enforces as `cross_league_challenge`.
      No signature changed, no caller learned a new argument, and no economic
      expression in that file was touched. §2 below pins that last claim.

  2 · THE READ MODEL LEARNED THE SECOND RECORD SHAPE IT ALREADY HALF-READ.
      `betting/versus_legacy_guard` classifies `beefs.beef_engine` as a GOVERNED
      FantasyStakes path — it is the single-GM `POST /bets/place` product that
      guard exists to refuse, not this one. An engine-written matchup funds,
      settles and posts to the ledger exactly as a proposal-lifecycle one does;
      it simply records its state in `status` and its terms in its own columns.
      The read model answered only from the proposal, so those wagers reported a
      $0 stake, no odds and no line, and a live one fell through to COMPLETED.

      THE GOVERNED COLUMNS STILL WIN. Every legacy read below is reached only
      when there is no proposal to read, so no proposal-lifecycle wager's
      classification, terms or money can move. §3 pins that.

  3 · THE NET IS THE LEDGER'S. `_settlement` computed `stake x odds - stake`,
      a payout rule `betting/settlement_engine` retired — it credits the winner
      BOTH escrow balances and says so: "the fix itself, not the 2x-amount
      shortcut it replaces". Action and Standings therefore disagreed about the
      same GM's same wagers. §4 asserts they now agree, against real postings.

WHAT WAS CONSIDERED AND REJECTED. Moving the showcase onto
`economy.challenge_funding.issue_funded_challenge` would have produced
proposal-shaped rows — and a different product. The legacy engine stakes both
GMs equally and varies the odds; the funded lifecycle quotes an odds-derived
Derived stake. Every GM's exposure, every settlement, the standings and the
championship would have moved. That is a change to wager economics, which this
wave was told to preserve.
"""

from __future__ import annotations

import ast
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


# ── §1 · The league is carried, and no migration was needed ─────────────────

_section("§1 · the challenge carries the league it was played in")

_engine = _read("beefs", "beef_engine.py")

_assert("issue_challenge sets league_id on the row it creates",
        "league_id            = challenger_team.league_id," in _engine)
_assert("it is DERIVED from the participants, not added to the signature",
        "league_id" not in _engine.split("def issue_challenge(")[1]
        .split(") -> ChallengeOut:")[0])
_assert("a cross-league pair is refused rather than assigned a league",
        "challenger_team.league_id != challenged_team.league_id" in _engine)

# The column already existed and is nullable — the finding said so and the
# schema confirms it. A migration here would have been a schema change this
# wave had no reason to make.
_schema = _read("db", "schema.py")
_assert("the column was already on the authoritative schema",
        re.search(r"league_id\s*=\s*Column\(Integer,\s*ForeignKey\("
                  r"\"leagues\.id\",\s*name=\"fk_beef_challenge_league\"\)",
                  _schema) is not None)
_assert("and no new migration was written for it",
        not any(f.startswith("migrate_uirecon")
                for f in os.listdir(os.path.join(ROOT, "db", "migrations"))))


# ── §2 · Nothing economic moved in the engine ───────────────────────────────

_section("§2 · the engine change is the league derivation and nothing else")

# THE CLAIM STATED AS CODE. Wave 4's frozen-module guard names
# `beefs/beef_engine.py` as an authorised exception; this is what that exception
# is allowed to contain. Anything the diff ADDS that mentions money, odds or a
# payout is a scope breach regardless of how correct it looks in isolation.
import subprocess  # noqa: E402


def _added_code_lines(path: str) -> list[str]:
    """The non-comment code lines this branch ADDS to one file."""
    base = subprocess.run(["git", "log", "-1", "--format=%H", "--", path],
                          cwd=ROOT, capture_output=True, text=True).stdout.strip()
    diff = subprocess.run(["git", "diff", "HEAD", "--", path],
                          cwd=ROOT, capture_output=True, text=True).stdout
    if not diff.strip():
        # Already committed — compare the commit that carries this wave.
        subject = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.strip()
        if "demo matchup visibility" in subject:
            diff = subprocess.run(["git", "show", "HEAD", "--", path],
                                  cwd=ROOT, capture_output=True, text=True).stdout
    out = []
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:].strip()
        if not body or body.startswith("#"):
            continue
        out.append(body)
    return out


_added = _added_code_lines("beefs/beef_engine.py")
_assert("the engine diff is small and reviewable", len(_added) <= 12,
        f"{len(_added)} added code line(s)")

_MONEY = ("amount", "odds", "payout", "stake", "cents", "MIN_BET", "wallet",
          "escrow", "ledger", "moneyline", "balance")
_economic = [ln for ln in _added
             if any(w in ln for w in _MONEY)]
_assert("no money, odds or payout expression was added to the engine",
        not _economic, " | ".join(_economic)[:150])
_assert("every added line concerns the league and nothing else",
        all("league" in ln.lower() or ln.startswith(("raise", "f\"", '"', ")"))
            for ln in _added), " | ".join(_added)[:150])


# ── §3 · The governed path is untouched by the legacy reads ────────────────

_section("§3 · a proposal-lifecycle wager cannot be affected")

_rm = _read("reports", "action_read_model.py")

_assert("the legacy state translation is consulted only when there is none "
        "governed",
        "if challenge.response_status is not None:" in _rm
        and "return challenge.response_status" in _rm)
_assert("the legacy vocabulary maps one-to-one onto the governed one",
        all(w in _rm for w in ('"pending":   OFFERED',
                               '"countered": COUNTERED',
                               '"accepted":  ACCEPTED',
                               '"declined":  DECLINED',
                               '"expired":   EXPIRED')))
_assert("legacy terms are read only when there is no proposal",
        "_proposal_terms(proposal) if proposal is not None" in _rm
        and "else _legacy_terms(db, challenge)" in _rm)
_assert("the league filter is intact and unweakened",
        "BeefChallenge.league_id == league_id" in _rm)
_assert("no NULL league is special-cased in the read",
        "league_id is None" not in _rm and "league_id.is_(None)" not in _rm)

# THE READ MODEL STILL WRITES NOTHING.
_MUTATIONS = ("db.add(", "db.commit()", "db.delete(", "db.flush()", "db.merge(")
_hits = [m for m in _MUTATIONS if m in _rm]
_assert("the read model still mutates nothing", not _hits, ", ".join(_hits))
_assert("and its only SQL is a SELECT",
        not re.search(r"text\(\s*\"(?!SELECT)", _rm))


# ── §4 · Against real showcase data ────────────────────────────────────────

_section("§4 · the served answer agrees with the persisted records")


def _pg_url() -> str | None:
    return os.environ.get("UIRECON_W4V_PG_URL")


def _functional() -> None:
    url = _pg_url()
    if not url:
        print("  [SKIP] functional tier — set UIRECON_W4V_PG_URL to a "
              "disposable PostgreSQL holding a seeded showcase")
        return

    from sqlalchemy import create_engine, text as _text
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(url)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        from db.schema import BeefChallenge, Team, User
        from demo.seed import DEMO_USER_EMAIL, find_showcase
        from reports.action_read_model import gm_action_state
        from reports.standings_read_model import league_standings

        league = find_showcase(db)
        _assert("a showcase league is present", league is not None)
        if league is None:
            return

        # 1 · every showcase challenge belongs to the showcase league, and no
        #     other league received one.
        rows = db.execute(_text(
            "SELECT league_id, COUNT(*) FROM beef_challenges GROUP BY league_id"
        )).fetchall()
        by_league = {r[0]: r[1] for r in rows}
        _assert("no showcase challenge is left without a league",
                None not in by_league, str(by_league))
        _assert("every challenge belongs to the showcase league",
                set(by_league) == {league.id}, str(by_league))

        team_ids = {t.id for t in db.query(Team)
                    .filter(Team.league_id == league.id).all()}
        stray = (db.query(BeefChallenge)
                 .filter(BeefChallenge.league_id == league.id)
                 .filter(~BeefChallenge.challenger_team_id.in_(team_ids))
                 .count())
        _assert("no challenge names a team outside the league it was filed to",
                stray == 0, str(stray))

        # 2 · the acting GM's Action tab reports their real wagers.
        seat = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
        state = gm_action_state(db, team_id=seat.team_id, league_id=league.id,
                                week=league.provider_current_week)
        _assert("the acting GM's Matchups are visible at all",
                len(state.cards) > 0, f"{len(state.cards)} card(s)")

        persisted = (db.query(BeefChallenge)
                     .filter(BeefChallenge.league_id == league.id)
                     .filter((BeefChallenge.challenger_team_id == seat.team_id)
                             | (BeefChallenge.challenged_team_id == seat.team_id))
                     .count())
        _assert("and every persisted Matchup of theirs is reported",
                len(state.cards) == persisted,
                f"{len(state.cards)} reported vs {persisted} persisted")

        settled = [c for c in state.cards if c.settled]
        _assert("settled Matchups are reported as COMPLETED",
                all(c.section == "completed" for c in settled),
                str({c.section for c in settled}))
        live = [c for c in state.cards if not c.settled]
        _assert("an accepted, unsettled Matchup sits on LIVE rather than "
                "falling through to COMPLETED",
                all(c.section == "live" for c in live),
                str([(c.week, c.section) for c in live]))

        # 3 · no cross-league leak.
        _assert("no reported Matchup involves a team outside the league",
                all(c.opponent_team_id in team_ids for c in state.cards),
                str([c.opponent_team_id for c in state.cards]))

        # 4 · the terms are the persisted ones, not zeroes.
        _assert("every card reports the stake that was actually placed",
                all(c.your_stake_cents > 0 for c in state.cards),
                str([c.your_stake_cents for c in state.cards]))
        _assert("every card reports the odds that were actually struck",
                all(c.your_odds for c in state.cards),
                str([c.your_odds for c in state.cards]))

        for card in state.cards:
            row = (db.query(BeefChallenge)
                   .filter(BeefChallenge.id == card.challenge_id).one())
            bets = db.execute(_text(
                "SELECT b.amount, b.odds, b.status FROM bets b "
                "JOIN wallets w ON w.id = b.wallet_id "
                "WHERE b.beef_challenge_id = :cid AND w.team_id = :tid"),
                {"cid": card.challenge_id, "tid": seat.team_id}).fetchall()
            if not bets:
                continue
            amount, odds, status = bets[0]
            _assert(f"challenge {card.challenge_id} — the reported stake is the "
                    f"placed stake",
                    card.your_stake_cents == int(round(float(amount) * 100)),
                    f"{card.your_stake_cents} vs {amount}")
            _assert(f"challenge {card.challenge_id} — the reported odds are the "
                    f"struck odds",
                    abs(float(card.your_odds) - float(odds)) < 1e-9,
                    f"{card.your_odds} vs {odds}")
            _assert(f"challenge {card.challenge_id} — the reported market is the "
                    f"persisted market",
                    card.wager_type == row.bet_type,
                    f"{card.wager_type} vs {row.bet_type}")
            if row.line is not None:
                _assert(f"challenge {card.challenge_id} — the reported line is "
                        f"the persisted line", card.line == row.line,
                        f"{card.line} vs {row.line}")
            if status not in ("pending", None):
                _assert(f"challenge {card.challenge_id} — the reported outcome "
                        f"is the persisted status", card.outcome == status,
                        f"{card.outcome} vs {status}")

        # 5 · THE CREDIT OUTCOME AGREES WITH THE LEDGER, per card and in total.
        for card in settled:
            bet = db.execute(_text(
                "SELECT b.id, b.amount FROM bets b JOIN wallets w "
                "ON w.id = b.wallet_id WHERE b.beef_challenge_id = :cid "
                "AND w.team_id = :tid"),
                {"cid": card.challenge_id, "tid": seat.team_id}).fetchone()
            if bet is None:
                continue
            credited = db.execute(_text(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
                "WHERE account = :wallet AND posting_id IN ("
                "  SELECT posting_id FROM ledger_entries "
                "  WHERE account = :escrow AND door = 'wager_settled')"),
                {"wallet": f"wallet:{seat.team_id}",
                 "escrow": f"escrow:{bet[0]}"}).scalar()
            expected = int(credited or 0) - int(round(float(bet[1]) * 100))
            _assert(f"challenge {card.challenge_id} — the reported credit "
                    f"outcome is the posting's",
                    card.net_cents == expected,
                    f"{card.net_cents} vs {expected}")

        # 6 · AND THE TWO READ MODELS NOW AGREE. Standings reads the ledger
        #     doors; Action reads the postings. A disagreement here is the
        #     defect §4 of the header describes, restated as money.
        standings = {r.team_id: r for r in
                     league_standings(db, league_id=league.id).overall}
        action_net = sum(c.net_cents or 0 for c in settled)
        _assert("Action and Standings report the same competitive net",
                action_net == standings[seat.team_id].versus_net_cents,
                f"action {action_net} vs standings "
                f"{standings[seat.team_id].versus_net_cents}")

        _assert("reading Action mutates nothing",
                not db.new and not db.dirty and not db.deleted,
                f"new={len(db.new)} dirty={len(db.dirty)}")
    finally:
        db.close()
        engine.dispose()


try:
    _functional()
except Exception as _exc:                                   # pragma: no cover
    _assert("the functional tier could run", False, repr(_exc))


# ── Result ─────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
if _failures:
    print(f"DEMO MATCHUP VISIBILITY — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
print("DEMO MATCHUP VISIBILITY — ALL PASSED")
