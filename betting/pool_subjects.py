"""
Provider-neutral input boundary — Scope Rev1.3 §C7.

THE EVALUATOR NEVER SEES A PROVIDER. Exactly two things cross this boundary and
nothing else (§C7): SUBJECTS, per POR §6.2 subject identity, and CANONICAL STAT
VALUES keyed by vocabulary name, with subject-level coverage. Endpoint shapes,
identifiers, response formats and authentication live on the far side.
Substituting a provider must not require an evaluator change, so nothing below
this line may name one.

WHY COVERAGE IS A SEPARATE SIGNAL FROM THE VALUES (§C7.3, load-bearing).
"Absence of coverage means unevaluable and is never inferred as zero." A
component-key check cannot carry that claim: a kicker's row legitimately has no
passing yards, so a missing key at the COMPONENT layer is structural, not a gap
in ingestion. Coverage is therefore asserted at the SUBJECT layer by the
adaptor, which is the only layer that knows whether a stat was actually
ingested. A subject is evaluable for a definition only when every one of its
`required_stats` has affirmative subject-level coverage.

    component-level structural omission        -> contributes 0.0, fine
    subject-level absence of coverage          -> UNEVALUABLE, never 0.0

THE CENSUS SOURCE IS INDEPENDENT OF THE STAT SOURCE, DELIBERATELY (§C9).
`WeeklyStructure` is read from the authoritative weekly league structure —
teams from the roster of record, matchups from the schedule — and NEVER from the
stat feed. A census derived from the stat feed shrinks to match the evaluated
count whenever data are missing, so the full-field gate would pass on a broken
week. The two counts must come from independent sources or the control is
non-discriminating. That is exactly what Scope §H scenario 28 tests.

WHAT THE LOCAL ADAPTOR CAN AND CANNOT SUPPLY TODAY. `LocalRecordedStatSource`
reads this repository's own recorded weekly tables — RosterSlot for that week's
starter assignments, Projection.actual_points for scored fantasy points, and
Matchup for team-level scores. That covers `player_fantasy_points`,
`matchup_home_score` and `matchup_away_score` and NOTHING ELSE, because no
per-player raw statistic table exists in this repository: `Projection` carries
points, not passing yards. Every raw-stat definition is therefore uncovered
here and its subjects report unevaluable — which is not a defect but the exact
state POR §13 records (provider access refused, 0 league-activation-ready). The
Yahoo gateway that would supply the rest is Sprint 6 and is out of S4-P1 scope;
inventing a local ingestion path would be inventing product behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol, Sequence

from betting.pool_catalog import StatVocabulary, load_vocabulary

SCOPE_TEAM = "TEAM"
SCOPE_MATCHUP = "MATCHUP"

# Slot names that do not occupy an ACTIVE STARTER slot. POR §1.3 excludes bench,
# IR, taxi "and all other non-starting rostered assets". Compared uppercased so
# a lowercase 'bn' in legacy data cannot slip through as a starter.
NON_STARTER_SLOTS = frozenset({"BN", "BE", "BENCH", "IR", "IL", "TAXI", "TX",
                               "NA", "RES"})

# Slots whose occupant's ACTUAL position is what counts — POR §1.3: "Flex and
# Superflex count by the actual player occupying the starting slot."
POSITION_FOLLOWS_PLAYER_SLOTS = frozenset({"FLEX", "SUPERFLEX", "SFLEX", "OP",
                                           "W/R/T", "WRT", "W/R", "Q/W/R/T"})


# ── The two things that cross the boundary ────────────────────────────────────

@dataclass(frozen=True)
class StatComponent:
    """One active starter's canonical stat row.

    `values` is keyed by CANONICAL vocabulary name only. Aliases are resolved on
    the far side of this boundary (§C7.2) — the evaluator never sees one.

    `slot` is the starting slot the player occupied THAT WEEK, and `position` is
    the player's actual position. Both are carried because POR §1.3 needs both:
    slot filters address slots, while Flex and Superflex resolve by occupant.
    """

    values: Mapping[str, float]
    slot: str | None = None
    position: str | None = None

    @property
    def effective_position(self) -> str | None:
        """The position this component counts as.

        For a Flex or Superflex slot that is the ACTUAL player's position, per
        POR §1.3. For every other slot the slot name already is the position,
        and using the player's position there would silently reclassify a
        player started out of position."""
        slot = (self.slot or "").upper()
        if slot in POSITION_FOLLOWS_PLAYER_SLOTS:
            return (self.position or slot) or None
        return slot or (self.position or None)


@dataclass(frozen=True)
class TeamFrame:
    """One team's contribution to a subject.

    A TEAM subject has exactly one frame. A MATCHUP subject has exactly two —
    which is what makes "a matchup is counted once as a matchup, not as two
    independent team subjects" (POR §6.2) structural rather than a convention a
    caller has to remember.

    `covered_stats` is the affirmative subject-level coverage signal of §C7.3
    for THIS team. `score` is the team's total from the league matchup record,
    used only by MATCHUP_SCORE_SUM; None where the record is absent.
    """

    team_id: int
    components: tuple[StatComponent, ...] = ()
    covered_stats: frozenset[str] = frozenset()
    score: float | None = None


@dataclass(frozen=True)
class Subject:
    """One selectable outcome unit — the thing a GM picks (POR §6.2).

    NOT the thing the metric reads from. A TEAM subject is one league team; a
    MATCHUP subject is one scheduled matchup.
    """

    subject_id: int
    subject_type: str
    frames: tuple[TeamFrame, ...]

    @property
    def components(self) -> tuple[StatComponent, ...]:
        """Every active starter across every participating team.

        For a MATCHUP this is both rosters concatenated, which is precisely what
        the grammar's `sum(both teams ...)` aggregates over."""
        out: list[StatComponent] = []
        for frame in self.frames:
            out.extend(frame.components)
        return tuple(out)

    @property
    def covered_stats(self) -> frozenset[str]:
        """Coverage for the subject as a whole.

        INTERSECTION, not union, across frames. POR §6.2: "A MATCHUP subject is
        evaluable only when both participants are evaluable. There is no partial
        matchup." A union would let one team's coverage vouch for the other's
        gap and settle a half-measured matchup."""
        if not self.frames:
            return frozenset()
        covered = self.frames[0].covered_stats
        for frame in self.frames[1:]:
            covered &= frame.covered_stats
        return covered

    def has_coverage_for(self, required_stats: Iterable[str]) -> bool:
        covered = self.covered_stats
        return all(stat in covered for stat in required_stats)


