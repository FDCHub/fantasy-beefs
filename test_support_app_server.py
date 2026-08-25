"""
test_support_app_server.py — disposable application server for browser suites.

INFRASTRUCTURE, NOT A TEST. No assertions live here.

WHY IT EXISTS (S8-P1). Before Sprint 8 the browser suites were served by the
harness's own static file server, which was exactly right: they certified
markup, layout and copy, and markup needs no API. P1 changed what the shell IS.
It now asks `/auth/me` who is acting before it draws anything, so a static
server — which answers 404 to that — gets the sign-in gate and none of the
application. The Sprint 7 assertions did not become wrong; the thing they
measure stopped being reachable the old way.

The honest response is to certify the real product: the same FastAPI process
that serves `/app` also answers `/auth/*`, which is the deployment shape, so
the suites now run against it with a real session. The alternative — teaching
the shell to render without an identity for tests — would have meant
certifying a build no GM will ever load.

WHAT IT GUARANTEES. A disposable SQLite database created fresh per run, seeded
with one league, one GM and one commissioner. It never reads DATABASE_URL from
the environment and never writes to a database it did not create.

NOT A SUBSTITUTE FOR PostgreSQL. Nothing here makes a claim that needs real
Postgres — no locking, no isolation, no concurrency. The PostgreSQL-backed
protocol suites remain a separate gate, still governed by TEST_DATABASE_URL.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))

#: Seeded accounts. The password is a fixture, not a secret.
GM_EMAIL = "gm@example.test"
COMMISSIONER_EMAIL = "commissioner@example.test"
PASSWORD = "sprint8-password"

_SEED_SCRIPT = '''
import os, sys
from datetime import datetime, timezone
os.environ["DATABASE_URL"] = {db_url!r}
sys.path.insert(0, {root!r})

from db.schema import Base, engine, SessionLocal, League, LeagueCommissioner, Team, User
from ledger.ledger import create_ledger_table
from auth.jwt_auth import hash_password

Base.metadata.create_all(engine)
create_ledger_table()

with SessionLocal() as db:
    # S8-P4C-3: THE FIXTURE LEAGUE STATES ITS OWN WEEK. Until now the frontend
    # assumed week 5 from an illustrative constant; the week is authoritative
    # now and comes from `leagues.provider_current_week`, so a fixture that
    # declared nothing would leave every week-scoped read unscoped — the Pool
    # slate included.
    #
    # Week 5 is the same week this fixture's slate, matchups and Rev 4.2
    # figures were always built for. What changed is that the league now SAYS
    # so, rather than the browser guessing it.
    league = League(name="Certification League", season=2026,
                    provider={provider!r},
                    provider_league_key={provider_key!r},
                    provider_current_week={provider_week})
    db.add(league); db.flush()

    gm_team = Team(team_name="Gravy Train", owner="A. Gm",
                   email={gm!r}, league_id=league.id)
    comm_team = Team(team_name="The Braintrust", owner="A. Commissioner",
                     email={comm!r}, league_id=league.id)
    db.add_all([gm_team, comm_team]); db.flush()

    hashed = hash_password({password!r})
    db.add_all([
        User(email={gm!r}, hashed_password=hashed, team_id=gm_team.id, role="gm"),
        User(email={comm!r}, hashed_password=hashed, team_id=comm_team.id,
             role="commissioner"),
    ])
    db.flush()

    comm_user = db.query(User).filter(User.email == {comm!r}).first()
    db.add(LeagueCommissioner(league_id=league.id, user_id=comm_user.id,
                              source="bootstrap"))
    db.flush()

    # S8-P4B-1 — post the authoritative Rev 4.2 accounting season for the GM's
    # team. The browser suites read that team's Ledger, so from here on those
    # figures come from posted ledger state rather than from illustrative
    # JavaScript. The opponent team funds the settled wager's other side.
    from test_support_rev42_fixture import _seed_accounting_fixture
    _seed_accounting_fixture(db, league, gm_team, comm_team)

    {extra_seed}
    db.commit()
'''

#: S8-P4C-2 — put the GM's team into one specific Action situation.
#:
#: SEEDED THROUGH THE GOVERNED PATH, not by writing rows. Each shape below is
#: produced by the same funded lifecycle calls the HTTP routes make, so a
#: browser assertion about a countered wager is an assertion about what the
#: real protocol produces rather than about what this fixture imagined.
#:
#: The Rev 4.2 season already leaves ONE open week-6 challenge from the GM to
#: the opponent. Shapes that need a clean slate decline it first, through the
#: lifecycle, so the money returns the way it really would.
_SEED_ACTION = """
    import uuid as _uuid
    from beefs import proposal_lifecycle as _spec1
    from economy import challenge_funding as _cf
    from db.schema import BeefChallenge as _BC, Matchup as _M, Player as _P
    from db.schema import Projection as _Pr, Roster as _R, Wallet as _W

    _shape = {shape!r}
    _week = {slate_week}

    # THE EMPTY GM IS A THIRD TEAM, seeded with nothing. Declining the Rev 4.2
    # fixture's own opening challenge would leave a terminal record, and a GM
    # whose wagers ENDED is not the same as one who never had any — the empty
    # rails claim is about the latter, so it needs a GM with no history at all.
    if _shape == "empty":
        from db.schema import Team as _T2, User as _U2, Wallet as _W2
        _fresh = _T2(team_name="Fresh Start", owner="A. Newcomer",
                     email="empty@certification.test", league_id=league.id)
        db.add(_fresh); db.flush()
        db.add(_U2(email="empty@certification.test", hashed_password=hashed,
                   team_id=_fresh.id, role="gm"))
        db.add(_W2(team_id=_fresh.id, balance=0.0))
        db.flush()

    # Rosters, projections and a shared matchup: the live route prices a locked
    # wager by Monte Carlo over real starters, and acceptance refuses to create
    # a Bet for a team with no matchup.
    for _t, _nfl in ((gm_team, "KC"), (comm_team, "PHI")):
        if not db.query(_R).filter(_R.team_id == _t.id).first():
            for _i in range(9):
                _pl = _P(name=_t.team_name[:4] + "-P" + str(_i),
                         position="WR", nfl_team=_nfl)
                db.add(_pl); db.flush()
                db.add(_R(team_id=_t.id, player_id=_pl.id))
                db.add(_Pr(player_id=_pl.id, week=_week, season=2026,
                           projected_points=12.0 + _i, source="fixture"))
        if not db.query(_W).filter(_W.team_id == _t.id).first():
            db.add(_W(team_id=_t.id, balance=0.0))
    db.flush()
    if not db.query(_M).filter(_M.league_id == league.id,
                              _M.week == _week).first():
        db.add(_M(league_id=league.id, week=_week, home_team_id=gm_team.id,
                  away_team_id=comm_team.id, home_score=0.0, away_score=0.0))
    db.flush()

    # The opponent needs spendable Credits to fund a Derived stake.
    from economy.current_settle import DOOR_APPROVED_TOPOFF as _DOOR
    from economy.economy_events import wallet_account as _wallet
    from ledger.ledger import post as _post
    _post([(_wallet(comm_team.id), 50_000), ("world", -50_000)],
          door=_DOOR, session=db)
    db.flush()

    # A CLEAN SLATE, through the protocol. The fixture's own open challenge is
    # declined rather than deleted, so the escrow unwinds by real reverse legs.
    for _open in db.query(_BC).filter(
            _BC.response_status.in_(_spec1.OPEN_STATES)).all():
        _cf.decline_funded_challenge(
            event_id=_uuid.uuid4(), challenge_id=_open.id,
            actor_team_id=_open.challenged_team_id, db=db)

    def _terms(cents, dynamic=False):
        return _spec1.ProposalTerms(
            anchor_stake_cents=cents,
            quoted_derived_stake_cents=None if dynamic else cents,
            quoted_funded_pot_cents=None if dynamic else cents * 2,
            anchor_odds=1.909, derived_odds=1.909,
            anchor_moneyline=-110, derived_moneyline=-110,
            anchor_win_probability=0.5, derived_win_probability=0.5,
            pricing_model_id="dynamic" if dynamic else "locked",
        )

    if _shape != "empty":
        _mode = _spec1.MODE_DYNAMIC if _shape == "dynamic" else _spec1.MODE_LOCKED
        # 'recipient' is the one shape where the GM must RECEIVE the offer.
        _from, _to = ((comm_team.id, gm_team.id) if _shape == "recipient"
                      else (gm_team.id, comm_team.id))
        _issued = _cf.issue_funded_challenge(
            event_id=_uuid.uuid4(), league_id=league.id, week=_week,
            challenger_team_id=_from, challenged_team_id=_to,
            wager_type="straight",
            terms=_terms(2_000, dynamic=(_shape == "dynamic")),
            db=db, challenge_mode=_mode)
        _ch = _issued.challenge_id

        if _shape == "countered":
            # The OPPONENT counters, handing the decision back to the GM — the
            # case where direction stops predicting the section.
            _cf.counter_funded_challenge(
                event_id=_uuid.uuid4(), challenge_id=_ch,
                actor_team_id=comm_team.id, terms=_terms(2_600), db=db)
        elif _shape == "accepted":
            _cf.accept_funded_challenge(
                event_id=_uuid.uuid4(), challenge_id=_ch,
                actor_team_id=comm_team.id, db=db)
        elif _shape == "declined":
            _cf.decline_funded_challenge(
                event_id=_uuid.uuid4(), challenge_id=_ch,
                actor_team_id=comm_team.id, db=db)
        elif _shape == "settled":
            # UI-5 GAP 4 -- A WAGER THAT HAS ACTUALLY FINISHED.
            #
            # §29 requires the FantasyStakes Matchups section to carry an FF
            # Breakdown AND a Bet Market Breakdown, and no fixture had ever
            # produced a settled wager for the wrap-up week -- so that section
            # correctly drew its empty-state note and the requirement went
            # UNVERIFIED rather than passing or failing.
            #
            # IT IS SETTLED BY THE REAL ENGINE, not by writing a settled row.
            # `settle_week` reads the finalized matchup and pays the winner
            # through the ledger, so what the surface then reads is a wager
            # that genuinely finished the way the product finishes one. A
            # hand-written row would certify the renderer against a shape
            # nothing produces.
            _cf.accept_funded_challenge(
                event_id=_uuid.uuid4(), challenge_id=_ch,
                actor_team_id=comm_team.id, db=db)
            db.flush()

            # THE MATCHUP MUST BE FINAL FIRST. The engine settles nothing
            # against a matchup the provider has not finalized, which is the
            # rule and not an obstacle -- so the fixture finalizes it exactly
            # as `_SEED_SKUNK_WEEK` does.
            # ── THE SHAPE IS POSTGRESQL-ONLY, AND THIS IS WHY ──────────────
            #
            # `settle_week` re-reads the WeekSettlement row with a plain
            # `SELECT ... FOR UPDATE` before it pays anything. That lock is the
            # engine's concurrency guarantee and is exactly right in
            # production -- and SQLite does not implement it, failing with
            # `near "FOR": syntax error`.
            #
            # Every certification fixture in this repository is SQLite, so the
            # wager settlement engine has never run in one. That -- not a
            # forgotten fixture row -- is why UI-5's FantasyStakes Matchups
            # section had no settled wager to draw and why §29's requirement
            # for that section is UNVERIFIED rather than passing or failing.
            #
            # REFUSED BY NAME RATHER THAN WORKED AROUND. The two workarounds
            # available are both worse than the gap: stripping the lock would
            # weaken a concurrency guard to make a test pass, and writing the
            # settled rows by hand would certify the renderer against a shape
            # nothing in the product produces. On PostgreSQL this shape runs
            # as written.
            if db.get_bind().dialect.name == "sqlite":
                raise RuntimeError(
                    "action_shape='settled' needs PostgreSQL: "
                    "betting.settlement_engine.settle_week takes SELECT ... "
                    "FOR UPDATE, which SQLite does not implement. The shape "
                    "is correct as written and runs on PostgreSQL; it is "
                    "refused here rather than settled by a second, weaker "
                    "path that would certify the surface against state the "
                    "engine never writes.")

            from betting.settlement_engine import settle_week as _settle_week
            from db.schema import Matchup as _M

            _mu = (db.query(_M)
                   .filter(_M.league_id == league.id, _M.week == _week)
                   .first())
            if _mu is None:
                _mu = _M(league_id=league.id, week=_week,
                         home_team_id=gm_team.id, away_team_id=comm_team.id)
                db.add(_mu)
            _mu.home_score = 141.62
            _mu.away_score = 118.04
            _mu.winner_team_id = _mu.home_team_id
            _mu.finalized_at = datetime.now(timezone.utc)
            db.flush()
            db.commit()
            _settle_week(week=_week, db=db, league_id=league.id)
            db.commit()
