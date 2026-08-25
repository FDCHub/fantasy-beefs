"""WP2 · BALLDONTLIE payload parsing. Payload in, plain typed rows out.

THIS IS THE ONLY MODULE THAT KNOWS BALLDONTLIE'S ENVELOPE. After it, the shape
of the API stops mattering. Its envelope is mercifully ordinary — a JSON object
with `data` and `meta`, real arrays, real numbers — which is why this module is
a third the size of the Yahoo parser and why almost all of WP2's difficulty
lives one layer up in `normalize.py` instead.

── WHAT THIS MODULE MUST NOT DO, AND WHY IT IS TEMPTING ────────────────────

IT MUST NOT INTERPRET AN ABSENT STAT. BALLDONTLIE omits every zero-valued field:
25 of the 34 week-1 kickers carried no `field_goals_missed` key at all, and all
25 had perfect days. Reading "absent means 0.0" here would be right for those 25
and catastrophic for a row that is absent because the player has no data at all.
The distinction between a zero and a gap is a RULE, it is Phase 0F's first rule,
and it is made in `normalize.py` where it can be stated once and gated.

IT MUST NOT DROP A ROW IT CANNOT READ. A parser that skips an unreadable row
silently shrinks a week, and a shrunken week is indistinguishable from a quiet
provider outage. Every refusal here is a ProviderParseError.

IT MUST NOT SORT PLAYS. Play order is not guaranteed and ids are non-monotonic
(Phase 0F), but ordering them is a rule with a reason — sort by wallclock — and
belongs with the other rules.

── THE SHAPES, AND WHERE THEY CAME FROM ────────────────────────────────────

Every field read below was OBSERVED in the Phase 0 acceptance test across 117
live requests against `/nfl/v1`, and is documented in the diligence report that
test produced. What that does NOT establish is that the live payload still looks
this way today; only a CAPTURED fixture settles that, and this repository holds
none for BALLDONTLIE. The synthetic corpus is built to these shapes precisely so
the work this layer does is real even though the bytes are not — the same
position `providers/yahoo/parse.py` documents for Yahoo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from providers.errors import ProviderParseError

__all__ = [
    "GameRow",
    "PlayRow",
    "WeeklyStatRow",
    "envelope",
    "parse_games",
    "parse_plays",
    "parse_players",
    "parse_teams",
    "parse_weekly_stats",
]


def _require(mapping: Any, key: str, context: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        present = (sorted(mapping) if isinstance(mapping, dict)
                   else type(mapping).__name__)
        raise ProviderParseError(
            f"{context} is missing required field {key!r}. Present: "
            f"{present!r}.")
    return mapping[key]


def _optional_number(value: Any) -> float | None:
    """A number, or None. NEVER 0.0 for an absent value — see the docstring."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ProviderParseError(f"expected a number, got the boolean {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ProviderParseError(
            f"expected a number or null, got {value!r}") from exc


def envelope(payload: Any, *, context: str = "payload") -> tuple[list, dict]:
    """`{"data": [...], "meta": {...}}` -> (rows, meta). Fails closed.

    `meta` is optional in practice on single-object responses and is returned as
    an empty dict rather than None, so a caller reading `next_cursor` does not
    have to branch on whether the server bothered to send pagination metadata.
    """
    if not isinstance(payload, dict):
        raise ProviderParseError(
            f"{context}: expected a JSON object, got {type(payload).__name__}.")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ProviderParseError(
            f"{context}: expected a list under 'data', got "
            f"{type(data).__name__}. Keys present: {sorted(payload)!r}.")
    meta = payload.get("meta")
    return data, meta if isinstance(meta, dict) else {}


# ── fantasy/weekly_stats ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class WeeklyStatRow:
    """One subject's finalized weekly fantasy row, exactly as reported.

    `stats` IS THE PROVIDER'S OWN DICT, UNTOUCHED. Absent keys stay absent and
    an empty dict stays empty, because those two states mean different things
    and only `normalize.py` is allowed to say which. `stats_present` records
    whether the row carried a `stats` object AT ALL, which is the third state —
    a malformed row — and is refused rather than folded into either.

    `player` is None for a team defense: BALLDONTLIE keys a DST row by team and
    issues no player object for it. That is not a defect in the row and must not
    be read as a missing player.
    """

    season: int
    week: int
    team: Mapping[str, Any]
    player: Mapping[str, Any] | None
    position: str | None
    stats: Mapping[str, Any]
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    @property
    def is_team_defense(self) -> bool:
        return self.player is None

    @property
    def player_id(self) -> int | None:
        return None if self.player is None else self.player.get("id")

    @property
    def team_abbreviation(self) -> str | None:
        return (self.team or {}).get("abbreviation")


def parse_weekly_stats(payload: Any) -> list[WeeklyStatRow]:
    """`/fantasy/weekly_stats` -> rows. The settlement-grade summary source."""
    rows, _ = envelope(payload, context="fantasy/weekly_stats")
    parsed: list[WeeklyStatRow] = []
    for index, row in enumerate(rows):
        context = f"fantasy/weekly_stats row {index}"
        if not isinstance(row, dict):
            raise ProviderParseError(
                f"{context}: expected an object, got {type(row).__name__}.")
        team = row.get("team")
        if not isinstance(team, dict):
            raise ProviderParseError(
                f"{context}: every fantasy row carries a team, including a "
                f"team defense, which has nothing else to be keyed by. Got "
                f"{type(team).__name__}.")
        stats = row.get("stats")
        if stats is None or not isinstance(stats, dict):
            raise ProviderParseError(
                f"{context}: 'stats' must be an object. An EMPTY object is "
                f"valid and means a real zero — a player who did not play — "
                f"but an absent or non-object 'stats' is a malformed row, and "
                f"reading it as a zero would invent a performance. Got "
                f"{type(stats).__name__}.")
        player = row.get("player")
        if player is not None and not isinstance(player, dict):
            raise ProviderParseError(
                f"{context}: 'player' must be an object or null (null means "
                f"team defense). Got {type(player).__name__}.")
        parsed.append(WeeklyStatRow(
            season=int(_require(row, "season", context)),
            week=int(_require(row, "week", context)),
            team=team,
            player=player,
            position=row.get("position"),
            stats=stats,
            raw=row,
        ))
    return parsed


# ── games ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GameRow:
    """One game. The scores here are the ONLY authority for a final score.

    `period_scores` is carried for display and audit and is deliberately awkward
    to sum: BALLDONTLIE writes `null` for a scoreless quarter, so a naive sum
    over four periods produces a TypeError at best and a wrong total at worst.
    Phase 0F's rule is that nothing may derive a final score by adding quarters,
    and `normalize.final_score` is the only supported reader.
    """

    id: int
    season: int
    week: int
    postseason: bool
    home_team: Mapping[str, Any]
    visitor_team: Mapping[str, Any]
    home_team_score: float | None
    visitor_team_score: float | None
    status: str | None = None
    date: str | None = None
    period_scores: tuple = ()
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)


