"""
economy/skunk_correction.py — restating a Skunk after a provider correction (WP-12).

WHY SKUNK NEEDS A CORRECTION PATH AT ALL. The Skunk is assessed on the LARGEST
MARGIN OF DEFEAT in a week. A provider correction that moves one score by a
point can move the whole determination onto a different GM — not change an
amount, change WHO WAS CHARGED. Nothing else in the economy has that shape, and
it is why the delta-posting idiom RC2 uses for championship results is the wrong
tool here: a delta says "you are owed 3 more Credits", and what actually needs
saying is "you were never the Skunk; they were".

── REVERSE, RE-DERIVE, RE-POST ─────────────────────────────────────────────

    1. REVERSE   post the exact inverse of the standing assessment's legs,
                 under `DOOR_SKUNK_CORRECTION_REVERSAL`
    2. RE-DERIVE run `determine_skunk_losers` again over the corrected scores
    3. RE-POST   assess the same governing fee against the newly determined
                 GM(s), under `DOOR_SKUNK_CORRECTION_REPOST`

The REVERSAL IS SOURCE-FAITHFUL: it reads the standing posting's own legs back
out of the ledger and negates each one. It does not recompute what the original
"should have" been, because the original may have been made under a fee that has
since been reconfigured, or a canonical split across a tie that this build would
reproduce identically but need not — and either way the thing being undone is
what was actually posted, not a reconstruction of it.

── THE DERIVATION RUNS BEFORE THE REVERSAL, AND POSTS NOTHING IF NOTHING MOVED ─

Step 2 is a pure read, so it is done FIRST and its outcome compared with the
standing one. A provider correction that does not change who was skunked, or by
how much, writes NOTHING — no reversal, no restatement, no event. A correction
path that churned a balanced pair of postings every time a score was refreshed
would bury the real corrections in noise and make "was this week ever corrected?"
unanswerable. The POSTING order is still reverse-then-repost, which is the part
that has to be true of the ledger.

── CORRECTION-AWARE EVENT KEYS, AND WHY THE PLAIN ONE WOULD NOT DO ─────────

    generation 0   SKUNK_ASSESSMENT:{L}:{S}:{W}                original
    generation n   SKUNK_ASSESSMENT_REVERSAL:{L}:{S}:{W}:gen{n-1}
                   SKUNK_ASSESSMENT_CORRECTION:{L}:{S}:{W}:gen{n}

A corrected week is assessed more than once, and the plain league-week key can
only ever claim the first assessment — every later restatement would collide
with the original and silently do nothing while reporting success. The
generation makes each restatement independently exactly-once. A week may be
corrected repeatedly; generation n always reverses generation n-1, so the chain
stays balanced however long it grows.

── PROVENANCE IS PRESERVED, NOT TIDIED ─────────────────────────────────────

Nothing is deleted, updated or backdated. The original event row and its posting
stay exactly as they were; a correction only ever APPENDS. `history()` reads the
whole chain back, so "who was charged for week 3, and when did that change?" is
answerable from posted state alone.

── THE SCORE NETS WITHOUT A SPECIAL CASE ───────────────────────────────────

All three event types are in `SKUNK_SCORING_EVENT_TYPES`, and
`economy.skunk.skunk_fees_by_team` sums `receivable:` legs across that family
and negates once. The original's negative leg, the reversal's positive leg and
the restatement's new negative leg therefore net to exactly the corrected
per-GM figure. WP-3 wrote that derivation for this and says so at the site.

── ERA ─────────────────────────────────────────────────────────────────────

`RULESET_FINAL_POR` only. A legacy season's Skunk was assessed, distributed and
in some cases paid out under rules this module does not implement; restating one
would move real Credits on an authority that does not exist for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from economy.economy_events import (
    DOOR_SKUNK_CORRECTION_REPOST,
    DOOR_SKUNK_CORRECTION_REVERSAL,
    EVENT_SKUNK_ASSESSMENT,
    EVENT_SKUNK_ASSESSMENT_CORRECTION,
    EVENT_SKUNK_ASSESSMENT_REVERSAL,
    correction_week_key,
    league_week_key,
    receivable_account,
    record_event,
)
from ledger.ledger import _balance_of_in_session, post as ledger_post
from ruleset import is_final_por


class SkunkCorrectionError(ValueError):
    """A Skunk correction was refused, carrying a stable reason code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_WRONG_ERA = "SKUNK_CORRECTION_WRONG_ERA"
REASON_NEVER_ASSESSED = "SKUNK_CORRECTION_NEVER_ASSESSED"
REASON_POT_DISTRIBUTED = "SKUNK_CORRECTION_POT_DISTRIBUTED"
REASON_LEAGUE_NOT_FOUND = "SKUNK_CORRECTION_LEAGUE_NOT_FOUND"
REASON_NO_POSTING = "SKUNK_CORRECTION_NO_POSTING"


