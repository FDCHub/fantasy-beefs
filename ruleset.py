"""
ruleset.py — the one era gate for the Final POR (WP-1).

WHAT THIS MODULE IS. The single place that answers "which edition of the
FantasyStakes rules governs this league-season?", and the named constants that
question is answered with. It reads one row, it stamps one row, and it decides
nothing else.

WHY ONE VERSION AND NOT THREE. The Final POR changes scoring (FantasyStakes
Score gains a Skunk term), economy (Weekly Minimum forfeiture, league-level
pots, Top-Off pot growth), lifecycle (the FantasyStakes Championship no longer
freezes at the playoff boundary) and reconciliation (My Settle's obligation set)
TOGETHER AND INSEPARABLY. A season is played entirely under one edition of them.
Separate `scoring_version` / `economy_version` / `lifecycle_version` columns
would each be individually defensible and could, between them, describe a season
that never existed — a season scored the new way and settled the old way. One
integer cannot do that.

── ABSENCE IS THE LEGACY ERA, EXPLICITLY ────────────────────────────────────

No row means `RULESET_LEGACY`. This is not a default standing in for missing
data: it is the correct and complete answer for every season activated before
WP-1, and it is what makes the Final POR PROSPECTIVE. Nothing is backfilled,
no frozen score is recomputed, no paid award is revisited, and no historical
posting is rewritten. `LeagueSeasonEconomyConfig` established the same
"absence is a governed state" convention for the same reason.

── WHERE THIS IS AND IS NOT CONSULTED ───────────────────────────────────────

CONSULTED at every point where the Final POR and the legacy rules would produce
DIFFERENT MONEY OR A DIFFERENT SCORE: the Weekly Minimum week-close destination,
the FantasyStakes Score identity, championship pot funding, the championship
lifecycle, and the My Settle obligation set.

NOT CONSULTED for anything both eras agree on. Min-first spend sourcing, the
non-negative Wallet guard, escrow attribution, the third-place rule and the
canonical remainder convention are unchanged by the Final POR, and threading a
version through them would imply a difference that does not exist.

── A TOP-LEVEL MODULE, DELIBERATELY ─────────────────────────────────────────

`economy`, `reports` and `betting` all consult the gate. Putting it inside any
one of them would make the other two reach into a sibling package for a fact
that belongs to none of them. It imports `db.schema` and nothing else, so it can
be imported from anywhere without forming a cycle.

`season/` would have been the natural home by name and is FORBIDDEN by that
package's own contract: nothing under `season/` may import `db`, and
`test_wp1a_championship_track` walks its AST to prove it.
"""

from __future__ import annotations

from datetime import datetime, timezone

#: The rules as they stood through RC2 — the era of every season activated
#: before WP-1. REPRESENTED BY THE ABSENCE OF A ROW, never written.
#:
#:   FantasyStakes Score = matchup net + prop-pool net
#:   unused Weekly Minimum -> expired_min: -> Wallet at season close
#:   championship pots funded by per-GM contributions
#:   FantasyStakes Championship frozen at the playoff boundary
#:   Skunk pot paid whole to the regular-season Points For leader
RULESET_LEGACY = 1

#: The Final POR.
#:
#:   FantasyStakes Score = matchup net + prop-pool net - Skunk fees
#:   unused Weekly Minimum -> FantasyStakes Championship Pot at WEEK close
#:   championship pots are league-level minted allocations
#:   FantasyStakes Championship runs through the postseason; LIVE -> FINAL -> PAID
#:   Points Championship pot = Skunk actually assessed, paid 60/30/10
#:   an approved Top-Off grows the FantasyStakes Championship Pot by the same amount
RULESET_FINAL_POR = 2

#: What a season activated today is stamped with. Named separately from
#: `RULESET_FINAL_POR` so a future edition changes ONE constant and every
#: activation site follows, without any of them naming a version literal.
CURRENT_RULESET = RULESET_FINAL_POR


