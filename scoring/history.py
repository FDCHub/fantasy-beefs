"""Sprint 5 · historical model parameters — measured rates, and how they are read.

WHAT THIS MODULE IS FOR. Sprint 4 built three projection models and refused all
three, because each needed a rate and no rate had been measured. This is the
store those measurements live in, the derivation that produces them from
BALLDONTLIE facts, and the resolver IPRM reads them through.

    reception-model-v1      receptions / targets, per player, per position
    pick-six-model-v1       pick-sixes / interceptions, per quarterback
    three-and-out-model-v1  three-and-outs forced / opponent drives, per team

THREE MODELS, THREE POPULATIONS, AND THEY ARE NOT INTERCHANGEABLE. A catch rate
is a property of one receiver's hands. A conditional pick-six rate is a property
of a quarterback meeting a defence. A three-and-out rate is a property of a
defensive unit meeting an offence. They share this storage and this as-of
discipline; they share no statistical assumption, and the resolver keeps their
entity types apart so one can never answer for another.

── AS-OF IS THE PROPERTY THAT MAKES A REPLAY DEFENSIBLE ────────────────────

Every parameter records the cutoff its derivation respected. Selection never
returns a parameter derived AFTER the moment being priced for, so a week-1 2026
projection cannot be built from week-3 2026 results. A wager priced on future
information is indefensible however good the arithmetic is, and this is the one
line of code that prevents it.

── NO NETWORK. EVER. ───────────────────────────────────────────────────────

Derivation may be fed by a live acquisition run; RESOLUTION reads the database
and nothing else. Nothing in the quote path opens a socket, which is what makes
a price replayable months later from stored rows alone.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "LEAGUE_KEY",
    "PICK_SIX_MODEL_VERSION",
    "RECEPTION_MODEL_VERSION",
    "RateBundle",
    "RateResolution",
    "THREE_AND_OUT_MODEL_VERSION",
    "DRIVES_MODEL_VERSION",
    "derive_drive_rates",
    "derive_reception_rates_from_season_totals",
    "HistoricalRate",
    "derive_pick_six_rates",
    "derive_reception_rates",
    "derive_three_and_out_rates",
    "persist_rates",
    "rate_fingerprint",
    "resolve_bundle",
    "resolve_bundles",
    "select_rate",
]

#: v2 (Sprint 5B): POSITION -> LEAGUE. The player tier was measured against
#: two real seasons and removed; see `resolve_bundle` for the numbers.
RECEPTION_MODEL_VERSION = "reception-model-v2"
#: v2 (Sprint 5B): the LEAGUE CONDITIONAL rate only. A quarterback throws far
#: too few interceptions for his own pick-six rate to mean anything -- see
#: `resolve_bundle`.
PICK_SIX_MODEL_VERSION = "pick-six-model-v2"
#: v2 (Sprint 5B): the LEAGUE rate per opponent drive. A defence's own measured
#: rate predicts its next game WORSE than the league does -- see `resolve_bundle`.
THREE_AND_OUT_MODEL_VERSION = "three-and-out-model-v2"
#: Sprint 5B: drives per team-game, the second half of the three-and-out
#: projection. A rate per opponent drive is not a per-game expectation until
#: something says how many drives there will be.
DRIVES_MODEL_VERSION = "drives-model-v1"

#: The entity key a league-wide parameter is stored under.
LEAGUE_KEY = "LEAGUE"


@dataclass(frozen=True)
class HistoricalRate:
    """One derived parameter, ready to persist."""

    provider: str
    model_type: str
    model_version: str
    entity_type: str
    entity_key: str
    season_window: str
    as_of: datetime
    numerator: float
    denominator: float
    sample_size: int
    source_kind: str
    position: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)

    @property
    def rate(self) -> float:
        """The measured rate. A zero denominator is a zero rate, not a crash.

        A player with no targets has no catch rate — the SAMPLE SIZE is what
        tells a reader that, and the resolver's minimum-sample rule is what acts
        on it. Returning 0.0 here rather than raising keeps the arithmetic total
        and pushes the judgement to the one place that should make it.
        """
        return (self.numerator / self.denominator) if self.denominator else 0.0

    def fingerprint(self) -> str:
        return rate_fingerprint(
            provider=self.provider, model_type=self.model_type,
            model_version=self.model_version, entity_type=self.entity_type,
            entity_key=self.entity_key, season_window=self.season_window,
            as_of=self.as_of, numerator=self.numerator,
            denominator=self.denominator, sample_size=self.sample_size)


def rate_fingerprint(*, provider: str, model_type: str, model_version: str,
                     entity_type: str, entity_key: str, season_window: str,
                     as_of: datetime, numerator: float, denominator: float,
                     sample_size: int) -> str:
    """The deterministic identity of one DERIVATION.

    It covers what was measured and what came out, and NOT when the derivation
    ran. Re-deriving unchanged history therefore reproduces the digest and
    writes nothing; a provider CORRECTION changes a count, changes the digest,
    and lands a new parameter beside its predecessor so the old one stays
    replayable.
    """
    payload = {
        "provider": provider, "model_type": model_type,
        "model_version": model_version, "entity_type": entity_type,
        "entity_key": entity_key, "season_window": season_window,
        "as_of": as_of.astimezone(timezone.utc).isoformat()
        if as_of.tzinfo else as_of.isoformat(),
        "numerator": repr(float(numerator)),
        "denominator": repr(float(denominator)),
        "sample_size": int(sample_size),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── persistence ──────────────────────────────────────────────────────────────

def persist_rates(db, rates: Iterable[HistoricalRate], *,
                  generated_at: datetime | None = None) -> dict:
    """Store derived parameters. Idempotent by fingerprint.

    Returns named counts. A refresh that learned nothing reports every rate as a
    duplicate and writes no row, which is what makes a scheduled refresh safe to
    run as often as anyone likes.
    """
    from db.schema import ProviderHistoricalRate

    generated_at = generated_at or datetime.now(timezone.utc)
    report = {"persisted": 0, "duplicate": 0, "rates": []}
    for rate in rates:
        digest = rate.fingerprint()
        existing = (db.query(ProviderHistoricalRate)
                    .filter(ProviderHistoricalRate.provider == rate.provider,
                            ProviderHistoricalRate.model_type == rate.model_type,
                            ProviderHistoricalRate.model_version
                            == rate.model_version,
                            ProviderHistoricalRate.entity_type
                            == rate.entity_type,
                            ProviderHistoricalRate.entity_key == rate.entity_key,
                            ProviderHistoricalRate.season_window
                            == rate.season_window,
                            ProviderHistoricalRate.as_of == rate.as_of,
                            ProviderHistoricalRate.fingerprint == digest)
                    .first())
        if existing is not None:
            report["duplicate"] += 1
            continue
        row = ProviderHistoricalRate(
            provider=rate.provider, model_type=rate.model_type,
            model_version=rate.model_version, entity_type=rate.entity_type,
            entity_key=rate.entity_key, position=rate.position,
            season_window=rate.season_window, as_of=rate.as_of,
            numerator=float(rate.numerator), denominator=float(rate.denominator),
            rate=rate.rate, sample_size=int(rate.sample_size),
            source_kind=rate.source_kind, parameters=dict(rate.parameters),
            fingerprint=digest, generated_at=generated_at)
        db.add(row)
        db.flush()
        report["persisted"] += 1
        report["rates"].append(row.id)
    return report


def select_rate(db, *, provider: str, model_type: str, entity_type: str,
                entity_key: str, as_of: datetime,
                model_version: str | None = None):
    """The parameter in force for this entity at this instant, or None.

    NEVER A PARAMETER DERIVED FROM THE FUTURE. `as_of <= the moment being priced
    for` is the whole of the leakage guard; the ordering below then takes the
    most recent cutoff at or before it, and the newest derivation of that cutoff
    when a correction has produced two.
    """
    from db.schema import ProviderHistoricalRate

    query = (db.query(ProviderHistoricalRate)
             .filter(ProviderHistoricalRate.provider == provider,
                     ProviderHistoricalRate.model_type == model_type,
                     ProviderHistoricalRate.entity_type == entity_type,
                     ProviderHistoricalRate.entity_key == str(entity_key),
                     ProviderHistoricalRate.as_of <= as_of))
    if model_version is not None:
        query = query.filter(
            ProviderHistoricalRate.model_version == model_version)
    return (query.order_by(ProviderHistoricalRate.as_of.desc(),
                           ProviderHistoricalRate.generated_at.desc(),
                           ProviderHistoricalRate.id.desc())
            .first())


# ── the resolver IPRM reads ──────────────────────────────────────────────────

@dataclass(frozen=True)
class RateResolution:
    """One resolved rate, and which level of the hierarchy answered."""

    rate: float | None
    level: str
    sample_size: int = 0
    numerator: float = 0.0
    denominator: float = 0.0
    season_window: str = ""
    as_of: datetime | None = None
    model_version: str = ""
    detail: str = ""

    @property
    def resolved(self) -> bool:
        return self.rate is not None

    def as_dict(self) -> dict:
        return {"rate": self.rate, "level": self.level,
                "sample_size": self.sample_size, "numerator": self.numerator,
                "denominator": self.denominator,
                "season_window": self.season_window,
                "as_of": self.as_of.isoformat() if self.as_of else None,
                "model_version": self.model_version, "detail": self.detail}


UNRESOLVED = RateResolution(rate=None, level="MODEL_UNRESOLVED",
                            detail="no parameter is in force for this entity "
                                   "at this as-of")


@dataclass(frozen=True)
class RateBundle:
    """Every parameter one player-week needs, resolved once, ahead of scoring.

    RESOLVED BY THE CALLER, NOT BY IPRM. IPRM must stay a pure function — no
    session, no query — so the lineup builder resolves a bundle per subject in
    the batch it is already fetching, and hands it in. That is also what keeps a
    league-week to one query per model rather than one per player.
    """

    reception: RateResolution = UNRESOLVED
    pick_six: RateResolution = UNRESOLVED
    three_and_out: RateResolution = UNRESOLVED
    #: Sprint 5B. Expected opponent drives per game — the second half of the
    #: three-and-out projection, and the reason Sprint 5 refused it.
    drives: RateResolution = UNRESOLVED

    def as_dict(self) -> dict:
        return {"reception": self.reception.as_dict(),
                "pick_six": self.pick_six.as_dict(),
                "three_and_out": self.three_and_out.as_dict(),
                "drives": self.drives.as_dict()}


EMPTY_BUNDLE = RateBundle()


def _resolution(row, level: str, detail: str) -> RateResolution:
    return RateResolution(
        rate=row.rate, level=level, sample_size=row.sample_size,
        numerator=row.numerator, denominator=row.denominator,
        season_window=row.season_window, as_of=row.as_of,
        model_version=row.model_version, detail=detail)


def resolve_bundle(db, *, provider: str, as_of: datetime,
                   player_key: str | None = None, position: str | None = None,
                   nfl_team: str | None = None,
                   minimum_player_targets: int = 50,
                   minimum_player_interceptions: int = 20,
                   minimum_team_drives: int = 100) -> RateBundle:
    """Resolve all three models for one subject, hierarchy and all.

    ── RECEPTIONS RESOLVE POSITION -> LEAGUE. THE PLAYER TIER IS GONE. ─────

    Sprint 5 assumed a player's own catch rate was the best estimate of his
    next one and fell back to his position only for want of sample. Two real
    seasons say the opposite. Training on 2024 and testing on 2025, over the
    SAME 134 players who cleared the fifty-target minimum, the positional rate
    predicted better than each player's own: MAE 4.01 against 4.65. Across all
    502 receivers the gap is wider — 2.28 for position against 2.87 for player
    history, which was the worst of every rule tried.

    Shrinkage was then measured rather than argued about, since the data to fit
    it finally existed: blending each player toward his positional prior, the
    held-out error is flat from k=150 to k=500 and bottoms at k=250 with MAE
    2.22. That is 2.6% better than simply using the position — and choosing
    k=250 would mean fitting a constant on the very season being used to judge
    it. A 2.6% gain does not buy a tuned parameter, so the model takes the
    simpler rule that the same evidence supports.

    Catch rate turns out to be a property of a ROLE more than of a pair of
    hands: it does not survive a new scheme, a new quarterback or a new depth
    chart, and a season is long enough that noise is not what breaks it.

    ── PICK-SIX RESOLVES AT THE LEAGUE CONDITIONAL. ────────────────────────

    A quarterback does not throw enough interceptions for his own pick-six rate
    to be an estimate of anything. Over 2024 the busiest passer in the league
    threw sixteen; the median threw seven. At the league rate of 0.0685, a rate
    measured from ten interceptions carries a standard error of 117% OF THE
    RATE ITSELF, and from twenty, 82%. The held-out test says exactly what that
    implies: predicting each 2025 quarterback from his own 2024 rate scored MAE
    0.771 against the league conditional's 0.529, and among those with ten or
    more interceptions, 0.668 against 0.502. The league rate wins by a quarter
    to a third, on every threshold tried.

    This is not a sample-size problem that a longer window fixes. Twelve
    quarterbacks clear twenty interceptions across BOTH seasons, and at that
    sample the standard error is still 82% of the rate.

    ── THREE-AND-OUTS RESOLVE AT THE LEAGUE RATE PER DRIVE. ────────────────

    A defence forcing three-and-outs looks like a skill and largely is not a
    STABLE one. Split-half reliability within 2024 -- a defence's rate over its
    odd-numbered games against its own even-numbered games -- is r=0.19,
    a full-season reliability of 0.32. Most of what a team rate measures is the
    schedule and the noise, not the defence.

    Held out over all 544 team-games of 2025, trained on all 534 of 2024:

        league baseline           MAE 1.0928   <- production
        defence-only              MAE 1.1159
        simple average of both    MAE 1.1041
        offence-suffered only     MAE 1.1389
        shrunk to reliability     MAE 1.0911   (0.15% better; not worth a
                                                parameter)

    Every team-based rule loses to the pooled rate. Shrinking the team rate
    toward the league by its measured reliability recovers the difference and
    then some, by 0.15% -- which does not buy a new constant, a new stored
    weight and a new thing to explain.

    ── AND THE SAME ANSWER THREE TIMES IS NOT A COINCIDENCE. ───────────────

    Catch rate, pick-six rate and three-and-out rate are all quantities where
    the individual history is thin, noisy, or measuring the schedule. In each
    case the pooled rate predicted better on held-out football. The granular
    rates are still derived and STORED -- they are real measurements and the
    audit trail wants them -- but nothing prices from them.

    `minimum_player_targets`, `minimum_player_interceptions` and
    `minimum_team_drives` are retained in the signature and in `IprmConfig` so
    that iprm-v2's contract and config hash are untouched. No model consults
    them any more; they are the thresholds of the tiers that were removed.
    """
    from db.schema import ProviderHistoricalRate as R

    def _player(model_type, minimum, level_name):
        if not player_key:
            return None
        row = select_rate(db, provider=provider, model_type=model_type,
                          entity_type=R.ENTITY_PLAYER, entity_key=player_key,
                          as_of=as_of)
        if row is None:
            return None
        if row.sample_size < minimum:
            return RateResolution(
                rate=None, level="INSUFFICIENT_PLAYER_SAMPLE",
                sample_size=row.sample_size, season_window=row.season_window,
                as_of=row.as_of, model_version=row.model_version,
                detail=f"player sample {row.sample_size} is below the minimum "
                       f"{minimum} this model trusts")
        return _resolution(row, level_name,
                           f"player history over {row.season_window}")

    # ── receptions: position -> league (v2; no player tier) ─────────────────
    reception = UNRESOLVED
    row = (select_rate(db, provider=provider, model_type=R.MODEL_RECEPTION,
                       entity_type=R.ENTITY_POSITION, entity_key=position,
                       as_of=as_of) if position else None)
    if row is not None:
        reception = _resolution(
            row, "MODELLED_POSITIONAL_FALLBACK",
            f"positional history for {position} over {row.season_window}")
    else:
        row = select_rate(db, provider=provider, model_type=R.MODEL_RECEPTION,
                          entity_type=R.ENTITY_LEAGUE, entity_key=LEAGUE_KEY,
                          as_of=as_of)
        if row is not None:
            reception = _resolution(
                row, "MODELLED_LEAGUE_FALLBACK",
                f"league-wide history over {row.season_window}")

    # ── pick six: the league conditional (v2; no quarterback tier) ──────────
    pick_six = UNRESOLVED
    row = select_rate(db, provider=provider, model_type=R.MODEL_PICK_SIX,
                      entity_type=R.ENTITY_LEAGUE, entity_key=LEAGUE_KEY,
                      as_of=as_of)
    if row is not None:
        pick_six = _resolution(
            row, "MODELLED_LEAGUE_FALLBACK",
            f"league conditional rate over {row.season_window}")

    # ── three-and-outs: the league rate per opponent drive (v2) ─────────────
    three_and_out = UNRESOLVED
    row = select_rate(db, provider=provider, model_type=R.MODEL_THREE_AND_OUT,
                      entity_type=R.ENTITY_LEAGUE, entity_key=LEAGUE_KEY,
                      as_of=as_of)
    if row is not None:
        three_and_out = _resolution(
            row, "MODELLED_LEAGUE_FALLBACK",
            f"league-wide rate per opponent drive over {row.season_window}")

    # ── expected opponent drives ────────────────────────────────────────────
    # LEAGUE-LEVEL BY MEASUREMENT, NOT BY LAZINESS. Drives per team-game barely
    # varies by team — both sides of a game trade possessions, so the count is a
    # property of the GAME rather than of either defence — and Sprint 5B backtested
    # a team-level estimate against the league mean before settling here. See
    # `derive_drive_rates` and the Sprint 5B drive backtest for the numbers.
    drives = UNRESOLVED
    row = select_rate(db, provider=provider, model_type=R.MODEL_DRIVES,
                      entity_type=R.ENTITY_LEAGUE, entity_key=LEAGUE_KEY,
                      as_of=as_of)
    if row is not None:
        drives = _resolution(
            row, "MODELLED_LEAGUE_FALLBACK",
            f"league-wide drives per team-game over {row.season_window}")

    return RateBundle(reception=reception, pick_six=pick_six,
                      three_and_out=three_and_out, drives=drives)


def resolve_bundles(db, *, provider: str, as_of: datetime,
                    subjects: Sequence, config=None) -> dict:
    """Resolve every subject in a lineup in a FIXED number of queries.

    `subjects` is a sequence of `(player_key, position, nfl_team)`. Calling
    `resolve_bundle` per player would be three queries each — twenty-seven for a
    nine-man lineup, and the quote path is exactly where that cost is least
    welcome. This fetches each MODEL once for the whole set and resolves the
    hierarchy in memory, so a lineup costs the same seven queries whether it
    holds one starter or a hundred.

    The hierarchy, the minimum samples and the as-of cutoff are identical to
    `resolve_bundle`'s — this is a batching strategy, not a second policy.
    """
    from db.schema import ProviderHistoricalRate as R

    # NO MINIMUM-SAMPLE THRESHOLDS ARE READ ANY MORE. Every model resolves at a
    # pooled level, so there is no individual estimate whose sample could be
    # too thin to trust. `IprmConfig` still carries the fields (iprm-v2's
    # config hash is unchanged by Sprint 5B) and nothing consults them.
    positions = sorted({s[1] for s in subjects if s[1]})

    def _latest(model_type, entity_type, keys):
        """The in-force row per entity_key, newest cutoff first, one query."""
        if not keys:
            return {}
        rows = (db.query(R)
                .filter(R.provider == provider, R.model_type == model_type,
                        R.entity_type == entity_type,
                        R.entity_key.in_(list(keys)), R.as_of <= as_of)
                .order_by(R.as_of.desc(), R.generated_at.desc(), R.id.desc())
                .all())
        chosen: dict = {}
        for row in rows:
            chosen.setdefault(row.entity_key, row)
        return chosen

    reception_positions = _latest(R.MODEL_RECEPTION, R.ENTITY_POSITION, positions)
    reception_league = _latest(R.MODEL_RECEPTION, R.ENTITY_LEAGUE, [LEAGUE_KEY])
    pick_six_league = _latest(R.MODEL_PICK_SIX, R.ENTITY_LEAGUE, [LEAGUE_KEY])
    tao_league = _latest(R.MODEL_THREE_AND_OUT, R.ENTITY_LEAGUE, [LEAGUE_KEY])
    drives_league = _latest(R.MODEL_DRIVES, R.ENTITY_LEAGUE, [LEAGUE_KEY])

    # ONE DRIVE EXPECTATION FOR THE WHOLE LINEUP. Drives per team-game is a
    # property of a game, not of a subject, so it is resolved once here rather
    # than per starter — and it costs the batch one more query, not one more
    # per player.
    drives = UNRESOLVED
    if drives_league.get(LEAGUE_KEY) is not None:
        drives = _resolution(drives_league[LEAGUE_KEY],
                             "MODELLED_LEAGUE_FALLBACK",
                             "league-wide drives per team-game")

    out: dict = {}
    for player_key, position, nfl_team in subjects:
        # position -> league, identical to `resolve_bundle`. This path prices
        # every lineup, so a hierarchy here that disagreed with the one there
        # would make a lineup quote differ from the same player quoted alone.
        reception = UNRESOLVED
        row = reception_positions.get(position)
        if row is not None:
            reception = _resolution(
                row, "MODELLED_POSITIONAL_FALLBACK",
                f"positional history for {position} over {row.season_window}")
        elif reception_league.get(LEAGUE_KEY) is not None:
            reception = _resolution(
                reception_league[LEAGUE_KEY], "MODELLED_LEAGUE_FALLBACK",
                "league-wide history")

        pick_six = UNRESOLVED
        row = pick_six_league.get(LEAGUE_KEY)
        if row is not None:
            pick_six = _resolution(
                row, "MODELLED_LEAGUE_FALLBACK",
                f"league conditional rate over {row.season_window}")

        three_and_out = UNRESOLVED
        if tao_league.get(LEAGUE_KEY) is not None:
            three_and_out = _resolution(tao_league[LEAGUE_KEY],
                                        "MODELLED_LEAGUE_FALLBACK",
                                        "league-wide rate per opponent drive")

        out[player_key] = RateBundle(reception=reception, pick_six=pick_six,
                                     three_and_out=three_and_out,
                                     drives=drives)
    return out


# ── derivation, from BALLDONTLIE facts ───────────────────────────────────────

def derive_reception_rates(rows: Iterable, *, provider: str,
                           season_window: str, as_of: datetime,
                           source_kind: str = "fantasy/weekly_stats") -> list:
    """Weekly stat rows -> catch rates per player, per position, and league-wide.

    `rows` are WP2 `WeeklyStatRow`s from FINALIZED weeks. Targets and receptions
    both come from the same row, so the ratio is measured on one population
    rather than joined across two.
    """
    players: dict = {}
    positions: dict = {}
    league = [0.0, 0.0]

    for row in rows:
        stats = row.stats or {}
        targets = float(stats.get("targets") or 0.0)
        receptions = float(stats.get("receptions") or 0.0)
        if targets <= 0:
            continue
        from providers.balldontlie.normalize import fantasy_position, subject_key
        try:
            key = subject_key(row)
        except Exception:                                      # noqa: BLE001
            continue
        position = fantasy_position(row)
        entry = players.setdefault(key, [0.0, 0.0, position])
        entry[0] += receptions
        entry[1] += targets
        if position:
            bucket = positions.setdefault(position, [0.0, 0.0])
            bucket[0] += receptions
            bucket[1] += targets
        league[0] += receptions
        league[1] += targets

    from db.schema import ProviderHistoricalRate as R
    out = []
    for key, (receptions, targets, position) in sorted(players.items()):
        out.append(HistoricalRate(
            provider=provider, model_type=R.MODEL_RECEPTION,
            model_version=RECEPTION_MODEL_VERSION,
            entity_type=R.ENTITY_PLAYER, entity_key=key, position=position,
            season_window=season_window, as_of=as_of, numerator=receptions,
            denominator=targets, sample_size=int(targets),
            source_kind=source_kind,
            parameters={"receptions": receptions, "targets": targets}))
    for position, (receptions, targets) in sorted(positions.items()):
        out.append(HistoricalRate(
            provider=provider, model_type=R.MODEL_RECEPTION,
            model_version=RECEPTION_MODEL_VERSION,
            entity_type=R.ENTITY_POSITION, entity_key=position,
            position=position, season_window=season_window, as_of=as_of,
            numerator=receptions, denominator=targets,
            sample_size=int(targets), source_kind=source_kind,
            parameters={"receptions": receptions, "targets": targets}))
    if league[1] > 0:
        out.append(HistoricalRate(
            provider=provider, model_type=R.MODEL_RECEPTION,
            model_version=RECEPTION_MODEL_VERSION,
            entity_type=R.ENTITY_LEAGUE, entity_key=LEAGUE_KEY,
            season_window=season_window, as_of=as_of, numerator=league[0],
            denominator=league[1], sample_size=int(league[1]),
            source_kind=source_kind,
            parameters={"receptions": league[0], "targets": league[1]}))
    return out


def derive_pick_six_rates(games: Iterable, *, provider: str,
                          season_window: str, as_of: datetime,
                          source_kind: str = "plays") -> list:
    """Play streams -> P(pick six | interception), per quarterback and league.

    `games` is an iterable of play sequences. Both terms are counted from the
    same streams by `factual.pick_six_events`, so an interception the stream
    could not attribute is excluded from BOTH — it cannot depress a rate it was
    never part of.
    """
    from providers.balldontlie.factual import pick_six_events
    from db.schema import ProviderHistoricalRate as R

    interceptions: dict = {}
    pick_sixes: dict = {}
    for plays in games:
        events = pick_six_events(plays)
        for passer, count in events["interceptions"].items():
            interceptions[passer] = interceptions.get(passer, 0) + count
        for passer, count in events["pick_sixes"].items():
            pick_sixes[passer] = pick_sixes.get(passer, 0) + count

    from providers.balldontlie_identity import player_key
    out = []
    for passer, thrown in sorted(interceptions.items(), key=lambda kv: str(kv[0])):
        returned = pick_sixes.get(passer, 0)
        out.append(HistoricalRate(
            provider=provider, model_type=R.MODEL_PICK_SIX,
            model_version=PICK_SIX_MODEL_VERSION,
            entity_type=R.ENTITY_PLAYER, entity_key=player_key(passer),
            position="QB", season_window=season_window, as_of=as_of,
            numerator=float(returned), denominator=float(thrown),
            sample_size=int(thrown), source_kind=source_kind,
            parameters={"interceptions": thrown, "pick_sixes": returned}))
    total_thrown = sum(interceptions.values())
    total_returned = sum(pick_sixes.values())
    if total_thrown:
        out.append(HistoricalRate(
            provider=provider, model_type=R.MODEL_PICK_SIX,
            model_version=PICK_SIX_MODEL_VERSION,
            entity_type=R.ENTITY_LEAGUE, entity_key=LEAGUE_KEY, position="QB",
            season_window=season_window, as_of=as_of,
            numerator=float(total_returned), denominator=float(total_thrown),
            sample_size=int(total_thrown), source_kind=source_kind,
            parameters={"interceptions": total_thrown,
                        "pick_sixes": total_returned}))
    return out


def derive_three_and_out_rates(games: Iterable, *, provider: str,
                               season_window: str, as_of: datetime,
                               source_kind: str = "plays") -> list:
    """Play streams -> three-and-outs forced per opponent drive, per defence.

    `games` yields `(plays, home, visitor)`. Both teams are measured from each
    game, and drives the stream could not classify are excluded from numerator
    and denominator alike by `factual.three_and_outs_forced`.

    THE RATE IS PER DRIVE, NOT PER GAME, and that is the modelling decision that
    matters. A defence facing fourteen drives has more chances than one facing
    nine; a per-game rate silently prices game pace into a defensive skill
    estimate, and pace belongs to the projection of drives rather than to the
    defence.
    """
    from providers.balldontlie.factual import three_and_outs_forced
    from db.schema import ProviderHistoricalRate as R

    teams: dict = {}
    for plays, home, visitor in games:
        for team in (home, visitor):
            summary = three_and_outs_forced(plays, home=home, visitor=visitor,
                                            team=team)
            entry = teams.setdefault(team, [0.0, 0.0])
            entry[0] += summary["three_and_outs"]
            entry[1] += summary["opponent_drives"]

    out = []
    league = [0.0, 0.0]
    for team, (forced, drives) in sorted(teams.items()):
        league[0] += forced
        league[1] += drives
        out.append(HistoricalRate(
            provider=provider, model_type=R.MODEL_THREE_AND_OUT,
            model_version=THREE_AND_OUT_MODEL_VERSION,
            entity_type=R.ENTITY_TEAM, entity_key=team,
            season_window=season_window, as_of=as_of, numerator=forced,
            denominator=drives, sample_size=int(drives),
            source_kind=source_kind,
            parameters={"three_and_outs": forced, "opponent_drives": drives}))
    if league[1] > 0:
        out.append(HistoricalRate(
            provider=provider, model_type=R.MODEL_THREE_AND_OUT,
            model_version=THREE_AND_OUT_MODEL_VERSION,
            entity_type=R.ENTITY_LEAGUE, entity_key=LEAGUE_KEY,
            season_window=season_window, as_of=as_of, numerator=league[0],
            denominator=league[1], sample_size=int(league[1]),
            source_kind=source_kind,
            parameters={"three_and_outs": league[0],
                        "opponent_drives": league[1]}))
    return out


def derive_reception_rates_from_season_totals(rows, *, provider: str,
                                              season_window: str,
                                              as_of: datetime,
                                              source_kind: str = "season_stats"
                                              ) -> list:
    """`/season_stats` rows -> catch rates per player, position and league.

    THE SAME MODEL AS `derive_reception_rates`, FED FROM SEASON AGGREGATES.
    `/season_stats` returns one row per player per season with `receptions` and
    `receiving_targets` already summed, which is the identical population the
    weekly path sums by hand -- at roughly a fortieth of the request cost, and
    a five-per-minute budget makes that the difference between a measured model
    and an unmeasured one.

    Postseason rows are dropped: the window this product prices is the regular
    season, and mixing January football into a season rate changes what the
    rate means without saying so.
    """
    from db.schema import ProviderHistoricalRate as R
    from providers.balldontlie_identity import player_key

    players: dict = {}
    positions: dict = {}
    league = [0.0, 0.0]
    quarantined: list = []

    for row in rows:
        if row.get("postseason"):
            continue
        player = row.get("player") or {}
        identifier = player.get("id")
        if identifier is None:
            continue
        targets = float(row.get("receiving_targets") or 0.0)
        receptions = float(row.get("receptions") or 0.0)
        if targets <= 0:
            continue

        # -- IMPOSSIBLE ROWS ARE QUARANTINED, NEVER NORMALISED --------------
        # More receptions than targets is not a rounding artefact, it is a
        # contradiction, and silently clamping it would fold a data error into
        # a parameter that later prices a wager.
        if receptions < 0 or receptions > targets:
            quarantined.append({"player": identifier, "receptions": receptions,
                                "targets": targets})
            continue

        position = player.get("position_abbreviation") or None
        key = player_key(identifier)
        entry = players.setdefault(key, [0.0, 0.0, position])
        entry[0] += receptions
        entry[1] += targets
        if position:
            bucket = positions.setdefault(position, [0.0, 0.0])
            bucket[0] += receptions
            bucket[1] += targets
        league[0] += receptions
        league[1] += targets

    out = []
    for key, (receptions, targets, position) in sorted(players.items()):
        out.append(HistoricalRate(
            provider=provider, model_type=R.MODEL_RECEPTION,
            model_version=RECEPTION_MODEL_VERSION,
            entity_type=R.ENTITY_PLAYER, entity_key=key, position=position,
            season_window=season_window, as_of=as_of, numerator=receptions,
            denominator=targets, sample_size=int(targets),
            source_kind=source_kind,
            parameters={"receptions": receptions, "targets": targets}))
    for position, (receptions, targets) in sorted(positions.items()):
        out.append(HistoricalRate(
            provider=provider, model_type=R.MODEL_RECEPTION,
            model_version=RECEPTION_MODEL_VERSION,
            entity_type=R.ENTITY_POSITION, entity_key=position,
            position=position, season_window=season_window, as_of=as_of,
            numerator=receptions, denominator=targets,
            sample_size=int(targets), source_kind=source_kind,
            parameters={"receptions": receptions, "targets": targets}))
    if league[1] > 0:
        out.append(HistoricalRate(
            provider=provider, model_type=R.MODEL_RECEPTION,
            model_version=RECEPTION_MODEL_VERSION,
            entity_type=R.ENTITY_LEAGUE, entity_key=LEAGUE_KEY,
            season_window=season_window, as_of=as_of, numerator=league[0],
            denominator=league[1], sample_size=int(league[1]),
            source_kind=source_kind,
            parameters={"receptions": league[0], "targets": league[1],
                        "quarantined_rows": len(quarantined)}))
    return out


def derive_drive_rates(games, *, provider: str, season_window: str,
                       as_of: datetime, source_kind: str = "plays") -> list:
    """Play streams -> drives per team-game, per team and league-wide.

    `games` yields `(plays, home, visitor)`.

    THIS IS THE MEASUREMENT SPRINT 5 REFUSED TO INVENT. `expected_opponent_
    drives` defaulted to None precisely because nothing had counted drives:
    ten, eleven and twelve are all plausible-sounding numbers and none of them
    was evidence. Here every classified possession in every acquired game is
    counted, so the figure carries its own sample size.

    The numerator is DRIVES and the denominator is TEAM-GAMES, so `rate` reads
    directly as drives per team-game. Only drives the classifier could judge
    are counted: an unclassifiable possession is excluded here exactly as it is
    from the three-and-out rate, so the two models see the same football.
    """
    from providers.balldontlie.factual import classify_drives
    from db.schema import ProviderHistoricalRate as R

    per_team: dict = {}
    league = [0.0, 0.0]

    for plays, home, visitor in games:
        drives = classify_drives(plays, home=home, visitor=visitor)
        counted: dict = {home: 0, visitor: 0}
        for drive in drives:
            if drive.team in counted and drive.counts_toward_sample:
                counted[drive.team] += 1
        for team, count in counted.items():
            if team is None:
                continue
            entry = per_team.setdefault(team, [0.0, 0.0])
            entry[0] += count          # drives
            entry[1] += 1.0            # team-games
            league[0] += count
            league[1] += 1.0

    out = []
    for team, (drives, team_games) in sorted(per_team.items()):
        if team_games <= 0:
            continue
        out.append(HistoricalRate(
            provider=provider, model_type=R.MODEL_DRIVES,
            model_version=DRIVES_MODEL_VERSION,
            entity_type=R.ENTITY_TEAM, entity_key=team,
            season_window=season_window, as_of=as_of, numerator=drives,
            denominator=team_games, sample_size=int(team_games),
            source_kind=source_kind,
            parameters={"drives": drives, "team_games": team_games}))
    if league[1] > 0:
        out.append(HistoricalRate(
            provider=provider, model_type=R.MODEL_DRIVES,
            model_version=DRIVES_MODEL_VERSION,
            entity_type=R.ENTITY_LEAGUE, entity_key=LEAGUE_KEY,
            season_window=season_window, as_of=as_of, numerator=league[0],
            denominator=league[1], sample_size=int(league[1]),
            source_kind=source_kind,
            parameters={"drives": league[0], "team_games": league[1]}))
    return out
