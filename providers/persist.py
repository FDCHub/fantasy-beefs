"""E — persistence, refresh, ingestion horizon and conflict recording.

WP2 MOVED THIS MODULE HERE FROM `providers/yahoo/persist.py`. The four rules
below, the conflict identity, the horizon and the finality discipline are the
certified Sprint 6 ones and are unchanged. ONE thing changed: the provider name
is now READ OFF THE SNAPSHOT (`snapshot.league.provider`) instead of being the
module constant "yahoo".

WHY THAT ONE LINE WAS THE WHOLE BLOCKER. Everything this module does — resolve
identity, orient a matchup, apply finality, record a contradiction, respect the
horizon — is provider-neutral by construction; only the name it looked identity
up under was not. A Demo league whose teams carry `provider = "demo"` was
therefore unreachable: `resolve_league` asked for a Yahoo row and got
UNKNOWN_IDENTITY, and the refusal read as a Demo defect rather than as a
hardcoded constant. Taking the name from the DTO that already carries it is the
smallest correct fix, and it means a second provider needs no branch anywhere
below this line.

THIS MODULE POSTS NO LEDGER ENTRY AND IMPORTS NOTHING FROM ledger/ OR economy/.
It writes domain FACTS — matchup rows, scores, finality, roster slots, provider
identity, conflicts. Every cent that moves as a consequence moves later, through
the accepted Sprint 1-5 engines, gated by Matchup.finalized_at. C-15 replays a
full season here and proves trial_balance is untouched; WP2's C-19 does the same
for the Demo provider.

FOUR RULES GOVERN A REFRESH:

  1. HORIZON (§6). Rows are persisted only THROUGH THE PROVIDER'S CURRENT WEEK.
     Accepted Sprint 5 season close derives `played_weeks` from Matchup row
     EXISTENCE (economy/season_close_orchestrator.py:150), so pre-creating the
     full future schedule would silently redefine which weeks the season close
     demands a Skunk assessment for. A future week is not persisted at all.

  2. BEFORE FINALITY, REFRESH MAY UPDATE (§9). Scores move during a game; that
     is the normal case and needs no ceremony.

  3. AFTER FINALITY, NOTHING SILENTLY CHANGES (S6-R3, §9). home_score,
     away_score, winner_team_id and finalized_at are frozen once finalized_at is
     set. A provider that disagrees does not win: the stored value stands, a
     ProviderConflict is recorded, and the refresh fails closed by named error.

  4. FROZEN SEASON BOUNDARIES ARE FACTS FANTASYBEEFS OWNS (§12). Once
     season_final_week / playoff_start_week / start_week are populated they are
     load-bearing — betting/pool_season_boundary.py reads them for rollover
     expiry and the no-repeat rule, and the configurable season economy derives
     its week count from them. A provider contradicting a populated value is the
     same shape of conflict as a post-final score.

SERIALIZATION IS THE LEAGUE ROW PLUS DB UNIQUENESS, IN THAT ORDER AND FOR
DIFFERENT REASONS. The `SELECT ... FOR UPDATE` on the League row serializes
concurrent refreshes of the same league inside one process lifetime, so two
workers cannot interleave read-modify-write on the same matchup. The UNIQUE
indexes are what survive a crash, a lost lock or a worker on another host —
they are the durable guarantee, and the lock is the cheap one. Neither alone is
sufficient; this is the same two-layer discipline betting/pool_settlement.py
uses for pool instances.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from providers.base import ProviderWeek
from providers.errors import ProviderConflictError, ProviderIdentityError
from providers.finality import apply_finality, assert_never_retracted
from providers.identity import (
    build_team_identity_resolver,
    resolve_league,
    resolve_or_create_player,
)

#: The provider a snapshot is attributed to when its DTO does not say. A
#: ProviderLeague always carries `provider` in practice — every normalizer in
#: the repository sets it — and this exists so a hand-built DTO in a harness
#: behaves as it did before WP2 rather than raising somewhere unhelpful.
FALLBACK_PROVIDER = "yahoo"

CONFLICT_POST_FINAL_SCORE = "POST_FINAL_SCORE"
CONFLICT_POST_FINAL_WINNER = "POST_FINAL_WINNER"
CONFLICT_FINALITY_RETRACTION = "POST_FINAL_FINALITY_RETRACTION"
CONFLICT_FROZEN_BOUNDARY = "FROZEN_SEASON_BOUNDARY"


@dataclass
class RefreshResult:
    """What one league-week refresh did. Purely descriptive — no money."""

    league_id: int
    week: int
    matchups_inserted: int = 0
    matchups_updated: int = 0
    matchups_unchanged: int = 0
    matchups_finalized: int = 0
    roster_slots_written: int = 0
    players_created: int = 0
    conflicts_recorded: int = 0
    skipped_beyond_horizon: bool = False
    conflict_keys: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)
    #: WP2 — which provider produced the snapshot this result describes. An
    #: operator reading a refresh report for a stuck league should not have to
    #: re-query to learn whether it was Yahoo or Demo that answered.
    provider: str = FALLBACK_PROVIDER


def snapshot_provider(snapshot: ProviderWeek) -> str:
    """The provider a snapshot speaks for. WP2's single derivation point."""
    return getattr(snapshot.league, "provider", None) or FALLBACK_PROVIDER


