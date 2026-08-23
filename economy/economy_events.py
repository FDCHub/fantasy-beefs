"""
Sprint 5 economy event identities and account names.

THE KEY IS A PURE FUNCTION OF THE EVENT. No timestamp, no random value, no
retry counter — recomputing it from the same event always yields the same
string, which is what makes `uq_economy_event_key` an idempotency guard rather
than a duplicate-row detector.

The four shapes are encoded in the key itself, so a per-GM weekly event and a
league-season event can never collide even though they share a table:

    release:{league}:{season}:{week}:{team}
    skunk_assessment:{league}:{season}:{week}
    opening_allocation:{league}:{season}:{team}
    championship_distribution:{league}:{season}

ACCOUNT NAMES LIVE HERE TOO, for one reason: every Sprint 5 module posts to the
same six account families, and a single mistyped prefix at one call site would
create a real, balanced, permanently-stranded account that no reader queries and
no invariant covers. One definition each, imported everywhere.
"""

from __future__ import annotations

from ledger.ledger import CHAMPIONSHIP_POT_MINT_DOOR

# ── Account names ─────────────────────────────────────────────────────────────

def wallet_account(team_id: int) -> str:
    return f"wallet:{team_id}"


def min_reserve_account(team_id: int) -> str:
    """The GM's undrawn Weekly Minimum allocation for the season (S5-R2)."""
    return f"min_reserve:{team_id}"


def min_account(team_id: int, week: int) -> str:
    """One week's released Weekly Minimum. Spent before wallet."""
    return f"min:{team_id}:{week}"


def expired_min_account(team_id: int) -> str:
    """LEGACY-ERA ONLY (RULESET_LEGACY). Weekly Minimum that expired unspent.

    NO FINAL POR SEASON EVER WRITES HERE. WP-4 replaced the destination: under
    `RULESET_FINAL_POR` an unspent Weekly Minimum is swept at WEEK close to
    `fantasystakes_championship:{league}:{season}` and is gone from the GM's
    asset position for good. This account name survives because the postings
    already made under the legacy era are real, are still read by Current
    Settle and the Week Ledger, and are still returned to Wallet at legacy
    season close. It is a READ surface for those seasons, not a write target
    for new ones.

    WHAT IT MEANT UNDER THE LEGACY ERA. Money that left circulation but remained
    the GM's asset: not swept to championship, not returned to Wallet during the
    season, credited back only at season-end reconciliation. It stayed inside
    the settlement-relevant asset set throughout, which is why the legacy
    `min: -> expired_min:` moved Current Settle by exactly zero — and precisely
    what the Final POR sweep changes, deliberately and once."""
    return f"expired_min:{team_id}"


def reserve_account(team_id: int) -> str:
    """The GM's Championship Reserve — GM-keyed for provenance, economically
    committed to the Championship pot from activation. Never spendable, never
    releasable to Wallet, and NOT part of the settlement-relevant asset set."""
    return f"reserve:{team_id}"


def receivable_account(team_id: int) -> str:
    """The GM's protocol obligation account. Skunk assessments land here.

    Exempt from the ledger's non-negative guard, which is what lets an
    obligation be recorded without any wallet having to fund it (S5-R1)."""
    return f"receivable:{team_id}"


def season_issuance_account(league_id: int, season: int) -> str:
    """The season-OPENING issuance tally (owner ruling, S5-P1).

    DELIBERATELY A DIFFERENT NAMESPACE FROM bab_issuance. B6 fixed that
    account's funded-balance exemption to the canonical approved Top-Off door
    and proved it by naming `season_allocation` as a door that must NOT be
    exempt on it. Keeping the two apart leaves every one of those assertions
    intact AND keeps the two obligations independently derivable from posted
    state, which is what S5-P2/P3 Current Settle needs:

        season_issuance:{league}:{season}   the season-opening advance
        bab_issuance:{league}:{season}      approved Top-Off issuance

    Not a real-money account and never described as one."""
    return f"season_issuance:{league_id}:{season}"


def topoff_issuance_account(league_id: int, season: int) -> str:
    """The approved Top-Off issuance tally. Written only under the canonical
    Top-Off door; the opening allocation must never use it."""
    return f"bab_issuance:{league_id}:{season}"


def skunk_account(league_id: int) -> str:
    return f"skunk:{league_id}"


def championship_account(league_id: int) -> str:
    return f"championship:{league_id}"


