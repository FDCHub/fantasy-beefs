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
                    provider="yahoo",
                    provider_league_key="461.l.certification",
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
                db.add(_Pr(player_id=_pl.id, week=5, season=2026,
                           projected_points=12.0 + _i, source="fixture"))
        if not db.query(_W).filter(_W.team_id == _t.id).first():
            db.add(_W(team_id=_t.id, balance=0.0))
    db.flush()
    if not db.query(_M).filter(_M.league_id == league.id, _M.week == 5).first():
        db.add(_M(league_id=league.id, week=5, home_team_id=gm_team.id,
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
            event_id=_uuid.uuid4(), league_id=league.id, week=5,
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
"""

#: Opt-in seed steps. Kept OUT of the default fixture on purpose: every existing
#: suite runs against the plain league, and silently giving it a drawn Pool slate
#: would change what those suites are certifying.
_SEED_POOL_SLATE = """
    # A DRAWN slate for week 5, from the REAL Rev1.3 catalog. This is the
    # persisted output `betting/pool_slate.build_and_persist_slate` would write.
    # The builder itself cannot run here — it needs four definitions passing
    # BOTH gates, and gate 2 is the per-league provider measurement this
    # environment does not satisfy — so the RESULT is seeded and the UI is then
    # tested for reading it rather than composing one. No gate is weakened and
    # no provider measurement is fabricated.
    from betting.pool_catalog import seed_definitions
    from db.schema import PoolDefinition, PoolInstance
    seed_definitions(db)
    db.flush()

    slate_keys = [d.key for d in db.query(PoolDefinition)
                  .order_by(PoolDefinition.catalog_number).limit(4).all()]

    prior = PoolInstance(league_id=league.id, season=league.season, week=4,
                         phase="REGULAR", rotation_cycle=1,
                         definition_key=slate_keys[0], slot=1,
                         pot_cents=1000, rollover_cents=0, settled=True)
    db.add(prior); db.flush()

    for slot, key in enumerate(slate_keys, start=1):
        db.add(PoolInstance(
            league_id=league.id, season=league.season, week=5, phase="REGULAR",
            rotation_cycle=1, definition_key=key, slot=slot,
            pot_cents=100 * slot, rollover_cents=1000 if slot == 1 else 0,
            origin_instance_id=prior.id if slot == 1 else None,
            settled=False))
    db.flush()
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
                 provider_week: int | None = 5) -> None:
        self._tmp_dir: str | None = None
        self._process: subprocess.Popen | None = None
        self.origin: str = ""
        # Both default to False so the fixture every existing suite runs
        # against is byte-identical to the one they were certified on.
        self._seed_pool_slate = seed_pool_slate
        self._freeze_pool_entry = freeze_pool_entry
        # S8-P4C-2: which Action situation the GM's team should be in. None
        # leaves the fixture exactly as every earlier suite was certified on —
        # the Rev 4.2 season already carries one open challenge and no more.
        self._action_shape = action_shape
        # S8-P4C-3: the week the fixture league STATES. Defaults to 5 — the week
        # every earlier suite was certified on — so their fixtures are
        # unchanged. `None` seeds a provider-bound league that has never been
        # refreshed, which is the state a real deployment without Yahoo
        # credentials actually has.
        self._provider_week = provider_week

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
        env["JWT_SECRET_KEY"] = "certification-suite-secret"

        self._process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:app",
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
        if self._seed_pool_slate:
            extra += _SEED_POOL_SLATE
        if self._freeze_pool_entry:
            extra += _SEED_FROZEN_POOL_ENTRY
        if self._action_shape:
            extra += _SEED_ACTION.format(shape=self._action_shape)

        script = _SEED_SCRIPT.format(db_url=db_url, root=ROOT, gm=GM_EMAIL,
                                     comm=COMMISSIONER_EMAIL, password=PASSWORD,
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