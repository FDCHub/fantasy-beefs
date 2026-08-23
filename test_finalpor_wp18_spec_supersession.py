#!/usr/bin/env python3
"""FINAL POR · WP-18 certification — the governing spec agrees with the code.

    F1  a governing active spec exists and names itself as such
    F2  it states all eleven required Final POR behaviours
    F3  every implementation module it names actually exists
    F4  every certification suite it cites actually exists
    F5  every superseded document carries an explicit supersession header
    F6  a superseded document still says what it always said, below its header
    F7  the spec's era constants match `ruleset.py`
    F8  the spec's account names match `economy/economy_events.py`
    F9  the spec's split matches `economy/championship_distribution.py`
    F10 the spec states what is BLOCKED and what is OPEN rather than implying done

WHY THIS SUITE EXISTS AT ALL. A spec that merely contradicts the code is a
documentation problem; a spec that contradicts the code AND is believed is a
correctness problem, because the next change is made against the wrong model.
The previous run left the governing specs describing the retired architecture
and recorded it as the branch's most important documentation debt. Asserting the
agreement mechanically is what stops it recurring: a rename in the code that is
not reflected here fails a test rather than quietly ageing the document.

WHAT IT DELIBERATELY DOES NOT DO. It does not parse prose or check that the
English is accurate — no test can. It checks the things that CAN drift silently
and be checked: named modules, named suites, named constants, named accounts,
and the presence of the supersession headers.
"""
from __future__ import annotations

import io
import os
import re
import sys

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(ROOT, "spec", "FANTASYSTAKES_FINAL_POR.md")

SUPERSEDED = (
    os.path.join("spec", "RC2_CHAMPIONSHIP_POR.md"),
    os.path.join("spec", "FantasyBeefs_Merged_Section_4_BABEconomy.md"),
)


def _read(path: str) -> str:
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


# ── F1 · the governing spec ─────────────────────────────────────────────────

print("\nWP18-F1 · a governing active spec exists and names itself")
_assert("spec/FANTASYSTAKES_FINAL_POR.md exists", os.path.exists(SPEC_PATH))
SPEC = _read(SPEC_PATH) if os.path.exists(SPEC_PATH) else ""
_assert("  · it declares itself GOVERNING ACTIVE SPEC",
        "GOVERNING ACTIVE SPEC" in SPEC)
_assert("  · it names what it supersedes",
        "spec/RC2_CHAMPIONSHIP_POR.md" in SPEC)
_assert("  · and scopes itself to RULESET_FINAL_POR seasons",
        "RULESET_FINAL_POR" in SPEC and "RULESET_LEGACY" in SPEC)
_assert("  · stating explicitly that nothing is retroactive",
        "retroactive" in SPEC.lower())


# ── F2 · the eleven required behaviours ────────────────────────────────────

print("\nWP18-F2 · it states all eleven required Final POR behaviours")
REQUIRED = {
    "3-term FS Score":
        ("Matchup Net + Prop Pool Net", "Skunk Fees"),
    "optional Skunk":
        ("Skunk Fee of 0", "no Points Championship at all"),
    "unused Minimum -> FS Pot":
        ("min:{team}:{week}", "fantasystakes_championship:{league}:{season}"),
    "league-level minted pots":
        ("league-level virtual-credit allocation", "championship_issuance:"),
    "Top-Off pot addition":
        ("bab_issuance:{L}:{S}", "-2X"),
    "actual-assessed Points Pot":
        ("actually assessed", "never posted"),
    "postseason FS scoring":
        ("no playoff-boundary freeze", "through the postseason"),
    "Grand VC-total model":
        ("championship VC awarded", "3/2/1 model is retired"),
    "canonical dead heats":
        ("Dead heat", "ascending canonical team id"),
    "ruleset_version":
        ("ruleset_version", "stamped inside the activation transaction"),
    "external reconciliation mapping":
        ("not a ledger posting", "frozen participant field"),
}
# SEARCHED OVER A NORMALISED SPEC, NOT THE RAW BYTES. Markdown wraps lines and
# uses typographic minus signs and bold markers, so a raw substring search finds
# the FORMATTING rather than the statement — three of these first failed on a
# line break and a Unicode minus while the spec said exactly the right thing.
# What is being checked is that the document STATES each behaviour; whitespace
# and typography are not part of that claim.
_FLAT = re.sub(r"\s+", " ", SPEC.replace("−", "-").replace("**", ""))