# ── Conflict identity (§10) ───────────────────────────────────────────────────

def conflict_key(*, provider: str, external_identity: str,
                 conflict_type: str, contradicted_field: str,
                 existing_value: str, provider_value: str) -> str:
    """The deterministic idempotency key for one conflict.

    Derived from WHAT DISAGREES, never from when it was noticed. Re-ingesting
    the identical contradiction produces the identical key and therefore finds
    the identical row — which is what stops a nightly job that keeps seeing the
    same bad payload from writing a conflict row every night (§10).

    The contradicting VALUE is part of the key on purpose. A provider that
    reports a third, different score for the same final matchup is telling us
    something new, and that genuinely deserves its own row.
    """
    material = "|".join((provider, external_identity, conflict_type,
                         contradicted_field, existing_value, provider_value))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def record_conflict(db, *, league_id: int, external_identity: str,
                    conflict_type: str, contradicted_field: str,
                    existing_value, provider_value, now: datetime,
                    provider: str = FALLBACK_PROVIDER,
                    audit: dict | None = None) -> str:
    """Write or bump one ProviderConflict. Returns its conflict_key.

    Does NOT commit, and does NOT raise — the caller decides whether this
    conflict also aborts the refresh, and needs the row to exist in the same
    transaction as that decision.

    A repeat bumps `occurrence_count` and `last_seen_at` and touches nothing
    else. In particular it does NOT reopen an acknowledged conflict: an operator
    who acknowledged this exact contradiction has already made that call, and
    re-deciding it on their behalf every time the feed is polled would make
    acknowledgement useless.
    """
    from db.schema import ProviderConflict

    existing_text = "NULL" if existing_value is None else str(existing_value)
    provider_text = "NULL" if provider_value is None else str(provider_value)

    key = conflict_key(provider=provider, external_identity=external_identity,
                       conflict_type=conflict_type,
                       contradicted_field=contradicted_field,
                       existing_value=existing_text,
                       provider_value=provider_text)

    row = (db.query(ProviderConflict)
           .filter(ProviderConflict.conflict_key == key)
           .with_for_update()
           .first())
    if row is not None:
        row.occurrence_count = int(row.occurrence_count or 1) + 1
        row.last_seen_at = now
        db.flush()
        return key

    db.add(ProviderConflict(
        league_id=league_id,
        provider=provider,
        external_identity=external_identity,
        conflict_type=conflict_type,
        contradicted_field=contradicted_field,
        existing_value=existing_text,
        provider_value=provider_text,
        conflict_key=key,
        detected_at=now,
        last_seen_at=now,
        occurrence_count=1,
        audit_metadata=audit or None,
    ))
    db.flush()
    return key


def open_conflicts(db, *, league_id: int) -> list:
    """Every unresolved conflict for a league. Read by season close (§11)."""
    from db.schema import ProviderConflict

    return (db.query(ProviderConflict)
            .filter(ProviderConflict.league_id == league_id,
                    ProviderConflict.resolved_at.is_(None))
            .order_by(ProviderConflict.id)
            .all())