@dataclass(frozen=True)
class WeeklyStructure:
    """The authoritative weekly league structure — the census source.

    Read from the roster of record and the schedule, NEVER from the stat feed
    (§C9). `considered_subject_ids` is per-week and actual: a legitimately
    smaller field is a smaller `considered`, not an incomplete one.
    """

    scope: str
    considered_subject_ids: tuple[int, ...]


# ── Stat source protocol ──────────────────────────────────────────────────────

class PoolStatSource(Protocol):
    """What a provider adaptor must implement. Nothing more crosses the line."""

    def subjects_for(self, *, league_id: int, season: int, week: int,
                     structure: WeeklyStructure) -> tuple[Subject, ...]:
        ...


# ── Canonical normalization ───────────────────────────────────────────────────

def normalize_component(values: Mapping[str, float],
                        vocab: StatVocabulary | None = None,
                        ) -> tuple[dict[str, float], frozenset[str]]:
    """Resolve aliases and materialize governed derived stats for one component.

    Returns (canonical values, locally derivable stat names).

    DERIVED STATS ARE COMPUTED HERE, NOT IN THE EVALUATOR (§C7.2). `touches`,
    `opportunities`, `offensive_yards`, `scrimmage_yards`,
    `total_touchdown_credits` and `field_goals_made` all have governed formulas
    over other canonical operands. `field_goals_made` in particular sums FIVE
    bracket counters, which exceeds the closed grammar's three-operand limit —
    §C7.2 requires it be supplied as a single canonical operand, so it must be
    materialized before the boundary or it could never be evaluated at all.

    A derived stat is produced ONLY when every input is present. A partially
    present formula yields no key, so the subject reports no coverage for it and
    is unevaluable — never a plausible-looking partial sum.
    """
    vocab = vocab or load_vocabulary()
    canonical: dict[str, float] = {}
    for raw_key, raw_value in values.items():
        canonical[vocab.canonical_operand(raw_key)] = float(raw_value)

    # Repeat to a fixed point: a derived stat may feed another (scrimmage_yards
    # and offensive_yards both build on rushing_yards, and a future vocabulary
    # revision could chain further). Bounded by the vocabulary size, so it
    # terminates; no formula is self-referential.
    for _ in range(len(vocab.derived_formula)):
        progressed = False
        for name, formula in vocab.derived_formula.items():
            if not formula or name in canonical:
                continue
            inputs = [t.strip() for t in formula.split("+")]
            if all(i in canonical for i in inputs):
                canonical[name] = sum(canonical[i] for i in inputs)
                progressed = True
        if not progressed:
            break

    return canonical, frozenset(canonical)


