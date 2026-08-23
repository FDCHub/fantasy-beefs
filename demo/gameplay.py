"""The showcase's competition, played through the real FantasyStakes lifecycle.

WHAT CHANGED AND WHY. Earlier demo builds posted `wager_settled` and the Pool
doors directly, on the reasoning that the ledger figures would be identical. That
reasoning was wrong and the D2 certification proved it: `versus_record` counts
`Bet` rows carrying a `beef_challenge_id`, and `pool_wins` counts
`pool_winner_distribution` legs crediting `wallet:`. A direct posting produces
neither, so the demo showed twelve GMs at 0-0 with no pool wins — the two columns
that make "head-to-head matchups" and "prop pools" legible.

So competition here goes through the same calls a GM's clicks reach:

    economy.top_off        create_top_off_request -> approve_top_off
    beefs.beef_engine      issue_challenge -> respond_to_challenge
    betting.settlement_engine.settle_week
    economy.weekly_minimum release_week / expire_week
    economy.skunk          assess_weekly_skunk

NOTHING HERE COMPUTES ECONOMICS. This module chooses who plays whom and for how
much; every cent is moved by certified code, and the market prices come from
`beefs.beef_engine.compute_market_board` rather than from any literal in the
fixture.

── WHY THE WEEKS ARE PLAYED FORWARD ─────────────────────────────────────────

`issue_challenge` refuses a week whose kickoff has passed, and the D2.3 lock
resolver makes a showcase week open exactly while it is the league's
`provider_current_week`. So the season is replayed the way a season happens: set
the current week, release the minimum, play it, finalize it, settle it, expire
it, assess the skunk, advance. A week locks behind us because it genuinely is
behind us.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

from demo import showcase

#: What each GM is topped off with, in dollars. The governed cap is
#: `min_reserve x multiplier` = 14000 cents at the certified 10000 bps, so 60
#: dollars sits comfortably inside it and is enough for one Versus stake a week
#: across the season without ever approaching the ceiling.
TOP_OFF_DOLLARS = 60.0

#: One Versus contest per team per week. `beefs.beef_engine.MIN_BET` is $5, so
#: this is the product's own floor rather than a demo preference — a first draft
#: used $2 and was refused, correctly. Each team draws roughly seven contests
#: across the season, so $35 of worst-case exposure against a $60 Top-Off: a GM
#: can lose every single one and still be playing in week 14.
VERSUS_STAKE_DOLLARS = 5.0

#: The three certified markets, rotated deterministically so every week shows a
#: mix and every market appears often enough to be visible in the demo. The
#: fixture owns the tuple because `demo.reset.expected_fingerprint` derives the
#: canonical challenge count from its length — one contest per market per week.
MARKETS: tuple = showcase.VERSUS_PER_WEEK_MARKETS


def _now() -> datetime:
    return datetime(2026, 12, 30, 12, 0, 0, tzinfo=timezone.utc)


# ── governed wallet funding ──────────────────────────────────────────────────

def top_off_all_teams(db, *, league, teams: dict, owner_user_id: int) -> dict:
    """Fund every GM's Wallet through the certified BAB Top-Off path.

    WHY THIS IS NEEDED AT ALL. The Season-Opening Allocation deliberately gives
    the Wallet NO leg — it funds `min_reserve:` and `reserve:`. But
    `beef_engine._verify_wallet_available` checks `wallet:` alone, so a GM whose
    credits are all in weekly play accounts cannot issue a Versus challenge.
    Top-Off is the product's own answer to that, and the demo uses it rather
    than inventing a door.

    THE CAP IS THE LEAGUE'S OWN. `activate_season_allocation` freezes
    `LeagueSeasonTopoffConfig` at the certified multiplier; nothing here edits
    it, and a request above the cap would be refused by `create_top_off_request`
    exactly as it would for a real league.
    """
    from economy.top_off import approve_top_off, create_top_off_request

    funded = 0
    for spec in showcase.TEAMS:
        team = teams[spec.ordinal]
        request = create_top_off_request(league.id, team.id, owner_user_id,
                                         TOP_OFF_DOLLARS, db)
        db.flush()
        approve_top_off(league.id, request.request_id, owner_user_id,
                        "demo league funding", db)
        db.flush()
        funded += 1
    return {"teams_funded": funded, "dollars_each": TOP_OFF_DOLLARS}


# ── the week's Versus card ───────────────────────────────────────────────────

def versus_card(week: int) -> tuple:
    """Which pairings play a FantasyStakes matchup this week, and in which market.

    DERIVED FROM THE YAHOO-STYLE SCHEDULE, so a FantasyStakes contest always
    sits on top of a real fixture between the two GMs — which is what the
    product means by a Versus matchup, and what `_find_shared_matchup` needs in
    order to price and settle it.

    Three of the week's six pairings play, rotated by week so the same GMs are
    not always the ones with action.
    """
    games = showcase.REGULAR_SCHEDULE.get(week) or ()
    if not games:
        return ()
    picked = []
    for offset in range(len(MARKETS)):
        index = (week + offset * 2) % len(games)
        home, away, _, _ = games[index]
        market = MARKETS[(week + offset) % len(MARKETS)]
        picked.append((home, away, market))
    if week == showcase.CURRENT_WEEK:
        picked.extend(showcase.VISITOR_LIVE_EXTRA_MATCHUPS)
    return tuple(picked)


def play_week_versus(db, *, league, teams: dict, week: int) -> dict:
    """Issue and accept this week's FantasyStakes matchups, priced for real.

    THE LINE COMES FROM THE PRODUCTION MARKET BOARD. A spread or an over/under
    needs a threshold, and taking it from `compute_market_board` is the whole
    point: the demo's lines are simulated from the synthetic projections by the
    same engine a live league uses, so nothing here is a display literal.
    """
    from beefs.beef_engine import (
        compute_market_board, issue_challenge, respond_to_challenge,
    )

    issued = []
    for home, away, market in versus_card(week):
        anchor, opponent = teams[home], teams[away]
        board = compute_market_board(anchor, opponent, week, db)

        line = None
        side = None
        if market == "spread":
            line = float(board.spread_line)
        elif market == "over_under":
            line = float(getattr(board, "total_line", None)
                         or getattr(board, "over_under_line"))
            # Alternate the side by week so the demo shows both.
            side = "over" if week % 2 == 0 else "under"

        out = issue_challenge(anchor.id, opponent.id, week=week,
                              bet_type=market, amount=VERSUS_STAKE_DOLLARS,
                              db=db, line=line, side=side)
        db.flush()
        respond_to_challenge(out.challenge_id, accept=True, db=db)
        db.flush()
        issued.append({
            "week": week, "market": market,
            "challenge_id": out.challenge_id,
            "anchor": anchor.team_name, "opponent": opponent.team_name,
            "anchor_moneyline": board.anchor_moneyline,
            "spread_line": float(board.spread_line),
            "line": line, "side": side,
        })
    return {"issued": issued}


#: The namespace the showcase's protocol event ids are minted in.
#:
#: DETERMINISTIC BY CONSTRUCTION. `issue_funded_challenge` takes an `event_id`
#: and treats a repeat of one as a REPLAY rather than a second issue, so the id
#: cannot be random without making the seeder non-repeatable — and D2.4 compares
#: two independent runs field by field. `uuid5` over a stable key gives the same
#: id for the same negotiation on every run, on every machine, forever.
_EVENT_NAMESPACE = _uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def _negotiation_event_id(league_id: int, week: int, spec) -> _uuid.UUID:
    """The protocol event id for one seeded negotiation."""
    return _uuid.uuid5(
        _EVENT_NAMESPACE,
        f"fantasystakes/demo/open-negotiation/{league_id}/{week}/"
        f"{spec.issuer_ordinal}/{spec.recipient_ordinal}/{spec.market}")


def open_live_negotiations(db, *, league, teams: dict, week: int) -> dict:
    """Issue the live week's UNANSWERED challenges — Status's two open rails.

    ── WHY THESE GO THROUGH THE FUNDED LIFECYCLE ────────────────────────────

    `play_week_versus` above issues through `beefs.beef_engine`, which is the
    right path for a contest that is immediately accepted: it prices, it places
    both Bets, and the week settles them. These two are never accepted, and they
    exist so a visitor can answer one — so they have to be answerable, which
    means they have to be the shape the RESPONSE ROUTES understand.
    `/beef/{id}/accept` is `economy.challenge_funding.accept_funded_challenge`,
    and it resolves the challenge's active PROPOSAL. An engine-written row has
    none, so an Accept button on one would be a control that cannot work — the
    thing §6 of the brief forbids more plainly than anything else in it.

    So these are issued the way the product issues one: the same pricing call
    `api.main` makes, the same `proposal_economics`, the same
    `issue_funded_challenge`. A visitor pressing Accept reaches the identical
    command a signed-in GM reaches, because it IS the identical record.

    ── AND WHY THEY COST NOTHING ────────────────────────────────────────────

    An offered challenge places no Bet and settles nothing. Its Anchor escrow is
    funded min-first, so it comes out of the issuer's weekly minimum rather than
    their wallet, and the weekly minimum is swept at week close regardless.
    Nothing here touches a completed week.
    """
    from beefs import proposal_lifecycle as spec1
    from beefs.beef_engine import _compute_odds, compute_market_board
    from beefs.versus_quote import proposal_economics
    from betting.lock_resolver import lock_time_for_league
    from economy.challenge_funding import issue_funded_challenge

    stake_cents = int(round(VERSUS_STAKE_DOLLARS * 100))
    # THE RESPONSE DEADLINE IS THE WEEK'S OWN LOCK, not a fixed timestamp. The
    # showcase's live week resolves to a far-future moment, so the offer reads
    # as open whenever the demo is visited rather than expiring by the calendar.
    deadline = lock_time_for_league(league, week)

    issued = []
    for spec in showcase.VISITOR_OPEN_NEGOTIATIONS:
        issuer = teams[spec.issuer_ordinal]
        recipient = teams[spec.recipient_ordinal]

        # THE LINE IS THE MARKET BOARD'S, exactly as the accepted contests take
        # theirs. A spread needs a threshold and inventing one here would put a
        # display literal in front of a GM about to stake Credits on it.
        line = None
        side = None
        if spec.market == "spread":
            board = compute_market_board(issuer, recipient, week, db)
            line = float(board.spread_line)
        elif spec.market == "over_under":
            board = compute_market_board(issuer, recipient, week, db)
            line = float(getattr(board, "total_line", None)
                         or getattr(board, "over_under_line"))
            side = "over"

        dec_a, ml_a, dec_d, ml_d, prob_a, prob_d = _compute_odds(
            spec.market, issuer, recipient, week, db, line, side, None)
        economics = proposal_economics(
            stake_cents=stake_cents, anchor_odds=dec_a, derived_odds=dec_d,
            dynamic=False)

        result = issue_funded_challenge(
            event_id=_negotiation_event_id(league.id, week, spec),
            league_id=league.id,
            week=week,
            challenger_team_id=issuer.id,
            challenged_team_id=recipient.id,
            wager_type=spec.market,
            terms=spec1.ProposalTerms(
                line=line,
                side=side,
                player_id=None,
                anchor_stake_cents=economics.anchor_stake_cents,
                quoted_derived_stake_cents=economics.quoted_derived_stake_cents,
                quoted_funded_pot_cents=economics.quoted_funded_pot_cents,
                quoted_anchor_payout_cents=economics.quoted_anchor_payout_cents,
                quoted_derived_payout_cents=economics.quoted_derived_payout_cents,
                anchor_win_probability=prob_a,
                derived_win_probability=prob_d,
                anchor_odds=dec_a,
                derived_odds=dec_d,
                anchor_moneyline=ml_a,
                derived_moneyline=ml_d,
                pricing_model_id=spec1.MODE_LOCKED,
            ),
            db=db,
            challenge_mode=spec1.MODE_LOCKED,
            proposal_lock_at=deadline,
        )
        db.flush()
        issued.append({
            "challenge_id": result.challenge_id,
            "week": week,
            "market": spec.market,
            "line": line,
            "issuer": issuer.team_name,
            "recipient": recipient.team_name,
        })
    return {"issued": issued}


def expire_live_negotiations(db, *, league, week: int) -> dict:
    """Close the week's unanswered challenges the way a real week closes them.

    ── WHY THIS EXISTS AT ALL ───────────────────────────────────────────────

    `open_live_negotiations` leaves two challenges offered so the Status tab has
    an ACTION REQUIRED and a WAITING rail. An offered challenge holds a real
    Anchor escrow, and `economy.season_close_orchestrator.verify_preconditions`
    refuses to close a season while any challenge escrow is unresolved — which
    is correct, and is the guard that caught this: a season cannot be finished
    with money still committed to a wager nobody answered.

    A REAL LEAGUE RESOLVES THEM BY LETTING THEM RUN OUT, so the demo does the
    same. `expire_funded_challenge` is the system-owned expiry: no actor,
    because expiring is not something a team does, and the issuer's escrow comes
    back by exact reverse legs. Nothing is abandoned and nothing is deleted.

    THE CLOCK IS THE WEEK'S OWN. These offers were opened with the live week's
    lock as their deadline — a far-future moment, so the demo reads as open
    whenever it is visited — and expiry refuses a deadline that has not been
    reached. Advancing past this week IS that deadline arriving, so the moment
    passed here is the deadline itself rather than a wall clock that would make
    the showcase behave differently in different months.
    """
    import uuid as _u

    from beefs.proposal_lifecycle import OPEN_STATES
    from betting.lock_resolver import lock_time_for_league
    from db.schema import BeefChallenge
    from economy.challenge_funding import expire_funded_challenge

    deadline = lock_time_for_league(league, week)
    rows = (db.query(BeefChallenge)
            .filter(BeefChallenge.league_id == league.id,
                    BeefChallenge.week == week,
                    BeefChallenge.response_status.in_(tuple(OPEN_STATES)))
            .order_by(BeefChallenge.id).all())

    expired = []
    for challenge in rows:
        expire_funded_challenge(
            event_id=_u.uuid5(
                _EVENT_NAMESPACE,
                f"fantasystakes/demo/expire-negotiation/{league.id}/"
                f"{week}/{challenge.id}"),
            challenge_id=challenge.id, db=db, now=deadline)
        expired.append(challenge.id)
    db.flush()
    return {"expired": expired}


# ── the ordered weekly economy ───────────────────────────────────────────────

def release_week_minimums(db, *, league, week: int) -> None:
    """The certified weekly release. Never a hand-written posting."""
    from economy.weekly_minimum import release_week

    release_week(db, league_id=league.id, week=week, now=_now())
    db.flush()


def close_week(db, *, league, teams: dict, week: int) -> dict:
    """Settle, expire and assess — the real end-of-week sequence, in order.

    ORDER IS THE PRODUCT'S, NOT A CONVENIENCE. Settlement has to run before
    expiry, because expiry refuses to sweep a week that still holds an open
    wager; and the skunk assessment has to see a fully finalized week. Getting
    this order wrong is exactly what `season_close_orchestrator.verify_preconditions`
    catches later, so it is done properly here rather than patched there.
    """
    from betting.settlement_engine import settle_week
    from economy.skunk import assess_weekly_skunk
    from economy.weekly_minimum import expire_week

    report = settle_week(week, db, league.id)
    db.flush()
    # POOLS SETTLE BEFORE THE SWEEP, for the same reason Versus does: the
    # entries are sitting in `pool:{league}` having left the GMs' weekly
    # accounts, and expiring the week around an unsettled pot would sweep
    # against money that is still in play.
    pools = settle_week_pools(db, league=league, teams=teams, week=week)
    expire_week(db, league_id=league.id, week=week, now=_now())
    db.flush()
    assessment = assess_weekly_skunk(db, league_id=league.id, week=week,
                                     now=_now())
    db.flush()
    return {
        "week": week,
        "settled": getattr(report, "settled_count", None),
        "pools_settled": pools["settled"],
        "pools_refused": pools["refused"],
        "skunk": getattr(assessment, "total_cents", None),
    }


# ── the prop pool lifecycle ──────────────────────────────────────────────────

def prepare_pools(db, *, league, teams: dict) -> dict:
    """Seed the governed catalog and measure this league's gate-2 readiness.

    ── WHY THE DEMO NEEDS A STAT FEED AT ALL ────────────────────────────────

    The Pool engine settles from a PROVIDER STAT SOURCE. Driving it from the
    repository's local records covers three canonical operands, which supports
    three catalog definitions — and POR §4.1 requires FOUR fully supported
    definitions before a week's slate may be drawn. The showcase's first real
    pool week was refused outright:

        PoolSlateError [INSUFFICIENT_ELIGIBLE_DEFINITIONS] — 3 definitions pass
        BOTH gates, which cannot fill 4 fresh slots even after a cycle reset.

    So the showcase supplies a week the way its own provider would, through
    `demo.stats`, and readiness is measured by the CERTIFIED demo measurement
    rather than asserted here. A definition whose stats the snapshot does not
    carry is blocked with the missing stats named — the demo gets no free pass,
    which is the whole point of measuring instead of declaring.

    MEASURED AT WALL CLOCK, DELIBERATELY. Gate-2 readiness ages, and the slate
    builder reads it against the real clock. A frozen measurement stamp would
    start fresh and silently go stale, so the demo re-measures every time it is
    seeded or reset — which is exactly what a live league does.
    """
    from betting.pool_catalog import seed_definitions
    from betting.pool_funding import configure_pool_weekly_entry
    from betting.pool_gates import selectable_definitions
    from providers.demo.pool_source import measure_league_activation
    from providers.identity import build_team_identity_resolver
    from demo import stats

    catalog = seed_definitions(db)
    db.flush()

    snapshot = stats.snapshot_for_week(league, teams, showcase.START_WEEK)
    resolver = build_team_identity_resolver(db, league_id=league.id,
                                            provider=league.provider)
    measure_league_activation(db, league_id=league.id, snapshot=snapshot,
                              resolver=resolver)
    configure_pool_weekly_entry(db, league_id=league.id,
                                cents=showcase.POOL_ENTRY_CENTS)
    db.flush()

    selectable = selectable_definitions(db, league_id=league.id,
                                        provider=league.provider,
                                        phase="REGULAR")
    return {"catalog": catalog["total"], "selectable": len(selectable),
            "entry_cents": showcase.POOL_ENTRY_CENTS}


def _stat_source(db, *, league, teams: dict, week: int):
    """The demo provider's stat source for one week, bound and resolver-backed."""
    from providers.demo.pool_source import DemoProviderStatSource
    from providers.identity import build_team_identity_resolver
    from demo import stats

    snapshot = stats.snapshot_for_week(league, teams, week)
    resolver = build_team_identity_resolver(db, league_id=league.id,
                                            provider=league.provider)
    return DemoProviderStatSource(snapshot).bind(db, resolver)