"""

#: Opt-in seed steps. Kept OUT of the default fixture on purpose: every existing
#: suite runs against the plain league, and silently giving it a drawn Pool slate
#: would change what those suites are certifying.
_SEED_POOL_SLATE = """
    # A DRAWN slate for the league's OWN stated week, from the REAL Rev1.3
    # catalog. S8-P4C-5 made the week a parameter: a fixture that hard-coded 5
    # could not tell "the UI reads the authoritative week" apart from "the UI
    # assumes 5", which is exactly what the adversarial week-9 session exists
    # to distinguish. This is the
    # persisted output `betting/pool_slate.build_and_persist_slate` would write.
    # The builder itself cannot run here — it needs four definitions passing
    # BOTH gates, and gate 2 is the per-league provider measurement this
    # environment does not satisfy — so the RESULT is seeded and the UI is then
    # tested for reading it rather than composing one. No gate is weakened and
    # no provider measurement is fabricated.
    from betting.pool_catalog import seed_definitions
    from db.schema import PoolDefinition, PoolInstance, PoolPot
    seed_definitions(db)
    db.flush()

    # WP6C — THE WEEK'S GOVERNED LOCK MOMENT.
    #
    # `pool_claims.pool_lock_time` reads `PoolPot.lock_time` when an operator
    # has pinned one and otherwise derives the week's earliest kickoff from
    # `NflSchedule`. This fixture has no schedule, so without a pinned lock the
    # read raises ScheduleNotReadyError and every occurrence reports itself
    # closed — which is the CORRECT fail-closed answer, and also means no pick
    # could be certified through the product here.
    #
    # A pinned lock is the state a real operating week has, not a weakened gate:
    # the value is a real future moment and the same server-side comparison
    # `submit_claim` performs still decides every submission. The late/locked
    # negative is certified separately by moving this timestamp into the past.
    from datetime import timedelta as _td
    db.add(PoolPot(league_id=league.id, week={slate_week},
                   lock_time=datetime.now(timezone.utc) + _td(days=3)))
    db.flush()

    # FINAL POR §16 / UI-3B — THE FIXTURE DRAWS THE GOVERNED MIX, 3 TEAM + 1
    # MATCHUP, rather than the first four definitions by catalog number.
    #
    # WHY IT MATTERS THAT A FIXTURE IS RIGHT ABOUT THIS. `betting.pool_rotation
    # .DEFAULT_SCOPE_MIX` is `(('TEAM', 3), ('MATCHUP', 1))` and is certified at
    # the data layer, but the first four catalog definitions happen to be all
    # TEAM — so every browser suite that reads this fixture was looking at a
    # slate composition the product does not draw, and a surface that rendered
    # a MATCHUP occurrence wrongly would have gone unseen at every viewport.
    #
    # ORDERED WITHIN EACH SCOPE BY CATALOG NUMBER, so the draw is deterministic
    # and the first slot is still the lowest-numbered TEAM definition — which is
    # the one the rollover below attaches to, and which several suites name.
    # (Braces are doubled: this block is a `.format()` template.)
    _by_scope = {{}}
    for _d in (db.query(PoolDefinition)
               .order_by(PoolDefinition.catalog_number).all()):
        _by_scope.setdefault(_d.scope, []).append(_d.key)
    slate_keys = (_by_scope.get('TEAM', [])[:3]
                  + _by_scope.get('MATCHUP', [])[:1])
    # FAIL LOUDLY RATHER THAN SEED A SHORT SLATE. A catalog that cannot supply
    # the governed mix would otherwise produce a three-card week that every
    # suite would read as normal.
    assert len(slate_keys) == 4, (
        'pool catalog cannot supply the governed 3 TEAM + 1 MATCHUP mix: '
        + repr(sorted((k, len(v)) for k, v in _by_scope.items())))

    prior = PoolInstance(league_id=league.id, season=league.season,
                         week={prior_week},
                         phase="REGULAR", rotation_cycle=1,
                         definition_key=slate_keys[0], slot=1,
                         pot_cents=1000, rollover_cents=0, settled=True)
    db.add(prior); db.flush()

    for slot, key in enumerate(slate_keys, start=1):
        db.add(PoolInstance(
            league_id=league.id, season=league.season, week={slate_week},
            phase="REGULAR",
            rotation_cycle=1, definition_key=key, slot=slot,
            pot_cents=100 * slot, rollover_cents=1000 if slot == 1 else 0,
            origin_instance_id=prior.id if slot == 1 else None,
            settled=False))
    db.flush()
