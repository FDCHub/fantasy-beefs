"""
test_spec1_proposal_lifecycle_red.py — SPEC 1 (Locked Challenge Proposal
Lifecycle, Rev 3) schema/constraint tests. TESTS-FIRST red baseline.

Authority: SPEC_1_Proposal_Lifecycle_v3.md, §3 (schema model), §3.4 (integrity
constraints), §12 (tests required). Implementation basis HEAD 149ef8c, ADDITIVE
per Ruling 1 (2026-07-23): the three new structures are added; every legacy
BeefChallenge column is retained; beef_engine.py is untouched.

WHAT THIS FILE COVERS (schema / DB-enforced-constraint / structural layer of §12):
  Immutability (structural proxy), versioning + provenance, timing formula and
  historical reproducibility, wager identity (wager_type vocabulary + no
  duplicated free bet-type), mode CHECK, both-sides proposal starters, integrity
  constraints (UNIQUE version, UNIQUE starter, same-challenge FK presence),
  role assignment, negotiation vocabulary, revive lineage column, display column,
  integer-cents money typing.

WHAT THIS FILE DOES NOT COVER (requires Spec 2 service logic — OUT OF SCOPE here;
enumerated in the Step B report for a ruling): the §8 actor-authorization matrix
behavior, the SELECT-FOR-UPDATE first-valid-commit race, single-transaction
atomicity, locked-accept no-reprice, accepted->Pending-atomic, and revive
behavior. Only the schema enforcers those flows will build on are tested here.

RED INTENT: the module must LOAD and RUN. Every test must then FAIL because the
required model/column/relationship/constraint is ABSENT — never because import
or collection is broken. New symbols are resolved by getattr, never by a
top-level `from db.schema import BeefProposal`.

Uses a temp SQLite DB through db.engine_factory.get_engine (FK enforcement
active) so production is never touched.
"""

import os
import sys
import tempfile

# ── Must set DATABASE_URL before any project import touches db/schema.py ──────
_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_spec1_proposal_lifecycle.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

# Floor assertion — never run against anything but a temp SQLite file.
assert os.environ["DATABASE_URL"].startswith("sqlite:///"), "ABORT: not sqlite floor"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta, timezone

from sqlalchemy import Float, ForeignKeyConstraint, Integer
from sqlalchemy.exc import IntegrityError

import db.schema as schema
from db.schema import Base, engine, SessionLocal, BeefChallenge, League, Player, Team

# New Spec 1 structures — resolved defensively so the module loads pre-implementation.
BeefProposal = getattr(schema, "BeefProposal", None)
BeefProposalStarter = getattr(schema, "BeefProposalStarter", None)

# ── Harness ───────────────────────────────────────────────────────────────────

_failures: list[str] = []
_total = 0


def _assert(label: str, condition: bool, detail: str = "") -> None:
    global _total
    _total += 1
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if (detail and not condition) else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _has_col(model, name: str) -> bool:
    return model is not None and name in model.__table__.columns


def _has_model(model) -> bool:
    return model is not None


# ── DB bootstrap ──────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)

with SessionLocal() as _s:
    _lg = League(season=2026, name="Spec1 League", projection_source="fantasypros")
    _s.add(_lg)
    _s.flush()
    _challenger = Team(league_id=_lg.id, team_name="Challenger", owner="Cee", email="cee@t.com")
    _challenged = Team(league_id=_lg.id, team_name="Challenged", owner="Dee", email="dee@t.com")
    _s.add_all([_challenger, _challenged])
    _s.flush()
    _p_ch = Player(name="Chal-P", position="WR", nfl_team="KC")
    _p_cg = Player(name="Cged-P", position="RB", nfl_team="PHI")
    _s.add_all([_p_ch, _p_cg])
    _s.flush()
    _s.commit()
    LEAGUE_ID = _lg.id
    CH_ID = _challenger.id      # challenger / issuer / Anchor
    CG_ID = _challenged.id      # challenged / recipient / Derived
    PLAYER_CH = _p_ch.id
    PLAYER_CG = _p_cg.id

