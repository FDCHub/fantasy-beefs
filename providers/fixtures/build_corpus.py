#!/usr/bin/env python3
"""Build the Sprint 6 SYNTHETIC fixture corpus.

EVERY FIXTURE THIS SCRIPT WRITES IS PROVENANCE = SYNTHETIC, WITHOUT EXCEPTION.
Recon R-3 searched the repository and found ZERO captured Yahoo payloads: the
only JSON in the tree is the governed Pool catalog and stat vocabulary, which
are product artifacts, not provider responses. There is nothing to promote, and
under §16 nothing here may claim otherwise. `providers/fixtures/record.py`
keeps `capture_live()` as the ONLY function able to write CAPTURED provenance,
and it requires a live transport this environment cannot construct.

THE PAYLOADS ARE BUILT TO YAHOO'S DOCUMENTED ENVELOPE, NOT TO A CONVENIENT
SHAPE. Yahoo's Fantasy API serializes PHP arrays: collections are
numeric-string-keyed objects with a `count` sibling, entities are lists of
single-key dicts sometimes nested one level, and numbers are strings. Building
tidy fixtures instead would have certified the parser against its own
assumptions. What that still does NOT certify is whether Yahoo's LIVE payload
matches its documentation — only a CAPTURED fixture settles that, and C-3
reports the gap explicitly.

THE CORPUS IS DESIGNED AROUND THE CERTIFICATION GATES, one scenario per gate
that needs distinct data:

    w1   a normal completed week — all postevent, distinct scores
    w2   the FINALITY TRUTH TABLE in one week: postevent 0-0, midevent with
         scores, preevent, and a matchup with no status field at all
    w3   the CURRENT week, all postevent — the horizon boundary
    w4   BEYOND the horizon (current_week is 3) — must not persist
    w1m  week 1 MIRRORED: identical facts, both teams listed in the opposite
         order in every matchup. Must produce byte-identical matchup keys.
    w1c  week 1 CONTRADICTED: same final matchups, different scores. Feeds the
         post-final conflict gate.
    rosters for week 1 — starters, bench, a same-name player pair, a player
         with no selected_position, and a player whose stats are absent.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from providers.fixtures.record import SYNTHETIC, write_fixture  # noqa: E402

CORPUS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus")

GAME_ID = 461
LEAGUE_NUMBER = "488800"
LEAGUE_KEY = f"{GAME_ID}.l.{LEAGUE_NUMBER}"
SEASON = 2025
CURRENT_WEEK = 3

#: The frozen replay instant. Every manifest declares it, so gate-2 staleness
#: (§14, C-13) is exercised against a fixed clock rather than against whenever
#: the suite happened to run.
REPLAY_NOW = "2025-09-23T12:00:00+00:00"

TEAM_COUNT = 6
TEAM_NAMES = {
    1: "Mahomes Alone",
    2: "Sunday Scaries",
    3: "Kelce Grammer",
    4: "Purdy Good",
    5: "The Nix Files",
    6: "Bijan Mustard",
}


def team_key(ordinal: int) -> str:
    return f"{LEAGUE_KEY}.t.{ordinal}"


# ── Yahoo envelope builders ───────────────────────────────────────────────────

def collection(items: list) -> dict:
    """Yahoo's numeric-string-keyed collection with its `count` sibling."""
    out: dict = {str(index): item for index, item in enumerate(items)}
    out["count"] = len(items)
    return out


def team_entity(ordinal: int, *, points: float | None = None,
                name_override: str | None = None) -> dict:
    """One team, in Yahoo's [[scalars...], {sub-resource}] entity shape."""
    scalars = [
        {"team_key": team_key(ordinal)},
        {"team_id": str(ordinal)},
        {"name": name_override or TEAM_NAMES[ordinal]},
        {"managers": collection([
            {"manager": [
                {"manager_id": str(ordinal)},
                {"nickname": f"GM{ordinal}"},
                # Deliberately present so C-17 proves the scrubber removes it.
                {"email": f"gm{ordinal}@example.invalid"},
            ]},
        ])},
    ]
    entity: list = [scalars]
    if points is not None:
        entity.append({"team_points": {"coverage_type": "week",
                                       "total": f"{points:.2f}"}})
    return entity


