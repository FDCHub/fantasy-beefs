"""Sprint 3 · CSPS — components + a league's rules -> that league's points.

ONE ENGINE, TWO KINDS OF INPUT, AND THE DIFFERENCE IS THE WHOLE DESIGN.

    FACTUAL      a stat line that HAPPENED. 195 rushing yards means the 150-yard
                 bonus was earned. 28 points allowed means the 28-34 band. Every
                 rule applies deterministically, and this is the mode that
                 reproduces Yahoo's own scoreboard exactly.

    PROJECTION   an EXPECTATION. 195 projected rushing yards does not mean the
                 150 bonus will be earned; it means the mean of a distribution
                 sits above the threshold, and the bonus is worth its
                 PROBABILITY times its value. That probability is not a scoring
                 rule — it is an uncertainty model.

CSPS DOES NOT OWN THE UNCERTAINTY MODEL, AND THIS SPRINT DOES NOT INVENT ONE.
This repository contains no approved specification for converting a mean into an
expected threshold bonus or an expected points-allowed band: there is no CSPS or
IPRM spec document, and the Phase 0 diligence explicitly lists the 150-yard tier,
reception counts and the 18-21 points-allowed bucket as items "that need
modelling FOR PRICING". Pricing is IPRM's job.

So in PROJECTION mode every probability-dependent rule is reported as
MODEL_REQUIRED, contributes nothing, and makes the result PARTIAL. The
alternatives were both worse than useless: awarding a mean-crossed bonus in full
would over-price every player near a threshold, and silently omitting it would
under-price them while looking complete.

── WHAT THIS MODULE MUST NEVER DO ──────────────────────────────────────────

IT MUST NEVER READ OR WRITE `projections.projected_points`. That column holds a
scalar that has ALREADY been through a league's scoring rules, and putting it in
here would score it a second time. `score_components` takes components and a
profile and nothing else; `score_snapshot` reads the Sprint 2B component seam.
The double-scoring guard is executable, in the Sprint 3 suite, not a comment.

IT MUST NEVER CONSULT THE PROVIDER'S OWN POINT TOTAL. BALLDONTLIE publishes
`fantasy_points` under its own default format. That number is provider
commentary; Sprint 2B carries it and CSPS does not read it.

── PRECISION ───────────────────────────────────────────────────────────────

Components are never rounded before scoring — a projection of 268.4 passing
yards is scored as 268.4. The full-precision float is the result; `points_display`
rounds to two decimals at the boundary and nowhere else, because Yahoo displays
two decimals and every historical figure this engine is certified against is a
two-decimal number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from scoring.profile import ScoringProfile, load_profile

__all__ = [
    "CSPS_VERSION",
    "Contribution",
    "CspsResult",
    "FACTUAL",
    "PROJECTION",
    "Quality",
    "ResultStatus",
    "score_components",
    "score_snapshot",
    "score_week",
]

#: The frozen implementation version. It travels with every result, so a stored
#: or logged figure can always be traced to the code that produced it. Bump it
#: when a scoring OUTCOME could change; not when a comment does.
CSPS_VERSION = "csps-v1"

FACTUAL = "FACTUAL"
PROJECTION = "PROJECTION"

#: Components the provider's PROJECTION BLOCK omits for EVERY subject — a gap in
#: the vocabulary rather than a statement about one player.
#:
#: THE DISTINCTION THIS SET DRAWS IS THE WHOLE OF PROJECTION ABSENCE SEMANTICS.
#: A wide receiver's row carries no `passing_yards` because he is not projected
#: to throw: absent means zero, and scoring it as zero is correct. A wide
#: receiver's row carries no `receptions` because BALLDONTLIE projects nobody's
#: receptions — Phase 0 measured that the block publishes `targets` instead —
#: and scoring THAT as zero would zero out the largest input a PPR league has,
#: for every pass-catcher alive.
#:
#: Membership is therefore a measured fact about the provider, not a convenience.
#: One field qualifies today.
SYSTEMATIC_PROJECTION_GAPS = frozenset({"receptions"})


class Quality:
    """What kind of thing one category's contribution is."""

    #: Scored from a component the source actually carried.
    DIRECT = "DIRECT"
    #: Scored from other components by an approved, deterministic derivation.
    DERIVED = "DERIVED"
    #: The league scores it, and turning the available input into an expected
    #: contribution needs an uncertainty model CSPS does not own.
    MODEL_REQUIRED = "MODEL_REQUIRED"
    #: The league scores it and the input is simply not there.
    UNAVAILABLE = "UNAVAILABLE"
    #: The league does not score it. Reported rather than skipped, so "not
    #: scored here" never looks like "we could not find it".
    NOT_ENABLED = "NOT_ENABLED"
    #: The league scores it and the rule's VALUE is not established by evidence.
    UNRESOLVED_RULE = "UNRESOLVED_RULE"


