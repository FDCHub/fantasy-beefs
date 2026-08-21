"""providers/live_scoring.py — what a starter has ACTUALLY SCORED this week.

READ-ONLY, AND IT PERSISTS NOTHING. Nothing here writes a row, opens a cache or
holds a figure past the call that asked for it. That is a compliance property
and not an implementation convenience: `ops/yahoo_retention.py` inventories
every persisted field of provider origin and `test_c1_yahoo_retention.py` checks
that inventory against `db/schema.py`, so a new store of Yahoo player scoring
would be a retention question before it was a feature. There is no new table, no
new column and no new writer below this line.

── WHY THIS MODULE EXISTS (Rev 1.4 Lane C, Part 2) ──────────────────────────

The Matchup Preview could show a GM what its starters were PROJECTED to score
and nothing about what they HAD scored. A GM deciding whether to take a line on
Sunday afternoon was reading a Thursday forecast with no way to see that half of
it had already happened.

The data was not missing, and — as in Wave 4A — that is the whole point. Every
provider in this repository already publishes weekly fantasy points per player:
`ProviderPlayerStats.fantasy_points`, carried on the `ProviderWeek` aggregate
that `providers/week_stat_source.py` has settled Prop Pools from since WP2. What
was missing was a reader between that DTO and the preview. This is that reader.

── WHAT IT DELIBERATELY DOES NOT DO ────────────────────────────────────────

It does not SCORE. `fantasy_points` is the provider's own statement of what its
league settings produced — `providers/base.py` keeps it in a field separate from
`values` for exactly that reason — and re-deriving it from a raw stat line here
would give FantasyStakes a second opinion about a number the provider owns.

It does not FETCH. A snapshot is handed in, exactly as `matchup_preview` is
handed a board rather than computing one. `api.main._provider_week_snapshot` is
the ONE place in the product that branches on a provider name, and putting a
second such branch here would be a second composition boundary to keep in step.

It does not INVENT A ZERO. A player the feed never spoke about is absent from
`points_by_player_id` and reads back as None — never 0.0. This is the same
distinction `providers/week_stat_source.py` makes between a missing stat and a
measured zero, and it exists for the same reason: 0.0 is a claim that a player
played and scored nothing, which before kickoff is false about every starter on
both rosters.

It does not GUESS AN IDENTITY. Internal player ids are resolved through
`Player.provider_player_key` scoped to the snapshot's own provider — never by
name. S6-R1 forbids name matching and two real players share a name often
enough that the ban is a live defect guard, not a formality.

── DEMO AND PRODUCTION ARE THE SAME CODE OVER DIFFERENT FACTS ───────────────

Both providers produce `ProviderWeek`, so both are read by the functions below
with no branch anywhere in this file:

    yahoo   providers/yahoo/week_snapshot.fetch_week_snapshot(..., with_rosters=True)
            -> normalize_roster() -> ProviderPlayerStats.fantasy_points, which is
               Yahoo's own `player_points` for that player-week

    demo    providers/demo/scenario.week_snapshot(..., with_rosters=True)
            -> DemoScenario.player_points(), pure arithmetic on (league key,
               ordinal, index, week), no RNG and no clock

The Demo feed's determinism is inherited rather than re-established: two reads
of the same Demo league-week return equal `ProviderWeek` values, therefore equal
`ProviderLiveWeek` values, therefore equal figures on screen. WP2 §12 requires
that of the Demo provider and this module simply does not break it.

── THE PRE-GAME STATE IS A PROVIDER FACT, NOT AN ERROR ─────────────────────

`providers/demo/scenario.week_snapshot` publishes roster entries for any week
and player stats only for a FINAL one, because "lineups are set before kickoff
and numbers do not exist until the games are played" is what a real feed does.
An open week therefore reaches this module as a perfectly healthy snapshot whose
`player_stats` collection is empty, and it is reported as `REASON_NOT_REPORTED`
— a named state with no figures, which is different from a provider we could not
reach and very different from a provider that reported zeroes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Mapping, Optional

from providers.base import ProviderWeek

#: The provider answered and has published no player scoring for this week yet.
#: Before the week's first kickoff this is the CORRECT state for every starter
#: on both rosters, and the surface renders it as an em dash rather than as a 0.
REASON_NOT_REPORTED = "live_not_reported"

#: The provider could not be read at all — no credential, a transport failure,
#: a league with no provider binding. Distinguished from NOT_REPORTED for the
#: same reason `providers.base.Finality` keeps UNKNOWN apart from NOT_FINAL:
#: they mean the same thing to the surface and different things to an operator.
REASON_UNREADABLE = "live_provider_unreadable"

#: No live read was attempted for this call. The default state of a preview
#: built without one, and never a claim about the provider.
REASON_NOT_REQUESTED = "live_not_requested"


@dataclass(frozen=True)
class ProviderLiveWeek:
    """One league-week's reported fantasy points, keyed by PROVIDER player key.

    The provider-native half of the read, kept separate from the internal-id
    half below so it can be built and asserted with no Session at all. A demo
    determinism check is then a comparison of two of these, which is a claim
    about the FEED rather than about a database that happened to answer twice.
    """

    provider: str
    week: int
    observed_at: Optional[datetime]
    #: Only the players the feed actually measured. A key's absence is the
    #: whole signal; there is no zero standing in for it.
    points_by_player_key: Mapping[str, float] = field(default_factory=dict)

    @property
    def measured_any(self) -> bool:
        return bool(self.points_by_player_key)


@dataclass(frozen=True)
class LiveScores:
    """What the preview is entitled to say about current scoring.

    `available` answers "did we get the provider's statement about this week",
    NOT "are there figures". A healthy pre-game read is available with an empty
    map and `reason=REASON_NOT_REPORTED`, and the surface has to be able to tell
    that apart from a provider it could not reach — one is the product working
    and the other is an operational problem.
    """

    available: bool
    reason: Optional[str] = None
    provider: Optional[str] = None
    week: Optional[int] = None
    observed_at: Optional[datetime] = None
    points_by_player_id: Mapping[int, float] = field(default_factory=dict)

    def points_for(self, player_id: int) -> Optional[float]:
        """This starter's reported points, or None where the feed said nothing.

        NONE IS NOT ZERO and the caller must keep it that way to the pixel. A
        player who has not kicked off has no live figure; a player who took the
        field and did nothing has 0.0. Both are true statements and they are not
        the same statement.
        """
        value = self.points_by_player_id.get(player_id)
        return None if value is None else float(value)

    def measured(self, player_id: int) -> bool:
        """Whether the feed stated a figure for this player. Affirmative."""
        return player_id in self.points_by_player_id


def no_live_scores(*, reason: str = REASON_NOT_REQUESTED,
                   week: Optional[int] = None,
                   provider: Optional[str] = None) -> LiveScores:
    """The absent state, named.

    A CONSTRUCTOR RATHER THAN A NULL, so every caller that has no live figures
    still has to say WHY it has none. A None passed down the chain would arrive
    at the surface as "no live scoring" with the reason lost, and the surface
    would then have to choose a sentence for a situation nobody told it about.
    """
    return LiveScores(available=False, reason=reason, provider=provider,
                      week=week)


def live_week_from_snapshot(snapshot: ProviderWeek) -> ProviderLiveWeek:
    """Read one normalized week snapshot's reported fantasy points.

    A PURE FUNCTION OF THE DTO. No Session, no network, no clock — which is what
    lets a determinism assertion compare two of these directly.

    ONLY `fantasy_points` IS READ, and only where the provider set it. The raw
    `values` mapping is deliberately untouched: a scoring total assembled here
    out of passing yards and receptions would be FantasyStakes scoring a league
    whose settings it does not own, which is precisely the fabrication this lane
    is forbidden from committing.
    """
    points: dict[str, float] = {}
    for stats in snapshot.player_stats or ():
        if stats.fantasy_points is None:
            # The feed carried a stat record for this player and no scoring
            # total on it. Absent, not zero — see the module docstring.
            continue
        points[stats.player_key] = float(stats.fantasy_points)

    return ProviderLiveWeek(
        provider=snapshot.league.provider,
        week=snapshot.week,
        observed_at=snapshot.observed_at,
        points_by_player_key=points,
    )


def resolve_live_scores(db, live_week: ProviderLiveWeek, *,
                        player_ids: Iterable[int]) -> LiveScores:
    """Re-key one provider live week onto the internal player ids asked about.

    SCOPED TO THE SNAPSHOT'S OWN PROVIDER. The lookup filters on
    `Player.provider` as well as `Player.provider_player_key`, so a Demo
    league's figures can never be resolved onto a Yahoo league's players even
    if two provider namespaces ever collided on a key string. WP2 keeps the two
    providers' facts apart at composition; this keeps them apart at identity.

    NEVER BY NAME (S6-R1). A player whose row carries no provider key simply has
    no live figure — which is honest, and is exactly the state of the certification
    fixture's synthetic roster.

    ONLY THE PLAYERS THE CALLER NAMED. The preview asks about eighteen starters,
    so eighteen rows are read; nothing walks the league.
    """
    from db.schema import Player

    wanted = [int(pid) for pid in player_ids]
    if not wanted or not live_week.points_by_player_key:
        # A week the feed has not scored yet. AVAILABLE — the provider answered
        # — with no figures and the reason named.
        return LiveScores(available=True, reason=REASON_NOT_REPORTED,
                          provider=live_week.provider, week=live_week.week,
                          observed_at=live_week.observed_at)

    rows = (db.query(Player.id, Player.provider_player_key)
            .filter(Player.id.in_(wanted),
                    Player.provider == live_week.provider,
                    Player.provider_player_key.isnot(None))
            .all())

    points: dict[int, float] = {}
    for player_id, provider_key in rows:
        value = live_week.points_by_player_key.get(provider_key)
        if value is None:
            # A started player this feed never spoke about. Left OUT of the
            # map, so `points_for` answers None and the surface draws its
            # unresolved mark — the same withdrawal
            # `providers/week_stat_source.py` performs for coverage.
            continue
        points[player_id] = float(value)

    return LiveScores(
        available=True,
        reason=None if points else REASON_NOT_REPORTED,
        provider=live_week.provider,
        week=live_week.week,
        observed_at=live_week.observed_at,
        points_by_player_id=points,
    )


def live_scores_from_snapshot(db, snapshot: ProviderWeek, *,
                              player_ids: Iterable[int]) -> LiveScores:
    """The two steps above, for the ordinary caller that has a snapshot."""
    return resolve_live_scores(db, live_week_from_snapshot(snapshot),
                               player_ids=player_ids)