@dataclass(frozen=True)
class SkunkGeneration:
    """One link in a league-week's Skunk chain, as posted."""

    generation: int
    event_type: str
    event_key: str
    posting_id: str | None
    amount_cents: int
    #: (team_id, cents) charged by THIS generation, positive magnitudes.
    assessed: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class SkunkCorrectionResult:
    league_id: int
    season: int
    week: int
    #: False when the re-derivation agreed with the standing assessment. Nothing
    #: was posted and no event was recorded.
    changed: bool
    generation: int
    #: Who was charged before, and who is charged now. Positive magnitudes.
    previous_assessed: tuple[tuple[int, int], ...]
    corrected_assessed: tuple[tuple[int, int], ...]
    reversed_cents: int
    reposted_cents: int


def _league(db, league_id: int):
    from db.schema import League

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise SkunkCorrectionError(REASON_LEAGUE_NOT_FOUND,
                                   f"league {league_id} not found")
    return league


def _norm(value) -> str:
    """The dialect-safe posting-id form, matching `skunk_fees_by_team`.

    THE SAME NORMALISATION, NOT A SECOND ONE. `economy_event.posting_id` is
    written through raw SQL as a dashed string while `ledger_entries.posting_id`
    is written through the ORM dashless, so a plain equality join returns zero
    rows on SQLite and every row on PostgreSQL. WP-3's derivation normalises
    both sides at read time for exactly this reason and deliberately leaves the
    WRITE formats alone; this module does the same rather than inventing a
    second, differently-shaped workaround for the same defect.
    """
    return str(value).replace("-", "").lower()


def _legs_of(db, posting_id) -> tuple[tuple[str, int], ...]:
    """Every leg of one posting, as posted. Read back, never reconstructed."""
    from sqlalchemy import text

    db.flush()
    rows = db.execute(text(
        "SELECT account, amount_cents FROM ledger_entries "
        "WHERE REPLACE(LOWER(CAST(posting_id AS TEXT)), '-', '') = :p "
        "ORDER BY account"), {"p": _norm(posting_id)}).fetchall()
    return tuple((r[0], int(r[1])) for r in rows)


def _assessed_from_legs(legs) -> tuple[tuple[int, int], ...]:
    """(team_id, positive cents) from a posting's `receivable:` legs."""
    out: list[tuple[int, int]] = []
    for account, amount in legs:
        if not account.startswith("receivable:"):
            continue
        try:
            team_id = int(account.split(":", 1)[1])
        except (IndexError, ValueError):
            continue
        out.append((team_id, -int(amount)))
    return tuple(sorted(out))


def history(db, *, league_id: int, week: int,
            season: int | None = None) -> tuple[SkunkGeneration, ...]:
    """The whole assessment chain for one league-week, oldest first.

    READ-ONLY, and the answer to "who was charged for this week, and when did
    that change?" — from posted state alone, with nothing inferred.
    """
    from sqlalchemy import text

    league = _league(db, league_id)
    season = league.season if season is None else season
    db.flush()

    rows = db.execute(text(
        "SELECT event_key, event_type, posting_id, amount_cents "
        "FROM economy_event "
        "WHERE league_id = :l AND season = :s AND week = :w "
        "  AND event_type IN (:a, :r, :c) "
        "ORDER BY id"),
        {"l": league_id, "s": season, "w": week,
         "a": EVENT_SKUNK_ASSESSMENT,
         "r": EVENT_SKUNK_ASSESSMENT_REVERSAL,
         "c": EVENT_SKUNK_ASSESSMENT_CORRECTION}).fetchall()

    chain: list[SkunkGeneration] = []
    generation = 0
    for event_key, event_type, posting_id, amount in rows:
        if event_type == EVENT_SKUNK_ASSESSMENT_CORRECTION:
            generation += 1
        legs = _legs_of(db, posting_id) if posting_id else ()
        chain.append(SkunkGeneration(
            generation=generation, event_type=event_type, event_key=event_key,
            posting_id=str(posting_id) if posting_id else None,
            amount_cents=int(amount or 0),
            assessed=_assessed_from_legs(legs)))
    return tuple(chain)


def standing_assessment(db, *, league_id: int, week: int,
                        season: int | None = None) -> SkunkGeneration | None:
    """The generation currently in force for this league-week, or None.

    The LAST assessment-shaped link in the chain — the original if the week has
    never been corrected, otherwise the most recent restatement. Reversals are
    skipped: a reversal undoes, it does not stand.
    """
    assessments = [g for g in history(db, league_id=league_id, week=week,
                                      season=season)
                   if g.event_type in (EVENT_SKUNK_ASSESSMENT,
                                       EVENT_SKUNK_ASSESSMENT_CORRECTION)]
    return assessments[-1] if assessments else None


