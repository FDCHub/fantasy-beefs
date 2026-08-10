#!/usr/bin/env python3
"""
test_s8_p1_browser.py — Sprint 8 Package 1 · real-browser session verification.

DRIVER, NOT THE SUITE. This module starts a real uvicorn process against a
disposable SQLite database, seeds two accounts, and hands the origin to
web/tests/s8_p1_session_browser.mjs, which makes the actual assertions inside a
headless Chrome. The claims Sprint 8 rests on — that HttpOnly means the page
cannot read the token, that a raw fetch bypassing the client seam is refused —
are claims about a browser, and only a browser can settle them.

WHY A REAL SERVER PROCESS RATHER THAN TestClient. Same-origin, cookies, CSRF
and CORS are all properties of an ORIGIN. TestClient has no origin: it dispatches
into the ASGI app in-process. The page must be served by the same server that
answers /auth/*, which is the real deployment shape (`app.mount("/app", ...)`),
so the suite runs against exactly that.

FS_COOKIE_INSECURE=1 is set for the child, because the harness serves plain
http and a conforming browser will not return a Secure cookie over it. The
Python suite asserts separately that Secure is the default, so this opt-out
cannot conceal a regression in the attribute it disables.

USAGE:
    python test_s8_p1_browser.py
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

GM_EMAIL = "gm@example.test"
COMM_EMAIL = "commissioner@example.test"
PASSWORD = "sprint8-password"

_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "s8p1_browser.db")
_DB_URL = f"sqlite:///{_DB_PATH.replace(os.sep, '/')}"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed() -> None:
    """Seed the disposable database in a SUBPROCESS.

    Deliberately not in this process: db.schema binds its engine from
    DATABASE_URL at import time, and importing it here would leave this
    process holding a second engine on the same SQLite file as the server.
    """
    script = f'''
import os, sys
os.environ["DATABASE_URL"] = {_DB_URL!r}
sys.path.insert(0, {ROOT!r})

from db.schema import Base, engine, SessionLocal, League, LeagueCommissioner, Team, User
from ledger.ledger import create_ledger_table
from auth.jwt_auth import hash_password

Base.metadata.create_all(engine)
create_ledger_table()

with SessionLocal() as db:
    league = League(name="Certification League", season=2026)
    db.add(league); db.flush()

    gm_team = Team(team_name="Gravy Train", owner="A. Gm",
                   email={GM_EMAIL!r}, league_id=league.id)
    comm_team = Team(team_name="The Braintrust", owner="A. Commissioner",
                     email={COMM_EMAIL!r}, league_id=league.id)
    db.add_all([gm_team, comm_team]); db.flush()

    hashed = hash_password({PASSWORD!r})
    gm = User(email={GM_EMAIL!r}, hashed_password=hashed, team_id=gm_team.id, role="gm")
    comm = User(email={COMM_EMAIL!r}, hashed_password=hashed,
                team_id=comm_team.id, role="commissioner")
    db.add_all([gm, comm]); db.flush()

    db.add(LeagueCommissioner(league_id=league.id, user_id=comm.id, source="bootstrap"))
    db.commit()
print("seeded")
'''
    result = subprocess.run([sys.executable, "-c", script],
                            capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise SystemExit("FAILED: could not seed the disposable database")


def _wait_for_health(url: str, process: subprocess.Popen, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.35)
    return False


def main() -> int:
    print("=" * 60)
    print("S8-P1 — real-browser session verification")
    print("=" * 60)

    node = subprocess.run(["node", "--version"], capture_output=True, text=True)
    if node.returncode != 0:
        print("  [FAIL] node is required for the browser suite")
        return 1

    _seed()
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"

    env = dict(os.environ)
    env["DATABASE_URL"] = _DB_URL
    env["FS_COOKIE_INSECURE"] = "1"     # the harness serves plain http
    env.pop("FS_ALLOWED_ORIGINS", None)
    env["JWT_SECRET_KEY"] = "s8-p1-browser-suite-secret"

    print(f"\nStarting the application on {origin} …")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    try:
        if not _wait_for_health(f"{origin}/health", server):
            print("  [FAIL] the application did not become healthy")
            if server.poll() is not None and server.stdout:
                print(server.stdout.read()[-3000:])
            return 1
        print("Healthy. Handing off to the browser suite.\n")

        suite = subprocess.run(
            ["node", os.path.join("web", "tests", "s8_p1_session_browser.mjs"),
             f"--origin={origin}",
             f"--gm-email={GM_EMAIL}",
             f"--commissioner-email={COMM_EMAIL}",
             f"--password={PASSWORD}"],
            cwd=ROOT,
        )
        return suite.returncode
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    code = main()
    print()
    if code == 0:
        print("S8-P1 BROWSER — all assertions PASSED")
    else:
        print("S8-P1 BROWSER — FAILED")
    sys.exit(code)
