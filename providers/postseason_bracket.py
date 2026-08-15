"""
WP1D — the production source of postseason BRACKET classification.

THE ONE THING THIS MODULE DOES: turn the matchup rows a league already has into
normalized `ProviderMatchup` DTOs, and give each one whatever bracket its
provider is able to state. It builds no championship track, decides no
eligibility and pays nobody; `season/championship_track.py` owns the first and
`economy/championship_podium.py` the last.

── WHY BRACKET IS A SEPARATE PROVIDER CAPABILITY ────────────────────────────

`providers/yahoo/normalize.py` normalizes a scoreboard and never sets `bracket`,
so every Yahoo matchup in this system is `MatchupBracket.UNKNOWN`. That is not an
oversight to be patched here. The WP1A recon recorded that this repository holds
no evidence of how — or whether — Yahoo distinguishes a championship matchup from
a consolation one, and inventing a field name would manufacture exactly the
evidence that is missing. So bracket classification is modelled as its own
capability that a provider either HAS or does not, rather than as a column the
scoreboard normalizer fills in with a guess.

THE REGISTRY IS EMPTY ON PURPOSE, AND THAT IS THE LIVE BEHAVIOUR.
A league no registered source claims keeps UNKNOWN on every matchup, the
championship track refuses to determine, and the Championship Pot is not paid —
the season simply does not close until the bracket is knowable. Losing a close is
the correct price for not knowing who won; paying 60/30/10 to the wrong three
teams is not.

── WHAT REACHES THIS MODULE, AND FROM WHERE ─────────────────────────────────

PERSISTED ROWS, NOT A LIVE FETCH. Every other step of the season close reads
persisted state, and `Matchup.finalized_at` is the certified economic-finality
fact the whole close is already built on. Re-fetching several weeks over the
network inside the terminal money action would introduce a second, fresher
opinion about results that the rest of the close does not share, and would make
the close fail on a provider outage that has nothing to do with the money.

IDENTITY IS THE PERSISTED PROVIDER KEY, NEVER AN ORDINAL OR A NAME. S6-R1 is
reused rather than restated: a team with no provider identity cannot be named in
a normalized DTO at all, so a league that never bound its teams yields no
matchups and fails closed downstream rather than being described in invented
keys.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from providers.base import Finality, MatchupBracket, ProviderMatchup
from providers.errors import ProviderIdentityError

#: name -> a registered postseason source. DELIBERATELY EMPTY at import: a
#: deployment that registers nothing classifies nothing and pays no Championship
#: Pot. See `register_postseason_source` for why the key is a source name and
#: NOT the league's identity provider.
_SOURCES: dict[str, "PostseasonBracketSource"] = {}


@runtime_checkable
class PostseasonBracketSource(Protocol):
    """What a provider must be able to answer for its postseason to be readable.

    Two questions, and the second is not optional decoration. A six-team field in
    a twelve-team league gives two teams a first-round bye, and a bye team plays
    in NO round-one matchup — its identity is unrecoverable from matchups alone.
    `ChampionshipFieldDeclaration` exists for that, and a source that can
    classify brackets but cannot name the field yields a determination that fails
    closed at round one. So both are asked here.
    """

    def knows(self, *, league_key: str) -> bool:
        """Whether this source can speak for that league at all.

        Asked first, and separately from `classify_week`, so that "I have no
        opinion about this league" is distinguishable from "I looked and every
        matchup is unclassified". Only the second is a determination.
        """

    def classify_week(self, *, league_key: str, week: int,
                      matchups: tuple[ProviderMatchup, ...],
                      ) -> tuple[ProviderMatchup, ...]:
        """The same matchups with `bracket` populated where the provider knows.

        Returning a matchup still UNKNOWN is a legitimate answer — "this provider
        classifies some weeks and not this one" — and fails closed downstream.
        """

    def championship_field(self, *, league_key: str,
                           season: int) -> frozenset[str] | None:
        """The team keys that entered the championship track, or None."""


def register_postseason_source(name: str,
                               source: PostseasonBracketSource) -> None:
    """Register a postseason source under its own name. Idempotent per source.

    THE KEY IS THE SOURCE'S NAME, NOT THE LEAGUE'S IDENTITY PROVIDER, and the
    distinction is the load-bearing one in this module.

    A league's identity provider answers "which internal team is this?" — Yahoo
    answers that, and answers it well. NOTHING FOLLOWS FROM IT about whether the
    same provider can say which of a league's games are championship games.
    Keying bracket capability off the identity binding would have made those two
    questions one, and the only way to certify a bracket at all would then have
    been to register synthetic material under Yahoo's name — which would assert,
    falsely, that Yahoo classifies brackets.

    So postseason classification is its own capability with its own registry. A
    deployment registers whichever sources it actually has; a league whose key no
    registered source claims stays UNKNOWN and its Championship Pot is not paid.
    Yahoo registers nothing today, and that is not worked around anywhere.

    Registering a DIFFERENT source under an existing name raises rather than
    replacing it: two live opinions about which games are championship games is
    the ambiguity this whole area exists to refuse.
    """
    existing = _SOURCES.get(name)
    if existing is not None and existing is not source:
        raise ValueError(
            f"a postseason source named {name!r} is already registered "
            f"({type(existing).__name__}); refusing to replace it with "
            f"{type(source).__name__}.")
    _SOURCES[name] = source


def unregister_postseason_source(name: str) -> None:
    """Drop a registration. Present so a harness can restore the empty default."""
    _SOURCES.pop(name, None)


def postseason_source_for(league_key: str | None) -> PostseasonBracketSource | None:
    """The one registered source that claims this league, or None.

    TWO SOURCES CLAIMING ONE LEAGUE IS A REFUSAL, NOT A PRECEDENCE RULE. If a
    deployment ever ran two postseason adapters that both knew a league, picking
    either would decide a championship by registration order.
    """
    if not league_key:
        return None
    claimants = [s for s in _SOURCES.values() if s.knows(league_key=league_key)]
    if len(claimants) > 1:
        # A NAMED PROVIDER REFUSAL, NOT A BARE ValueError. Both callers — the
        # season close and the settlement report — already map `ProviderError`
        # to a governed answer, so this surfaces as a 409 an operator can act on
        # rather than as a 500 from a read-only report.
        raise ProviderIdentityError(
            ProviderIdentityError.AMBIGUOUS,
            f"{len(claimants)} postseason sources claim league {league_key!r}; "
            f"refusing to choose between two statements of which games are "
            f"championship games.")
    return claimants[0] if claimants else None


def league_provider(db, *, league_id: int) -> str | None:
    """The one provider this league's teams are bound to, or None.

    None for an unbound league and, deliberately, for a league whose teams
    disagree — a mixed binding means there is no single provider whose postseason
    vocabulary governs, and choosing one of them would decide a championship on
    row order.
    """
    from db.schema import Team

    providers = {p for (p,) in db.query(Team.provider)
                 .filter(Team.league_id == league_id).distinct().all() if p}
    return next(iter(providers)) if len(providers) == 1 else None


def rehydrate_week(db, *, league, week: int) -> tuple[ProviderMatchup, ...]:
    """One persisted week as normalized DTOs, every bracket UNKNOWN.

    FINALITY COMES FROM `finalized_at` AND NOTHING ELSE — not from a non-null
    score, not from 0.0-0.0, not from `refreshed_at`. That is the same rule the
    column's own comment fixes, and restating it as a score comparison here would
    put a second, weaker definition of "over" on a money path.

    A DECLARED WINNER, NOT A DERIVED ONE. `winner_team_id` is read straight
    across; a final row with no winner is reported as a tie rather than resolved
    by comparing points, because `Finality`'s contract and the championship
    track's `is_decided` both refuse that inference at every other boundary.
    """
    from db.schema import Matchup, Team

    keys = {t.id: t.provider_team_key for t in
            db.query(Team).filter(Team.league_id == league.id).all()}
    provider = league_provider(db, league_id=league.id)

    out: list[ProviderMatchup] = []
    rows = (db.query(Matchup)
            .filter(Matchup.league_id == league.id, Matchup.week == week)
            .order_by(Matchup.id).all())
    for row in rows:
        home = keys.get(row.home_team_id)
        away = keys.get(row.away_team_id)
        if not home or not away or not row.provider_matchup_key:
            # UNNAMEABLE, SO NOT REPORTED. A matchup whose participants have no
            # provider identity cannot be described without inventing keys, and
            # the week it belongs to then reads as incomplete — which is the
            # honest state and the one that fails closed.
            continue
        final = row.finalized_at is not None
        winner = keys.get(row.winner_team_id) if row.winner_team_id else None
        out.append(ProviderMatchup(
            provider=provider or "",
            league_key=league.provider_league_key or "",
            matchup_key=row.provider_matchup_key,
            week=week,
            home_team_key=home,
            away_team_key=away,
            home_points=row.home_score,
            away_points=row.away_score,
            finality=Finality.FINAL if final else Finality.NOT_FINAL,
            winner_team_key=winner,
            is_tied=bool(final and row.winner_team_id is None),
            bracket=MatchupBracket.UNKNOWN,
        ))
    return tuple(out)


def classified_week(db, *, league, week: int) -> tuple[ProviderMatchup, ...]:
    """One week's matchups with brackets applied if the provider can state them.

    Unclassified is the pass-through case and needs no branch of its own: with no
    registered source the tuple is returned exactly as rehydrated, every bracket
    UNKNOWN, and the championship track refuses on it.
    """
    matchups = rehydrate_week(db, league=league, week=week)
    source = postseason_source_for(league.provider_league_key)
    if source is None or not matchups:
        return matchups
    return tuple(source.classify_week(
        league_key=league.provider_league_key or "", week=week,
        matchups=matchups))


def championship_field(db, *, league) -> frozenset[str] | None:
    """The declared championship field for this league, or None if unstated."""
    source = postseason_source_for(league.provider_league_key)
    if source is None:
        return None
    return source.championship_field(
        league_key=league.provider_league_key or "", season=league.season)