def correct_weekly_skunk(db, *, league_id: int, week: int,
                         now: datetime | None = None) -> SkunkCorrectionResult:
    """Restate one league-week's Skunk against corrected scores. No commit.

    Returns `changed=False`, having written nothing, when the corrected scores
    produce the same assessment that already stands.
    """
    from economy.skunk import (
        determine_skunk_losers, resolve_skunk_fee_cents, skunk_pot_account,
        split_by_canonical_id,
    )

    now = now or datetime.now(timezone.utc)
    league = _league(db, league_id)
    season = league.season

    if not is_final_por(db, league_id=league_id, season=season):
        raise SkunkCorrectionError(
            REASON_WRONG_ERA,
            f"league {league_id} season {season} is governed by the legacy "
            f"ruleset. Its Skunk was assessed, and may have been distributed "
            f"and paid, under rules this module does not implement; refusing "
            f"to restate it.")

    standing = standing_assessment(db, league_id=league_id, week=week,
                                   season=season)
    if standing is None:
        raise SkunkCorrectionError(
            REASON_NEVER_ASSESSED,
            f"league {league_id} week {week} has no Skunk assessment to "
            f"correct. Assess the week first; a correction restates an "
            f"existing charge and never creates the first one.")

    # ── 2. RE-DERIVE FIRST, because it is a pure read (see module docstring) ──
    # Raises RESULTS_NOT_READY if the corrected week is not final again, which
    # is right: a correction still in flight is not a result.
    losers, _margin = determine_skunk_losers(db, league_id=league_id, week=week)
    fee = int(resolve_skunk_fee_cents(db, league_id=league_id, season=season))
    corrected = (tuple(sorted(split_by_canonical_id(fee, losers).items()))
                 if losers else ())

    if corrected == standing.assessed:
        return SkunkCorrectionResult(
            league_id=league_id, season=season, week=week, changed=False,
            generation=standing.generation,
            previous_assessed=standing.assessed,
            corrected_assessed=corrected,
            reversed_cents=0, reposted_cents=0)

    pot_account = skunk_pot_account(db, league_id=league_id, season=season)
    standing_legs = _legs_of(db, standing.posting_id) if standing.posting_id \
        else ()
    if standing.assessed and not standing_legs:
        raise SkunkCorrectionError(
            REASON_NO_POSTING,
            f"league {league_id} week {week} generation {standing.generation} "
            f"records {standing.amount_cents} cents assessed but no ledger "
            f"legs can be read back for posting {standing.posting_id!r}. "
            f"Refusing to reverse a posting that cannot be read.")

    # THE POT MUST STILL HOLD WHAT IS BEING TAKEN BACK OUT OF IT. Once the
    # Points Championship has been distributed the pot is drained, and reversing
    # would drive a league-level pot negative — the ledger's guard would refuse
    # it anyway, but refusing here names the reason instead of surfacing a
    # generic shortfall, and does so before anything at all is posted.
    # The standing posting CREDITED the pot, so its leg is positive and the
    # reversal will debit exactly that much back out. Reading the credit as it
    # was posted is what makes this the amount actually at risk.
    reversing_from_pot = sum(a for acct, a in standing_legs
                             if acct == pot_account)
    if reversing_from_pot > 0:
        held = _balance_of_in_session(db, pot_account)
        if held < reversing_from_pot:
            raise SkunkCorrectionError(
                REASON_POT_DISTRIBUTED,
                f"{pot_account} holds {held} cents but reversing league "
                f"{league_id} week {week} would take {reversing_from_pot} out "
                f"of it. The pot has already been distributed, so the Credits "
                f"being un-assessed are in GM Wallets and are not this "
                f"module's to reclaim. Nothing was posted.")

    generation = standing.generation + 1

    # ── 1. REVERSE — source-faithful, every leg negated as posted ───────────
    reversal_posting = None
    reversed_cents = 0
    if standing_legs:
        reversal_posting = ledger_post(
            [(account, -amount) for account, amount in standing_legs],
            door=DOOR_SKUNK_CORRECTION_REVERSAL, session=db)
        reversed_cents = standing.amount_cents
    record_event(
        db,
        event_key=correction_week_key(EVENT_SKUNK_ASSESSMENT_REVERSAL,
                                      league_id, season, week,
                                      standing.generation),
        league_id=league_id, season=season, week=week,
        event_type=EVENT_SKUNK_ASSESSMENT_REVERSAL,
        amount_cents=reversed_cents, posting_id=reversal_posting, now=now)
    db.flush()

    # ── 3. RE-POST — the same shape an ordinary assessment posts ────────────
    repost_posting = None
    reposted_cents = 0
    if corrected:
        legs = [(receivable_account(team_id), -cents)
                for team_id, cents in corrected]
        legs.append((pot_account, sum(c for _t, c in corrected)))
        repost_posting = ledger_post(legs, door=DOOR_SKUNK_CORRECTION_REPOST,
                                     session=db)
        reposted_cents = sum(c for _t, c in corrected)
    record_event(
        db,
        event_key=correction_week_key(EVENT_SKUNK_ASSESSMENT_CORRECTION,
                                      league_id, season, week, generation),
        league_id=league_id, season=season, week=week,
        event_type=EVENT_SKUNK_ASSESSMENT_CORRECTION,
        amount_cents=reposted_cents, posting_id=repost_posting, now=now)
    db.flush()

    return SkunkCorrectionResult(
        league_id=league_id, season=season, week=week, changed=True,
        generation=generation,
        previous_assessed=standing.assessed,
        corrected_assessed=corrected,
        reversed_cents=reversed_cents, reposted_cents=reposted_cents)
