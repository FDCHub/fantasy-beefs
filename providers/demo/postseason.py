"""The Demo PostseasonBracketSource — a provider that can actually state a bracket.

WHY THIS EXISTS AND WHY IT IS NOT A SHORTCUT. `providers/postseason_bracket.py`
models bracket classification as a capability a provider either HAS or does not,
precisely because no evidence in this repository shows that Yahoo has it. The
Demo provider genuinely has it: it invented the games, so it knows which ones
were championship games, and saying so is a statement of fact rather than an
inference.

WHAT IT DOES NOT DO, and each omission is load-bearing:

  * It does NOT name a podium. It classifies matchups and declares the field;
    `season/championship_track.py` derives the track and
    `economy/championship_podium.py` derives champion, runner-up and third.
    A source that returned an ordered podium would put the determination in the
    provider, where it could disagree with the games.
  * It does NOT infer anything from a score. The winner it reports is the one
    the matchup DTO already declared.
  * It does NOT identify the official third-place game. WP1BC derives that from
    the semifinal losers, and re-stating it here would create a second opinion
    about which game it is.
  * It does NOT claim a league it did not invent. `knows()` matches the Demo
    league-key prefix and nothing else, so registering it can never take over a
    Yahoo league — which, under `postseason_source_for`, would otherwise be an
    ambiguity that refuses every real season close.

REGISTRATION IS A DEPLOYMENT ACT, NOT AN IMPORT SIDE EFFECT. Nothing registers
on import; `install_demo_postseason_source()` is called by the composition layer
that mounts the Demo routes. That keeps the registry's default — empty, classify
nothing, pay no Championship Pot — true for any deployment that does not want
Demo at all.
"""

from __future__ import annotations

from dataclasses import replace

from providers.base import ProviderMatchup
from providers.demo import DEMO_LEAGUE_KEY_PREFIX
from providers.demo.scenario import DemoScenario

#: The name this source registers under. A SOURCE name, not a provider name:
#: `providers/postseason_bracket.py` keys the registry on the former precisely
#: so a league's identity provider and its bracket authority stay separable.
DEMO_POSTSEASON_SOURCE = "demo-postseason"


class DemoPostseasonBracketSource:
    """States the bracket of every game the Demo scenario invented."""

    def knows(self, *, league_key: str) -> bool:
        """Only Demo leagues. Asked separately from `classify_week` so that
        "I have no opinion about this league" stays distinguishable from
        "I looked and every matchup is unclassified"; only the second is a
        determination."""
        return bool(league_key) and league_key.startswith(DEMO_LEAGUE_KEY_PREFIX)

    def classify_week(self, *, league_key: str, week: int,
                      matchups: tuple[ProviderMatchup, ...],
                      ) -> tuple[ProviderMatchup, ...]:
        """The same matchups with `bracket` populated from the scenario.

        MATCHED BY PARTICIPANTS, NOT BY ROW ORDER. The persisted rows arrive in
        database order and carry the canonical matchup key; the scenario answers
        on the ordinal pair, so the two are joined through the team keys they
        both name. Order is never consulted.

        A REGULAR-SEASON WEEK STAYS UNKNOWN, because that is the truth: the
        scenario states brackets for its postseason games and says nothing about
        week 2, and the championship track never asks about it.
        """
        if not self.knows(league_key=league_key):
            return tuple(matchups)
        scenario = DemoScenario(league_key=league_key)

        out: list[ProviderMatchup] = []
        for matchup in matchups:
            home = scenario.ordinal_of(matchup.home_team_key)
            away = scenario.ordinal_of(matchup.away_team_key)
            if home is None or away is None:
                # A participant this scenario never invented. Left UNKNOWN,
                # which fails the determination closed — the honest answer for a
                # game whose teams the provider cannot name.
                out.append(matchup)
                continue
            out.append(replace(matchup,
                               bracket=scenario.bracket_of(week, home, away)))
        return tuple(out)

    def championship_field(self, *, league_key: str,
                           season: int) -> frozenset[str] | None:
        """The team keys that entered the championship track, or None.

        DECLARED RATHER THAN RECONSTRUCTED. This scenario's field has no byes,
        so round one's participants would in fact reconstruct it — declaring it
        anyway exercises the `PROVIDER_CLASSIFIED` authority path and the
        field-size cross-check against `playoff_team_count`, which a
        reconstruction-only source would leave untested.
        """
        if not self.knows(league_key=league_key):
            return None
        return DemoScenario(league_key=league_key).championship_field


#: Module-level so repeated installation registers the SAME object — the
#: production registry refuses to rebind a name to a DIFFERENT source, and two
#: callers installing it must not trip that.
DEMO_BRACKET_SOURCE = DemoPostseasonBracketSource()


def install_demo_postseason_source() -> DemoPostseasonBracketSource:
    """Register the Demo postseason source, as a Demo deployment does.

    THE REGISTRY IS PRODUCTION; ONLY THE SOURCE IS THE DEMO'S. A caller that
    invokes this exercises the real extension point the season-close route reads
    through, so a Demo championship reaches the podium by the production path
    rather than by injection into a test-only parameter.
    """
    from providers.postseason_bracket import register_postseason_source

    register_postseason_source(DEMO_POSTSEASON_SOURCE, DEMO_BRACKET_SOURCE)
    return DEMO_BRACKET_SOURCE