def derivable_coverage(covered: Iterable[str],
                       vocab: StatVocabulary | None = None) -> frozenset[str]:
    """Expand a coverage set with every derived stat whose inputs are covered.

    Coverage of `rush_attempts` and `receptions` IS coverage of `touches` — the
    derived value is fully determined by inputs that were affirmatively
    ingested. Without this, every ratio definition over a derived operand would
    report unevaluable on complete data."""
    vocab = vocab or load_vocabulary()
    out = set(covered)
    for _ in range(len(vocab.derived_formula)):
        progressed = False
        for name, formula in vocab.derived_formula.items():
            if not formula or name in out:
                continue
            inputs = [t.strip() for t in formula.split("+")]
            if all(i in out for i in inputs):
                out.add(name)
                progressed = True
        if not progressed:
            break
    return frozenset(out)


# ── Slot filtering (POR §1.3) ─────────────────────────────────────────────────

def is_active_starter(component: StatComponent) -> bool:
    """POR §1.3 — count only players occupying ACTIVE STARTER slots.

    A NULL slot is treated as NON-starting. db/roster_read.py's fallback path
    can return static Roster rows whose slot is NULL for pre-migration data, and
    that path's own docstring warns callers to guard it. For Pool settlement the
    fail-closed reading is the right one: an unknown slot cannot be asserted to
    be a starter, and counting it would silently add bench production to a
    starters-only Pool."""
    slot = (component.slot or "").upper()
    if not slot:
        return False
    return slot not in NON_STARTER_SLOTS


def passes_slot_rules(component: StatComponent,
                      slot_filter: Sequence[str],
                      slot_exclusions: Sequence[str]) -> bool:
    """Apply a definition's `slot_filter` and `slot_exclusions` deterministically.

    Both the raw slot AND the effective position are tested, because the catalog
    uses the two interchangeably and correctness differs per definition:

      #42 lists FLEX and SUPERFLEX as SLOTS to include and DEF to exclude.
      #43 lists RB/WR/TE/FLEX to include and QB/K/DEF to exclude, and its
          governed_definition says Flex and Superflex "follow actual player
          position" — so a Flex occupied by a QB must be EXCLUDED even though
          its slot name is not in the exclusion list.

    Testing both fields satisfies each without a per-definition branch, which is
    what §4's "avoid bespoke if definition_key == ..." requires.

    EXCLUSIONS ARE APPLIED AFTER THE FILTER AND WIN. An entry appearing in both
    is excluded; that is the only reading under which the #43 rule above holds.
    """
    slot = (component.slot or "").upper()
    effective = (component.effective_position or "").upper()

    excl = {s.upper() for s in slot_exclusions}
    if slot in excl or effective in excl:
        return False

    if not slot_filter:
        return True
    keep = {s.upper() for s in slot_filter}
    return slot in keep or effective in keep