"""

#: WP6A — a FINALIZED, SKUNK-ASSESSED week 5, for the SKUNK OF THE WEEK callout.
#:
#: The scores are the product ruling's own worked example — 132.47 to 101.83, a
#: margin of 30.64 — so a browser assertion about the differential is an
#: assertion about the number the ruling specified, and any float that got
#: truncated between the matchup row and the rendered card shows up as a
#: mismatch rather than as a plausible-looking figure.
#:
#: THE ENGINE IS CALLED, NOT IMITATED. `assess_weekly_skunk` is the same
#: certified function Week Close invokes, so the seeded state is the state the
#: production path produces — the event, the posting and the receivable — rather
#: than rows hand-written to look like it.
_SEED_SKUNK_WEEK = """
    from db.schema import Matchup as _MSk
    from economy.skunk import assess_weekly_skunk as _assess

    _m = (db.query(_MSk)
          .filter(_MSk.league_id == league.id, _MSk.week == {slate_week})
          .order_by(_MSk.id).first())
    if _m is None:
        _m = _MSk(league_id=league.id, week={slate_week},
                  home_team_id=gm_team.id, away_team_id=comm_team.id,
                  home_score=0.0, away_score=0.0)
        db.add(_m)
    # The GM's own team takes the skunk, so the signed-in GM session sees the
    # callout describing themselves — the case a real league cares about.
    _m.home_team_id = gm_team.id
    _m.away_team_id = comm_team.id
    _m.home_score = 101.83
    _m.away_score = 132.47
    _m.finalized_at = datetime.now(timezone.utc)
    db.flush()

    _assess(db, league_id=league.id, week={slate_week})
    db.flush()