def fantasystakes_championship_account(league_id: int, season: int) -> str:
    """The league-season FantasyStakes Championship Pot.

    THE ONE DEFINITION OF THIS NAME. `economy.fantasystakes_championship_
    allocation.pot_account` was where it lived and now delegates here, because
    WP-4 made a second module post into it and this file's contract is one
    definition per account family. Two spellings of a league-season pot would
    be two real, balanced, permanently-divergent pots.

    SEASON-SCOPED, UNLIKE `championship:{league}`. A pot that accumulates
    across seasons cannot be distributed at the end of any one of them.

    NOT A GM ACCOUNT. It is deliberately outside the settlement-relevant asset
    set, which is the whole mechanism by which a Weekly Minimum swept here
    reduces that GM's Current Settle exactly once and permanently (WP-4)."""
    return f"fantasystakes_championship:{league_id}:{season}"


def points_championship_account(league_id: int, season: int) -> str:
    """The league-season Points Championship Pot (Final POR §12).

    THE SEASON-SCOPED SUCCESSOR TO `skunk:{league}`. Its balance is the Skunk
    ACTUALLY ASSESSED this season and nothing else — not a projection, not a
    minted allocation. That is why it has no mint door: a Points pot that could
    be minted could disagree with the fees the league really paid.

    A LEAGUE PLAYING A SECOND SEASON IS THE WHOLE REASON FOR THE SCOPE.
    `skunk:{league}` accumulates across seasons, so season two would distribute
    season one's unpaid Skunk. Every other Final POR pot is season-scoped for
    the same reason: a pot that outlives its season cannot be distributed at
    the end of one."""
    return f"points_championship:{league_id}:{season}"


def ff_championship_account(league_id: int, season: int) -> str:
    """The league-season Fantasy Football Championship Pot (Final POR §14).

    ONE COMMISSIONER-ENTERED LEAGUE AMOUNT, WHICH MAY BE ZERO, minted at
    activation and frozen there. It NEVER accretes: no sweep, no remainder, no
    Top-Off and no forfeiture is ever credited here. A pot that grows from
    unrelated sources is a pot whose size no commissioner ever agreed to, and
    this is the one pillar whose settlement is gated on provider finality — a
    balance that moved after activation could not be reconciled against the
    amount the league was told it was playing for."""
    return f"ff_championship:{league_id}:{season}"


def championship_issuance_account(league_id: int, season: int) -> str:
    """The league-season MINTED-POT issuance tally (Final POR §11, Model B).

    NOT A GM OBLIGATION, AND THAT IS ITS ENTIRE PURPOSE. `season_issuance:` and
    `bab_issuance:` are both counted against GMs by Current Settle. This third
    namespace exists so a minted league-level pot is derivable from posted state
    WITHOUT being derivable as anybody's debt — the distinction Model B rests on.

    Its debit balance is the tally of every Credit this league-season has minted
    into a championship pot. Exempt from the funded-balance guard under
    `CHAMPIONSHIP_POT_MINT_DOOR` and under no other door."""
    return f"championship_issuance:{league_id}:{season}"


#: The pre-league-scoping global account. READ for consolidation, never written.
LEGACY_CHAMPIONSHIP_ACCOUNT = "championship"

#: The three governed Final POR championship pots, by pillar. ENUMERATED so a
#: reader, a conservation assertion and the Grand Championship's funded-pillar
#: test all consult ONE list rather than three independent spellings.
PILLAR_FANTASYSTAKES = "fantasystakes"
PILLAR_POINTS = "points"
PILLAR_FANTASY_FOOTBALL = "fantasy_football"

CHAMPIONSHIP_PILLARS: tuple[str, ...] = (
    PILLAR_FANTASYSTAKES, PILLAR_POINTS, PILLAR_FANTASY_FOOTBALL,
)


def championship_pot_account(pillar: str, league_id: int, season: int) -> str:
    """The governed pot account for one pillar of one league-season."""
    if pillar == PILLAR_FANTASYSTAKES:
        return fantasystakes_championship_account(league_id, season)
    if pillar == PILLAR_POINTS:
        return points_championship_account(league_id, season)
    if pillar == PILLAR_FANTASY_FOOTBALL:
        return ff_championship_account(league_id, season)
    raise ValueError(
        f"{pillar!r} is not a governed championship pillar "
        f"(known: {CHAMPIONSHIP_PILLARS}).")


