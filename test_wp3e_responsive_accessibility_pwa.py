#!/usr/bin/env python3
"""
test_wp3e_responsive_accessibility_pwa.py — WP3E · the final UI hardening gate.

WHAT THIS CERTIFIES, AND WHY THE MEASUREMENTS HAD TO BE REAL.

  1. THE VIEWPORT MATRIX. Fifteen viewports, portrait and landscape, phone
     through desktop, driven in a real browser. Both carry-forward issues this
     package closes were invisible in source and obvious the moment something
     measured a box: a rail 76px tall holding a card that needed 127px, and a
     lockup squeezed to 37px because a badge beside it was 93px wide.

  2. THE PWA SURFACE. A manifest is a contract with a launcher, and a service
     worker is a thing that can silently serve yesterday's application. Both are
     asserted here field by field and rule by rule — including, at length, the
     things the worker must NEVER do.

  3. ACCESSIBILITY THAT CAN BE MEASURED. Touch targets, focus rings, landmarks,
     accessible names, zoom, reduced motion. Where a claim genuinely cannot be
     automated — colour perception, screen-reader narration — it is reported as
     not automated rather than asserted from a stylesheet.

WHAT THIS PACKAGE DELIBERATELY DID NOT DO. It moved no navigation, renamed no
tab, changed no economics, touched no schema, and hid no content to make a
measurement pass. The close control stays UPPER-RIGHT; see §2 below.

DATABASE. None of its own — the browser tiers run against disposable
application servers.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_app_server import (                              # noqa: E402
    AppServer, COMMISSIONER_EMAIL, GM_EMAIL, PASSWORD,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


# ── 1 · The governing conflict, resolved and recorded ────────────────────────

_section("1 · The close control is UPPER-LEFT, and the POR now says so")

# THE CONTRADICTION IS RESOLVED, so the assertion that kept it visible is gone.
#
# WP3E certified upper-right because Rev 4.3 §25 required it. WP3E-FIX moved the
# control on an owner ruling that superseded §25, and asserted BOTH the ruling
# and the stale POR text so nobody could mistake the disagreement for a
# rendering bug. The owner has now confirmed the ruling as the governing POR and
# instructed that the written specification be brought into line, so §25 itself
# is the claim under test rather than the gap around it.
POR = _read("spec", "FantasyStakes_UIUX_Rev4_3_FINAL_POR.md")
_assert("the authoritative Rev 4.3 POR §25 specifies upper-left",
        "positioned **upper-left**" in POR)
_assert("and no longer instructs an implementer to use upper-right",
        "positioned **upper-right**" not in POR)
_assert("it carries the ruling's other terms — attached, matching Versus, 44px",
        "visually attached to the active card, sheet or modal" in POR
        and "matching the Versus composer treatment" in POR
        and "minimum 44 px touch target" in POR)
# §26 LISTED UPPER-LEFT AS A RETIRED CONCEPT, which would have contradicted §25
# from two pages away — the exact failure mode this synchronization exists to
# remove.
_assert("§26 no longer retires upper-left placement",
        'the League-tab countdown or the "Fantasy Sportsbook" heading suffix' in POR
        and "Upper-left close placement is **not** a retired concept" in POR)

# THE HISTORICAL DELTA IS MARKED, NOT REWRITTEN. Editing a record of what Rev
# 4.2 decided so it agrees with a later ruling would misrepresent the history
# rather than correct it. The statement stands and is labelled unusable.
DELTA = _read("spec", "SPEC_Mobile_UI_UX_Rev4_2_Global_Delta.md")
_assert("the Rev 4.2 delta still records what Rev 4.2 decided",
        "The close **X** is always in the **upper-right**" in DELTA)
_assert("but it is marked SUPERSEDED and points at the governing section",
        "SUPERSEDED — HISTORICAL RECORD ONLY" in DELTA
        and "Do not implement from this paragraph" in DELTA
        and "§25 of `FantasyStakes_UIUX_Rev4_3_FINAL_POR.md`" in DELTA)

_assert("the shipped control is described as upper-left",
        "upper-left" in _read("web", "index.html")
        and "upper-right" not in _read("web", "index.html"))

# ONE AUTHORITY, NOT A PER-SURFACE SWEEP. Every dismissible overlay renders
# through `sheet()`, so the ruling is kept by a single rule and a single markup
# helper. Asserting that is what makes "everywhere" checkable at all.
_COMPONENTS_JS = _read("web", "js", "components.js")
_assert("exactly one close control is emitted in the whole frontend",
        _COMPONENTS_JS.count("data-fs-close") == 1)
_assert("and every sheet is composed through the helper that emits it",
        "return closeControl() + titleHtml" in _COMPONENTS_JS)

_COMPONENTS_CSS = _read("web", "styles", "components.css")
_CLOSE_BODIES = re.findall(r"\.fs-sheet__close[^{]*\{([^}]*)\}", _COMPONENTS_CSS)
_assert("the shared rule anchors it left", any(re.search(r"(^|;)\s*left:", b)
                                               for b in _CLOSE_BODIES))
_RIGHTS = [m.strip().lower() for b in _CLOSE_BODIES
           for m in re.findall(r"(?:^|;)\s*right:\s*([^;]+)", b)]
_assert("and releases the right anchor rather than leaving it inherited",
        _RIGHTS == ["auto"], ", ".join(_RIGHTS) or "none")

# NO SURFACE OPTS OUT. A stylesheet that re-anchored this control to the right
# for one panel would be invisible in the shared rule and obvious only on that
# one screen, which is precisely the failure a universal treatment is for.
for _name in sorted(os.listdir(os.path.join(ROOT, "web", "styles"))):
    if not _name.endswith(".css") or _name == "components.css":
        continue
    _other = _read("web", "styles", _name)
    _assert(f"{_name} does not re-anchor the close control",
            not re.search(r"\.fs-sheet__close[^{]*\{[^}]*(^|[;\s])(right|left)\s*:",
                          _other))


# ── 2 · The manifest ─────────────────────────────────────────────────────────

_section("2 · The web app manifest")

MANIFEST_PATH = os.path.join(ROOT, "web", "manifest.webmanifest")
_assert("a manifest exists", os.path.isfile(MANIFEST_PATH))

MANIFEST = json.loads(_read("web", "manifest.webmanifest"))
_assert("it is valid JSON", isinstance(MANIFEST, dict))
_assert("the product is named FantasyStakes",
        MANIFEST["name"] == "FantasyStakes"
        and MANIFEST["short_name"] == "FantasyStakes", MANIFEST["name"])
_assert("no FantasyBeefs branding survives anywhere in it",
        "FantasyBeefs" not in json.dumps(MANIFEST)
        and "Fantasy Beefs" not in json.dumps(MANIFEST))
_assert("it starts inside the application, not at the site root",
        MANIFEST["start_url"] == "/app/index.html", MANIFEST["start_url"])
_assert("its scope is the application mount",
        MANIFEST["scope"] == "/app/", MANIFEST["scope"])
_assert("it installs standalone", MANIFEST["display"] == "standalone")
_assert("theme and background match the shipped app background",
        MANIFEST["theme_color"] == "#0c0a07"
        and MANIFEST["background_color"] == "#0c0a07")
_assert("and the theme colour agrees with the page's own meta tag",
        'content="#0c0a07"' in _read("web", "index.html"))

# NO CLAIM THE PRODUCT CANNOT KEEP. A manifest is read by app stores and by
# launchers; a capability declared here that does not exist is a promise made
# to a user who cannot collect on it.
for overclaim in ("share_target", "file_handlers", "protocol_handlers",
                  "shortcuts", "related_applications"):
    _assert(f"no unsupported {overclaim} is declared", overclaim not in MANIFEST)

_assert("the description is the product's own trust anchor",
        MANIFEST.get("description") == "Real odds. Fantasy stakes. "
        "Ledger keeps score.", str(MANIFEST.get("description")))


_section("3 · Icons")

ICONS = MANIFEST["icons"]
_assert("at least one 192px and one 512px icon are declared",
        any(i["sizes"] == "192x192" for i in ICONS)
        and any(i["sizes"] == "512x512" for i in ICONS))
_assert("maskable variants are declared for both sizes",
        {i["sizes"] for i in ICONS if i.get("purpose") == "maskable"}
        == {"192x192", "512x512"})
_assert("every declared icon is a PNG",
        all(i["type"] == "image/png" for i in ICONS))

import struct                                                      # noqa: E402

for icon in ICONS:
    path = os.path.join(ROOT, "web", icon["src"].lstrip("./"))
    _assert(f"{icon['src']} exists on disk", os.path.isfile(path))
    if not os.path.isfile(path):
        continue
    data = open(path, "rb").read()
    _assert(f"{icon['src']} is a real PNG",
            data[:8] == b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", data[16:24])
    declared = icon["sizes"].split("x")[0]
    _assert(f"{icon['src']} is genuinely {icon['sizes']}",
            (width, height) == (int(declared), int(declared)),
            f"{width}x{height}")
    _assert(f"{icon['src']} is not an empty placeholder", len(data) > 200,
            f"{len(data)} bytes")

_assert("an apple-touch-icon exists, because iOS ignores the manifest for it",
        os.path.isfile(os.path.join(ROOT, "web", "assets", "icons",
                                    "apple-touch-icon.png")))
INDEX = _read("web", "index.html")
_assert("the manifest is linked from the page",
        'rel="manifest"' in INDEX and "manifest.webmanifest" in INDEX)
_assert("and so is the apple-touch-icon",
        'rel="apple-touch-icon"' in INDEX)


# ── 4 · The service worker ───────────────────────────────────────────────────

_section("4 · The service worker caches the shell and NEVER the API")

SW_PATH = os.path.join(ROOT, "web", "service-worker.js")
_assert("a service worker exists", os.path.isfile(SW_PATH))
SW = _read("web", "service-worker.js")
# CODE ONLY FOR THE TERM SCAN BELOW. The worker's header explains at length
# WHICH credentials it must never cache, naming each of them; scanning the file
# for those words would fail on the documentation that exists to prevent the
# very thing being scanned for.
SW_CODE = re.sub(r"/\*[\s\S]*?\*/", " ",
                 re.sub(r"^\s*//.*$", " ", SW, flags=re.M))

_assert("it is registered from the page", "serviceWorker" in INDEX
        and "service-worker.js" in INDEX)
_assert("registration failure is non-fatal — it is an affordance, not a "
        "dependency", ".catch(" in INDEX)
_assert("and registration waits for load, so it never delays the first paint",
        "'load'" in INDEX)

_assert("the cache carries an explicit version", "const VERSION" in SW)
_assert("activation deletes every cache that is not this version",
        "caches.delete" in SW and "!== VERSION" in SW)
_assert("a new worker takes over immediately",
        "skipWaiting" in SW and "clients.claim" in SW)

# THE RULE THAT MATTERS MOST.
_assert("it is NETWORK-FIRST, so a release is never trapped behind a cache",
        "await fetch(request)" in SW
        and SW.index("await fetch(request)") < SW.index("caches.match(request)"),
        "network attempted before any cached copy")
_assert("and the reason is recorded where the next reader will find it",
        "WHY NETWORK-FIRST AND NOT CACHE-FIRST" in SW)

for never in ("/auth/", "/league/", "/beef/", "/health"):
    _assert(f"{never} can never be cached", f"'{never}'" in SW)
_assert("the never-cache list is applied before anything is stored",
        "NEVER_CACHE.some" in SW)
_assert("only static extensions are ever stored",
        "SHELL_EXTENSIONS" in SW)
_assert("non-GET requests are never intercepted",
        "request.method !== 'GET'" in SW)
_assert("cross-origin requests are never intercepted",
        "url.origin !== self.location.origin" in SW)
_assert("credentialed requests are never stored",
        "credentials === 'include'" in SW)
_assert("only a clean 200 basic response is stored",
        "status === 200" in SW and "type === 'basic'" in SW)
_assert("no token, session or identity term appears in the worker's CODE",
        not re.search(r"token|cookie|password|Bearer", SW_CODE, re.I),
        (re.search(r".{0,40}(token|cookie|password|Bearer).{0,40}",
                   SW_CODE, re.I) or [""])[0])
_assert("it pre-caches nothing, so there is no second asset inventory to drift",
        "pre-cache nothing" in SW or "NOTHING IS PRE-CACHED" in SW)
_assert("and it does not claim to be an offline mode",
        "It is not an offline mode" in SW)


# ── 5 · Zoom, motion and the safe areas, from the shipped sources ───────────

_section("5 · Zoom, reduced motion and safe areas")

_viewport = re.search(r'<meta name="viewport" content="([^"]+)"', INDEX)
_assert("a viewport meta is present", _viewport is not None)
VP = _viewport.group(1) if _viewport else ""
_assert("it does NOT disable user zoom",
        "user-scalable=no" not in VP.replace(" ", "")
        and not re.search(r"maximum-scale\s*=\s*1", VP), VP)
_assert("and it opts into safe-area insets", "viewport-fit=cover" in VP)

CSS = "\n".join(_read("web", "styles", name)
                for name in sorted(os.listdir(os.path.join(ROOT, "web", "styles")))
                if name.endswith(".css"))
_assert("a reduced-motion rule exists",
        "prefers-reduced-motion: reduce" in CSS)
_assert("it neutralises transitions and animations",
        "transition-duration: 0.01ms" in CSS
        and "animation-duration: 0.01ms" in CSS)
_assert("all four safe-area insets are defined as tokens",
        all(f"env(safe-area-inset-{side}" in CSS
            for side in ("top", "bottom", "left", "right")))
_assert("the horizontal insets are actually applied to the chrome",
        "--fs-safe-left" in CSS and "--fs-safe-right" in CSS
        and CSS.count("--fs-safe-left") >= 2)
_assert("a focus-visible baseline exists so no control is reachable unseen",
        ":focus-visible" in CSS and "outline:" in CSS)


# ── 6 · Nothing outside WP3E's remit moved ───────────────────────────────────

_section("6 · Scope discipline")

# ── THE SCOPE GUARD IS ANCHORED TO THIS PACKAGE'S OWN COMMIT RANGE ──────────
#
# It used to diff against a moving HEAD, which was right exactly once: while
# this package was the uncommitted work. The moment a LATER package landed, the
# guard started reporting that later package's files as violations of this one's
# scope — auth/, providers/ and a migration, none of which this package wrote.
#
# A scope claim is a claim about a fixed set of changes, so it is measured
# against a fixed range. These two SHAs are this package's parent and its
# commit; the answer is now the same today as it was on the day it was made, and
# no future package can turn it red.
WP3E_PARENT, WP3E_COMMIT = "5504933", "ef1ef6e"
_diff = subprocess.run(
    ["git", "diff", "--name-only", WP3E_PARENT, WP3E_COMMIT],
    cwd=ROOT, capture_output=True, text=True).stdout.split()
_touched = set(_diff)

for forbidden in ("db/schema.py", "economy/", "ledger/", "betting/", "odds/",
                  "beefs/", "reports/", "providers/", "auth/"):
    hits = sorted(f for f in _touched if f.startswith(forbidden))
    _assert(f"{forbidden} is untouched by this package", not hits,
            ", ".join(hits))

_assert("no migration was introduced",
        not any(f.startswith("migrations/") for f in _touched))
# WP3E-FIX2 NARROWLY OPENS THIS. The owner instructed that the close-X POR be
# synchronized with shipped behaviour, so two spec files may move — and only
# those two, and only on that subject. Everything else under spec/ and docs/
# stays shut, and the diff is checked for what it says as well as which file it
# is in: a close-X synchronization that quietly edited economics or navigation
# would pass a filename check and fail this one.
_POR_SYNC_ALLOWED = {
    "spec/FantasyStakes_UIUX_Rev4_3_FINAL_POR.md",
    "spec/SPEC_Mobile_UI_UX_Rev4_2_Global_Delta.md",
}
_spec_touched = {f for f in _touched
                 if f.startswith("spec/") or f.startswith("docs/")}
_assert("no governed document outside the close-X synchronization is modified",
        _spec_touched <= _POR_SYNC_ALLOWED,
        ", ".join(sorted(_spec_touched - _POR_SYNC_ALLOWED)) or "none")

_spec_diff = subprocess.run(
    ["git", "diff", "-U0", "bc2de7b", "--", "spec/", "docs/"],
    cwd=ROOT, capture_output=True, text=True,
    encoding="utf-8", errors="replace").stdout
_changed_lines = [ln[1:] for ln in _spec_diff.splitlines()
                  if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
# THE PRODUCT'S OWN NAME IS NOT A SUBJECT TERM. A first cut scanned for "stake",
# which matches every occurrence of FantasyStakes and flagged the citation that
# tells the reader where the governing rule lives. The name is removed before
# the scan and the terms are matched on word boundaries.
_OFF_SUBJECT = (r"wager", r"credits?", r"settle\w*", r"escrow", r"Ledger",
                r"postseason", r"Yahoo", r"navigation", r"tab bar", r"odds",
                r"buy-?in", r"payout")
_off = []
for _ln in _changed_lines:
    _clean = _ln.replace("FantasyStakes", "").replace("Fantasy Stakes", "")
    if any(re.search(rf"\b{term}\b", _clean, re.I) for term in _OFF_SUBJECT):
        _off.append(_ln.strip())
_assert("and every changed spec line is about the close control",
        not _off, " | ".join(_off)[:200])

# THE NAVIGATION IS UNCHANGED — the one thing §2 of the brief locks hardest.
# THE ORDER IS READ FROM THE SHIPPED MODULE, not from where the strings happen
# to appear in the file. `NAV_DESTINATIONS` is what the tab bar renders from.
sys.path.insert(0, ROOT)
_nav_src = _read("web", "js", "nav.js")
_ids = re.findall(r"id:\s*'([a-z]+)'", _nav_src)
_assert("the five primary destinations keep their locked order",
        _ids[:5] == ["standings", "league", "action", "week", "ledger"],
        " -> ".join(_ids[:5]))
_assert("and Standings is still the default landing surface",
        re.search(r"DEFAULT_DESTINATION_ID\s*=\s*'standings'", _nav_src)
        is not None)


# ── 7 · The browser tiers ────────────────────────────────────────────────────

def _run_node(script: str, label: str, env_extra: dict | None = None) -> None:
    node = shutil.which("node")
    if node is None:
        _assert(f"{label} — node is available", False, "node not on PATH")
        return
    print(f"\n{label}")
    env = dict(os.environ)
    env.update(env_extra or {})
    proc = subprocess.run(
        [node, os.path.join(ROOT, "web", "tests", script)],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print(proc.stderr.rstrip()[-2000:])
    passes = proc.stdout.count("[PASS]")
    fails = proc.stdout.count("[FAIL]")
    _assert(f"{label} is green", proc.returncode == 0 and fails == 0,
            f"{passes} PASS / {fails} FAIL, exit {proc.returncode}")


_section("7 · The matrix, measured in a real browser")

# THE POOL SLATE IS SEEDED TOO. Play draws its Pools zone from the governed
# weekly draw, and a fixture without one renders the empty state — which is
# correct behaviour and useless for a geometry claim about Pool cards.
for mode, email in (("gm", GM_EMAIL), ("commissioner", COMMISSIONER_EMAIL)):
    with AppServer(seed_priceable_versus=True, seed_pool_slate=True) as server:
        _run_node("wp3e_browser.mjs", f"WP3E browser suite — {mode}",
                  {"FS_TEST_ORIGIN": server.origin,
                   "FS_TEST_AUTH_EMAIL": email,
                   "FS_TEST_AUTH_PASSWORD": PASSWORD,
                   "FS_WP3E_MODE": mode})

# THE GATE RUNS SIGNED OUT, so the harness is given no credentials.
# THE GATE NEEDS A CONFIGURED YAHOO SIGN-IN to have a CTA to certify. Without
# it the deployment correctly reports `yahoo: false` and draws its unavailable
# state — a real state, certified in the AUTH1 suite, and not this section's
# subject.
with AppServer(server_env={
        # A REAL PRODUCTION PROCESS, because the gate's claim is a PRODUCTION
        # claim: Sign in with Yahoo and no password field anywhere. A
        # development process legitimately renders the local sign-in, and
        # certifying geometry against that would be certifying the wrong page.
        "FS_ENV": "production",
        "FS_YAHOO_CLIENT_ID": "dj0yJmk9wp3e",
        "FS_YAHOO_CLIENT_SECRET": "wp3e-secret",
        "FS_YAHOO_REDIRECT_URI": "https://stakes.example/auth/yahoo/callback",
}) as server:
    _run_node("wp3e_browser.mjs", "WP3E browser suite — sign-in gate",
              {"FS_TEST_ORIGIN": server.origin, "FS_WP3E_MODE": "gate"})

# AND THE PWA ASSETS ARE FETCHED FROM THE REAL SERVER, because a manifest that
# exists on disk and 404s over HTTP is not a manifest.
_section("8 · The PWA assets, served")

import urllib.request                                              # noqa: E402
import urllib.error                                                # noqa: E402

with AppServer() as server:
    def _get(path):
        try:
            with urllib.request.urlopen(server.origin + path, timeout=10) as r:
                return r.status, r.headers.get("Content-Type", ""), r.read()
        except urllib.error.HTTPError as e:
            return e.code, "", b""

    status, ctype, body = _get("/app/manifest.webmanifest")
    _assert("the manifest is served", status == 200, str(status))
    _assert("with a manifest media type",
            "manifest" in ctype or "json" in ctype, ctype)
    _assert("and it parses over the wire",
            json.loads(body.decode())["name"] == "FantasyStakes")

    status, ctype, body = _get("/app/service-worker.js")
    _assert("the service worker is served", status == 200, str(status))
    _assert("as JavaScript", "javascript" in ctype, ctype)

    for icon in ICONS:
        path = "/app/" + icon["src"].lstrip("./")
        status, ctype, body = _get(path)
        _assert(f"{path} is served", status == 200, str(status))
        _assert(f"  · as a PNG with real bytes",
                ctype == "image/png" and body[:8] == b"\x89PNG\r\n\x1a\n"
                and len(body) > 200, f"{ctype}, {len(body)} bytes")

    status, _, _ = _get("/app/assets/icons/apple-touch-icon.png")
    _assert("the apple-touch-icon is served", status == 200, str(status))

    status, _, body = _get("/app/index.html")
    _assert("the start_url loads", status == 200, str(status))
    _assert("and it links the manifest it declares",
            b"manifest.webmanifest" in body)


# ── 9 · What was NOT automated ───────────────────────────────────────────────
#
# STATED, NOT SKIPPED. A certification that quietly omits what it could not
# measure reads as a stronger claim than it is.

_section("9 · Recorded as not automated in this environment")

for item in (
    "colour-contrast ratios are reasoned from the palette tokens and their "
    "recorded measurements, not sampled from rendered pixels",
    "screen-reader narration is not exercised; semantics are asserted "
    "structurally instead",
    "real device installation on iOS and Android is not performed",
    "true browser page-zoom is approximated by root font size and by the "
    "320-wide viewport",
):
    _assert(f"NOT AUTOMATED: {item}", True, "reported")


print("\n" + "=" * 66)
if _failures:
    print(f"WP3E RESPONSIVE / ACCESSIBILITY / PWA — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("WP3E RESPONSIVE / ACCESSIBILITY / PWA — all assertions PASSED")
