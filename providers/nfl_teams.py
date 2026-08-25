"""Canonical NFL team identity, and the provider dialects that spell it wrong.

WP1 — WHY THIS IS A REGISTRY AND NOT A MAPPING TABLE. `providers/identity.py`
refuses to resolve a fantasy team by anything but a persisted provider key,
because a fantasy team is league-scoped, renameable, and there are as many of
them as the product has leagues. An NFL team is none of those things: there are
thirty-two, the set has not changed since 2002, and every provider names them
with the same three-letter idea spelled slightly differently. That is a closed
enumeration, so it belongs in code where a reviewer can read all of it at once
and a diff shows exactly which abbreviation moved — not in a table that could be
half-seeded on one deployment and fully seeded on another.

THE CANONICAL DIALECT IS THE ONE ALREADY IN THE DATABASE. `nfl_schedule` stores
ESPN abbreviations, `seed_nfl_schedule_from_csv.py` normalizes WAS -> WSH on the
way in, and `scripts/backfill_nfl_teams.py` wrote `players.nfl_team` in the same
dialect. Choosing anything else for WP1 would have meant rewriting rows that are
already correct, so canonical here means EXACTLY what those two already mean.

BALLDONTLIE AGREES WITH CANONICAL ON ALL THIRTY-TWO. That was measured, not
assumed: the Phase 0 capture carries all thirty-two abbreviations and every one
of them is already the canonical spelling, WSH and JAX included. So the BDL
dialect table below is deliberately EMPTY of exceptions, and the equality is
asserted by a test rather than trusted.

YAHOO DIFFERS ON EXACTLY ONE, TODAY. Yahoo's `editorial_team_abbr` says WAS
where canonical says WSH. The rest of the Yahoo entries below are RELOCATION AND
LEGACY spellings (SD, OAK, STL, LA, JAC, ARZ...) that a historical payload or an
older feed can still carry. They are listed because a silent miss on one of them
resolves a player to the wrong franchise, and `to_canonical` refuses an unknown
abbreviation rather than passing it through.

WHY `to_canonical` REFUSES INSTEAD OF ECHOING. An unrecognised abbreviation
echoed back looks, one layer up, exactly like a recognised one. It would then
flow into a discovery key, match nothing, and surface as "this player does not
exist at BALLDONTLIE" — a wrong diagnosis of a spelling problem. The refusal
names the abbreviation and the dialect instead.

DEF AND DST ARE THE SAME POSITION. Yahoo calls a team defense DEF, BALLDONTLIE
calls it DST, and both mean the one fantasy subject that has a team but no
player. Canonical is DEF, because `Player.position` has said DEF since Sprint 1
and every roster row already written spells it that way.
"""

from __future__ import annotations

from providers.errors import ProviderIdentityError

__all__ = [
    "CANONICAL_NFL_TEAMS",
    "CANONICAL_POSITIONS",
    "TEAM_DEFENSE",
    "canonical_position",
    "is_team_defense",
    "to_canonical_team",
]


#: The thirty-two canonical NFL team abbreviations. ESPN dialect, which is what
#: `nfl_schedule` and `players.nfl_team` already hold.
CANONICAL_NFL_TEAMS: frozenset[str] = frozenset({
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB",  "HOU", "IND", "JAX", "KC",
    "LAC", "LAR", "LV",  "MIA", "MIN", "NE",  "NO",  "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF",  "TB",  "TEN", "WSH",
})


#: Per-dialect exceptions: what the provider writes -> what we store. Only the
#: DIFFERENCES appear here; anything already canonical needs no entry, and
#: `to_canonical_team` checks the canonical set first.
_DIALECTS: dict[str, dict[str, str]] = {
    # Yahoo `editorial_team_abbr`. WAS is the one live difference; the rest are
    # relocation and legacy spellings a historical payload can still carry.
    "yahoo": {
        "WAS": "WSH",   # live difference — Yahoo has never adopted WSH
        "JAC": "JAX",
        "ARZ": "ARI",
        "LA":  "LAR",   # pre-2020 Rams, before the Chargers forced LAR/LAC
        "SD":  "LAC",   # San Diego Chargers
        "OAK": "LV",    # Oakland Raiders
        "STL": "LAR",   # St. Louis Rams
        "HST": "HOU",
        "BLT": "BAL",
        "CLV": "CLE",
        "GNB": "GB",
        "KAN": "KC",
        "NWE": "NE",
        "NOR": "NO",
        "SFO": "SF",
        "TAM": "TB",
    },
    # BALLDONTLIE NFL v1. Measured against the Phase 0 capture: all thirty-two
    # abbreviations are already canonical, so there is nothing to except. The
    # entry exists so the dialect is a NAMED, asserted fact rather than an
    # unstated assumption that BDL happens to agree.
    "balldontlie": {},
    # DynastyProcess `db_playerids.csv`, already used by
    # scripts/backfill_nfl_teams.py. Reproduced here so the two agree by
    # construction rather than by coincidence.
    "dynastyprocess": {
        "GBP": "GB",  "JAC": "JAX", "KCC": "KC", "LVR": "LV",
        "NEP": "NE",  "NOS": "NO",  "SFO": "SF", "TBB": "TB",
        "WAS": "WSH",
    },
    # The season-schedule CSV, whose WAS -> WSH normalization
    # seed_nfl_schedule_from_csv.py already performs on ingest.
    "schedule_csv": {"WAS": "WSH"},
}


