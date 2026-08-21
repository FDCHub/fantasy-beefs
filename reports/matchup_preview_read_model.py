"""
reports/matchup_preview_read_model.py — what the Matchup Preview explains from.

READ-ONLY. Nothing here posts, locks, commits, prices or transitions anything.
It answers one question — "what is this pairing made of, and what did the
simulation say about it" — from the same inputs and the same board the wager
routes already use.

── WHY THIS EXISTS (UIRECON Wave 4A) ────────────────────────────────────────

The Matchup Preview was fed nulls by construction. `shell.js openPreview()`
handed it `spread: null`, `yourLineup: []` and `opponentLineup: []`, so every
narrative branch in `narrative.js` took its "not priced yet / lineups bind from
the provider once its read is wired" path and the surface explained nothing —
on a demo whose whole purpose is to show that the odds are calculated from real
lineups.

THE DATA WAS NEVER MISSING. `demo/rosters.py` seeds nine starters per team with
a projection row per player per week, and `beefs.beef_engine`'s pricing path
reads exactly those rows. What was missing was a read model between them. This
is that read model, and it is the reason the preview can now say something true.

── WHAT IT DOES NOT DO, AND THE LIST IS THE POINT ───────────────────────────

It does not simulate. It does not price. It does not round a line, choose a
sign, convert a probability to American odds, or decide whether a matchup is
eligible. Every number it returns arrived from one of two existing callables:

    _fetch_starters_for_odds   the roster+projection bundle the simulator is
                               handed — read verbatim, per player
    compute_market_board       the board the `/versus/board` route serves, which
                               simulates ONCE and returns moneyline, both win
                               probabilities, the canonical spread threshold,
                               both sportsbook-signed displays and the total

Search this module for an arithmetic operator and you will find exactly one
kind: `sum()` over the projected points of a lineup, and the subtraction of one
such sum from the other. That is addition of served inputs, not a second
pricing model — the projected lineup total is a fact about the projections, and
it is labelled as such everywhere it surfaces. The simulation's own outputs —
win probability, the median margin that becomes the spread, the median total —
are reported exactly as the board produced them and are never recomputed here.

── WHAT REV 1.4 LANE C ADDED, AND WHY IT IS STILL NOT ARITHMETIC ───────────

A third served callable joins the two above:

    providers.live_scoring    the provider's OWN reported fantasy points for
                              this league-week, read verbatim per player from
                              `ProviderPlayerStats.fantasy_points`

A GM comparing a line on Sunday afternoon was reading a Thursday forecast with
no way to see how much of it had already happened. Every starter now carries
what it HAS scored beside what it was projected to score, and so does each team.

THE LIVE FIGURES ARE PASSED IN, NOT FETCHED, for the same reason the board is:
`api.main._provider_week_snapshot` is the one place in the product that branches
on a provider name, and a second such branch here would be a second composition
boundary to keep in step.

NONE IS NOT ZERO, ANYWHERE BELOW. A starter whose game has not kicked off has
`live_points=None` and `live_measured=False`; a starter who played and scored
nothing has 0.0 and True. Substituting one for the other would tell a GM that
half a lineup had busted when in fact it had not yet played, which is the single
most expensive thing this surface could get wrong.

── ORIENTATION ─────────────────────────────────────────────────────────────

Everything is oriented on the ACTING GM, because that is the orientation the
board, the quote route and the write route all use. `acting_spread` arrives
already signed from `market_lines.sportsbook_spread`; nothing here flips it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session


@dataclass
class LineupRow:
    """One starter, exactly as the pricing path reads them.

    `slot` is the roster slot's ordinal position in the starting lineup, which
    is what `_fetch_starters_for_odds` orders by — the engine takes the first
    `N_START` roster rows by id, so position in that list IS the lineup.
    """

    slot: int
    player_id: int
    player_name: str
    position: str
    projected_points: float
    #: The provider's injury designation when one is recorded. Carried because
    #: the projection row already holds it and a lineup that hides it would be
    #: showing a projection without the caveat attached to it.
    injury_status: Optional[str] = None
    #: What this starter HAS scored, per the provider's own weekly statement.
    #: None where the feed has said nothing about the player yet — which before
    #: kickoff is every starter on both rosters. NEVER 0.0 standing in for it.
    live_points: Optional[float] = None
    #: Affirmative: the feed stated a figure for this player. Kept as its own
    #: field rather than inferred from `live_points is not None` so a genuine
    #: measured zero survives every hop to the surface intact.
    live_measured: bool = False


@dataclass
class SideView:
    """One team's identity and its projected starting lineup."""

    team_id: int
    team_name: str
    lineup: list[LineupRow] = field(default_factory=list)
    #: The SUM of the projections above. Addition of served inputs — not a
    #: simulation output, and never presented as one.
    projected_total: float = 0.0
    #: The SUM of the LIVE figures above, over the starters the feed has
    #: actually measured. Addition of served inputs, exactly as the projected
    #: total is — no scoring rule is applied and no absent starter contributes.
    #:
    #: None WHEN NOTHING HAS BEEN MEASURED. A 0.0 here would read as "this team
    #: has scored nothing", which before kickoff is a claim about a game that
    #: has not been played. The two counts below let the surface say how much of
    #: the lineup the figure covers instead of implying it covers all of it.
    live_total: Optional[float] = None
    #: How many starters the feed has measured, and how many there are.
    live_measured_count: int = 0
    starter_count: int = 0