def matchup_entity(*, week: int, status: str | None, team_a: int, team_b: int,
                   points_a: float | None, points_b: float | None,
                   winner: int | None = None, is_tied: int = 0) -> dict:
    """One matchup. `status=None` omits the field entirely (§7 unknown case)."""
    scalars: dict = {"week": str(week), "is_tied": is_tied}
    if status is not None:
        scalars["status"] = status
    if winner is not None:
        scalars["winner_team_key"] = team_key(winner)
    return {
        "matchup": [
            scalars,
            {"teams": collection([
                {"team": team_entity(team_a, points=points_a)},
                {"team": team_entity(team_b, points=points_b)},
            ])},
        ],
    }


def league_payload(*, current_week: int) -> dict:
    return {
        "fantasy_content": {
            "league": [
                {
                    "league_key": LEAGUE_KEY,
                    "league_id": LEAGUE_NUMBER,
                    "name": "Fantasy Beefs Certification League",
                    "season": str(SEASON),
                    "current_week": str(current_week),
                    "start_week": "1",
                    "end_week": "17",
                    "playoff_start_week": "15",
                    "num_teams": TEAM_COUNT,
                },
            ],
        },
    }


def teams_payload() -> dict:
    return {
        "fantasy_content": {
            "league": [
                {"league_key": LEAGUE_KEY, "league_id": LEAGUE_NUMBER,
                 "name": "Fantasy Beefs Certification League",
                 "season": str(SEASON)},
                {"teams": collection([
                    {"team": team_entity(ordinal)}
                    for ordinal in range(1, TEAM_COUNT + 1)
                ])},
            ],
        },
    }


def scoreboard_payload(week: int, matchups: list) -> dict:
    return {
        "fantasy_content": {
            "league": [
                {"league_key": LEAGUE_KEY, "league_id": LEAGUE_NUMBER,
                 "name": "Fantasy Beefs Certification League",
                 "season": str(SEASON), "current_week": str(CURRENT_WEEK)},
                {"scoreboard": {
                    "week": str(week),
                    "0": {"matchups": collection(matchups)},
                }},
            ],
        },
    }


# ── Player / roster construction ──────────────────────────────────────────────

def player_entity(*, player_id: int, name: str, display_position: str,
                  nfl_team: str, selected_slot: str,
                  stats: dict[str, float] | None,
                  points: float | None) -> dict:
    """One roster player.

    `stats=None` means the payload carries NO player_stats node at all — a
    started player the feed never spoke about, which must read as UNEVALUABLE
    rather than as zero (§13). That is a different fixture condition from an
    EMPTY stats dict, and both appear in the corpus.
    """
    scalars = [
        {"player_key": f"{GAME_ID}.p.{player_id}"},
        {"player_id": str(player_id)},
        {"name": {"full": name, "first": name.split()[0],
                  "last": name.split()[-1]}},
        {"editorial_team_abbr": nfl_team},
        {"display_position": display_position},
        {"eligible_positions": collection([
            {"position": p} for p in display_position.split(",")
        ])},
    ]
    entity: list = [scalars]
    entity.append({"selected_position": [
        {"coverage_type": "week"},
        {"position": selected_slot},
    ]} if selected_slot else {"selected_position": [{"coverage_type": "week"}]})

    if stats is not None:
        entity.append({"player_stats": {
            "coverage_type": "week",
            "stats": collection([
                {"stat": {"stat_id": stat_id, "value": str(value)}}
                for stat_id, value in sorted(stats.items())
            ]),
        }})
    if points is not None:
        entity.append({"player_points": {"coverage_type": "week",
                                         "total": f"{points:.2f}"}})
    return entity


#: A full offensive stat line keyed by Yahoo stat id, matching the ids the
#: governed vocabulary declares. Every id here is one the artifact maps.
def stat_line(*, pass_yds=0, pass_td=0, ints=0, rush_att=0, rush_yds=0,
              rush_td=0, rec=0, rec_yds=0, rec_td=0, targets=0,
              fumbles_lost=0) -> dict[str, float]:
    return {
        "4": pass_yds, "5": pass_td, "6": ints,
        "8": rush_att, "9": rush_yds, "10": rush_td,
        "11": rec, "12": rec_yds, "13": rec_td,
        "18": fumbles_lost, "78": targets,
    }