class ResultStatus:
    """How much of a scored result can be relied on."""

    COMPLETE_DIRECT = "COMPLETE_DIRECT"
    COMPLETE_WITH_MODELLED_COMPONENTS = "COMPLETE_WITH_MODELLED_COMPONENTS"
    PARTIAL = "PARTIAL"
    REFUSED = "REFUSED"


@dataclass(frozen=True)
class Contribution:
    """One category's arithmetic, kept so the total can be explained.

    The four fields answer "why is this 22.74?" without re-running anything:
    what the component was, what rule applied, what it contributed, and how much
    that contribution can be trusted.
    """

    category: str
    component: float | None
    rule: str
    contribution: float
    quality: str
    note: str = ""

    def as_dict(self) -> dict:
        return {"category": self.category, "component": self.component,
                "rule": self.rule, "contribution": self.contribution,
                "quality": self.quality, "note": self.note}


@dataclass
class CspsResult:
    """A league-specific projection, and everything needed to audit it."""

    profile_id: str
    profile_version: str
    csps_version: str = CSPS_VERSION
    mode: str = PROJECTION
    points: float = 0.0
    status: str = ResultStatus.REFUSED
    contributions: list = field(default_factory=list)
    model_required: list = field(default_factory=list)
    unavailable: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    # ── provenance, carried from the component snapshot ──────────────────────
    player_id: int | None = None
    provider: str | None = None
    provider_player_key: str | None = None
    season: int | None = None
    week: int | None = None
    component_snapshot_id: int | None = None
    component_vocabulary_version: str | None = None
    observed_at: datetime | None = None
    calculated_at: datetime | None = None
    refusal: str = ""

    @property
    def points_display(self) -> float:
        """Two decimals, applied ONCE, at the boundary. Never fed back in."""
        return round(self.points + 0.0, 2)

    @property
    def complete(self) -> bool:
        return self.status in (ResultStatus.COMPLETE_DIRECT,
                               ResultStatus.COMPLETE_WITH_MODELLED_COMPONENTS)

    def contribution(self, category: str) -> Contribution | None:
        for item in self.contributions:
            if item.category == category:
                return item
        return None

    def as_dict(self) -> dict:
        return {
            "player_id": self.player_id, "provider": self.provider,
            "provider_player_key": self.provider_player_key,
            "season": self.season, "week": self.week,
            "component_snapshot_id": self.component_snapshot_id,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "csps_version": self.csps_version, "mode": self.mode,
            "points": self.points, "points_display": self.points_display,
            "status": self.status,
            "contributions": [c.as_dict() for c in self.contributions],
            "model_required": list(self.model_required),
            "unavailable": list(self.unavailable),
            "unresolved": list(self.unresolved),
            "warnings": list(self.warnings),
            "calculated_at": (self.calculated_at.isoformat()
                              if self.calculated_at else None),
            "refusal": self.refusal,
        }


# ── the scorer ───────────────────────────────────────────────────────────────