"""


#: FINAL POR — the fixture league as a FINAL POR season with a frozen economy.
#:
#: WHY THIS IS OPT-IN. The certification league is a LEGACY season, and every
#: earlier suite was certified against that fixture. Stamping the whole fixture
#: Final POR would change what Standings, the Ledger and Current Settle report
#: for every one of them at once — the Score gains its Skunk term, the pots
#: change namespace, the expired-minimum asset disappears. That is a fixture
#: migration, not a UI-7 change, and it is not this package's to make.
#:
#: WHAT IT SEEDS, AND WHY EACH PART IS NEEDED. §23's table cannot be derived
#: from a legacy stop: the ratio column is taken against the Weekly Minimum, and
#: a legacy stop carries constants rather than a weekly figure. So the season
#: needs a FROZEN economy configuration (which supplies the minimum, the Skunk
#: fee, the week count and the Fantasy Football pot), a frozen top-off
#: multiplier (which anchors the Season Top-Off Limit), and the ruleset stamp
#: that makes the season Final POR at all.
#:
#: THE FANTASY FOOTBALL POT IS DELIBERATELY 0, not NULL. Zero is the governed
#: "this league plays without one" state, and seeding it means the certification
#: exercises a DECLINED row rather than only CONFIGURED ones — the distinction
#: §23 exists to preserve is then actually on the screen being measured.
_SEED_FINAL_POR_ECONOMY = """
    from db.schema import (
        LeagueSeasonEconomyConfig, LeagueSeasonTopoffConfig, PoolConfig,
    )
    from ruleset import RULESET_FINAL_POR, stamp_ruleset

    _naive = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(LeagueSeasonEconomyConfig(
        league_id=league.id, season=league.season,
        weekly_bet_minimum_cents=1000,
        championship_contribution_cents=8000,
        skunk_fee_cents=1000,
        ff_championship_pot_cents=0,
        regular_season_week_count=14,
        active_team_count=2,
        start_week_used=1, playoff_start_week_used=15,
        frozen_at=_naive))
    db.add(LeagueSeasonTopoffConfig(league_id=league.id, season=league.season,
                                    topoff_cap_multiplier_bps=5000))
    if db.query(PoolConfig).filter(PoolConfig.league_id == league.id).first() is None:
        db.add(PoolConfig(league_id=league.id, pool_weekly_entry_cents=200))
    db.flush()
    db.commit()
    stamp_ruleset(db, league_id=league.id, season=league.season,
                  version=RULESET_FINAL_POR)
    db.commit()