#: Account namespaces RETIRED for Final POR seasons (WP-5). Kept as data so the
#: retirement is testable by enumeration rather than by remembering every site.
#: READABLE FOREVER — every posting already made to these is real history and is
#: still read by legacy-season close, Current Settle and the Week Ledger. What is
#: retired is NEW WRITES BY A FINAL POR SEASON, nothing else.
RETIRED_FOR_FINAL_POR_PREFIXES: tuple[str, ...] = (
    "reserve:",          # the per-GM Championship Reserve contribution
    "championship:",     # the season-less league championship pot
)
RETIRED_FOR_FINAL_POR_ACCOUNTS: tuple[str, ...] = (
    LEGACY_CHAMPIONSHIP_ACCOUNT,   # the bare pre-league-scoping account
    "skunk:",                      # season-less; superseded by points_championship:
)


# ── Event types ───────────────────────────────────────────────────────────────

EVENT_OPENING_ALLOCATION = "OPENING_ALLOCATION"
EVENT_WEEKLY_MINIMUM_RELEASE = "WEEKLY_MINIMUM_RELEASE"
EVENT_WEEKLY_MINIMUM_EXPIRY = "WEEKLY_MINIMUM_EXPIRY"

#: WP-4. Week close under `RULESET_FINAL_POR`: the unspent Weekly Minimum is
#: swept to the FantasyStakes Championship Pot. A DISTINCT event type from
#: `EVENT_WEEKLY_MINIMUM_EXPIRY`, not a reuse of it, because the two move the
#: same cents to economically opposite places and an audit that cannot tell
#: them apart cannot answer "where did this GM's Week 3 Minimum go?".
EVENT_WEEKLY_MINIMUM_SWEEP = "WEEKLY_MINIMUM_SWEEP"
EVENT_SKUNK_ASSESSMENT = "SKUNK_ASSESSMENT"

#: WP-12 — a Skunk correction, in its two halves.
#:
#: TWO EVENT TYPES, NOT ONE, because the two halves answer different questions
#: and an audit needs both: "what did we un-assess?" and "what did we assess
#: instead?". A single event type carrying a net figure could not say who was
#: wrongly charged, which is the whole reason a correction happens.
#:
#: BOTH ARE SKUNK-SCORING EVENTS. `economy.skunk.skunk_fees_by_team` sums
#: `receivable:` legs across this family and negates once, so a reversal's
#: positive leg nets against the original's negative leg with no special case
#: and with both postings preserved in full. WP-3 wrote that derivation with
#: this in mind and says so at the site.
EVENT_SKUNK_ASSESSMENT_REVERSAL = "SKUNK_ASSESSMENT_REVERSAL"
EVENT_SKUNK_ASSESSMENT_CORRECTION = "SKUNK_ASSESSMENT_CORRECTION"
EVENT_SKUNK_OBLIGATION = "SKUNK_OBLIGATION"
EVENT_SKUNK_DISTRIBUTION = "SKUNK_DISTRIBUTION"
EVENT_RESERVE_SWEEP = "RESERVE_SWEEP"
EVENT_LEGACY_CHAMPIONSHIP_CONSOLIDATION = "LEGACY_CHAMPIONSHIP_CONSOLIDATION"
EVENT_CHAMPIONSHIP_DISTRIBUTION = "CHAMPIONSHIP_DISTRIBUTION"
EVENT_EXPIRED_MINIMUM_RECONCILIATION = "EXPIRED_MINIMUM_RECONCILIATION"

#: WP-5 — one minted league-level pot allocation. The pillar is carried in the
#: event key, not in three separate event types, so "what did this league-season
#: mint?" is one query rather than a union of three.
EVENT_CHAMPIONSHIP_POT_MINT = "CHAMPIONSHIP_POT_MINT"


# ── Doors ─────────────────────────────────────────────────────────────────────

DOOR_WEEKLY_MINIMUM_RELEASE = "weekly_minimum_release"
DOOR_WEEKLY_MINIMUM_EXPIRY = "weekly_minimum_expiry"
DOOR_WEEKLY_MINIMUM_SWEEP = "weekly_minimum_sweep"
DOOR_SKUNK_ASSESSMENT = "skunk_assessment"