def roster_payload(ordinal: int, week: int) -> dict:
    """One team's week roster.

    Deliberate conditions, each certifying something:
      * player 90001/90002 are TWO DIFFERENT PLAYERS WITH THE SAME NAME across
        two teams — C-4's same-name collision case, impossible to ingest while
        players.name was UNIQUE (recon R-4).
      * one BN player, to prove bench is excluded by slot, not by position.
      * one starter with stats=None on team 2 — the UNEVALUABLE case (C-12).
      * a W/R/T flex slot occupied by an RB, exercising the accepted FLEX rule.
    """
    base = ordinal * 100
    players = [
        player_entity(player_id=base + 1, name=f"Quarterback {ordinal}",
                      display_position="QB", nfl_team="KC",
                      selected_slot="QB",
                      stats=stat_line(pass_yds=250 + ordinal, pass_td=2,
                                      rush_att=3, rush_yds=12),
                      points=20.0 + ordinal),
        player_entity(player_id=base + 2, name=f"Runner {ordinal}",
                      display_position="RB", nfl_team="SF",
                      selected_slot="RB",
                      stats=stat_line(rush_att=18, rush_yds=88 + ordinal,
                                      rush_td=1, rec=3, rec_yds=21, targets=4),
                      points=15.0 + ordinal),
        player_entity(player_id=base + 3, name=f"Receiver {ordinal}",
                      display_position="WR", nfl_team="MIN",
                      selected_slot="WR",
                      stats=stat_line(rec=7, rec_yds=95 + ordinal, rec_td=1,
                                      targets=10),
                      points=18.0 + ordinal),
        # FLEX occupied by an RB — the accepted POR §1.3 "follows the actual
        # player" rule, which betting/pool_subjects.py resolves via
        # StatComponent.position.
        player_entity(player_id=base + 4, name=f"Flexer {ordinal}",
                      display_position="RB", nfl_team="DET",
                      selected_slot="W/R/T",
                      stats=stat_line(rush_att=9, rush_yds=41, rec=2,
                                      rec_yds=18, targets=3),
                      points=9.0),
        # BENCH. Must be excluded by SLOT — its position is a startable one, so
        # a filter reading display_position would wrongly include it.
        player_entity(player_id=base + 5, name=f"Benchwarmer {ordinal}",
                      display_position="WR", nfl_team="NYJ",
                      selected_slot="BN",
                      stats=stat_line(rec=11, rec_yds=180, rec_td=3,
                                      targets=14),
                      points=40.0),
    ]

    # SAME-NAME PLAYERS on teams 1 and 2 — different provider keys, one name.
    if ordinal in (1, 2):
        players.append(player_entity(
            player_id=90000 + ordinal, name="Josh Allen",
            display_position="QB" if ordinal == 1 else "DEF",
            nfl_team="BUF" if ordinal == 1 else "JAX",
            selected_slot="BN",
            stats=stat_line(), points=0.0))

    # A STARTED PLAYER THE FEED NEVER REPORTED — stats=None, points=None.
    if ordinal == 2:
        players.append(player_entity(
            player_id=base + 6, name=f"Unreported Starter {ordinal}",
            display_position="TE", nfl_team="BAL", selected_slot="TE",
            stats=None, points=None))
    else:
        players.append(player_entity(
            player_id=base + 6, name=f"TightEnd {ordinal}",
            display_position="TE", nfl_team="BAL", selected_slot="TE",
            stats=stat_line(rec=5, rec_yds=52, targets=6), points=8.0))

    # A player with NO selected_position at all — must be skipped, not
    # defaulted to a starter (normalize.py fails closed on an unknown slot).
    if ordinal == 3:
        players.append(player_entity(
            player_id=base + 7, name=f"Slotless {ordinal}",
            display_position="WR", nfl_team="LAR", selected_slot="",
            stats=stat_line(rec=4, rec_yds=44), points=6.0))

    return {
        "fantasy_content": {
            "team": [
                [
                    {"team_key": team_key(ordinal)},
                    {"team_id": str(ordinal)},
                    {"name": TEAM_NAMES[ordinal]},
                ],
                {"roster": {
                    "coverage_type": "week",
                    "week": str(week),
                    "0": {"players": collection([
                        {"player": p} for p in players])},
                }},
            ],
        },
    }


# ── Week definitions ──────────────────────────────────────────────────────────

