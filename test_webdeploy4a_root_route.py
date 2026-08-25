#!/usr/bin/env python3
"""WEBDEPLOY-4a - the bare origin lands on the application.

    python test_webdeploy4a_root_route.py

WHY THIS SUITE EXISTS. With the custom domain live, `GET /` answered
`{"detail":"Not Found"}` - FastAPI's default for a path nothing claims. Every
other surface was healthy; nothing had ever registered `/`, because until
`app.fantasystakesapp.com` existed the application was only ever reached at a
path. The first thing a human typing the domain saw was a raw API error.

WHAT IS ASSERTED, AND WHY EACH MATTERS

  1. `GET /` is not a 404 any more, and specifically not the FastAPI shape.
  2. It redirects to `_APP_HOME` - the constant the application already uses for
     "where a user lands", shared with the sign-in paths. The test reads the
     constant rather than hard-coding the string, so the redirect cannot drift
     away from the rest of the application without this failing.
  3. The status is 303. Not 301: a permanently-cached redirect is the wrong
     promise for a route whose destination may yet change, and it is very hard
     to take back from browsers that have already stored it.
  4. THE REDIRECT HAS NO SIDE EFFECTS. No cookie, no session, no demo league.
     This is the assertion that keeps `/` from quietly becoming a second way in:
     entering the demo is `POST /demo/enter`, and a GET that mutated state is
     precisely what that route was designed to avoid.
  5. The destination actually serves the FantasyStakes shell, and the shell
     carries the certified Try Demo control - so the redirect lands somewhere a
     visitor can act, not merely somewhere that returns 200.
  6. `/ready`, the demo entry flow and the Yahoo gating are all untouched.

Runs on SQLite: nothing here depends on PostgreSQL semantics, and the demo
entry check is exercised against a seeded showcase only when one is available.
"""
from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="wd4a-")
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = (
        "sqlite:///" + os.path.join(_TMP, "wd4a.db").replace(os.sep, "/"))
os.environ.setdefault("JWT_SECRET_KEY", "webdeploy4a-suite")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_FAILURES: list = []
_PASSES = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _PASSES
    if condition:
        _PASSES += 1
        print(f"  [PASS] {label}" + (f" - {detail}" if detail else ""))
    else:
        _FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{title}")


from fastapi.testclient import TestClient  # noqa: E402

import api.main_rc2 as entry  # noqa: E402
from api.main import _APP_HOME  # noqa: E402

print("=" * 78)
print("WEBDEPLOY-4a - ROOT ROUTE")
print("=" * 78)

# ENTERED ONCE SO THE STARTUP HOOKS RUN. They are what create the schema; a
# TestClient constructed without entering it never fires them, and every
# database read below would fail on a table that was never made.
with TestClient(entry.app):
    pass

client = TestClient(entry.app)


# -- 1 . the root route itself ----------------------------------------------

section("1 - GET / redirects to the application's canonical home")

r = client.get("/", follow_redirects=False)

check("GET / is no longer 404", r.status_code != 404, f"HTTP {r.status_code}")
check("  - and is not the FastAPI not-found body",
      "Not Found" not in r.text, r.text[:60] or "(empty body)")
check("GET / is a redirect", 300 <= r.status_code < 400, f"HTTP {r.status_code}")
check("  - specifically 303 See Other, matching this file's landing convention",
      r.status_code == 303, f"HTTP {r.status_code}")
check("  - NOT 301, which browsers cache permanently",
      r.status_code != 301, f"HTTP {r.status_code}")

location = r.headers.get("location")
check("it sends a Location header", bool(location), str(location))
# READ FROM THE CONSTANT, NOT A LITERAL. If the application moves its home, this
# test moves with it - and a redirect that drifted away from `_APP_HOME` would
# fail here rather than in a browser.
check("Location is the application's own _APP_HOME constant",
      location == _APP_HOME, f"{location!r} vs _APP_HOME={_APP_HOME!r}")
check("the target is explicit and stable, not a wildcard or a query",
      location == _APP_HOME and "?" not in (location or ""), str(location))


# -- 2 . the redirect must do nothing else ----------------------------------

section("2 - The redirect has no side effects")

# THE POINT OF THIS SECTION. `/` must not become a second, GET-shaped way into
# the demo. Entering is POST /demo/enter and nothing else.
check("no cookie is set by GET /", not r.cookies,
      str(dict(r.cookies)) if r.cookies else "no cookies")
raw_cookies = [v for k, v in r.headers.items() if k.lower() == "set-cookie"]
check("  - no Set-Cookie header at all", not raw_cookies, str(raw_cookies))

