"""
scripts/bootstrap_league_commissioner.py

OPERATOR-ONLY, ONE-TIME GENESIS. Creates the FIRST commissioner for one league
and nothing else. Every commissioner after the first is granted through the
authenticated route POST /league/{league_id}/commissioners, by an existing
commissioner of that same league.

WHY THIS EXISTS. Authority is a LeagueCommissioner row, so a league with zero
rows has no one who can grant the first one — a bootstrap paradox. Direct,
unattributed database INSERTs were ruled unacceptable, so this CLI is the single
sanctioned way to break that cycle. It is deliberately the narrowest possible
tool: it refuses the moment a league already has any authority row.

SELF-LIMITING. Refuses if ANY LeagueCommissioner row exists for the league —
including one naming the same user. It can only ever create row number one.
This restriction belongs to this CLI alone; the table and the grant route remain
many-to-many, and a league may hold as many commissioners as it is granted.

EXPLICIT IDS ONLY. --league-id and --user-id are required and are the only
selectors. No names, emails, team ids, Yahoo ids, role names, "first user" or
any other discovery: an inferred grant is exactly the failure mode this package
exists to prevent.

RACE SAFETY. The unique constraint on (league_id, user_id) does NOT prevent two
different users from both becoming the first commissioner concurrently — it only
blocks a duplicate of the same pair. A plain count-then-insert is therefore
insufficient. This script takes SELECT ... FOR UPDATE on the league row before
counting, following betting/settlement_engine.py, so concurrent invocations
serialize on that row and exactly one can observe an empty authority set.

SECURITY. No HTTP exposure. No import side effect — importing this module runs
nothing. No credentials or database URL are printed. No production default is
baked in; the database comes from the repository's standard configuration. No
retry, because a silent retry would mask precisely the race this lock prevents.

USAGE
    DATABASE_URL="<url>" python scripts/bootstrap_league_commissioner.py \
        --league-id 1 --user-id 4
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from db.schema import League, LeagueCommissioner, SessionLocal, User

SOURCE = "bootstrap"


class GenesisRefused(RuntimeError):
    """Raised when genesis is not permitted. Nothing has been written."""


def bootstrap_first_commissioner(league_id: int, user_id: int) -> dict:
    """Create the first LeagueCommissioner row for `league_id`.

    Returns a record of what was inserted. Raises GenesisRefused, without
    writing anything, if the league or user is missing, the user is inactive,
    or the league already has any authority row.

    ONE COMMIT, and only on the success path. Every refusal rolls back first, so
    the FOR UPDATE lock is released and no partial state can persist.
    """
    with SessionLocal() as db:
        try:
            # Lock the league row FIRST. Concurrent genesis attempts for this
            # league serialize here, so only one can pass the emptiness check
            # below. Held until this transaction commits or rolls back.
            locked = db.execute(
                text("SELECT id FROM leagues WHERE id = :lid FOR UPDATE"),
                {"lid": league_id},
            ).fetchone()

            if locked is None:
                raise GenesisRefused(f"league {league_id} does not exist")

            user = db.query(User).filter(User.id == user_id).first()
            if user is None:
                raise GenesisRefused(f"user {user_id} does not exist")
            if not user.is_active:
                raise GenesisRefused(f"user {user_id} is inactive")

            existing = (
                db.query(LeagueCommissioner)
                .filter(LeagueCommissioner.league_id == league_id)
                .all()
            )
            if existing:
                holders = sorted(r.user_id for r in existing)
                raise GenesisRefused(
                    f"league {league_id} already has {len(existing)} commissioner "
                    f"row(s) for user id(s) {holders}. Genesis creates only the "
                    f"FIRST commissioner. Use POST /league/{league_id}/commissioners "
                    f"as an existing commissioner of that league to grant another."
                )

            row = LeagueCommissioner(
                league_id           = league_id,
                user_id             = user_id,
                source              = SOURCE,
                assigned_by_user_id = None,   # genesis has no granting user
            )
            db.add(row)
            db.commit()                       # the one and only commit
            db.refresh(row)

            return {
                "authority_row_id":    row.id,
                "league_id":           row.league_id,
                "user_id":             row.user_id,
                "source":              row.source,
                "assigned_by_user_id": row.assigned_by_user_id,
                "created_at":          row.created_at.isoformat() if row.created_at else None,
            }
        except Exception:
            db.rollback()
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bootstrap_league_commissioner",
        description="Create the FIRST commissioner for one league. Refuses if the "
                    "league already has any commissioner.",
    )
    parser.add_argument("--league-id", type=int, required=True,
                        help="Local league id (integer primary key). Required.")
    parser.add_argument("--user-id", type=int, required=True,
                        help="Local user id (integer primary key). Required.")
    args = parser.parse_args(argv)

    try:
        record = bootstrap_first_commissioner(args.league_id, args.user_id)
    except GenesisRefused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        print("Nothing was written.", file=sys.stderr)
        return 2
    except Exception as e:                      # database/driver failure
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        print("Rolled back. Nothing was written.", file=sys.stderr)
        return 1

    print("GENESIS COMMISSIONER CREATED")
    print(f"  authority_row_id    : {record['authority_row_id']}")
    print(f"  league_id           : {record['league_id']}")
    print(f"  user_id             : {record['user_id']}")
    print(f"  source              : {record['source']}")
    print(f"  assigned_by_user_id : {record['assigned_by_user_id']}")
    print(f"  created_at          : {record['created_at']}")
    print("This league now has its first commissioner. Grant any further "
          "commissioners through POST /league/{league_id}/commissioners.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