#: Week 1 — a normal completed week. Three matchups, all postevent, distinct
#: scores, explicit winners.
WEEK1 = [
    dict(team_a=1, team_b=2, points_a=112.5, points_b=98.25, winner=1),
    dict(team_a=3, team_b=4, points_a=87.0, points_b=131.75, winner=4),
    dict(team_a=5, team_b=6, points_a=104.4, points_b=104.4, winner=None,
         is_tied=1),
]

#: Week 1 CONTRADICTED — identical pairings and finality, DIFFERENT scores.
WEEK1_CONTRADICTED = [
    dict(team_a=1, team_b=2, points_a=999.99, points_b=98.25, winner=1),
    dict(team_a=3, team_b=4, points_a=87.0, points_b=131.75, winner=4),
    dict(team_a=5, team_b=6, points_a=104.4, points_b=104.4, winner=None,
         is_tied=1),
]

#: Week 2 — the §7 truth table, one row per case.
WEEK2 = [
    # final 0-0 -> finalized_at MUST be set. The case a score-based reading
    # would misclassify as "not played".
    dict(status="postevent", team_a=1, team_b=2, points_a=0.0, points_b=0.0,
         winner=None, is_tied=1),
    # scores present, explicitly NOT final -> finalized_at stays NULL.
    dict(status="midevent", team_a=3, team_b=4, points_a=77.5, points_b=61.2),
    # not started -> NULL.
    dict(status="preevent", team_a=5, team_b=6, points_a=0.0, points_b=0.0),
]

#: Week 3 — the current week, fully final. The horizon boundary INSIDE.
WEEK3 = [
    dict(team_a=1, team_b=3, points_a=120.0, points_b=110.0, winner=1),
    dict(team_a=2, team_b=5, points_a=95.5, points_b=99.5, winner=5),
    dict(team_a=4, team_b=6, points_a=101.0, points_b=88.0, winner=4),
]

#: Week 4 — BEYOND current_week=3. Scheduled, preevent, must not be persisted.
WEEK4 = [
    dict(status="preevent", team_a=1, team_b=4, points_a=None, points_b=None),
    dict(status="preevent", team_a=2, team_b=6, points_a=None, points_b=None),
    dict(status="preevent", team_a=3, team_b=5, points_a=None, points_b=None),
]


def build_week(week: int, rows: list, *, mirrored: bool = False) -> dict:
    matchups = []
    for row in rows:
        spec = dict(row)
        spec.setdefault("status", "postevent")
        if mirrored:
            # SAME FACTS, OPPOSITE PAYLOAD ORDER. This is the C-5 fixture: if
            # anything downstream derived orientation or identity from list
            # position, this week would create a second row per matchup.
            spec["team_a"], spec["team_b"] = spec["team_b"], spec["team_a"]
            spec["points_a"], spec["points_b"] = (spec["points_b"],
                                                  spec["points_a"])
        matchups.append(matchup_entity(week=week, **spec))
    return scoreboard_payload(week, matchups)


