#!/usr/bin/env python3
"""WP2 certification — the BALLDONTLIE client, parser and normalizer.

WHAT THIS SUITE PROVES, AND WHY EACH GROUP EXISTS:

    A  the transport refuses what a 200 would otherwise hide
    B  the parser reads the envelope and fails closed, interpreting nothing
    C  every Phase 0F rule is implemented, named, and behaves as measured
    D  a ProviderWeek from this provider states only what it can state
    E  the identity seam agrees with WP1, key for key
    F  the corpus says what it is, and it does not say CAPTURED

GROUP C IS THE PACKAGE. Phase 0F is a list of eighteen behaviours the Phase 0
acceptance test MEASURED in BALLDONTLIE's live payloads — zeros omitted,
possession inverted on kicking plays, a field goal attributable only by
participant — and each one silently corrupts a settlement if the code in front
of it assumes the ordinary thing. `normalize.RULES` names them; this group
exercises them; and §C-0 asserts the register is complete, so a rule cannot be
deleted without a gate going red.

GROUP A IS WHERE THE TERMS OF SERVICE LIVE. §7c forbids working around a rate
limit, and the only durable way to keep that promise is to make the workaround
absent rather than discouraged: there is no retry loop to tune, and this group
asserts a 429 raises on the first response with the server's own Retry-After.

OFFLINE, DETERMINISTIC, AND CREDENTIAL-FREE. No network, no API key, no clock
dependency, no database. The live transport is exercised through an injected
fake HTTP client, and pacing is asserted against an injected clock so a suite
that proves the client waits never itself waits.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from datetime import datetime, timezone                        # noqa: E402

from providers.balldontlie import capture as C                  # noqa: E402
from providers.balldontlie import normalize as N                # noqa: E402
from providers.balldontlie import parse as P                    # noqa: E402
from providers.balldontlie import transport as T                # noqa: E402
from providers.balldontlie_identity import directory_from_fixture  # noqa: E402
from providers.base import ProviderLeague                       # noqa: E402
from providers.errors import (                                  # noqa: E402
    ProviderCredentialError,
    ProviderParseError,
    ProviderTransportError,
)
from providers.incident import is_retryable, reason_for_exception  # noqa: E402

CORPUS = os.path.join(ROOT, "providers", "fixtures", "balldontlie")

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _refuses(label: str, call, expected=ProviderTransportError) -> None:
    """Assert a call FAILS CLOSED with the named refusal, not a bare error."""
    try:
        call()
    except expected as exc:
        _assert(label, True, str(exc).splitlines()[0][:74])
    except Exception as exc:                                    # noqa: BLE001
        _assert(label, False,
                f"raised {type(exc).__name__}, not {expected.__name__}: {exc}")
    else:
        _assert(label, False, "returned instead of refusing")


# ── a fake HTTP client, so the live transport is exercised without a socket ──

class _Response:
    def __init__(self, status_code=200, payload=None, headers=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"data": [], "meta": {}}
        self.headers = headers or {}
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


class _Client:
    """Records every call and answers from a queue. No network, ever."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}),
                           "headers": dict(headers or {}), "timeout": timeout})
        return self.responses.pop(0) if self.responses else _Response()


class _Clock:
    """A monotonic clock that only moves when something sleeps."""

    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def _live(responses, **kwargs):
    clock = _Clock()
    transport = T.BalldontlieLiveTransport(
        api_key="test-key-not-a-credential", client=_Client(responses),
        clock=clock, sleeper=clock.sleep,
        now=lambda: datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc), **kwargs)
    return transport, clock


print("=" * 78)
print("WP2 · BALLDONTLIE CLIENT, PARSER AND NORMALIZER")
print("=" * 78)
print(f"  corpus                : {os.path.relpath(CORPUS)}")
print(f"  endpoints registered  : {len(T.ENDPOINTS)}")
print(f"  Phase 0F rules        : {len(N.RULES)}")


# ══════════════════════════════════════════════════════════════════════════════
# A · the transport
# ══════════════════════════════════════════════════════════════════════════════

print("\nWP2-A · the transport refuses what a 200 would otherwise hide")

_refuses("no credentials anywhere -> a NAMED credential refusal, never an "
         "empty key",
         lambda: T.load_credentials(environ={},
                                    secrets_dir=os.path.join(ROOT, "nope")),
         ProviderCredentialError)
