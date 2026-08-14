"""
WP1B — championship-track state to Pool subject universe.

THE ONE THING THIS MODULE DOES: turn WP1A's provider-neutral
`ChampionshipTrackState` into the internal team ids and matchup ids that the
certified Pool engine already understands, and FREEZE that answer for the week.

Everything downstream of the freeze is unchanged code. `pool_census.classify_pool`
still iterates `structure.considered_subject_ids`; `YahooProviderStatSource.
subjects_for` still builds facts for exactly the ids it is handed;
`pool_settlement.settle_pool_instance` still calls `league_weekly_structure` with
the same three arguments it always did. Contracting one tuple contracts the whole
pipeline, which is why this package is small.

── THE RESOLVER IS INJECTED, NOT IMPORTED ────────────────────────────────────

`betting/` imports nothing from `providers/` and this module does not change
that. The provider-team-key to internal-team-id mapping is the certified
`providers.yahoo.identity.build_team_identity_resolver`, and the CALLER supplies
it — the same injection shape `betting/pool_settlement.py` already uses for its
stat source. Two properties fall out of that: the certified identity rule (S6-R1:
the compound provider key is the identity, never a name or an email) is reused
rather than reimplemented, and a Demo provider satisfies this module by
supplying its own resolver with no change here.

── FAIL CLOSED, AND SAY WHICH CLOSURE ────────────────────────────────────────

Every refusal below is a named error. The failure this module exists to prevent
is not an exception — it is a plausible-looking postseason Pool drawn over all
twelve league teams, four of which are playing consolation. That one does not
raise anything; it settles, and it pays a GM who picked an eliminated team.
So there is no path here that returns a partial or default universe: either the
championship state is authoritative and completely resolvable, or the draw is
refused before an occurrence exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from betting.pool_subjects import SCOPE_MATCHUP, SCOPE_TEAM

REASON_NO_TRACK_STATE = "CHAMPIONSHIP_STATE_NOT_SUPPLIED"
REASON_TRACK_UNKNOWN = "CHAMPIONSHIP_STATE_UNKNOWN"
REASON_UNRESOLVED_TEAM = "CHAMPIONSHIP_TEAM_UNRESOLVED"
REASON_UNRESOLVED_MATCHUP = "CHAMPIONSHIP_MATCHUP_UNRESOLVED"
REASON_EMPTY_UNIVERSE = "CHAMPIONSHIP_UNIVERSE_EMPTY"
REASON_ALREADY_FROZEN = "CHAMPIONSHIP_MANIFEST_CONFLICT"


class PostseasonSubjectError(ValueError):
    """A postseason subject universe could not be established.

    A ValueError subclass so an existing `except ValueError` around slate
    construction still catches it, carrying `reason` for the surfaces that map
    refusals to reason codes."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


# ── Championship-week themed slate (WP1B §12) ─────────────────────────────────
#
# WHY THESE FOUR, AND WHY THEY ARE KEYS RATHER THAN A NEW CATALOG COLUMN. The
# championship round faces a two-team, one-matchup field. Most of the postseason
# catalog still WORKS there, but "which of these two teams gained more receiving
# yards" is a thin title-week card. These four were chosen because each measures
# something different about a two-team field, and every one of them is an
# EXISTING gate-1-eligible definition using an existing evaluator shape — no new
# family, no new stat, no new phase and no schema:
#
#   most_complete_offensive_production  #42  the title decider — total scored
#                                            fantasy points across the starting
#                                            lineup, which is the closest thing
#                                            the catalog has to "who played best"
#   most_dual_threat_yards              #17  PLAYER_EXTREMUM_WITHIN_SUBJECT — the
#                                            single best individual performance,
#                                            not a team sum. The one shape that
#                                            makes a title week feel personal.
#   the_grand_slam                      #1   the marquee milestone qualifier, and
#                                            one of only sixteen rollover-eligible
#                                            rows in the entire catalog
#   matchups_with_700plus_combined_...  #91  the title GAME itself as a single
#                                            yes/no proposition — permitted
#                                            MATCHUP/QUALIFIER, never a
#                                            matchup-vs-matchup contest
#
# ORDER IS LOAD-BEARING. It is the deterministic preference order used when the
# gates leave fewer than four of them standing, so a reader can predict which
# survives a partial-support week without running the selector.
CHAMPIONSHIP_PREFERRED_KEYS: tuple[str, ...] = (
    "most_complete_offensive_production",
    "most_dual_threat_yards",
    "the_grand_slam",
    "matchups_with_700plus_combined_offensive_yards",
)