def open_week_pools(db, *, league, week: int) -> dict:
    """Collect the week's entries and draw its slate — one certified call.

    `collect_weekly_entries` claims the week, builds the slate, locks every
    wallet in a stable order and posts the collection. The demo does not
    reimplement any of that; it supplies the league and the week.
    """
    from betting.pool_funding import collect_weekly_entries

    result = collect_weekly_entries(db, league_id=league.id, week=week,
                                    provider=league.provider)
    db.flush()
    return {"week": week, "teams_charged": result.teams_charged,
            "per_pool_cents": result.per_pool_share_cents,
            "instances": len(result.instance_ids)}


def claim_week_pools(db, *, league, teams: dict, week: int) -> int:
    """Every GM makes a Prediction on every occurrence of the week.

    THE SUBJECT UNIVERSE IS THE ENGINE'S, NOT THE DEMO'S.
    `league_weekly_structure` is the same census settlement will use, so a GM
    can only claim something that week's field actually contains — which is
    what makes the claims survive settlement instead of being discarded as
    out-of-field.

    Picks are rotated by (GM, slot) so the demo shows a spread of predictions
    rather than twelve identical ones, and so winners differ across occurrences.
    """
    from betting.pool_claims import submit_claim
    from betting.pool_subjects import league_weekly_structure
    from db.schema import PoolDefinition, PoolInstance

    instances = (db.query(PoolInstance)
                 .filter(PoolInstance.league_id == league.id,
                         PoolInstance.week == week)
                 .order_by(PoolInstance.slot).all())

    claims = 0
    for instance in instances:
        definition = (db.query(PoolDefinition)
                      .filter(PoolDefinition.key == instance.definition_key)
                      .first())
        structure = league_weekly_structure(db, league_id=league.id, week=week,
                                            scope=definition.scope)
        subjects = list(structure.considered_subject_ids)
        if not subjects:
            continue
        for n, spec in enumerate(showcase.TEAMS):
            # UIRECON WAVE 3B — ONE SLOT, ONE GM, LIVE WEEK ONLY.
            #
            # The visitor is skipped on the live week's first Pool slot so the
            # demo has a Prop Pool they can actually pick. Every other GM claims
            # it, they claim the other three, and no completed week is affected
            # — `week` here is the loop's week and the guard names it, so a
            # settled week can never take this branch. See the note beside
            # `showcase.VISITOR_OPEN_PICK_SLOT` for why this moves no Credits.
            if showcase.visitor_skips_claim(week, instance.slot, spec.ordinal):
                continue
            submit_claim(db, pool_instance_id=instance.id,
                         team_id=teams[spec.ordinal].id,
                         subject_id=subjects[(n + instance.slot) % len(subjects)],
                         now=_now())
            claims += 1
    db.flush()
    return claims