_assert("an explicit key is accepted from the environment",
        T.load_credentials(environ={"BALLDONTLIE_API_KEY": "abc"},
                           secrets_dir="/nonexistent") == "abc")

# THE PARAMETER TRAP. BALLDONTLIE answers 200 to a request it did not
# understand, applies no filter, and returns confidently wrong rows.
_transport, _clock = _live([])
_refuses("an unknown ENDPOINT is refused before any request is made",
         lambda: _transport.get("fantasy/nonsense", season=2025))
_refuses("a MISSPELLED parameter is refused rather than sent — the API would "
         "answer 200 and ignore it",
         lambda: _transport.get("fantasy/weekly_stats", season=2025,
                                weak=17))
_refuses("per_page above the documented maximum is refused, not clamped",
         lambda: _transport.get("fantasy/weekly_stats", season=2025, week=17,
                                per_page=500))
_assert("  · and no request left the client during any of those refusals",
        _transport.requests_made == 0, str(_transport.requests_made))

_transport, _clock = _live([
    _Response(headers={"x-ratelimit-limit": "5", "x-ratelimit-remaining": "4"}),
    _Response(headers={"x-ratelimit-limit": "5", "x-ratelimit-remaining": "3"}),
    _Response(headers={"x-ratelimit-limit": "5", "x-ratelimit-remaining": "2"}),
])
_transport.get("fantasy/weekly_stats", season=2025, week=1)
_transport.get("fantasy/weekly_stats", season=2025, week=2)
_transport.get("fantasy/weekly_stats", season=2025, week=3)
_assert("requests are PACED to the configured ceiling before they are sent",
        [round(w, 3) for w in _clock.slept] == [12.0, 12.0],
        f"waits {[round(w, 3) for w in _clock.slept]} at "
        f"{T.DEFAULT_REQUESTS_PER_MINUTE}/min")
_assert("  · the default ceiling is the MEASURED tier, not the hoped-for one",
        T.DEFAULT_REQUESTS_PER_MINUTE == 5, str(T.DEFAULT_REQUESTS_PER_MINUTE))
_assert("rate-limit telemetry is recorded from SUCCESSFUL responses too",
        _transport.last_rate_limit.limit == 5
        and _transport.last_rate_limit.remaining == 2,
        f"limit={_transport.last_rate_limit.limit} "
        f"remaining={_transport.last_rate_limit.remaining}")

_transport, _clock = _live([
    _Response(status_code=429, headers={"retry-after": "31",
                                        "x-ratelimit-limit": "5"})])
try:
    _transport.get("fantasy/weekly_stats", season=2025, week=1)
    _assert("a 429 raises rather than being retried", False, "it returned")
except T.BalldontlieRateLimited as exc:
    _assert("a 429 raises, carrying the server's own Retry-After",
            exc.retry_after == 31.0, f"retry_after={exc.retry_after}")
    _assert("  · exactly ONE request was made — there is no retry loop to tune "
            "into a workaround (§7c)",
            _transport.requests_made == 1, str(_transport.requests_made))
    _assert("  · and it reaches an operator through the CERTIFIED vocabulary, "
            "not a synonym",
            reason_for_exception(exc) == "provider_unavailable"
            and is_retryable("provider_unavailable") is True,
            reason_for_exception(exc))

# THE REQUEST ITSELF. Nothing above would notice a client that paced perfectly
# and then called the wrong URL without authenticating.
_client = _Client([_Response(payload={"data": [], "meta": {}})])
_clockx = _Clock()
_t = T.BalldontlieLiveTransport(api_key="secret-key-abc", client=_client,
                                clock=_clockx, sleeper=_clockx.sleep)
_t.get("fantasy/weekly_stats", season=2025, week=17)
_call = _client.calls[0]
_assert("the request goes to the documented NFL v1 resource",
        _call["url"] == "https://api.balldontlie.io/nfl/v1/fantasy/weekly_stats",
        _call["url"])
_assert("  · authenticated, and with the caller's parameters intact",
        _call["headers"].get("Authorization") == "secret-key-abc"
        and _call["params"] == {"season": 2025, "week": 17},
        str(_call["params"]))
_refuses("  · and the key never reaches an error message an operator will read",
         lambda: _t.get("fantasy/weekly_stats", season=2025, weak=17))
try:
    _t.get("fantasy/weekly_stats", season=2025, weak=17)