@dataclass
class MarketView:
    """The board, reported. Every field is `compute_market_board`'s own.

    `available` is False when the pairing could not be priced, and then the
    figures are all None and `unavailable_reason` carries the server's own
    sentence. A preview that showed a number here would be inventing one.
    """

    available: bool
    reason_code: Optional[str] = None
    unavailable_reason: Optional[str] = None

    acting_moneyline: Optional[int] = None
    opponent_moneyline: Optional[int] = None
    acting_win_probability: Optional[float] = None
    opponent_win_probability: Optional[float] = None
    spread_line: Optional[float] = None
    acting_spread: Optional[float] = None
    opponent_spread: Optional[float] = None
    total_line: Optional[float] = None


@dataclass
class MatchupPreview:
    """Everything the preview surface is entitled to explain from."""

    league_id: int
    week: int
    phase: Optional[str]
    acting: SideView
    opponent: SideView
    market: MarketView
    #: acting projected total minus opponent's. Positive means the acting GM's
    #: lineup projects higher. This is lineup arithmetic and is NOT the spread —
    #: the spread is the simulation's median margin and lives on `market`.
    projected_margin: float = 0.0
    #: Whether the provider answered about current scoring for this week at all.
    #: False means the read failed or was never attempted; True with no figures
    #: means the provider answered and has published none yet. The surface says
    #: a different thing for each, and `live_reason` carries which.
    live_available: bool = False
    #: One of `providers.live_scoring`'s governed reason codes, or None when
    #: figures were served.
    live_reason: Optional[str] = None


def _lineup_rows(starters, live) -> list[LineupRow]:
    """`PlayerProj` bundles from the pricing path, as rows.

    Read verbatim and in order. The engine's own ordering is the lineup order,
    so nothing here sorts, filters or re-ranks: a preview that reordered the
    starters would be showing a lineup the simulator did not use. Rev 1.4's
    comparison matrix pairs the two sides ROW BY ROW off this ordering, so a
    sort introduced here would silently pair a quarterback against a kicker.

    `live` is a `providers.live_scoring.LiveScores`, or None where no live read
    was made. A player it does not name keeps `live_points=None`, which is the
    pre-kickoff state and is never rendered as a score.
    """
    rows: list[LineupRow] = []
    for index, p in enumerate(starters or ()):
        measured = bool(live and live.measured(p.player_id))
        rows.append(LineupRow(
            slot=index + 1,
            player_id=p.player_id,
            player_name=p.name,
            position=p.position,
            projected_points=float(p.projected_points or 0.0),
            injury_status=getattr(p, "injury_status", None),
            # `points_for` returns the provider's own figure or None. A measured
            # 0.0 arrives as 0.0 and stays 0.0; an unmeasured starter arrives as
            # None and stays None.
            live_points=live.points_for(p.player_id) if measured else None,
            live_measured=measured,
        ))
    return rows