def main() -> None:
    written = []

    def emit(fixture_id: str, endpoint: str, payload, *, week=None,
             notes: str | None = None, team_key_value: str | None = None):
        manifest = write_fixture(
            CORPUS_DIR, fixture_id=fixture_id, provenance=SYNTHETIC,
            layer="L1_RAW", endpoint=endpoint, league_key=LEAGUE_KEY,
            payload=payload, season=SEASON, week=week,
            captured_at=None, http_status=200,
            client_library="synthetic (no client library involved)",
            replay_now=REPLAY_NOW, notes=notes)
        # team_key is a fixture-selection field the replay transport filters on;
        # written into the manifest after construction so record.py's signature
        # stays endpoint-agnostic.
        if team_key_value:
            import json
            path = os.path.join(CORPUS_DIR, f"{fixture_id}.manifest.json")
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            data["team_key"] = team_key_value
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
        written.append((fixture_id, manifest.payload_sha256))
        return manifest

    emit("yahoo_league_w3", "league", league_payload(current_week=CURRENT_WEEK),
         notes="league metadata; current_week=3 defines the §6 ingestion horizon")
    emit("yahoo_teams", "teams", teams_payload(),
         notes="six teams with provider-stable compound keys; manager emails "
               "present so C-17 proves they are scrubbed")

    emit("yahoo_scoreboard_w1", "scoreboard", build_week(1, WEEK1), week=1,
         notes="normal completed week: three postevent matchups, one a tie")
    emit("yahoo_scoreboard_w1_mirrored", "scoreboard",
         build_week(1, WEEK1, mirrored=True), week=1,
         notes="C-5: identical facts, every matchup's teams listed in the "
               "opposite payload order")
    emit("yahoo_scoreboard_w1_contradicted", "scoreboard",
         build_week(1, WEEK1_CONTRADICTED), week=1,
         notes="C-8: same final matchups, matchup 1 reports a different score")
    emit("yahoo_scoreboard_w2", "scoreboard", build_week(2, WEEK2), week=2,
         notes="C-6 truth table: final 0-0, midevent with scores, preevent")
    emit("yahoo_scoreboard_w3", "scoreboard", build_week(3, WEEK3), week=3,
         notes="the current week, fully final — inside the §6 horizon")
    emit("yahoo_scoreboard_w4", "scoreboard", build_week(4, WEEK4), week=4,
         notes="C-11: week 4 is BEYOND current_week=3 and must not persist")

    # A matchup with NO status field at all — the §7 'absent/unknown' row. Kept
    # as its own single-matchup week so the unknown case cannot be confused with
    # the explicit non-final ones in week 2.
    emit("yahoo_scoreboard_w2_nostatus", "scoreboard",
         scoreboard_payload(2, [matchup_entity(
             week=2, status=None, team_a=1, team_b=2,
             points_a=88.0, points_b=91.0)]),
         week=2,
         notes="C-6: matchup carries scores but NO status field — finality "
               "absent/unknown, finalized_at must stay NULL")

    for ordinal in range(1, TEAM_COUNT + 1):
        emit(f"yahoo_roster_t{ordinal}_w1", "roster",
             roster_payload(ordinal, 1), week=1,
             team_key_value=team_key(ordinal),
             notes="week-1 selected_position slots, bench, flex, and (teams "
                   "1-2) a same-name player pair")

    # ── L2 NORMALIZED (§16) ──────────────────────────────────────────────────
    #
    # The serialized normalized DTO set, derived from the L1 payloads above by
    # running the real parser and normalizer. Its purpose is to certify
    # identity, finality and persistence INDEPENDENTLY of parser behavior: a
    # certification that only ever reached persistence through the parser could
    # not distinguish "persistence is correct" from "the parser and persistence
    # share a compensating bug".
    #
    # Generated rather than hand-written precisely so the two layers cannot
    # drift apart — but consumed through a separate code path in certification,
    # which is what makes the independence real.
    from providers.yahoo import normalize, parse  # noqa: E402

    for week, source_id in ((1, "yahoo_scoreboard_w1"),
                            (2, "yahoo_scoreboard_w2"),
                            (3, "yahoo_scoreboard_w3")):
        import json
        with open(os.path.join(CORPUS_DIR, f"{source_id}.json"),
                  encoding="utf-8") as handle:
            raw = json.load(handle)
        matchups = normalize.normalize_scoreboard(parse.parse_scoreboard(raw))
        emit(f"yahoo_normalized_w{week}", "normalized_week",
             {
                 "league_key": LEAGUE_KEY,
                 "season": SEASON,
                 "week": week,
                 "current_week": CURRENT_WEEK,
                 "matchups": [
                     {
                         "matchup_key": m.matchup_key,
                         "home_team_key": m.home_team_key,
                         "away_team_key": m.away_team_key,
                         "home_points": m.home_points,
                         "away_points": m.away_points,
                         "finality": m.finality.value,
                         "winner_team_key": m.winner_team_key,
                         "is_tied": m.is_tied,
                     }
                     for m in matchups
                 ],
             },
             week=week,
             notes="L2 normalized DTO set; certifies identity/finality/"
                   "persistence independently of the parser")
        # emit() defaults to L1_RAW; correct the layer on the manifest.
        path = os.path.join(CORPUS_DIR,
                            f"yahoo_normalized_w{week}.manifest.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        data["layer"] = "L2_NORMALIZED"
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")

    print(f"\n  Wrote {len(written)} SYNTHETIC fixtures to {CORPUS_DIR}\n")
    for fixture_id, digest in written:
        print(f"    {fixture_id:<38} sha256={digest}")
    print("\n  CAPTURED = 0   SYNTHETIC = %d" % len(written))
    print("  Live Yahoo payload parsing is NOT certified by this corpus.\n")


if __name__ == "__main__":
    main()