def acknowledge_conflict(db, *, conflict_key_value: str, operator: str,
                         note: str | None = None,
                         now: datetime | None = None) -> None:
    """Mark one conflict acknowledged. MOVES NO MONEY, BY DESIGN.

    S6-R3 forbids automatic economic reversal in Sprint 6. Acknowledgement
    records that a human looked at a contradiction and accepted the stored
    value; it does not correct anything, and there is deliberately no code path
    here that could.
    """
    from db.schema import ProviderConflict

    now = now or datetime.now(timezone.utc)
    row = (db.query(ProviderConflict)
           .filter(ProviderConflict.conflict_key == conflict_key_value)
           .with_for_update()
           .first())
    if row is None:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN,
            f"no ProviderConflict with key {conflict_key_value!r}")
    if row.resolved_at is not None:
        return
    row.resolved_at = now
    row.resolved_by = operator
    row.resolution_note = note
    db.flush()


# ── Season boundaries (§12) ───────────────────────────────────────────────────

def _reconcile_boundary(db, league, *, field_name: str, provider_value,
                        league_key: str, now: datetime, result: RefreshResult,
                        provider: str = FALLBACK_PROVIDER) -> None:
    """Populate a season boundary once; conflict if the provider contradicts it.

    Three cases, and only the first writes:

        stored is NULL, provider reports  -> populate (first measurement)
        stored == provider                -> no-op
        stored != provider                -> ProviderConflict, stored value kept

    The third case does NOT abort the refresh. A boundary disagreement does not
    make this week's scores wrong, and refusing the whole refresh over it would
    strand live matchup data. It is recorded, it is unresolved, and §11 makes it
    block season close — which is the point at which a wrong boundary would
    actually cost money.
    """
    if provider_value is None:
        return
    stored = getattr(league, field_name)
    if stored is None:
        setattr(league, field_name, int(provider_value))
        result.notes.append(
            f"{field_name} populated from provider: {provider_value}")
        db.flush()
        return
    if int(stored) == int(provider_value):
        return

    key = record_conflict(
        db, league_id=league.id, external_identity=league_key,
        conflict_type=CONFLICT_FROZEN_BOUNDARY,
        contradicted_field=field_name, provider=provider,
        existing_value=stored, provider_value=provider_value, now=now,
        audit={"league_key": league_key, "field": field_name})
    result.conflicts_recorded += 1
    result.conflict_keys = result.conflict_keys + (key,)
    result.notes.append(
        f"{field_name} CONFLICT: stored {stored} kept, provider claimed "
        f"{provider_value} — recorded, not overwritten (§12).")


# ── Matchup persistence (§9) ──────────────────────────────────────────────────

def _find_matchup(db, *, league_id: int, week: int, matchup_key: str,
                  home_id: int, away_id: int):
    """Locate the existing row for this provider matchup, if any.

    TWO LOOKUPS, IN PRIORITY ORDER, AND THE SECOND IS AN ADOPTION PATH.

    First by provider key — the authoritative identity. Second by the UNORDERED
    internal team pair, which finds a row written before Sprint 6 (or by the
    legacy Tuesday upsert) that carries no provider key. Adopting such a row is
    strictly better than inserting beside it: an insert would violate
    uq_matchups_unordered_pair anyway, and adopting preserves whatever finality
    and settlement history the existing row already carries.

    The pair lookup is order-insensitive — it matches (A home, B away) and
    (B home, A away) alike — which is the same mirror-immunity the derived key
    has, applied to rows that predate it.
    """
    from db.schema import Matchup

    row = (db.query(Matchup)
           .filter(Matchup.league_id == league_id,
                   Matchup.provider_matchup_key == matchup_key)
           .with_for_update()
           .first())
    if row is not None:
        return row

    pair = {home_id, away_id}
    candidates = (db.query(Matchup)
                  .filter(Matchup.league_id == league_id,
                          Matchup.week == week)
                  .with_for_update()
                  .all())
    for candidate in candidates:
        if {candidate.home_team_id, candidate.away_team_id} == pair:
            return candidate
    return None


