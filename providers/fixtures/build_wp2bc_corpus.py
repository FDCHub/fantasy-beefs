#!/usr/bin/env python3
"""Build the WP2B-C SYNTHETIC fixture corpus — the ECONOMIC-PROOF league.

WHY A SECOND LEAGUE RATHER THAN MORE WEEKS OF THE FIRST. The Sprint 6 corpus
(461.l.488800) was designed around the PROVIDER certification gates: finality
truth table, mirrored payloads, contradicted scores, horizon boundaries. It
carries roster and player-stat coverage for WEEK 1 ONLY, and week 1 there cannot
prove either economic outcome WP2B-C needs — there is no definition whose field
is fully evaluable with a single deterministic winner, and no week that produces
a genuine zero-winner rollover rather than a fail-closed refusal. Extending that
corpus would have meant editing fixtures whose bytes seventeen certification
gates are pinned to. A second league is additive: every existing manifest,
payload and SHA-256 is untouched.

PUBLICATION-SAFE IDENTITY, AND NOTHING ELSE. The league key is 999.l.100001,
teams are 999.l.100001.t.1 … t.6, players are 999.p.*. Game id 999 is not an
allocated Yahoo game id, and league number 100001 is not a real league. No real
league identifier, no real name, no email outside the reserved .invalid TLD, no
credential material of any kind. Every manifest declares provenance SYNTHETIC —
`providers/fixtures/record.capture_live()` remains the only function in the
repository able to write CAPTURED, and it needs a live transport this
environment cannot construct.

THE PAYLOADS ARE BUILT TO YAHOO'S DOCUMENTED ENVELOPE, in exactly the shape
providers/fixtures/build_corpus.py already uses: numeric-string-keyed
collections with a `count` sibling, entities as lists of single-key dicts,
numbers as strings. Building a tidier shape would certify the parser against its
own assumptions rather than against the documented protocol.

────────────────────────────────────────────────────────────────────────────────
WHAT EACH DELIBERATE DATA CHOICE PROVES
────────────────────────────────────────────────────────────────────────────────

THE DELIVERED STAT SET IS EXACTLY THREE YAHOO IDS: 4 (passing_yards),
6 (interceptions_thrown) and 18 (fumbles_lost). It is narrow on purpose. Gate-2
readiness is measured FROM THE PAYLOAD, so this set is what decides which
governed definitions this league can run at all — twelve of them, which is the
eligible set the deterministic rotation then ranks. Every one of those twelve is
fully evaluable from these three ids plus the matchup record, so no week can
settle on a partially-measured field.

NO `player_points` NODE IS EMITTED ANYWHERE. Fantasy points are a scored value
under the league's own scoring settings; this corpus deliberately does not claim
one. The consequence is measured rather than asserted: `player_fantasy_points`
and `kicking_points` report unsupported, and the four definitions that need them
stay out of the eligible set.

EVERY STARTER ON EVERY TEAM CARRIES ALL THREE IDS. That is what makes each team
frame affirmatively covered, which is what makes `subjects_evaluated ==
subjects_considered`, which is what makes a zero-winner outcome a GENUINE
ZERO_ELIGIBLE_CLAIMS rather than INCOMPLETE_FIELD or NO_EVALUABLE_SUBJECTS. The
distinction is the whole point of the second proof: both end in a rollover-shaped
absence of winners, and only one of them is a legitimate settlement.

WEEK 1 — most_passing_yards (#20, TEAM, RANK_EXTREMUM, MAX)
    Team starter passing yards descend 300 / 280 / 260 / 240 / 220 / 200, so the
    field is complete and the extremum is unique: team 1. THE BENCH IS THE
    DISCRIMINATOR. Team 6 benches a quarterback with 999 passing yards. An
    implementation that read the roster rather than the SELECTED SLOT would
    score team 6 at 1199 and hand it the win, so the assertion "team 1 won"
    fails loudly rather than passing for the wrong reason.

WEEK 1 — matchups_with_zero_total_turnovers (#87, MATCHUP, QUALIFIER)
    Combined turnovers per matchup are 2, 3 and 3. Every matchup is fully
    evaluable and NOT ONE qualifies, so the predicate legitimately selects
    nothing. Because the definition is rollover-eligible and week 1 is not the
    season's final week, the pot carries forward rather than sweeping — and the
    carry is then consumed as a week-2 continuation, which is the other half of
    the rollover claim.

WEEK 1 — the two remaining slate members are not incidental. #95
    (matchups_where_neither_team_threw_an_interception) is a second QUALIFIER
    with zero qualifiers, and #56 (highest_combined_passing_yards) is a
    RANK_EXTREMUM with a unique winner nobody picked. Between them the week
    exercises all three terminal shapes in one settlement: rollover, championship
    sweep, and distribution.

WEEK 2 — the FINALITY NEGATIVE. Two scoreboards describe the same three
    matchups: `..._w2_pending` reports them `midevent`, and `..._w2` reports them
    `postevent` with identical scores. Identical scores are the load-bearing
    detail. Finality must be decided by `finalized_at` and nothing else (§7), so
    a fixture pair that ALSO changed the score would let a score-watching
    implementation pass. Ingesting the pending payload first leaves three rows
    with scores, a live pot and `finalized_at IS NULL`; ingesting the final one
    afterwards moves exactly one fact.

RUN:
    python providers/fixtures/build_wp2bc_corpus.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from providers.fixtures.record import SYNTHETIC, write_fixture  # noqa: E402

CORPUS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus")

#: Publication-safe identity. Game id 999 is not an allocated Yahoo game id.
GAME_ID = 999
LEAGUE_NUMBER = "100001"
LEAGUE_KEY = f"{GAME_ID}.l.{LEAGUE_NUMBER}"
SEASON = 2025
#: Weeks 1 and 2 are both inside the §6 ingestion horizon; nothing beyond is.
CURRENT_WEEK = 2
END_WEEK = 17
PLAYOFF_START_WEEK = 15

#: The same frozen replay instant the Sprint 6 corpus declares. Sharing it means
#: adding this league changes nothing about `FixtureTransport.observed_at()` for
#: any existing suite, whichever fixture the corpus scan happens to reach first.
REPLAY_NOW = "2025-09-23T12:00:00+00:00"

TEAM_COUNT = 6
TEAM_NAMES = {
    1: "Proof Of Concept",
    2: "Ledger Legends",
    3: "Trial Balance",
    4: "Double Entry",
    5: "Conservation Law",
    6: "Settled Science",
}

#: The three governed Yahoo stat ids this corpus delivers, and nothing else.
STAT_PASSING_YARDS = "4"
STAT_INTERCEPTIONS_THROWN = "6"
STAT_FUMBLES_LOST = "18"

#: A fixture-only prefix, chosen so these files sort AFTER every Sprint 6
#: fixture in the corpus directory listing and the two sets stay visually
#: separate in review.
PREFIX = "yahoo_wp2bc"


def team_key(ordinal: int) -> str:
    return f"{LEAGUE_KEY}.t.{ordinal}"


# ── Yahoo envelope builders (documented shape, not a convenient one) ──────────

def collection(items: list) -> dict:
    """Yahoo's numeric-string-keyed collection with its `count` sibling."""
    out: dict = {str(index): item for index, item in enumerate(items)}
    out["count"] = len(items)
    return out