from db.schema import League, SessionLocal  # noqa: E402

with SessionLocal() as db:
    before = db.query(League).count()
client.get("/", follow_redirects=False)
client.get("/", follow_redirects=False)
with SessionLocal() as db:
    after = db.query(League).count()
check("repeated GET / creates no league", before == after,
      f"{before} -> {after}")

head = client.request("HEAD", "/", follow_redirects=False)
check("HEAD / behaves like GET /", head.status_code in (303, 405),
      f"HTTP {head.status_code}")


# -- 3 . the destination is the real application ----------------------------

section("3 - The destination serves the FantasyStakes application")

followed = client.get("/", follow_redirects=True)
check("following the redirect returns 200", followed.status_code == 200,
      f"HTTP {followed.status_code}")
check("  - it is HTML, not a JSON API error",
      "text/html" in followed.headers.get("content-type", ""),
      followed.headers.get("content-type", ""))
check("  - it is the FantasyStakes shell",
      "<title>FantasyStakes</title>" in followed.text,
      "title found" if "<title>FantasyStakes</title>" in followed.text else "NOT FOUND")
check("  - no raw FastAPI error body survived the redirect",
      '{"detail"' not in followed.text[:400], "clean")

direct = client.get(_APP_HOME)
check(f"{_APP_HOME} serves the same document directly",
      direct.status_code == 200 and direct.text == followed.text,
      f"HTTP {direct.status_code}")

# THE SHELL MUST BE ACTIONABLE, not merely present: the gate the visitor lands
# on is the one carrying the D1-certified public entry control.
gate = client.get("/app/js/auth-view.js")
check("the gate script is served", gate.status_code == 200,
      f"HTTP {gate.status_code}")
check("  - and carries the certified Try Demo control",
      "fs-gate-demo" in gate.text and "/demo/enter" in gate.text,
      "Try Demo -> /demo/enter")


# -- 4 . nothing else moved --------------------------------------------------

section("4 - Existing contracts are unchanged")

ready = client.get("/ready")
body = ready.json()
check("/ready still answers", ready.status_code in (200, 503),
      f"HTTP {ready.status_code}")
check("  - and still reports the same check set",
      set(body.get("checks", {})) >= {"database", "configuration", "migrations",
                                      "schema", "writes", "yahoo_sign_in"},
      ", ".join(sorted(body.get("checks", {}))))
check("  - /ready is NOT a redirect", ready.status_code != 303,
      f"HTTP {ready.status_code}")

version = client.get("/version")
check("/version still answers 200", version.status_code == 200,
      f"HTTP {version.status_code}")

methods = client.get("/auth/methods")
check("/auth/methods still answers 200", methods.status_code == 200,
      f"HTTP {methods.status_code}")

# DEMO ENTRY IS UNCHANGED. On an unseeded database this is the certified 404;
# on a seeded one it seats a visitor. Both prove the route still owns entry -
# what must never happen is `/` taking the job over.
demo = client.post("/demo/enter")
if demo.status_code == 404:
    detail = demo.json().get("detail", {})
    check("POST /demo/enter keeps its certified unseeded behaviour",
          isinstance(detail, dict) and detail.get("reason_code") == "demo_not_seeded",
          str(detail)[:70])
else:
    payload = demo.json()
    check("POST /demo/enter still seats a visitor",
          demo.status_code == 200 and payload.get("demo") is True,
          f"HTTP {demo.status_code} league {payload.get('league_id')}")

check("GET /demo/enter is still not a way in",
      client.get("/demo/enter", follow_redirects=False).status_code == 405,
      "405 Method Not Allowed")


# -- 5 . Yahoo remains gated -------------------------------------------------

section("5 - Yahoo gating is untouched")

m = methods.json()
check("Yahoo sign-in is not offered", m.get("yahoo") is False, str(m.get("yahoo")))
check("the root redirect does not point at any Yahoo surface",
      "yahoo" not in (location or "").lower(), str(location))

yahoo_start = client.get("/auth/yahoo/start", follow_redirects=False)
check("/auth/yahoo/start does not begin OAuth",
      yahoo_start.status_code == 303
      and "sign_in_unavailable" in yahoo_start.headers.get("location", ""),
      f"HTTP {yahoo_start.status_code} -> {yahoo_start.headers.get('location')}")


print("\n" + "=" * 78)
if _FAILURES:
    print(f"WEBDEPLOY-4a ROOT ROUTE: {len(_FAILURES)} FAILED")
    for item in _FAILURES:
        print(f"  - {item}")
    raise SystemExit(1)
print(f"WEBDEPLOY-4a ROOT ROUTE: all {_PASSES} assertions PASSED")
