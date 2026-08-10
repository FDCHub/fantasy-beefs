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
os.environ["DATABASE_URL"] = {db_url!r}
sys.path.insert(0, {root!r})

from db.schema import Base, engine, SessionLocal, League, LeagueCommissioner, Team, User
from ledger.ledger import create_ledger_table
from auth.jwt_auth import hash_password

Base.metadata.create_all(engine)
create_ledger_table()

with SessionLocal() as db:
    league = League(name="Certification League", season=2026)
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
    db.commit()
'''


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AppServer:
    """A running application on a disposable database.

    Use as a context manager — the server is terminated and the database
    directory removed on exit, whether the body succeeded or raised.
    """

    def __init__(self) -> None:
        self._tmp_dir: str | None = None
        self._process: subprocess.Popen | None = None
        self.origin: str = ""

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
        script = _SEED_SCRIPT.format(db_url=db_url, root=ROOT, gm=GM_EMAIL,
                                     comm=COMMISSIONER_EMAIL, password=PASSWORD)
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