class _Sheet:
    """Accumulates contributions and keeps the bookkeeping in one place."""

    def __init__(self, components: Mapping[str, float], present: Iterable[str],
                 profile: ScoringProfile, mode: str, derived: Iterable[str]):
        self.components = components
        self.present = set(present) if present is not None else set(components)
        self.profile = profile
        self.mode = mode
        self.derived = set(derived or ())
        self.items: list[Contribution] = []
        self.total = 0.0

    def value(self, key: str):
        """(value, is_present). ABSENCE MEANS DIFFERENT THINGS PER MODE.

        On a FACTUAL line an omitted component is a zero — BALLDONTLIE omits
        every zero-valued field, and 25 of 34 week-1 kickers carried no
        `field_goals_missed` key precisely because they missed none (Phase 0F-1).

        On a PROJECTION it depends on WHY it is absent, and
        `SYSTEMATIC_PROJECTION_GAPS` is the list of fields the provider omits
        for everybody. `receptions` is on it — treating that as zero would
        silently zero-out every PPR league's largest input (Sprint 2B rule
        0F-20). Everything else absent means the subject is not projected to do
        it, which really is zero: a receiver throws for nothing.
        """
        raw = self.components.get(key)
        if raw is None:
            if self.mode == FACTUAL:
                return 0.0, True
            if key in SYSTEMATIC_PROJECTION_GAPS:
                return None, False
            # Not projected to occur. A receiver with no passing line is
            # projected to throw for nothing, and that IS zero.
            return 0.0, True
        return float(raw), True

    def add(self, category: str, component, rule: str, contribution: float,
            quality: str, note: str = "") -> None:
        self.items.append(Contribution(category=category, component=component,
                                       rule=rule, contribution=contribution,
                                       quality=quality, note=note))
        self.total += contribution

    def rate(self, category: str, key: str, per_unit: float,
             rule: str | None = None) -> None:
        """A simple per-unit rule: value x rate."""
        if not per_unit:
            self.add(category, None, "not scored by this league", 0.0,
                     Quality.NOT_ENABLED)
            return
        value, present = self.value(key)
        rule = rule or f"{per_unit:g} per unit of {key}"
        if not present:
            self.add(category, None, rule, 0.0, Quality.UNAVAILABLE,
                     f"{key} was not forecast, and this league scores it")
            return
        quality = Quality.DERIVED if key in self.derived else Quality.DIRECT
        self.add(category, value, rule, value * per_unit, quality)

    def tiers(self, category: str, key: str, tiers: Sequence) -> None:
        """Yardage threshold bonuses. THE MODE DECIDES WHETHER THEY APPLY.

        FACTUAL: cumulative, deterministic — 195 rushing yards earns both the
        100 and the 150 tier, which is exactly what Bijan Robinson's +2.00 was.

        PROJECTION: refused as MODEL_REQUIRED. A mean above a threshold is not a
        threshold crossed, and the expected value of the bonus is
        P(yards >= threshold) x points — a probability this engine has no
        approved way to compute and no business inventing.
        """
        if not tiers:
            self.add(category, None, "not scored by this league", 0.0,
                     Quality.NOT_ENABLED)
            return
        value, present = self.value(key)
        ladder = ", ".join(f"{t.points:g} at {t.threshold:g}" for t in tiers)

        if self.mode == PROJECTION:
            self.add(category, value, f"cumulative tiers ({ladder})", 0.0,
                     Quality.MODEL_REQUIRED,
                     "a projected mean above a threshold is not a threshold "
                     "crossed; the expected bonus is P(cross) x points, which "
                     "belongs to IPRM")
            return

        if not present:
            self.add(category, None, f"cumulative tiers ({ladder})", 0.0,
                     Quality.UNAVAILABLE)
            return

        earned = [t for t in tiers if value >= t.threshold]
        blocked = [t for t in earned if t.unresolved]
        if blocked:
            self.add(category, value, f"cumulative tiers ({ladder})", 0.0,
                     Quality.UNRESOLVED_RULE,
                     f"{value:g} crosses tier(s) at "
                     f"{', '.join(f'{t.threshold:g}' for t in blocked)} whose "
                     f"point value is not established by any evidence in this "
                     f"repository. Refusing to guess.")
            return
        points = sum(t.points for t in earned)
        self.add(category, value, f"cumulative tiers ({ladder})", points,
                 Quality.DIRECT,
                 f"crossed {len(earned)} tier(s)" if earned else "no tier crossed")

    def bands(self, category: str, key: str, bands: Sequence,
              label: str) -> None:
        """A continuous stat scored by discrete band. SAME SPLIT AS TIERS.

        FACTUAL: 28 points allowed is the 28-34 band, worth -1.00, and that is
        how the Titans reconciled to 6.00.

        PROJECTION: a projected 21.3 points allowed is a distribution whose mass
        sits across several bands, and its expected contribution is the sum of
        P(band) x points. BALLDONTLIE even publishes band probabilities — but
        its bands (14-17, 18-21, 22-27) STRADDLE Yahoo's (14-20, 21-27), so they
        must be re-split before they mean anything. That re-split is a model.
        """
        if not bands:
            self.add(category, None, "not scored by this league", 0.0,
                     Quality.NOT_ENABLED)
            return
        value, present = self.value(key)
        ladder = ", ".join(f"[{b.low:g}-{b.high:g}]={b.points:g}" for b in bands)

        if self.mode == PROJECTION:
            self.add(category, value, f"{label} bands ({ladder})", 0.0,
                     Quality.MODEL_REQUIRED,
                     "a mean lands in one band; a distribution lands across "
                     "several. The expected contribution is sum(P(band) x "
                     "points), and the provider's own bands straddle Yahoo's, "
                     "so re-splitting them is IPRM's work")
            return

        if not present:
            self.add(category, None, f"{label} bands ({ladder})", 0.0,
                     Quality.UNAVAILABLE)
            return

        for band in bands:
            if band.contains(value):
                self.add(category, value, f"{label} bands ({ladder})",
                         band.points, Quality.DIRECT,
                         f"{value:g} falls in [{band.low:g}-{band.high:g}]")
                return
        self.add(category, value, f"{label} bands ({ladder})", 0.0,
                 Quality.UNAVAILABLE,
                 f"{value:g} falls outside every configured band")