def is_championship_round(state) -> bool:
    """Whether `state` describes the round that decides the championship.

    Read from WP1A's own arithmetic — `championship_round_ordinal ==
    round_count_expected` — and never from a week number. A league whose
    championship track ends in round two identifies its title week exactly as
    well as one that ends in round three, which is the property that keeps the
    themed slate free of Fraser's league.

    False when either value is absent: an unknown round count cannot establish
    that this round is the last one, and guessing would theme a semi-final.
    """
    if state is None:
        return False
    ordinal = state.championship_round_ordinal
    expected = state.round_count_expected
    return (ordinal is not None and expected is not None and ordinal == expected)


# ── Resolution ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ResolvedUniverse:
    """The internal-id subject universe for one postseason week."""

    team_ids: tuple[int, ...]
    matchup_ids: tuple[int, ...]

    def for_scope(self, scope: str) -> tuple[int, ...]:
        if scope == SCOPE_TEAM:
            return self.team_ids
        if scope == SCOPE_MATCHUP:
            return self.matchup_ids
        raise PostseasonSubjectError(
            REASON_EMPTY_UNIVERSE,
            f"scope {scope!r} has no postseason subject rule; "
            f"betting.pool_subjects owns that ruling (POR §6.2).")


def resolve_universe(db, *, league_id: int, week: int, state,
                     resolver) -> ResolvedUniverse:
    """Championship state -> internal team ids and matchup ids. Reads only.

    Refuses rather than partially resolving. A championship team whose provider
    key maps to no internal team, or a championship matchup whose derived key
    matches no persisted row, would each silently shrink the universe — and a
    silently shrunk universe is indistinguishable downstream from a legitimately
    smaller field. `pool_census` would then census the short set, find it
    complete, and settle.
    """
    from db.schema import Matchup

    if state is None:
        raise PostseasonSubjectError(
            REASON_NO_TRACK_STATE,
            f"league {league_id} week {week} is a postseason week and no "
            f"championship track state was supplied. The postseason subject "
            f"universe is not derivable from league membership.")

    allowed = state.championship_subject_team_keys()
    if allowed is None:
        raise PostseasonSubjectError(
            REASON_TRACK_UNKNOWN,
            f"league {league_id} week {week}: the championship track is not "
            f"determinable (authority={state.authority.value}, reasons="
            f"{list(state.insufficiency_reasons)}). Refusing to draw a "
            f"postseason slate — there is no fallback to the league's teams.")

    # ── TEAM universe. Bye teams ARE included: a bye team is championship-alive
    # (WP1B §5), and `championship_subject_team_keys()` returns the CONTESTING
    # field, which is byes plus this round's participants. Whether that team's
    # week is evaluable is a data question the census answers later, per its own
    # fail-closed rule; it is emphatically not a reason to drop the team here.
    team_ids: list[int] = []
    unresolved: list[str] = []
    for team_key in sorted(allowed):
        try:
            internal = resolver.to_internal(team_key)
        except Exception:                       # noqa: BLE001 - re-raised named
            internal = None
        if internal is None:
            unresolved.append(team_key)
            continue
        team_ids.append(int(internal))
    if unresolved:
        raise PostseasonSubjectError(
            REASON_UNRESOLVED_TEAM,
            f"league {league_id} week {week}: {len(unresolved)} championship "
            f"team(s) have no internal identity ({unresolved!r}). S6-R1 forbids "
            f"matching them by name, and a partial field would settle as though "
            f"it were complete.")

    # ── MATCHUP universe. Joined on `provider_matchup_key`, the derived,
    # mirror-stable identity providers/base.py constructs — never on team ids,
    # never on a name. A championship matchup with no persisted row is a
    # refusal, not an omission: the alternative is a census that silently drops
    # a title game.
    matchup_ids: list[int] = []
    missing_keys: list[str] = []
    if state.championship_matchups:
        wanted = {m.matchup_key for m in state.championship_matchups}
        rows = (db.query(Matchup)
                .filter(Matchup.league_id == league_id,
                        Matchup.week == week,
                        Matchup.provider_matchup_key.in_(sorted(wanted)))
                .all())
        found = {r.provider_matchup_key: r.id for r in rows}
        for key in sorted(wanted):
            if key not in found:
                missing_keys.append(key)
            else:
                matchup_ids.append(int(found[key]))
    if missing_keys:
        raise PostseasonSubjectError(
            REASON_UNRESOLVED_MATCHUP,
            f"league {league_id} week {week}: {len(missing_keys)} championship "
            f"matchup(s) have no persisted row with a matching "
            f"provider_matchup_key ({missing_keys!r}). The column is nullable "
            f"for pre-Sprint-6 and locally seeded rows; an unjoinable "
            f"championship matchup fails closed rather than being dropped.")

    if not team_ids:
        raise PostseasonSubjectError(
            REASON_EMPTY_UNIVERSE,
            f"league {league_id} week {week}: the championship field resolved "
            f"to zero teams. An empty universe is never published.")

    # DEFENSIVE, AND THE HOLE IT CLOSES IS SILENT. WP1A only assigns a round
    # ordinal to a week that HAS championship matchups, so an authoritative
    # state with an empty matchup set should be unreachable. But a frozen
    # MATCHUP universe of zero rows would read back as "unmanifested" and fall
    # through to the derived query — which is every matchup of the week,
    # consolation included. Refusing here is cheap; that fallback is not.
    if not matchup_ids:
        raise PostseasonSubjectError(
            REASON_EMPTY_UNIVERSE,
            f"league {league_id} week {week}: the championship round resolved "
            f"to zero matchups while reporting round "
            f"{state.championship_round_ordinal}. Refusing rather than freezing "
            f"an empty MATCHUP universe, which would read back as unmanifested.")

    return ResolvedUniverse(team_ids=tuple(sorted(set(team_ids))),
                            matchup_ids=tuple(sorted(set(matchup_ids))))