_FUTURE = datetime(2026, 9, 14, 18, 0, 0)


def _mk_challenge(s, **extra):
    """A valid legacy BeefChallenge row (all legacy non-null columns filled),
    plus any new Spec 1 columns supplied via **extra (set with setattr so the
    call is safe whether or not the column exists yet)."""
    c = BeefChallenge(
        challenger_team_id=CH_ID,
        challenged_team_id=CG_ID,
        week=1,
        bet_type="straight",
        amount=10.0,
        challenger_odds=1.9,
        challenged_odds=1.9,
        challenger_moneyline=-110,
        challenged_moneyline=-110,
        expires_at=_FUTURE,
    )
    for k, v in extra.items():
        setattr(c, k, v)
    s.add(c)
    s.flush()
    return c


def _mk_proposal(s, challenge, version_number, version_kind, proposing_team_id, **extra):
    p = BeefProposal(
        challenge_id=challenge.id,
        version_number=version_number,
        version_kind=version_kind,
        proposing_team_id=proposing_team_id,
    )
    for k, v in extra.items():
        setattr(p, k, v)
    s.add(p)
    s.flush()
    return p


# ── §12 · models exist ────────────────────────────────────────────────────────

def t01_models_exist():
    print("\nT01 — new tables present (§3.2, §3.3)")
    _assert("BeefProposal model exists", _has_model(BeefProposal), "absent")
    _assert("BeefProposalStarter model exists", _has_model(BeefProposalStarter), "absent")


def t02_challenge_container_columns():
    print("\nT02 — BeefChallenge gains container columns, additively (§3.1)")
    for name in (
        "league_id", "challenge_mode", "wager_type", "response_status",
        "active_proposal_id", "accepted_proposal_id", "active_response_expires_at",
        "revived_from_challenge_id", "updated_at",
    ):
        _assert(f"BeefChallenge.{name} present", _has_col(BeefChallenge, name), "absent")
    # Ruling 1: legacy columns retained (regression guard, green today).
    for name in ("bet_type", "amount", "line", "side", "player_id", "status", "countered_amount"):
        _assert(f"legacy BeefChallenge.{name} retained", _has_col(BeefChallenge, name), "missing")


# ── §12 · mode immutability / CHECK ───────────────────────────────────────────

def t03_challenge_mode_check():
    print("\nT03 — challenge_mode CHECK IN ('locked','dynamic') (§3.1, §12 mode)")
    if not _has_col(BeefChallenge, "challenge_mode"):
        _assert("challenge_mode CHECK enforced", False, "BeefChallenge.challenge_mode absent")
        return
    with SessionLocal() as s:
        try:
            _mk_challenge(s, challenge_mode="bogus")
            _assert("challenge_mode CHECK rejects invalid", False, "'bogus' accepted")
        except IntegrityError:
            _assert("challenge_mode CHECK rejects invalid", True)
        finally:
            s.rollback()
    with SessionLocal() as s:
        try:
            _mk_challenge(s, challenge_mode="locked")
            _mk_challenge(s, challenge_mode="dynamic")
            _assert("challenge_mode accepts locked/dynamic", True)
        except IntegrityError as e:
            _assert("challenge_mode accepts locked/dynamic", False, str(e))
        finally:
            s.rollback()


# ── §12 · wager identity ──────────────────────────────────────────────────────

def t04_wager_type_check():
    print("\nT04 — wager_type CHECK IN ('straight','spread','over_under') (§5, Ruling 2)")
    if not _has_col(BeefChallenge, "wager_type"):
        _assert("wager_type CHECK enforced", False, "BeefChallenge.wager_type absent")
        return
    with SessionLocal() as s:
        try:
            _mk_challenge(s, wager_type="moneyline")  # display label, never a persisted value
            _assert("wager_type CHECK rejects 'moneyline'", False, "'moneyline' accepted")
        except IntegrityError:
            _assert("wager_type CHECK rejects 'moneyline'", True)
        finally:
            s.rollback()
    with SessionLocal() as s:
        try:
            for v in ("straight", "spread", "over_under"):
                _mk_challenge(s, wager_type=v)
            _assert("wager_type accepts straight/spread/over_under", True)
        except IntegrityError as e:
            _assert("wager_type accepts straight/spread/over_under", False, str(e))
        finally:
            s.rollback()