#: Components only a team defence can have. Used to recognise one when the
#: caller did not say — a snapshot always carries a position, but the pure
#: evaluator is callable without one and must not guess wrong in either
#: direction.
_DST_COMPONENTS = frozenset({
    "defensive_sacks", "defensive_interceptions", "opponent_fumble_recoveries",
    "defensive_safeties", "kicks_blocked", "interception_return_touchdowns",
    "fumble_return_touchdowns", "turnover_return_touchdowns",
    "blocked_kick_return_touchdowns", "two_point_returns",
    "dst_points_allowed", "dst_yards_allowed", "dst_three_and_outs",
})

_DEFENSE_POSITIONS = frozenset({"DEF", "DST", "D/ST", "D"})


def _is_defense(position: str | None, components: Mapping[str, float]) -> bool:
    if position:
        return position.strip().upper() in _DEFENSE_POSITIONS
    return any(key in components for key in _DST_COMPONENTS)


def score_components(components: Mapping[str, float], profile: ScoringProfile,
                     *, mode: str = PROJECTION,
                     components_present: Iterable[str] | None = None,
                     derived_components: Iterable[str] = (),
                     position: str | None = None) -> CspsResult:
    """The pure evaluator. Components in, one league's points out.

    NO DATABASE, NO NETWORK, NO PROVIDER. It takes a mapping of normalized
    component names to numbers and a profile, which is what makes it
    provider-neutral: BALLDONTLIE supplies the components today, and a second
    provider supplying the same names would score identically without this file
    changing.
    """
    sheet = _Sheet(components, components_present, profile, mode,
                   derived_components)
    p = profile
    defense = _is_defense(position, components)

    # THE SCOPE IS SYMMETRIC. A defence does not throw interceptions and a
    # quarterback does not allow points, so each side's categories are marked
    # NOT_ENABLED for the other rather than evaluated. Without this a projected
    # Mr Whiskers defence reported `pick_six_thrown` as MODEL_REQUIRED — which
    # is not a gap in the projection, it is a category that cannot apply — and
    # the noise would sit in `model_required` where an operator reads it as
    # missing input.
    if defense:
        for category in ("passing_yards", "passing_touchdowns",
                         "passing_interceptions", "pick_six_thrown",
                         "passing_yard_bonus", "rushing_yards",
                         "rushing_touchdowns", "rushing_yard_bonus",
                         "receptions", "receiving_yards",
                         "receiving_touchdowns", "receiving_yard_bonus",
                         "two_point_conversions", "fumbles_lost",
                         "offensive_fumble_recovery_touchdowns",
                         "return_touchdowns", "field_goal_yards",
                         "field_goals_made", "field_goals_missed",
                         "extra_points_made", "extra_points_missed"):
            sheet.add(category, None, "not applicable to this position", 0.0,
                      Quality.NOT_ENABLED)
        return _score_defense(sheet, p, profile, mode, position)

    # ── offence ──────────────────────────────────────────────────────────────
    sheet.rate("passing_yards", "passing_yards", p.passing_yards_per_point,
               f"{p.passing_yards_per_point:g} per passing yard")
    sheet.rate("passing_touchdowns", "passing_touchdowns", p.passing_touchdown,
               f"{p.passing_touchdown:g} per passing touchdown")
    sheet.rate("passing_interceptions", "passing_interceptions",
               p.passing_interception,
               f"{p.passing_interception:g} per interception thrown")
    _pick_six(sheet, p)
    sheet.tiers("passing_yard_bonus", "passing_yards", p.passing_tiers)

    sheet.rate("rushing_yards", "rushing_yards", p.rushing_yards_per_point,
               f"{p.rushing_yards_per_point:g} per rushing yard")
    sheet.rate("rushing_touchdowns", "rushing_touchdowns", p.rushing_touchdown,
               f"{p.rushing_touchdown:g} per rushing touchdown")
    sheet.tiers("rushing_yard_bonus", "rushing_yards", p.rushing_tiers)

    _receptions(sheet, p)
    sheet.rate("receiving_yards", "receiving_yards", p.receiving_yards_per_point,
               f"{p.receiving_yards_per_point:g} per receiving yard")
    sheet.rate("receiving_touchdowns", "receiving_touchdowns",
               p.receiving_touchdown,
               f"{p.receiving_touchdown:g} per receiving touchdown")
    sheet.tiers("receiving_yard_bonus", "receiving_yards", p.receiving_tiers)

    _two_point(sheet, p)
    sheet.rate("fumbles_lost", "fumbles_lost", p.fumble_lost,
               f"{p.fumble_lost:g} per fumble lost")
    sheet.rate("offensive_fumble_recovery_touchdowns",
               "offensive_fumble_recovery_touchdowns",
               p.offensive_fumble_recovery_touchdown,
               f"{p.offensive_fumble_recovery_touchdown:g} each")
    _return_touchdowns(sheet, p)

    # ── kicker ───────────────────────────────────────────────────────────────
    if p.field_goal_yards_per_point:
        sheet.rate("field_goal_yards", "field_goals_made_yards",
                   p.field_goal_yards_per_point,
                   f"{p.field_goal_yards_per_point:g} per YARD of made field "
                   f"goals (total yardage rule)")
    else:
        sheet.add("field_goal_yards", None, "not scored by this league", 0.0,
                  Quality.NOT_ENABLED)
    _bucketed(sheet, p.field_goals_made, "field_goals_made")
    _bucketed(sheet, p.field_goals_missed, "field_goals_missed")
    sheet.rate("extra_points_made", "extra_points_made", p.extra_point_made,
               f"{p.extra_point_made:g} per extra point made")
    sheet.rate("extra_points_missed", "extra_points_missed",
               p.extra_point_missed,
               f"{p.extra_point_missed:g} per extra point missed")

    # ── defence / special teams ──────────────────────────────────────────────
    #
    # NOT SCORED FOR A NON-DEFENCE, and the reason is not tidiness. Under the
    # zero-omission rule an absent component on a factual line reads as a zero —
    # so a quarterback, who has no `dst_points_allowed` key because the concept
    # does not apply to him, would read as having allowed ZERO points and be
    # paid the shutout band. Every non-defence subject in both leagues came out
    # exactly 10.00 points high before this scope existed.
    for category in ("dst_sacks", "dst_interceptions", "dst_fumble_recoveries",
                     "dst_touchdowns", "dst_safeties", "dst_blocked_kicks",
                     "dst_return_touchdowns", "dst_two_point_returns",
                     "dst_three_and_outs", "dst_points_allowed",
                     "dst_yards_allowed"):
        sheet.add(category, None, "not applicable to this position", 0.0,
                  Quality.NOT_ENABLED)
    return _finish(sheet, profile, mode, position)