def _persist_matchup(db, *, league, provider_matchup, resolver, now: datetime,
                     provider: str, result: RefreshResult) -> None:
    from db.schema import Matchup

    home_id = resolver.to_internal(provider_matchup.home_team_key)
    away_id = resolver.to_internal(provider_matchup.away_team_key)
    winner_id = (resolver.to_internal(provider_matchup.winner_team_key)
                 if provider_matchup.winner_team_key else None)

    row = _find_matchup(db, league_id=league.id, week=provider_matchup.week,
                        matchup_key=provider_matchup.matchup_key,
                        home_id=home_id, away_id=away_id)

    # Scores are NOT NULL in the accepted schema, so a pre-event matchup with no
    # provider score is stored as 0.0 — exactly as Sprint 1-5 stored it. That is
    # safe ONLY because finalized_at is what carries finality; the score is
    # never consulted to decide whether a result happened. This is the
    # conflation db/schema.py's finalized_at comment exists to describe.
    home_points = (0.0 if provider_matchup.home_points is None
                   else float(provider_matchup.home_points))
    away_points = (0.0 if provider_matchup.away_points is None
                   else float(provider_matchup.away_points))

    if row is None:
        row = Matchup(
            league_id=league.id,
            week=provider_matchup.week,
            home_team_id=home_id,
            away_team_id=away_id,
            home_score=home_points,
            away_score=away_points,
            winner_team_id=winner_id,
            refreshed_at=now,
            provider_matchup_key=provider_matchup.matchup_key,
        )
        db.add(row)
        db.flush()
        changed, _retraction = apply_finality(
            row, provider_matchup.finality, observed_at=now)
        if changed:
            result.matchups_finalized += 1
        result.matchups_inserted += 1
        db.flush()
        return

    finalized_before = row.finalized_at

    # Adopt a pre-Sprint-6 row into provider identity. This is the ONLY write to
    # provider_matchup_key that touches an existing row, and it only ever fills
    # a NULL — a row already bound to a different provider key is a different
    # matchup and would not have been returned by the pair lookup for this week.
    if row.provider_matchup_key is None:
        row.provider_matchup_key = provider_matchup.matchup_key
        result.notes.append(
            f"adopted pre-existing matchup {row.id} into provider identity "
            f"{provider_matchup.matchup_key}")

    if finalized_before is not None:
        # ── AFTER FINALITY (S6-R3) ───────────────────────────────────────────
        # Compare, never assign. Any disagreement on a load-bearing field is
        # recorded and the refresh fails closed with the stored value intact.
        conflicts: list[tuple[str, object, object, str]] = []
        if float(row.home_score) != home_points:
            conflicts.append(("home_score", row.home_score, home_points,
                              CONFLICT_POST_FINAL_SCORE))
        if float(row.away_score) != away_points:
            conflicts.append(("away_score", row.away_score, away_points,
                              CONFLICT_POST_FINAL_SCORE))
        if winner_id is not None and row.winner_team_id != winner_id:
            conflicts.append(("winner_team_id", row.winner_team_id, winner_id,
                              CONFLICT_POST_FINAL_WINNER))
        if not provider_matchup.finality.is_affirmatively_final:
            conflicts.append(("finalized_at", row.finalized_at.isoformat(),
                              provider_matchup.finality.value,
                              CONFLICT_FINALITY_RETRACTION))

        if conflicts:
            keys = []
            for field_name, existing, claimed, kind in conflicts:
                keys.append(record_conflict(
                    db, league_id=league.id,
                    external_identity=provider_matchup.matchup_key,
                    conflict_type=kind, contradicted_field=field_name,
                    existing_value=existing, provider_value=claimed, now=now,
                    provider=provider,
                    audit={"week": provider_matchup.week,
                           "matchup_id": row.id,
                           "league_key": provider_matchup.league_key}))
            result.conflicts_recorded += len(keys)
            result.conflict_keys = result.conflict_keys + tuple(keys)
            # The stored row is untouched — no score, no winner, no finality was
            # assigned above. Assert it, then refuse.
            assert_never_retracted(finalized_before, row.finalized_at)
            db.flush()
            raise ProviderConflictError(
                f"provider contradicts economically final matchup "
                f"{provider_matchup.matchup_key} on "
                f"{[c[0] for c in conflicts]!r}. Stored final state is "
                f"unchanged; {len(keys)} conflict(s) recorded. Sprint 6 builds "
                f"no automatic economic reversal (S6-R3) — resolve by hand.",
                conflict_key=keys[0],
                conflict_type=conflicts[0][3],
                external_identity=provider_matchup.matchup_key)

        # Identical repeat of a final result. refreshed_at is the ONE field a
        # post-final refresh may move — §9 names it as explicitly allowed, and
        # C-9 exempts it for exactly this reason.
        row.refreshed_at = now
        result.matchups_unchanged += 1
        assert_never_retracted(finalized_before, row.finalized_at)
        db.flush()
        return

    # ── BEFORE FINALITY (§9) — mutable facts may legitimately move ───────────
    mutated = (float(row.home_score) != home_points
               or float(row.away_score) != away_points
               or row.winner_team_id != winner_id
               or row.home_team_id != home_id
               or row.away_team_id != away_id)

    row.home_team_id = home_id
    row.away_team_id = away_id
    row.home_score = home_points
    row.away_score = away_points
    row.winner_team_id = winner_id
    row.refreshed_at = now

    changed, _retraction = apply_finality(row, provider_matchup.finality,
                                          observed_at=now)
    if changed:
        result.matchups_finalized += 1
    if mutated or changed:
        result.matchups_updated += 1
    else:
        result.matchups_unchanged += 1

    assert_never_retracted(finalized_before, row.finalized_at)
    db.flush()