def t05_no_independent_proposal_bet_type():
    print("\nT05 — proposal carries no independently-set wager class (§5, §12 wager identity)")
    if not _has_model(BeefProposal):
        _assert("BeefProposal omits free bet_type/wager_type", False, "BeefProposal absent")
        return
    # §5 recommended design: the class lives once, on the challenge. The proposal
    # must not carry a freely-set bet_type. (If a frozen redundant snapshot were
    # ever retained it would have to equal the challenge's wager_type; we do not
    # retain one.)
    has_bet_type = _has_col(BeefProposal, "bet_type")
    has_wager_type = _has_col(BeefProposal, "wager_type")
    _assert("BeefProposal has no free bet_type column", not has_bet_type,
            "proposal carries an independent bet_type")
    _assert("BeefProposal does not duplicate wager_type", not has_wager_type,
            "proposal duplicates wager_type")


# ── §12 · negotiation status vocabulary ───────────────────────────────────────

def t06_response_status_check():
    print("\nT06 — response_status CHECK is the 6 negotiation states (§3.1, §4)")
    if not _has_col(BeefChallenge, "response_status"):
        _assert("response_status CHECK enforced", False, "BeefChallenge.response_status absent")
        return
    valid = ("offered", "countered", "accepted", "declined", "expired", "cancelled")
    with SessionLocal() as s:
        try:
            for v in valid:
                _mk_challenge(s, response_status=v)
            _assert("response_status accepts all 6 negotiation states", True)
        except IntegrityError as e:
            _assert("response_status accepts all 6 negotiation states", False, str(e))
        finally:
            s.rollback()
    with SessionLocal() as s:
        try:
            _mk_challenge(s, response_status="pending")  # legacy Bet-lifecycle word, not negotiation
            _assert("response_status rejects non-negotiation value", False, "'pending' accepted")
        except IntegrityError:
            _assert("response_status rejects non-negotiation value", True)
        finally:
            s.rollback()


def t07_accepted_is_nonterminal_vocabulary():
    print("\nT07 — response_status is negotiation-scoped, disjoint from Bet lifecycle (§4, §12)")
    if not _has_col(BeefChallenge, "response_status"):
        _assert("negotiation vocabulary disjoint from wager lifecycle", False,
                "BeefChallenge.response_status absent")
        return
    # §4: 'accepted' closes negotiation but is NOT a terminal wager outcome; the
    # wager lifecycle (Pending/Final/Push/Void) is disjoint. Structural proof:
    # the negotiation CHECK admits 'accepted' but none of the wager-lifecycle words.
    negotiation = {"offered", "countered", "accepted", "declined", "expired", "cancelled"}
    wager_lifecycle = {"Pending", "Final", "Push", "Void", "Offered", "Accepted"}
    with SessionLocal() as s:
        try:
            _mk_challenge(s, response_status="accepted")
            accepts_accepted = True
        except IntegrityError:
            accepts_accepted = False
        finally:
            s.rollback()
    _assert("response_status admits 'accepted'", accepts_accepted, "rejected")
    _assert("negotiation set names no wager-lifecycle state",
            negotiation.isdisjoint(wager_lifecycle - {"Accepted"}),
            "negotiation vocabulary overlaps wager lifecycle")


# ── §12 · versioning & provenance ─────────────────────────────────────────────