def filtered_components(subject: Subject, slot_filter: Sequence[str],
                        slot_exclusions: Sequence[str]) -> tuple[StatComponent, ...]:
    """Active starters of `subject` passing the definition's slot rules.

    The active-starter rule is applied FIRST and globally — POR §1.3 makes it
    unconditional, so a definition's slot_filter narrows the starters, it never
    re-admits a bench player."""
    return tuple(
        c for c in subject.components
        if is_active_starter(c) and passes_slot_rules(c, slot_filter,
                                                      slot_exclusions)
    )


# ── Adaptors ──────────────────────────────────────────────────────────────────

class StaticStatSource:
    """A recorded-fixture source. Subjects are supplied whole.

    §14 permits recorded fixtures during Sprint 4. This is the shape a fixture
    takes: it asserts nothing about where the numbers came from, which is
    exactly why a fixture built through it is as authoritative a test of the
    evaluator as production data would be."""

    def __init__(self, subjects: Sequence[Subject]) -> None:
        self._subjects = tuple(subjects)

    def subjects_for(self, *, league_id: int, season: int, week: int,
                     structure: WeeklyStructure) -> tuple[Subject, ...]:
        wanted = set(structure.considered_subject_ids)
        return tuple(s for s in self._subjects if s.subject_id in wanted)


def league_weekly_structure(db, *, league_id: int, week: int,
                            scope: str) -> WeeklyStructure:
    """Build the census source from the authoritative weekly league structure.

    TEAM subjects come from the league's team roster of record; MATCHUP subjects
    from that week's schedule. Neither query touches a stat table, which is the
    property Scope §H scenario 28 exists to prove.

    ── WP1B: A FROZEN POSTSEASON WEEK OVERRIDES THE DERIVED UNIVERSE ─────────

    When `pool_week_subject_manifest` carries rows for this league-week-scope,
    THOSE ids are the census — the derived queries below are not run at all.
    That is the whole of the postseason contraction: every consumer of this
    function (settlement's census, the GM's option list, and the claim
    validator) gets the contracted field without any of them changing.

    THE SIGNATURE IS UNCHANGED, AND THAT IS THE DESIGN. `pool_settlement.py` is
    certified economic code and calls this with exactly these three arguments.
    Keying the manifest by league-week-scope rather than by occurrence is what
    lets the frozen field reach settlement through the seam it already uses,
    instead of threading an occurrence id through a protected money path.

    ABSENT MANIFEST MEANS NO FREEZE APPLIES — never an empty field. The regular
    season is unmanifested by construction, and so is every occurrence drawn
    before WP1B; both keep the derived behaviour below, byte for byte.
    """
    from db.schema import League, Matchup, Team
    from betting.pool_postseason import frozen_subject_ids

    league = db.query(League).filter(League.id == league_id).first()
    if league is not None and scope in (SCOPE_TEAM, SCOPE_MATCHUP):
        frozen = frozen_subject_ids(db, league_id=league_id,
                                    season=league.season, week=week,
                                    scope=scope)
        if frozen is not None:
            return WeeklyStructure(scope=scope, considered_subject_ids=frozen)

    if scope == SCOPE_TEAM:
        ids = [t.id for t in db.query(Team)
               .filter(Team.league_id == league_id)
               .order_by(Team.id).all()]
    elif scope == SCOPE_MATCHUP:
        ids = [m.id for m in db.query(Matchup)
               .filter(Matchup.league_id == league_id, Matchup.week == week)
               .order_by(Matchup.id).all()]
    else:
        raise ValueError(
            f"scope {scope!r} has no subject rule. POR §6.2: PLAYER, POSITION "
            f"and LEAGUE are not current catalog scopes and inherit none; any "
            f"future definition introducing one requires its own subject ruling."
        )
    return WeeklyStructure(scope=scope, considered_subject_ids=tuple(ids))