# ── Roster slots ──────────────────────────────────────────────────────────────

def _persist_roster(db, *, league, snapshot: ProviderWeek, resolver,
                    provider: str, result: RefreshResult) -> None:
    """Write the week's RosterSlot rows from the provider's SELECTED positions.

    Insert-only and idempotent against the accepted UNIQUE (team_id, player_id,
    week), matching FR-5.7's established semantics: a captured week is never
    overwritten. The slot written is the provider's weekly selected position and
    NEVER display_position (§13) — normalize.py already refused to merge them,
    and this layer never sees the display value at all.
    """
    from db.schema import RosterSlot

    if not snapshot.roster_entries:
        return

    existing = {
        (row.team_id, row.player_id)
        for row in db.query(RosterSlot.team_id, RosterSlot.player_id)
        .filter(RosterSlot.league_id == league.id,
                RosterSlot.week == snapshot.week).all()
    }

    for entry in snapshot.roster_entries:
        team_id = resolver.to_internal(entry.team_key)
        player = resolve_or_create_player(
            db, player_key=entry.player_key, name=entry.name,
            position=(entry.eligible_positions[0]
                      if entry.eligible_positions else None),
            nfl_team=entry.nfl_team, provider=provider)
        if (team_id, player.id) in existing:
            continue
        db.add(RosterSlot(league_id=league.id, team_id=team_id,
                          player_id=player.id, week=snapshot.week,
                          slot=entry.slot))
        existing.add((team_id, player.id))
        result.roster_slots_written += 1
    db.flush()


# ── The refresh entry point ───────────────────────────────────────────────────

