"""The shared economic finality precondition for money paths (§8).

WHY THIS EXISTS. Recon R-1 found that `betting/settlement_engine.py` never
mentions `finalized_at` — not once. Versus settlement was guarded only by the
`week_settlements` claim row, and Pool settlement only by the subject census.
The ACTUAL finality safety lived in `notifications/tuesday_sync.py`, which
refuses to settle unless Yahoo reported every matchup `status == "final"` and
every row carries a non-NULL `refreshed_at`.

That was survivable while non-final Matchup rows essentially did not exist: the
season seed wrote rows only for weeks that had been played. Sprint 6 changes
that premise. The provider gateway legitimately writes a matchup row at slate
time, BEFORE kickoff, so the Pool MATCHUP census has something to count (§6).
From this sprint on, an unfinished matchup row is a normal object — and a
settlement path reached outside the Tuesday pipeline (a manual call, an admin
route, a script, a test) would have driven money from it.

WHAT THIS ADDS, AND WHAT IT DELIBERATELY DOES NOT. It adds ONE precondition,
shared by both money paths, reading `Matchup.finalized_at` AND NOTHING ELSE. It
does not change settlement economics, ordering, payout arithmetic, or the
claim/lock discipline. It runs BEFORE any money moves, so a refusal leaves the
system exactly as it was and is safely retryable once results are final.

`refreshed_at` IS NOT CONSULTED HERE. The Tuesday pipeline's own
`_assert_slate_fresh` still reads it, and that check keeps its own meaning —
"the refresh completed". This gate answers the different and stricter question
"is the result economically final", which §7 makes `finalized_at`'s sole
business. Two gates, two facts; neither substitutes for the other.

THE VOCABULARY IS THE EXISTING ONE. `RESULTS_NOT_READY` is already the accepted
name for this refusal — `economy/skunk.py` raises it and
`economy/season_close_orchestrator.py` names its precondition step after it.
Introducing a second name for the same condition would leave operators matching
on two strings.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The accepted refusal name, reused verbatim from economy/skunk.py.
REASON_RESULTS_NOT_READY = "RESULTS_NOT_READY"


class ResultsNotReadyError(ValueError):
    """A money path was asked to settle a week that is not economically final.

    Carries the offending matchup ids so an operator is told WHICH game is
    unfinished rather than being handed a generic refusal.
    """

    def __init__(self, message: str, *, league_id: int, week: int,
                 unfinalized_matchup_ids: tuple[int, ...]) -> None:
        super().__init__(f"[{REASON_RESULTS_NOT_READY}] {message}")
        self.reason = REASON_RESULTS_NOT_READY
        self.league_id = league_id
        self.week = week
        self.unfinalized_matchup_ids = unfinalized_matchup_ids


@dataclass(frozen=True)
class WeekFinality:
    """The finality census of one league-week. Returned for observability."""

    league_id: int
    week: int
    matchups_total: int
    matchups_finalized: int
    unfinalized_matchup_ids: tuple[int, ...]

    @property
    def is_final(self) -> bool:
        """Every matchup in the week is economically final.

        A week with NO matchup rows is `is_final` True and `matchups_total` 0.
        That is correct and is not a hole: `require_week_final` handles the
        empty case separately, because "no games" and "all games finished" are
        different situations and only the caller knows which one is legitimate
        for it.
        """
        return not self.unfinalized_matchup_ids


def week_finality(db, *, league_id: int, week: int) -> WeekFinality:
    """Census the week's finality. Pure read — writes nothing, locks nothing."""
    from db.schema import Matchup

    rows = (db.query(Matchup.id, Matchup.finalized_at)
            .filter(Matchup.league_id == league_id, Matchup.week == week)
            .order_by(Matchup.id)
            .all())
    unfinalized = tuple(row.id for row in rows if row.finalized_at is None)
    return WeekFinality(
        league_id=league_id, week=week, matchups_total=len(rows),
        matchups_finalized=len(rows) - len(unfinalized),
        unfinalized_matchup_ids=unfinalized,
    )


def require_week_final(db, *, league_id: int, week: int,
                       context: str,
                       allow_empty: bool = True) -> WeekFinality:
    """Refuse unless every matchup in the week is economically final.

    THE ONE PREDICATE: `Matchup.finalized_at IS NOT NULL`, for every row in the
    week. Not the score, not a non-null score, not a 0-0, not `refreshed_at`,
    not elapsed time, not row presence, not payload presence, not the local
    clock — §7 forbids every one of those, and none of them is readable from
    here because this function queries exactly two columns.

    `allow_empty` defaults True so a week with no matchups is not refused BY
    THIS GATE. An empty week is a real state — a league whose schedule has not
    been ingested, or a bye-only week — and the accepted engines already have
    their own opinions about it: `betting.pool_census` classifies an empty
    subject field as NO_SUBJECTS and fails closed there, and
    `notifications.tuesday_sync._assert_slate_fresh` refuses a zero-row slate
    outright. Duplicating that judgement here would put a third, differently
    worded opinion about emptiness into the tree.
    """
    census = week_finality(db, league_id=league_id, week=week)

    if census.matchups_total == 0:
        if allow_empty:
            return census
        raise ResultsNotReadyError(
            f"{context}: league {league_id} week {week} has no matchup rows at "
            f"all; there is no result to settle.",
            league_id=league_id, week=week, unfinalized_matchup_ids=())

    if not census.is_final:
        raise ResultsNotReadyError(
            f"{context}: league {league_id} week {week} has "
            f"{len(census.unfinalized_matchup_ids)} of {census.matchups_total} "
            f"matchup(s) with finalized_at IS NULL (matchup ids "
            f"{list(census.unfinalized_matchup_ids)!r}). Economic finality is "
            f"finalized_at and nothing else (§7); a score, a 0-0, a refreshed_at "
            f"or the passage of time is not a final result. Nothing has been "
            f"settled and no wallet moved — retry once the provider declares "
            f"the week final.",
            league_id=league_id, week=week,
            unfinalized_matchup_ids=census.unfinalized_matchup_ids)

    return census


def require_matchup_final(db, *, matchup_id: int, context: str):
    """Refuse unless ONE matchup is economically final.

    For paths that settle a single game rather than a week. Same predicate, same
    refusal, so a per-matchup caller cannot end up with weaker safety than a
    per-week one by virtue of having chosen a different granularity.
    """
    from db.schema import Matchup

    row = (db.query(Matchup.id, Matchup.league_id, Matchup.week,
                    Matchup.finalized_at)
           .filter(Matchup.id == matchup_id).first())
    if row is None:
        raise ResultsNotReadyError(
            f"{context}: matchup {matchup_id} does not exist.",
            league_id=-1, week=-1, unfinalized_matchup_ids=())
    if row.finalized_at is None:
        raise ResultsNotReadyError(
            f"{context}: matchup {matchup_id} (league {row.league_id} week "
            f"{row.week}) has finalized_at IS NULL and is not an economically "
            f"final result.",
            league_id=row.league_id, week=row.week,
            unfinalized_matchup_ids=(matchup_id,))
    return row
