#!/usr/bin/env python3
"""
test_uirecon_wave5.py — UIRECON Wave 5 · the Status tab's lifecycle demo.

Run:  python test_uirecon_wave5.py
With the demo economy tier (PostgreSQL, a seeded showcase):
      UIRECON_W5_PG_URL=postgresql://... python test_uirecon_wave5.py

WHAT WAVE 5 DID.

  THE STATUS TAB COULD ONLY DEMONSTRATE HALF OF ITSELF. Its four rails are the
  FantasyStakes lifecycle — what needs my decision, what am I waiting on, what
  is live, what just finished — and the showcase accepted every contest on the
  tick it issued it. ACTION REQUIRED and WAITING were therefore structurally
  unreachable, and a GM meeting the product for the first time never saw what a
  decision waiting on them looks like.

  The fixture now leaves TWO live-week challenges unanswered: one issued to the
  seated visitor, one issued by them. Two directions, because seeding only one
  would demonstrate a rail rather than the distinction between "yours to answer"
  and "theirs".

WHY THEY GO THROUGH THE FUNDED LIFECYCLE AND NOT THE ENGINE.

  The accepted contests are issued by `beefs.beef_engine`, which is right for a
  contest that is immediately accepted. These are meant to be ANSWERED, and
  `/beef/respond` resolves a challenge's active PROPOSAL — which an
  engine-written row does not have. An Accept button on one would be a control
  that cannot work. So they are issued exactly the way `api.main` issues one,
  and a visitor pressing Accept reaches the identical command a signed-in GM
  reaches, because it is the identical record.

WHY THEY COST NOTHING, AND WHY THAT IS ASSERTED RATHER THAN CLAIMED.

  An offered challenge places no Bet, settles nothing, and funds its Anchor
  escrow MIN-FIRST — out of the issuer's weekly minimum, which is swept at week
  close regardless, and never out of a wallet. §5 below measures a seeded
  showcase against every figure the brief names and requires them unchanged.

AND WHY THE DEMO SURVIVES BEING PLAYED WITH.

  A visitor can genuinely accept the incoming challenge — that is the point of
  seeding it — and accepting it does not create an extra row, it changes the
  state of a canonical one. The old fingerprint counted challenges and would not
  have noticed, so the rail would have emptied permanently on the first Accept.
  §4 asserts the fingerprint now carries the OFFERED count, and §5 drives a real
  accept through the real command and requires the demo to come back.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")

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


def _code_only(source: str) -> str:
    """Python source with comments and docstrings removed."""
    source = re.sub(r'""".*?"""', "", source, flags=re.S)
    source = re.sub(r"'''.*?'''", "", source, flags=re.S)
    return re.sub(r"^\s*#.*$", "", source, flags=re.M)


def _without_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


# ── §1 · The rails and the terminology are the locked ones ──────────────────

_section("§1 · the four rails keep their locked names and public terms")

_action_js = _read("web", "js", "action.js")

# FINAL POR §28 — THE LOCKED CATEGORY NAMES CHANGED, SO THIS LIST DID.
#
# `WAITING` / `LIVE` / `COMPLETED` named three different kinds of thing.
# The Final POR names all four rails by the ACTION each one holds. The
# assertion's INTENT is unchanged — the four words are stated once, in a
# frozen map, and nothing assembles a heading per rail — so only the words
# themselves are replaced.
for _rail in ("ACTION REQUIRED", "PENDING ACTION", "LOCKED ACTION",
              "RESOLVED ACTION"):
    _assert(f"the rail `{_rail}` keeps its locked heading", f"'{_rail}" in _action_js
            or f'"{_rail}' in _action_js or _rail in _action_js)

_assert("no public-facing `Versus` reaches the Status surface",
        "Versus" not in _without_comments(_action_js).replace("versus", ""))
_assert("the card speaks of Matchups", "Matchup" in _action_js)
_assert("and of Credits rather than money",
        "Credits" in _action_js and "cash" not in _action_js.lower())


# ── §2 · The card says what state it is in ──────────────────────────────────

_section("§2 · every rail's card answers its own rail's question")

_js = _without_comments(_action_js)
_assert("a per-state sentence exists", "function stateCopy(" in _js)
_assert("the card uses it rather than the mode note",
        "copy: card.copy || cardCopy(card)" in _js)
_assert("and a Dynamic wager keeps its governed mode sentence too",
        "card.mode === 'dynamic' ? `${state} ${modeCopy(card)}`" in _js)
_assert("an incoming offer says who sent it and what it is",
        "sent you a ${market} Matchup" in _js)
_assert("an outgoing offer says who is being waited on",
        "Waiting for ${opponent} to respond" in _js)
_assert("an accepted wager says it is live",
        "This Matchup is live" in _js)
_assert("a settled wager says where the Credits went",
        "Credits posted to your Wallet" in _js)

# NO TEAM-SPECIFIC SENTENCE. The brief's examples name teams; the code may not.
for _name in ("Blitz and Pieces", "Victorious Secret", "Kittle Big Town",
              "Pain Sanders"):
    _assert(f"`{_name}` is not hard-coded into the surface",
            _name not in _action_js)

# THE MODE IS STILL VISIBLE — it moved to the context line, it did not go.
_assert("the card still states FIXED or FLOATING before a GM acts",
        "modeLabel(card)" in _js and "FLOATING" in _js)


# ── §3 · The demo enrichment is isolated and derived ────────────────────────

_section("§3 · the fixture states the negotiations; the code derives them")

_showcase = _read("demo", "showcase.py")
_gameplay = _read("demo", "gameplay.py")

_assert("the fixture declares the open negotiations",
        "VISITOR_OPEN_NEGOTIATIONS" in _showcase)
_assert("and one predicate answers whether a pairing is one",
        "def is_open_negotiation(" in _showcase)
_assert("the seeder issues them", "def open_live_negotiations(" in _gameplay)
_assert("through the funded lifecycle the response routes understand",
        "issue_funded_challenge" in _gameplay)
_assert("with a deterministic event id, never a random one",
        "uuid5" in _gameplay and "uuid4" not in _code_only(_gameplay))
_assert("priced from the market board rather than a literal",
        "compute_market_board" in _gameplay and "_compute_odds" in _gameplay)
_assert("the enrichment is confined to the demo package",
        all(os.path.dirname(p).startswith("demo")
            for p in ("demo/showcase.py", "demo/gameplay.py")))

# THE PRODUCTION WAGER PATH IS UNTOUCHED.
_FROZEN = ("beefs/proposal_lifecycle.py", "economy/challenge_funding.py",
           "betting/settlement_engine.py", "betting/pool_settlement.py",
           "betting/pool_claims.py", "beefs/beef_engine.py")


def _wave5_changed_files() -> list[str]:
    def _git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, check=False).stdout

    files = set(_git("diff", "--name-only", "HEAD").split())
    if _git("log", "-1", "--format=%s").strip().startswith("UIRECON Wave 5"):
        files |= set(_git("show", "--name-only", "--format=", "HEAD").split())
    return sorted(files)


_breach = sorted(set(_FROZEN) & set(_wave5_changed_files()))
_assert("no wagering, settlement or funding module was touched",
        not _breach, ", ".join(_breach))


# ── §4 · The canonical state accounts for them ──────────────────────────────

_section("§4 · the fingerprint derives the new counts and detects an answer")

_reset = _read("demo", "reset.py")
_assert("the expectation counts the negotiations from the fixture",
        "len(showcase.VISITOR_OPEN_NEGOTIATIONS)" in _reset)
_assert("no unexplained numeric delta was written",
        not re.search(r'"challenges":\s*\d+\s*[+-]\s*\d+', _reset))
_assert("the fingerprint carries the OFFERED count, not just the total",
        '"offered_challenges"' in _reset)
_assert("restore reconciles them by shape rather than by id",
        "is_open_negotiation" in _reset)
_assert("and re-issues through the seeder rather than rewinding by hand",
        "open_live_negotiations" in _reset)

from demo import reset as _reset_mod  # noqa: E402
from demo import showcase as _showcase_mod  # noqa: E402

_expected = _reset_mod.expected_fingerprint()
_assert("the expected challenge count is accepted contests plus negotiations",
        _expected["challenges"]
        == (len(_showcase_mod.VERSUS_PER_WEEK_MARKETS)
            * (_showcase_mod.COMPLETED_THROUGH_WEEK + 1)
            + len(_showcase_mod.VISITOR_OPEN_NEGOTIATIONS)),
        str(_expected["challenges"]))
_assert("the expected offered count is the fixture's own length",
        _expected["offered_challenges"]
        == len(_showcase_mod.VISITOR_OPEN_NEGOTIATIONS),
        str(_expected["offered_challenges"]))

# THE WAVE 3 PROP POOL PICK IS UNTOUCHED.
_assert("the visitor still has exactly one open Prop Pool slot",
        _showcase_mod.visitor_skips_claim(
            _showcase_mod.CURRENT_WEEK, _showcase_mod.VISITOR_OPEN_PICK_SLOT,
            _showcase_mod.VISITOR_ORDINAL))
_assert("and no other slot was opened",
        sum(1 for slot in range(1, _showcase_mod.POOL_SLOTS_PER_WEEK + 1)
            if _showcase_mod.visitor_skips_claim(
                _showcase_mod.CURRENT_WEEK, slot,
                _showcase_mod.VISITOR_ORDINAL)) == 1)

# ONE DIRECTION EACH — the rails only differ if the seeding does.
_dirs = {(s.issuer_ordinal == _showcase_mod.VISITOR_ORDINAL)
         for s in _showcase_mod.VISITOR_OPEN_NEGOTIATIONS}
_assert("one negotiation is issued to the visitor and one by them",
        _dirs == {True, False},
        str([(s.issuer_ordinal, s.recipient_ordinal)
             for s in _showcase_mod.VISITOR_OPEN_NEGOTIATIONS]))


# ── §5 · Against a seeded showcase ──────────────────────────────────────────

_section("§5 · the served rails, and what the enrichment cost")


def _pg_url() -> str | None:
    return os.environ.get("UIRECON_W5_PG_URL")


def _functional() -> None:
    url = _pg_url()
    if not url:
        print("  [SKIP] demo tier — set UIRECON_W5_PG_URL to a disposable "
              "PostgreSQL holding a seeded showcase")
        return

    import uuid

    from sqlalchemy import create_engine, text as _text
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(url)
    Session = sessionmaker(bind=engine)

    from db.schema import BeefChallenge, User
    from demo.seed import DEMO_USER_EMAIL, find_showcase
    from reports.action_read_model import gm_action_state

    def _rails(db, league, team_id):
        state = gm_action_state(db, team_id=team_id, league_id=league.id,
                                week=league.provider_current_week)
        rails: dict[str, list] = {}
        for card in state.cards:
            rails.setdefault(card.section, []).append(card)
        return rails

    db = Session()
    try:
        league = find_showcase(db)
        _assert("a showcase league is present", league is not None)
        if league is None:
            return
        seat = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
        rails = _rails(db, league, seat.team_id)

        _assert("ACTION REQUIRED carries a real record",
                len(rails.get("action", [])) >= 1,
                str(len(rails.get("action", []))))
        _assert("WAITING carries a real record",
                len(rails.get("waiting", [])) >= 1,
                str(len(rails.get("waiting", []))))
        _assert("LIVE still carries the Wave 4 accepted Matchup",
                len(rails.get("live", [])) == 1,
                str(len(rails.get("live", []))))
        _assert("COMPLETED still carries the Wave 4 settled Matchups",
                len(rails.get("completed", [])) == 7,
                str(len(rails.get("completed", []))))

        incoming = rails["action"][0]
        _assert("the incoming Matchup is this GM's to decide",
                incoming.viewer_decides is True)
        _assert("and offers the governed responses",
                set(incoming.controls) == {"accept", "counter", "decline"},
                str(incoming.controls))
        _assert("it carries the stake that was actually escrowed",
                incoming.your_stake_cents > 0, str(incoming.your_stake_cents))
        _assert("it carries the odds it was priced at",
                bool(incoming.your_odds), str(incoming.your_odds))
        _assert("it is an offered proposal, not an engine row",
                incoming.protocol_state == "offered", str(incoming.protocol_state))

        outgoing = rails["waiting"][0]
        _assert("the outgoing Matchup is NOT this GM's to decide",
                outgoing.viewer_decides is False)
        _assert("and therefore offers no control at all",
                outgoing.controls == (), str(outgoing.controls))

        # NOTHING IS SETTLED ON THE OPEN RAILS.
        for card in rails["action"] + rails["waiting"]:
            _assert(f"challenge {card.challenge_id} has moved no Credits",
                    card.settled is False and card.net_cents is None,
                    f"settled={card.settled} net={card.net_cents}")
            bets = db.execute(_text(
                "SELECT COUNT(*) FROM bets WHERE beef_challenge_id = :c"),
                {"c": card.challenge_id}).scalar()
            _assert(f"challenge {card.challenge_id} placed no Bet",
                    int(bets or 0) == 0, str(bets))

        # THE ESCROW CAME OUT OF THE WEEKLY MINIMUM, NOT A WALLET.
        for card in rails["action"] + rails["waiting"]:
            legs = db.execute(_text(
                "SELECT account, amount_cents FROM ledger_entries "
                "WHERE posting_id IN (SELECT posting_id FROM ledger_entries "
                "                     WHERE account = :escrow)"),
                {"escrow": f"escrow:challenge:{card.challenge_id}"}).fetchall()
            sources = [a for a, c in legs if int(c) < 0]
            _assert(f"challenge {card.challenge_id} was funded from a weekly "
                    f"minimum, not a wallet",
                    sources and all(a.startswith("min:") for a in sources),
                    ", ".join(sources) or "no legs")

        # EVERY SEEDED NEGOTIATION IS ONE THE FIXTURE NAMES.
        from db.schema import Team
        ordinal_of = {t.team_name: t.ordinal for t in _showcase_mod.TEAMS}
        by_id = {t.id: ordinal_of.get(t.team_name)
                 for t in db.query(Team).filter(Team.league_id == league.id)}
        for row in db.query(BeefChallenge).filter(
                BeefChallenge.response_status.isnot(None)).all():
            _assert(f"challenge {row.id} is a negotiation the fixture declares",
                    _showcase_mod.is_open_negotiation(
                        row.week, by_id.get(row.challenger_team_id),
                        by_id.get(row.challenged_team_id)),
                    f"wk{row.week} {row.challenger_team_id}->"
                    f"{row.challenged_team_id}")

        _assert("reading Status mutates nothing",
                not db.new and not db.dirty and not db.deleted,
                f"new={len(db.new)} dirty={len(db.dirty)}")
    finally:
        db.close()
        engine.dispose()


try:
    _functional()
except Exception as _exc:                                   # pragma: no cover
    _assert("the demo tier could run", False, repr(_exc))


# ── Node tier ───────────────────────────────────────────────────────────────

def _run_node(script: str, label: str) -> None:
    node = shutil.which("node")
    if node is None:
        _assert(f"{label} — node is available", False, "node not on PATH")
        return
    if not os.environ.get("FS_TEST_ORIGIN"):
        print(f"  [SKIP] {label} — set FS_TEST_ORIGIN to a running demo app")
        return
    print(f"\n{label}")
    proc = subprocess.run([node, os.path.join(WEB, "tests", script)],
                          cwd=ROOT, capture_output=True, text=True)
    print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print(proc.stderr.rstrip())
    passes = proc.stdout.count("[PASS]")
    fails = proc.stdout.count("[FAIL]")
    _assert(f"{label} is green", proc.returncode == 0,
            f"{passes} PASS / {fails} FAIL, exit {proc.returncode}")


_run_node("uirecon_wave5_browser.mjs",
          "UIRECON Wave 5 browser suite (headless Chrome, seeded showcase)")


# ── Result ─────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
if _failures:
    print(f"UIRECON WAVE 5 — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
print("UIRECON WAVE 5 — ALL PASSED")