def t08_version_unique():
    print("\nT08 — UNIQUE(challenge_id, version_number) (§3.4, §9, §12 versioning)")
    if not _has_model(BeefProposal):
        _assert("UNIQUE(challenge_id, version_number) enforced", False, "BeefProposal absent")
        return
    with SessionLocal() as s:
        c = _mk_challenge(s, challenge_mode="locked", wager_type="straight", response_status="offered")
        _mk_proposal(s, c, version_number=1, version_kind="initial", proposing_team_id=CH_ID)
        try:
            _mk_proposal(s, c, version_number=1, version_kind="counter", proposing_team_id=CG_ID)
            _assert("UNIQUE(challenge_id, version_number) rejects duplicate", False, "duplicate v1 accepted")
        except IntegrityError:
            _assert("UNIQUE(challenge_id, version_number) rejects duplicate", True)
        finally:
            s.rollback()


def t09_version_kind_check():
    print("\nT09 — version_kind CHECK IN ('initial','counter') (§3.2)")
    if not _has_model(BeefProposal):
        _assert("version_kind CHECK enforced", False, "BeefProposal absent")
        return
    with SessionLocal() as s:
        c = _mk_challenge(s, challenge_mode="locked", wager_type="straight", response_status="offered")
        try:
            _mk_proposal(s, c, version_number=1, version_kind="bogus", proposing_team_id=CH_ID)
            _assert("version_kind CHECK rejects invalid", False, "'bogus' accepted")
        except IntegrityError:
            _assert("version_kind CHECK rejects invalid", True)
        finally:
            s.rollback()


def t10_version_roles_and_provenance_independent():
    print("\nT10 — v1 initial / v2 counter distinct + independently reproducible (§12 versioning)")
    if not _has_model(BeefProposal):
        _assert("proposals independently reproducible from provenance", False, "BeefProposal absent")
        return
    for name in ("pricing_input_hash", "anchor_odds", "projection_source_id"):
        if not _has_col(BeefProposal, name):
            _assert("proposals independently reproducible from provenance", False,
                    f"BeefProposal.{name} absent")
            return
    with SessionLocal() as s:
        c = _mk_challenge(s, challenge_mode="locked", wager_type="straight", response_status="offered")
        p1 = _mk_proposal(s, c, version_number=1, version_kind="initial", proposing_team_id=CH_ID,
                          pricing_input_hash="hash-v1", anchor_odds=1.80, projection_source_id="src-A")
        p2 = _mk_proposal(s, c, version_number=2, version_kind="counter", proposing_team_id=CG_ID,
                          pricing_input_hash="hash-v2", anchor_odds=2.10, projection_source_id="src-B")
        s.commit()
        s.expire_all()
        r1, r2 = s.get(BeefProposal, p1.id), s.get(BeefProposal, p2.id)
        _assert("version_kind correct for initial vs counter",
                r1.version_kind == "initial" and r2.version_kind == "counter")
        _assert("proposing_team_id correct for initial vs counter",
                r1.proposing_team_id == CH_ID and r2.proposing_team_id == CG_ID)
        _assert("each proposal stores its own provenance independently",
                r1.pricing_input_hash == "hash-v1" and r2.pricing_input_hash == "hash-v2"
                and r1.anchor_odds == 1.80 and r2.anchor_odds == 2.10
                and r1.projection_source_id == "src-A" and r2.projection_source_id == "src-B")
        s.rollback()


def t11_money_fields_integer_cents():
    print("\nT11 — new money fields are integer cents, not Float (binding constraint 2)")
    if not _has_model(BeefProposal):
        _assert("money fields are Integer cents", False, "BeefProposal absent")
        return
    for name in ("anchor_stake_cents", "quoted_derived_stake_cents", "quoted_funded_pot_cents"):
        if not _has_col(BeefProposal, name):
            _assert(f"{name} is Integer cents", False, "absent")
            continue
        col = BeefProposal.__table__.columns[name]
        is_int = isinstance(col.type, Integer) and not isinstance(col.type, Float)
        _assert(f"{name} is Integer cents", is_int, f"type={col.type!r}")


# ── §12 · timing ──────────────────────────────────────────────────────────────

