#!/usr/bin/env python3
"""
tools/yahoo_live_probe.py — YAHOO-LIVE-1 · the live authorization probe.

WHAT IT IS FOR. Answering, with evidence rather than assumption, whether Yahoo
currently authorizes this application's Fantasy Sports API access — and doing it
on the bearer token of a real signed-in user rather than on the repository's
operator credential.

IT IS NOT PART OF THE APPLICATION AND NOTHING IMPORTS IT. It is run by hand, by
an operator who has live Yahoo configuration, and it is the only place in this
repository that makes an outbound Fantasy API call.

    python tools/yahoo_live_probe.py --grant-user-id 7
    python tools/yahoo_live_probe.py --grant-user-id 7 --league 461.l.488800

── WHY THIS EXISTS SEPARATELY FROM THE TEST SUITE ──────────────────────────

A certification suite must be deterministic and must run with no credentials.
A live probe is the opposite of both: it needs real secrets and its result is
whatever Yahoo says today. Fusing them would mean either a suite that cannot run
offline or a probe that proves nothing. So the suite proves the ARCHITECTURE
offline, and this proves the AUTHORIZATION when there is something to prove it
against.

── WHAT IT WILL NOT DO ─────────────────────────────────────────────────────

IT PRINTS NO BEARER MATERIAL. Not the access token, not the refresh token, not
the Authorization header, not a prefix or a length of any of them. Presence is
reported; value never is.

IT PERSISTS NO YAHOO FANTASY INFORMATION. Responses are inspected in memory and
what is printed is STRUCTURAL — which keys came back, how many entries, what
shape — not the content. Nothing is written to a file, a table or a fixture.
The Yahoo agreement's restriction is on Fantasy Information, and the safe way to
honour it while still learning what the API returns is to describe the shape and
keep none of the substance.

IT CRAWLS NOTHING. The endpoint list below is fixed, ordered smallest-first, and
stops at the first refusal. A broad walk of a provider's API is exactly what an
access agreement means when it says excessive usage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FANTASY_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"

#: SMALLEST FIRST, AND EACH ONE ANSWERS A DIFFERENT QUESTION.
#:
#: `game/nfl`            public game metadata. Needs no league, no team and no
#:                       user association at all. If THIS is refused, the
#:                       refusal cannot be about league access — which is the
#:                       single most useful discriminator in the whole probe.
#: `users;use_login=1`   the credential's own identity. Proves the token is
#:                       associated with a Yahoo user and that the Fantasy API
#:                       will speak about them.
#: `...;out=games`       the leagues that user actually holds. This is what a
#:                       commissioner's "connect my league" flow would call, and
#:                       it is the first call that is about a person's data.
PROBES = [
    ("game_meta", f"{FANTASY_BASE}/game/nfl",
     "public game metadata — requires no league authorization"),
    ("user_identity", f"{FANTASY_BASE}/users;use_login=1",
     "the credential's own Yahoo user"),
    ("user_leagues",
     f"{FANTASY_BASE}/users;use_login=1/games;game_keys=nfl/leagues",
     "leagues this user is authorized to see"),
]


def _league_probes(league_key: str) -> list[tuple[str, str, str]]:
    """The narrow, named reads for one league. Never a crawl."""
    base = f"{FANTASY_BASE}/league/{league_key}"
    return [
        ("league_settings", f"{base}/settings",
         "regular-season length, playoff structure, scoring identity"),
        ("league_standings", f"{base}/standings", "standings"),
        ("league_scoreboard", f"{base}/scoreboard", "current-week matchups"),
    ]


def _describe(payload) -> str:
    """A STRUCTURAL description. Keys and counts, never values.

    This is the function that keeps the probe on the right side of the storage
    boundary: it is impossible to print Fantasy Information through it, because
    it never returns a leaf value — only the shape around one.
    """
    def walk(node, depth=0):
        if depth > 3:
            return "…"
        if isinstance(node, dict):
            keys = list(node.keys())[:12]
            return "{" + ", ".join(
                f"{k}: {walk(node[k], depth + 1)}" for k in keys) + "}"
        if isinstance(node, list):
            if not node:
                return "[]"
            return f"[{len(node)} × {walk(node[0], depth + 1)}]"
        return type(node).__name__

    return walk(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grant-user-id", type=int, required=True,
                        help="FantasyStakes user id whose stored Yahoo grant "
                             "the probe runs on")
    parser.add_argument("--league", default=None,
                        help="Yahoo league key, e.g. 461.l.488800. Probed only "
                             "if the smaller calls are authorized.")
    args = parser.parse_args()

    print("YAHOO LIVE AUTHORIZATION PROBE")
    print(f"  at {datetime.now(timezone.utc).isoformat()}")
    print(f"  on the stored grant of user {args.grant_user_id}")
    print()

    try:
        import requests
    except ImportError:
        print("  requests is not installed; cannot probe.")
        return 2

    from auth.provider_grant import GrantError, access_token_for
    from db.schema import SessionLocal

    db = SessionLocal()
    try:
        try:
            token = access_token_for(db, user_id=args.grant_user_id)
        except GrantError as exc:
            # THE REASON CODE, NOT THE EXCEPTION. `detail` can name a
            # configuration value; the code is an enumerated string.
            print(f"  NO USABLE GRANT — {exc.reason_code}")
            print("  The architecture is reachable; this user has not "
                  "authorized, or Yahoo has rejected the grant.")
            return 3

        print("  bearer token   obtained from the stored per-user grant "
              "(value not shown)")
        print()

        headers = {"Authorization": f"Bearer {token}",
                   "Accept": "application/json"}
        results = []
        probes = list(PROBES)
        if args.league:
            probes += _league_probes(args.league)

        for name, url, why in probes:
            shown = url.replace(FANTASY_BASE, "…/fantasy/v2")
            print(f"  → {name}")
            print(f"    {shown}")
            print(f"    ({why})")
            try:
                response = requests.get(url, headers=headers,
                                        params={"format": "json"}, timeout=20)
            except Exception as exc:
                print(f"    TRANSPORT FAILED: {type(exc).__name__}")
                results.append((name, "transport", None))
                break

            status = response.status_code
            print(f"    HTTP {status}")
            if status == 200:
                try:
                    payload = response.json()
                    print(f"    shape: {_describe(payload)[:400]}")
                except ValueError:
                    print("    body was not JSON")
                results.append((name, "ok", status))
            else:
                # THE ERROR TEXT IS SANITISED AND TRUNCATED. Yahoo's error
                # bodies are short and do not echo the Authorization header,
                # but the value is bounded here rather than trusted to be.
                text = " ".join(response.text.split())[:200]
                for secret in ("Bearer", token):
                    text = text.replace(secret, "<redacted>")
                print(f"    body: {text}")
                results.append((name, "refused", status))
                print()
                print("    STOPPING. A refusal is the answer; continuing would "
                      "be crawling to get the same one repeatedly.")
                break
            print()

        print()
        print("SUMMARY")
        for name, outcome, status in results:
            print(f"  {name:18} {outcome:10} {status if status else ''}")

        refused = [r for r in results if r[1] == "refused"]
        if refused and refused[0][0] == "game_meta":
            print()
            print("  CLASSIFICATION: the refusal is on PUBLIC GAME METADATA, "
                  "which requires no league authorization and no league "
                  "membership. A league-scoped or user-scoped problem cannot "
                  "produce it. This is an application-registration condition — "
                  "the same one WP2B measured.")
        elif refused:
            print()
            print(f"  CLASSIFICATION: refused first at {refused[0][0]}, AFTER "
                  f"smaller calls succeeded. That is a narrower condition than "
                  f"WP2B measured and is scoped to that resource.")
        elif results:
            print()
            print("  CLASSIFICATION: authorized. Record the observed structures "
                  "and proceed with the adapter work.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