#: WP-12. DISTINCT FROM `DOOR_SKUNK_ASSESSMENT`, deliberately. A correction is
#: not an ordinary assessment, and conflating them would make the two
#: indistinguishable in the ledger forever — the same rule RC2's championship
#: correction applies for the same reason.
DOOR_SKUNK_CORRECTION_REVERSAL = "skunk_correction_reversal"
DOOR_SKUNK_CORRECTION_REPOST = "skunk_correction_repost"
DOOR_SKUNK_DISTRIBUTION = "skunk_distribution"
DOOR_RESERVE_SWEEP = "championship_reserve_sweep"
DOOR_LEGACY_CHAMPIONSHIP_CONSOLIDATION = "legacy_championship_consolidation"
DOOR_CHAMPIONSHIP_DISTRIBUTION = "championship_distribution"
DOOR_EXPIRED_MINIMUM_RECONCILIATION = "expired_minimum_reconciliation"

#: WP-5. Re-exported from `ledger.ledger`, which OWNS it because the
#: funded-balance exemption is keyed on it (imported at the top of this file).
#: Named here by convention with every other door; the literal has ONE
#: definition, in the module whose guard reads it.
DOOR_CHAMPIONSHIP_POT_MINT = CHAMPIONSHIP_POT_MINT_DOOR


# ── Key builders ──────────────────────────────────────────────────────────────

def gm_week_key(event_type: str, league_id: int, season: int, week: int,
                team_id: int) -> str:
    return f"{event_type}:{league_id}:{season}:{week}:{team_id}"


def league_week_key(event_type: str, league_id: int, season: int,
                    week: int) -> str:
    return f"{event_type}:{league_id}:{season}:{week}"


def gm_season_key(event_type: str, league_id: int, season: int,
                  team_id: int) -> str:
    return f"{event_type}:{league_id}:{season}:gm:{team_id}"


def league_season_key(event_type: str, league_id: int, season: int) -> str:
    return f"{event_type}:{league_id}:{season}"


def correction_week_key(event_type: str, league_id: int, season: int,
                        week: int, generation: int) -> str:
    """A CORRECTION-AWARE league-week key (WP-12).

    A corrected week is assessed more than once, so the plain league-week key
    can only ever claim the FIRST assessment — every correction after it would
    collide with the original and silently do nothing. The generation makes each
    restatement independently exactly-once while leaving the original key, and
    the original event row, exactly as they were.

        generation 0   the original assessment, under `league_week_key`
        generation n   the nth restatement, under this key
    """
    return f"{event_type}:{league_id}:{season}:{week}:gen{generation}"


def pillar_season_key(event_type: str, pillar: str, league_id: int,
                      season: int) -> str:
    """One league-season event that happens once PER PILLAR (WP-5).

    A fifth key shape, and a necessary one: three pots are minted for the same
    league-season, so `league_season_key` would make the second and third mint
    collide with the first and silently mint nothing."""
    return f"{event_type}:{pillar}:{league_id}:{season}"


# ── Recording ─────────────────────────────────────────────────────────────────

class DuplicateEconomyEvent(Exception):
    """This event has already been recorded. Nothing was written by this call."""

    def __init__(self, event_key: str) -> None:
        self.event_key = event_key
        super().__init__(f"economy event {event_key!r} already recorded")


def record_event(db, *, event_key: str, league_id: int, season: int,
                 event_type: str, amount_cents: int, week: int | None = None,
                 team_id: int | None = None, posting_id=None, now=None):
    """Claim one economy event. Does NOT commit — the caller owns the
    transaction, which is what makes the claim atomic with its posting.

    Uses INSERT ... ON CONFLICT DO NOTHING rather than a preceding SELECT: two
    concurrent workers both see no row, and only the constraint decides. Raises
    `DuplicateEconomyEvent` so callers branch on a domain type rather than on a
    driver IntegrityError.
    """
    from datetime import datetime, timezone

    from sqlalchemy import text

    now = now or datetime.now(timezone.utc)
    row = db.execute(text("""
        INSERT INTO economy_event
            (event_key, league_id, season, week, team_id, event_type,
             posting_id, amount_cents, created_at)
        VALUES (:key, :league_id, :season, :week, :team_id, :event_type,
                :posting_id, :amount, :now)
        ON CONFLICT (event_key) DO NOTHING
        RETURNING id
    """), {
        "key": event_key, "league_id": league_id, "season": season,
        "week": week, "team_id": team_id, "event_type": event_type,
        "posting_id": str(posting_id) if posting_id is not None else None,
        "amount": amount_cents, "now": now,
    }).fetchone()
    if row is None:
        raise DuplicateEconomyEvent(event_key)
    return row[0]


def event_exists(db, event_key: str) -> bool:
    from db.schema import EconomyEvent

    return (db.query(EconomyEvent)
            .filter(EconomyEvent.event_key == event_key).count()) > 0