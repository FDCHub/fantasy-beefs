"""
test_spec1_2a_lifecycle_pg.py — Sprint 2 Package 2A: the Spec 1 lifecycle
behaviour matrix (PostgreSQL).

    L1  initial issue                     L10 deterministic terminal replay
    L2  version 1 immutability            L11 revive creates a NEW challenge
    L3  exactly one counter               L12 both-team snapshots per version
    L4  version 2 immutability, class     L13 accepted version authoritative
        unchanged                         L14 no proposal mutation path
    L5  the complete §8 actor matrix      L15 effective deadline calculation
    L6  Locked accept, no reprice         L16 anchor_team_id stays the issuer
    L7  decline                           L17 cross-league isolation
    L8  offered-only issuer cancel
    L9  expiration

THE CALLER OWNS THE TRANSACTION, AND THIS SUITE IS THAT CALLER. The service
never commits, so every scenario opens a Session, calls the service, and commits
itself — standing in for Package 2B, which will one day commit the lifecycle and
the escrow together. Where a scenario needs to prove nothing was written, it
simply rolls back instead, which is only meaningful BECAUSE the service left the
transaction open.

COMMIT COUNTS ARE MEASURED where they matter: an after_commit listener on the
session proves the service issued none of its own.

Postgres only: the composite same-challenge FK is declaration-authoritative under
SQLite (the ALTER-added constraint is dropped there), and every lock and race in
the companion suite needs real row locking.

Requires TEST_DATABASE_URL pointing at a dedicated, empty, _test-named,
non-Railway PostgreSQL database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] Package 2A lifecycle suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []
_seq = {"n": 0}


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _uniq(prefix: str) -> str:
    _seq["n"] += 1
    return f"{prefix}{_seq['n']}"


def main(tdb) -> None:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import event, text

    from db.schema import (
        SessionLocal, BeefChallenge, BeefProposal, BeefProposalStarter,
        League, Player, Roster, Team,
    )
    from beefs.proposal_lifecycle import (
        issue_proposal_challenge, counter_challenge_proposal,
        accept_locked_proposal, decline_challenge, cancel_challenge,
        expire_challenge, revive_challenge,
        effective_deadline, ProposalTerms,
        ActorNotAuthorizedError, ChallengeNotFoundError, DeadlineNotReachedError,
        DeadlinePassedError, InvalidTransitionError, NotANewModelChallengeError,
        UnsupportedModeError,
        OFFERED, COUNTERED, ACCEPTED, DECLINED, EXPIRED, CANCELLED,
        MODE_LOCKED, MODE_DYNAMIC, RESPONSE_TTL_MINUTES,
    )

    # ── seed helpers ──────────────────────────────────────────────────────

    def _mk_league(name: str) -> int:
        with SessionLocal() as db:
            lg = League(season=2025, name=name, projection_source="fantasypros")
            db.add(lg); db.commit(); return lg.id

    def _mk_team(league_id: int, name: str) -> int:
        with SessionLocal() as db:
            t = Team(league_id=league_id, team_name=name, owner=name,
                     email=f"{name}@gg.test")
            db.add(t); db.commit(); return t.id

    def _mk_roster(team_id: int, n: int = 3) -> list:
        """n players on a team's roster, so a proposal has something to freeze."""
        ids = []
        with SessionLocal() as db:
            for i in range(n):
                p = Player(name=_uniq("Player"), position="RB", nfl_team="SF")
                db.add(p); db.flush()
                db.add(Roster(team_id=team_id, player_id=p.id))
                ids.append(p.id)
            db.commit()
        return ids

    def _terms(anchor_cents: int = 2500, **kw) -> ProposalTerms:
        base = dict(
            line=None, side=None, player_id=None,
            anchor_stake_cents=anchor_cents,
            quoted_derived_stake_cents=anchor_cents,
            quoted_funded_pot_cents=anchor_cents * 2,
            anchor_odds=1.91, derived_odds=1.91,
            anchor_moneyline=-110, derived_moneyline=-110,
            pricing_model_id="mc-v1", pricing_calc_version="1.0.0",
            projection_source_id="fantasypros-2025w1",
            anchor_win_probability=0.5, derived_win_probability=0.5,
            pricing_input_hash=_uniq("hash"),
            display_terms="display only, never authoritative",
        )
        base.update(kw)
        return ProposalTerms(**base)

    class Fixture:
        """One league, two teams with rosters. Team A is the challenger/issuer
        (and therefore always the Anchor); team B is the recipient."""

        def __init__(self, tag: str):
            self.league_id = _mk_league(_uniq(f"{tag}-lg"))
            self.a = _mk_team(self.league_id, _uniq(f"{tag}A"))
            self.b = _mk_team(self.league_id, _uniq(f"{tag}B"))
            self.a_players = _mk_roster(self.a, 3)
            self.b_players = _mk_roster(self.b, 2)

    class Caller:
        """The transaction owner — Package 2B's stand-in. Counts commits so the
        service's own commit discipline is measured, not assumed."""

        def __init__(self):
            self.db = SessionLocal()
            self.commits = 0
            event.listen(self.db, "after_commit", self._bump)

        def _bump(self, session):
            self.commits += 1

        def close(self):
            event.remove(self.db, "after_commit", self._bump)
            self.db.close()

    def _issue(fx, *, lock_at=None, now=None, terms=None, mode=MODE_LOCKED,
               wager="straight", commit=True):
        """Issue and commit, the ordinary setup path."""
        c = Caller()
        try:
            res = issue_proposal_challenge(
                league_id=fx.league_id, week=1,
                challenger_team_id=fx.a, challenged_team_id=fx.b,
                challenge_mode=mode, wager_type=wager,
                terms=terms or _terms(), db=c.db,
                proposal_lock_at=lock_at, schedule_source_ref="sched-v1",
                now=now,
            )
            service_commits = c.commits
            if commit:
                c.db.commit()
            return res, service_commits
        finally:
            c.close()

    def _run(fn, **kw):
        """Call one transition on its own caller-owned session and commit.
        Returns (result, exception, commits_issued_by_the_service)."""
        c = Caller()
        try:
            out = fn(db=c.db, **kw)
            service_commits = c.commits
            c.db.commit()
            return out, None, service_commits
        except Exception as exc:                  # noqa: BLE001 — recording
            service_commits = c.commits
            c.db.rollback()
            return None, exc, service_commits
        finally:
            c.close()

    def _challenge(cid: int):
        with SessionLocal() as db:
            return db.query(BeefChallenge).filter(BeefChallenge.id == cid).one_or_none()

    def _proposals(cid: int):
        with SessionLocal() as db:
            return (db.query(BeefProposal)
                    .filter(BeefProposal.challenge_id == cid)
                    .order_by(BeefProposal.version_number).all())

    def _starters(pid: int):
        with SessionLocal() as db:
            return (db.query(BeefProposalStarter)
                    .filter(BeefProposalStarter.proposal_id == pid).all())

    def _snapshot(p: BeefProposal) -> tuple:
        return (p.id, p.version_number, p.version_kind, p.proposing_team_id,
                p.created_at, p.response_expires_at, p.proposal_lock_at,
                p.anchor_stake_cents, p.quoted_derived_stake_cents,
                p.anchor_team_id, p.derived_team_id, p.anchor_odds,
                p.anchor_moneyline, p.pricing_input_hash, p.display_terms)

    # ══════════════════════════════════════════════════════════════════════
    # L1 — initial issue
    # ══════════════════════════════════════════════════════════════════════
    print("\nL1   initial offer creates challenge + version 1 + both-team "
          "starters (§7.1)")
    tdb.reset()
    fx = Fixture("l1")
    res, svc_commits = _issue(fx)

    ch = _challenge(res.challenge_id)
    ps = _proposals(res.challenge_id)
    _assert("L1 the service issued NO commit of its own", svc_commits == 0,
            str(svc_commits))
    _assert("L1 response_status is 'offered'", ch.response_status == OFFERED,
            str(ch.response_status))
    _assert("L1 exactly one proposal exists", len(ps) == 1, str(len(ps)))
    _assert("L1 it is version 1, kind 'initial', proposed by the challenger",
            (ps[0].version_number, ps[0].version_kind, ps[0].proposing_team_id)
            == (1, "initial", fx.a),
            f"{(ps[0].version_number, ps[0].version_kind, ps[0].proposing_team_id)}")
    _assert("L1 the active pointer names version 1",
            ch.active_proposal_id == ps[0].id)
    _assert("L1 nothing is accepted yet", ch.accepted_proposal_id is None)
    _assert("L1 the cached deadline equals the proposal's own",
            ch.active_response_expires_at == ps[0].response_expires_at)
    _assert("L1 the immutable identity is frozen on the challenge",
            (ch.challenge_mode, ch.wager_type, ch.week,
             ch.challenger_team_id, ch.challenged_team_id)
            == (MODE_LOCKED, "straight", 1, fx.a, fx.b))
    _assert("L1 anchor_team_id is the issuer, derived is the recipient",
            (ps[0].anchor_team_id, ps[0].derived_team_id) == (fx.a, fx.b))
    _assert("L1 both teams' starters are captured on the proposal",
            {s.team_id for s in _starters(ps[0].id)} == {fx.a, fx.b},
            str({s.team_id for s in _starters(ps[0].id)}))
    _assert("L1 the snapshot holds every rostered player of both teams",
            len(_starters(ps[0].id)) == 5, str(len(_starters(ps[0].id))))

    # Refusals at issue.
    _, exc, _ = _run(issue_proposal_challenge, league_id=fx.league_id, week=1,
                     challenger_team_id=fx.a, challenged_team_id=fx.a,
                     challenge_mode=MODE_LOCKED, wager_type="straight",
                     terms=_terms())
    _assert("L1 a team cannot challenge itself",
            isinstance(exc, InvalidTransitionError), f"{type(exc).__name__}")
    _, exc, _ = _run(issue_proposal_challenge, league_id=fx.league_id, week=1,
                     challenger_team_id=fx.a, challenged_team_id=fx.b,
                     challenge_mode="sideways", wager_type="straight",
                     terms=_terms())
    _assert("L1 an invalid mode is refused",
            isinstance(exc, InvalidTransitionError), f"{type(exc).__name__}")
    _, exc, _ = _run(issue_proposal_challenge, league_id=fx.league_id, week=1,
                     challenger_team_id=fx.a, challenged_team_id=fx.b,
                     challenge_mode=MODE_LOCKED, wager_type="parlay",
                     terms=_terms())
    _assert("L1 an invalid wager class is refused",
            isinstance(exc, InvalidTransitionError), f"{type(exc).__name__}")

    # ══════════════════════════════════════════════════════════════════════
    # L2 / L3 / L4 / L16 — counter, immutability, one-counter ceiling
    # ══════════════════════════════════════════════════════════════════════
    print("\nL2-L4/L16  counter creates version 2; version 1 is untouched; "
          "exactly one counter; the Anchor stays the issuer")
    tdb.reset()
    fx = Fixture("l3")
    res, _ = _issue(fx, terms=_terms(2500))
    v1_before = _snapshot(_proposals(res.challenge_id)[0])

    out, exc, svc = _run(counter_challenge_proposal,
                         challenge_id=res.challenge_id, actor_team_id=fx.b,
                         terms=_terms(4000), schedule_source_ref="sched-v2")
    _assert("L3 the recipient may counter an offered challenge",
            exc is None and out.changed is True, f"{type(exc).__name__}: {exc}")
    _assert("L3 the service issued no commit", svc == 0, str(svc))

    ps = _proposals(res.challenge_id)
    ch = _challenge(res.challenge_id)
    _assert("L3 there are now exactly two proposals", len(ps) == 2, str(len(ps)))
    _assert("L2 VERSION 1 IS BYTE-STABLE after the counter",
            _snapshot(ps[0]) == v1_before,
            "the initial proposal was mutated")
    _assert("L4 version 2 is kind 'counter', proposed by the recipient",
            (ps[1].version_number, ps[1].version_kind, ps[1].proposing_team_id)
            == (2, "counter", fx.b))
    _assert("L4 the counter carries the NEW anchor stake",
            ps[1].anchor_stake_cents == 4000 and ps[0].anchor_stake_cents == 2500,
            f"v1={ps[0].anchor_stake_cents} v2={ps[1].anchor_stake_cents}")
    _assert("L4 the wager class is unchanged by the counter",
            ch.wager_type == "straight")
    _assert("L4 mode, participants and week are unchanged",
            (ch.challenge_mode, ch.challenger_team_id, ch.challenged_team_id,
             ch.week) == (MODE_LOCKED, fx.a, fx.b, 1))
    _assert("L3 the challenge is now 'countered' and points at version 2",
            (ch.response_status, ch.active_proposal_id) == (COUNTERED, ps[1].id))
    _assert("L16 anchor_team_id on the RECIPIENT-authored counter is still the "
            "original issuer (A4)",
            (ps[1].anchor_team_id, ps[1].derived_team_id) == (fx.a, fx.b),
            f"{(ps[1].anchor_team_id, ps[1].derived_team_id)}")
    _assert("L12 the counter re-captured BOTH teams, inheriting nothing",
            {s.team_id for s in _starters(ps[1].id)} == {fx.a, fx.b}
            and len(_starters(ps[1].id)) == 5,
            str(len(_starters(ps[1].id))))
    _assert("L12 version 1 still owns its OWN starter rows, disjoint from v2's",
            {s.id for s in _starters(ps[0].id)}.isdisjoint(
                {s.id for s in _starters(ps[1].id)}))

    # A second counter is refused deterministically, not by exception (§9).
    out2, exc2, _ = _run(counter_challenge_proposal,
                         challenge_id=res.challenge_id, actor_team_id=fx.b,
                         terms=_terms(9000))
    _assert("L3 a SECOND counter returns deterministically 'already countered'",
            exc2 is None and out2.changed is False and out2.replayed is True
            and out2.detail == "already countered",
            f"{type(exc2).__name__}: {getattr(out2, 'detail', None)}")
    _assert("L3 no third proposal was created",
            len(_proposals(res.challenge_id)) == 2)

    # ══════════════════════════════════════════════════════════════════════
    # L5 — the complete §8 actor matrix
    # ══════════════════════════════════════════════════════════════════════
    print("\nL5   the §8 actor matrix, cell by cell")
    tdb.reset()
    fx = Fixture("l5")

    # offered: issuer may NOT counter / accept / decline
    r1, _ = _issue(fx)
    for action, fn in (("counter", counter_challenge_proposal),
                       ("accept",  accept_locked_proposal),
                       ("decline", decline_challenge)):
        kw = {"challenge_id": r1.challenge_id, "actor_team_id": fx.a}
        if fn is counter_challenge_proposal:
            kw["terms"] = _terms()
        _, exc, _ = _run(fn, **kw)
        _assert(f"L5 offered: the ISSUER may not {action}",
                isinstance(exc, ActorNotAuthorizedError), f"{type(exc).__name__}")
    # offered: recipient may NOT cancel
    _, exc, _ = _run(cancel_challenge, challenge_id=r1.challenge_id,
                     actor_team_id=fx.b)
    _assert("L5 offered: the RECIPIENT may not cancel",
            isinstance(exc, ActorNotAuthorizedError), f"{type(exc).__name__}")

    # countered: the countering recipient is read-only
    r2, _ = _issue(fx)
    _run(counter_challenge_proposal, challenge_id=r2.challenge_id,
         actor_team_id=fx.b, terms=_terms(3000))
    for action, fn in (("accept", accept_locked_proposal),
                       ("decline", decline_challenge)):
        _, exc, _ = _run(fn, challenge_id=r2.challenge_id, actor_team_id=fx.b)
        _assert(f"L5 countered: the COUNTERING RECIPIENT may not {action} — "
                f"read-only", isinstance(exc, ActorNotAuthorizedError),
                f"{type(exc).__name__}")
    # countered: nobody may cancel
    for who, tid in (("issuer", fx.a), ("recipient", fx.b)):
        _, exc, _ = _run(cancel_challenge, challenge_id=r2.challenge_id,
                         actor_team_id=tid)
        _assert(f"L5 countered: the {who} may not cancel — §8 grants cancel "
                f"only from 'offered'",
                isinstance(exc, (InvalidTransitionError, ActorNotAuthorizedError)),
                f"{type(exc).__name__}")
    # countered: the original issuer MAY accept
    out, exc, _ = _run(accept_locked_proposal, challenge_id=r2.challenge_id,
                       actor_team_id=fx.a)
    _assert("L5 countered: the ORIGINAL ISSUER may accept",
            exc is None and out.response_status == ACCEPTED,
            f"{type(exc).__name__}: {exc}")

    # ══════════════════════════════════════════════════════════════════════
    # L6 / L13 — Locked accept, no reprice, accepted version authoritative
    # ══════════════════════════════════════════════════════════════════════
    print("\nL6/L13  Locked acceptance selects the frozen proposal and reprices "
          "nothing (§7.3)")
    tdb.reset()
    fx = Fixture("l6")
    res, _ = _issue(fx, terms=_terms(2500))
    _run(counter_challenge_proposal, challenge_id=res.challenge_id,
         actor_team_id=fx.b, terms=_terms(4000))
    ps_before = [_snapshot(p) for p in _proposals(res.challenge_id)]

    out, exc, svc = _run(accept_locked_proposal, challenge_id=res.challenge_id,
                         actor_team_id=fx.a)
    ch = _challenge(res.challenge_id)
    ps = _proposals(res.challenge_id)

    _assert("L6 acceptance succeeded", exc is None and out.changed is True,
            f"{type(exc).__name__}: {exc}")
    _assert("L6 the service issued no commit", svc == 0, str(svc))
    _assert("L6 response_status is 'accepted'", ch.response_status == ACCEPTED)
    _assert("L13 accepted_proposal_id names the ACTIVE version, version 2",
            ch.accepted_proposal_id == ps[1].id and out.version_number == 2,
            f"{ch.accepted_proposal_id} vs v2={ps[1].id}")
    _assert("L6 NO REPRICE — both proposals are byte-stable through acceptance",
            [_snapshot(p) for p in ps] == ps_before,
            "a proposal changed during acceptance")
    _assert("L13 the accepted terms are the frozen version-2 terms",
            (ps[1].anchor_stake_cents, ps[1].anchor_odds, ps[1].anchor_moneyline)
            == (4000, 1.91, -110))
    # Package 2A is economically inert.
    with SessionLocal() as db:
        n_bets = db.execute(text("SELECT COUNT(*) FROM bets")).scalar()
        n_ledger = db.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()
    _assert("L6 acceptance created NO Bet row and NO ledger entry",
            n_bets == 0 and n_ledger == 0, f"bets={n_bets} ledger={n_ledger}")

    # Dynamic acceptance is a defined boundary, not a Package 2A path.
    fx_dyn = Fixture("l6dyn")
    rd, _ = _issue(fx_dyn, mode=MODE_DYNAMIC)
    _, exc, _ = _run(accept_locked_proposal, challenge_id=rd.challenge_id,
                     actor_team_id=fx_dyn.b)
    _assert("L6 a DYNAMIC challenge cannot be accepted here — Spec 3's boundary",
            isinstance(exc, UnsupportedModeError), f"{type(exc).__name__}")

    # ══════════════════════════════════════════════════════════════════════
    # L7 / L8 — decline and cancel
    # ══════════════════════════════════════════════════════════════════════
    print("\nL7/L8  decline, and issuer-only cancel from 'offered' only")
    tdb.reset()
    fx = Fixture("l7")
    r, _ = _issue(fx)
    out, exc, _ = _run(decline_challenge, challenge_id=r.challenge_id,
                       actor_team_id=fx.b)
    _assert("L7 the recipient declines an offered challenge",
            exc is None and _challenge(r.challenge_id).response_status == DECLINED,
            f"{type(exc).__name__}: {exc}")
    _assert("L7 declining sets no accepted proposal",
            _challenge(r.challenge_id).accepted_proposal_id is None)

    r, _ = _issue(fx)
    out, exc, _ = _run(cancel_challenge, challenge_id=r.challenge_id,
                       actor_team_id=fx.a)
    _assert("L8 the issuer cancels an offered challenge",
            exc is None and _challenge(r.challenge_id).response_status == CANCELLED,
            f"{type(exc).__name__}: {exc}")

    r, _ = _issue(fx)
    _run(counter_challenge_proposal, challenge_id=r.challenge_id,
         actor_team_id=fx.b, terms=_terms())
    _, exc, _ = _run(cancel_challenge, challenge_id=r.challenge_id,
                     actor_team_id=fx.a)
    _assert("L8 a COUNTERED challenge cannot be cancelled at all",
            isinstance(exc, InvalidTransitionError), f"{type(exc).__name__}")
    _assert("L8 it is still 'countered' afterwards",
            _challenge(r.challenge_id).response_status == COUNTERED)

    # ══════════════════════════════════════════════════════════════════════
    # L9 / L15 — expiration and the effective deadline
    # ══════════════════════════════════════════════════════════════════════
    print("\nL9/L15  the effective deadline is min(created+60m, "
          "proposal_lock_at), and expiry is system-owned (§7.4)")
    base = datetime(2026, 9, 13, 12, 0, 0)
    _assert("L15 with no lock timestamp the 60-minute TTL governs",
            effective_deadline(base, None) == base + timedelta(minutes=RESPONSE_TTL_MINUTES))
    _assert("L15 a LATER kickoff does not extend the TTL",
            effective_deadline(base, base + timedelta(hours=5))
            == base + timedelta(minutes=60))
    _assert("L15 an EARLIER kickoff truncates the window",
            effective_deadline(base, base + timedelta(minutes=20))
            == base + timedelta(minutes=20))
    _assert("L15 an AWARE lock timestamp is normalised, not mis-compared",
            effective_deadline(base, (base + timedelta(minutes=20)).replace(
                tzinfo=timezone.utc)) == base + timedelta(minutes=20))
    _assert("L15 the TTL is 60 minutes, not the legacy 24 hours",
            RESPONSE_TTL_MINUTES == 60, str(RESPONSE_TTL_MINUTES))

    tdb.reset()
    fx = Fixture("l9")
    lock_at = base + timedelta(minutes=20)
    r, _ = _issue(fx, lock_at=lock_at, now=base)
    ps = _proposals(r.challenge_id)
    _assert("L9 the proposal stored the truncated deadline",
            ps[0].response_expires_at == lock_at, str(ps[0].response_expires_at))
    _assert("L9 and its schedule source reference",
            ps[0].schedule_source_ref == "sched-v1")

    _, exc, _ = _run(expire_challenge, challenge_id=r.challenge_id,
                     now=base + timedelta(minutes=5))
    _assert("L9 expiring BEFORE the deadline is refused",
            isinstance(exc, DeadlineNotReachedError), f"{type(exc).__name__}")
    _assert("L9 the challenge is still offered",
            _challenge(r.challenge_id).response_status == OFFERED)

    out, exc, svc = _run(expire_challenge, challenge_id=r.challenge_id,
                         now=base + timedelta(minutes=21))
    _assert("L9 expiring AFTER the deadline sets 'expired'",
            exc is None and _challenge(r.challenge_id).response_status == EXPIRED,
            f"{type(exc).__name__}: {exc}")
    _assert("L9 the service issued no commit", svc == 0, str(svc))

    # A response after the deadline is refused, and does NOT itself expire the
    # challenge — expiry has exactly one writer (§7.4).
    r2, _ = _issue(fx, lock_at=lock_at, now=base)
    for action, fn, actor in (("accept", accept_locked_proposal, fx.b),
                              ("counter", counter_challenge_proposal, fx.b)):
        kw = {"challenge_id": r2.challenge_id, "actor_team_id": actor,
              "now": base + timedelta(minutes=30)}
        if fn is counter_challenge_proposal:
            kw["terms"] = _terms()
        _, exc, _ = _run(fn, **kw)
        _assert(f"L9 {action} after the deadline is refused",
                isinstance(exc, DeadlinePassedError), f"{type(exc).__name__}")
    _assert("L9 and NO read or response path expired it as a side effect",
            _challenge(r2.challenge_id).response_status == OFFERED,
            str(_challenge(r2.challenge_id).response_status))

    # ══════════════════════════════════════════════════════════════════════
    # L10 — deterministic terminal replay
    # ══════════════════════════════════════════════════════════════════════
    print("\nL10  every terminal state answers deterministically, writing "
          "nothing (§9)")
    tdb.reset()
    fx = Fixture("l10")
    for label, closer, actor, expect in (
        ("declined",  decline_challenge, fx.b, DECLINED),
        ("cancelled", cancel_challenge,  fx.a, CANCELLED),
    ):
        r, _ = _issue(fx)
        _run(closer, challenge_id=r.challenge_id, actor_team_id=actor)
        for again, fn, who in (("accept", accept_locked_proposal, fx.b),
                               ("decline", decline_challenge, fx.b),
                               ("cancel", cancel_challenge, fx.a),
                               ("expire", expire_challenge, None)):
            kw = {"challenge_id": r.challenge_id}
            if who is not None:
                kw["actor_team_id"] = who
            out, exc, svc = _run(fn, **kw)
            _assert(f"L10 [{label}] a later {again} returns 'already {label}'",
                    exc is None and out.replayed is True and out.changed is False
                    and out.response_status == expect,
                    f"{type(exc).__name__}: {getattr(out, 'detail', None)}")
        _assert(f"L10 [{label}] the state never moved",
                _challenge(r.challenge_id).response_status == expect)

    # accepted is action-closed for negotiation but NOT wager-terminal (§4).
    r, _ = _issue(fx)
    _run(accept_locked_proposal, challenge_id=r.challenge_id, actor_team_id=fx.b)
    out, exc, _ = _run(decline_challenge, challenge_id=r.challenge_id,
                       actor_team_id=fx.b)
    _assert("L10 declining an ACCEPTED challenge returns 'already accepted'",
            exc is None and out.detail == "already accepted"
            and out.response_status == ACCEPTED, str(getattr(out, "detail", None)))
    _assert("L10 the accepted proposal pointer survives that call",
            _challenge(r.challenge_id).accepted_proposal_id is not None)
    _assert("L10 §4: 'accepted' is NOT in the negotiation-terminal set, so "
            "settlement is never blocked by it",
            _challenge(r.challenge_id).response_status == ACCEPTED)

    # ══════════════════════════════════════════════════════════════════════
    # L11 — revive creates a NEW challenge
    # ══════════════════════════════════════════════════════════════════════
    print("\nL11  revive produces an entirely NEW challenge, never reopening "
          "the old one (§8)")
    tdb.reset()
    fx = Fixture("l11")
    old, _ = _issue(fx, terms=_terms(2500))
    _run(decline_challenge, challenge_id=old.challenge_id, actor_team_id=fx.b)
    old_before = _challenge(old.challenge_id)
    old_state = (old_before.response_status, old_before.active_proposal_id,
                 old_before.accepted_proposal_id, old_before.updated_at)
    old_props = [_snapshot(p) for p in _proposals(old.challenge_id)]

    new, exc, svc = _run(revive_challenge, challenge_id=old.challenge_id,
                         actor_team_id=fx.a, terms=_terms(7777),
                         schedule_source_ref="sched-revive")
    _assert("L11 the original issuer may revive a declined challenge",
            exc is None and new.changed is True, f"{type(exc).__name__}: {exc}")
    _assert("L11 the service issued no commit", svc == 0, str(svc))
    _assert("L11 a NEW challenge id was produced",
            new.challenge_id != old.challenge_id,
            f"{new.challenge_id} vs {old.challenge_id}")
    nch = _challenge(new.challenge_id)
    nps = _proposals(new.challenge_id)
    _assert("L11 the new challenge is 'offered' with a fresh version 1",
            (nch.response_status, len(nps), nps[0].version_number,
             nps[0].version_kind) == (OFFERED, 1, 1, "initial"))
    _assert("L11 with fresh proposal id and fresh terms",
            nps[0].id != old_props[0][0] and nps[0].anchor_stake_cents == 7777)
    _assert("L11 with fresh both-team starters of its own",
            {s.team_id for s in _starters(nps[0].id)} == {fx.a, fx.b}
            and {s.id for s in _starters(nps[0].id)}.isdisjoint(
                {s.id for s in _starters(old_props[0][0])}))
    _assert("L11 lineage is recorded on the NEW row",
            nch.revived_from_challenge_id == old.challenge_id)
    _assert("L11 THE OLD CHALLENGE IS UNTOUCHED — not reopened, not mutated",
            (_challenge(old.challenge_id).response_status,
             _challenge(old.challenge_id).active_proposal_id,
             _challenge(old.challenge_id).accepted_proposal_id,
             _challenge(old.challenge_id).updated_at) == old_state,
            "the terminal challenge was modified by revive")
    _assert("L11 and its proposals are byte-stable",
            [_snapshot(p) for p in _proposals(old.challenge_id)] == old_props)

    # Only the original issuer, only from terminal.
    _, exc, _ = _run(revive_challenge, challenge_id=old.challenge_id,
                     actor_team_id=fx.b, terms=_terms())
    _assert("L11 the recipient may NOT revive",
            isinstance(exc, ActorNotAuthorizedError), f"{type(exc).__name__}")
    live, _ = _issue(fx)
    _, exc, _ = _run(revive_challenge, challenge_id=live.challenge_id,
                     actor_team_id=fx.a, terms=_terms())
    _assert("L11 a LIVE challenge cannot be revived",
            isinstance(exc, InvalidTransitionError), f"{type(exc).__name__}")

    # ══════════════════════════════════════════════════════════════════════
    # L14 — no proposal mutation path
    # ══════════════════════════════════════════════════════════════════════
    print("\nL14  the service contains no path that updates a proposal row")
    import ast as _ast
    from pathlib import Path as _Path
    svc_src = (_Path(os.path.dirname(os.path.abspath(__file__)))
               / "beefs" / "proposal_lifecycle.py").read_text(encoding="utf-8")
    tree = _ast.parse(svc_src)
    proposal_writes = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Assign):
            for tgt in node.targets:
                if (isinstance(tgt, _ast.Attribute)
                        and isinstance(tgt.value, _ast.Name)
                        and tgt.value.id in ("proposal", "active", "p")):
                    proposal_writes.append(f"{tgt.value.id}.{tgt.attr}:{node.lineno}")
    _assert("L14 no attribute of a loaded proposal is ever assigned",
            proposal_writes == [], str(proposal_writes))
    _assert("L14 proposals are only ever constructed, never updated",
            svc_src.count("BeefProposal(") == 1,
            "exactly one construction site, inside _insert_proposal")

    # Behavioural: after a full lifecycle, every proposal is byte-stable.
    tdb.reset()
    fx = Fixture("l14")
    r, _ = _issue(fx, terms=_terms(1000))
    snap_v1 = _snapshot(_proposals(r.challenge_id)[0])
    _run(counter_challenge_proposal, challenge_id=r.challenge_id,
         actor_team_id=fx.b, terms=_terms(2000))
    snap_v2 = _snapshot(_proposals(r.challenge_id)[1])
    _run(accept_locked_proposal, challenge_id=r.challenge_id, actor_team_id=fx.a)
    after = [_snapshot(p) for p in _proposals(r.challenge_id)]
    _assert("L14 both versions survive issue → counter → accept byte-stable",
            after == [snap_v1, snap_v2])

    # ══════════════════════════════════════════════════════════════════════
    # L17 — cross-league isolation and unknown/legacy challenges
    # ══════════════════════════════════════════════════════════════════════
    print("\nL17  cross-league isolation, unknown ids, and legacy rows")
    tdb.reset()
    fx = Fixture("l17a")
    other = Fixture("l17b")
    r, _ = _issue(fx)
    for label, fn, kw in (
        ("counter", counter_challenge_proposal,
         {"actor_team_id": other.b, "terms": _terms()}),
        ("accept",  accept_locked_proposal, {"actor_team_id": other.b}),
        ("decline", decline_challenge,      {"actor_team_id": other.b}),
        ("cancel",  cancel_challenge,       {"actor_team_id": other.a}),
    ):
        _, exc, _ = _run(fn, challenge_id=r.challenge_id, **kw)
        _assert(f"L17 a team from ANOTHER league cannot {label}",
                isinstance(exc, ActorNotAuthorizedError), f"{type(exc).__name__}")
    _assert("L17 the challenge is untouched by every cross-league attempt",
            _challenge(r.challenge_id).response_status == OFFERED)

    _, exc, _ = _run(accept_locked_proposal, challenge_id=999_999,
                     actor_team_id=fx.b)
    _assert("L17 an unknown challenge id raises ChallengeNotFoundError",
            isinstance(exc, ChallengeNotFoundError), f"{type(exc).__name__}")

    # A legacy mutable challenge — no response_status — is refused, not adopted.
    with SessionLocal() as db:
        legacy = BeefChallenge(
            challenger_team_id=fx.a, challenged_team_id=fx.b, week=1,
            bet_type="straight", amount=10.0, challenger_odds=1.9,
            challenged_odds=1.9, challenger_moneyline=-110,
            challenged_moneyline=-110, status="pending",
            expires_at=datetime(2026, 9, 13, 12, 0, 0))
        db.add(legacy); db.commit(); legacy_id = legacy.id
    _, exc, _ = _run(accept_locked_proposal, challenge_id=legacy_id,
                     actor_team_id=fx.b)
    _assert("L17 a LEGACY challenge is refused, never adopted into the new "
            "model (§11)", isinstance(exc, NotANewModelChallengeError),
            f"{type(exc).__name__}")


try:
    main(tdb)
finally:
    tdb.teardown()

print("\n" + "=" * 60)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("All assertions PASSED")