def parse_games(payload: Any) -> list[GameRow]:
    rows, _ = envelope(payload, context="games")
    parsed: list[GameRow] = []
    for index, row in enumerate(rows):
        context = f"games row {index}"
        if not isinstance(row, dict):
            raise ProviderParseError(
                f"{context}: expected an object, got {type(row).__name__}.")
        postseason = row.get("postseason")
        if not isinstance(postseason, bool):
            raise ProviderParseError(
                f"{context}: 'postseason' must be a boolean. Week numbering "
                f"RESTARTS at 1 in January, so a week-filtered query without "
                f"this flag mixes September and postseason games — it is the "
                f"only field that tells them apart.")
        periods = row.get("period_scores")
        parsed.append(GameRow(
            id=int(_require(row, "id", context)),
            season=int(_require(row, "season", context)),
            week=int(_require(row, "week", context)),
            postseason=postseason,
            home_team=_require(row, "home_team", context),
            visitor_team=_require(row, "visitor_team", context),
            home_team_score=_optional_number(row.get("home_team_score")),
            visitor_team_score=_optional_number(row.get("visitor_team_score")),
            status=row.get("status"),
            date=row.get("date"),
            period_scores=tuple(periods) if isinstance(periods, list) else (),
            raw=row,
        ))
    return parsed