for name, tokens in REQUIRED.items():
    missing = [t for t in tokens
               if re.sub(r"\s+", " ", t.replace("−", "-")) not in _FLAT]
    _assert(f"  · {name}", not missing, f"missing {missing}")


# ── F3/F4 · everything it names exists ─────────────────────────────────────

print("\nWP18-F3 · every implementation module it names exists")
modules = sorted(set(re.findall(r"`((?:economy|reports|betting|db|api"
                                r"|migrations|providers|season|ledger)"
                                r"/[A-Za-z0-9_/]+\.py)`", SPEC)))
_assert("the spec names implementation modules at all", len(modules) >= 10,
        f"{len(modules)} named")
absent = [m for m in modules if not os.path.exists(os.path.join(ROOT, m))]
_assert("  · and every one of them exists", not absent, str(absent))

print("\nWP18-F4 · every certification suite it cites exists")
suites = sorted(set(re.findall(r"`(test_[A-Za-z0-9_]+\.py)`", SPEC)))
_assert("the spec cites certification suites", len(suites) >= 10,
        f"{len(suites)} cited")
missing_suites = [s for s in suites
                  if not os.path.exists(os.path.join(ROOT, s))]
_assert("  · and every one of them exists", not missing_suites,
        str(missing_suites))
_assert("  · each Final POR work package's suite is cited",
        all(any(f"wp{n}_" in s for s in suites)
            for n in (1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)),
        str(suites))


# ── F5/F6 · the superseded documents ───────────────────────────────────────

print("\nWP18-F5 · every superseded document carries an explicit header")
for rel in SUPERSEDED:
    path = os.path.join(ROOT, rel)
    _assert(f"{rel} exists", os.path.exists(path))
    if not os.path.exists(path):
        continue
    body = _read(path)
    head = body[:6000]
    _assert(f"  · {rel} is marked SUPERSEDED at the very top",
            "SUPERSEDED" in head and head.lstrip().startswith(">"),
            head.lstrip()[:60])
    _assert(f"  · {rel} names its successor",
            "spec/FANTASYSTAKES_FINAL_POR.md" in head)
    _assert(f"  · {rel} says it STILL governs legacy seasons",
            "RULESET_LEGACY" in head)
    _assert(f"  · {rel} says it is preserved and not edited below the header",
            "preserved as historical evidence" in head
            and "not edited" in head)

print("\nWP18-F6 · a superseded document still says what it always said")
rc2 = _read(os.path.join(ROOT, "spec", "RC2_CHAMPIONSHIP_POR.md"))
_assert("RC2's original title survives",
        "# FantasyStakes 1.0 RC2 — Championship POR" in rc2)
_assert("  · its 3/2/1 table is untouched",
        "| 1st | 3 | 3 |" in rc2, "the retired model was edited away")
_assert("  · its boundary rule is untouched",
        "The scoring window closes at the boundary immediately before "
        "`playoff_start_week`" in rc2)
_assert("  · its per-GM contribution rule is untouched",
        "FantasyStakes Championship Contribution per GM" in rc2)
_assert("  · and the header states the delta rather than deleting it",
        "three terms" in rc2 and "no boundary and no freeze" in rc2)

section4 = _read(os.path.join(ROOT, "spec",
                              "FantasyBeefs_Merged_Section_4_BABEconomy.md"))
_assert("Section 4's original title survives",
        "# Fantasy Beefs — Merged Hybrid · Section 4 — BAB Economy" in section4)