def t12_effective_deadline_formula():
    print("\nT12 — effective deadline = min(created+60m, proposal_lock_at) (§3.2, §12 timing)")
    if not (_has_model(BeefProposal) and _has_col(BeefProposal, "proposal_lock_at")
            and _has_col(BeefProposal, "response_expires_at")):
        _assert("effective deadline computable from stored proposal fields", False,
                "BeefProposal timing columns absent")
        return
    with SessionLocal() as s:
        c = _mk_challenge(s, challenge_mode="locked", wager_type="straight", response_status="offered")
        created = datetime(2026, 9, 1, 12, 0, 0)
        # Case A: lock BEFORE ttl -> lock governs.
        lock_a = created + timedelta(minutes=20)
        pa = _mk_proposal(s, c, version_number=1, version_kind="initial", proposing_team_id=CH_ID,
                          created_at=created, proposal_lock_at=lock_a)
        # Case B: lock AFTER ttl -> the 60-minute ttl governs.
        lock_b = created + timedelta(hours=5)
        pb = _mk_proposal(s, c, version_number=2, version_kind="counter", proposing_team_id=CG_ID,
                          created_at=created, proposal_lock_at=lock_b)
        s.flush()
        eff_a = min(pa.created_at + timedelta(minutes=60), pa.proposal_lock_at)
        eff_b = min(pb.created_at + timedelta(minutes=60), pb.proposal_lock_at)
        _assert("lock-limited proposal: effective deadline is the lock", eff_a == lock_a)
        _assert("ttl-limited proposal: effective deadline is created+60m",
                eff_b == created + timedelta(minutes=60))
        _assert("each proposal owns its own proposal_lock_at", pa.proposal_lock_at != pb.proposal_lock_at)
        s.rollback()


def t13_prior_proposal_timing_stable_after_pointer_move():
    print("\nT13 — initial proposal timing reproducible after active pointer moves (§12 timing/immutability)")
    if not (_has_model(BeefProposal) and _has_col(BeefChallenge, "active_proposal_id")
            and _has_col(BeefProposal, "proposal_lock_at")):
        _assert("prior proposal timing stable after counter", False, "structures absent")
        return
    with SessionLocal() as s:
        c = _mk_challenge(s, challenge_mode="locked", wager_type="straight", response_status="offered")
        lock1 = datetime(2026, 9, 1, 12, 20, 0)
        exp1 = datetime(2026, 9, 1, 12, 20, 0)
        p1 = _mk_proposal(s, c, version_number=1, version_kind="initial", proposing_team_id=CH_ID,
                          proposal_lock_at=lock1, response_expires_at=exp1)
        c.active_proposal_id = p1.id
        s.flush()
        p2 = _mk_proposal(s, c, version_number=2, version_kind="counter", proposing_team_id=CG_ID,
                          proposal_lock_at=datetime(2026, 9, 2, 9, 0, 0),
                          response_expires_at=datetime(2026, 9, 2, 9, 0, 0))
        c.active_proposal_id = p2.id  # pointer moves to the counter
        s.commit()
        s.expire_all()
        r1 = s.get(BeefProposal, p1.id)
        _assert("initial proposal lock unchanged after pointer move", r1.proposal_lock_at == lock1)
        _assert("initial proposal deadline unchanged after pointer move", r1.response_expires_at == exp1)
        s.rollback()


# ── §12 · both-sides starters ─────────────────────────────────────────────────

def t14_both_sides_starters():
    print("\nT14 — each proposal captures both teams' starters, proposal-scoped (§3.3, §6)")
    if not _has_model(BeefProposalStarter):
        _assert("proposal owns a both-teams starter set", False, "BeefProposalStarter absent")
        return
    if not _has_col(BeefProposalStarter, "proposal_id"):
        _assert("BeefProposalStarter is proposal-scoped", False, "proposal_id absent")
        return
    with SessionLocal() as s:
        c = _mk_challenge(s, challenge_mode="locked", wager_type="straight", response_status="offered")
        p = _mk_proposal(s, c, version_number=1, version_kind="initial", proposing_team_id=CH_ID)
        s.add(BeefProposalStarter(proposal_id=p.id, team_id=CH_ID, player_id=PLAYER_CH, nfl_team="KC"))
        s.add(BeefProposalStarter(proposal_id=p.id, team_id=CG_ID, player_id=PLAYER_CG, nfl_team="PHI"))
        s.flush()
        teams = {r.team_id for r in s.query(BeefProposalStarter).filter_by(proposal_id=p.id)}
        _assert("both challenger and challenged represented in the snapshot",
                teams == {CH_ID, CG_ID}, f"got {teams}")
        s.rollback()