except Exception as _exc:                                       # noqa: BLE001
    _assert("  · (checked: the refusal text carries no credential material)",
            "secret-key-abc" not in str(_exc))

_transport, _clock = _live([_Response(status_code=401)])
_refuses("a 401 is a CREDENTIAL refusal, not a generic outage",
         lambda: _transport.get("teams"), ProviderCredentialError)

_transport, _clock = _live([_Response(status_code=503)])
_refuses("a 5xx is a transport refusal",
         lambda: _transport.get("teams"))

_transport, _clock = _live([_Response(bad_json=True)])
_refuses("a 200 whose body is not JSON is a PARSE refusal — the status lied",
         lambda: _transport.get("teams"), ProviderParseError)

_transport, _clock = _live([_Response(payload={"data": [{"id": 1}], "meta": {}})])
_first = _transport.get("teams")
_second = _transport.get("teams")
_assert("an identical request inside the TTL is served from cache",
        _transport.requests_made == 1 and _transport.cache_hits == 1
        and _first == _second,
        f"requests={_transport.requests_made} hits={_transport.cache_hits}")
_assert("  · and the cache key ignores how a caller spelled its numbers",
        T.cache_key("teams", {"season": 2025}) ==
        T.cache_key("teams", {"season": "2025"}))

_sunk: list[dict] = []
_transport, _clock = _live([_Response(payload={"data": [], "meta": {}})],
                           raw_sink=lambda **kw: _sunk.append(kw))
_transport.get("teams")
_assert("the raw payload and its collected_at are offered to WP5's store",
        len(_sunk) == 1 and _sunk[0]["path"] == "teams"
        and _sunk[0]["collected_at"].tzinfo is not None,
        f"{len(_sunk)} payload(s) sunk")

_transport, _clock = _live([
    _Response(payload={"data": [{"id": 1}], "meta": {"next_cursor": 1}}),
    _Response(payload={"data": [{"id": 2}], "meta": {"next_cursor": 2}}),
    _Response(payload={"data": [{"id": 3}], "meta": {"next_cursor": 3}}),
])
_refuses("an unbounded cursor walk is REFUSED at the page bound, never "
         "silently truncated",
         lambda: _transport.paginate("teams", max_pages=2))

# THE CAPTURE PATH. Written, never run here — and the one thing it must refuse
# is the mistake that would look like success in every log.
_refuses("capturing from a FIXTURE transport is refused — only a live fetch may "
         "write CAPTURED provenance",
         lambda: C.capture_week(T.BalldontlieFixtureTransport(CORPUS),
                                season=2025, week=17), ValueError)
_refuses("  · and so is capturing from anything that is not the certified live "
         "client",
         lambda: C.capture_week(object(), season=2025, week=17), ValueError)

_fixture = T.BalldontlieFixtureTransport(CORPUS)
_assert("a fixture transport needs no key and opens no socket",
        _fixture.provider == "balldontlie")
_assert("  · and stamps the RECORDED instant, so replay is deterministic",
        _fixture.observed_at() == T.BalldontlieFixtureTransport(
            CORPUS).observed_at())
_refuses("a missing fixture is refused rather than answered with an empty page",
         lambda: _fixture.get("fantasy/weekly_stats", season=1999, week=1))
_assert("the NFL-teams reader is NOT named fetch_teams — that name already "
        "means a league's FANTASY teams",
        hasattr(T.BalldontlieLiveTransport, "fetch_nfl_teams")
        and not hasattr(T.BalldontlieLiveTransport, "fetch_teams"))
_assert("the fixture transport walks real cursor pages",
        len(_fixture.fetch_weekly_stats(season=2025, week=17)) == 8
        and _fixture.requests_made == 2,
        f"{_fixture.requests_made} pages")


# ══════════════════════════════════════════════════════════════════════════════
# B · the parser
# ══════════════════════════════════════════════════════════════════════════════

print("\nWP2-B · the parser reads the envelope and interprets nothing")

_raw_weekly = json.load(open(os.path.join(
    CORPUS, "fantasy_weekly_stats__per_page-100__season-2025__week-17.json"),
    encoding="utf-8"))
_page1, _page2 = _raw_weekly["pages"]
_rows = P.parse_weekly_stats(_page1) + P.parse_weekly_stats(_page2)
_assert("every row on both pages parses", len(_rows) == 8, f"{len(_rows)} rows")