def _side(team, starters, live=None) -> SideView:
    rows = _lineup_rows(starters, live)
    measured = [r for r in rows if r.live_measured]
    return SideView(
        team_id=team.id,
        team_name=team.team_name,
        lineup=rows,
        # ROUNDED FOR PRESENTATION ONLY, at one decimal — the precision every
        # projection in this product is already drawn at. The unrounded sum is
        # not an authoritative figure anywhere; the projections themselves are.
        projected_total=round(sum(r.projected_points for r in rows), 1),
        # THE LIVE TOTAL COVERS THE MEASURED STARTERS AND SAYS SO. It is the
        # sum of what the provider has reported so far, which is what a running
        # team score IS mid-week; the two counts beside it are how the surface
        # avoids implying the figure covers a lineup it does not.
        live_total=(round(sum(r.live_points or 0.0 for r in measured), 1)
                    if measured else None),
        live_measured_count=len(measured),
        starter_count=len(rows),
    )


def matchup_preview(db: Session, *, league_id: int, week: int,
                    acting_team, opponent_team,
                    board=None, refusal=None,
                    phase: Optional[str] = None,
                    live=None) -> MatchupPreview:
    """Build the preview view for one pairing.

    THE BOARD IS PASSED IN, NOT FETCHED HERE, and that is deliberate. The route
    already resolves it through `_market_board_or_refuse`, which owns the
    eligibility gate and the governed refusal vocabulary; fetching it a second
    time here would simulate the matchup twice and give the preview a second
    opinion about whether a pairing may be priced. This module reports.

    THE LIVE SCORING IS PASSED IN FOR THE SAME REASON. Reaching a provider is
    `api.main._provider_week_snapshot`'s job — the single place in the product
    that branches on a provider name — and a preview that fetched its own would
    be a second such branch, reachable from a route that must degrade rather
    than fail when a provider is unreadable.

    :param board: a `VersusMarketBoard`, or None when the pairing is unpriceable
    :param refusal: `(reason_code, message)` when it is
    :param live: a `providers.live_scoring.LiveScores`, or None for no live read
    """
    from beefs.beef_engine import _fetch_starters_for_odds
    from providers.live_scoring import REASON_NOT_REQUESTED

    # THE SIMULATOR'S OWN INPUTS. `straight` is the bet type the board itself
    # uses to gather starters, so this reads the same bundle for the same
    # pairing and the same week — the lineup shown IS the lineup priced.
    inputs = _fetch_starters_for_odds(
        "straight", acting_team.id, opponent_team.id, None, week, db)

    acting = _side(acting_team, inputs.ch_starters, live)
    opponent = _side(opponent_team, inputs.cd_starters, live)

    if board is None:
        code, message = refusal or (None, None)
        market = MarketView(available=False, reason_code=code,
                            unavailable_reason=message)
    else:
        market = MarketView(
            available=True,
            acting_moneyline=board.anchor_moneyline,
            opponent_moneyline=board.opponent_moneyline,
            acting_win_probability=board.anchor_win_probability,
            opponent_win_probability=board.opponent_win_probability,
            spread_line=board.spread_line,
            acting_spread=board.anchor_spread_display,
            opponent_spread=board.opponent_spread_display,
            total_line=board.total_line,
        )

    return MatchupPreview(
        league_id=league_id,
        week=week,
        phase=phase,
        acting=acting,
        opponent=opponent,
        market=market,
        projected_margin=round(
            acting.projected_total - opponent.projected_total, 1),
        # THE PROVIDER'S OWN VERDICT ABOUT ITS OWN FEED, forwarded unchanged. A
        # caller that made no live read is reported as unavailable with the
        # reason saying exactly that, rather than as a provider that failed.
        live_available=bool(live and live.available),
        live_reason=(live.reason if live is not None else REASON_NOT_REQUESTED),
    )