class LocalRecordedStatSource:
    """Adaptor over this repository's recorded weekly tables.

    Supplies exactly three canonical operands, because exactly three have a
    local source of record:

        player_fantasy_points  <- Projection.actual_points for the week
        matchup_home_score     <- Matchup.home_score
        matchup_away_score     <- Matchup.away_score

    Every other canonical stat is UNCOVERED and its subjects report unevaluable.
    That is the honest state of this environment, not a stub: no per-player raw
    statistic table exists here, and fabricating one would be Sprint 6 gateway
    work performed early and without a source.

    HISTORICAL WEEKS READ THAT WEEK'S SLOTS (§C7.1). Starter construction goes
    through db.roster_read._roster_for_week, which prefers the immutable
    RosterSlot snapshot for the week and falls back to the static Roster only
    when the week has no snapshot. The current roster is not the week-N roster,
    and settling a completed week against today's lineup would score players who
    were not started.
    """

    #: Canonical stats this adaptor can affirm coverage for at the subject level.
    SUPPORTED_STATS = frozenset({"player_fantasy_points",
                                 "matchup_home_score", "matchup_away_score"})

    def __init__(self, *, source: str, season: int) -> None:
        self._source = source
        self._season = season

    def subjects_for(self, *, league_id: int, season: int, week: int,
                     structure: WeeklyStructure) -> tuple[Subject, ...]:
        from db.schema import Matchup

        if structure.scope == SCOPE_TEAM:
            return tuple(
                Subject(subject_id=team_id, subject_type=SCOPE_TEAM,
                        frames=(self._team_frame(team_id, week),))
                for team_id in structure.considered_subject_ids
            )

        subjects: list[Subject] = []
        for matchup_id in structure.considered_subject_ids:
            m = self._db.query(Matchup).filter(Matchup.id == matchup_id).first()
            if m is None:
                # The structure named a matchup the schedule no longer holds.
                # Emitting no subject makes it unevaluable, which is the
                # fail-closed reading; silently dropping it from `considered`
                # would be the census-shrinking defect §C9 forbids.
                continue
            home = self._team_frame(m.home_team_id, week, score=m.home_score)
            away = self._team_frame(m.away_team_id, week, score=m.away_score)
            subjects.append(Subject(subject_id=matchup_id,
                                    subject_type=SCOPE_MATCHUP,
                                    frames=(home, away)))
        return tuple(subjects)

    # `bind` keeps the Session out of __init__ so one adaptor instance is not
    # tied to a transaction it did not open.
    _db = None

    def bind(self, db) -> "LocalRecordedStatSource":
        self._db = db
        return self

    def _team_frame(self, team_id: int, week: int,
                    score: float | None = None) -> TeamFrame:
        from db.roster_read import _roster_for_week
        from db.schema import Projection

        rows = _roster_for_week(team_id, week, self._db)
        components: list[StatComponent] = []
        points_complete = True

        for row in rows:
            proj = (self._db.query(Projection)
                    .filter_by(player_id=row.player_id, week=week,
                               season=self._season, source=self._source)
                    .first())
            slot = getattr(row, "slot", None)
            position = getattr(getattr(row, "player", None), "position", None)
            component = StatComponent(values={}, slot=slot, position=position)
            if not is_active_starter(component):
                continue
            if proj is None or proj.actual_points is None:
                # A started player with no recorded result leaves the SUBJECT
                # uncovered. Not zero — POR §6.2: "Absence of a stat is not a
                # stat of zero."
                points_complete = False
                continue
            # PDS1 — normalized through the SAME governed helper the provider
            # boundary uses, so the two sources cannot drift. This adaptor
            # supplies one operand, and `player_fantasy_points` carries no
            # governed formula, so normalization materializes nothing extra
            # here — which is the point: the fix adds derived operands only
            # where their raw inputs were genuinely ingested, and never invents
            # coverage a source did not claim.
            _values, _ = normalize_component(
                {"player_fantasy_points": float(proj.actual_points)})
            components.append(StatComponent(
                values=_values, slot=slot, position=position))

        covered: set[str] = set()
        if points_complete and components:
            covered.add("player_fantasy_points")
        if score is not None:
            covered.update({"matchup_home_score", "matchup_away_score"})

        return TeamFrame(team_id=team_id, components=tuple(components),
                         covered_stats=frozenset(covered), score=score)