"""
test_pool_catalog_invariants.py -- Pool catalog family-invariant control.

Product authority: spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_1.md
Implementation scope: spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_1.md

WHAT THIS PROVES. Rollover eligibility follows evaluator family without
exception: RANK_EXTREMUM is never rollover-eligible, QUALIFIER always is
(FR-POOL-ROLL-1, ruled 2026-07-31). Rev1.0 carried two violations, #84 and
#87, inherited from section-based classification in
FR-6_1_CATALOG_CLASSIFICATION.md that was never reconciled against
evaluator_family. Rev1.1 corrects them.

DISCRIMINATION. Assertion 3 loads the real frozen spec/pool_catalog_rev1_0.json
and requires exactly two mismatches. A stub would prove nothing against a
reconstruction. This also enforces Rev1.0's retention: delete or move it and
this suite goes red.

Assertion 10 parses the POR section 10 catalog table and compares it row by row
against the JSON. Rev1.0 stated rollover eligibility in three independent
places -- a count cell, a prose paragraph, and this table. Correcting some and
missing others leaves the document self-consistent and wrong (FR-POOL-POR-1).
The table is located by heading and parsed structurally, never by grep and
never by fixed line number, so it survives insertion of any line above it.

TEN ASSERTIONS. Assertion 10 collects every parity problem into one issues list
and reports through a single assertion. The diagnostics are detailed; the
contract is ten.

PURE. No Session, no ORM, no database, no network, no clock, no randomness.
JSON and text only. Exit 0 on pass, 1 on failure.
"""

import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = os.path.join(_ROOT, "spec")

_CATALOG_REV11 = os.path.join(_SPEC, "pool_catalog_rev1_1.json")
_CATALOG_REV10 = os.path.join(_SPEC, "pool_catalog_rev1_0.json")
_POR_REV11 = os.path.join(_SPEC, "SPEC_Pool_Catalog_Rotation_POR_Rev1_1.md")

_POR_REV11_REL = "spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_1.md"

# Section 10 is located by its heading number, not its title text and not a
# line number. A retitled section still parses; a renumbered one fails loudly.
# The trailing group prevents "## 10.1 ..." from matching as section 10.
_SECTION_10 = re.compile(r"^##\s+10\.(?:\s|$)")
_ANY_H2 = re.compile(r"^##\s")

# A section 10 catalog row: a number, then a backtick-quoted key. The backtick
# discriminates against the retired table and the blocked tables, which also
# lead with a number and a pipe but carry a display name in that field.
_ROW = re.compile(r"^\|\s*\d+\s*\|\s*`")

_FIELDS = 11          # 10 pipes plus the empty tail after the trailing pipe
_NUM_FIELD = 1
_RO_FIELD = 8

_failures = []


def _assert(condition, label, detail=""):
    if condition:
        print("  PASS  {}".format(label))
    else:
        print("  FAIL  {}".format(label))
        if detail:
            print("        {}".format(detail))
        _failures.append(label)


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _family_mismatches(defs):
    """Catalog numbers where rollover_eligible disagrees with evaluator_family."""
    return sorted(
        d["catalog_number"]
        for d in defs
        if bool(d["rollover_eligible"]) != (d["evaluator_family"] == "QUALIFIER")
    )


def _parse_por_section_10(path):
    """Return (rows, errors) for the POR section 10 catalog table.

    Parsing is bounded to section 10: it begins after the section 10 heading
    and stops at the next H2 heading or EOF. The row regex is applied only
    inside that window, so a table added elsewhere in the POR can never
    contribute rows.

    rows maps catalog_number -> bool rollover_eligible, read from the RO cell.
    Structural problems are collected as errors rather than raised, so a
    malformed table reports as a named failure instead of a traceback.
    """
    rows = {}
    errors = []

    with open(path, encoding="utf-8") as fh:
        lines = [ln.rstrip("\n") for ln in fh]

    starts = [i for i, ln in enumerate(lines) if _SECTION_10.match(ln)]
    if len(starts) == 0:
        errors.append("section 10 heading not found")
        return rows, errors
    if len(starts) > 1:
        errors.append("section 10 heading appears {} times at lines {}".format(
            len(starts), [i + 1 for i in starts]))
        return rows, errors

    start = starts[0]
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if _ANY_H2.match(lines[i]):
            end = i
            break

    for offset, line in enumerate(lines[start + 1:end], start=start + 2):
        if not _ROW.match(line):
            continue
        fields = line.split("|")
        if len(fields) != _FIELDS:
            errors.append("line {}: {} fields, expected {}".format(
                offset, len(fields), _FIELDS))
            continue
        ro_text = fields[_RO_FIELD].strip()
        if ro_text not in ("", "Y"):
            errors.append("line {}: RO cell is {!r}, expected '' or 'Y'".format(
                offset, ro_text))
            continue
        num = int(fields[_NUM_FIELD].strip())
        if num in rows:
            errors.append("line {}: duplicate catalog number {}".format(offset, num))
            continue
        rows[num] = (ro_text == "Y")

    return rows, errors