def settle_week_pools(db, *, league, teams: dict, week: int) -> dict:
    """Settle every occurrence of the week against the demo's own stat feed.

    PAYS THE WINNER'S WALLET, WHICH IS THE POINT. The read model counts a GM's
    Pool WINS as distinct `pool_winner_distribution` postings crediting
    `wallet:{team}` — an earlier demo build posted that door by hand to `min:`
    accounts instead, so every GM showed zero pool wins while the ledger looked
    plausible. Going through settlement is what makes the column true.
    """
    from betting.pool_settlement import settle_week as _settle

    result = _settle(db, league_id=league.id, week=week,
                     stat_source=_stat_source(db, league=league, teams=teams,
                                              week=week))
    db.flush()

    # A REFUSAL IS FATAL TO THE SEED, AND SAYING SO HERE IS THE POINT. Pool
    # settlement isolates a governed refusal to its own occurrence and returns
    # it, which is right for production — one stuck Pool must not hold three
    # settleable ones hostage. But for the seeder an unsettled occurrence means
    # the NEXT week's collection refuses with [PRIOR_WEEK_UNSETTLED], three
    # steps away from the cause. Raising here names the definition that could
    # not be evaluated instead of leaving a later week to report a symptom.
    if result.refused:
        raise RuntimeError(
            f"demo seed: week {week} could not settle "
            f"{len(result.refused)} Pool occurrence(s) — "
            + " | ".join(str(e) for e in result.refused))

    return {"week": week, "settled": len(result.settled), "refused": []}


