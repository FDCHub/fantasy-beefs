"""
auth/yahoo_identity.py — turning a Yahoo subject into a FantasyStakes user.

ONE QUESTION, ANSWERED ONCE: given that Yahoo has just authenticated somebody,
which FantasyStakes account is that? Everything about how the flow got here
belongs to `yahoo_oidc.py`; everything about what the account may then DO
belongs to the existing authorization guards, which this does not touch.

THREE OUTCOMES, AND THE MIDDLE ONE IS THE DELICATE PART.

  1. LINKED ALREADY. A row carries this `(yahoo, subject)`. That row is the
     user, whatever their email says today. This is the ordinary case on every
     sign-in after the first, and it is why the subject is the key: a GM who
     changed their Yahoo address overnight lands back on their own Ledger.

  2. CLAIMABLE. No row carries the subject, but exactly one row carries this
     email and no provider identity at all. That is a pre-cutover account
     meeting its owner for the first time, and it is LINKED rather than
     duplicated — the alternative would leave a GM's wagers, Credits and league
     membership stranded on an account they can no longer reach.

     THE CLAIM IS NARROW ON PURPOSE. It requires an exact email match, on a row
     that is not already linked to a DIFFERENT subject. A row already bound to
     another Yahoo account is never re-bound, because that would be one person
     taking over another's identity by controlling an address.

  3. NEW. Nobody matches, so a new account is created — with no password, no
     team and no role beyond `gm`. Yahoo identity grants nothing: league
     membership, commissioner standing and every other authority still come
     from the existing guards, and a brand-new account has none of them.

WHAT THIS NEVER DOES. It never merges two existing FantasyStakes accounts, never
moves a team between users, never changes a role, and never touches a Ledger.
Those are ownership decisions, and an authentication callback is not the place
any of them should be made silently.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.schema import User

__all__ = ["PROVIDER_YAHOO", "ResolvedIdentity", "resolve_user"]

#: The one provider this build authenticates with.
PROVIDER_YAHOO = "yahoo"


@dataclass(frozen=True)
class ResolvedIdentity:
    """Which account answered, and how it was reached.

    `outcome` is for the certification suite and for an operator reading a
    support question — it is never rendered to a GM, who simply arrives in the
    product.
    """

    user: User
    outcome: str          # "linked" | "claimed" | "created"


def resolve_user(db: Session, *, subject: str, email: str | None,
                 display_name: str | None = None) -> ResolvedIdentity:
    """Find or create the FantasyStakes account for a Yahoo subject.

    :param subject: Yahoo's stable `sub`. Required; never an email.
    :param email: the address Yahoo reported, for contact and display only.
    """
    subject = (subject or "").strip()
    if not subject:
        # Defensive: `validate_id_token` already refuses this. A blank subject
        # reaching here would match every other blank subject, which is the one
        # way this function could fuse two people into one account.
        raise ValueError("a Yahoo identity requires a subject")

    normalised = (email or "").strip().lower() or None

    # ── 1 · already linked ───────────────────────────────────────────────────
    linked = (db.query(User)
              .filter(User.auth_provider == PROVIDER_YAHOO,
                      User.provider_subject == subject)
              .first())
    if linked is not None:
        # THE EMAIL FOLLOWS THE IDENTITY, not the other way round. Yahoo is
        # authoritative for the address on the account, so a change is recorded
        # — but it changes nothing about WHICH account this is, and the unique
        # constraint on `email` means a collision leaves the stored value alone
        # rather than failing a sign-in over a display field.
        if normalised and linked.email != normalised:
            clash = (db.query(User)
                     .filter(User.email == normalised, User.id != linked.id)
                     .first())
            if clash is None:
                linked.email = normalised
        _touch(linked)
        db.commit()
        return ResolvedIdentity(user=linked, outcome="linked")

    # ── 2 · claimable pre-cutover account ────────────────────────────────────
    if normalised:
        candidate = (db.query(User)
                     .filter(User.email == normalised,
                             User.provider_subject.is_(None))
                     .first())
        if candidate is not None:
            candidate.auth_provider = PROVIDER_YAHOO
            candidate.provider_subject = subject
            # THE PASSWORD HASH IS LEFT ALONE. Clearing it here would make the
            # rollback this package promises unsafe: a deployment rolled back to
            # pre-WP3D.1 code would find an account nobody can sign into. It is
            # inert either way — production accepts no password — and retiring
            # the column is a separate, later cleanup.
            _touch(candidate)
            db.commit()
            return ResolvedIdentity(user=candidate, outcome="claimed")

    # ── 3 · a new FantasyStakes account ──────────────────────────────────────
    #
    # NO TEAM, NO ROLE, NO MEMBERSHIP. A Yahoo sign-in proves who somebody is
    # and nothing else. Whether they are in a league, and whether they
    # commission one, is decided by the existing authorization surfaces exactly
    # as it was before this package.
    # THE ADDRESS MAY ALREADY BELONG TO SOMEBODY ELSE, AND THAT IS NOT AN ERROR.
    #
    # `users.email` is unique, and two DIFFERENT Yahoo accounts can legitimately
    # report the same address at different times — an address is released and
    # later reassigned, or a person moves one between accounts. Inserting the
    # contested value would violate the constraint and turn an ordinary sign-in
    # into a 500; taking it from the existing account would be handing one
    # person's identity to another, which is the exact failure keying on the
    # subject exists to prevent.
    #
    # So the new account is created WITHOUT claiming the address. It is a real
    # account with a real identity — the subject — and no contact address, which
    # is the truth. The first holder keeps theirs.
    taken = (normalised is not None
             and db.query(User).filter(User.email == normalised).first()
             is not None)
    # A PLACEHOLDER ADDRESS IS MARKED AS ONE. `.invalid` is reserved by RFC 2606
    # and can never be delivered to, so an account with no usable address — or
    # one whose address is held elsewhere — cannot be mistaken for one that has
    # a real inbox.
    #
    # IT IS A DIGEST OF THE SUBJECT, NOT THE SUBJECT. `email` is a DISPLAYED
    # field: the masthead falls back to it when an account has no team, so a raw
    # Yahoo subject printed there would put a provider identifier on screen for
    # no reason. A digest keeps the two properties that matter — deterministic,
    # so the same account gets the same placeholder, and unique, so two accounts
    # never collide — without displaying the identity itself.
    user = User(
        email=(normalised if (normalised and not taken)
               else _placeholder_email(subject)),
        hashed_password=None,
        auth_provider=PROVIDER_YAHOO,
        provider_subject=subject,
        team_id=None,
        role="gm",
    )
    db.add(user)
    _touch(user)
    db.commit()
    db.refresh(user)
    return ResolvedIdentity(user=user, outcome="created")


def _placeholder_email(subject: str) -> str:
    """A unique, undeliverable, non-identifying stand-in address."""
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:16]
    return f"yahoo-{digest}@yahoo.invalid"


def _touch(user: User) -> None:
    user.last_login_at = datetime.now(timezone.utc)
    if user.is_active is None:
        user.is_active = 1