# ── plays ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PlayRow:
    """One play-by-play event.

    THREE FIELDS HERE ARE TRAPS, AND THE PARSER'S JOB IS ONLY TO SURFACE THEM
    HONESTLY — the rules that defuse them are in `normalize.py`:

        `team`          NULL happens (observed on a timeout), and on kicking
                        plays it is the RECEIVING team for `punt`, `kickoff` and
                        `field-goal-missed` but the KICKING team for
                        `field-goal-good`. Never read it as possession.

        `stat_yardage`  not always the player's official yardage — a touchdown
                        whose text says "for 23 yards" carried 15 where a
                        penalty was enforced between downs. Never aggregate.

        `wallclock`     the only reliable ordering. Ids are non-monotonic and a
                        record can appear after `end-of-game`.
    """

    id: Any
    game_id: Any
    type: str
    team: Mapping[str, Any] | None
    text: str
    stat_yardage: float | None
    period: int | None
    clock: str | None
    wallclock: str | None
    start_down: int | None
    participants: tuple = ()
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    def participant_ids(self, participant_type: str) -> tuple:
        """Player ids for one participant role, in payload order.

        THE ONLY SUPPORTED WAY TO ATTRIBUTE A PLAY TO A PLAYER. Phase 0 measured
        a team-keyed read misattributing 5 of 9 field-goal misses, because the
        team on the play is not always the kicking team.
        """
        out = []
        for participant in self.participants:
            if not isinstance(participant, dict):
                continue
            if str(participant.get("type") or "") != participant_type:
                continue
            player = participant.get("player")
            identifier = (participant.get("player_id")
                          if participant.get("player_id") is not None
                          else (player or {}).get("id")
                          if isinstance(player, dict) else None)
            if identifier is not None:
                out.append(identifier)
        return tuple(out)


def parse_plays(payload: Any) -> list[PlayRow]:
    rows, _ = envelope(payload, context="plays")
    parsed: list[PlayRow] = []
    for index, row in enumerate(rows):
        context = f"plays row {index}"
        if not isinstance(row, dict):
            raise ProviderParseError(
                f"{context}: expected an object, got {type(row).__name__}.")
        team = row.get("team")
        if team is not None and not isinstance(team, dict):
            raise ProviderParseError(
                f"{context}: 'team' must be an object or null. Null is "
                f"ordinary — it was observed on a timeout — and is skipped by "
                f"the rules layer rather than failing a whole game.")
        participants = row.get("participants")
        parsed.append(PlayRow(
            id=row.get("id"),
            game_id=row.get("game_id"),
            type=str(_require(row, "type", context)),
            team=team,
            text=str(row.get("text") or row.get("description") or ""),
            stat_yardage=_optional_number(row.get("stat_yardage")),
            period=(int(row["period"]) if isinstance(row.get("period"), int)
                    else None),
            clock=row.get("clock"),
            wallclock=row.get("wallclock"),
            start_down=(int(row["start_down"])
                        if isinstance(row.get("start_down"), int) else None),
            participants=tuple(participants) if isinstance(participants, list)
            else (),
            raw=row,
        ))
    return parsed


# ── players and teams ────────────────────────────────────────────────────────

def parse_players(payload: Any) -> list[dict]:
    """`/players` rows, unchanged. WP1's resolver reads these directly."""
    rows, _ = envelope(payload, context="players")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ProviderParseError(
                f"players row {index}: expected an object, got "
                f"{type(row).__name__}.")
    return list(rows)


def parse_teams(payload: Any) -> list[dict]:
    """`/teams` rows, unchanged."""
    rows, _ = envelope(payload, context="teams")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ProviderParseError(
                f"teams row {index}: expected an object, got "
                f"{type(row).__name__}.")
        _require(row, "abbreviation", f"teams row {index}")
    return list(rows)