_refuses("a payload that is not the documented envelope is refused",
         lambda: P.parse_weekly_stats({"rows": []}), ProviderParseError)
_refuses("a row whose 'stats' is ABSENT is refused — reading it as a zero "
         "would invent a performance",
         lambda: P.parse_weekly_stats(
             {"data": [{"season": 2025, "week": 1, "team": {"abbreviation": "SF"},
                        "player": {"id": 1}}]}), ProviderParseError)
_assert("but an EMPTY 'stats' object parses — it is a row, not a gap",
        any(row.stats == {} for row in _rows))
_refuses("a game row without the postseason flag is refused — it is the only "
         "field that separates January from September",
         lambda: P.parse_games({"data": [{"id": 1, "season": 2025, "week": 1,
                                          "home_team": {}, "visitor_team": {}}]}),
         ProviderParseError)

_plays = P.parse_plays(json.load(open(os.path.join(
    CORPUS, "plays__game_ids-424186__per_page-100.json"), encoding="utf-8")))
_assert("plays parse, including one with a NULL team",
        len(_plays) == 19 and any(p.team is None for p in _plays),
        f"{len(_plays)} plays")
_assert("participants are addressable by role, not by position in a list",
        [p for p in _plays if p.id == 5201][0].participant_ids("passer") == (63,))
_assert("the parser does NOT sort — ordering is a rule, and it lives one layer "
        "up",
        [p.id for p in _plays][:2] == [5107, 5101])


# ══════════════════════════════════════════════════════════════════════════════
# C · the Phase 0F rules
# ══════════════════════════════════════════════════════════════════════════════

print("\nWP2-C · every Phase 0F rule, as measured")

def _resolve(module, dotted: str):
    """Resolve `name` or `Class.name` against a module."""
    target = module
    for part in dotted.split("."):
        target = getattr(target, part, None)
        if target is None:
            return None
    return target


_ids = [rule for rule, _, _ in N.RULES] + [r for r, _, _ in T.TRANSPORT_RULES]
_assert("the Phase 0F register covers the payload rules AND the transport ones",
        len(N.RULES) == 19 and len(T.TRANSPORT_RULES) == 4
        and len(set(_ids)) == len(_ids),
        f"{len(N.RULES)} payload + {len(T.TRANSPORT_RULES)} transport")
_unresolved = ([n for _, _, n in N.RULES if _resolve(N, n) is None]
               + [n for _, _, n in T.TRANSPORT_RULES if _resolve(T, n) is None])
_assert("  · and every registered rule names something that really exists",
        not _unresolved, str(_unresolved))
_assert("  · the register is not a comment — deleting a rule breaks this gate",
        all(callable(_resolve(N, n)) for _, _, n in N.RULES))

_stats = N.normalize_weekly_stats(_rows)
_by_key = {s.player_key: s for s in _stats}

# 0F-1 · zeros are omitted entirely.
_purdy_raw = [r for r in _rows if r.player_id == 27][0]
_purdy = _by_key["bdl.p.27"]
_assert("0F-1 an omitted field is a ZERO on a present row",
        "passing_interceptions" not in _purdy_raw.stats
        and _purdy.values["passing_interceptions"] == 0.0)
_assert("  · and it counts as COVERED, or no kicker Pool could ever settle",
        "passing_interceptions" in _purdy.stat_ids_present)

# 0F-2 · an empty stats block is a real zero.
_bowers = _by_key["bdl.p.277679"]
_assert("0F-2 an EMPTY stats block is a real zero, not a gap",
        _bowers.values["receptions"] == 0.0
        and len(_bowers.stat_ids_present) == len(N.PLAYER_FIELDS),
        f"{len(_bowers.stat_ids_present)} covered")

# 0F-3 · an absent ROW is unevaluable.
_assert("0F-3 a subject with NO row produces no record at all",
        "bdl.p.999999" not in _by_key)
_assert("  · coverage is asserted at ROW level — values and coverage agree "
        "exactly",
        all(set(s.values) == set(s.stat_ids_present) for s in _stats))
_assert("  · and this INVERTS week_stat_source's Yahoo rule deliberately: "
        "there, an absent stat is unevaluable",
        "A MISSING STAT IS UNEVALUABLE" in open(
            os.path.join(ROOT, "providers", "week_stat_source.py"),
            encoding="utf-8").read())

