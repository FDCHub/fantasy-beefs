"""Sprint 3 · the scoring profile — one league's rules, as data.

WHY THIS EXISTS WHEN `LeagueScoring` ALREADY DOES. `db/schema.LeagueScoring` has
seven columns: a scoring type, a reception rate, three touchdown values and two
hundred-yard bonuses. Every league this product has run so far fits in them.
Mr Whiskers Memorial League does not fit in them and never will:

    a −3.14 penalty for a missed extra point
    field goals scored by distance band, and missed ones penalised by band
    a SECOND penalty for an interception returned for a touchdown
    three tiers of rushing and receiving yardage bonus
    a defensive category (three-and-outs forced) with no provider field at all

Those are not exotic; they are what a real Yahoo league had switched on. The
Phase 0 reconciliation settled 58 real records against them exactly, so the
rules are known — what was missing was anywhere to WRITE them down.

── THE MODEL IS DATA, AND THE DATA IS VERSIONED ────────────────────────────

A profile is a JSON document under `scoring/profiles/`, loaded into the frozen
dataclasses below. Not code, because a league's rules are configuration and the
next twenty leagues must not each need a function; not a database table yet,
because nothing writes them at runtime and a table nobody writes is a migration
that buys nothing (Sprint 4 wires league configuration to this seam).

`profile_id` and `version` travel with every scored result, so a projection can
always be traced to the exact rules that produced it.

── AN ABSENT RULE CONTRIBUTES ZERO, AND SAYS SO ────────────────────────────

A category a league does not score is simply absent from its profile, and the
evaluator records it as NOT_ENABLED rather than silently skipping it. CULV
Appreciation Society scores no yardage bonuses at all — that is a fact about
CULV, and it should be visible in an audit rather than inferred from silence.

── AN UNRESOLVED RULE IS NOT THE SAME AS AN ABSENT ONE ─────────────────────

`unresolved` names a rule the league DOES score and whose value the historical
evidence does not pin down. Mr Whiskers has passing-yardage bonuses at 300, 400
and 500 yards; no reconciled record crossed 300, so their point values are not
established by anything this repository can show. They are therefore declared
and marked unresolved, and a line that would trigger one refuses instead of
guessing. Recording it as "no bonus" would silently under-score a 300-yard game;
guessing +1 would silently invent a rule.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = [
    "Band",
    "PROFILE_DIR",
    "ScoringProfile",
    "Tier",
    "available_profiles",
    "load_profile",
]

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "profiles")


class ProfileError(ValueError):
    """A profile document that cannot be trusted to score with."""


@dataclass(frozen=True)
class Tier:
    """A yardage threshold bonus: cross `threshold` yards, earn `points`.

    CUMULATIVE, NOT EXCLUSIVE — and the distinction was measured, not assumed.
    Bijan Robinson's 195 rushing yards earned +2 in Mr Whiskers: the 100 tier
    AND the 150 tier, not just the highest one reached. A profile whose tiers
    were exclusive would have paid +1 and been wrong by a point.
    """

    threshold: float
    points: float
    unresolved: bool = False


@dataclass(frozen=True)
class Band:
    """A closed range of a continuous stat, and what it scores.

    `low` and `high` are INCLUSIVE. Yahoo's own labels read "Pts Allow 28-34",
    and a band model that treated 34 as belonging to the next band would move a
    defence's score by three points on the boundary.
    """

    low: float
    high: float
    points: float

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high


def _tiers(raw: Any) -> tuple:
    if not raw:
        return ()
    return tuple(Tier(threshold=float(t["threshold"]),
                      points=float(t.get("points") or 0.0),
                      unresolved=bool(t.get("unresolved")))
                 for t in raw)


def _bands(raw: Any) -> tuple:
    if not raw:
        return ()
    bands = tuple(Band(low=float(b["low"]), high=float(b["high"]),
                       points=float(b["points"])) for b in raw)
    ordered = sorted(bands, key=lambda b: b.low)
    for first, second in zip(ordered, ordered[1:]):
        if first.high >= second.low:
            raise ProfileError(
                f"points bands overlap: [{first.low}, {first.high}] and "
                f"[{second.low}, {second.high}]. Two bands claiming one value "
                f"means the score depends on which is checked first.")
    return ordered and tuple(ordered)


@dataclass(frozen=True)
class ScoringProfile:
    """One league's complete scoring rules.

    Every rate defaults to 0.0, so a category a league does not score costs
    nothing to omit and contributes nothing when omitted. The evaluator still
    reports it — as NOT_ENABLED — because "this league does not score receptions"
    and "we could not find a reception count" must never look the same.
    """

    profile_id: str
    name: str
    version: str
    provenance: str = ""

    # ── offence ──────────────────────────────────────────────────────────────
    passing_yards_per_point: float = 0.0      # points PER YARD
    passing_touchdown: float = 0.0
    passing_interception: float = 0.0
    pick_six_thrown: float = 0.0
    passing_tiers: tuple = ()
    rushing_yards_per_point: float = 0.0
    rushing_touchdown: float = 0.0
    rushing_tiers: tuple = ()
    reception: float = 0.0
    receiving_yards_per_point: float = 0.0
    receiving_touchdown: float = 0.0
    receiving_tiers: tuple = ()
    two_point_conversion: float = 0.0
    fumble_lost: float = 0.0
    offensive_fumble_recovery_touchdown: float = 0.0
    return_touchdown: float = 0.0

    # ── kicker ───────────────────────────────────────────────────────────────
    #: CULV's rule, and the one Yahoo's own API cannot serve: points per YARD of
    #: made field goals, summed. Zero for a league that scores by band instead.
    field_goal_yards_per_point: float = 0.0
    #: Made-FG points by distance band, keyed by the normalized component name.
    field_goals_made: Mapping[str, float] = field(default_factory=dict)
    field_goals_missed: Mapping[str, float] = field(default_factory=dict)
    extra_point_made: float = 0.0
    extra_point_missed: float = 0.0

    # ── defence / special teams ──────────────────────────────────────────────
    dst_sack: float = 0.0
    dst_interception: float = 0.0
    dst_fumble_recovery: float = 0.0
    dst_touchdown: float = 0.0
    dst_safety: float = 0.0
    dst_blocked_kick: float = 0.0
    dst_return_touchdown: float = 0.0
    dst_two_point_return: float = 0.0
    dst_three_and_out: float = 0.0
    points_allowed_bands: tuple = ()
    yards_allowed_bands: tuple = ()

    def enabled(self, attribute: str) -> bool:
        value = getattr(self, attribute, 0.0)
        if isinstance(value, (tuple, list, dict)):
            return bool(value)
        return bool(value)

    @property
    def unresolved_rules(self) -> tuple:
        """Rules this league scores whose VALUE the evidence does not establish."""
        out = []
        for name in ("passing_tiers", "rushing_tiers", "receiving_tiers"):
            for tier in getattr(self, name):
                if tier.unresolved:
                    out.append(f"{name}@{tier.threshold:g}")
        return tuple(out)

    def as_dict(self) -> dict:
        return {"profile_id": self.profile_id, "name": self.name,
                "version": self.version,
                "unresolved_rules": list(self.unresolved_rules)}


def load_profile(profile_id: str, directory: str | None = None
                 ) -> ScoringProfile:
    """Load one profile by id. Fails closed on anything it cannot trust."""
    directory = directory or PROFILE_DIR
    path = os.path.join(directory, f"{profile_id}.json")
    if not os.path.exists(path):
        raise ProfileError(
            f"no scoring profile {profile_id!r} in {directory}. Known: "
            f"{sorted(available_profiles(directory))!r}. A league cannot be "
            f"scored under rules nobody has written down.")
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    return from_document(raw, profile_id=profile_id)


def from_document(raw: Mapping[str, Any], *, profile_id: str | None = None
                  ) -> ScoringProfile:
    """Validate a profile document and freeze it."""
    for required in ("profile_id", "name", "version"):
        if not raw.get(required):
            raise ProfileError(
                f"scoring profile is missing {required!r}. A profile without a "
                f"version cannot be cited by a scored result, and a result "
                f"nobody can trace to its rules is not auditable.")
    if profile_id is not None and raw["profile_id"] != profile_id:
        raise ProfileError(
            f"profile document declares id {raw['profile_id']!r} but was "
            f"loaded as {profile_id!r}. A profile whose filename and identity "
            f"disagree will be cited under the wrong name.")

    offence = raw.get("offense", {})
    kicker = raw.get("kicker", {})
    defense = raw.get("dst", {})

    profile = ScoringProfile(
        profile_id=raw["profile_id"], name=raw["name"], version=raw["version"],
        provenance=raw.get("provenance", ""),
        passing_yards_per_point=float(offence.get("passing_yards_per_point") or 0.0),
        passing_touchdown=float(offence.get("passing_touchdown") or 0.0),
        passing_interception=float(offence.get("passing_interception") or 0.0),
        pick_six_thrown=float(offence.get("pick_six_thrown") or 0.0),
        passing_tiers=_tiers(offence.get("passing_tiers")),
        rushing_yards_per_point=float(offence.get("rushing_yards_per_point") or 0.0),
        rushing_touchdown=float(offence.get("rushing_touchdown") or 0.0),
        rushing_tiers=_tiers(offence.get("rushing_tiers")),
        reception=float(offence.get("reception") or 0.0),
        receiving_yards_per_point=float(offence.get("receiving_yards_per_point") or 0.0),
        receiving_touchdown=float(offence.get("receiving_touchdown") or 0.0),
        receiving_tiers=_tiers(offence.get("receiving_tiers")),
        two_point_conversion=float(offence.get("two_point_conversion") or 0.0),
        fumble_lost=float(offence.get("fumble_lost") or 0.0),
        offensive_fumble_recovery_touchdown=float(
            offence.get("offensive_fumble_recovery_touchdown") or 0.0),
        return_touchdown=float(offence.get("return_touchdown") or 0.0),
        field_goal_yards_per_point=float(
            kicker.get("field_goal_yards_per_point") or 0.0),
        field_goals_made={k: float(v)
                          for k, v in (kicker.get("field_goals_made") or {}).items()},
        field_goals_missed={k: float(v)
                            for k, v in (kicker.get("field_goals_missed") or {}).items()},
        extra_point_made=float(kicker.get("extra_point_made") or 0.0),
        extra_point_missed=float(kicker.get("extra_point_missed") or 0.0),
        dst_sack=float(defense.get("sack") or 0.0),
        dst_interception=float(defense.get("interception") or 0.0),
        dst_fumble_recovery=float(defense.get("fumble_recovery") or 0.0),
        dst_touchdown=float(defense.get("touchdown") or 0.0),
        dst_safety=float(defense.get("safety") or 0.0),
        dst_blocked_kick=float(defense.get("blocked_kick") or 0.0),
        dst_return_touchdown=float(defense.get("return_touchdown") or 0.0),
        dst_two_point_return=float(defense.get("two_point_return") or 0.0),
        dst_three_and_out=float(defense.get("three_and_out") or 0.0),
        points_allowed_bands=_bands(defense.get("points_allowed_bands")),
        yards_allowed_bands=_bands(defense.get("yards_allowed_bands")),
    )

    # A KICKER PROFILE MUST PICK ONE SYSTEM. CULV scores made field goals by
    # total yardage; Mr Whiskers scores them by distance band. A profile doing
    # both would pay a kicker twice for one kick, which is the exact class of
    # error this sprint exists to make impossible.
    if profile.field_goal_yards_per_point and profile.field_goals_made:
        raise ProfileError(
            f"profile {profile.profile_id!r} scores made field goals BOTH by "
            f"total yardage and by distance band. One kick would be paid "
            f"twice; a league scores one way or the other.")
    return profile


def available_profiles(directory: str | None = None) -> tuple:
    directory = directory or PROFILE_DIR
    if not os.path.isdir(directory):
        return ()
    return tuple(sorted(name[:-5] for name in os.listdir(directory)
                        if name.endswith(".json")))
