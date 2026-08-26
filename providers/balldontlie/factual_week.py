"""Sprint 6 · BALLDONTLIE facts -> CSPS FACTUAL components.

WHAT THIS IS. Sprint 3 proved CSPS can reproduce Yahoo's scoreboard exactly
when it is handed the right components. Sprint 5B proved the play stream can be
read correctly. This module is the join: it turns what BALLDONTLIE actually
reports about a finished NFL week into the component vocabulary CSPS scores,
for every subject a fantasy lineup can hold.

── THE CENTRAL FINDING, AND WHY THIS MODULE READS TWO ENDPOINTS ────────────

A kicker's summary row cannot score a kicker. Measured across 479 real kicker
game-rows, `/stats` reports exactly five kicking fields:

    field_goal_attempts, field_goals_made, field_goal_pct,
    long_field_goal_made, extra_points_made

Mr Whiskers pays 3, 4 or 5 points for a made field goal by DISTANCE BAND, and
-1 for a miss inside 40. CULV pays 0.1 per YARD of made field goals. Neither
number is recoverable from a count and a longest. `long_field_goal_made = 34`
tells you nothing about the other two attempts, and `extra_point_attempts` is
not reported at all, so a missed extra point — worth -3.14 in Mr Whiskers — is
invisible in summary.

So exact kicker scoring comes from PLAYS, where `stat_yardage` carries the
distance of every attempt and the `field_goal_kicker` / `xp_kicker`
participants carry identity. The summary row is retained as an INDEPENDENT
CROSS-CHECK, never as a second source of points: if the two disagree the
subject is reported KICKER_RECONCILIATION_FAILED and scores nothing, because a
disagreement means one of them is wrong and nothing here can say which.

── WHAT COMES FROM WHERE ───────────────────────────────────────────────────

    passing / rushing / receiving / fumbles     /stats   (summary is exact)
    field goals by distance, extra points       /plays   (summary cannot)
    pick-six thrown                             /plays   (structural slug)
    three-and-outs forced                       /plays   (drive classifier)
    DST sacks / INT / fumble recoveries         /stats   summed over the team
    DST touchdowns, safeties, blocked kicks     /plays   (event-level)
    points allowed                              /games   (opponent score)

── ZERO IS NOT ABSENCE, AND THIS MODULE KEEPS THEM APART ───────────────────

BALLDONTLIE omits every zero-valued field, so a kicker who missed nothing
carries no `field_goals_missed` key at all. On a FACTUAL line that omission IS
a zero — the player was measured and did not do it — which is why every subject
here declares `components_present` covering its whole vocabulary once the
underlying evidence is known to be complete. What is NOT a zero is evidence
that never arrived: a game with no play data cannot say whether a kicker missed
from 45, and that subject is refused rather than scored as though he did not.

── NO PROJECTION MODEL EVER TOUCHES A FACTUAL LINE ─────────────────────────

`reception-model-v2`, `pick-six-model-v2`, `three-and-out-model-v2` and
`drives-model-v1` are projection machinery. A factual pick-six is COUNTED, not
estimated; a factual three-and-out is CLASSIFIED, not multiplied by a rate.
Nothing in this module imports `scoring.history` or `scoring.iprm`, and the
Sprint 6 suite asserts that.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from providers.balldontlie import factual as F
from providers.balldontlie_identity import defense_key, player_key

__all__ = [
    "Diagnostic",
    "KickerEvidence",
    "SubjectFacts",
    "FactualWeek",
    "kicker_events",
    "reconcile_kicker",
    "build_factual_week",
    "evidence_fingerprint",
]


class Diagnostic:
    """Named refusal reasons. An operator reads these, so they say what is wrong."""

    MISSING_PLAY_DATA = "MISSING_PLAY_DATA"
    MISSING_FINAL_STATS = "MISSING_FINAL_STATS"
    MISSING_PLAYER_IDENTITY = "MISSING_PLAYER_IDENTITY"
    KICKER_RECONCILIATION_FAILED = "KICKER_RECONCILIATION_FAILED"
    DST_RECONCILIATION_FAILED = "DST_RECONCILIATION_FAILED"
    UNKNOWN_DRIVE_EVENTS = "UNKNOWN_DRIVE_EVENTS"
    PROVIDER_NOT_FINAL = "PROVIDER_NOT_FINAL"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_CORRECTION_PENDING = "PROVIDER_CORRECTION_PENDING"


# ── game finality ────────────────────────────────────────────────────────────

#: Values of `status_state` BALLDONTLIE uses for a completed game. Measured on
#: the 2024-2025 corpus, where every one of 544 completed games carried
#: `status='Final'` with `status_state='final'`.
FINAL_STATES = frozenset({"final"})


def game_is_final(game: Mapping[str, Any]) -> bool:
    """Provider-DECLARED finality, never inferred.

    A non-null score does not mean final: a game leads 21-17 at half with both
    numbers populated. Elapsed time does not mean final either. Only the
    provider's own status field is read, which is the same discipline
    `providers/finality.py` applies to Yahoo.
    """
    state = str(game.get("status_state") or "").strip().lower()
    if state:
        return state in FINAL_STATES
    return str(game.get("status") or "").strip().lower().startswith("final")


# ── kickers ──────────────────────────────────────────────────────────────────

_FG_MADE_SLUGS = frozenset({"field-goal-good"})
_FG_MISS_SLUGS = frozenset({"field-goal-missed", "blocked-field-goal",
                            "field-goal-blocked"})
_GOOD = re.compile(r"\bis GOOD\b", re.I)
_NO_GOOD = re.compile(r"\b(is No Good|No Good|MISSED|is Blocked|BLOCKED)\b", re.I)
_XP_GOOD = re.compile(r"extra point is GOOD", re.I)
_XP_BAD = re.compile(r"extra point (is No Good|No Good|MISSED|is Blocked|is Aborted)",
                     re.I)

# THE PROVIDER WRITES EXTRA POINTS TWO WAYS. Beside the play-by-play sentence
# there is a box-score form — "(Jason Myers Kick)" for a conversion,
# "(Brandon McManus PAT blocked)" for a failure — used on 20 of 2025's
# conversions. Reading only the first form left those kickers a point short and
# failed their summary cross-check.
_XP_BOX_GOOD = re.compile(r"\([^)]*Kick\)", re.I)
_XP_BOX_BAD = re.compile(r"\([^)]*PAT[^)]*(blocked|failed|missed|no good)\)",
                         re.I)

#: A BLOCKED FIELD GOAL CARRIES ITS DISTANCE IN THE PROSE AND NOT IN
#: `stat_yardage` — "J.Romo 37 yard field goal is BLOCKED". Thirteen of 2025's
#: attempts looked distanceless for this reason alone. The number is the
#: provider's own, read from its own sentence, not inferred from field position.
_FG_TEXT_DISTANCE = re.compile(r"(\d{1,2})\s*yard field goal", re.I)

#: The distance bands both certified profiles use.
BANDS = (("0_to_39", 0, 39), ("40_to_49", 40, 49), ("50_plus", 50, 10_000))

#: The FINER bands the governed pool vocabulary uses. Exact distances are
#: already in hand, so emitting both costs nothing and saves the pool boundary
#: from having to split a band it was never given.
POOL_BANDS = (("0_19", 0, 19), ("20_29", 20, 29), ("30_39", 30, 39),
              ("40_49", 40, 49), ("50_plus", 50, 10_000))


def _band(distance: float) -> str:
    for name, low, high in BANDS:
        if low <= distance <= high:
            return name
    return BANDS[-1][0]


@dataclass
class KickerEvidence:
    """Every kicking event one kicker produced in one game, from the plays."""

    provider_player_key: str
    field_goals_made: list = field(default_factory=list)     # distances
    field_goals_missed: list = field(default_factory=list)   # distances
    extra_points_made: int = 0
    extra_points_missed: int = 0
    #: attempts whose distance the stream did not carry — these make the
    #: kicker unscoreable rather than silently dropped.
    undistanced_attempts: int = 0

    def components(self) -> dict:
        out: dict = {
            "field_goals_made": float(len(self.field_goals_made)),
            "field_goal_attempts": float(len(self.field_goals_made)
                                         + len(self.field_goals_missed)),
            "field_goals_made_yards": float(sum(self.field_goals_made)),
            "field_goals_missed": float(len(self.field_goals_missed)),
            "extra_points_made": float(self.extra_points_made),
            "extra_points_missed": float(self.extra_points_missed),
            "extra_point_attempts": float(self.extra_points_made
                                          + self.extra_points_missed),
        }
        for name, _, _ in BANDS:
            out[f"field_goals_made_{name}"] = 0.0
            out[f"field_goals_missed_{name}"] = 0.0
        for d in self.field_goals_made:
            out[f"field_goals_made_{_band(d)}"] += 1.0
        for d in self.field_goals_missed:
            out[f"field_goals_missed_{_band(d)}"] += 1.0
        for name, low, high in POOL_BANDS:
            out[f"field_goals_made_{name}"] = float(
                sum(1 for d in self.field_goals_made if low <= d <= high))
        return out


#: Any extra-point outcome, made or not. Used to find conversions the provider
#: describes in prose but does not attach a participant to.
_XP_ANY = re.compile(r"extra point (is GOOD|is No Good|No Good|MISSED|"
                     r"is Blocked|is Aborted)", re.I)


def kicker_events(plays: Sequence, *, team_of: Mapping[str, str] | None = None
                  ) -> dict:
    """Play stream -> {provider_player_key: KickerEvidence}.

    FIELD GOALS come from their own plays and carry `stat_yardage` as the
    attempt distance. EXTRA POINTS DO NOT HAVE THEIR OWN PLAY: the provider
    attaches an `xp_kicker` participant to the TOUCHDOWN play and writes the
    outcome into that play's text.

    ── THE EXTRA POINTS WITH NO PARTICIPANT ────────────────────────────────

    On a RETURN touchdown the provider names the conversion in the text and
    attaches no `xp_kicker` at all — 34 of 1,242 extra-point plays across 2025.
    Left alone, each one silently costs its kicker a point and fails the
    summary cross-check, which refused 12% of all kicker game-lines.

    They are attributed STRUCTURALLY, never from the prose. WP1 forbids
    name-only identity in a path that settles money, so the kicker's name in
    the sentence is not read. What is read is `play.team` — the scoring team on
    these slugs — plus `team_of`, the caller's map of kicker identity to team
    taken from the same game's stat rows. A team fields one placekicker; if
    exactly one is known for the scoring team, the conversion is his. If none
    or several are, the attempt stays unattributed and the kicker refuses.
    """
    out: dict = {}
    team_of = dict(team_of or {})

    def entry(pid) -> KickerEvidence:
        key = pid if isinstance(pid, str) else player_key(pid)
        if key not in out:
            out[key] = KickerEvidence(provider_player_key=key)
        return out[key]

    orphan_xp: list = []

    for play in F.ordered_plays(plays):
        raw = play.raw if isinstance(play.raw, Mapping) else {}
        text = play.text or ""
        kickers = play.participant_ids("field_goal_kicker")
        if kickers and (play.type in _FG_MADE_SLUGS or play.type in _FG_MISS_SLUGS):
            ev = entry(kickers[0])
            distance = raw.get("stat_yardage")
            made = play.type in _FG_MADE_SLUGS
            # the text is a second opinion on the outcome; the slug is the first
            if made and _NO_GOOD.search(text) and not _GOOD.search(text):
                made = False
            if not isinstance(distance, (int, float)) or distance <= 0:
                stated = _FG_TEXT_DISTANCE.search(text)
                distance = float(stated.group(1)) if stated else None
            if not isinstance(distance, (int, float)) or distance <= 0:
                ev.undistanced_attempts += 1
                continue
            (ev.field_goals_made if made else ev.field_goals_missed).append(
                float(distance))

        attached = play.participant_ids("xp_kicker")
        for pid in attached:
            ev = entry(pid)
            if _XP_BAD.search(text) or _XP_BOX_BAD.search(text):
                ev.extra_points_missed += 1
            elif _XP_GOOD.search(text) or _XP_BOX_GOOD.search(text):
                ev.extra_points_made += 1
            else:
                # an xp_kicker with no readable outcome is not a made kick
                ev.undistanced_attempts += 1

        if not attached and (_XP_ANY.search(text)
                             or _XP_BOX_GOOD.search(text)
                             or _XP_BOX_BAD.search(text)):
            orphan_xp.append(((play.team or {}).get("abbreviation"),
                              bool(_XP_BAD.search(text)
                                   or _XP_BOX_BAD.search(text))))

    if orphan_xp:
        by_team: dict = {}
        for key, team in team_of.items():
            by_team.setdefault(team, set()).add(key)
        for team, missed in orphan_xp:
            candidates = by_team.get(team) or set()
            if len(candidates) == 1:
                ev = entry(next(iter(candidates)))
                if missed:
                    ev.extra_points_missed += 1
                else:
                    ev.extra_points_made += 1
            else:
                # nobody to attribute it to, or an ambiguous choice: this is
                # unresolved evidence, and it fails the team's kicker closed.
                for key in candidates:
                    entry(key).undistanced_attempts += 1
                if not candidates and team:
                    orphan = entry("unattributed.xp." + str(team))
                    orphan.undistanced_attempts += 1
    return out


def reconcile_kicker(evidence: KickerEvidence, summary: Mapping[str, Any]
                     ) -> tuple[bool, str]:
    """Cross-check play-derived kicking against the summary row.

    THE SUMMARY IS A WITNESS, NOT A SOURCE. Its counts are compared to the
    counts the plays produced; agreement raises confidence and disagreement
    refuses. What is deliberately NOT done is picking whichever number is
    larger, or falling back to the summary when the plays look thin — either
    would turn a data conflict into a silently wrong score.
    """
    if evidence.undistanced_attempts:
        return False, (f"{evidence.undistanced_attempts} kicking attempt(s) "
                       f"carried no readable distance or outcome")
    if not summary:
        return True, "no summary row to cross-check against"

    made = len(evidence.field_goals_made)
    attempts = made + len(evidence.field_goals_missed)
    s_made = summary.get("field_goals_made")
    s_att = summary.get("field_goal_attempts")
    s_xp = summary.get("extra_points_made")

    problems = []
    if isinstance(s_made, (int, float)) and int(s_made) != made:
        problems.append(f"made {made} from plays vs {int(s_made)} in summary")
    if isinstance(s_att, (int, float)) and int(s_att) != attempts:
        problems.append(f"attempts {attempts} from plays vs {int(s_att)} in summary")
    if isinstance(s_xp, (int, float)) and int(s_xp) != evidence.extra_points_made:
        problems.append(f"extra points {evidence.extra_points_made} from plays "
                        f"vs {int(s_xp)} in summary")
    if problems:
        return False, "; ".join(problems)

    # the longest made field goal is a third, independent check
    s_long = summary.get("long_field_goal_made")
    if (isinstance(s_long, (int, float)) and s_long
            and evidence.field_goals_made
            and int(max(evidence.field_goals_made)) != int(s_long)):
        return False, (f"longest made {int(max(evidence.field_goals_made))} from "
                       f"plays vs {int(s_long)} in summary")
    return True, "play and summary evidence agree"


# ── offence ──────────────────────────────────────────────────────────────────

#: `/stats` field -> CSPS component. Only fields whose meaning is exact are
#: mapped; a field this table does not name is not silently invented.
STAT_TO_COMPONENT: Mapping[str, str] = {
    "passing_yards": "passing_yards",
    "passing_touchdowns": "passing_touchdowns",
    "passing_interceptions": "passing_interceptions",
    "rushing_yards": "rushing_yards",
    "rushing_touchdowns": "rushing_touchdowns",
    "receptions": "receptions",
    "receiving_yards": "receiving_yards",
    "receiving_touchdowns": "receiving_touchdowns",
    "fumbles_lost": "fumbles_lost",
}

OFFENSIVE_COMPONENTS = frozenset(STAT_TO_COMPONENT.values())


def offensive_components(row: Mapping[str, Any]) -> dict:
    """One `/stats` row -> the offensive components CSPS scores.

    An absent field is a ZERO here and that is correct: the row exists, so the
    player was measured, and BALLDONTLIE omits what did not happen. Absence of
    the ROW is the different thing, and is handled by the caller.
    """
    out = {name: 0.0 for name in OFFENSIVE_COMPONENTS}
    for source, component in STAT_TO_COMPONENT.items():
        value = row.get(source)
        if isinstance(value, (int, float)):
            out[component] = float(value)
    return out


# ── team defence ─────────────────────────────────────────────────────────────

_DEF_TD_SLUGS = frozenset({"interception-return-touchdown",
                           "fumble-return-touchdown"})
#: Touchdowns Yahoo does NOT charge to the defence that was not on the field.
#: Measured in week 17: New Orleans scored 34 against Tennessee, six of them on
#: a fumble return, and Yahoo charged Tennessee 28.
_NON_OFFENSIVE_TD_SLUGS = frozenset({"interception-return-touchdown",
                                     "fumble-return-touchdown",
                                     "kickoff-return-touchdown",
                                     "punt-return-touchdown",
                                     "blocked-punt-touchdown",
                                     "blocked-field-goal-touchdown"})

_RETURN_TD_SLUGS = frozenset({"kickoff-return-touchdown",
                              "punt-return-touchdown",
                              "blocked-punt-touchdown",
                              "blocked-field-goal-touchdown"})
#: A fumble the OTHER team recovers. `play.team` is the recovering side on
#: each of these, which is what makes them readable without possession context.
_OPPONENT_RECOVERY_SLUGS = frozenset({"fumble-recovery-opponent",
                                      "sack-opp-fumble-recovery",
                                      "muffed-punt-recovery-opponent"})

_BLOCK_SLUGS = frozenset({"blocked-punt", "blocked-field-goal",
                          "field-goal-blocked", "blocked-punt-touchdown",
                          "blocked-field-goal-touchdown"})



def _scored_touchdown(play) -> bool:
    """Did this play put six on the board? The flag first, the word second."""
    raw = play.raw if isinstance(play.raw, Mapping) else {}
    if not raw.get("scoring_play"):
        return False
    return "TOUCHDOWN" in (play.text or "").upper()


def defense_components(*, team: str, opponent: str, plays: Sequence,
                       team_stat_rows: Iterable[Mapping[str, Any]],
                       points_allowed: float | None) -> tuple[dict, list]:
    """Team-defence components, from the summary rows AND the play stream.

    THE TWO SOURCES ARE USED FOR DIFFERENT THINGS, WHICH IS HOW DOUBLE-COUNTING
    IS AVOIDED. Sacks, interceptions and fumble recoveries are per-player
    counting stats and are SUMMED from that team's `/stats` rows. Touchdowns,
    safeties and blocked kicks are EVENTS and are counted once each from the
    plays. No quantity is taken from both.
    """
    notes: list = []
    out = {
        "defensive_sacks": 0.0,
        "defensive_interceptions": 0.0,
        "opponent_fumble_recoveries": 0.0,
        "interception_return_touchdowns": 0.0,
        "fumble_return_touchdowns": 0.0,
        "turnover_return_touchdowns": 0.0,
        "kick_return_touchdowns": 0.0,
        "punt_return_touchdowns": 0.0,
        "defensive_safeties": 0.0,
        "kicks_blocked": 0.0,
        "two_point_returns": 0.0,
        "dst_three_and_outs": 0.0,
    }
    # SACKS AND INTERCEPTIONS come from the per-player summary rows. Both are
    # counting stats the provider attributes to individuals, and summing them
    # is the only team total on offer. See the module note on the sack residual.
    for row in team_stat_rows:
        for source, component in (("defensive_sacks", "defensive_sacks"),
                                  ("defensive_interceptions",
                                   "defensive_interceptions")):
            value = row.get(source)
            if isinstance(value, (int, float)):
                out[component] += float(value)

    # FUMBLE RECOVERIES COME FROM THE PLAYS, NOT THE SUMMARY. `fumbles_recovered`
    # on a stat row includes a player recovering his OWN team's fumble — in
    # week 17 the two such rows belonged to quarterbacks — and that is not a
    # takeaway. The stream names the opponent recovery explicitly.
    for play in F.ordered_plays(plays):
        if play.type in _OPPONENT_RECOVERY_SLUGS:
            if (play.team or {}).get("abbreviation") == team:
                out["opponent_fumble_recoveries"] += 1.0

    for play in F.ordered_plays(plays):
        slug = play.type
        scoring_team = (play.team or {}).get("abbreviation")
        # A SACK-FUMBLE RETURNED FOR SIX HAS NO TOUCHDOWN SLUG OF ITS OWN. The
        # provider calls it `sack-opp-fumble-recovery` whether it ended at the
        # spot or in the end zone, so the scoring flag and the word in the text
        # are what separate them. Week 17: New Orleans scored exactly this way
        # and Yahoo paid the Saints for a defensive touchdown.
        if (slug in _OPPONENT_RECOVERY_SLUGS and scoring_team == team
                and _scored_touchdown(play)):
            out["fumble_return_touchdowns"] += 1.0
            out["turnover_return_touchdowns"] += 1.0
        if slug in _DEF_TD_SLUGS and scoring_team == team:
            if slug == "interception-return-touchdown":
                out["interception_return_touchdowns"] += 1.0
            else:
                out["fumble_return_touchdowns"] += 1.0
            out["turnover_return_touchdowns"] += 1.0
        elif slug in _RETURN_TD_SLUGS and scoring_team == team:
            if "punt" in slug:
                out["punt_return_touchdowns"] += 1.0
            elif "kickoff" in slug:
                out["kick_return_touchdowns"] += 1.0
        if slug == "safety" and scoring_team == team:
            out["defensive_safeties"] += 1.0
        if slug in _BLOCK_SLUGS and scoring_team == team:
            out["kicks_blocked"] += 1.0

    if points_allowed is not None:
        excluded = 0.0
        for play in F.ordered_plays(plays):
            scored_by = (play.team or {}).get("abbreviation")
            if scored_by != opponent:
                continue
            if (play.type in _NON_OFFENSIVE_TD_SLUGS
                    or (play.type in _OPPONENT_RECOVERY_SLUGS
                        and _scored_touchdown(play))):
                excluded += 6.0
        out["dst_points_allowed"] = float(points_allowed) - excluded
        if excluded:
            notes.append(
                f"points allowed {points_allowed:g} on the scoreboard less "
                f"{excluded:g} scored by {opponent} on a defensive or return "
                f"touchdown this defence was not on the field for")

    return out, notes


def three_and_outs_for(plays: Sequence, *, home: str, visitor: str, team: str
                       ) -> tuple[float, int, int]:
    """Factual three-and-outs this defence forced. COUNTED, never modelled."""
    summary = F.three_and_outs_forced(plays, home=home, visitor=visitor,
                                      team=team)
    drives = F.classify_drives(plays, home=home, visitor=visitor)
    opponent = visitor if team == home else home
    unknown = sum(1 for d in drives
                  if d.team == opponent
                  and d.outcome == F.DriveOutcome.UNKNOWN)
    return float(summary["three_and_outs"]), summary["opponent_drives"], unknown


# ── the assembled week ───────────────────────────────────────────────────────

@dataclass
class SubjectFacts:
    """One scoreable subject's factual components, and whether they are usable."""

    provider_player_key: str
    position: str | None
    nfl_team: str | None
    provider_game_id: Any
    components: dict = field(default_factory=dict)
    components_present: tuple = ()
    diagnostics: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.diagnostics

    def as_dict(self) -> dict:
        return {"provider_player_key": self.provider_player_key,
                "position": self.position, "nfl_team": self.nfl_team,
                "provider_game_id": self.provider_game_id,
                "components": dict(self.components),
                "components_present": list(self.components_present),
                "diagnostics": list(self.diagnostics),
                "notes": list(self.notes)}