# 0F-4 · quarters are not a score.
_games = P.parse_games(json.load(open(os.path.join(
    CORPUS, "games__per_page-100__seasons-2025__weeks-1.json"),
    encoding="utf-8")))
_game = [g for g in _games if g.id == 424186][0]
_assert("0F-4 the final score comes from the GAME object",
        N.final_score(_game) == (24.0, 17.0), str(N.final_score(_game)))
_assert("  · and the quarters really do carry nulls that would break a sum",
        any(period.get("home") is None or period.get("visitor") is None
            for period in _game.period_scores))
_refuses("  · summing quarters is a NAMED refusal, always",
         lambda: N.refuse_quarter_sum(_game), ProviderParseError)
_refuses("  · an unfinished game has no score to read, and none is invented",
         lambda: N.final_score([g for g in _games if g.id == 999002][0]),
         ProviderParseError)

# 0F-5 · ordering.
_ordered = N.ordered_plays(_plays)
_assert("0F-5 plays are ordered by WALLCLOCK, not by arrival or by id",
        [p.id for p in _ordered][:5] == [5101, 5102, 5103, 5104, 5107],
        str([p.id for p in _ordered][:5]))
_assert("  · the corpus really does carry non-monotonic ids, so the rule is "
        "not vacuous",
        any(a.id > b.id for a, b in zip(_plays, _plays[1:])))
_assert("  · and a record survives AFTER end-of-game — which is why the last "
        "play is never the score",
        _ordered[-1].type == "two-minute-warning"
        and _ordered[-2].type == "end-of-game",
        f"{_ordered[-2].type} -> {_ordered[-1].type}")

# 0F-6 / 0F-7 · possession.
_possession = list(N.carry_possession(_plays, home="LAR", visitor="DEN"))
_trace = {play.id: side for play, side in _possession}
_assert("0F-6 a NULL team leaves possession exactly as it was, and fails "
        "nothing",
        _trace[5301] == _trace[5211], f"{_trace[5301]}")
_punt = [p for p in _plays if p.id == 5107][0]
_assert("0F-7 on a punt, play.team is the RECEIVING side — possession is the "
        "other one",
        _punt.team["abbreviation"] == "LAR" and _trace[5107] == "DEN")
_fg_good = [p for p in _plays if p.id == 5205][0]
_assert("  · on field-goal-good the SAME field means the kicking side, one "
        "slug apart",
        _fg_good.team["abbreviation"] == "LAR" and _trace[5205] == "LAR")
_assert("  · so possession is carried forward and the ball changes hands after "
        "the kick",
        _trace[5107] == "DEN" and _trace[5201] == "LAR")

# 0F-8 · attribution by participant.
_fg_missed = [p for p in _plays if p.id == 5208][0]
_assert("0F-8 a field goal is attributed by PARTICIPANT",
        N.field_goal_kicker_id(_fg_missed) == 20002,
        str(N.field_goal_kicker_id(_fg_missed)))
_assert("  · and a team-keyed read would have booked this miss against the "
        "wrong side — which is how 5 of 9 were misattributed",
        _fg_missed.team["abbreviation"] == "LAR" and _trace[5208] == "DEN")

# 0F-9 · blocked kicks.
_blocked = [p for p in _plays if p.id == 5210][0]
_blocked_td = [p for p in _plays if p.id == 5211][0]
_assert("0F-9 a blocked kick surrenders its DISTANCE",
        N.field_goal_distance(_blocked) is None
        and N.field_goal_distance(_fg_good) == 38.0)
_assert("  · and the return yardage on a blocked-kick touchdown is NOT read as "
        "the attempt",
        _blocked_td.stat_yardage == 76.0
        and N.field_goal_distance(_blocked_td) is None)
_assert("  · but an attribution the payload DID make is still honoured",
        N.field_goal_kicker_id(_blocked) == 20001
        and N.field_goal_kicker_id(_blocked_td) is None)
_assert("  · and no slug is matched by prefix — 'blocked-field-goal' does not "
        "start with 'field-goal'",
        not "blocked-field-goal".startswith("field-goal")
        and "blocked-field-goal" in N.FIELD_GOAL_SLUGS)

# 0F-10 · which source settles a kicker.
_little = _by_key["bdl.p.278371"]
_fairbairn = _by_key["bdl.p.1828"]
_assert("0F-10 one miss settles from the SUMMARY — that field is the miss's "
        "own distance",
        N.kicker_settlement_source(_little.values)[0] == "summary")