def main():
    print("\n== Pool catalog family invariants ==")

    rev11 = _load(_CATALOG_REV11)
    rev10 = _load(_CATALOG_REV10)
    defs11 = rev11["definitions"]
    defs10 = rev10["definitions"]

    # 1 -- Rev1.1 definitions count
    _assert(len(defs11) == 94,
            "1. Rev1.1 definitions count is 94",
            "got {}".format(len(defs11)))

    # 2 -- Rev1.1 family invariant holds everywhere
    mis11 = _family_mismatches(defs11)
    _assert(len(mis11) == 0,
            "2. Rev1.1 family-invariant mismatches is 0",
            "got {}".format(mis11))

    # 3 -- frozen Rev1.0 carries exactly two. Real file, never a stub.
    mis10 = _family_mismatches(defs10)
    _assert(len(mis10) == 2,
            "3. Frozen Rev1.0 family-invariant mismatches is 2",
            "got {} -> {}".format(len(mis10), mis10))

    # 4 -- and they are #84 and #87 specifically
    _assert(mis10 == [84, 87],
            "4. Rev1.0 mismatches are exactly #84 and #87",
            "got {}".format(mis10))

    # 5 -- both corrected in Rev1.1
    by_num11 = {d["catalog_number"]: d for d in defs11}
    corrected = {n: bool(by_num11[n]["rollover_eligible"])
                 for n in (84, 87) if n in by_num11}
    _assert(corrected == {84: True, 87: True},
            "5. #84 and #87 are rollover-eligible in Rev1.1",
            "got {}".format(corrected))

    # 6 -- every declared count equals its measured value. All nine keys.
    #      The subject-scope field is named "scope" in the catalog schema.
    declared = rev11["counts"]
    measured = {
        "active": len(defs11),
        "team": sum(1 for d in defs11 if d["scope"] == "TEAM"),
        "matchup": sum(1 for d in defs11 if d["scope"] == "MATCHUP"),
        "blocked": sum(1 for d in defs11 if d["dependency_state"] == "BLOCKED"),
        "rotatable": sum(1 for d in defs11 if d["dependency_state"] == "ENABLED"),
        "rollover_eligible": sum(1 for d in defs11 if d["rollover_eligible"]),
        "rank_extremum": sum(1 for d in defs11
                             if d["evaluator_family"] == "RANK_EXTREMUM"),
        "qualifier": sum(1 for d in defs11
                         if d["evaluator_family"] == "QUALIFIER"),
        "retired": len(rev11["retired"]),
    }
    undeclared = sorted(set(measured) - set(declared))
    unmeasured = sorted(set(declared) - set(measured))
    drift = {k: {"declared": declared[k], "measured": measured[k]}
             for k in sorted(set(declared) & set(measured))
             if declared[k] != measured[k]}
    _assert(not drift and not undeclared and not unmeasured,
            "6. Declared counts equal measured counts, all nine keys",
            "drift {} / undeclared {} / unmeasured {}".format(
                drift, undeclared, unmeasured))

    # 7 -- governing spec pointer moved
    _assert(rev11["governing_spec"] == _POR_REV11_REL,
            "7. Rev1.1 governing_spec points at POR Rev1.1",
            "got {!r}".format(rev11["governing_spec"]))

    # 8 -- retired collection size
    retired = rev11["retired"]
    _assert(len(retired) == 4,
            "8. Retired collection count is 4",
            "got {}".format(len(retired)))

    # 9 -- no retired catalog number reappears among the active definitions
    retired_nums = {r["catalog_number"] for r in retired
                    if r["catalog_number"] is not None}
    active_nums = {d["catalog_number"] for d in defs11}
    collision = sorted(retired_nums & active_nums)
    _assert(not collision,
            "9. No retired catalog number appears in active definitions",
            "collision {}".format(collision))

    # 10 -- POR section 10 and Rev1.1 JSON rollover parity. One assertion,
    #       every problem collected.
    issues = []

    por_rows, parse_errors = _parse_por_section_10(_POR_REV11)
    issues.extend(parse_errors)

    if len(por_rows) != 94:
        issues.append("POR row count is {}, expected 94".format(len(por_rows)))

    json_ro = {d["catalog_number"]: bool(d["rollover_eligible"]) for d in defs11}
    if len(json_ro) != len(defs11):
        issues.append("JSON catalog numbers not unique: {} unique across {}".format(
            len(json_ro), len(defs11)))

    # POR uniqueness is enforced inside the parser; a duplicate is reported
    # there and the row is dropped, so the count check above also fires.

    missing = sorted(set(json_ro) - set(por_rows))
    extra = sorted(set(por_rows) - set(json_ro))
    if missing:
        issues.append("absent from POR: {}".format(missing))
    if extra:
        issues.append("absent from JSON: {}".format(extra))

    row_mismatch = sorted(n for n in set(json_ro) & set(por_rows)
                          if json_ro[n] != por_rows[n])
    if row_mismatch:
        issues.append("row-level rollover mismatch at {}".format(row_mismatch))

    por_total = sum(1 for v in por_rows.values() if v)
    if por_total != 21:
        issues.append("POR rollover total is {}, expected 21".format(por_total))

    json_total = sum(1 for v in json_ro.values() if v)
    if json_total != 21:
        issues.append("JSON rollover total is {}, expected 21".format(json_total))

    flagged = {n: por_rows.get(n) for n in (84, 87)}
    if flagged != {84: True, 87: True}:
        issues.append("POR #84/#87 rollover cells are {}, expected both True".format(
            flagged))

    _assert(not issues,
            "10. POR section 10 and Rev1.1 JSON have complete rollover parity",
            "; ".join(issues))

    print("\n10 assertions, {} failures".format(len(_failures)))
    if _failures:
        for f in _failures:
            print("  FAILED: {}".format(f))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