def _score_defense(sheet: "_Sheet", p: ScoringProfile, profile: ScoringProfile,
                   mode: str, position: str | None) -> CspsResult:
    """The team-defence half of the sheet."""
    sheet.rate("dst_sacks", "defensive_sacks", p.dst_sack,
               f"{p.dst_sack:g} per sack")
    sheet.rate("dst_interceptions", "defensive_interceptions",
               p.dst_interception, f"{p.dst_interception:g} per interception")
    sheet.rate("dst_fumble_recoveries", "opponent_fumble_recoveries",
               p.dst_fumble_recovery,
               f"{p.dst_fumble_recovery:g} per fumble recovery")
    _dst_touchdowns(sheet, p)
    sheet.rate("dst_safeties", "defensive_safeties", p.dst_safety,
               f"{p.dst_safety:g} per safety")
    sheet.rate("dst_blocked_kicks", "kicks_blocked", p.dst_blocked_kick,
               f"{p.dst_blocked_kick:g} per blocked kick")
    _dst_return_touchdowns(sheet, p)
    sheet.rate("dst_two_point_returns", "two_point_returns",
               p.dst_two_point_return,
               f"{p.dst_two_point_return:g} per extra point returned")
    _three_and_outs(sheet, p)
    sheet.bands("dst_points_allowed", "dst_points_allowed",
                p.points_allowed_bands, "points allowed")
    sheet.bands("dst_yards_allowed", "dst_yards_allowed",
                p.yards_allowed_bands, "yards allowed")

    return _finish(sheet, profile, mode, position)