def team_entity(ordinal: int, *, points: float | None = None) -> list:
    """One team in Yahoo's [[scalars...], {sub-resource}] entity shape."""
    scalars = [
        {"team_key": team_key(ordinal)},
        {"team_id": str(ordinal)},
        {"name": TEAM_NAMES[ordinal]},
        {"managers": collection([
            {"manager": [
                {"manager_id": str(ordinal)},
                {"nickname": f"GM{ordinal}"},
                # Present so C-17 proves the scrubber removes it, and inside the
                # reserved .invalid TLD so it could never route anywhere.
                {"email": f"gm{ordinal}@example.invalid"},
            ]},
        ])},
    ]
    entity: list = [scalars]
    if points is not None:
        entity.append({"team_points": {"coverage_type": "week",
                                       "total": f"{points:.2f}"}})
    return entity


def matchup_entity(*, week: int, status: str, team_a: int, team_b: int,
                   points_a: float, points_b: float,
                   winner: int | None = None, is_tied: int = 0) -> dict:
    scalars: dict = {"week": str(week), "is_tied": is_tied, "status": status}
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


def league_payload() -> dict:
    return {
        "fantasy_content": {
            "league": [
                {
                    "league_key": LEAGUE_KEY,
                    "league_id": LEAGUE_NUMBER,
                    "name": "WP2B-C Economic Proof League",
                    "season": str(SEASON),
                    "current_week": str(CURRENT_WEEK),
                    "start_week": "1",
                    "end_week": str(END_WEEK),
                    "playoff_start_week": str(PLAYOFF_START_WEEK),
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
                 "name": "WP2B-C Economic Proof League",
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
                 "name": "WP2B-C Economic Proof League",
                 "season": str(SEASON), "current_week": str(CURRENT_WEEK)},
                {"scoreboard": {
                    "week": str(week),
                    "0": {"matchups": collection(matchups)},
                }},
            ],
        },
    }


# ── Player / roster construction ─────────────────────────────────────────────

