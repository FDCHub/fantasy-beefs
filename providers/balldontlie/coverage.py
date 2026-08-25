"""Sprint 2B · can a persisted snapshot carry what CSPS will need?

THE QUESTION THIS ANSWERS, AND THE ONE IT DOES NOT. It answers: for every
scoring category in CULV Appreciation Society and Mr Whiskers Memorial League,
is the input CSPS will need present in a stored BALLDONTLIE component
projection, derivable from what is stored, or absent? It does NOT score
anything, apply a rate, or convert a component into a point — that is WP4's
work, and doing any of it here would be the second implementation of a scoring
engine this repository has been careful not to acquire.

Every classification below comes from the Phase 0 diligence report's coverage
matrix, which was built by sweeping BALLDONTLIE weeks 1, 4, 8, 12 and 17 (160
DST team-weeks among them) to tell a genuinely absent field apart from a zero
that was simply omitted.

── THE FOUR VERDICTS, AND WHY "DERIVED" IS NOT A SOFTER "DIRECT" ───────────

    DIRECT       the component is in the projection block under its own name.
    DERIVED      the component is NOT projected, and a projection for it must be
                 MODELLED from components that are — reception counts from
                 `targets`, a 150-yard bonus tier from a 100–199 bucket. Real
                 work, real error bars, and WP4's to do openly.
    SETTLEMENT   projected only as a distribution, but exact at settlement from
                 `fantasy/weekly_stats`. Pricing needs the model; paying does
                 not.
    ABSENT       BALLDONTLIE does not publish it in any form. There is exactly
                 one, and it is named rather than smoothed over.

THREE-AND-OUTS FORCED IS ABSENT, AND STAYS ABSENT. It is in neither the stat
vocabulary, the scoring formats, nor the projection block. WP2 can derive a
FINALIZED count from `/plays` down-sequencing and returns it UNVERIFIED because
the threshold is uncalibrated; there is no projection of it at all, and this
module will not invent one. A Mr Whiskers DST projection is therefore
structurally short by one category until that gap is closed by verification, and
saying so here is the point of the exercise.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CATEGORIES", "CULV", "WHISKERS", "Category", "coverage_report",
           "uncovered"]

CULV = "CULV Appreciation Society"
WHISKERS = "Mr Whiskers Memorial League"

DIRECT = "direct"
DERIVED = "derived"
SETTLEMENT = "settlement-exact, projection modelled"
ABSENT = "absent"


@dataclass(frozen=True)
class Category:
    """One league scoring category, and what a stored snapshot can offer it."""

    leagues: tuple
    yahoo_category: str
    #: The normalized component name CSPS will read, or "" when there is none.
    component: str
    #: The BALLDONTLIE projection field the component comes from.
    source_field: str
    verdict: str
    note: str = ""

    @property
    def persisted(self) -> str:
        """How the material reaches CSPS from a stored row.

        A DERIVED category whose source is not a component — the pick six is the
        only one — reaches CSPS from nowhere in this table. Saying "components[
        '/plays participants']" would be a lie about a column, so it says so.
        """
        if self.verdict == ABSENT:
            return "not persisted — nothing to persist"
        if not self.component:
            return f"not persisted — derived elsewhere ({self.source_field})"
        if self.verdict == DERIVED:
            return f"components[{self.source_field!r}] (input to a model)"
        return f"components[{self.component!r}]"


BOTH = (CULV, WHISKERS)

CATEGORIES: tuple = (
    # ── offence ──────────────────────────────────────────────────────────────
    Category(BOTH, "Passing yards", "passing_yards", "passing_yards", DIRECT),
    Category(BOTH, "Passing TD", "passing_touchdowns", "passing_touchdowns",
             DIRECT),
    Category(BOTH, "Interception thrown", "passing_interceptions",
             "passing_interceptions", DIRECT),
    Category((WHISKERS,), "Pass bonus 300 / 400 / 500", "passing_yards",
             "passing_300_to_399_yard_games", DERIVED,
             "the projection carries 300-399 and 400+ probabilities and NO 500 "
             "tier, so the top bonus must be modelled from the yardage "
             "distribution. Exact from raw yards at settlement."),
    Category(BOTH, "Rushing yards", "rushing_yards", "rushing_yards", DIRECT),
    Category(BOTH, "Rushing TD", "rushing_touchdowns", "rushing_touchdowns",
             DIRECT),
    Category(BOTH, "Rush bonus (100 CULV; 100/150/200 Whiskers)",
             "rushing_yards", "rushing_100_to_199_yard_games", DERIVED,
             "buckets are 100-199 and 200+, so the 150 tier straddles a bucket "
             "boundary and must be modelled."),
    Category(BOTH, "Receptions", "receptions", "targets", DERIVED,
             "THE ONE EVERY PPR LEAGUE TRIPS ON. The projection block carries "
             "no reception count at all — only targets — so a PPR input is "
             "modelled from targets and a catch rate. Sprint 2B refuses to "
             "zero-fill it (rule 0F-20), so the absence is visible in the "
             "stored row rather than hidden as a confident 0.0."),
    Category(BOTH, "Receiving yards", "receiving_yards", "receiving_yards",
             DIRECT),
    Category(BOTH, "Receiving TD", "receiving_touchdowns",
             "receiving_touchdowns", DIRECT),
    Category((WHISKERS,), "Receiving bonus tiers", "receiving_yards",
             "receiving_100_to_199_yard_games", DERIVED, "as rushing."),
    Category(BOTH, "Fumbles lost", "fumbles_lost", "fumbles_lost", DIRECT),
    Category(BOTH, "2-point conversion",
             "passing_two_point_conversions",
             "passing_/rushing_/receiving_two_point_conversions", DIRECT,
             "three structured fields; never parsed from play text."),
    Category(BOTH, "Return TD", "kick_return_touchdowns",
             "kick_return_touchdowns + punt_return_touchdowns", DIRECT,
             "Yahoo collapses both into one category; BALLDONTLIE splits them, "
             "which is strictly better."),
    Category(BOTH, "Offensive fumble return TD",
             "offensive_fumble_recovery_touchdowns",
             "offensive_fumble_recovery_touchdowns", DIRECT),
    Category((WHISKERS,), "Pick six thrown", "", "/plays participants", DERIVED,
             "not a BALLDONTLIE stat and not in the projection block at all. "
             "Derived at SETTLEMENT from /plays — INTERCEPT + TOUCHDOWN charged "
             "to the passer participant, validated exactly on Matthew "
             "Stafford. Pricing must model it from passing_interceptions; "
             "nothing about it is persisted in a component snapshot."),

    # ── kicker ───────────────────────────────────────────────────────────────
    Category(BOTH, "PAT made", "extra_points_made", "extra_points_made", DIRECT),
    Category((WHISKERS,), "PAT missed", "extra_points_missed",
             "extra_points_missed", DIRECT,
             "also cross-checkable as attempts minus made."),
    Category((CULV,), "FG total made yards", "field_goals_made_yards",
             "field_goals_made_yards", DIRECT,
             "the exact figure CULV needs as a single integer. Yahoo's own feed "
             "cannot supply this."),
    Category((WHISKERS,), "FG made 0-19 / 20-29 / 30-39",
             "field_goals_made_0_to_39", "field_goals_made_0_to_39", DIRECT,
             "all three tiers score 3 in Whiskers, so the collapsed bucket is "
             "exact."),
    Category((WHISKERS,), "FG made 40-49", "field_goals_made_40_to_49",
             "field_goals_made_40_to_49", DIRECT),
    Category((WHISKERS,), "FG made 50+", "field_goals_made_50_plus",
             "field_goals_made_50_plus", DIRECT),
    Category((WHISKERS,), "FG missed 0-19 (-3.14) vs 20-39 (-1)",
             "field_goals_missed_0_to_39",
             "field_goals_missed_0_to_39 + field_goals_missed_yards",
             SETTLEMENT,
             "with ONE miss the missed-yards figure is that miss's exact "
             "distance, which settled all nine week-17 kickers with a miss. "
             "Two or more misses including a 0-39 need /plays."),
    Category((WHISKERS,), "FG missed 40-49 / 50+",
             "field_goals_missed_40_to_49", "field_goals_missed_40_to_49",
             DIRECT, "both score zero in Whiskers, so precision is moot."),

    # ── defence / special teams ──────────────────────────────────────────────
    Category(BOTH, "Sack", "defensive_sacks", "defensive_sacks", DIRECT,
             "half sacks carry cleanly — defensive_half_sacks is exactly double "
             "in all 29 observed rows, so a 0.5 surfaces as x.5."),
    Category(BOTH, "Interception", "defensive_interceptions",
             "defensive_interceptions", DIRECT),
    Category(BOTH, "Fumble recovery", "opponent_fumble_recoveries",
             "opponent_fumble_recoveries", DIRECT,
             "kept distinct from fumbles_forced, which Yahoo does not score."),
    Category(BOTH, "Defensive TD", "interception_return_touchdowns",
             "interception_return_touchdowns + fumble_return_touchdowns",
             DIRECT, "turnover_return_touchdowns is the pre-summed total."),
    Category(BOTH, "Safety", "defensive_safeties", "defensive_safeties", DIRECT),
    Category(BOTH, "Blocked kick", "kicks_blocked", "kicks_blocked", DIRECT),
    Category(BOTH, "Kick / punt return TD", "kick_return_touchdowns",
             "kick_return_touchdowns / punt_return_touchdowns", DIRECT,
             "blocked_kick_return_touchdowns is also present."),
    Category(BOTH, "Points allowed", "dst_points_allowed", "dst_points_allowed",
             SETTLEMENT,
             "settlement is exact. The projection's buckets (14-17, 18-21, "
             "22-27) STRADDLE Yahoo's (14-20, 21-27), so bucket probabilities "
             "must be re-split for pricing."),
    Category(BOTH, "Extra point returned", "two_point_returns",
             "two_point_returns", DIRECT),
    Category((WHISKERS,), "Three-and-outs forced", "", "", ABSENT,
             "THE ONLY GENUINELY ABSENT CATEGORY. Not in the stat vocabulary, "
             "the scoring formats, or the projection block. WP2 derives a "
             "FINALIZED count from /plays and returns it UNVERIFIED because the "
             "threshold is uncalibrated (1.19 per team-game against a norm "
             "nearer 2.3). There is no projection of it, and Sprint 2B does not "
             "fabricate one."),
)


def uncovered() -> tuple:
    """Categories a stored snapshot cannot serve in any form. Expect exactly one."""
    return tuple(c for c in CATEGORIES if c.verdict == ABSENT)


def coverage_report(league: str | None = None) -> dict:
    selected = [c for c in CATEGORIES if league is None or league in c.leagues]
    return {
        "league": league or "both",
        "categories": len(selected),
        "direct": sum(1 for c in selected if c.verdict == DIRECT),
        "derived": sum(1 for c in selected if c.verdict == DERIVED),
        "settlement_exact": sum(1 for c in selected if c.verdict == SETTLEMENT),
        "absent": sum(1 for c in selected if c.verdict == ABSENT),
        "absent_categories": [c.yahoo_category for c in selected
                              if c.verdict == ABSENT],
    }


def _print_matrix() -> None:                    # pragma: no cover - operator tool
    header = ("YAHOO CATEGORY", "COMPONENT", "PERSISTED AS", "BDL SOURCE",
              "VERDICT")
    print(" | ".join(header))
    print("-" * 78)
    for category in CATEGORIES:
        print(" | ".join((category.yahoo_category, category.component or "—",
                          category.persisted, category.source_field or "—",
                          category.verdict)))


if __name__ == "__main__":                      # pragma: no cover
    _print_matrix()
