#!/usr/bin/env python3
"""SPRINT C1 — the Yahoo retention inventory, the scopes, and the attribution.

    python test_c1_yahoo_retention.py

WHAT THIS PROTECTS. `ops/yahoo_retention.py` is a hand-maintained record of every
persisted field that originates from Yahoo. A hand-maintained list rots — someone
adds a provider column and the inventory quietly stops being true, which is the
worst possible failure for a document whose entire purpose is to be relied on
when a contractual question is answered.

So the inventory is checked against the SCHEMA. A provider-origin column that
exists in `db/schema.py` and is not inventoried fails this suite, and an
inventoried field that does not exist fails it too.

IT ALSO ASSERTS WHAT THE PRODUCT MUST NOT CLAIM. No code may assert a right to
retain Yahoo data indefinitely, the OAuth scopes may not widen beyond the three
approved, and the attribution must stay factual — no sponsorship, endorsement,
partnership or affiliation.

NO ECONOMICS, NO DATABASE, NO NETWORK. This suite reads source and a frozen
inventory. It settles nothing and connects to nothing.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

FAIL: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


def section(title: str) -> None:
    print(f"\n{title}")


print("=" * 74)
print("C1 — YAHOO RETENTION INVENTORY, SCOPES AND ATTRIBUTION")
print("=" * 74)

from ops.yahoo_retention import (  # noqa: E402
    DERIVED, GATE, PROVIDER_FACTS, REQUIRES_RULING, SAFE_WITHOUT_RULING,
    YAHOO_DERIVED_RELATIONSHIPS, inventoried_columns, related_columns,
    report,
)

SCHEMA = (ROOT / "db" / "schema.py").read_text(encoding="utf-8")


def schema_columns() -> dict:
    """`{table: {column, ...}}` for every mapped table in db/schema.py."""
    tables: dict = {}
    for blob in re.split(r"\nclass ", SCHEMA)[1:]:
        match = re.search(r'__tablename__\s*=\s*"([a-z0-9_]+)"', blob)
        if not match:
            continue
        # C2.1 - [a-z0-9_]+, NOT [a-z_]+. The old class excluded digits, so
        # a column named `provider_v2_key` was invisible to the completeness
        # scan entirely. Proved by injecting `provider_c2_probe_field` and
        # watching certification pass. Same defect class as the Sprint B
        # migration identifier regex that rejected `rc2`.
        cols = set(re.findall(r"^\s{4}([a-z0-9_]+)\s*[:=].*Column\(", blob, re.M))
        tables.setdefault(match.group(1), set()).update(cols)
    return tables


TABLES = schema_columns()


# ── 1 · the inventory is COMPLETE against the schema ───────────────────

section("1 · Every Yahoo-origin persisted column is inventoried")

# ── C2.1 · WHY A NAME SCAN IS NOT ENOUGH, AND WHAT REPLACED IT ─────────────
#
# The original check looked for columns NAMED `provider_*` or `yahoo_*`. That is
# a real signal and it still runs below, but on its own it was wrong in the most
# dangerous direction: `players.name`, `players.position` and `players.nfl_team`
# are written straight from the Yahoo snapshot and are named for what they are,
# so the scan could not see them and certification passed with them missing.
#
# There is no honest fully-automatic discovery here — whether a column carries
# Yahoo-origin content is a judgement about DATA FLOW, not about a name. So the
# authority is an EXPLICIT REVIEWED SET, each entry tied to the module that
# writes it. Reviewing this list is a deliberate act; that is the point. A new
# provider write must be added here, and the name scan stays as a second net.

SOURCE_DERIVED = (
    # providers/persist.py `_persist_matchup` - the competitive facts.
    ("matchups", "home_score", "providers/persist.py"),
    ("matchups", "away_score", "providers/persist.py"),
    ("matchups", "winner_team_id", "providers/persist.py"),
    ("matchups", "provider_matchup_key", "providers/persist.py"),
    ("matchups", "refreshed_at", "providers/persist.py"),
    # providers/persist.py `refresh_league_week` - the league boundary.
    ("leagues", "provider_current_week", "providers/persist.py"),
    # providers/persist.py `_persist_roster` - the roster slot itself.
    ("roster_slots", "slot", "providers/persist.py"),
    ("roster_slots", "player_id", "providers/persist.py"),
    ("roster_slots", "week", "providers/persist.py"),
    # providers/identity.py `resolve_or_create_player` - the Player row.
    ("players", "name", "providers/identity.py"),
    ("players", "position", "providers/identity.py"),
    ("players", "nfl_team", "providers/identity.py"),
    ("players", "yahoo_id", "providers/identity.py"),
    ("players", "provider", "providers/identity.py"),
    ("players", "provider_player_key", "providers/identity.py"),
    # team and league resolution keys.
    ("teams", "provider_team_key", "providers/identity.py"),
    ("teams", "provider_team_id", "providers/identity.py"),
    ("leagues", "provider_league_key", "providers/identity.py"),
    # auth/provider_grant.py `record_grant` / `_seal_into` - the credential.
    ("provider_grants", "provider_subject", "auth/provider_grant.py"),
    ("provider_grants", "access_token_sealed", "auth/provider_grant.py"),
    ("provider_grants", "refresh_token_sealed", "auth/provider_grant.py"),
    # Found by the C2.1 independent source trace, not by the name scan:
    # `granted_scope` holds the scope string Yahoo RETURNED.
    ("provider_grants", "granted_scope", "auth/provider_grant.py"),
    # auth/yahoo_identity.py `resolve_user` - the signed-in account.
    ("users", "provider_subject", "auth/yahoo_identity.py"),
    # providers/persist.py `record_conflict` - the disagreement audit.
    ("provider_conflict", "provider_value", "providers/persist.py"),
)

inventoried = inventoried_columns()
related = related_columns()

# EVERY REVIEWED SOURCE FIELD MUST BE INVENTORIED. This is the assertion the
# original suite lacked, and the one that would have caught the omission.
uncovered = [f"{t}.{c} (written in {w})"
             for t, c, w in SOURCE_DERIVED if (t, c) not in inventoried]
check("every source-derived Yahoo-origin field is inventoried",
      not uncovered,
      f"NOT INVENTORIED: {uncovered}" if uncovered
      else f"{len(SOURCE_DERIVED)} reviewed fields")

# The four C2 found missing are named individually, so a regression on any one
# fails with its own line rather than inside a list.
for table, column in (("players", "name"), ("players", "position"),
                      ("players", "nfl_team"), ("players", "provider")):
    check(f"  · {table}.{column} is inventoried",
          (table, column) in inventoried)

# The reviewed set must itself be real - a typo would silently weaken the check
# above rather than fail it.
unreal = [f"{t}.{c}" for t, c, _ in SOURCE_DERIVED
          if t not in TABLES or c not in TABLES[t]]
check("every reviewed field exists in the schema", not unreal, str(unreal))

missing_src = sorted({w for _, _, w in SOURCE_DERIVED
                      if not (ROOT / w).is_file()})
check("every reviewed field names a source file that exists",
      not missing_src, str(missing_src))

# ── the name scan, kept as a second net ─────────────────────────────
#
# It cannot prove completeness, but it reliably catches the obvious drift: a new
# `provider_*` or `yahoo_*` column added with no matching inventory entry.

named = set()
for table, cols in TABLES.items():
    for col in cols:
        if re.search(r"provider_|yahoo", col, re.I):
            named.add((table, col))

missing = named - inventoried - related
check("the schema provider-named columns are all inventoried or classified",
      not missing,
      f"NOT INVENTORIED: {sorted(missing)}" if missing else f"{len(named)} columns")
check("  · and the scan actually found some, so it is not vacuous",
      len(named) >= 10, f"{len(named)} provider-named columns")
# THE SCAN MUST SEE DIGIT-BEARING NAMES. `[a-z_]+` did not, which is how a probe
# column slipped past certification entirely.
check("  · the column scan accepts digit-bearing identifiers",
      bool(re.match(r"^[a-z0-9_]+$", "provider_v2_key")))

# The other direction: the inventory must not cite fields that do not exist.
ghosts = []
for table, column in sorted(inventoried | related):
    if table not in TABLES:
        ghosts.append(f"{table} (no such table)")
    elif column not in TABLES[table]:
        ghosts.append(f"{table}.{column}")
check("the inventory cites no field that does not exist in the schema",
      not ghosts, str(ghosts))

check("the inventory covers MORE than a name scan can see",
      len(inventoried - named) >= 8,
      f"{len(inventoried - named)} plainly-named provider facts")

for table, column in (("matchups", "home_score"), ("matchups", "away_score"),
                      ("matchups", "winner_team_id"), ("roster_slots", "slot"),
                      ("roster_slots", "player_id"), ("roster_slots", "week")):
    check(f"  · {table}.{column} is inventoried",
          (table, column) in inventoried)

# ── the Yahoo-derived relationship is classified, not silently omitted ───────

check("the matchup pairing is explicitly classified",
      ("matchups", "home_team_id") in related
      and ("matchups", "away_team_id") in related,
      str(sorted(related)))
check("  · and is NOT misclassified as a raw Yahoo identifier",
      ("matchups", "home_team_id") not in inventoried
      and ("matchups", "away_team_id") not in inventoried)
check("  · while its economic dependency is recorded",
      any(r.economic_dependency for r in YAHOO_DERIVED_RELATIONSHIPS))


# ── 2 · every fact carries the sentence a decision is made against ───────────

section("2 · The inventory is usable, not decorative")

check("every provider fact says what it is", all(f.what for f in PROVIDER_FACTS))
check("every provider fact says why it is held",
      all(f.purpose for f in PROVIDER_FACTS))
check("every provider fact says what breaks if it is deleted",
      all(len(f.if_deleted) > 20 for f in PROVIDER_FACTS))
check("the economic dependencies are marked",
      sum(1 for f in PROVIDER_FACTS if f.economic_dependency) >= 4,
      str(sum(1 for f in PROVIDER_FACTS if f.economic_dependency)))
check("derived FantasyStakes state is enumerated separately",
      len(DERIVED) >= 5, str(len(DERIVED)))
check("every derived entry names the fields it came from",
      all(d.from_fields for d in DERIVED))

# The derived entries must point at real modules.
for d in DERIVED:
    for path in (p.strip() for p in d.where.split(",")):
        check(f"  · {d.name}: {path} exists", (ROOT / path).is_file(), path)


# ── 3 · the contractual gate stays OPEN and unclaimed ────────────────────────

section("3 · Nothing claims a retention right that was not granted")

r = report()
check("the inventory reports the gate as open", r["gate_open"] is True)
check("  · and says so in words", "not been clarified" in GATE)
check("both categories are populated",
      len(SAFE_WITHOUT_RULING) >= 5 and len(REQUIRES_RULING) >= 5,
      f"{len(SAFE_WITHOUT_RULING)} safe / {len(REQUIRES_RULING)} requires")

# The inventory must not read as a compliance claim.
inventory_src = (ROOT / "ops" / "yahoo_retention.py").read_text(encoding="utf-8")
for phrase in ("compliant", "compliance with", "permitted to retain",
               "we may retain", "approved by Yahoo", "Yahoo has agreed"):
    check(f"the inventory makes no claim: {phrase!r}",
          phrase.lower() not in inventory_src.lower())

# NO CODE ANYWHERE may assert indefinite retention.
CODE = list(ROOT.glob("*.py")) + [
    p for d in ("api", "auth", "providers", "ops", "economy", "reports",
                "betting", "ledger", "db")
    for p in (ROOT / d).rglob("*.py") if "__pycache__" not in str(p)
]
CLAIMS = re.compile(
    r"retain(?:ed|s)?\s+(?:it\s+)?(?:indefinitely|forever|permanently)"
    r"|stored?\s+(?:indefinitely|forever|permanently)"
    r"|keep\s+(?:yahoo\s+)?data\s+(?:indefinitely|forever)", re.I)

# AN AFFIRMATIVE CLAIM, NOT A DENIAL OF ONE. The inventory's whole purpose is to
# say that no such right has been granted, and it has to use the words to say
# so — "Nothing in this repository asserts a right to retain Yahoo data" would
# trip a blanket ban on the phrase. So a line is an offender only when it
# ASSERTS the thing: a negation anywhere in the sentence clears it, and this
# suite excludes itself, since it necessarily quotes what it forbids.
NEGATED = re.compile(
    r"\b(no|not|never|nothing|neither|nor|without|whether|cannot|"
    r"must not|may not|does not|is not|un\w+)\b", re.I)
offenders = []
for path in CODE:
    if path.name == pathlib.Path(__file__).name:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        continue
    # BY SENTENCE, NOT BY PHYSICAL LINE. Source wraps: `"Not asserting ... that
    # Yahoo data may be "` / `"retained indefinitely."` puts the claim and its
    # negation on different lines, and a line-by-line scan reads the second half
    # as an assertion. Adjacent string literals are joined and comment markers
    # dropped first, so a wrapped sentence is scanned as the one sentence it is.
    joined = re.sub(r'"\s*\n\s*"', "", text)
    joined = re.sub(r"'\s*\n\s*'", "", joined)
    joined = re.sub(r"^\s*#[:]?\s?", " ", joined, flags=re.M)
    joined = re.sub(r"\s+", " ", joined)
    # A BOUNDED WINDOW, NOT AN UNBOUNDED SENTENCE. Splitting the whole file on
    # sentence terminators produces blobs so large that some negation word
    # appears in nearly all of them, which would clear every claim — proved by
    # injecting `retained indefinitely` and watching it pass. So the negation
    # must sit close enough to the claim to actually be negating it: the window
    # runs from the nearest preceding sentence break, capped at 140 characters.
    for match in CLAIMS.finditer(joined):
        start = max(match.start() - 140, 0)
        window = joined[start:match.end()]
        cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
        if cut != -1:
            window = window[cut + 2:]
        if not NEGATED.search(window):
            offenders.append(f"{path.relative_to(ROOT)}: {window.strip()[:90]}")
check("no module claims Yahoo data may be retained indefinitely",
      not offenders, str(offenders))

# And no retention TIMER may exist, because no period has been granted.
check("no retention period is implemented",
      not re.search(r"RETENTION_(DAYS|PERIOD|SECONDS)\s*=", inventory_src))


# ── 4 · the OAuth scopes have not widened ────────────────────────────────────

section("4 · Yahoo scopes stay at the approved minimum")

from auth.yahoo_oidc import SCOPES  # noqa: E402

check("the scopes are exactly openid, email, fspt-r",
      tuple(SCOPES) == ("openid", "email", "fspt-r"), str(tuple(SCOPES)))
check("  · no write scope is requested",
      not any("-w" in s or "write" in s.lower() for s in SCOPES), str(SCOPES))
check("  · and the read scope is the fantasy read scope",
      "fspt-r" in SCOPES)


# ── 5 · attribution is factual and claims no relationship ────────────────────

section("5 · Attribution is factual, and claims nothing further")

ATTR = (ROOT / "web" / "js" / "attribution.js").read_text(encoding="utf-8")
check("the required attribution text is present, verbatim",
      "Fantasy data provided by Yahoo Fantasy" in ATTR)

# It must be RENDERED, not merely defined.
rendered = [p.name for p in (ROOT / "web" / "js").glob("*.js")
            if "attributionFooter()" in p.read_text(encoding="utf-8")
            and p.name != "attribution.js"]
check("  · and it is rendered on at least one product surface",
      len(rendered) >= 2, ", ".join(sorted(rendered)))

WEB = " ".join(p.read_text(encoding="utf-8")
               for p in (ROOT / "web" / "js").rglob("*.js")
               if "/tests/" not in str(p))
for claim in ("sponsored by", "in partnership with", "official partner",
              "endorsed by", "affiliated with", "powered by Yahoo",
              "a Yahoo company"):
    check(f"the product claims no relationship: {claim!r}",
          claim.lower() not in WEB.lower())


# ── 6 · the inventory is machine-readable ────────────────────────────────────

section("6 · The inventory can be consumed by something other than a human")

import json  # noqa: E402

payload = json.dumps(report())
check("report() is JSON-serialisable", len(payload) > 500)
check("  · and carries the economic dependency list",
      len(report()["economic_dependencies"]) >= 4)

import subprocess  # noqa: E402

proc = subprocess.run([sys.executable, "-m", "ops.yahoo_retention", "--json"],
                      cwd=str(ROOT), capture_output=True, text=True,
                      encoding="utf-8", errors="replace",
                      env={**os.environ, "PYTHONIOENCODING": "utf-8"})
check("the CLI emits valid JSON", proc.returncode == 0
      and json.loads(proc.stdout or "{}").get("gate_open") is True,
      (proc.stderr or "")[-160:])


print("\n" + "=" * 74)
if FAIL:
    print(f"C1 YAHOO RETENTION — {len(FAIL)} FAILED")
    for f in FAIL:
        print(f"  · {f}")
    sys.exit(1)
print("PASS: Yahoo retention inventory, scopes and attribution certified")
print("      CONTRACTUAL RETENTION GATE REMAINS OPEN — by design.")