@dataclass
class FactualWeek:
    """Every subject BALLDONTLIE can score for one NFL week."""

    season: int
    week: int
    subjects: dict = field(default_factory=dict)
    games: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)

    def complete_subjects(self) -> dict:
        return {k: v for k, v in self.subjects.items() if v.complete}

    def as_dict(self) -> dict:
        return {"season": self.season, "week": self.week,
                "games": list(self.games),
                "subjects": {k: v.as_dict() for k, v in self.subjects.items()},
                "diagnostics": list(self.diagnostics)}


def evidence_fingerprint(subject: SubjectFacts) -> str:
    """Deterministic identity of one subject's FACTUAL evidence.

    Covers what was measured, not when it was fetched: refetching identical
    facts reproduces the digest, and a provider correction that moves a single
    yard changes it.
    """
    payload = {
        "provider_player_key": subject.provider_player_key,
        "provider_game_id": subject.provider_game_id,
        "components": {k: repr(float(v))
                       for k, v in sorted(subject.components.items())},
        "components_present": sorted(subject.components_present),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_factual_week(*, season: int, week: int, games: Sequence) -> FactualWeek:
    """Assemble every subject's factual components for one NFL week.

    `games` is a sequence of dicts:
        {"game": <provider game row>,
         "plays": <parsed PlayRow sequence or None>,
         "stats": <sequence of provider /stats rows>}

    A game whose plays never arrived still yields offensive subjects — their
    scoring needs no play evidence — while its kickers and defences are
    refused, because theirs does. That asymmetry is the point: correctness per
    subject, not a whole week discarded or a whole week waved through.
    """
    out = FactualWeek(season=season, week=week)

    for entry in games:
        game = entry.get("game") or {}
        plays = entry.get("plays")
        stats = list(entry.get("stats") or [])
        gid = game.get("id")
        home = (game.get("home_team") or {}).get("abbreviation")
        visitor = (game.get("visitor_team") or {}).get("abbreviation")
        out.games.append(gid)

        final = game_is_final(game)
        home_score = game.get("home_team_score")
        visitor_score = game.get("visitor_team_score")

        game_diags = []
        if not final:
            game_diags.append(Diagnostic.PROVIDER_NOT_FINAL)
        if not stats:
            game_diags.append(Diagnostic.MISSING_FINAL_STATS)
        plays_missing = not plays

        # ── offensive and kicking subjects ────────────────────────────────
        by_team: dict = {}
        for row in stats:
            player = row.get("player") or {}
            pid = player.get("id")
            if pid is None:
                continue
            team = (row.get("team") or {}).get("abbreviation")
            by_team.setdefault(team, []).append(row)

        kicker_team = {
            player_key((r.get("player") or {}).get("id")):
                (r.get("team") or {}).get("abbreviation")
            for r in stats
            if (r.get("player") or {}).get("id") is not None
            and ((r.get("player") or {}).get("position_abbreviation")
                 in ("K", "PK"))
        }
        kickers = ({} if plays_missing
                   else kicker_events(plays, team_of=kicker_team))

        for row in stats:
            player = row.get("player") or {}
            pid = player.get("id")
            if pid is None:
                out.diagnostics.append(
                    f"{Diagnostic.MISSING_PLAYER_IDENTITY}: a /stats row in "
                    f"game {gid} carries no player id")
                continue
            key = player_key(pid)
            position = player.get("position_abbreviation")
            team = (row.get("team") or {}).get("abbreviation")

            components = offensive_components(row)
            present = set(OFFENSIVE_COMPONENTS)
            diagnostics = list(game_diags)
            notes = []

            is_kicker = position in ("K", "PK")
            kicking = kickers.get(key)
            if is_kicker or kicking is not None:
                if plays_missing:
                    diagnostics.append(Diagnostic.MISSING_PLAY_DATA)
                    notes.append("exact kicker scoring needs per-attempt "
                                 "distances and this game has no play data")
                else:
                    evidence = kicking or KickerEvidence(provider_player_key=key)
                    ok, why = reconcile_kicker(evidence, row)
                    if not ok:
                        diagnostics.append(
                            Diagnostic.KICKER_RECONCILIATION_FAILED)
                        notes.append(why)
                    else:
                        components.update(evidence.components())
                        present |= set(evidence.components())
                        notes.append(why)

            out.subjects[key] = SubjectFacts(
                provider_player_key=key, position=position, nfl_team=team,
                provider_game_id=gid, components=components,
                components_present=tuple(sorted(present)),
                diagnostics=diagnostics, notes=notes)

        # ── factual pick-sixes attach to the PASSER who threw them ────────
        # COUNTED from the stream, never estimated. `pick-six-model-v2` is a
        # projection parameter and has no business on a factual line.
        if not plays_missing:
            for key, count in pick_six_components(plays).items():
                subject = out.subjects.get(key)
                if subject is not None:
                    subject.components["pick_six_thrown"] = count
                    subject.components_present = tuple(sorted(
                        set(subject.components_present) | {"pick_six_thrown"}))
        for key, subject in out.subjects.items():
            # a quarterback who threw none still has a measured zero, provided
            # the game's plays were read at all
            if (subject.provider_game_id == gid and not plays_missing
                    and subject.position == "QB"
                    and "pick_six_thrown" not in subject.components):
                subject.components["pick_six_thrown"] = 0.0
                subject.components_present = tuple(sorted(
                    set(subject.components_present) | {"pick_six_thrown"}))

        # ── team defences ─────────────────────────────────────────────────
        for team, opponent, allowed in ((home, visitor, visitor_score),
                                        (visitor, home, home_score)):
            if not team:
                continue
            key = defense_key(team)
            diagnostics = list(game_diags)
            notes = []
            components: dict = {}
            present: set = set()

            if plays_missing:
                diagnostics.append(Diagnostic.MISSING_PLAY_DATA)
                notes.append("defensive touchdowns, safeties, blocked kicks "
                             "and three-and-outs are event-level and this game "
                             "has no play data")
            else:
                components, extra = defense_components(
                    team=team, opponent=opponent, plays=plays,
                    team_stat_rows=by_team.get(team, []),
                    points_allowed=allowed)
                notes.extend(extra)
                forced, opp_drives, unknown = three_and_outs_for(
                    plays, home=home, visitor=visitor, team=team)
                components["dst_three_and_outs"] = forced
                if unknown:
                    diagnostics.append(Diagnostic.UNKNOWN_DRIVE_EVENTS)
                    notes.append(
                        f"{unknown} opponent possession(s) could not be "
                        f"classified; a three-and-out among them would change "
                        f"this score, so the evidence is incomplete")
                present = set(components)

            if allowed is None:
                diagnostics.append(Diagnostic.MISSING_FINAL_STATS)
                notes.append("no opponent score, so points allowed is unknown")

            out.subjects[key] = SubjectFacts(
                provider_player_key=key, position="DEF", nfl_team=team,
                provider_game_id=gid, components=components,
                components_present=tuple(sorted(present)),
                diagnostics=diagnostics, notes=notes)

    return out


def pick_six_components(plays: Sequence) -> dict:
    """Factual pick-sixes thrown, per passer. COUNTED from the stream.

    Separate from `build_factual_week` because it attaches to the QB subject
    rather than to a stat row, and because it must be impossible to confuse
    with `pick-six-model-v2`, which estimates a rate and has no business here.
    """
    events = F.pick_six_events(plays)
    return {player_key(passer): float(count)
            for passer, count in events["pick_sixes"].items()}