"""


_SEED_FROZEN_POOL_ENTRY = """
    # The governed frozen state: `pool_weekly_entry_frozen_at` is written once,
    # by the season's first Rev1.3 collection, and `configure_pool_weekly_entry`
    # refuses every later change. Seeding the timestamp reproduces that state.
    from db.schema import PoolConfig
    cfg = PoolConfig(league_id=league.id, pool_weekly_entry_cents=200,
                     pool_weekly_entry_frozen_at=datetime.now(timezone.utc))
    db.add(cfg); db.flush()
"""


#: WP3C.1 — a matchup the ODDS ENGINE can actually price.
#:
#: WHY `_SEED_ACTION`'S ROSTERS ARE NOT ENOUGH. That block writes projections
#: with `source="fixture"`, and the pricing model reads the season and source
#: the LEAGUE states — which for this fixture resolves to the global default.
#: The rows are therefore in the table and invisible to the engine, so every
#: quote against that fixture refuses for want of projections. Nothing was
#: wrong with it: the suites that use it seed their terms directly and never
#: ask the model to price anything. WP3C.1 is the first suite that does.
#:
#: SEEDED THROUGH THE ENGINE'S OWN CONTEXT READ, not through a copy of its
#: rule. If the projection context ever stops being (league season, league
#: source), this fixture follows it rather than quietly seeding the wrong
#: season and reporting an unpriceable league as a product failure.
#:
#: ONE SIDE IS STRONGER, deliberately. Two identical boards price at exactly
#: even money, and an even-money quote is the one quote that cannot tell a real
#: price apart from a fabricated 50/50 — the precise substitution WP3C.1 exists
#: to make impossible.
_SEED_PRICEABLE_VERSUS = """
    from db.schema import Player as _QP, Projection as _QPr, Roster as _QR
    from db.schema import Team as _QT, User as _QU, Wallet as _QW
    from beefs.beef_engine import projection_context_for_team as _qctx

    _qweek = {slate_week}
    _qctxv = _qctx(db, gm_team.id)

    # ── UIRECON WAVE 4A · PROJECT THE ROWS THE ENGINE ACTUALLY READS ─────────
    #
    # `_fetch_starters_for_odds` takes the first `N_START` roster rows BY ID, so
    # when `_SEED_ACTION` has already seeded a roster its players are the ones
    # priced — and its projections are deliberately written under the wrong
    # (season, source), which is what the note above this block describes. The
    # nine players added below therefore sat behind them: the pairing priced,
    # and every projection the Matchup Preview read was 0.0.
    #
    # That was invisible while nothing read the lineup. The Wave 4A preview read
    # model reads exactly what the simulator is handed, so the fixture has to
    # give those rows a projection in the LEAGUE'S OWN context or the suite
    # certifies a lineup of zeroes.
    #
    # ADDITIVE, AND ONLY WHERE ONE IS MISSING. Existing rows are left alone, so
    # the refusal-path team below still has no lineup and `_SEED_ACTION`'s own
    # wrong-context rows are still there to be resolved past.
    for _qt, _qbase in ((gm_team, 12.4), (comm_team, 11.9)):
        for _qidx, _qrow in enumerate(
                db.query(_QR).filter(_QR.team_id == _qt.id)
                  .order_by(_QR.id).limit(9).all()):
            _qhave = (db.query(_QPr)
                      .filter(_QPr.player_id == _qrow.player_id,
                              _QPr.week == _qweek,
                              _QPr.season == _qctxv.season,
                              _QPr.source == _qctxv.source).first())
            if _qhave is None:
                db.add(_QPr(player_id=_qrow.player_id, week=_qweek,
                            season=_qctxv.season,
                            projected_points=round(_qbase + _qidx * 0.7, 1),
                            source=_qctxv.source))
    db.flush()

    for _qt, _qnfl, _qbase in ((gm_team, "KC", 12.4), (comm_team, "PHI", 11.9)):
        for _qi in range(9):
            _qpl = _QP(name=_qt.team_name[:4] + "-Q" + str(_qi),
                       position="WR", nfl_team=_qnfl)
            db.add(_qpl); db.flush()
            db.add(_QR(team_id=_qt.id, player_id=_qpl.id))
            db.add(_QPr(player_id=_qpl.id, week=_qweek, season=_qctxv.season,
                        projected_points=_qbase, source=_qctxv.source))
        if not db.query(_QW).filter(_QW.team_id == _qt.id).first():
            db.add(_QW(team_id=_qt.id, balance=0.0))
    db.flush()

    # A LEAGUE MEMBER WITH NO STARTING LINEUP. The refusal path is a product
    # surface too, and a suite that could only reach it by breaking the server
    # would be certifying its own stub rather than the page.
    _qbare = _QT(team_name="No Lineup", owner="A. Latecomer",
                 email="nolineup@certification.test", league_id=league.id)
    db.add(_qbare); db.flush()
    db.add(_QU(email="nolineup@certification.test", hashed_password=hashed,
               team_id=_qbare.id, role="gm"))
    db.add(_QW(team_id=_qbare.id, balance=0.0))
    db.flush()
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AppServer:
    """A running application on a disposable database.

    Use as a context manager — the server is terminated and the database
    directory removed on exit, whether the body succeeded or raised.
    """

    def __init__(self, *, seed_pool_slate: bool = False,
                 freeze_pool_entry: bool = False,
                 action_shape: str | None = None,
                 seed_skunk_week: bool = False,
                 seed_priceable_versus: bool = False,
                 provider_binding: str = "yahoo",
                 server_env: dict | None = None,
                 seed_final_por: bool = False,
                 provider_week: int | None = 5) -> None:
        self._tmp_dir: str | None = None
        self._process: subprocess.Popen | None = None
        self.origin: str = ""
        self.database_url: str = ""
        # Both default to False so the fixture every existing suite runs
        # against is byte-identical to the one they were certified on.
        self._seed_pool_slate = seed_pool_slate
        self._freeze_pool_entry = freeze_pool_entry
        # WP6A: off by default, so every existing suite runs against the
        # byte-identical fixture it was certified on.
        self._seed_skunk_week = seed_skunk_week
        # S8-P4C-2: which Action situation the GM's team should be in. None
        # leaves the fixture exactly as every earlier suite was certified on —
        # the Rev 4.2 season already carries one open challenge and no more.
        self._action_shape = action_shape
        # WP3C.1: off by default, so every existing suite runs against the
        # byte-identical fixture it was certified on. On, the league's own
        # projection context carries a real board and the Versus quote route
        # can price a matchup instead of refusing one.
        self._seed_priceable_versus = seed_priceable_versus
        # WP3D: which provider answers for the fixture league.
        #
        #   "yahoo"  the default every earlier suite was certified on;
        #   "demo"   the governed synthetic provider — `provider="demo"` with a
        #            `demo.l.` league key, which is what `is_demo_league` reads.
        #            The binding is the ONLY thing that makes a league Demo; a
        #            name would not, and must not;
        #   "none"   no provider binding at all, which is the NOT CONNECTED
        #            state a league has before anyone connects one.
        #
        # Parameterised rather than given a `demo=True` boolean because there
        # are three states and a boolean can only carry two.
        self._provider_binding = provider_binding
        # WP3D.1: extra environment for the SERVER PROCESS only — never for the
        # seed, which must build the same fixture whatever the runtime is
        # configured to accept as a login. `FS_ENV=production` is the case this
        # exists for: the browser tier has to meet a real production process,
        # and a production process is a property of the runtime rather than of
        # the data.
        self._server_env = dict(server_env or {})
        # S8-P4C-3: the week the fixture league STATES. Defaults to 5 — the week
        # every earlier suite was certified on — so their fixtures are
        # unchanged. `None` seeds a provider-bound league that has never been
        # refreshed, which is the state a real deployment without Yahoo
        # credentials actually has.
        self._provider_week = provider_week
        # UI-7 / FINAL POR: off by default, so every existing suite runs
        # against the byte-identical LEGACY fixture it was certified on. On,
        # the league becomes a Final POR season with a frozen economy — which
        # is the only state §23's VC allocation table can be derived from.
        self._seed_final_por = seed_final_por

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def __enter__(self) -> "AppServer":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stop()

    def start(self) -> "AppServer":
        self._tmp_dir = tempfile.mkdtemp(prefix="fs-appserver-")
        db_path = os.path.join(self._tmp_dir, "certification.db")
        db_url = f"sqlite:///{db_path.replace(os.sep, '/')}"
        # PUBLISHED SO A SUITE CAN PLANT STATE THE SEED DOES NOT COVER.
        #
        # YAHOO-LIVE-1 needs a deployment that genuinely HOLDS a Yahoo grant
        # before it can assert that no surface leaks one — asserting "no token
        # in the response" against a server with no token asserts nothing. The
        # attribute is read-only by convention and every existing suite ignores
        # it; the seeding path below is unchanged.
        self.database_url = db_url

        self._seed(db_url)

        port = _free_port()
        self.origin = f"http://127.0.0.1:{port}"

        env = dict(os.environ)
        env["DATABASE_URL"] = db_url
        # The harness serves plain http, and a conforming browser will not
        # return a Secure cookie over it. The S8-P1 suite asserts separately
        # that Secure is the DEFAULT, so this opt-out cannot hide a regression
        # in the attribute it disables.
        env["FS_COOKIE_INSECURE"] = "1"
        env.pop("FS_ALLOWED_ORIGINS", None)

        # PROD-HARDEN-1 — A PRODUCTION-MODE SERVER NEEDS A TOKEN ENCRYPTION KEY.
        #
        # Several suites start this harness with `FS_ENV=production` to certify
        # production-only behaviour — the sign-in gate, the retired password
        # routes. The startup guard added by PROD-HARDEN-1 refuses to start a
        # production process without a key, correctly: such a process accepts
        # Yahoo sign-ins and silently drops the grant each one produces.
        #
        # So the harness supplies what a real production deployment supplies.
        # Generated per server, never written anywhere, and secures nothing but
        # this process's own throwaway database. A suite that wants to certify
        # the ABSENCE of a key sets it explicitly through `server_env`, which is
        # applied after this and therefore wins.
        if "FS_TOKEN_ENCRYPTION_KEY" not in env:
            from auth.token_crypto import generate_key

            env["FS_TOKEN_ENCRYPTION_KEY"] = generate_key()
        env["JWT_SECRET_KEY"] = "certification-suite-secret"
        env.update(self._server_env)

        self._process = subprocess.Popen(
            # B1 — THE CERTIFIED PRODUCTION ENTRYPOINT, AS `Procfile` AND
            # `railway.toml` both name it. Booting `api.main` here registered no
            # RC2 model, so every fresh certification database was built without
            # the six championship tables while the bootstrap still stamped
            # 0003-0006 as applied — the precise corrupt state B1's schema
            # verification now refuses. A harness must not manufacture a
            # database shape production can never have.
            [sys.executable, "-m", "uvicorn", "api.main_rc2:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

        if not self._wait_for_health():
            output = ""
            if self._process.poll() is not None and self._process.stdout:
                output = self._process.stdout.read()[-3000:]
            self.stop()
            raise RuntimeError(f"application did not become healthy\n{output}")
        return self

    def stop(self) -> None:
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
        if self._tmp_dir:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None

    # ── Internals ────────────────────────────────────────────────────────────

    def _seed(self, db_url: str) -> None:
        """Seed in a SUBPROCESS.

        db.schema binds its engine from DATABASE_URL at import time. Seeding
        in-process would leave the caller holding a second engine against the
        same SQLite file as the server, which is the kind of thing that works
        until it intermittently does not.
        """
        extra = ""
        # The seeded week follows what the league STATES. A league with no
        # stated week still needs a concrete week to seed rows for, so week 5
        # stands in there — it is fixture scaffolding, not a claim, and the
        # league reports no current week either way.
        slate_week = self._provider_week or 5
        if self._seed_pool_slate:
            extra += _SEED_POOL_SLATE.format(slate_week=slate_week,
                                             prior_week=slate_week - 1)
        if self._freeze_pool_entry:
            extra += _SEED_FROZEN_POOL_ENTRY
        if self._action_shape:
            extra += _SEED_ACTION.format(shape=self._action_shape,
                                         slate_week=slate_week)
        if self._seed_priceable_versus:
            extra += _SEED_PRICEABLE_VERSUS.format(slate_week=slate_week)
        # LAST, so it finalizes whichever matchup the blocks above created.
        if self._seed_skunk_week:
            extra += _SEED_SKUNK_WEEK.format(slate_week=slate_week)
        # AFTER the Pool config blocks, so it does not overwrite a frozen entry
        # one of them seeded, and after the Skunk week for the same reason the
        # Skunk block goes last: it reads whatever the blocks above built.
        if self._seed_final_por:
            extra += _SEED_FINAL_POR_ECONOMY

        binding = {
            "yahoo": ("yahoo", "461.l.certification"),
            "demo": ("demo", "demo.l.certification"),
            "none": (None, None),
        }[self._provider_binding]

        script = _SEED_SCRIPT.format(db_url=db_url, root=ROOT, gm=GM_EMAIL,
                                     comm=COMMISSIONER_EMAIL, password=PASSWORD,
                                     provider=binding[0],
                                     provider_key=binding[1],
                                     provider_week=self._provider_week,
                                     extra_seed=extra)
        result = subprocess.run([sys.executable, "-c", script],
                                capture_output=True, text=True, cwd=ROOT)
        if result.returncode != 0:
            raise RuntimeError(
                f"could not seed the disposable database\n{result.stdout}\n{result.stderr}")

    def _wait_for_health(self, timeout: float = 45.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._process is not None and self._process.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(f"{self.origin}/health", timeout=2) as response:
                    if response.status == 200:
                        return True
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(0.35)
        return False

    # ── For the node suites ──────────────────────────────────────────────────

    def browser_args(self, *, authenticate_as: str | None = GM_EMAIL) -> list[str]:
        """Arguments the browser harness reads for itself.

        `authenticate_as=None` leaves the browser signed out, for a suite whose
        subject is the signed-out state.
        """
        args = [f"--origin={self.origin}"]
        if authenticate_as:
            args += [f"--auth-email={authenticate_as}", f"--auth-password={PASSWORD}"]
        return args