def _pick_six(sheet: _Sheet, p: ScoringProfile) -> None:
    """The second penalty on an interception returned for a touchdown.

    FACTUAL: a real component, derived from play participants by WP2 and
    validated exactly on Matthew Stafford (12.76 plain, 10.76 with the penalty).

    PROJECTION: BALLDONTLIE does not project it, and it must NOT be inferred
    from projected interceptions by an assumed rate — a pick-six rate is a model
    parameter, and no approved one exists here. MODEL_REQUIRED.
    """
    if not p.pick_six_thrown:
        sheet.add("pick_six_thrown", None, "not scored by this league", 0.0,
                  Quality.NOT_ENABLED)
        return
    rule = f"{p.pick_six_thrown:g} per interception returned for a touchdown"
    value, present = sheet.value("pick_six_thrown")
    if sheet.mode == PROJECTION:
        sheet.add("pick_six_thrown", value if present else None, rule, 0.0,
                  Quality.MODEL_REQUIRED,
                  "not projected by the provider, and inferring it from "
                  "projected interceptions needs a rate this repository has "
                  "not approved")
        return
    if not present:
        sheet.add("pick_six_thrown", None, rule, 0.0, Quality.UNAVAILABLE)
        return
    quality = (Quality.DERIVED if "pick_six_thrown" in sheet.derived
               else Quality.DIRECT)
    sheet.add("pick_six_thrown", value, rule, value * p.pick_six_thrown,
              quality, "charged to the passer participant, never to the team")


def _receptions(sheet: _Sheet, p: ScoringProfile) -> None:
    """Receptions — the category a projection never carries.

    The projection block publishes `targets` and no reception count at all, so a
    PPR league's largest single input has to be modelled from targets and a
    catch rate. That model is not here, and a zero would be a confident lie.
    """
    if not p.reception:
        sheet.add("receptions", None, "not scored by this league", 0.0,
                  Quality.NOT_ENABLED)
        return
    rule = f"{p.reception:g} per reception"
    value, present = sheet.value("receptions")
    if present:
        quality = (Quality.DERIVED if "receptions" in sheet.derived
                   else Quality.DIRECT)
        sheet.add("receptions", value, rule, value * p.reception, quality)
        return
    targets = sheet.components.get("targets")
    if targets is not None:
        sheet.add("receptions", None, rule, 0.0, Quality.MODEL_REQUIRED,
                  f"not forecast; {targets:g} targets ARE forecast, and a "
                  f"reception projection is targets x catch rate — a model "
                  f"IPRM owns")
        return
    # NEITHER RECEPTIONS NOR TARGETS. This subject is not projected to catch
    # passes at all — a quarterback, a kicker, a defence — which is a real zero
    # rather than a gap. The gap case is the one above: targets ARE projected
    # and the reception count that should accompany them is not.
    sheet.add("receptions", 0.0, rule, 0.0, Quality.DIRECT,
              "not projected to receive; no targets are forecast either")


def _two_point(sheet: _Sheet, p: ScoringProfile) -> None:
    """Two-point conversions, summed across the three structured fields."""
    if not p.two_point_conversion:
        sheet.add("two_point_conversions", None, "not scored by this league",
                  0.0, Quality.NOT_ENABLED)
        return
    keys = ("passing_two_point_conversions", "rushing_two_point_conversions",
            "receiving_two_point_conversions")
    _summed(sheet, "two_point_conversions", keys, p.two_point_conversion,
            f"{p.two_point_conversion:g} per two-point conversion")


def _return_touchdowns(sheet: _Sheet, p: ScoringProfile) -> None:
    if not p.return_touchdown:
        sheet.add("return_touchdowns", None, "not scored by this league", 0.0,
                  Quality.NOT_ENABLED)
        return
    _summed(sheet, "return_touchdowns",
            ("kick_return_touchdowns", "punt_return_touchdowns"),
            p.return_touchdown, f"{p.return_touchdown:g} per return touchdown")


def _dst_touchdowns(sheet: _Sheet, p: ScoringProfile) -> None:
    """Defensive touchdowns, from the two split fields.

    `turnover_return_touchdowns` is the provider's PRE-SUMMED total and is
    deliberately not read: adding it to its own two components would pay a
    defence twice for one score.
    """
    if not p.dst_touchdown:
        sheet.add("dst_touchdowns", None, "not scored by this league", 0.0,
                  Quality.NOT_ENABLED)
        return
    _summed(sheet, "dst_touchdowns",
            ("interception_return_touchdowns", "fumble_return_touchdowns"),
            p.dst_touchdown, f"{p.dst_touchdown:g} per defensive touchdown",
            note="from the two split fields; turnover_return_touchdowns is the "
                 "provider's pre-summed total and is never added on top")