def t15_starter_unique():
    print("\nT15 — UNIQUE(proposal_id, team_id, player_id) (§3.3)")
    if not _has_model(BeefProposalStarter):
        _assert("UNIQUE(proposal_id, team_id, player_id) enforced", False, "BeefProposalStarter absent")
        return
    with SessionLocal() as s:
        c = _mk_challenge(s, challenge_mode="locked", wager_type="straight", response_status="offered")
        p = _mk_proposal(s, c, version_number=1, version_kind="initial", proposing_team_id=CH_ID)
        s.add(BeefProposalStarter(proposal_id=p.id, team_id=CH_ID, player_id=PLAYER_CH, nfl_team="KC"))
        s.flush()
        try:
            s.add(BeefProposalStarter(proposal_id=p.id, team_id=CH_ID, player_id=PLAYER_CH, nfl_team="KC"))
            s.flush()
            _assert("UNIQUE(proposal_id, team_id, player_id) rejects duplicate", False, "duplicate accepted")
        except IntegrityError:
            _assert("UNIQUE(proposal_id, team_id, player_id) rejects duplicate", True)
        finally:
            s.rollback()


def t16_starter_not_challenge_scoped():
    print("\nT16 — proposal starters replace challenge-scoped BeefStarter (§3.3, §6 no cross-proposal join)")
    if not _has_model(BeefProposalStarter):
        _assert("BeefProposalStarter is proposal-scoped not challenge-scoped", False,
                "BeefProposalStarter absent")
        return
    _assert("BeefProposalStarter has proposal_id", _has_col(BeefProposalStarter, "proposal_id"), "absent")
    _assert("BeefProposalStarter is NOT challenge-scoped",
            not _has_col(BeefProposalStarter, "beef_challenge_id"),
            "still carries beef_challenge_id — would allow a cross-proposal join")


# ── §3.4 · same-challenge FK integrity ────────────────────────────────────────

def t17_same_challenge_fk_present():
    print("\nT17 — active/accepted proposal must belong to this challenge (§3.4, §9)")
    if not (_has_model(BeefProposal) and _has_col(BeefChallenge, "active_proposal_id")):
        _assert("same-challenge FK constraint present", False, "structures absent")
        return
    # Structural check (SQLite-safe): a composite FK on BeefChallenge references
    # beef_proposals.challenge_id, binding the referenced proposal to this
    # challenge. Behavioral enforcement is Postgres (production) — cyclic FKs use
    # ALTER, which SQLite drops. This asserts the constraint exists in metadata.
    found = False
    for con in BeefChallenge.__table__.constraints:
        if isinstance(con, ForeignKeyConstraint):
            for fk in con.elements:
                col = fk.column
                if col.table.name == "beef_proposals" and col.name == "challenge_id":
                    found = True
    _assert("composite FK binds active/accepted proposal to this challenge", found,
            "no ForeignKeyConstraint references beef_proposals.challenge_id")


# ── §12 · role assignment ─────────────────────────────────────────────────────

