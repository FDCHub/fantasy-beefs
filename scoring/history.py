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

RECEPTION_MODEL_VERSION = "reception-model-v1"
PICK_SIX_MODEL_VERSION = "pick-six-model-v1"
THREE_AND_OUT_MODEL_VERSION = "three-and-out-model-v1"

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

    def as_dict(self) -> dict:
        return {"reception": self.reception.as_dict(),
                "pick_six": self.pick_six.as_dict(),
                "three_and_out": self.three_and_out.as_dict()}


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

    THE HIERARCHY IS A MINIMUM-SAMPLE RULE, NOT SHRINKAGE, AND THAT IS A CHOICE.
    A shrinkage estimator — blending a player's rate toward his position's by
    sample size — is the statistically nicer answer and needs one more free
    parameter: the sample size at which the two are weighted equally. There is
    no data in this repository to fit that parameter, so choosing it would be
    inventing a constant with a sophisticated name. A stated minimum sample is
    cruder, is auditable in one line, and every result says which level answered
    it. If a real sample later justifies shrinkage, it mints a v2.
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

    # ── receptions: player -> position -> league ────────────────────────────
    reception = UNRESOLVED
    attempt = _player(R.MODEL_RECEPTION, minimum_player_targets,
                      "MODELLED_PLAYER_HISTORY")
    if attempt is not None and attempt.resolved:
        reception = attempt
    else:
        insufficient = attempt.detail if attempt is not None else ""
        row = (select_rate(db, provider=provider,
                           model_type=R.MODEL_RECEPTION,
                           entity_type=R.ENTITY_POSITION, entity_key=position,
                           as_of=as_of) if position else None)
        if row is not None:
            reception = _resolution(
                row, "MODELLED_POSITIONAL_FALLBACK",
                f"positional history for {position} over {row.season_window}"
                + (f"; {insufficient}" if insufficient else ""))
        else:
            row = select_rate(db, provider=provider,
                              model_type=R.MODEL_RECEPTION,
                              entity_type=R.ENTITY_LEAGUE,
                              entity_key=LEAGUE_KEY, as_of=as_of)
            if row is not None:
                reception = _resolution(
                    row, "MODELLED_LEAGUE_FALLBACK",
                    f"league-wide history over {row.season_window}")

    # ── pick six: quarterback -> league conditional ─────────────────────────
    #
    # A POSITIONAL LEVEL WOULD BE THE LEAGUE LEVEL HERE. Only quarterbacks throw
    # interceptions in any volume, so "the QB positional rate" and "the league
    # conditional rate" are the same population under two names. Storing one and
    # calling it two would make the provenance dishonest.
    pick_six = UNRESOLVED
    attempt = _player(R.MODEL_PICK_SIX, minimum_player_interceptions,
                      "MODELLED_PLAYER_HISTORY")
    if attempt is not None and attempt.resolved:
        pick_six = attempt
    else:
        insufficient = attempt.detail if attempt is not None else ""
        row = select_rate(db, provider=provider, model_type=R.MODEL_PICK_SIX,
                          entity_type=R.ENTITY_LEAGUE, entity_key=LEAGUE_KEY,
                          as_of=as_of)
        if row is not None:
            pick_six = _resolution(
                row, "MODELLED_LEAGUE_FALLBACK",
                f"league conditional rate over {row.season_window}"
                + (f"; {insufficient}" if insufficient else ""))

    # ── three-and-outs: this defence -> league ──────────────────────────────
    three_and_out = UNRESOLVED
    if nfl_team:
        row = select_rate(db, provider=provider,
                          model_type=R.MODEL_THREE_AND_OUT,
                          entity_type=R.ENTITY_TEAM, entity_key=nfl_team,
                          as_of=as_of)
        if row is not None and row.sample_size >= minimum_team_drives:
            three_and_out = _resolution(
                row, "MODELLED_TEAM_HISTORY",
                f"defensive history over {row.season_window}")
        elif row is not None:
            three_and_out = RateResolution(
                rate=None, level="INSUFFICIENT_TEAM_SAMPLE",
                sample_size=row.sample_size, season_window=row.season_window,
                as_of=row.as_of, model_version=row.model_version,
                detail=f"team sample {row.sample_size} drives is below the "
                       f"minimum {minimum_team_drives}")
    if not three_and_out.resolved:
        row = select_rate(db, provider=provider,
                          model_type=R.MODEL_THREE_AND_OUT,
                          entity_type=R.ENTITY_LEAGUE, entity_key=LEAGUE_KEY,
                          as_of=as_of)
        if row is not None:
            three_and_out = _resolution(
                row, "MODELLED_LEAGUE_FALLBACK",
                f"league-wide rate over {row.season_window}")

    return RateBundle(reception=reception, pick_six=pick_six,
                      three_and_out=three_and_out)


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

    minimum_targets = getattr(config, "minimum_player_targets", 50)
    minimum_interceptions = getattr(config, "minimum_player_interceptions", 20)
    minimum_drives = getattr(config, "minimum_team_drives", 100)

    player_keys = sorted({s[0] for s in subjects if s[0]})
    positions = sorted({s[1] for s in subjects if s[1]})
    teams = sorted({s[2] for s in subjects if s[2]})

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

    reception_players = _latest(R.MODEL_RECEPTION, R.ENTITY_PLAYER, player_keys)
    reception_positions = _latest(R.MODEL_RECEPTION, R.ENTITY_POSITION, positions)
    reception_league = _latest(R.MODEL_RECEPTION, R.ENTITY_LEAGUE, [LEAGUE_KEY])
    pick_six_players = _latest(R.MODEL_PICK_SIX, R.ENTITY_PLAYER, player_keys)
    pick_six_league = _latest(R.MODEL_PICK_SIX, R.ENTITY_LEAGUE, [LEAGUE_KEY])
    tao_teams = _latest(R.MODEL_THREE_AND_OUT, R.ENTITY_TEAM, teams)
    tao_league = _latest(R.MODEL_THREE_AND_OUT, R.ENTITY_LEAGUE, [LEAGUE_KEY])

    def _player_level(row, minimum, level_name):
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

    out: dict = {}
    for player_key, position, nfl_team in subjects:
        reception = UNRESOLVED
        attempt = _player_level(reception_players.get(player_key),
                                minimum_targets, "MODELLED_PLAYER_HISTORY")
        if attempt is not None and attempt.resolved:
            reception = attempt
        else:
            note = attempt.detail if attempt is not None else ""
            row = reception_positions.get(position)
            if row is not None:
                reception = _resolution(
                    row, "MODELLED_POSITIONAL_FALLBACK",
                    f"positional history for {position} over "
                    f"{row.season_window}" + (f"; {note}" if note else ""))
            elif reception_league.get(LEAGUE_KEY) is not None:
                reception = _resolution(
                    reception_league[LEAGUE_KEY], "MODELLED_LEAGUE_FALLBACK",
                    "league-wide history")

        pick_six = UNRESOLVED
        attempt = _player_level(pick_six_players.get(player_key),
                                minimum_interceptions,
                                "MODELLED_PLAYER_HISTORY")
        if attempt is not None and attempt.resolved:
            pick_six = attempt
        else:
            note = attempt.detail if attempt is not None else ""
            row = pick_six_league.get(LEAGUE_KEY)
            if row is not None:
                pick_six = _resolution(
                    row, "MODELLED_LEAGUE_FALLBACK",
                    f"league conditional rate over {row.season_window}"
                    + (f"; {note}" if note else ""))

        three_and_out = UNRESOLVED
        row = tao_teams.get(nfl_team)
        if row is not None and row.sample_size >= minimum_drives:
            three_and_out = _resolution(
                row, "MODELLED_TEAM_HISTORY",
                f"defensive history over {row.season_window}")
        elif row is not None:
            three_and_out = RateResolution(
                rate=None, level="INSUFFICIENT_TEAM_SAMPLE",
                sample_size=row.sample_size, season_window=row.season_window,
                as_of=row.as_of, model_version=row.model_version,
                detail=f"team sample {row.sample_size} drives is below the "
                       f"minimum {minimum_drives}")
        if not three_and_out.resolved and tao_league.get(LEAGUE_KEY) is not None:
            three_and_out = _resolution(tao_league[LEAGUE_KEY],
                                        "MODELLED_LEAGUE_FALLBACK",
                                        "league-wide rate")

        out[player_key] = RateBundle(reception=reception, pick_six=pick_six,
                                     three_and_out=three_and_out)
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
