#!/usr/bin/env python3
"""
test_uirecon_rev14_refresh_odds.py — UIRECON Rev 1.4 · the Dynamic informational
odds refresh.

Run:  python test_uirecon_rev14_refresh_odds.py

WHAT REV 1.4 ADDED. A Dynamic FantasyStakes Matchup is the mode whose lineups,
projections and odds stay LIVE until Final Lock (Locked-vs-Dynamic ruling §3).
Simulation Engine Rev 9 §5 has always permitted a "display-only re-sim" in that
window and called it nonbinding. Nothing surfaced it: the one mode whose
defining property is movement was the one mode a GM could not watch move. Rev
1.4 is the route, the shared record and the `↻ REFRESH ODDS` control that do.

THE FOUR CLAIMS THAT MATTER, AND WHY EACH NEEDS ITS OWN KIND OF PROOF.

  1. IT MOVES NOTHING. Not Credits, not escrow, not a stake, a line, an odds of
     record or a status. Reading the source and concluding it "should not" is
     the weakest available evidence, because a refresh that reserved Credits
     would look identical in review. §4 therefore SNAPSHOTS the trial balance,
     every ledger entry, every wallet, both per-side escrow accounts and every
     governed column on the challenge and its accepted proposal, drives real
     refreshes through the real route, and demands the snapshot back byte for
     byte.

  2. BOTH GMs SEE ONE LINE. This is not a property of the arithmetic — the
     arithmetic is deterministic and would agree with itself — it is a property
     of WHERE the number comes from. §5 has the issuer refresh, then has the
     OPPONENT read, and requires the opponent to receive the issuer's figures
     rather than figures of their own. Then it reverses the roles.

  3. IT IS REFUSED OUTSIDE THE WINDOW. A Locked wager gets no refresh behaviour
     at all — not a degraded one — and a wager past Final Lock is closed. §6
     exercises Locked, past-Final-Lock, non-existent and non-participant, and
     requires a governed `reason_code` for each rather than a 500 or a silence.

  4. THE CARD TELLS THE TRUTH ABOUT WHAT HAPPENED. "Fresh odds from current
     projections / Wager unchanged", and nothing that reads as a reprice. That
     is a claim about copy and about which cards draw the control, and it is
     proved by the Node component tier at the bottom of this file.

DATABASE. A temp SQLite file per run, built from the models — which is also how
the new `challenge_odds_refresh` table gets exercised on the SQLite test path.
The PostgreSQL certification path builds it from `migrations/
add_dynamic_odds_refresh.py`, registered ACTIVE as `0007_dynamic_odds_refresh`;
§2 asserts the manifest registration and the two schemas' agreement.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'rev14.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient                          # noqa: E402

from api.main import app                                           # noqa: E402
from auth.jwt_auth import hash_password                            # noqa: E402
from auth.session import CSRF_COOKIE, CSRF_HEADER                  # noqa: E402
from config import CURRENT_SEASON                                  # noqa: E402
from db.schema import (                                            # noqa: E402
    Base, BeefChallenge, BeefProposal, Bet, ChallengeFinalLock,
    ChallengeOddsRefresh, League, Matchup, Player, Projection, ProtocolEvent,
    Roster, SessionLocal, Team, User, Wallet, engine,
)
from economy.economy_events import wallet_account                  # noqa: E402
from ledger.ledger import (                                        # noqa: E402
    LedgerEntry, create_ledger_table, post as ledger_post, trial_balance,
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


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


# ══ §1 · The governing rule is the one this feature was built to ═════════════
#
# NOT DECORATION. Every other section proves the code behaves; this one proves
# the behaviour is the one the ruling asked for, quoted from the ruling itself.
# A suite that only measured the implementation would pass just as happily
# against a refresh that repriced the wager.

_section("§1 · the ruling this feature implements")

_ruling = _read("spec", "LOCKED_VS_DYNAMIC_WAGER_MODEL_RULING.md")
_assert("the ruling permits nonbinding informational refreshes in Dynamic",
        "Informational refreshes between Handshake and Final Lock are "
        "nonbinding and move no money" in _ruling)
_assert("and states that Locked freezes at proposal creation, not at refresh",
        "A Locked proposal freezes when it is created" in _ruling)

def _code_only(source: str) -> str:
    """Python source with docstrings and comments removed.

    THE PROSE HAS TO BE SCANNED PAST, not scanned. `beefs/versus_refresh.py`
    documents each of the absences below by NAME — that is the point of the
    docstring — so a naive substring search over the whole file would find
    "ledger" in the sentence that promises never to touch it and fail the
    assertion for saying so.
    """
    source = re.sub(r'""".*?"""', "", source, flags=re.S)
    source = re.sub(r"'''.*?'''", "", source, flags=re.S)
    return re.sub(r"^\s*#.*$", "", source, flags=re.M)


_service = _code_only(_read("beefs", "versus_refresh.py"))

# THE ABSENCES ARE THE ARCHITECTURE. A module that cannot reach the ledger
# cannot post to it by accident, and that is a stronger guarantee than a
# reviewer's attention.
for _forbidden, _why in (
    ("ledger.ledger", "the ledger"),
    ("ledger_post", "a posting"),
    ("lock_funding_scopes", "a wallet lock"),
    ("acquire_final_lock_claim", "the Final-Lock claim"),
    ("execute_final_lock", "Final Lock itself"),
):
    _assert(f"the refresh service never reaches {_why}",
            _forbidden not in _service)

_assert("it writes exactly one kind of row, and it is its own",
        _service.count("db.add(") == 1
        and "db.add(row)" in _service)
_assert("it mints no ProtocolEvent — a refresh is not a money operation",
        "ProtocolEvent" not in _service)
_assert("it resolves the HANDSHAKE-FROZEN model, never the active one",
        "resolve_and_verify" in _service
        and "ACTIVE_MODEL_VERSION_ID" not in _service
        and "resolve_active_model_config" not in _service)


# ══ §2 · The schema object and its migration ═════════════════════════════════

_section("§2 · the shared record, on both dialects")

from migrations.manifest import ACTIVE                             # noqa: E402

_mig = [m for m in ACTIVE if m.identifier == "0007_dynamic_odds_refresh"]
_assert("the migration is registered ACTIVE", len(_mig) == 1,
        ", ".join(m.identifier for m in ACTIVE))
if _mig:
    _assert("and names the table it creates as its proof",
            _mig[0].tables == ("challenge_odds_refresh",), str(_mig[0].tables))
    _assert("and points at a module that exists",
            os.path.exists(os.path.join(
                ROOT, "migrations", "add_dynamic_odds_refresh.py")))

_migration_src = _read("migrations", "add_dynamic_odds_refresh.py")
_assert("the migration is additive — it creates and never alters or drops",
        "CREATE TABLE" in _migration_src
        and "ALTER TABLE" not in _migration_src
        and "DROP" not in _migration_src)
_assert("it is idempotent — a second run observes the table and stops",
        "already exists" in _migration_src)
_assert("it is written for both dialects",
        "postgresql" in _migration_src and "SERIAL" in _migration_src
        and "AUTOINCREMENT" in _migration_src)

# THE MIGRATION AND THE MODEL MUST DESCRIBE ONE TABLE. A clean install builds
# from the model and an upgrade builds from the migration; a column present in
# one and absent from the other is two different production schemas wearing one
# name, and nothing else in the suite would notice.
_model_columns = {c.name for c in ChallengeOddsRefresh.__table__.columns}
_migration_columns = {
    name for name in _model_columns
    if f"\n                {name} " in _migration_src
}
_assert("every model column is created by the migration too",
        _model_columns == _migration_columns,
        f"missing from migration: {sorted(_model_columns - _migration_columns)}")

_assert("the record is append-only — no UNIQUE(challenge_id) to overwrite into",
        not any("challenge_id" in str(getattr(c, "columns", ""))
                and c.__class__.__name__ == "UniqueConstraint"
                for c in ChallengeOddsRefresh.__table__.constraints))


# ══ Fixture ══════════════════════════════════════════════════════════════════

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "rev14-password"
SEASON = CURRENT_SEASON
WEEK = 3
N_START = 9

# A genuine favourite inside the priceable range. An even-money board would make
# "both GMs see the same figures" pass for the wrong reason — every figure would
# be symmetric — and a blowout board returns certainty, which `derive_stakes`
# refuses outright, so the Dynamic path would never run at all.
STRONG_POINTS = 13.0
WEAK_POINTS = 11.5

OPENING_CENTS = 500_00
STAKE_DOLLARS = 25.0

with SessionLocal() as db:
    hashed = hash_password(PASSWORD)
    league = League(name="Rev14 League", season=SEASON,
                    projection_source="fantasypros")
    db.add(league)
    db.flush()
    LEAGUE_ID = league.id

    def _team(name: str, email: str, points: float) -> int:
        t = Team(team_name=name, owner=f"{name} Owner", email=email,
                 league_id=LEAGUE_ID)
        db.add(t)
        db.flush()
        db.add(Wallet(team_id=t.id, balance=0.0))
        db.add(User(email=email, hashed_password=hashed, team_id=t.id,
                    role="gm"))
        for slot in range(N_START):
            p = Player(name=f"{name} p{slot}", position="WR", nfl_team="KC")
            db.add(p)
            db.flush()
            db.add(Roster(team_id=t.id, player_id=p.id))
            db.add(Projection(player_id=p.id, week=WEEK, season=SEASON,
                              source="fantasypros", projected_points=points))
        return t.id

    ISSUER = _team("Issuer", "issuer@rev14.test", STRONG_POINTS)
    OPPONENT = _team("Opponent", "opponent@rev14.test", WEAK_POINTS)
    # A league member who is in NEITHER wager. Their refusal must be about
    # participation, not about the wager being unreadable.
    BYSTANDER = _team("Bystander", "bystander@rev14.test", WEAK_POINTS)

    db.add(Matchup(league_id=LEAGUE_ID, week=WEEK, home_team_id=ISSUER,
                   away_team_id=OPPONENT, home_score=0.0, away_score=0.0))
    db.commit()

for _team_id in (ISSUER, OPPONENT, BYSTANDER):
    ledger_post([(wallet_account(_team_id), OPENING_CENTS),
                 ("world", -OPENING_CENTS)], door="season_allocation")


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _sign_in(client: TestClient, email: str) -> None:
    r = client.post("/auth/session", json={"email": email,
                                           "password": PASSWORD})
    assert r.status_code == 200, r.text


def _post(client: TestClient, path: str, body=None):
    headers = {}
    token = client.cookies.get(CSRF_COOKIE)
    if token:
        headers[CSRF_HEADER] = token
    return client.post(path, json=body, headers=headers)


def _refresh_path(challenge_id: int) -> str:
    return f"/league/{LEAGUE_ID}/challenge/{challenge_id}/odds/refresh"


def _issue(client: TestClient, mode: str, challenged: int = OPPONENT):
    return _post(client, "/beef/challenge", {
        "challenger_team_id": ISSUER,
        "challenged_team_id": challenged,
        "week": WEEK,
        "bet_type": "straight",
        "amount": STAKE_DOLLARS,
        "challenge_mode": mode,
    })


def _accept(client: TestClient, challenge_id: int):
    return _post(client, "/beef/respond",
                 {"challenge_id": challenge_id, "accept": True})


# ── Build one Dynamic (Handshaken) and one Locked (accepted) wager ───────────

DYNAMIC_ID = None
LOCKED_ID = None
_setup_detail = ""

with _client() as _c:
    _sign_in(_c, "issuer@rev14.test")
    _r = _issue(_c, "dynamic")
    if _r.status_code == 201:
        DYNAMIC_ID = _r.json()["challenge_id"]
    else:
        _setup_detail = f"issue dynamic -> {_r.status_code} {_r.text[:200]}"
    _r2 = _issue(_c, "locked")
    if _r2.status_code == 201:
        LOCKED_ID = _r2.json()["challenge_id"]
    elif not _setup_detail:
        _setup_detail = f"issue locked -> {_r2.status_code} {_r2.text[:200]}"

with _client() as _c:
    _sign_in(_c, "opponent@rev14.test")
    if DYNAMIC_ID is not None:
        _ra = _accept(_c, DYNAMIC_ID)
        if _ra.status_code != 200 and not _setup_detail:
            _setup_detail = f"handshake -> {_ra.status_code} {_ra.text[:200]}"
    if LOCKED_ID is not None:
        _rb = _accept(_c, LOCKED_ID)
        if _rb.status_code != 200 and not _setup_detail:
            _setup_detail = f"locked accept -> {_rb.status_code} {_rb.text[:200]}"

_section("§3 · the fixture reaches the state the window is defined over")
_assert("a Dynamic challenge was issued", DYNAMIC_ID is not None, _setup_detail)
_assert("a Locked challenge was issued", LOCKED_ID is not None, _setup_detail)

with SessionLocal() as db:
    _dyn = db.query(BeefChallenge).filter(
        BeefChallenge.id == DYNAMIC_ID).first() if DYNAMIC_ID else None
    _assert("and it Handshaked — the refresh window is open",
            _dyn is not None and _dyn.dynamic_handshake_at is not None
            and _dyn.dynamic_opponent_ceiling_cents is not None,
            _setup_detail or (str(_dyn.response_status) if _dyn else "no row"))
    _assert("under a frozen model version",
            _dyn is not None and bool(_dyn.dynamic_model_version_id),
            str(_dyn.dynamic_model_version_id) if _dyn else "")

_RUNNABLE = DYNAMIC_ID is not None and _dyn is not None \
    and _dyn.dynamic_handshake_at is not None


# ── Snapshot helpers ─────────────────────────────────────────────────────────

def _money_snapshot() -> dict:
    """Everything a refresh must leave untouched, read from the ledger itself.

    THE TRIAL BALANCE AND THE ENTRY COUNT ARE BOTH TAKEN, deliberately. The
    trial balance would stay zero across a perfectly balanced pair of postings
    that moved a GM's Credits into escrow; the entry count catches that, and the
    per-account balances say WHERE anything moved if it did.
    """
    from economy.dynamic_challenge import (
        anchor_escrow_account, derived_escrow_account,
    )

    with SessionLocal() as db:
        accounts = {
            "trial_balance": trial_balance(),
            "entries": db.query(LedgerEntry).count(),
        }
        for team_id in (ISSUER, OPPONENT, BYSTANDER):
            accounts[f"wallet:{team_id}"] = _balance(db, wallet_account(team_id))
        for cid in (DYNAMIC_ID, LOCKED_ID):
            if cid is None:
                continue
            accounts[f"pooled:{cid}"] = _balance(db, f"escrow:challenge:{cid}")
            accounts[f"anchor:{cid}"] = _balance(db, anchor_escrow_account(cid))
            accounts[f"derived:{cid}"] = _balance(db, derived_escrow_account(cid))
    return accounts


def _balance(db, account: str) -> int:
    from ledger.ledger import _balance_of_in_session
    return _balance_of_in_session(db, account)


#: The columns that ARE the wager. Every one of them is a term two GMs agreed
#: to, and a refresh that changed any single one would be a reprice however it
#: was described in the response.
TERM_COLUMNS = (
    "challenge_mode", "wager_type", "bet_type", "amount", "line", "side",
    "status", "response_status", "challenger_odds", "challenged_odds",
    "challenger_moneyline", "challenged_moneyline",
    "dynamic_issuer_ceiling_cents", "dynamic_opponent_ceiling_cents",
    "dynamic_model_version_id", "dynamic_model_config_hash",
    "dynamic_handshake_at", "accepted_proposal_id", "active_proposal_id",
    "challenger_bet_id", "challenged_bet_id", "expires_at", "responded_at",
)

PROPOSAL_COLUMNS = (
    "anchor_stake_cents", "quoted_derived_stake_cents",
    "quoted_funded_pot_cents", "anchor_moneyline", "derived_moneyline",
    "anchor_win_probability", "derived_win_probability", "line", "side",
    "anchor_odds", "derived_odds", "version_number", "version_kind",
    "anchor_team_id", "derived_team_id", "pricing_model_id",
    "pricing_calc_version", "pricing_input_hash", "proposal_lock_at",
    "response_expires_at",
)


def _terms_snapshot(challenge_id: int) -> dict:
    with SessionLocal() as db:
        row = db.query(BeefChallenge).filter(
            BeefChallenge.id == challenge_id).one()
        snap = {f"challenge.{c}": getattr(row, c) for c in TERM_COLUMNS}
        for prop in (db.query(BeefProposal)
                     .filter(BeefProposal.challenge_id == challenge_id)
                     .order_by(BeefProposal.id).all()):
            for c in PROPOSAL_COLUMNS:
                snap[f"proposal{prop.id}.{c}"] = getattr(prop, c)
        for bet in (db.query(Bet)
                    .filter(Bet.beef_challenge_id == challenge_id)
                    .order_by(Bet.id).all()):
            for c in ("amount", "odds", "line", "status", "bet_type"):
                snap[f"bet{bet.id}.{c}"] = getattr(bet, c)
        snap["final_locks"] = db.query(ChallengeFinalLock).filter(
            ChallengeFinalLock.challenge_id == challenge_id).count()
    return snap


def _diff(before: dict, after: dict) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [f"{k}: {before.get(k)!r} -> {after.get(k)!r}"
            for k in keys if before.get(k) != after.get(k)]


# ══ §4 · A refresh returns fresh pricing and moves nothing ═══════════════════

_section("§4 · an eligible Dynamic refresh prices, and moves nothing")

FIRST = None
if _RUNNABLE:
    money_before = _money_snapshot()
    terms_before = _terms_snapshot(DYNAMIC_ID)
    locked_terms_before = _terms_snapshot(LOCKED_ID) if LOCKED_ID else {}

    with _client() as client:
        _sign_in(client, "issuer@rev14.test")
        r = _post(client, _refresh_path(DYNAMIC_ID))
        _assert("the issuer may refresh their live Dynamic Matchup",
                r.status_code == 200, f"{r.status_code} {r.text[:220]}")
        if r.status_code == 200:
            FIRST = r.json()

    if FIRST:
        _assert("it reports updated probabilities that describe one market",
                0.0 < FIRST["issuer_probability"] < 1.0
                and abs(FIRST["issuer_probability"]
                        + FIRST["opponent_probability"] - 1.0) < 1e-6,
                f"{FIRST['issuer_probability']} / "
                f"{FIRST['opponent_probability']}")
        _assert("the issuer is priced as the favourite the fixture built",
                FIRST["issuer_probability"] > 0.5,
                str(FIRST["issuer_probability"]))
        _assert("it reports a displayed American price for both sides",
                isinstance(FIRST["issuer_moneyline"], int)
                and isinstance(FIRST["opponent_moneyline"], int)
                and abs(FIRST["issuer_moneyline"]) >= 100,
                f"{FIRST['issuer_moneyline']} / {FIRST['opponent_moneyline']}")
        _assert("and fair decimal odds, the representation Bet.odds uses",
                FIRST["issuer_decimal_odds"] > 1.0
                and FIRST["opponent_decimal_odds"] > 1.0)
        _assert("it carries a refreshed-at timestamp",
                bool(FIRST["refreshed_at"]), str(FIRST["refreshed_at"]))
        _assert("it names the GM who asked, for the audit trail",
                FIRST["refreshed_by_team_id"] == ISSUER,
                str(FIRST["refreshed_by_team_id"]))
        _assert("it was priced under the HANDSHAKE-FROZEN model",
                FIRST["model_version_id"] == _dyn.dynamic_model_version_id,
                f"{FIRST['model_version_id']} vs "
                f"{_dyn.dynamic_model_version_id}")
        _assert("the indicative derived stake never exceeds the agreed ceiling",
                0 <= FIRST["indicative_derived_cents"]
                <= FIRST["opponent_ceiling_cents"],
                f"{FIRST['indicative_derived_cents']} / "
                f"{FIRST['opponent_ceiling_cents']}")
        _assert("the ceiling reported is the one frozen at the Handshake",
                FIRST["opponent_ceiling_cents"]
                == _dyn.dynamic_opponent_ceiling_cents)
        _assert("the Anchor is echoed unchanged — it never reprices on odds",
                FIRST["anchor_cents"] == _dyn.dynamic_issuer_ceiling_cents)

    # NO CREDIT MOVEMENT. Measured, not reasoned about.
    money_after = _money_snapshot()
    _assert("not one Credit moved — every balance and entry is identical",
            money_before == money_after,
            "; ".join(_diff(money_before, money_after)) or "identical")

    # NO ESCROW MOVEMENT, named separately because it is a separate claim: the
    # Handshake→Final-Lock window has NO authorized escrow writer (MS-SIM-6),
    # and §2 guard 3 refuses an issuer overshoot precisely because nothing
    # legitimate could have produced one.
    _assert("neither per-side escrow account moved",
            all(money_before[k] == money_after[k] for k in money_before
                if k.startswith(("anchor:", "derived:", "pooled:"))))

    # NO OFFICIAL TERM MUTATED.
    terms_after = _terms_snapshot(DYNAMIC_ID)
    _assert("no official term of the Dynamic wager changed",
            terms_before == terms_after,
            "; ".join(_diff(terms_before, terms_after)) or "identical")
    if LOCKED_ID:
        _assert("and the Locked wager beside it was not touched either",
                locked_terms_before == _terms_snapshot(LOCKED_ID))

    # NO FINAL LOCK, NO CLAIM.
    with SessionLocal() as db:
        _assert("no Final Lock was performed",
                db.query(ChallengeFinalLock).count() == 0)
        _assert("and no Final-Lock execution claim was taken",
                db.execute(__import__("sqlalchemy").text(
                    "SELECT COUNT(*) FROM challenge_final_lock_claims"
                )).scalar() == 0)
        _assert("exactly one informational record was written",
                db.query(ChallengeOddsRefresh).count() == 1,
                str(db.query(ChallengeOddsRefresh).count()))
else:
    _assert("§4 could run", False, _setup_detail or "fixture never Handshaked")


# ══ §5 · One line, read by both GMs ══════════════════════════════════════════

_section("§5 · the refresh is shared, not per-caller")

SHARED_FIGURES = ("issuer_probability", "opponent_probability",
                  "issuer_moneyline", "opponent_moneyline",
                  "issuer_decimal_odds", "opponent_decimal_odds",
                  "anchor_cents", "indicative_derived_cents",
                  "opponent_ceiling_cents", "ceiling_applied",
                  "refreshed_at", "model_version_id")

if _RUNNABLE and FIRST:
    with _client() as client:
        _sign_in(client, "opponent@rev14.test")
        r = client.get(_refresh_path(DYNAMIC_ID))
        _assert("the opponent may read the Matchup's refresh",
                r.status_code == 200, f"{r.status_code} {r.text[:200]}")
        opponent_read = r.json() if r.status_code == 200 else {}

    _assert("and reads the ISSUER's refresh, figure for figure",
            all(opponent_read.get(k) == FIRST.get(k) for k in SHARED_FIGURES),
            "; ".join(f"{k}: {FIRST.get(k)!r} != {opponent_read.get(k)!r}"
                      for k in SHARED_FIGURES
                      if opponent_read.get(k) != FIRST.get(k)) or "identical")
    _assert("including the timestamp — it is the moment the figures were made, "
            "not the moment they were read",
            opponent_read.get("refreshed_at") == FIRST.get("refreshed_at"))
    _assert("only the viewer LABEL differs, never a figure",
            FIRST.get("viewer_is_issuer") is True
            and opponent_read.get("viewer_is_issuer") is False,
            f"{FIRST.get('viewer_is_issuer')} / "
            f"{opponent_read.get('viewer_is_issuer')}")

    # AND THE OTHER DIRECTION. The opponent refreshing must publish to the
    # issuer just as readily; a shared record that only flowed one way would
    # pass the assertion above and still be two lines in practice.
    with _client() as client:
        _sign_in(client, "opponent@rev14.test")
        r = _post(client, _refresh_path(DYNAMIC_ID))
        _assert("the opponent may also refresh", r.status_code == 200,
                f"{r.status_code} {r.text[:200]}")
        second = r.json() if r.status_code == 200 else {}

    with _client() as client:
        _sign_in(client, "issuer@rev14.test")
        issuer_read = client.get(_refresh_path(DYNAMIC_ID)).json()

    _assert("the issuer now reads the OPPONENT's refresh, figure for figure",
            all(issuer_read.get(k) == second.get(k) for k in SHARED_FIGURES),
            "; ".join(f"{k}: {second.get(k)!r} != {issuer_read.get(k)!r}"
                      for k in SHARED_FIGURES
                      if issuer_read.get(k) != second.get(k)) or "identical")
    _assert("the record names the second GM as the one who asked",
            second.get("refreshed_by_team_id") == OPPONENT,
            str(second.get("refreshed_by_team_id")))

    # DETERMINISM. Identical projections and an identical frozen model produce
    # identical probabilities — the seed is derived from team identity and week,
    # so the two runs are the same draw. That is what makes "shared" cheap to
    # keep true; the persistence above is what makes it true even when the
    # projections DO move between two requests.
    _assert("re-simulating unchanged inputs reproduces the same probabilities",
            second.get("issuer_probability") == FIRST.get("issuer_probability"),
            f"{FIRST.get('issuer_probability')} -> "
            f"{second.get('issuer_probability')}")
    with SessionLocal() as db:
        rows = (db.query(ChallengeOddsRefresh)
                .filter(ChallengeOddsRefresh.challenge_id == DYNAMIC_ID)
                .order_by(ChallengeOddsRefresh.id).all())
        _assert("the record is append-only — both refreshes are kept",
                len(rows) == 2, str(len(rows)))
        _assert("and the history names both actors in order",
                [r.requested_by_team_id for r in rows] == [ISSUER, OPPONENT],
                str([r.requested_by_team_id for r in rows]))

    money_after_two = _money_snapshot()
    _assert("two refreshes by two GMs still moved not one Credit",
            money_before == money_after_two,
            "; ".join(_diff(money_before, money_after_two)) or "identical")
else:
    _assert("§5 could run", False, _setup_detail or "no first refresh")


# ══ §6 · Refused outside the window ══════════════════════════════════════════

_section("§6 · the refusals, each with its own governed reason code")


def _reason(response) -> str:
    try:
        detail = response.json().get("detail")
    except Exception:                                        # pragma: no cover
        return ""
    return detail.get("reason_code", "") if isinstance(detail, dict) else ""


if LOCKED_ID is not None:
    with _client() as client:
        _sign_in(client, "issuer@rev14.test")
        r = _post(client, _refresh_path(LOCKED_ID))
    _assert("a LOCKED Matchup is refused", r.status_code == 409,
            str(r.status_code))
    _assert("with `refresh_not_dynamic` — Locked gets no refresh behaviour",
            _reason(r) == "refresh_not_dynamic", _reason(r))

    # AND THE READ AGREES WITH THE WRITE. The card asks the GET whether to draw
    # the control; a GET that said "eligible" for a wager the POST refuses would
    # put a button on a Locked card.
    with _client() as client:
        _sign_in(client, "issuer@rev14.test")
        g = client.get(_refresh_path(LOCKED_ID))
    _assert("and the read tells the card not to draw the control",
            g.status_code == 200
            and g.json().get("refresh_eligible") is False
            and g.json().get("reason_code") == "refresh_not_dynamic",
            f"{g.status_code} {g.text[:160]}")
    _assert("with no figures at all beside it",
            g.status_code == 200 and g.json().get("refreshed_at") is None)
else:
    _assert("§6 Locked case could run", False, _setup_detail)

with _client() as client:
    _sign_in(client, "issuer@rev14.test")
    r = _post(client, _refresh_path(987654))
_assert("a Matchup that does not exist is refused", r.status_code == 404,
        str(r.status_code))
_assert("with `challenge_not_found`", _reason(r) == "challenge_not_found",
        _reason(r))

if _RUNNABLE:
    with _client() as client:
        _sign_in(client, "bystander@rev14.test")
        r = _post(client, _refresh_path(DYNAMIC_ID))
    _assert("a league member who is not in the wager is refused",
            r.status_code == 403, str(r.status_code))
    _assert("with `not_a_participant`", _reason(r) == "not_a_participant",
            _reason(r))

# PAST FINAL LOCK. Written directly, because reaching it through the worker
# needs a real NFL schedule this SQLite fixture deliberately does not carry —
# and because the condition under test is the DURABLE RECORD's existence, which
# Rev 9 §7.3 makes the authoritative completion fact. A refusal that only fired
# when a worker happened to have run would be no refusal at all.
if _RUNNABLE:
    import uuid as _uuid

    with SessionLocal() as db:
        ev = ProtocolEvent(event_id=_uuid.uuid4(),
                           event_type="challenge_final_lock",
                           challenge_id=DYNAMIC_ID, actor_identity="system")
        db.add(ev)
        db.flush()
        db.add(ChallengeFinalLock(
            challenge_id=DYNAMIC_ID,
            executed_model_version_id=_dyn.dynamic_model_version_id,
            executed_model_config_hash=_dyn.dynamic_model_config_hash,
            simulations=1, p_issuer_final=0.6, p_opponent_final=0.4,
            anchor_cents=_dyn.dynamic_issuer_ceiling_cents or 0,
            derived_raw_cents=_dyn.dynamic_opponent_ceiling_cents or 0,
            derived_final_cents=_dyn.dynamic_opponent_ceiling_cents or 0,
            final_funded_escrow_cents=0, protocol_event_id=ev.id))
        db.commit()

    with _client() as client:
        _sign_in(client, "issuer@rev14.test")
        r = _post(client, _refresh_path(DYNAMIC_ID))
    _assert("a Matchup past Final Lock is refused", r.status_code == 409,
            str(r.status_code))
    _assert("with `refresh_after_final_lock`",
            _reason(r) == "refresh_after_final_lock", _reason(r))

    with _client() as client:
        _sign_in(client, "opponent@rev14.test")
        g = client.get(_refresh_path(DYNAMIC_ID))
    _assert("the card is told to withdraw the control once Final Lock lands",
            g.status_code == 200 and g.json().get("refresh_eligible") is False,
            f"{g.status_code} {g.text[:160]}")
    _assert("while the last shared refresh is still readable as history",
            g.status_code == 200 and bool(g.json().get("refreshed_at")))

    with SessionLocal() as db:
        _assert("the refused refresh wrote nothing",
                db.query(ChallengeOddsRefresh).count() == 2,
                str(db.query(ChallengeOddsRefresh).count()))
    _assert("and moved nothing", _money_snapshot() == money_before,
            "; ".join(_diff(money_before, _money_snapshot())) or "identical")


# ══ §7 · The card ════════════════════════════════════════════════════════════

_section("§7 · the control, the stamp and the copy")

_affordance = _read("web", "js", "refresh-odds.js")
# SUPERSEDED BY THE REFINE-REFRESH PASS. Rev 1.4 drew this as a full-width
# button captioned `↻ REFRESH ODDS`. That is the size this product uses for
# DECISIONS — Accept, Counter, Submit Pick — and a refresh is a GM looking
# something up, so the affordance became the small shared glyph Play uses and
# the caption became the accessible name. The verb is unchanged; what changed is
# how loudly it is stated.
_assert("the control is the shared small glyph, not a full-width button",
        "refreshControl({" in _affordance
        and "fs-oddsref--card" in _affordance
        and "'↻ REFRESH ODDS'" not in _affordance)
_assert("  · and its subject moved into the accessible name, which a keyboard "
        "and a screen reader both reach",
        "REFRESH_LABEL = 'Refresh odds for this Matchup'" in _affordance)
_assert("the stamp reads `Updated H:MM AM`", "`Updated ${" in _affordance)
_assert("the confirmation is the two ruled lines",
        "'Fresh odds from current projections'" in _affordance
        and "'Wager unchanged'" in _affordance)
_assert("the card is decorated, never re-rendered — one card grammar",
        "wagerCard" not in _affordance)

_mount = _read("web", "js", "refresh-odds-mount.js")
_assert("the affordance is actually mounted by the app",
        "refresh-odds-mount.js" in _read("web", "index.html")
        and "mountRefreshOdds" in _mount)
_assert("and only against an authoritative Action read",
        "authoritative" in _mount)


def _run_node(script: str, label: str) -> None:
    node = shutil.which("node")
    if node is None:
        print(f"  [SKIP] {label} — node is not on PATH")
        return
    print(f"\n{label}")
    proc = subprocess.run([node, os.path.join(ROOT, "web", "tests", script)],
                          cwd=ROOT, capture_output=True, text=True)
    print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print(proc.stderr.rstrip())
    passes = proc.stdout.count("[PASS]")
    fails = proc.stdout.count("[FAIL]")
    _assert(f"{label} is green", proc.returncode == 0,
            f"{passes} PASS / {fails} FAIL, exit {proc.returncode}")


_run_node("uirecon_rev14_refresh_odds_component.mjs",
          "UIRECON Rev 1.4 component suite (node, no browser required)")


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
if _failures:
    print(f"UIRECON REV 1.4 REFRESH ODDS — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
print("UIRECON REV 1.4 REFRESH ODDS — ALL PASSED")
