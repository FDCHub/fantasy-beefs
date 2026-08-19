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

    return {
        "prepared": prepared,
        "funded": funded,
        "weeks_closed": len(weeks),
        "weeks": weeks,
        "live_week": {"week": current_week,
                      "pool_entries": live_pools["teams_charged"],
                      "claims": live_claims,
                      "versus_issued": len(live_versus["issued"])},
    }