def _dst_return_touchdowns(sheet: _Sheet, p: ScoringProfile) -> None:
    if not p.dst_return_touchdown:
        sheet.add("dst_return_touchdowns", None, "not scored by this league",
                  0.0, Quality.NOT_ENABLED)
        return
    _summed(sheet, "dst_return_touchdowns",
            ("kick_return_touchdowns", "punt_return_touchdowns",
             "blocked_kick_return_touchdowns"),
            p.dst_return_touchdown,
            f"{p.dst_return_touchdown:g} per special-teams return touchdown")


def _three_and_outs(sheet: _Sheet, p: ScoringProfile) -> None:
    """The category BALLDONTLIE does not publish in any form.

    FACTUAL: WP2 derives a count from play-by-play down sequencing, and it
    arrives here as a DERIVED component whose threshold rule is fitted rather
    than validated — so a result carrying one is COMPLETE_WITH_MODELLED_
    COMPONENTS, never COMPLETE_DIRECT.

    PROJECTION: there is nothing to project from. It is MODEL_REQUIRED and the
    result is PARTIAL — which is the point, because Mr Whiskers pays for these
    and a silent zero would under-project every defence in the league.
    """
    if not p.dst_three_and_out:
        sheet.add("dst_three_and_outs", None, "not scored by this league", 0.0,
                  Quality.NOT_ENABLED)
        return
    rule = f"{p.dst_three_and_out:g} per three-and-out forced"
    value, present = sheet.value("dst_three_and_outs")
    if sheet.mode == PROJECTION:
        sheet.add("dst_three_and_outs", None, rule, 0.0, Quality.MODEL_REQUIRED,
                  "the provider publishes no three-and-out statistic and no "
                  "projection of one; this league pays for them, so the "
                  "result is PARTIAL rather than quietly short")
        return
    if not present:
        sheet.add("dst_three_and_outs", None, rule, 0.0, Quality.UNAVAILABLE,
                  "this league scores three-and-outs and none were supplied")
        return
    sheet.add("dst_three_and_outs", value, rule, value * p.dst_three_and_out,
              Quality.DERIVED,
              "derived from play-by-play; the threshold rule is fitted to one "
              "observation and is reported UNVERIFIED upstream")


def _summed(sheet: _Sheet, category: str, keys: Sequence[str], per_unit: float,
            rule: str, note: str = "") -> None:
    """Sum several components under one rule, tracking presence honestly."""
    total = 0.0
    seen = False
    for key in keys:
        value, present = sheet.value(key)
        if present:
            seen = True
            total += value
    if not seen:
        sheet.add(category, None, rule, 0.0, Quality.UNAVAILABLE,
                  f"none of {list(keys)} were forecast")
        return
    quality = (Quality.DERIVED if any(k in sheet.derived for k in keys)
               else Quality.DIRECT)
    sheet.add(category, total, rule, total * per_unit, quality, note)


def _bucketed(sheet: _Sheet, buckets: Mapping[str, float], label: str) -> None:
    """Distance-banded field goals — one contribution per configured bucket."""
    if not buckets:
        sheet.add(label, None, "not scored by this league", 0.0,
                  Quality.NOT_ENABLED)
        return
    for key, points in sorted(buckets.items()):
        value, present = sheet.value(key)
        rule = f"{points:g} per {key}"
        if not present:
            sheet.add(key, None, rule, 0.0, Quality.UNAVAILABLE,
                      "this league scores this distance band and the provider "
                      "did not forecast it")
            continue
        sheet.add(key, value, rule, value * points, Quality.DIRECT)