class RulesetError(ValueError):
    """A ruleset stamp was refused, carrying a stable reason code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_ALREADY_STAMPED = "RULESET_ALREADY_STAMPED"
REASON_UNKNOWN_VERSION = "RULESET_UNKNOWN_VERSION"

#: Every version this build knows how to play. A row carrying anything else is a
#: database written by a NEWER build, and this one must not guess at its rules.
KNOWN_RULESETS = frozenset({RULESET_LEGACY, RULESET_FINAL_POR})


def resolve_ruleset_version(db, *, league_id: int, season: int) -> int:
    """The ruleset governing this league-season. Never raises for absence.

    Absence returns `RULESET_LEGACY` — the governed answer for every
    pre-WP-1 season, not a fallback standing in for a missing row.

    A row carrying a version this build does not know is a REFUSAL rather than
    a silent downgrade. Reading a newer season under older rules would score it,
    settle it and reconcile it wrongly while reporting success, and the
    divergence would be invisible in the ledger afterwards.
    """
    from db.schema import LeagueSeasonRuleset

    row = (db.query(LeagueSeasonRuleset)
           .filter(LeagueSeasonRuleset.league_id == league_id,
                   LeagueSeasonRuleset.season == season)
           .one_or_none())
    if row is None:
        return RULESET_LEGACY
    version = int(row.ruleset_version)
    if version not in KNOWN_RULESETS:
        raise RulesetError(
            REASON_UNKNOWN_VERSION,
            f"league {league_id} season {season} is stamped ruleset "
            f"{version}, which this build does not implement (known: "
            f"{sorted(KNOWN_RULESETS)}). Refusing to play a season under rules "
            f"it was not activated under.")
    return version


def is_final_por(db, *, league_id: int, season: int) -> bool:
    """Whether the Final POR governs this league-season.

    The predicate every era-gated site calls. Written as `>=` rather than `==`
    so a later edition that keeps the Final POR's economy does not have to
    revisit every call site — and so no call site has to name a version literal.
    """
    return resolve_ruleset_version(
        db, league_id=league_id, season=season) >= RULESET_FINAL_POR


def stamp_ruleset(db, *, league_id: int, season: int,
                  version: int = CURRENT_RULESET,
                  now: datetime | None = None):
    """Record the ruleset governing a league-season. Does NOT commit.

    Called once, by activation, inside the activation transaction — so a season
    that fails to activate is not left stamped, and a stamped season is one that
    really was activated under those rules.

    IDEMPOTENT ON AGREEMENT, A CONFLICT ON DISAGREEMENT. A replay that stamps the
    same version returns the existing row. A second stamp naming a DIFFERENT
    version raises: the row governs Credits already issued and results already
    scored, and treating a contradiction as a replay would report success while
    the wrong rules quietly governed the season. That is the rule
    `freeze_economy_config` already applies to the frozen economy configuration.
    """
    from db.schema import LeagueSeasonRuleset

    if int(version) not in KNOWN_RULESETS:
        raise RulesetError(
            REASON_UNKNOWN_VERSION,
            f"ruleset {version} is not implemented by this build "
            f"(known: {sorted(KNOWN_RULESETS)}).")

    now = now or datetime.now(timezone.utc)
    row = (db.query(LeagueSeasonRuleset)
           .filter(LeagueSeasonRuleset.league_id == league_id,
                   LeagueSeasonRuleset.season == season)
           .one_or_none())
    if row is not None:
        if int(row.ruleset_version) != int(version):
            raise RulesetError(
                REASON_ALREADY_STAMPED,
                f"league {league_id} season {season} is already governed by "
                f"ruleset {row.ruleset_version} (stamped {row.stamped_at}); "
                f"refusing to restamp it as {version}. The ruleset governs "
                f"Credits already issued and is never updated in place.")
        return row

    row = LeagueSeasonRuleset(league_id=league_id, season=season,
                              ruleset_version=int(version), stamped_at=now)
    db.add(row)
    db.flush()
    return row