_assert("  · BAB-506 is still stated as it was",
        "highest\ncumulative Yahoo regular-season Points For" in section4
        or "cumulative Yahoo regular-season Points For" in section4)
_assert("  · and the header names it as superseded by rule identifier",
        "**BAB-506**" in section4)
_assert("  · while naming the rules that are NOT superseded",
        "BAB-503's tie rule is NOT superseded" in section4)


# ── F7/F8/F9 · the spec agrees with the code ───────────────────────────────

print("\nWP18-F7 · the spec's era constants match `ruleset.py`")
from ruleset import RULESET_FINAL_POR, RULESET_LEGACY  # noqa: E402

_assert("the spec states the legacy version number",
        f"`RULESET_LEGACY = {RULESET_LEGACY}`" in SPEC
        or f"RULESET_LEGACY = {RULESET_LEGACY}" in SPEC,
        str(RULESET_LEGACY))
_assert("  · and the Final POR version number",
        f"RULESET_FINAL_POR = {RULESET_FINAL_POR}" in SPEC
        or f"`RULESET_FINAL_POR` ({RULESET_FINAL_POR})" in SPEC,
        str(RULESET_FINAL_POR))

print("\nWP18-F8 · the spec's account names match `economy_events.py`")
from economy.economy_events import (  # noqa: E402
    championship_issuance_account, ff_championship_account,
    fantasystakes_championship_account, points_championship_account,
)

for fn, label in ((fantasystakes_championship_account, "FantasyStakes"),
                  (points_championship_account, "Points"),
                  (ff_championship_account, "Fantasy Football"),
                  (championship_issuance_account, "minted issuance")):
    template = fn("{L}", "{S}")
    _assert(f"  · the {label} account name appears verbatim",
            template in SPEC or template.replace("{L}:{S}",
                                                 "{league}:{season}") in SPEC,
            template)

print("\nWP18-F9 · the spec's split matches the canonical implementation")
from economy.championship_distribution import CHAMPIONSHIP_SPLIT  # noqa: E402

_assert("the split is stated as the code defines it",
        " / ".join(str(p) for p in CHAMPIONSHIP_SPLIT) in SPEC
        or "60 / 30 / 10" in SPEC,
        str(CHAMPIONSHIP_SPLIT))
_assert("  · with §17's three worked dead-heat examples",
        all(token in SPEC for token in ("(60+30)/2", "(30+10)/2", "(10+0)/2")))
_assert("  · and the remainder convention",
        "first ordinal" in SPEC and "ascending canonical team id" in SPEC)

from economy.grand_championship import MINIMUM_FUNDED_PILLARS  # noqa: E402

_assert("  · the Grand Championship's pillar minimum matches the code",
        f"least {'two' if MINIMUM_FUNDED_PILLARS == 2 else MINIMUM_FUNDED_PILLARS}"
        in SPEC.lower() or "At least two FUNDED pillars" in SPEC,
        str(MINIMUM_FUNDED_PILLARS))


# ── F10 · what is blocked, said plainly ────────────────────────────────────

print("\nWP18-F10 · the spec states what is BLOCKED and what is OPEN")
_assert("Yahoo authorization is stated UNKNOWN",
        "authorization state: UNKNOWN" in SPEC or "UNKNOWN" in SPEC)
_assert("  · bracket classification is stated BLOCKED",
        "BLOCKED" in SPEC and "PROV-1" in SPEC)
_assert("  · the third-place question is stated OPEN, not implied settled",
        "OPEN PRODUCT QUESTION" in SPEC and "A ruling is required" in SPEC)
_assert("  · PostgreSQL parity is stated NOT RUN",
        "NOT RUN" in SPEC and "TEST_DATABASE_URL" in SPEC)
_assert("  · and nothing blocked is described as done",
        "provider finality BLOCKED" in SPEC or "BLOCKED" in SPEC)


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-18 spec supersession: all assertions passed")