def _finish(sheet: _Sheet, profile: ScoringProfile, mode: str,
            position: str | None) -> CspsResult:
    model_required = [c.category for c in sheet.items
                      if c.quality == Quality.MODEL_REQUIRED]
    unavailable = [c.category for c in sheet.items
                   if c.quality == Quality.UNAVAILABLE]
    unresolved = [c.category for c in sheet.items
                  if c.quality == Quality.UNRESOLVED_RULE]
    derived = [c.category for c in sheet.items if c.quality == Quality.DERIVED]

    if unresolved:
        status = ResultStatus.REFUSED
    elif model_required or unavailable:
        status = ResultStatus.PARTIAL
    elif derived:
        status = ResultStatus.COMPLETE_WITH_MODELLED_COMPONENTS
    else:
        status = ResultStatus.COMPLETE_DIRECT

    warnings = []
    if status == ResultStatus.PARTIAL:
        warnings.append(
            f"{len(model_required)} categor(ies) need an uncertainty model and "
            f"{len(unavailable)} have no input; this projection is a FLOOR "
            f"under this league's rules, not a complete one")
    if profile.unresolved_rules:
        warnings.append(
            f"profile {profile.profile_id} carries unresolved rule value(s): "
            f"{list(profile.unresolved_rules)}")

    result = CspsResult(
        profile_id=profile.profile_id, profile_version=profile.version,
        mode=mode, points=sheet.total, status=status,
        contributions=sheet.items, model_required=model_required,
        unavailable=unavailable, unresolved=unresolved, warnings=warnings,
        calculated_at=datetime.now(timezone.utc))
    if unresolved:
        result.refusal = (
            f"refusing to score: {unresolved} depend on a rule value this "
            f"repository has no evidence for. Guessing it would be an invented "
            f"scoring rule; omitting it would silently under-score.")
        result.points = 0.0
    return result


# ── the Sprint 2B seam ───────────────────────────────────────────────────────

def score_snapshot(db, *, provider: str, player_id: int, season: int, week: int,
                   profile: ScoringProfile | str, as_of: datetime | None = None,
                   mode: str = PROJECTION) -> CspsResult:
    """Score the component snapshot Sprint 2B would select for this subject.

    THE ONLY INPUT IS THE COMPONENT SEAM. It calls `select_snapshot`, which is
    provider-exact, identity-exact and has no fallback to another provider or to
    `projections.projected_points`. If there is no snapshot, this REFUSES — it
    does not reach for a scalar that was scored by somebody else's rules.
    """
    from providers.component_projections import select_snapshot

    if isinstance(profile, str):
        profile = load_profile(profile)

    snapshot = select_snapshot(db, provider=provider, player_id=player_id,
                               season=season, week=week, as_of=as_of)
    if snapshot is None:
        result = CspsResult(profile_id=profile.profile_id,
                            profile_version=profile.version, mode=mode,
                            status=ResultStatus.REFUSED,
                            calculated_at=datetime.now(timezone.utc))
        result.refusal = (
            f"no {provider} component snapshot for player {player_id}, season "
            f"{season}, week {week}"
            + (f" at or before {as_of.isoformat()}" if as_of else "")
            + ". Refusing rather than falling back to the legacy scalar "
              "projection, which was scored under a different provider's "
              "rules and would be double-converted.")
        result.player_id, result.provider = player_id, provider
        result.season, result.week = season, week
        return result

    result = score_components(
        snapshot.components or {}, profile, mode=mode,
        components_present=snapshot.components_present or [],
        position=snapshot.position)
    result.player_id = snapshot.player_id
    result.provider = snapshot.provider
    result.provider_player_key = snapshot.provider_player_key
    result.season = snapshot.season
    result.week = snapshot.week
    result.component_snapshot_id = snapshot.id
    result.component_vocabulary_version = snapshot.vocabulary_version
    result.observed_at = snapshot.observed_at
    return result


def score_week(db, *, provider: str, season: int, week: int,
               profile: ScoringProfile | str,
               player_ids: Sequence[int] | None = None,
               as_of: datetime | None = None,
               mode: str = PROJECTION) -> dict:
    """A whole league-week in ONE query, then pure arithmetic per subject.

    `select_week` fetches every snapshot for the week in a single statement and
    picks the winner per subject under the identical rule `select_snapshot`
    uses. Scoring a roster is then CPU-only: no network, no per-player query,
    and no N+1.
    """
    from providers.component_projections import select_week

    if isinstance(profile, str):
        profile = load_profile(profile)

    snapshots = select_week(db, provider=provider, season=season, week=week,
                            player_ids=player_ids, as_of=as_of)
    out: dict = {}
    for subject_id, snapshot in snapshots.items():
        result = score_components(
            snapshot.components or {}, profile, mode=mode,
            components_present=snapshot.components_present or [],
            position=snapshot.position)
        result.player_id = snapshot.player_id
        result.provider = snapshot.provider
        result.provider_player_key = snapshot.provider_player_key
        result.season, result.week = snapshot.season, snapshot.week
        result.component_snapshot_id = snapshot.id
        result.component_vocabulary_version = snapshot.vocabulary_version
        result.observed_at = snapshot.observed_at
        out[subject_id] = result
    return out