_assert("  · two misses including a 0–39 need /plays, because the summary "
        "figure is a total",
        N.kicker_settlement_source(_fairbairn.values)[0] == "plays",
        N.kicker_settlement_source(_fairbairn.values)[1][:60])

# 0F-11 · extra points.
_extras = N.extra_point_summary(_fairbairn.values)
_assert("0F-11 extra points come from STRUCTURED fields",
        _extras["extra_points_made"] == 1.0
        and _extras["extra_points_missed"] == 1.0)
_assert("  · the reader takes only a stat mapping, so there is no play text "
        "for it to parse",
        "play" not in N.extra_point_summary.__code__.co_varnames)

# 0F-12 · pick six.
_pick_six = [p for p in _plays if p.id == 5201][0]
_ordinary_td = [p for p in _plays if p.id == 5204][0]
_assert("0F-12 a pick six is INTERCEPT + TOUCHDOWN, charged to the PASSER",
        N.pick_six_passer_id(_pick_six) == 63)
_assert("  · an ordinary touchdown pass by the same passer is not one",
        N.pick_six_passer_id(_ordinary_td) is None)

# 0F-13 · three-and-outs stay fenced.
_derived = N.three_and_outs(_plays, home="LAR", visitor="DEN", team="LAR")
_assert("0F-13 three-and-outs are derived", _derived.value == 1.0,
        str(_derived.value))
_assert("  · and returned UNVERIFIED — the threshold is still PARTIAL",
        _derived.verified is False)
_refuses("  · so a caller cannot take the number without the gate",
         _derived.require_verified, ProviderParseError)

# 0F-14 · the postseason week collision.
_assert("0F-14 a naive week query really does return both season halves",
        len(_games) == 4 and any(g.postseason for g in _games)
        and all(g.week == 1 for g in _games),
        f"{len(_games)} games, all week 1")
_regular = N.regular_season_only(_games)
_assert("  · and the filter removes exactly the January game",
        len(_regular) == 3 and 999001 not in {g.id for g in _regular})
_assert("  · /fantasy/* is clean, so nothing in the weekly-stats path filters",
        "games" in T.POSTSEASON_AMBIGUOUS
        and "fantasy/weekly_stats" not in T.POSTSEASON_AMBIGUOUS)

# 0F-15 · plays never aggregate.
_refuses("0F-15 deriving a total by summing plays is a NAMED refusal",
         N.refuse_play_aggregation, ProviderParseError)
_assert("  · and the corpus shows why: the text says 23 yards, stat_yardage "
        "says 15",
        "23 yards" in _ordinary_td.text and _ordinary_td.stat_yardage == 15.0)

# 0F-16 · the position vocabulary.
_assert("0F-16 PK normalises to K",
        N.fantasy_position(
            [r for r in _rows if r.player_id == 278371][0]) == "K")
_assert("  · a DST row is DEF",
        N.fantasy_position([r for r in _rows if r.is_team_defense][0]) == "DEF")
_assert("  · and the stray DT is not forced into the fantasy vocabulary, nor "
        "dropped",
        N.fantasy_position([r for r in _rows if r.player_id == 909090][0])
        is None
        and "bdl.p.909090" in _by_key)

# 0F-17 · the DST row.
_dst_row = [r for r in _rows if r.is_team_defense][0]
_assert("0F-17 a DST record carries player: null and is keyed by TEAM",
        _dst_row.player is None and N.subject_key(_dst_row) == "bdl.dst.DET")
_assert("  · and it is scored on the DST vocabulary, not the player one",
        set(_by_key["bdl.dst.DET"].stat_ids_present) >= set(N.DST_FIELDS)
        and "passing_yards" not in _by_key["bdl.dst.DET"].stat_ids_present)

# 0F-19 · points allowed, and the caveat that rides with it.
_assert("0F-19 dst_points_allowed is read as reported",
        N.points_allowed(_by_key["bdl.dst.DET"].values) == 18.0)
_assert("  · and the unconfirmed extra-point treatment is recorded where a "
        "scorer will meet it",
        "unconfirmed" in (N.points_allowed.__doc__ or "").lower())

# 0F-18 · coverage is measured.
_offence_only = [r for r in _rows if not r.is_team_defense]
_assert("0F-18 coverage is measured from the PAYLOAD, not from documentation",
        "dst_points_allowed" in N.supported_stats(_rows)
        and "dst_points_allowed" not in N.supported_stats(_offence_only))