def stat_line(*, passing_yards: float = 0.0, interceptions: float = 0.0,
              fumbles_lost: float = 0.0) -> dict[str, float]:
    """The three delivered ids, ALWAYS all three.

    Emitting every id for every starter is what makes each team frame's
    affirmative coverage identical, so an unevaluable subject anywhere in this
    corpus would be a real ingestion failure rather than a modelled data gap.
    """
    return {
        STAT_PASSING_YARDS: passing_yards,
        STAT_INTERCEPTIONS_THROWN: interceptions,
        STAT_FUMBLES_LOST: fumbles_lost,
    }


def player_entity(*, player_id: int, name: str, display_position: str,
                  nfl_team: str, selected_slot: str,
                  stats: dict[str, float]) -> list:
    """One roster player. NO `player_points` node is ever emitted — see module
    docstring; this corpus does not claim a scored fantasy-points value."""
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
    return [
        scalars,
        {"selected_position": [
            {"coverage_type": "week"},
            {"position": selected_slot},
        ]},
        {"player_stats": {
            "coverage_type": "week",
            "stats": collection([
                {"stat": {"stat_id": stat_id, "value": str(value)}}
                for stat_id, value in sorted(stats.items())
            ]),
        }},
    ]


#: Per-team, per-week starter facts. `passing` is the team's whole passing total
#: and sits on the quarterback; `ints` and `fumbles` likewise. `bench_passing`
#: is the DISCRIMINATOR: a bench quarterback whose yards must never be counted.
WEEK_FACTS: dict[int, dict[int, dict]] = {
    1: {
        1: dict(passing=300.0, ints=1.0, fumbles=0.0, bench_passing=0.0),
        2: dict(passing=280.0, ints=0.0, fumbles=1.0, bench_passing=0.0),
        3: dict(passing=260.0, ints=1.0, fumbles=1.0, bench_passing=0.0),
        4: dict(passing=240.0, ints=0.0, fumbles=0.0, bench_passing=0.0),
        5: dict(passing=220.0, ints=2.0, fumbles=0.0, bench_passing=0.0),
        # 200 + 999 = 1199 would beat team 1's 300 if the bench were counted.
        6: dict(passing=200.0, ints=0.0, fumbles=1.0, bench_passing=999.0),
    },
    2: {
        1: dict(passing=210.0, ints=1.0, fumbles=1.0, bench_passing=0.0),
        2: dict(passing=200.0, ints=1.0, fumbles=0.0, bench_passing=0.0),
        3: dict(passing=190.0, ints=1.0, fumbles=0.0, bench_passing=0.0),
        4: dict(passing=180.0, ints=0.0, fumbles=1.0, bench_passing=0.0),
        5: dict(passing=170.0, ints=2.0, fumbles=1.0, bench_passing=0.0),
        6: dict(passing=160.0, ints=1.0, fumbles=2.0, bench_passing=0.0),
    },
}


def roster_payload(ordinal: int, week: int) -> dict:
    """One team's week roster: four starters, one bench.

    Slots are QB / RB / WR / TE plus BN. The bench player's position is a
    STARTABLE one, so a filter reading `display_position` instead of the weekly
    `selected_position` would wrongly include it — which is precisely what the
    week-1 team-6 bench discriminator is there to catch.
    """
    facts = WEEK_FACTS[week][ordinal]
    base = week * 1000 + ordinal * 100
    players = [
        player_entity(
            player_id=base + 1, name=f"Quarterback {ordinal}",
            display_position="QB", nfl_team="KC", selected_slot="QB",
            stats=stat_line(passing_yards=facts["passing"],
                            interceptions=facts["ints"],
                            fumbles_lost=facts["fumbles"])),
        player_entity(
            player_id=base + 2, name=f"Runner {ordinal}",
            display_position="RB", nfl_team="SF", selected_slot="RB",
            stats=stat_line()),
        player_entity(
            player_id=base + 3, name=f"Receiver {ordinal}",
            display_position="WR", nfl_team="MIN", selected_slot="WR",
            stats=stat_line()),
        player_entity(
            player_id=base + 4, name=f"TightEnd {ordinal}",
            display_position="TE", nfl_team="BAL", selected_slot="TE",
            stats=stat_line()),
        player_entity(
            player_id=base + 5, name=f"Benched Passer {ordinal}",
            display_position="QB", nfl_team="NYJ", selected_slot="BN",
            stats=stat_line(passing_yards=facts["bench_passing"])),
    ]

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


# ── Week schedules ───────────────────────────────────────────────────────────