def refresh_league_week(db, snapshot: ProviderWeek, *,
                        now: datetime | None = None,
                        allow_future_weeks: bool = False) -> RefreshResult:
    """Persist one provider league-week. Does NOT commit.

    The caller owns the transaction, so the conflict rows written here land
    atomically with (and survive) the refusal that accompanies them.

    `allow_future_weeks` exists only so a caller can state, explicitly and in
    writing, that it intends to breach the §6 horizon. Nothing in production
    sets it; it is there so a future package that genuinely needs a forward
    schedule has to say so at the call site rather than quietly widening the
    default.

    WP2: THE PROVIDER IS THE SNAPSHOT'S OWN. Identity is resolved under
    `snapshot.league.provider`, so a Demo snapshot resolves Demo rows and a
    Yahoo snapshot resolves Yahoo rows, through one code path with no branch.
    """
    from db.schema import League

    now = now or snapshot.observed_at or datetime.now(timezone.utc)
    provider = snapshot_provider(snapshot)
    resolved = resolve_league(db, league_key=snapshot.league.league_key,
                              provider=provider)

    # THE SERIALIZATION POINT. Every concurrent refresh of this league queues
    # here, so the read-modify-write on each matchup below is exclusive.
    league = (db.query(League)
              .filter(League.id == resolved.league_id)
              .with_for_update()
              .first())

    result = RefreshResult(league_id=league.id, week=snapshot.week,
                           provider=provider)

    # §12 — boundaries first, so a boundary conflict is recorded even if the
    # week's matchups are later refused.
    for field_name, value in (
        ("season_final_week", snapshot.league.season_final_week),
        ("playoff_start_week", snapshot.league.playoff_start_week),
        # ECONCFG-F1 — the season's first scoring week, reconciled on exactly
        # the same discipline as the other two boundaries. It is frozen for the
        # same reason: the configurable season economy derives its week count
        # from it, so a provider that later contradicts it is contradicting the
        # basis on which Credits were already issued.
        ("start_week", snapshot.league.start_week),
    ):
        _reconcile_boundary(db, league, field_name=field_name,
                            provider_value=value,
                            league_key=snapshot.league.league_key, now=now,
                            provider=provider, result=result)

    # §6 — THE INGESTION HORIZON. Checked before any matchup is written.
    current_week = snapshot.league.current_week

    # S8-P4C-3: RECORD THE PROVIDER'S CURRENT WEEK. It already governs the
    # horizon below; persisting it lets read models answer "which week is it"
    # from the provider's own statement instead of a constant.
    #
    # LAST WRITER WINS, deliberately, and this is NOT a boundary reconciliation.
    # `_reconcile_boundary` exists for season_final_week / playoff_start_week,
    # where a provider contradicting an already-frozen value is a CONFLICT
    # because the economy has been built on it. The current week is the opposite
    # kind of fact: it is expected to advance, and a refresh reporting a later
    # week is the normal case rather than a disagreement.
    if current_week is not None and league.provider_current_week != current_week:
        league.provider_current_week = current_week
        db.add(league)
    if (not allow_future_weeks and current_week is not None
            and snapshot.week > current_week):
        result.skipped_beyond_horizon = True
        result.notes.append(
            f"week {snapshot.week} is beyond the provider's current week "
            f"{current_week}; no matchup rows persisted. Accepted Sprint 5 "
            f"season close derives played_weeks from Matchup row existence, so "
            f"pre-creating future weeks would silently expand the set of weeks "
            f"the close demands a Skunk assessment for (§6).")
        db.flush()
        return result

    resolver = build_team_identity_resolver(db, league_id=league.id,
                                            provider=provider)

    for provider_matchup in snapshot.matchups:
        _persist_matchup(db, league=league, provider_matchup=provider_matchup,
                         resolver=resolver, now=now, provider=provider,
                         result=result)

    _persist_roster(db, league=league, snapshot=snapshot, resolver=resolver,
                    provider=provider, result=result)

    db.flush()
    return result


def refresh_season(db, snapshots, *, now: datetime | None = None
                   ) -> list[RefreshResult]:
    """Replay a sequence of league-week snapshots in order.

    Used by C-15's full-season replay. Deliberately not a transaction manager:
    the caller commits per week, which is what a real weekly job does.
    """
    return [refresh_league_week(db, snapshot, now=now) for snapshot in snapshots]


def snapshot_digest(snapshot: ProviderWeek) -> str:
    """A stable digest of one normalized snapshot, for replay-equality checks.

    C-9 asserts a second replay produces the same DOMAIN state; this is the
    complementary assertion that it was handed the same INPUT, so a passing
    C-9 cannot be explained by the second replay having quietly received
    different data.
    """
    payload = {
        "league": snapshot.league.league_key,
        "week": snapshot.week,
        "matchups": sorted(
            (m.matchup_key, m.home_team_key, m.away_team_key,
             m.home_points, m.away_points, m.finality.value, m.winner_team_key)
            for m in snapshot.matchups),
        "rosters": sorted(
            (r.team_key, r.player_key, r.slot) for r in snapshot.roster_entries),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