# ══════════════════════════════════════════════════════════════════════════════
# D · the week
# ══════════════════════════════════════════════════════════════════════════════

print("\nWP2-D · a ProviderWeek that states only what this provider knows")

_league = ProviderLeague(provider="yahoo", league_key="461.l.488800",
                        name="CULV Appreciation Society", season=2025,
                        current_week=17)
_week = N.build_week(league=_league, week=17, player_stats=_stats,
                     observed_at=_fixture.observed_at())
_assert("the league is the one the caller supplied — never invented here",
        _week.league is _league and _week.league.provider == "yahoo")
_assert("teams, matchups and rosters are EMPTY, because BALLDONTLIE hosts no "
        "league",
        _week.teams == () and _week.matchups == () and _week.roster_entries == ())
_assert("the facts it does hold are carried in full",
        len(_week.player_stats) == len(_stats) == 8)
_assert("observed_at is the recorded instant, so staleness measurement is "
        "deterministic",
        _week.observed_at == _fixture.observed_at())
_assert("every stat record names this provider",
        {s.provider for s in _week.player_stats} == {"balldontlie"})
_assert("provider fantasy points are carried as commentary, never as a "
        "settlement figure",
        all(s.fantasy_points is None for s in _stats))


# ══════════════════════════════════════════════════════════════════════════════
# E · the WP1 identity seam
# ══════════════════════════════════════════════════════════════════════════════

print("\nWP2-E · the identity seam agrees with WP1, key for key")

_directory = directory_from_fixture()
_resolvable = [k for k in _by_key if k != "bdl.p.909090"]
_unknown = [k for k in _resolvable if _directory.by_key(k) is None]
_assert("every subject WP2 produced is a subject WP1 already knows",
        not _unknown, f"unknown to WP1: {_unknown}")
_assert("  · including the team defense, keyed identically on both sides",
        _directory.by_key("bdl.dst.DET") is not None)
_assert("  · and the keys come from ONE module, so they cannot drift apart",
        N.subject_key.__module__ == "providers.balldontlie.normalize"
        and "balldontlie_identity" in open(
            os.path.join(ROOT, "providers", "balldontlie", "normalize.py"),
            encoding="utf-8").read())
_assert("the stray DT is honestly outside WP1's fantasy directory",
        _directory.by_key("bdl.p.909090") is None)


# ══════════════════════════════════════════════════════════════════════════════
# F · provenance
# ══════════════════════════════════════════════════════════════════════════════

print("\nWP2-F · the corpus says what it is")

_manifest = json.load(open(os.path.join(CORPUS, "MANIFEST.json"),
                           encoding="utf-8"))
_assert("the BALLDONTLIE corpus declares its provenance",
        _manifest.get("provenance") == "SYNTHETIC",
        str(_manifest.get("provenance")))
_assert("  · and never claims the CAPTURED tier, which no BALLDONTLIE payload "
        "in this repository has earned",
        "CAPTURED" not in _manifest.get("provenance", "")
        and "NOT CAPTURED" in _manifest.get("provenance_note", ""))
_assert("  · every fixture file on disk is described in the manifest",
        {name for name in os.listdir(CORPUS) if name.endswith(".json")
         and name != "MANIFEST.json"} == set(_manifest["fixtures"]),
        str(sorted(set(os.listdir(CORPUS)) - set(_manifest["fixtures"])
                   - {"MANIFEST.json"})))
_assert("no credential is reachable from this suite's environment",
        not os.environ.get("BALLDONTLIE_API_KEY"))
_assert("the package imports nothing from ledger/ or economy/",
        not any(bad in open(os.path.join(ROOT, "providers", "balldontlie", mod),
                            encoding="utf-8").read()
                for mod in ("transport.py", "parse.py", "normalize.py")
                for bad in ("from ledger", "import ledger",
                            "from economy", "import economy")))


print()
if _failures:
    print("=" * 78)
    print(f"WP2 — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  · {_f}")
    print("=" * 78)
    sys.exit(1)
print("=" * 78)
print(f"WP2 BALLDONTLIE client: all assertions passed — {len(N.RULES)} Phase 0F "
      f"rules exercised against a SYNTHETIC corpus, no network, no credential.")
print("=" * 78)
