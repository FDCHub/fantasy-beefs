"""Cross-provider player identity — Yahoo <-> FantasyStakes <-> BALLDONTLIE (WP1).

`providers/identity.py` answers "which internal row is this provider key?" for
ONE provider at a time, and every rule in it holds here too. This module answers
the different question WP1 exists for: the roster came from Yahoo, the facts are
about to come from BALLDONTLIE, and the two providers have never heard of each
other's identifiers. Something has to say that Yahoo's `461.p.31883` and
BALLDONTLIE's player 882 are the same man — durably, and without ever letting a
name become the thing that says it.

── THE ONE RULE ────────────────────────────────────────────────────────────

A NAME MAY DISCOVER A MAPPING. A NAME MAY NEVER BE THE MAPPING.

Discovery runs once, from a normalized name plus a team plus a position, and its
only product is a `provider_player_alias` row keyed on the two providers' own
identifiers. Every later lookup reads that row. So a player who is traded, who
changes his listed position, who has a suffix added or dropped by one provider,
or whose name is corrected, keeps the identity he already had — because after
the first resolution nothing consults his name again.

That is also why a trade cannot mint a second identity. The persisted mapping is
consulted FIRST, before any name or team is looked at, so a Yahoo row that now
says BUF and a BALLDONTLIE row that still says MIA resolve to the same
`players.id` without either team ever being compared.

── WHY THERE IS NO FUZZY MATCHING ──────────────────────────────────────────

Not "fuzzy matching is configured off". There is no similarity scorer in this
module at all. Every comparison below is an equality test between two normalized
strings, so the resolver's behaviour is a property of the inputs and not of a
threshold somebody chose. `suggest_candidates` exists for an OPERATOR staring at
an UNRESOLVED subject, returns a list, is never called by the resolver, and
cannot bind anything.

The reason is that a settlement runs on this. A 0.93-similar name is not
evidence about a human being; it is evidence about two strings. Under a
threshold, the wrong player's stat line pays out the wrong wager and nothing in
the system ever notices, because a confident wrong answer is indistinguishable
from a right one at every layer above this file.

── FOUR OUTCOMES, AND THE THREE FAILURES ARE DIFFERENT FACTS ───────────────

    RESOLVED     exactly one identity, and it is now persisted.
    UNRESOLVED   the provider has no such subject. Ingest it later, or accept
                 that this player has no BALLDONTLIE facts.
    AMBIGUOUS    the provider has MORE THAN ONE subject that fits. An operator
                 must choose. Never resolved by picking the first.
    CONFLICT     the mappings already stored disagree with each other or with
                 what the caller supplied. A human wrote something wrong, or a
                 constraint is missing.

Collapsing those into one "failed" would be the actual defect: UNRESOLVED is a
COVERAGE problem an ingest fixes, AMBIGUOUS is a DECISION only a person can
make, and CONFLICT is a DATA-INTEGRITY problem where acting on either candidate
makes the corruption permanent. They need three different humans doing three
different things.

`CrossProviderResolution` is returned rather than raised so a caller sweeping a
whole roster can count the outcomes; `.require()` converts it to the repo's
existing `ProviderIdentityError` for a caller that must not proceed.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone

from providers.errors import ProviderIdentityError
from providers.nfl_teams import (
    TEAM_DEFENSE,
    canonical_position,
    is_team_defense,
    to_canonical_team,
)

__all__ = [
    "BALLDONTLIE",
    "CanonicalSubject",
    "CrossProviderResolution",
    "Outcome",
    "ProviderSubject",
    "SubjectDirectory",
    "bind_alias",
    "canonical_subject_from_player",
    "discover",
    "lookup_alias",
    "normalize_person_name",
    "resolve_player",
    "retire_alias",
    "set_manual_alias",
    "suggest_candidates",
]


#: The provider name this WP was built for. A string, not an enum, because
#: `players.provider` and `leagues.provider` are already plain strings and a
#: second convention for the same idea is worse than a repeated literal.
BALLDONTLIE = "balldontlie"


class Outcome:
    """The four things a cross-provider resolution can conclude."""

    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"

    #: Outcome -> the reason constant `providers.errors` already uses, so a
    #: caller that catches ProviderIdentityError sees the vocabulary it knows.
    TO_IDENTITY_REASON = {
        UNRESOLVED: ProviderIdentityError.UNKNOWN,
        AMBIGUOUS: ProviderIdentityError.AMBIGUOUS,
        CONFLICT: ProviderIdentityError.CONFLICTING,
    }


# ── Name normalization ────────────────────────────────────────────────────────
#
# WHAT IS NORMALIZED AND WHAT IS NOT. Everything below removes a difference in
# HOW A NAME IS WRITTEN: accents, apostrophes, periods, hyphens, casing, spacing,
# and the generational suffix one provider prints and the other does not. Nothing
# below removes a difference in WHO IS NAMED. No token is dropped, no name is
# truncated to an initial, and no two distinct spellings of two distinct names
# are ever folded together.
#
# THE SUFFIX IS SEPARATED, NOT DELETED. Yahoo prints "Tyrone Tracy Jr." and
# BALLDONTLIE splits it into "Tyrone" + "Tracy Jr."; both must reach the same
# core. But a suffix is also the ONLY thing distinguishing a father from a son,
# so it is kept alongside the core and used to break a tie the core cannot —
# never to require a match the core already made.

_SUFFIXES = frozenset({"JR", "SR", "II", "III", "IV", "V"})

#: Characters that are punctuation INSIDE a name — removed, joining the parts.
#: "D'Andre" -> "dandre", "A.J." -> "aj", "St." -> "st".
_JOINING_PUNCTUATION = re.compile(r"[’'`.]")

#: Characters that SEPARATE name parts — replaced with a space.
#: "Amon-Ra" -> "amon ra", "Clyde Edwards-Helaire" -> "clyde edwards helaire".
_SEPARATING_PUNCTUATION = re.compile(r"[-–—_/\\,]+")

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class NormalizedName:
    """A name reduced to the two things that may be compared."""

    core: str            # "tyrone tracy" — every token but a trailing suffix
    suffix: str          # "jr", or "" when the name carries none
    display: str         # the input, whitespace-collapsed, for messages

    @property
    def full(self) -> str:
        return f"{self.core} {self.suffix}".strip()


def normalize_person_name(name: str | None) -> NormalizedName:
    """Fold away how a name is WRITTEN, keeping everything about who it names."""
    raw = _WHITESPACE.sub(" ", (name or "").strip())
    if not raw:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN,
            "empty player name. A name is not identity here, but it is the "
            "only thing discovery can start from; refusing to search on "
            "nothing.")

    # NFKD then drop combining marks: "José" -> "Jose", one code point per letter
    # so the comparison does not depend on which provider composed its accents.
    folded = "".join(c for c in unicodedata.normalize("NFKD", raw)
                     if not unicodedata.combining(c))
    folded = _JOINING_PUNCTUATION.sub("", folded)
    folded = _SEPARATING_PUNCTUATION.sub(" ", folded)
    tokens = [t for t in _WHITESPACE.sub(" ", folded).strip().lower().split(" ") if t]
    if not tokens:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN,
            f"player name {raw!r} normalizes to nothing — it is entirely "
            f"punctuation. Refusing to search on it.")

    suffix = ""
    # A trailing suffix is only stripped while at least two tokens remain, so a
    # name that IS a suffix-looking token cannot be normalized out of existence.
    if len(tokens) >= 3 and tokens[-1].upper() in _SUFFIXES:
        suffix = tokens.pop().lower()

    return NormalizedName(core=" ".join(tokens), suffix=suffix, display=raw)


# ── The two sides ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CanonicalSubject:
    """A FantasyStakes subject — one `players` row, reduced to identity terms.

    `player_id` is the canonical identity and the only durable field here.
    `name`, `position` and `nfl_team` are DISCOVERY INPUTS: read once, when no
    mapping exists yet, and never again.
    """

    player_id: int | None
    name: str
    position: str               # canonical
    nfl_team: str | None        # canonical; None only for a free agent
    provider: str | None = None
    provider_player_key: str | None = None

    @property
    def is_team_defense(self) -> bool:
        return self.position == TEAM_DEFENSE

    @property
    def normalized(self) -> NormalizedName:
        return normalize_person_name(self.name)


@dataclass(frozen=True)
class ProviderSubject:
    """One subject as the far provider states it.

    `provider_player_key` is namespaced ("bdl.p.882", "bdl.dst.WSH") rather than
    a bare integer for the same reason `provider_player_key` on `players` carries
    Yahoo's game segment: a bare id is only unique inside the namespace that
    issued it, and this column will hold more than one provider's ids.

    `positions` is a SET, not a value. BALLDONTLIE contradicts itself inside one
    payload — a kicker's fantasy row says K while his player object says PK, and
    twelve fullbacks are filed under RB while labelled FB — so a subject is
    recorded as matching every canonical position the provider assigned it. That
    is precision, not looseness: each entry is a position the provider actually
    stated, and a position it did not state still fails to match.
    """

    provider: str
    provider_player_key: str
    name: str
    positions: frozenset[str]
    nfl_team: str               # canonical
    provider_player_id: int | None = None
    provider_positions: tuple[str, ...] = ()
    is_team_defense: bool = False

    @property
    def normalized(self) -> NormalizedName | None:
        return None if self.is_team_defense else normalize_person_name(self.name)


class SubjectDirectory:
    """Every subject one provider knows about, indexed the three ways discovery asks.

    NOT A CLIENT. It is handed a list of already-fetched subjects and holds no
    key, opens no socket and knows nothing about HTTP — WP2 owns the transport.
    Building it from a committed fixture is what makes every identity test in
    this WP deterministic and offline.

    THE INDEXES ARE LISTS, NEVER SINGLE VALUES. A dict of key -> subject would
    silently keep whichever of two colliding subjects was inserted last, which is
    precisely the "never silently pick one" failure this module exists to stop.
    Collisions are preserved so they can be REPORTED as AMBIGUOUS.
    """

    def __init__(self, provider: str, subjects: list[ProviderSubject]) -> None:
        self.provider = provider
        self._by_key: dict[str, ProviderSubject] = {}
        self._by_core_team_pos: dict[tuple, list[ProviderSubject]] = {}
        self._by_core_pos: dict[tuple, list[ProviderSubject]] = {}
        self._defense_by_team: dict[str, list[ProviderSubject]] = {}

        for subject in subjects:
            if subject.provider != provider:
                raise ProviderIdentityError(
                    ProviderIdentityError.CONFLICTING,
                    f"subject {subject.provider_player_key!r} carries provider "
                    f"{subject.provider!r} in a {provider!r} directory. One "
                    f"directory is one provider's namespace.")
            if subject.provider_player_key in self._by_key:
                raise ProviderIdentityError(
                    ProviderIdentityError.AMBIGUOUS,
                    f"provider key {subject.provider_player_key!r} appears "
                    f"twice in the {provider!r} directory. A provider key is "
                    f"the provider's own identity for a subject; two rows "
                    f"claiming it means the source is corrupt.")
            self._by_key[subject.provider_player_key] = subject

            if subject.is_team_defense:
                self._defense_by_team.setdefault(subject.nfl_team, []).append(subject)
                continue

            norm = subject.normalized
            for position in subject.positions:
                self._by_core_team_pos.setdefault(
                    (norm.core, subject.nfl_team, position), []).append(subject)
                self._by_core_pos.setdefault(
                    (norm.core, position), []).append(subject)

    def __len__(self) -> int:
        return len(self._by_key)

    def __repr__(self) -> str:
        return (f"<SubjectDirectory {self.provider} "
                f"{len(self._by_key)} subjects, "
                f"{len(self._defense_by_team)} team defenses>")

    @property
    def subjects(self) -> tuple[ProviderSubject, ...]:
        return tuple(self._by_key.values())

    def by_key(self, provider_player_key: str) -> ProviderSubject | None:
        return self._by_key.get(provider_player_key)

    def defenses_for(self, nfl_team: str) -> list[ProviderSubject]:
        return list(self._defense_by_team.get(nfl_team, ()))

    def by_core_team_position(self, core: str, nfl_team: str,
                              position: str) -> list[ProviderSubject]:
        return list(self._by_core_team_pos.get((core, nfl_team, position), ()))

    def by_core_position(self, core: str, position: str) -> list[ProviderSubject]:
        return list(self._by_core_pos.get((core, position), ()))


# ── The result ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CrossProviderResolution:
    """What the resolver concluded, and why.

    `subject` may be None on a RESOLVED result, and that is not a contradiction.
    Identity is the persisted alias; the directory is one week's slate. A player
    who is correctly mapped and simply did not appear that week resolves fine and
    has no subject row in THAT directory. `subject_in_directory` states it
    plainly so a facts-consuming caller can tell "unmapped" from "mapped, no data
    this week" — which are different problems with different fixes.
    """

    outcome: str
    provider: str
    canonical: CanonicalSubject
    subject: ProviderSubject | None = None
    provider_player_key: str | None = None
    method: str | None = None
    candidates: tuple[ProviderSubject, ...] = ()
    subject_in_directory: bool = False
    detail: str = ""

    @property
    def resolved(self) -> bool:
        return self.outcome == Outcome.RESOLVED

    def require(self) -> ProviderSubject | None:
        """Return the subject, or raise the repo's ProviderIdentityError.

        For a caller that must not continue — a settlement, a lock, a payout.
        The three failures keep their own reason constants all the way out, so
        an operator reading a log still sees which of the three happened.
        """
        if self.resolved:
            return self.subject
        raise ProviderIdentityError(
            Outcome.TO_IDENTITY_REASON[self.outcome], self.detail)


def _resolution(outcome: str, canonical: CanonicalSubject, provider: str,
                detail: str, **kwargs) -> CrossProviderResolution:
    return CrossProviderResolution(outcome=outcome, provider=provider,
                                   canonical=canonical, detail=detail, **kwargs)


# ── Discovery — pure, no database ─────────────────────────────────────────────


def discover(canonical: CanonicalSubject,
             directory: SubjectDirectory) -> CrossProviderResolution:
    """Find the ONE provider subject that is this canonical subject, or refuse.

    Pure: no session, no writes, no clock. `resolve_player` calls this and then
    persists what it returns; a caller that only wants to know what discovery
    WOULD say can call it directly, and the tests do.

    ── THE ORDER, AND WHY THE FALLBACK IS SAFE ───────────────────────────────

    1. TEAM DEFENSE — a DEF/DST subject has no player object at BALLDONTLIE and
       no name worth comparing. Its identity IS its team, so it is matched on the
       team alone and never touches the name path at all.
    2. CORE NAME + TEAM + POSITION — the strict pass. All three must agree.
    3. SUFFIX TIE-BREAK — only when 2 returned more than one. A father and a son
       on the same team at the same position differ by exactly the suffix, so the
       suffix decides; if it still does not, this is AMBIGUOUS.
    4. CORE NAME + POSITION, TEAM RELAXED — reached ONLY when pass 2 found ZERO.
       That precondition is what makes it safe: it can never override a
       team-confirmed match, only cover the case our stored team is stale (a
       player traded since the last roster refresh, or a free agent). Relaxing
       the team while candidates existed would let a worse match beat a better
       one, so it does not.
    5. Otherwise UNRESOLVED — never a guess.
    """
    provider = directory.provider

    if canonical.is_team_defense:
        if not canonical.nfl_team:
            return _resolution(
                Outcome.UNRESOLVED, canonical, provider,
                "a team defense carries no NFL team. Its team IS its identity, "
                "so there is nothing to resolve on.")
        found = directory.defenses_for(canonical.nfl_team)
        if len(found) == 1:
            return _resolution(
                Outcome.RESOLVED, canonical, provider,
                f"team defense matched on NFL team {canonical.nfl_team}",
                subject=found[0], provider_player_key=found[0].provider_player_key,
                method="team_defense", subject_in_directory=True)
        if len(found) > 1:
            return _resolution(
                Outcome.AMBIGUOUS, canonical, provider,
                f"{len(found)} {provider} team defenses claim NFL team "
                f"{canonical.nfl_team}: "
                f"{[s.provider_player_key for s in found]!r}. There is exactly "
                f"one defense per team; refusing to pick one.",
                candidates=tuple(found))
        return _resolution(
            Outcome.UNRESOLVED, canonical, provider,
            f"{provider} lists no team defense for NFL team "
            f"{canonical.nfl_team}.")

    norm = canonical.normalized

    if canonical.nfl_team:
        strict = directory.by_core_team_position(
            norm.core, canonical.nfl_team, canonical.position)
        if len(strict) == 1:
            return _resolution(
                Outcome.RESOLVED, canonical, provider,
                f"matched on normalized name {norm.core!r} + team "
                f"{canonical.nfl_team} + position {canonical.position}",
                subject=strict[0], provider_player_key=strict[0].provider_player_key,
                method="normalized_discovery", subject_in_directory=True)
        if len(strict) > 1:
            # A father and a son. The suffix is the only thing that separates
            # them, and it separates them exactly.
            exact = [s for s in strict if s.normalized.suffix == norm.suffix]
            if len(exact) == 1:
                return _resolution(
                    Outcome.RESOLVED, canonical, provider,
                    f"{len(strict)} subjects share normalized name "
                    f"{norm.core!r} on {canonical.nfl_team} at "
                    f"{canonical.position}; generational suffix "
                    f"{norm.suffix or '(none)'!r} separated them",
                    subject=exact[0], provider_player_key=exact[0].provider_player_key,
                    method="normalized_discovery", subject_in_directory=True)
            return _resolution(
                Outcome.AMBIGUOUS, canonical, provider,
                f"{len(strict)} {provider} subjects match normalized name "
                f"{norm.core!r} on team {canonical.nfl_team} at position "
                f"{canonical.position}: "
                f"{[(s.provider_player_key, s.name) for s in strict]!r}. "
                f"Generational suffix {norm.suffix or '(none)'!r} does not "
                f"separate them ({len(exact)} carry it). A settlement-grade "
                f"mapping is not made by picking the first row; bind it "
                f"explicitly with set_manual_alias.",
                candidates=tuple(strict))

    # CONTROLLED FALLBACK. Reached only with zero team-scoped candidates.
    relaxed = directory.by_core_position(norm.core, canonical.position)
    if len(relaxed) == 1:
        subject = relaxed[0]
        return _resolution(
            Outcome.RESOLVED, canonical, provider,
            f"no {provider} subject named {norm.core!r} plays for "
            f"{canonical.nfl_team or '(no team)'}, and exactly one plays "
            f"{canonical.position} anywhere — at {subject.nfl_team}. Our stored "
            f"team is stale (a trade, or a free agent); the identity is not.",
            subject=subject, provider_player_key=subject.provider_player_key,
            method="normalized_discovery_team_relaxed", subject_in_directory=True)
    if len(relaxed) > 1:
        return _resolution(
            Outcome.AMBIGUOUS, canonical, provider,
            f"no {provider} subject named {norm.core!r} plays for "
            f"{canonical.nfl_team or '(no team)'}, and {len(relaxed)} play "
            f"{canonical.position} elsewhere: "
            f"{[(s.provider_player_key, s.name, s.nfl_team) for s in relaxed]!r}. "
            f"Without the team there is nothing left to separate them.",
            candidates=tuple(relaxed))

    return _resolution(
        Outcome.UNRESOLVED, canonical, provider,
        f"{provider} lists no subject with normalized name {norm.core!r} at "
        f"position {canonical.position} (team {canonical.nfl_team or 'unknown'}). "
        f"The subject is absent from this directory — a rookie not yet ingested, "
        f"a retired player, or a name this provider spells differently in a way "
        f"normalization does not reach. Bind it with set_manual_alias if it is "
        f"the third.")


def suggest_candidates(canonical: CanonicalSubject, directory: SubjectDirectory,
                       *, limit: int = 10) -> tuple[ProviderSubject, ...]:
    """Near-misses for an OPERATOR to read. Never called by the resolver.

    THIS IS THE ONLY LOOSE COMPARISON IN THE MODULE AND IT BINDS NOTHING. It
    exists so a person triaging an UNRESOLVED subject does not have to grep a
    directory by hand. It is deliberately not wired into `discover`: making it
    reachable from the automatic path is exactly how a similarity score becomes
    settlement evidence.
    """
    if canonical.is_team_defense:
        return tuple(directory.defenses_for(canonical.nfl_team or ""))
    norm = canonical.normalized
    surname = norm.core.rsplit(" ", 1)[-1]
    out = []
    for subject in directory.subjects:
        if subject.is_team_defense:
            continue
        other = subject.normalized
        shares_surname = other.core.rsplit(" ", 1)[-1] == surname
        shares_team = subject.nfl_team == canonical.nfl_team
        if shares_surname or (shares_team and canonical.position in subject.positions
                              and other.core.split(" ")[0] == norm.core.split(" ")[0]):
            out.append(subject)
        if len(out) >= limit:
            break
    return tuple(out)


# ── Persistence — the alias table ─────────────────────────────────────────────


def canonical_subject_from_player(player) -> CanonicalSubject:
    """A `players` row -> the identity terms discovery needs.

    The team and position are canonicalized THROUGH `providers.nfl_teams`, so a
    row still holding a Yahoo-dialect abbreviation resolves against a canonical
    directory. A row holding an abbreviation no dialect knows raises here rather
    than searching on a spelling that can only miss.
    """
    nfl_team = None
    if player.nfl_team:
        # `players.nfl_team` was written by two paths across the repo's history:
        # the FR-7.30 roster path, which copies Yahoo's editorial_team_abbr, and
        # scripts/backfill_nfl_teams.py, which wrote canonical. The Yahoo dialect
        # is a superset of canonical, so reading it through the Yahoo dialect
        # accepts both without changing either.
        nfl_team = to_canonical_team(player.nfl_team, dialect="yahoo")
    return CanonicalSubject(
        player_id=player.id,
        name=player.name,
        position=canonical_position(player.position),
        nfl_team=nfl_team,
        provider=player.provider,
        provider_player_key=player.provider_player_key,
    )


def lookup_alias(db, *, provider: str, player_id: int | None = None,
                 provider_player_key: str | None = None,
                 include_retired: bool = False) -> list:
    """Every alias row matching either side of the mapping."""
    from db.schema import ProviderPlayerAlias

    if player_id is None and provider_player_key is None:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN,
            "lookup_alias needs a player_id or a provider_player_key.")
    query = db.query(ProviderPlayerAlias).filter(
        ProviderPlayerAlias.provider == provider)
    if player_id is not None:
        query = query.filter(ProviderPlayerAlias.player_id == player_id)
    if provider_player_key is not None:
        query = query.filter(
            ProviderPlayerAlias.provider_player_key == provider_player_key)
    if not include_retired:
        query = query.filter(
            ProviderPlayerAlias.status == ProviderPlayerAlias.STATUS_ACTIVE)
    return query.order_by(ProviderPlayerAlias.id).all()


def _persisted(db, canonical: CanonicalSubject, directory: SubjectDirectory,
               provider: str) -> CrossProviderResolution | None:
    """Step 1 — the stored mapping, and every way it can disagree with itself.

    Returns None when there is nothing stored, so the caller falls through to
    discovery. Returns a CONFLICT (never a guess) when what is stored is not a
    single coherent answer.
    """
    from db.schema import ProviderPlayerAlias

    by_player = lookup_alias(db, provider=provider, player_id=canonical.player_id)
    if len(by_player) > 1:
        return _resolution(
            Outcome.CONFLICT, canonical, provider,
            f"player {canonical.player_id} carries {len(by_player)} ACTIVE "
            f"{provider} aliases "
            f"({[(a.id, a.provider_player_key) for a in by_player]!r}). "
            f"uq_provider_player_alias_active_player should make this "
            f"unreachable, so the constraint is absent or was dropped. "
            f"Refusing to pick one.",
            candidates=())
    if not by_player:
        return None

    alias = by_player[0]

    # The stored key must still belong to THIS player at the far provider.
    by_key = lookup_alias(db, provider=provider,
                          provider_player_key=alias.provider_player_key)
    other = [a for a in by_key if a.player_id != canonical.player_id]
    if other:
        return _resolution(
            Outcome.CONFLICT, canonical, provider,
            f"{provider} key {alias.provider_player_key!r} is mapped to player "
            f"{canonical.player_id} AND to player(s) "
            f"{[a.player_id for a in other]!r}. One provider subject is one "
            f"canonical player; two claims on it means one of them settles a "
            f"wager against the wrong stat line.")

    # A key our own Player rows claim natively as a DIFFERENT player is the
    # same corruption arriving from the other direction.
    from db.schema import Player
    native = (db.query(Player)
              .filter(Player.provider == provider,
                      Player.provider_player_key == alias.provider_player_key,
                      Player.id != canonical.player_id)
              .first())
    if native is not None:
        return _resolution(
            Outcome.CONFLICT, canonical, provider,
            f"{provider} key {alias.provider_player_key!r} is aliased to player "
            f"{canonical.player_id} but is ALSO the native provider identity of "
            f"player {native.id}. The alias table and `players` disagree about "
            f"who that subject is.")

    subject = directory.by_key(alias.provider_player_key)
    return _resolution(
        Outcome.RESOLVED, canonical, provider,
        f"persisted alias {alias.id} (method {alias.method}"
        f"{', manual override' if alias.manual_override else ''}). "
        f"Neither the name nor the team was consulted."
        + ("" if subject is not None else
           f" The subject is absent from this directory, which is ordinary — "
           f"the mapping is the identity, the directory is one slate."),
        subject=subject, provider_player_key=alias.provider_player_key,
        method=ProviderPlayerAlias.METHOD_MANUAL if alias.manual_override
        else alias.method,
        subject_in_directory=subject is not None)


def resolve_player(db, player, directory: SubjectDirectory, *,
                   provider: str = BALLDONTLIE,
                   persist: bool = True) -> CrossProviderResolution:
    """A `players` row -> the far provider's subject. The whole WP1 entry point.

    Order, and each step's reason:

      1. THE PERSISTED MAPPING, before anything else is read. This is what makes
         a trade, a rename, a position change and a suffix correction all
         non-events: none of them is consulted once a mapping exists.
      2. THE FAR PROVIDER'S OWN IDENTIFIER, when the row already carries one.
      3. DETERMINISTIC DISCOVERY, via `discover`.
      4. Anything else fails closed with its own named outcome.

    `persist=False` runs the identical decision and writes nothing — for a
    dry-run sweep that wants the counts before anything is committed.
    """
    from db.schema import ProviderPlayerAlias

    canonical = canonical_subject_from_player(player)

    if canonical.player_id is None:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN,
            "cannot resolve a Player that has not been flushed — it has no id, "
            "so there is nothing for an alias to point at.")

    stored = _persisted(db, canonical, directory, provider)
    if stored is not None:
        if stored.resolved and stored.subject is not None and persist:
            _refresh_observations(db, provider, canonical.player_id, stored.subject)
        return stored

    # Step 2 — the far provider's own id, already on the row.
    if canonical.provider == provider and canonical.provider_player_key:
        subject = directory.by_key(canonical.provider_player_key)
        if subject is not None:
            result = _resolution(
                Outcome.RESOLVED, canonical, provider,
                f"the player row already carries {provider} key "
                f"{canonical.provider_player_key!r}; no name was consulted",
                subject=subject,
                provider_player_key=canonical.provider_player_key,
                method=ProviderPlayerAlias.METHOD_PROVIDER_ID,
                subject_in_directory=True)
            return _persist(db, result) if persist else result

    result = discover(canonical, directory)
    if not result.resolved:
        return result

    method = {
        "team_defense": ProviderPlayerAlias.METHOD_TEAM_DEFENSE,
        "normalized_discovery": ProviderPlayerAlias.METHOD_DISCOVERY,
        "normalized_discovery_team_relaxed":
            ProviderPlayerAlias.METHOD_DISCOVERY_RELAXED,
    }[result.method]
    result = CrossProviderResolution(
        outcome=result.outcome, provider=result.provider,
        canonical=result.canonical, subject=result.subject,
        provider_player_key=result.provider_player_key, method=method,
        candidates=result.candidates,
        subject_in_directory=result.subject_in_directory, detail=result.detail)
    return _persist(db, result) if persist else result


def _persist(db, result: CrossProviderResolution) -> CrossProviderResolution:
    """Write the mapping a resolution just discovered. Refuses to overwrite."""
    bind_alias(db, provider=result.provider,
               player_id=result.canonical.player_id,
               provider_player_key=result.provider_player_key,
               method=result.method,
               provider_position=(result.subject.provider_positions[0]
                                  if result.subject
                                  and result.subject.provider_positions else None),
               provider_nfl_team=result.subject.nfl_team if result.subject else None)
    return result


def _refresh_observations(db, provider: str, player_id: int,
                          subject: ProviderSubject) -> None:
    """Update what the provider currently SAYS about a mapped subject.

    Never touches `player_id` or `provider_player_key`. This is the trade case:
    the observation moves, the identity does not.
    """
    from db.schema import ProviderPlayerAlias

    alias = (db.query(ProviderPlayerAlias)
             .filter(ProviderPlayerAlias.provider == provider,
                     ProviderPlayerAlias.player_id == player_id,
                     ProviderPlayerAlias.status ==
                     ProviderPlayerAlias.STATUS_ACTIVE)
             .first())
    if alias is None:
        return
    position = (subject.provider_positions[0]
                if subject.provider_positions else None)
    if alias.provider_nfl_team != subject.nfl_team or \
            alias.provider_position != position:
        alias.provider_nfl_team = subject.nfl_team
        alias.provider_position = position
        alias.updated_at = datetime.now(timezone.utc)
        db.flush()


def bind_alias(db, *, provider: str, player_id: int, provider_player_key: str,
               method: str, provider_position: str | None = None,
               provider_nfl_team: str | None = None,
               manual_override: bool = False):
    """Create the mapping. REBINDING IS A CONFLICT, NOT AN UPDATE.

    Mirrors `providers.identity.bind_team_identity` deliberately: the same
    refusal, for the same reason. A mapping that is silently repointed makes
    every fact already attached under the old one retroactively about somebody
    else, and there is no record afterwards that it ever changed.

    A RETIRED ROW STILL BLOCKS. That is what guards against provider id reuse:
    the key stays occupied after retirement, so an automatic rebind refuses and
    only `set_manual_alias` — a human, on the record — can move it.
    """
    from db.schema import ProviderPlayerAlias

    existing_player = lookup_alias(db, provider=provider, player_id=player_id,
                                   include_retired=True)
    active_player = [a for a in existing_player
                     if a.status == ProviderPlayerAlias.STATUS_ACTIVE]
    if active_player:
        alias = active_player[0]
        if alias.provider_player_key == provider_player_key:
            return alias
        raise ProviderIdentityError(
            ProviderIdentityError.CONFLICTING,
            f"player {player_id} is already mapped to {provider} key "
            f"{alias.provider_player_key!r}; refusing to rebind it to "
            f"{provider_player_key!r}. Every fact already attached under the "
            f"old key would become a fact about someone else, with no record "
            f"that it moved. Retire the mapping explicitly, or assert the new "
            f"one with set_manual_alias.")

    existing_key = lookup_alias(db, provider=provider,
                                provider_player_key=provider_player_key,
                                include_retired=True)
    if existing_key:
        alias = existing_key[0]
        raise ProviderIdentityError(
            ProviderIdentityError.CONFLICTING,
            f"{provider} key {provider_player_key!r} is already bound to player "
            f"{alias.player_id} (status {alias.status}); refusing to bind it to "
            f"player {player_id} as well. One provider subject is one canonical "
            f"player. A RETIRED row deliberately keeps the key occupied — that "
            f"is the guard against a provider reusing an identifier.")

    alias = ProviderPlayerAlias(
        provider=provider,
        provider_player_key=provider_player_key,
        player_id=player_id,
        provider_position=provider_position,
        provider_nfl_team=provider_nfl_team,
        status=ProviderPlayerAlias.STATUS_ACTIVE,
        method=method,
        manual_override=manual_override,
    )
    db.add(alias)
    db.flush()
    return alias


def retire_alias(db, *, provider: str, player_id: int, reason: str = ""):
    """Mark a mapping RETIRED. The row stays, and so does its hold on the key."""
    from db.schema import ProviderPlayerAlias

    rows = lookup_alias(db, provider=provider, player_id=player_id)
    if not rows:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN,
            f"player {player_id} has no ACTIVE {provider} alias to retire.")
    alias = rows[0]
    alias.status = ProviderPlayerAlias.STATUS_RETIRED
    alias.updated_at = datetime.now(timezone.utc)
    db.flush()
    return alias


def set_manual_alias(db, *, provider: str, player_id: int,
                     provider_player_key: str,
                     provider_position: str | None = None,
                     provider_nfl_team: str | None = None):
    """An operator asserts a mapping the resolver refused to make.

    THE ONLY PATH THAT MAY MOVE AN EXISTING MAPPING, and it leaves the evidence
    on the row: `manual_override` is True and `method` is 'manual' forever after,
    so a later audit can separate what a person decided from what the resolver
    derived. Nothing automatic reaches this function.

    An existing mapping for this player is RETIRED rather than edited, so the
    old key stays occupied and cannot be picked up again by discovery.
    """
    from db.schema import ProviderPlayerAlias

    current = lookup_alias(db, provider=provider, player_id=player_id)
    if current and current[0].provider_player_key == provider_player_key:
        alias = current[0]
        alias.manual_override = True
        alias.method = ProviderPlayerAlias.METHOD_MANUAL
        alias.updated_at = datetime.now(timezone.utc)
        db.flush()
        return alias

    claimed = lookup_alias(db, provider=provider,
                           provider_player_key=provider_player_key,
                           include_retired=True)
    conflicting = [a for a in claimed if a.player_id != player_id]
    if conflicting:
        raise ProviderIdentityError(
            ProviderIdentityError.CONFLICTING,
            f"{provider} key {provider_player_key!r} is held by player "
            f"{conflicting[0].player_id} (status {conflicting[0].status}). "
            f"Retire that mapping first; a manual override may move ONE "
            f"player's mapping, never take a subject away from another player "
            f"without that being said out loud.")

    if current:
        retire_alias(db, provider=provider, player_id=player_id)

    # A previously retired row for this same pair is revived rather than
    # duplicated — the unique constraint holds either way, and one row per pair
    # keeps the history readable.
    revived = [a for a in claimed if a.player_id == player_id]
    if revived:
        alias = revived[0]
        alias.status = ProviderPlayerAlias.STATUS_ACTIVE
        alias.method = ProviderPlayerAlias.METHOD_MANUAL
        alias.manual_override = True
        alias.provider_position = provider_position or alias.provider_position
        alias.provider_nfl_team = provider_nfl_team or alias.provider_nfl_team
        alias.updated_at = datetime.now(timezone.utc)
        db.flush()
        return alias

    return bind_alias(db, provider=provider, player_id=player_id,
                      provider_player_key=provider_player_key,
                      method=ProviderPlayerAlias.METHOD_MANUAL,
                      provider_position=provider_position,
                      provider_nfl_team=provider_nfl_team,
                      manual_override=True)