#: Week 1 — three matchups, all postevent. Combined turnovers 2 / 3 / 3, so NO
#: matchup satisfies the zero-turnover predicate and none satisfies the
#: zero-interception one either. Combined passing yards 580 / 500 / 420, a
#: unique MATCHUP extremum.
WEEK1 = [
    dict(team_a=1, team_b=2, points_a=120.50, points_b=98.25, winner=1),
    dict(team_a=3, team_b=4, points_a=87.00, points_b=131.75, winner=4),
    dict(team_a=5, team_b=6, points_a=104.40, points_b=99.60, winner=5),
]

#: Week 2 — different pairings, so the week is a real second week rather than a
#: repeat. Combined turnovers 3 / 4 / 4 (unique MIN at matchup 1) and combined
#: scores 220.00 / 195.00 / 215.00 (unique MAX at matchup 1).
WEEK2 = [
    dict(team_a=1, team_b=3, points_a=130.00, points_b=90.00, winner=1),
    dict(team_a=2, team_b=5, points_a=100.00, points_b=95.00, winner=2),
    dict(team_a=4, team_b=6, points_a=110.00, points_b=105.00, winner=4),
]


def build_week(week: int, rows: list, *, status: str) -> dict:
    matchups = []
    for row in rows:
        spec = dict(row)
        if status != "postevent":
            # A non-final matchup declares no winner. Yahoo does not report one
            # mid-event, and inventing one here would make the pending fixture
            # differ from the final one in TWO facts instead of one.
            spec.pop("winner", None)
        matchups.append(matchup_entity(week=week, status=status, **spec))
    return scoreboard_payload(week, matchups)


def main() -> None:
    written: list[tuple[str, str]] = []

    def emit(fixture_id: str, endpoint: str, payload, *, week=None,
             notes: str, team_key_value: str | None = None):
        manifest = write_fixture(
            CORPUS_DIR, fixture_id=fixture_id, provenance=SYNTHETIC,
            layer="L1_RAW", endpoint=endpoint, league_key=LEAGUE_KEY,
            payload=payload, season=SEASON, week=week,
            captured_at=None, http_status=200,
            client_library="synthetic (no client library involved)",
            replay_now=REPLAY_NOW, notes=notes)
        # `team_key` is a fixture-SELECTION field the replay transport filters
        # on. Written after construction so record.write_fixture's signature
        # stays endpoint-agnostic — the same convention build_corpus.py uses.
        if team_key_value:
            path = os.path.join(CORPUS_DIR, f"{fixture_id}.manifest.json")
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            data["team_key"] = team_key_value
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
        written.append((fixture_id, manifest.payload_sha256))

    emit(f"{PREFIX}_league", "league", league_payload(),
         notes="WP2B-C economic-proof league; current_week=2 puts weeks 1 and 2 "
               "inside the §6 ingestion horizon and nothing beyond")
    emit(f"{PREFIX}_teams", "teams", teams_payload(),
         notes="six teams with provider-stable compound keys under the "
               "publication-safe 999.l.100001 identity; manager emails present "
               "so C-17 proves they are scrubbed")

    emit(f"{PREFIX}_scoreboard_w1", "scoreboard",
         build_week(1, WEEK1, status="postevent"), week=1,
         notes="week 1, fully final: the winner-settlement and genuine "
               "zero-winner/rollover week")
    emit(f"{PREFIX}_scoreboard_w2", "scoreboard",
         build_week(2, WEEK2, status="postevent"), week=2,
         notes="week 2 FINAL: the positive half of the finality proof")
    emit(f"{PREFIX}_scoreboard_w2_pending", "scoreboard",
         build_week(2, WEEK2, status="midevent"), week=2,
         notes="week 2 NOT FINAL: identical scores, midevent status. Identical "
               "scores are load-bearing — a fixture that also changed the score "
               "would let a score-watching implementation pass the finality "
               "negative")

    for week in (1, 2):
        for ordinal in range(1, TEAM_COUNT + 1):
            emit(f"{PREFIX}_roster_t{ordinal}_w{week}", "roster",
                 roster_payload(ordinal, week), week=week,
                 team_key_value=team_key(ordinal),
                 notes=f"week-{week} selected_position slots; exactly three "
                       f"governed stat ids (4/6/18) on every starter, no "
                       f"player_points node, and a BENCHED quarterback whose "
                       f"yards must never be counted")

    print(f"\n  Wrote {len(written)} SYNTHETIC fixtures to {CORPUS_DIR}\n")
    for fixture_id, digest in written:
        print(f"    {fixture_id:<34} sha256={digest}")
    print(f"\n  league_key = {LEAGUE_KEY}   provenance = SYNTHETIC (all)")
    print("  No real league identifier, name, email, credential or token.\n")


if __name__ == "__main__":
    main()