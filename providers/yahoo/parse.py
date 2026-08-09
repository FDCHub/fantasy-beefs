"""B — raw Yahoo payload parsing. Bytes in, plain dicts out.

THIS IS THE ONLY MODULE THAT KNOWS YAHOO'S ENVELOPE. Yahoo's JSON is not a
document, it is a serialized PHP array, and it has three quirks that every
parser of it must handle explicitly:

  1. COLLECTIONS ARE NUMERIC-STRING-KEYED OBJECTS, NOT ARRAYS. A list of three
     matchups arrives as {"0": {...}, "1": {...}, "2": {...}, "count": 3}. The
     "count" sibling is metadata, not an element, and iterating the object
     naively includes it.

  2. AN ENTITY IS A LIST OF SINGLE-KEY DICTS, SOMETIMES NESTED. A team arrives
     as [[{"team_key": ...}, {"team_id": ...}, ...], {"team_points": {...}}] —
     scalar attributes in an inner list, sub-resources as outer siblings.
     `_flatten_entity` merges both levels into one dict.

  3. NUMBERS ARE STRINGS. "0" and 0 both appear for the same field across
     endpoints.

WHY PARSE THE REAL ENVELOPE WHEN THE CORPUS IS SYNTHETIC. Sprint 6's fixtures
are SYNTHETIC (recon R-3 found zero captured payloads), and it would have been
easier to invent a tidy shape for them. That would have certified nothing: the
parser would be tested against its own convenient assumptions, and the first
genuine capture would break it. The synthetic fixtures are therefore built to
Yahoo's DOCUMENTED envelope, and this parser reads that envelope — so the work
this layer does is real even though the bytes are not. What is NOT certified by
that is whether Yahoo's live payload matches its documentation; only a CAPTURED
fixture can settle it, and §17 C-3 reports that gap explicitly.

ORDER IS READ BUT NEVER TRUSTED. `_collection` iterates numeric keys in integer
order purely to make parsing deterministic. Nothing downstream derives identity
or orientation from that order (S6-R1) — providers/yahoo/normalize.py sorts the
team keys itself.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from providers.errors import ProviderParseError

#: Yahoo's three matchup status values, and their meaning for finality. Kept as
#: raw strings here; the mapping to the economic tristate is finality.py's job,
#: because a status string is a provider fact and finality is a product ruling.
STATUS_POSTEVENT = "postevent"
STATUS_MIDEVENT = "midevent"
STATUS_PREEVENT = "preevent"


# ── Envelope primitives ───────────────────────────────────────────────────────

def _s(value: Any) -> str:
    """Coerce a Yahoo scalar (bytes, int, str, None) to str. None becomes ""."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _f(value: Any) -> float | None:
    """Coerce to float, or None when absent or unparseable.

    None, not 0.0. A score that could not be read is not a score of zero, and
    returning 0.0 here would put the exact conflation Sprint 5's schema comment
    forbids into the very first layer that touches the number.
    """
    text = _s(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _collection(node: Any) -> Iterator[Any]:
    """Iterate a Yahoo numeric-string-keyed collection in integer key order.

    Skips the "count" sibling, which is metadata. A plain list is passed through
    unchanged, because a few endpoints do return real arrays.
    """
    if node is None:
        return
    if isinstance(node, list):
        yield from node
        return
    if not isinstance(node, dict):
        return
    keys = []
    for key in node:
        try:
            keys.append((int(key), key))
        except (TypeError, ValueError):
            continue  # "count" and any other metadata sibling
    for _, key in sorted(keys):
        yield node[key]


def _flatten_entity(node: Any) -> dict:
    """Merge Yahoo's list-of-single-key-dicts entity shape into one dict.

    Handles the nested case — [[{a},{b}], {c}] — by recursing into inner lists,
    which is how every team and player entity actually arrives.
    """
    out: dict = {}
    if isinstance(node, dict):
        return dict(node)
    if not isinstance(node, list):
        return out
    for item in node:
        if isinstance(item, list):
            out.update(_flatten_entity(item))
        elif isinstance(item, dict):
            out.update(item)
    return out


def _require(mapping: dict, key: str, context: str) -> Any:
    """Fetch a field that MUST be present, or refuse.

    Fail-closed rather than defaulting: a missing team_key is not a team with an
    empty key, it is a payload this parser cannot honestly claim to have read.
    """
    if key not in mapping or mapping[key] in (None, ""):
        raise ProviderParseError(
            f"{context}: required field {key!r} is absent or empty. Refusing to "
            f"substitute a default — a missing provider identifier is not an "
            f"empty one (S6-R1 fails closed on unknown identity).")
    return mapping[key]


def load_payload(raw: bytes | str | dict) -> dict:
    """Accept a raw fixture's bytes, text or already-decoded dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderParseError(
            f"payload is not valid JSON: {exc}") from exc


def _fantasy_content(payload: dict, context: str) -> dict:
    content = payload.get("fantasy_content")
    if not isinstance(content, dict):
        raise ProviderParseError(
            f"{context}: payload has no 'fantasy_content' envelope. Every Yahoo "
            f"Fantasy response carries one; a payload without it is not a Yahoo "
            f"response and must not be parsed as though it were.")
    return content


def _league_sections(payload: dict, context: str) -> tuple[dict, list]:
    """Yahoo's league response: [attributes_dict, {sub_resource: ...}, ...].

    Returns (merged attributes, the remaining sub-resource dicts).
    """
    content = _fantasy_content(payload, context)
    league = content.get("league")
    if league is None:
        raise ProviderParseError(f"{context}: no 'league' node in payload.")
    if isinstance(league, dict):
        return dict(league), []
    if not isinstance(league, list) or not league:
        raise ProviderParseError(
            f"{context}: 'league' node is neither a dict nor a non-empty list.")
    attributes = _flatten_entity(league[0])
    return attributes, [s for s in league[1:] if isinstance(s, dict)]


# ── Public parsers ────────────────────────────────────────────────────────────

def parse_league(raw: bytes | str | dict) -> dict:
    """Parse a league-info payload into a plain dict.

    Returns keys: league_key, league_id, name, season, current_week,
    start_week, end_week, playoff_start_week. Missing optional weeks are None —
    never a guessed default, because §12 makes season boundaries load-bearing
    and a fabricated one would freeze as though it had been measured.
    """
    payload = load_payload(raw)
    attributes, _ = _league_sections(payload, "parse_league")

    def _int_or_none(key: str) -> int | None:
        text = _s(attributes.get(key)).strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None

    return {
        "league_key": _s(_require(attributes, "league_key", "parse_league")),
        "league_id": _s(attributes.get("league_id")),
        "name": _s(attributes.get("name")),
        "season": _int_or_none("season"),
        "current_week": _int_or_none("current_week"),
        "start_week": _int_or_none("start_week"),
        "end_week": _int_or_none("end_week"),
        "playoff_start_week": _int_or_none("playoff_start_week"),
    }


def _parse_team_entity(node: Any, context: str) -> dict:
    """One team entity — the shape shared by /teams and by scoreboard matchups."""
    flat = _flatten_entity(node)
    name = flat.get("name")
    managers = flat.get("managers")
    manager_nickname = None
    manager_email = None
    for manager_node in _collection(managers):
        manager = _flatten_entity(manager_node).get("manager")
        manager = _flatten_entity(manager) if manager is not None else {}
        manager_nickname = _s(manager.get("nickname")) or manager_nickname
        manager_email = _s(manager.get("email")) or manager_email

    points = flat.get("team_points")
    total = None
    if isinstance(points, dict):
        total = _f(points.get("total"))

    return {
        "team_key": _s(_require(flat, "team_key", context)),
        "team_id": _s(flat.get("team_id")),
        "name": _s(name if not isinstance(name, dict) else name.get("full")),
        "manager": manager_nickname or None,
        "manager_email": manager_email or None,
        "points": total,
    }


def parse_teams(raw: bytes | str | dict) -> list[dict]:
    """Parse a league-teams payload into a list of team dicts."""
    payload = load_payload(raw)
    _, sections = _league_sections(payload, "parse_teams")
    teams_node = None
    for section in sections:
        if "teams" in section:
            teams_node = section["teams"]
            break
    if teams_node is None:
        raise ProviderParseError(
            "parse_teams: payload carries no 'teams' sub-resource.")
    out = []
    for entry in _collection(teams_node):
        entity = entry.get("team") if isinstance(entry, dict) else entry
        out.append(_parse_team_entity(entity, "parse_teams"))
    return out


def parse_scoreboard(raw: bytes | str | dict) -> dict:
    """Parse a scoreboard payload into {league_key, week, matchups: [...]}.

    Each matchup dict carries: status, is_tied, winner_team_key, and a `teams`
    list of exactly two team dicts IN PAYLOAD ORDER. Payload order is preserved
    here and DISCARDED by the next layer — normalize.py sorts the pair itself
    (§5). Preserving it at this layer keeps the parser a faithful reading of the
    bytes; deciding orientation here would bury a product rule in a decoder.
    """
    payload = load_payload(raw)
    attributes, sections = _league_sections(payload, "parse_scoreboard")
    league_key = _s(_require(attributes, "league_key", "parse_scoreboard"))

    scoreboard = None
    for section in sections:
        if "scoreboard" in section:
            scoreboard = section["scoreboard"]
            break
    if scoreboard is None:
        # yfpy raises KeyError('scoreboard') here and Sprint 1-5's
        # yahoo_scoreboard.py translated that specific error into "the week is
        # past the end of the schedule". Preserved as a NAMED empty result
        # rather than an exception: past-the-schedule is a legitimate answer,
        # and the caller distinguishes it by matchups == [].
        return {"league_key": league_key, "week": None, "matchups": [],
                "scoreboard_present": False}

    if isinstance(scoreboard, list):
        scoreboard = _flatten_entity(scoreboard)
    week = _s(scoreboard.get("week")).strip() or None

    matchups_node = None
    if "matchups" in scoreboard:
        matchups_node = scoreboard["matchups"]
    else:
        for entry in _collection(scoreboard):
            if isinstance(entry, dict) and "matchups" in entry:
                matchups_node = entry["matchups"]
                break

    matchups: list[dict] = []
    for entry in _collection(matchups_node):
        node = entry.get("matchup") if isinstance(entry, dict) else entry
        flat = _flatten_entity(node)

        teams_node = flat.get("teams")
        if teams_node is None:
            for sub in _collection(node):
                if isinstance(sub, dict) and "teams" in sub:
                    teams_node = sub["teams"]
                    break

        teams = []
        for team_entry in _collection(teams_node):
            entity = (team_entry.get("team")
                      if isinstance(team_entry, dict) else team_entry)
            teams.append(_parse_team_entity(entity, "parse_scoreboard"))

        if len(teams) != 2:
            raise ProviderParseError(
                f"parse_scoreboard: matchup in week {week!r} of {league_key} "
                f"lists {len(teams)} participant(s), not 2. Sprint 1-5's "
                f"yahoo_scoreboard.py silently skipped such a matchup, which "
                f"drops a real game from the slate; refusing outright instead.")

        matchups.append({
            "status": _s(flat.get("status")).strip().lower(),
            "is_tied": bool(int(_s(flat.get("is_tied")) or 0)),
            "winner_team_key": _s(flat.get("winner_team_key")).strip() or None,
            "week": _s(flat.get("week")).strip() or week,
            "teams": teams,
        })

    return {"league_key": league_key, "week": int(week) if week else None,
            "matchups": matchups, "scoreboard_present": True}


def parse_roster(raw: bytes | str | dict) -> dict:
    """Parse a team-roster-by-week payload.

    Returns {team_key, week, players: [...]}, each player carrying player_key,
    player_id, name, selected_position, display_position, eligible_positions,
    nfl_team, stats (raw stat_id -> value) and points.

    selected_position AND display_position ARE BOTH CARRIED, SEPARATELY. §13
    forbids display_position being used as eligibility truth for Pool starter
    classification; the guard against confusing them is that they never merge
    into one field, at any layer.
    """
    payload = load_payload(raw)
    content = _fantasy_content(payload, "parse_roster")
    team = content.get("team")
    if team is None:
        raise ProviderParseError("parse_roster: no 'team' node in payload.")
    sections = [s for s in (team if isinstance(team, list) else [team])
                if isinstance(s, dict)]
    attributes = _flatten_entity(team[0] if isinstance(team, list) else team)
    team_key = _s(_require(attributes, "team_key", "parse_roster"))

    roster = None
    for section in sections:
        if "roster" in section:
            roster = section["roster"]
            break
    if roster is None:
        raise ProviderParseError(
            f"parse_roster: team {team_key} payload carries no 'roster'.")
    if isinstance(roster, list):
        roster = _flatten_entity(roster)
    week = _s(roster.get("week")).strip() or None

    players_node = roster.get("players")
    if players_node is None:
        for entry in _collection(roster):
            if isinstance(entry, dict) and "players" in entry:
                players_node = entry["players"]
                break

    players: list[dict] = []
    for entry in _collection(players_node):
        node = entry.get("player") if isinstance(entry, dict) else entry
        flat = _flatten_entity(node)

        name = flat.get("name")
        full_name = _s(name.get("full") if isinstance(name, dict) else name)

        selected = flat.get("selected_position")
        selected_flat = _flatten_entity(selected) if selected is not None else {}
        selected_position = _s(selected_flat.get("position")).strip() or None

        eligible = tuple(
            _s(_flatten_entity(e).get("position")).strip()
            for e in _collection(flat.get("eligible_positions"))
            if _s(_flatten_entity(e).get("position")).strip()
        )

        # NO player_stats NODE AT ALL vs. AN EMPTY ONE ARE DIFFERENT FACTS, and
        # the difference is load-bearing. A player Yahoo reported with an empty
        # stat list has been measured and produced nothing; a player with no
        # stats node was never measured, and §13 makes that UNEVALUABLE rather
        # than zero. Collapsing both to {} would let an unmeasured starter read
        # as a measured zero — which is the exact defect the Pool coverage rule
        # exists to prevent. None means "no record"; {} means "measured, empty".
        stats: dict[str, float] | None = None
        stats_node = flat.get("player_stats")
        if stats_node is not None:
            stats = {}
            stats_flat = _flatten_entity(stats_node)
            for stat_entry in _collection(stats_flat.get("stats")):
                stat = _flatten_entity(stat_entry).get("stat")
                stat = _flatten_entity(stat) if stat is not None else {}
                stat_id = _s(stat.get("stat_id")).strip()
                if not stat_id:
                    continue
                value = _f(stat.get("value"))
                # A stat Yahoo reports as "-" (did not play) parses to None and
                # is OMITTED, not zeroed. §13: a missing stat is UNEVALUABLE.
                if value is not None:
                    stats[stat_id] = value

        points_node = flat.get("player_points")
        points = None
        if points_node is not None:
            points = _f(_flatten_entity(points_node).get("total"))

        players.append({
            "player_key": _s(_require(flat, "player_key", "parse_roster")),
            "player_id": _s(flat.get("player_id")),
            "name": full_name,
            "selected_position": selected_position,
            "display_position": _s(flat.get("display_position")).strip() or None,
            "eligible_positions": eligible,
            "nfl_team": (_s(flat.get("editorial_team_abbr")).upper() or None),
            "stats": stats,
            "points": points,
        })

    return {"team_key": team_key, "week": int(week) if week else None,
            "players": players}