# ── Freeze and read ───────────────────────────────────────────────────────────

def frozen_subject_ids(db, *, league_id: int, season: int, week: int,
                       scope: str) -> tuple[int, ...] | None:
    """The frozen universe for one league-week-scope, or None if unmanifested.

    NONE MEANS "NO FREEZE APPLIES", NEVER "THE FIELD IS EMPTY". Callers fall
    back to the derived universe on None, which is the regular season and every
    historical pre-WP1B occurrence. An empty tuple is not returned: the freeze
    refuses to publish an empty universe, so the state cannot arise.
    """
    from db.schema import PoolWeekSubjectManifest

    rows = (db.query(PoolWeekSubjectManifest.subject_id)
            .filter(PoolWeekSubjectManifest.league_id == league_id,
                    PoolWeekSubjectManifest.season == season,
                    PoolWeekSubjectManifest.week == week,
                    PoolWeekSubjectManifest.scope == scope)
            .all())
    if not rows:
        return None
    return tuple(sorted(int(r[0]) for r in rows))


def freeze_universe(db, *, league_id: int, season: int, week: int,
                    universe: ResolvedUniverse, rotation_cycle: int | None = None,
                    now: datetime | None = None) -> dict[str, int]:
    """Persist the week's legal subject universe. Does NOT commit.

    Runs inside the caller's transaction so the manifest and the occurrences it
    describes land together — a published slate with no manifest, or a manifest
    with no slate, are both states a reader could act on wrongly.

    IDEMPOTENT, AND A CONTRADICTION IS A CONFLICT RATHER THAN AN UPDATE. Writing
    the same universe again is a no-op. Writing a DIFFERENT one raises: the
    whole purpose of the freeze is that the field cannot move after publication,
    so a second freeze proposing a different field is exactly the event this
    table exists to refuse. Mid-Season Maintainability (WP1B §4) turns on this
    single branch.
    """
    from db.schema import PoolWeekSubjectManifest

    now = now or datetime.now(timezone.utc)
    written = 0

    for scope, ids in ((SCOPE_TEAM, universe.team_ids),
                       (SCOPE_MATCHUP, universe.matchup_ids)):
        existing = frozen_subject_ids(db, league_id=league_id, season=season,
                                      week=week, scope=scope)
        if existing is not None:
            if existing != tuple(sorted(ids)):
                raise PostseasonSubjectError(
                    REASON_ALREADY_FROZEN,
                    f"league {league_id} season {season} week {week} scope "
                    f"{scope} is already frozen with subjects {list(existing)} "
                    f"and this freeze proposes {sorted(ids)}. A published "
                    f"occurrence's field never changes; refusing rather than "
                    f"rewriting what members already picked from.")
            continue
        for subject_id in sorted(ids):
            db.add(PoolWeekSubjectManifest(
                league_id=league_id, season=season, week=week, scope=scope,
                subject_id=int(subject_id), rotation_cycle=rotation_cycle,
                frozen_at=now))
            written += 1

    db.flush()
    return {"written": written,
            "teams": len(universe.team_ids),
            "matchups": len(universe.matchup_ids)}
