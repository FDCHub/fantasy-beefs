"""
WP1C — postseason Versus admission eligibility.

THE ONE THING THIS MODULE DOES: answer, for one league-week and two teams,
whether both are permitted to enter or materially advance a NEW Versus
commitment. It moves no money, writes nothing, and opens no transaction.

── PARTICIPATION IS THE RESTRICTION HERE, UNLIKE POOLS ──────────────────────

WP1B settled that an eliminated GM remains a full Pool PARTICIPANT — they may
still enter, still be charged, still win — while their eliminated fantasy team
may not be a Pool SUBJECT. Versus is the opposite shape, by owner ruling: the
restriction applies to participation itself. A team eliminated from the
championship track may not originate, receive, accept, counter or revive a new
postseason wager at all.

So the Pool model is deliberately NOT copied. The two packages consume the same
eligibility fact and apply it to different questions.

── THE RULE IS NOT RESTATED HERE ────────────────────────────────────────────

`season/championship_track.py::postseason_subject_team_keys()` is the single
authority for who is eligible in a postseason week — the championship-contesting
field, plus the two official third-place participants in championship week. This
module resolves that answer into internal team ids and compares. It contains no
bracket logic, no week arithmetic and no third-place reasoning of its own,
because a second implementation of the rule would drift from the first the moment
either was amended.

── WHAT IS NEVER CONSULTED ──────────────────────────────────────────────────

Not `_find_matchup`. Not whether a Matchup row exists. Not points scored. Not
whether the provider is still scheduling games for the team. A consolation team
has all four of those and is ineligible; that gap is precisely the defect this
module closes.

── THE RESOLVER IS INJECTED, NOT IMPORTED ───────────────────────────────────

`beefs/` imports nothing from `providers/`, and WP1C does not start.
`providers.yahoo.identity.build_team_identity_resolver` is the certified
provider-key-to-internal-id mapping (S6-R1: the compound provider key is the
identity, never a name or an email), and the CALLER supplies it — the same
injection shape `betting/pool_postseason.py` uses. A Demo provider satisfies this
module by supplying its own resolver, with no change here.

── TEMPORAL CONTRACT ────────────────────────────────────────────────────────

This is an ADMISSION-TIME question and nothing else. It is asked once, at the
action that creates or advances a commitment, and never again. Final Lock and
settlement do not call it: a validly admitted wager stays valid through later
elimination, bracket advancement, provider refresh and redeploy. Callers place
the check AFTER their idempotency-replay and already-closed guards, so a retried
action returns its committed result without re-evaluating current eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass

REASON_NO_TRACK_STATE = "POSTSEASON_STATE_NOT_SUPPLIED"
REASON_TRACK_UNKNOWN = "POSTSEASON_STATE_UNKNOWN"
REASON_UNRESOLVED_TEAM = "POSTSEASON_TEAM_UNRESOLVED"
REASON_NOT_ELIGIBLE = "TEAM_NOT_POSTSEASON_ELIGIBLE"


class PostseasonVersusError(ValueError):
    """A Versus action was refused on postseason eligibility grounds.

    A ValueError subclass so the existing `except ValueError` around every
    lifecycle call still catches it and maps it to a 400, carrying `reason` for
    the surfaces that render reason codes.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


@dataclass(frozen=True)
class AdmissionDecision:
    """Why an action was admitted or refused. Returned for the admitted case
    too, so an operator asking "which field was this checked against?" gets an
    answer rather than a bare boolean."""

    eligible_team_ids: frozenset[int]
    week: int
    admitted: bool
    refusal_reason: str | None = None


def is_postseason_week(league, week: int) -> bool:
    """Whether this league-week is governed by postseason eligibility at all.

    Reads the SAME governed boundary the Pool phase rule reads, through
    `betting.pool_season_boundary`, so Versus and Pools can never disagree about
    where the postseason starts. Below it this module is not consulted, no
    championship state is required, and no provider work happens — which is what
    keeps the regular-season path exactly as it was.
    """
    from betting.pool_season_boundary import PHASE_POSTSEASON, phase_for_week

    return phase_for_week(league, week) == PHASE_POSTSEASON


def eligible_team_ids(state, resolver) -> frozenset[int]:
    """The postseason-eligible field as internal team ids.

    Refuses rather than partially resolving. An eligible team whose provider key
    maps to no internal team would silently shrink the field, and a silently
    shrunk field admits nobody it should have admitted while looking like a
    legitimate answer.
    """
    if state is None:
        raise PostseasonVersusError(
            REASON_NO_TRACK_STATE,
            "this is a postseason week and no championship track state was "
            "supplied. Versus eligibility is not derivable from league "
            "membership, from a matchup row, or from points scored.")

    allowed = state.postseason_subject_team_keys()
    if allowed is None:
        raise PostseasonVersusError(
            REASON_TRACK_UNKNOWN,
            f"the postseason field is not determinable "
            f"(authority={state.authority.value}, reasons="
            f"{list(state.insufficiency_reasons)}). Refusing the action — there "
            f"is no fallback to the league's teams.")

    resolved: set[int] = set()
    unresolved: list[str] = []
    for team_key in sorted(allowed):
        try:
            internal = resolver.to_internal(team_key)
        except Exception:                       # noqa: BLE001 - re-raised named
            internal = None
        if internal is None:
            unresolved.append(team_key)
            continue
        resolved.add(int(internal))

    if unresolved:
        raise PostseasonVersusError(
            REASON_UNRESOLVED_TEAM,
            f"{len(unresolved)} postseason-eligible team(s) have no internal "
            f"identity ({unresolved!r}). S6-R1 forbids matching them by name, "
            f"and a partial field would admit or refuse the wrong teams.")
    return frozenset(resolved)


def assert_admissible(*, league, week: int, team_ids, state, resolver,
                      action: str) -> AdmissionDecision:
    """Refuse unless EVERY participating team is postseason-eligible.

    `team_ids` is both sides of the wager. Both are required: a wager between an
    eligible team and an eliminated one is not half-legal, and checking only the
    actor would let an eliminated GM be dragged in as a counterparty.

    Returns an `AdmissionDecision` on success and raises `PostseasonVersusError`
    otherwise — so a caller that forgets to inspect the return value still
    cannot proceed past a refusal.

    REGULAR SEASON SHORT-CIRCUITS FIRST, before the state or the resolver is
    touched. Below `playoff_start_week` this is one phase comparison against a
    column the league row already carries: no provider call, no identity build,
    no behaviour change.
    """
    if not is_postseason_week(league, week):
        return AdmissionDecision(eligible_team_ids=frozenset(), week=week,
                                 admitted=True)

    eligible = eligible_team_ids(state, resolver)
    wanted = frozenset(int(t) for t in team_ids)
    ineligible = sorted(wanted - eligible)

    if ineligible:
        raise PostseasonVersusError(
            REASON_NOT_ELIGIBLE,
            f"{action}: team(s) {ineligible} are not eligible for postseason "
            f"Versus in week {week}. Eligible this week: {sorted(eligible)}. A "
            f"team eliminated from the championship track — including one "
            f"playing a consolation or placement game — may not enter a new "
            f"wager, however many matchups it still has and however many points "
            f"it still scores.")

    return AdmissionDecision(eligible_team_ids=eligible, week=week,
                             admitted=True)