# ── the season, replayed ─────────────────────────────────────────────────────

def play_season(db, *, league, teams: dict, owner_user_id: int,
                completed_through: int, current_week: int) -> dict:
    """Replay the showcase season through the real product, week by week.

    ── WHY FORWARD, ONE WEEK AT A TIME ──────────────────────────────────────

    Every gameplay API refuses a week that is behind the clock — `issue_challenge`
    on kickoff, `submit_claim` on the pick window — and the D2.3 resolver makes
    a showcase week open exactly while it is the league's own
    `provider_current_week`. So the only way to reach those APIs honestly is to
    live through the season: open week N, fund it, play it, settle it, sweep it,
    then advance. A week is locked behind us because it genuinely is behind us,
    not because a flag says so.

    ── THE ORDER INSIDE A WEEK IS THE PRODUCT'S ─────────────────────────────

    Release the weekly minimum, collect the Pool entries out of it, take the
    Versus stakes from the Wallet, settle both, sweep what went unspent, assess
    the skunk. Each step depends on the one before it having really happened —
    which is why the earlier direct-posting build could get the ledger totals
    right and still produce a demo with no matchup record and no pool wins.

    Returns a per-week trace so a certification run can read what happened
    rather than inferring it from balances.
    """
    prepared = prepare_pools(db, league=league, teams=teams)
    funded = top_off_all_teams(db, league=league, teams=teams,
                               owner_user_id=owner_user_id)

    weeks = []
    for week in range(showcase.START_WEEK, completed_through + 1):
        league.provider_current_week = week
        db.add(league)
        db.flush()

        release_week_minimums(db, league=league, week=week)
        opened = open_week_pools(db, league=league, week=week)
        claims = claim_week_pools(db, league=league, teams=teams, week=week)
        versus = play_week_versus(db, league=league, teams=teams, week=week)
        closed = close_week(db, league=league, teams=teams, week=week)
        weeks.append({**closed, "pool_entries": opened["teams_charged"],
                      "claims": claims, "versus_issued": len(versus["issued"])})

    # ── THE LIVE WEEK, DELIBERATELY LEFT OPEN ────────────────────────────────
    # Funded, drawn, claimed and played, but NOT settled — which is the honest
    # state of a week in progress and the thing that makes the demo's Status
    # and Current Settle screens show something real.
    league.provider_current_week = current_week
    db.add(league)
    db.flush()
    release_week_minimums(db, league=league, week=current_week)
    live_pools = open_week_pools(db, league=league, week=current_week)
    live_claims = claim_week_pools(db, league=league, teams=teams,
                                   week=current_week)
    live_versus = play_week_versus(db, league=league, teams=teams,
                                   week=current_week)
    # UIRECON WAVE 5 — AND TWO THAT NOBODY HAS ANSWERED YET. Issued last, so the
    # accepted contests above keep the ids they have always had and a restore
    # can tell the seeder's negotiations from a visitor's by shape rather than
    # by position.
    live_open = open_live_negotiations(db, league=league, teams=teams,
                                       week=current_week)

    return {
        "prepared": prepared,
        "funded": funded,
        "weeks_closed": len(weeks),
        "weeks": weeks,
        "live_week": {"week": current_week,
                      "pool_entries": live_pools["teams_charged"],
                      "claims": live_claims,
                      "versus_issued": len(live_versus["issued"]),
                      "negotiations_open": len(live_open["issued"])},
    }