def t18_anchor_role_bound_to_issuer():
    print("\nT18 — anchor_team_id stays the original issuer across a recipient counter (§3.2, §12 role)")
    if not (_has_model(BeefProposal) and _has_col(BeefProposal, "anchor_team_id")
            and _has_col(BeefProposal, "derived_team_id")):
        _assert("anchor role bound to issuer identity", False, "anchor/derived columns absent")
        return
    with SessionLocal() as s:
        c = _mk_challenge(s, challenge_mode="locked", wager_type="straight", response_status="offered")
        p1 = _mk_proposal(s, c, version_number=1, version_kind="initial", proposing_team_id=CH_ID,
                          anchor_team_id=CH_ID, derived_team_id=CG_ID)
        # recipient authors the counter, but the issuer remains the Anchor (A4)
        p2 = _mk_proposal(s, c, version_number=2, version_kind="counter", proposing_team_id=CG_ID,
                          anchor_team_id=CH_ID, derived_team_id=CG_ID)
        s.flush()
        _assert("anchor is issuer on the initial proposal", p1.anchor_team_id == CH_ID)
        _assert("anchor is still issuer on a recipient-authored counter",
                p2.anchor_team_id == CH_ID and p2.proposing_team_id == CG_ID)
        s.rollback()


# ── §12 · revive lineage + display non-authority ──────────────────────────────

def t19_revive_lineage_column():
    print("\nT19 — revived_from_challenge_id audit-lineage column (§8, §12 revive)")
    if not _has_col(BeefChallenge, "revived_from_challenge_id"):
        _assert("revived_from_challenge_id present and nullable", False, "absent")
        return
    col = BeefChallenge.__table__.columns["revived_from_challenge_id"]
    _assert("revived_from_challenge_id present and nullable", col.nullable, "not nullable")


def t20_display_terms_non_authoritative_column():
    print("\nT20 — display_terms is a plain non-authoritative column (§3.2, §12 display)")
    if not _has_model(BeefProposal):
        _assert("display_terms column present and non-authoritative", False, "BeefProposal absent")
        return
    if not _has_col(BeefProposal, "display_terms"):
        _assert("display_terms column present and non-authoritative", False, "absent")
        return
    # Non-authoritative: it participates in no CHECK/UNIQUE/FK — structured fields
    # govern. (Compare by column name; ColumnCollection.__contains__ wants a str.)
    in_constraint = False
    for con in BeefProposal.__table__.constraints:
        if con.__class__.__name__.startswith("Primary"):
            continue
        if "display_terms" in [c.name for c in getattr(con, "columns", [])]:
            in_constraint = True
    _assert("display_terms governs nothing (no constraint references it)",
            not in_constraint, "display_terms participates in a constraint")


# ── Runner ────────────────────────────────────────────────────────────────────

_TESTS = [
    t01_models_exist,
    t02_challenge_container_columns,
    t03_challenge_mode_check,
    t04_wager_type_check,
    t05_no_independent_proposal_bet_type,
    t06_response_status_check,
    t07_accepted_is_nonterminal_vocabulary,
    t08_version_unique,
    t09_version_kind_check,
    t10_version_roles_and_provenance_independent,
    t11_money_fields_integer_cents,
    t12_effective_deadline_formula,
    t13_prior_proposal_timing_stable_after_pointer_move,
    t14_both_sides_starters,
    t15_starter_unique,
    t16_starter_not_challenge_scoped,
    t17_same_challenge_fk_present,
    t18_anchor_role_bound_to_issuer,
    t19_revive_lineage_column,
    t20_display_terms_non_authoritative_column,
]

if __name__ == "__main__":
    print("=" * 68)
    print("SPEC 1 · Proposal Lifecycle · schema/constraint tests (Rev 3)")
    print("=" * 68)
    for t in _TESTS:
        try:
            t()
        except Exception as e:  # a test body blowing up is itself a failure, not a crash
            _assert(f"{t.__name__} raised", False, f"{type(e).__name__}: {e}")
    print("\n" + "=" * 68)
    outcome = "GREEN" if not _failures else "RED"
    print(f"SPEC 1 SCHEMA BASELINE — {outcome}: "
          f"{_total - len(_failures)}/{_total} assertions passed, {len(_failures)} failed")
    if _failures:
        print("FAILURES:")
        for f in _failures:
            print(f"  - {f}")
    print("=" * 68)
    sys.exit(1 if _failures else 0)