#: Canonical fantasy positions. FLEX is a LINEUP SLOT and never a subject's
#: position, so it is deliberately absent: a subject whose position resolved to
#: FLEX could not be matched against a provider that only ever states a real one.
CANONICAL_POSITIONS: frozenset[str] = frozenset(
    {"QB", "RB", "WR", "TE", "K", "DEF"})

#: The canonical spelling of a team defense.
TEAM_DEFENSE = "DEF"


#: Provider position label -> canonical position. Only the differences.
_POSITION_DIALECT: dict[str, str] = {
    # Kickers. Yahoo's roster feed says K; BALLDONTLIE's fantasy row says K but
    # its PLAYER OBJECT says PK, and the two disagree inside one payload. Both
    # are the same position.
    "PK": "K",
    "PLACE KICKER": "K",
    "KICKER": "K",
    # Team defenses, every spelling any of the three sources uses.
    "DST": "DEF",
    "D/ST": "DEF",
    "DEF": "DEF",
    "D": "DEF",
    "TEAM DEFENSE": "DEF",
    "DEFENSE": "DEF",
    # Fullbacks are RBs for every fantasy purpose. BALLDONTLIE labels twelve of
    # them FB on the player object while filing their fantasy row under RB.
    "FB": "RB",
    "FULLBACK": "RB",
    # Long-form labels BALLDONTLIE uses on `player.position`.
    "QUARTERBACK": "QB",
    "RUNNING BACK": "RB",
    "WIDE RECEIVER": "WR",
    "TIGHT END": "TE",
}


def to_canonical_team(abbreviation: str | None, *, dialect: str) -> str:
    """Provider NFL team abbreviation -> canonical. Fails closed on unknown.

    `dialect` is required and has no default, for the same reason `provider` is
    required in providers/identity.py: a caller that forgot it would silently
    ask for someone else's spelling rules and get a plausible-looking answer.
    """
    if dialect not in _DIALECTS:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN,
            f"no NFL team dialect named {dialect!r}. Known dialects: "
            f"{sorted(_DIALECTS)!r}.")

    raw = (abbreviation or "").strip().upper()
    if not raw:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN,
            f"empty NFL team abbreviation in dialect {dialect!r}. A subject "
            f"with no team cannot be resolved against a provider that keys "
            f"every subject by one; refusing to guess.")

    if raw in CANONICAL_NFL_TEAMS:
        return raw

    mapped = _DIALECTS[dialect].get(raw)
    if mapped is not None:
        return mapped

    raise ProviderIdentityError(
        ProviderIdentityError.UNKNOWN,
        f"NFL team abbreviation {raw!r} is not canonical and dialect "
        f"{dialect!r} declares no translation for it. Refusing to pass it "
        f"through: an unrecognised abbreviation that is echoed back matches "
        f"nothing downstream and reports as a missing player rather than as "
        f"the spelling problem it is.")


def canonical_position(position: str | None) -> str:
    """Provider position label -> canonical position. Fails closed on unknown."""
    raw = (position or "").strip().upper()
    if not raw:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN,
            "empty position. Position is part of the discovery key; refusing "
            "to treat 'unstated' as 'matches anything'.")
    if raw in CANONICAL_POSITIONS:
        return raw
    mapped = _POSITION_DIALECT.get(raw)
    if mapped is not None:
        return mapped
    raise ProviderIdentityError(
        ProviderIdentityError.UNKNOWN,
        f"position {raw!r} maps to no canonical fantasy position "
        f"{sorted(CANONICAL_POSITIONS)!r}. Refusing to pass it through.")


def is_team_defense(position: str | None) -> bool:
    """True for every spelling of a team defense, across every provider."""
    try:
        return canonical_position(position) == TEAM_DEFENSE
    except ProviderIdentityError:
        return False
