"""
test_pool_build_week_slate.py — step 7, the pure build_week_slate selector.

No database. No Session. No network.

DUAL ROLE. Imported/run normally it is the test suite. Run with
POOL_SLATE_CHILD=1 in the environment it prints one slate as JSON and exits —
that is how S1 proves cross-process determinism under different PYTHONHASHSEED
values, which cannot be observed from inside a single process.

Runs as: python test_pool_build_week_slate.py
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from betting.pool_rotation import (  # noqa: E402
    Continuation, EligibleDefinition, PoolRotationError,
    PHASE_POSTSEASON, PHASE_REGULAR,
    DEFAULT_SCOPE_MIX, SCOPE_MATCHUP, SCOPE_TEAM,
    REASON_MISSING_SCOPE, REASON_TOO_MANY_CONTINUATIONS,
    build_week_slate as _selector, digest_for, fresh_allocation,
    rank_definitions,
)

LEAGUE_ID, SEASON, CYCLE = 7, 2026, 3


def build_week_slate(**kwargs):
    """The selector with POR Rev 1.4 §4.2's scope composition OFF by default.

    S1-S12 below measure the ORDERING COMPATIBILITY CONTRACT — the digest
    serialization, the tie-breakers, carried-key subtraction, caller-order
    independence, reset signalling. A scope quota is a second, independent rule
    layered on top of that ordering, and leaving it on would mean every one of
    those assertions was measuring two things at once: a failure could be the
    ranking OR the composition, and the suite could not say which.

    So the ordering sections opt out explicitly, exactly as the selector's own
    signature invites (`scope_mix=None` is "rank without a quota"), and the
    composition gets its own section — S13 — which calls the real selector with
    its real default and asserts the mix. Nothing here weakens the default: a
    caller who passes nothing still gets 3 TEAM + 1 MATCHUP, and S13 proves it.
    """
    kwargs.setdefault("scope_mix", None)
    return _selector(**kwargs)


def _defs(n, start=1):
    """n eligible definitions with stable keys and catalog numbers.

    UNSCOPED, deliberately. These feed the ordering sections, which run with the
    composition off; a scope they never consult would be a fact the fixture
    asserts and nothing reads. S13 builds its own scoped fixture.
    """
    return [EligibleDefinition(definition_key=f"def_{i:03d}", catalog_number=i)
            for i in range(start, start + n)]


def _scoped(team, matchup):
    """`team` TEAM definitions then `matchup` MATCHUP ones, distinct keys.

    Catalog numbers are contiguous across both blocks so the scope cannot be
    inferred from the number — a composition that accidentally worked by
    ordering rather than by scope would still fail here.
    """
    rows = [EligibleDefinition(f"t_{i:03d}", i, SCOPE_TEAM)
            for i in range(1, team + 1)]
    rows += [EligibleDefinition(f"m_{i:03d}", team + i, SCOPE_MATCHUP)
             for i in range(1, matchup + 1)]
    return rows


def _scopes(res):
    """The slate's scopes, recovered from the fixture's key prefix."""
    return [SCOPE_TEAM if e.definition_key.startswith("t_") else SCOPE_MATCHUP
            for e in res.slate]


# ── child mode: emit one slate as JSON, for the S1 subprocess probe ──────────
if os.environ.get("POOL_SLATE_CHILD") == "1":
    res = build_week_slate(
        league_id=LEAGUE_ID, season=SEASON, week=5, rotation_cycle=CYCLE,
        phase=PHASE_REGULAR, eligible=_defs(12), continuations=(),
        used_fresh_keys=(),
    )
    print(json.dumps([[e.slot, e.definition_key, e.is_continuation]
                      for e in res.slate], separators=(",", ":")))
    raise SystemExit(0)


_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _keys(res):
    return [e.definition_key for e in res.slate]


def _slots(res):
    return [e.slot for e in res.slate]


def main() -> None:
    # ================================================================
    # S1 — CROSS-PROCESS DETERMINISM.
    # Under SHA-256 digest ranking this passes BY CONSTRUCTION. The test is a
    # REGRESSION GUARD: if anyone ever replaces the ranking with
    # random.shuffle, sorted(key=hash), or set-iteration order, this is the
    # only test in the suite that catches it, because builtin hash() is salted
    # per process and the damage is invisible inside a single run.
    # DO NOT DELETE THIS AS REDUNDANT.
    # ================================================================
    print("\n-- S1: cross-process determinism --")

    outs = []
    for seed in ("0", "1", "random"):
        env = dict(os.environ)
        env["POOL_SLATE_CHILD"] = "1"
        env["PYTHONHASHSEED"] = seed
        p = subprocess.run([sys.executable, os.path.abspath(__file__)],
                           env=env, capture_output=True, text=True, timeout=60)
        outs.append((seed, p.returncode, p.stdout.strip(), p.stderr.strip()))

    all_ok = all(rc == 0 for _, rc, _, _ in outs)
    distinct = {o for _, _, o, _ in outs}
    _assert("0: identical slate across PYTHONHASHSEED=0, 1 and random "
            "(regression guard against a future PRNG/hash-based ordering)",
            all_ok and len(distinct) == 1 and outs[0][2] != "",
            detail=f"exit codes={[rc for _, rc, _, _ in outs]} "
                   f"distinct outputs={len(distinct)} "
                   f"slate={outs[0][2][:120]}"
                   + (f" stderr={outs[0][3][:200]}" if not all_ok else ""))

    # ================================================================
    # S2 — WEEK IS NOT IN THE DIGEST.
    # Built precisely: week N draws from a cycle with NO prior fresh use; the
    # keys it consumed are then passed as used_fresh_keys for week N+1. The
    # underlying cycle ORDERING must be unchanged, and week N+1 must consume
    # the NEXT entries in that same ordering. Merely changing `week` while
    # passing identical used-state would not discriminate.
    # ================================================================
    print("\n-- S2: week is not in the digest --")

    pool12 = _defs(12)
    ordering = [d.definition_key for d in rank_definitions(
        pool12, league_id=LEAGUE_ID, season=SEASON, rotation_cycle=CYCLE)]

    wk_n = build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=5,
                            rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                            eligible=pool12, used_fresh_keys=())
    consumed_n = _keys(wk_n)

    wk_n1 = build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=6,
                             rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                             eligible=pool12, used_fresh_keys=consumed_n)
    consumed_n1 = _keys(wk_n1)

    # The ordering must be identical when recomputed at week 6...
    ordering_at_6 = [d.definition_key for d in rank_definitions(
        pool12, league_id=LEAGUE_ID, season=SEASON, rotation_cycle=CYCLE)]
    _assert("1: the cycle ordering is identical regardless of week",
            ordering == ordering_at_6,
            detail=f"first 6 of ordering={ordering[:6]}")
    _assert("2: week N consumed the FIRST 4 entries of the cycle ordering",
            consumed_n == ordering[:4],
            detail=f"consumed={consumed_n} expected={ordering[:4]}")
    _assert("3: week N+1 consumed the NEXT 4 entries of the SAME ordering",
            consumed_n1 == ordering[4:8],
            detail=f"consumed={consumed_n1} expected={ordering[4:8]}")

    # ================================================================
    # S3 — SLOT POSITIONS for carries. Assert POSITION, not presence: a
    # presence-only assertion passes under an implementation that appends
    # carries last, which POR §4 line 112 forbids.
    # ================================================================
    print("\n-- S3: carries occupy leading slot positions --")

    for s3_idx, n_carry in enumerate((1, 2, 4), start=4):
        carries = [Continuation(definition_key=f"carry_{i}", prior_slot=i)
                   for i in range(1, n_carry + 1)]
        res = build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=9,
                               rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                               eligible=_defs(12), continuations=carries,
                               used_fresh_keys=())
        positions = {e.definition_key: e.slot for e in res.slate
                     if e.is_continuation}
        expect = {f"carry_{i}": i for i in range(1, n_carry + 1)}
        _assert(f"{s3_idx}: {n_carry} carry/carries occupy slots "
                f"{list(range(1, n_carry + 1))} exactly",
                positions == expect and len(res.slate) == 4,
                detail=f"carry slots={positions} expected={expect} "
                       f"slate size={len(res.slate)}")

    # ================================================================
    # S4 — MULTI-CARRY ORDER, including a prior_slot tie broken by
    # definition_key. Assert exact slot assignment.
    # ================================================================
    print("\n-- S4: multi-carry ordering, prior_slot tie broken by key --")

    carries = [
        Continuation(definition_key="zulu",  prior_slot=3),
        Continuation(definition_key="bravo", prior_slot=1),
        Continuation(definition_key="alpha", prior_slot=3),   # ties with zulu
    ]
    res = build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=9,
                           rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                           eligible=_defs(12), continuations=carries,
                           used_fresh_keys=())
    got = [(e.slot, e.definition_key) for e in res.slate if e.is_continuation]
    _assert("7: carries ordered by prior_slot ASC then definition_key ASC",
            got == [(1, "bravo"), (2, "alpha"), (3, "zulu")],
            detail=f"got={got} expected=[(1,'bravo'),(2,'alpha'),(3,'zulu')]")

    # ================================================================
    # S5 — CARRIED-KEY SUBTRACTION. The discriminating fixture.
    # Built so that WITHOUT subtraction the carried key would be drawn: the
    # carried definition is chosen to sit inside the top fresh_slots of the
    # UN-subtracted ranking. Proven to bite via rank_definitions() on the
    # un-subtracted candidate set — no source mutation, no test-only branch
    # inside production code.
    # ================================================================
    print("\n-- S5: carried-key subtraction (discriminating) --")

    pool = _defs(12)
    unsubtracted = rank_definitions(pool, league_id=LEAGUE_ID, season=SEASON,
                                    rotation_cycle=CYCLE)
    # Carry the definition that ranks FIRST in the un-subtracted ordering: with
    # 1 carry there are 3 fresh slots, so without subtraction it is certain to
    # be drawn again.
    carried_key = unsubtracted[0].definition_key
    carries = [Continuation(definition_key=carried_key, prior_slot=1)]

    res = build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=9,
                           rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                           eligible=pool, continuations=carries,
                           used_fresh_keys=())
    keys = _keys(res)

    _assert("8: the fixture BITES — without subtraction the carried key would "
            "rank inside the fresh draw window",
            unsubtracted[0].definition_key == carried_key
            and carried_key in [d.definition_key for d in unsubtracted[:3]],
            detail=f"carried={carried_key!r}; un-subtracted top-3="
                   f"{[d.definition_key for d in unsubtracted[:3]]} "
                   f"(a collision was genuinely available)")
    _assert("9: the carried definition appears in the slate EXACTLY once",
            keys.count(carried_key) == 1,
            detail=f"count={keys.count(carried_key)} slate={keys}")
    _assert("10: exactly four slots are still returned",
            len(res.slate) == 4, detail=f"slate size={len(res.slate)}")
    expected_fresh = [d.definition_key for d in unsubtracted
                      if d.definition_key != carried_key][:3]
    _assert("11: the replacement is the NEXT valid definition in digest order",
            [e.definition_key for e in res.slate if not e.is_continuation]
            == expected_fresh,
            detail=f"fresh={[e.definition_key for e in res.slate if not e.is_continuation]} "
                   f"expected={expected_fresh}")

    # ================================================================
    # S6 — SLATE COMPLETENESS.
    # ================================================================
    print("\n-- S6: slate completeness --")

    res = build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=9,
                           rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                           eligible=_defs(12),
                           continuations=[Continuation("carry_x", 2)],
                           used_fresh_keys=())
    ks, sl = _keys(res), _slots(res)
    _assert("12: exactly 4 entries, slots exactly [1,2,3,4], no gaps, no "
            "duplicate slots, no duplicate definition keys",
            len(res.slate) == 4 and sl == [1, 2, 3, 4]
            and len(set(sl)) == 4 and len(set(ks)) == 4,
            detail=f"slots={sl} keys={ks}")

    # ================================================================
    # S7 — INSUFFICIENT FRESH DEFINITIONS -> reset signalled, not performed.
    # ================================================================
    print("\n-- S7: reset signalling --")

    small = _defs(5)
    used = [d.definition_key for d in small[:3]]      # only 2 left, need 4
    res = build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=9,
                           rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                           eligible=small, used_fresh_keys=used)
    rc = res.reset_context
    _assert("13: insufficient fresh candidates signals a reset and returns no slate",
            res.reset_required is True and res.slate == () and rc is not None,
            detail=f"reset_required={res.reset_required} slate={res.slate}")
    _assert("14: the reset context carries everything §C3's audit row needs",
            rc is not None and rc.league_id == LEAGUE_ID and rc.season == SEASON
            and rc.exhausted_cycle == CYCLE and rc.opened_week == 9
            and rc.eligible_set_size == 5 and rc.fresh_slots_required == 4
            and rc.fresh_candidates_available == 2,
            detail=f"{rc}")

    sufficient = build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=9,
                                  rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                                  eligible=_defs(12), used_fresh_keys=())
    _assert("15: a sufficient fresh set does NOT signal a reset",
            sufficient.reset_required is False
            and sufficient.reset_context is None
            and len(sufficient.slate) == 4,
            detail=f"reset_required={sufficient.reset_required}")

    # ================================================================
    # S8 — CALLER INPUT ORDER INDEPENDENCE, and no eligibility decision.
    # ================================================================
    print("\n-- S8: input order independence --")

    base = _defs(12)
    forward = _keys(build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=9,
                                     rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                                     eligible=base, used_fresh_keys=()))
    reversed_ = _keys(build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=9,
                                       rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                                       eligible=list(reversed(base)),
                                       used_fresh_keys=()))
    # A fixed, non-random permutation — a shuffled order that is itself
    # reproducible, so a failure here is reproducible too.
    perm = [base[i] for i in (7, 0, 11, 3, 9, 1, 5, 10, 2, 8, 4, 6)]
    shuffled = _keys(build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=9,
                                      rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                                      eligible=perm, used_fresh_keys=()))
    _assert("16: slate is identical for forward, reversed and permuted input order",
            forward == reversed_ == shuffled,
            detail=f"forward={forward} reversed={reversed_} permuted={shuffled}")

    other = _defs(12, start=100)
    other_slate = _keys(build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=9,
                                         rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                                         eligible=other, used_fresh_keys=()))
    _assert("17: the selector ranks exactly what it was given and makes no "
            "eligibility decision of its own",
            set(other_slate).issubset({d.definition_key for d in other})
            and not set(other_slate) & set(forward),
            detail=f"slate from a disjoint eligible set={other_slate}")

    # ================================================================
    # Invariant violations and phase handling.
    # ================================================================
    print("\n-- invariants --")

    raised = None
    try:
        build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=9,
                         rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                         eligible=_defs(12),
                         continuations=[Continuation(f"c{i}", i) for i in range(1, 6)],
                         used_fresh_keys=())
    except PoolRotationError as exc:
        raised = exc
    _assert("18: more continuations than slots raises (neither §E nor the POR "
            "defines it; refused rather than truncating a live carry)",
            raised is not None and raised.reason == REASON_TOO_MANY_CONTINUATIONS,
            detail=str(raised) if raised else "did not raise")

    four = [Continuation(definition_key=f"carry_{i}", prior_slot=i)
            for i in range(1, 5)]
    res = build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=9,
                           rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                           eligible=_defs(12), continuations=four,
                           used_fresh_keys=())
    _assert("19: four carries fill the slate with zero fresh draws and no fifth slot",
            len(res.slate) == 4 and all(e.is_continuation for e in res.slate)
            and res.reset_required is False,
            detail=f"slots={_slots(res)} all_continuations="
                   f"{all(e.is_continuation for e in res.slate)}")

    # POSTSEASON does not cycle: an insufficient subset raises rather than
    # silently signalling a regular-season reset.
    raised = None
    try:
        build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=16,
                         rotation_cycle=CYCLE, phase=PHASE_POSTSEASON,
                         eligible=_defs(2), used_fresh_keys=())
    except PoolRotationError as exc:
        raised = exc
    _assert("20: POSTSEASON with an insufficient subset does not signal a "
            "regular-season reset", raised is not None,
            detail=str(raised) if raised else "did not raise")

    # Digest contract: types are load-bearing.
    # GOLDEN VALUE. The expected payload and its sha256 were constructed
    # independently of digest_for(), so this is not circular. It breaks if the
    # key names, key order, separators, ascii flag or field types ever change —
    # which is exactly what the compatibility contract forbids.
    _GOLDEN_PAYLOAD = ('{"definition_key":"most_total_touchdowns",'
                       '"league_id":7,"rotation_cycle":3,"season":2026}')
    _GOLDEN_SHA256 = "c72a5aa4f45a4a0f1501b5058393c36110eabf1b68e77cf753b6b525a9c1a9b8"
    import hashlib as _hashlib
    _assert("21: digest matches the pinned golden value for the documented "
            "serialization (breaks if key order, separators, ascii flag or "
            "field types change)",
            digest_for("most_total_touchdowns", 7, 2026, 3).hex() == _GOLDEN_SHA256
            and _hashlib.sha256(_GOLDEN_PAYLOAD.encode("utf-8")).hexdigest()
            == _GOLDEN_SHA256,
            detail=f"digest={digest_for('most_total_touchdowns', 7, 2026, 3).hex()[:24]}... "
                   f"golden={_GOLDEN_SHA256[:24]}...")
    _assert("22: digest is sensitive to every field it serializes",
            len({digest_for("k", 1, 2026, 1), digest_for("k2", 1, 2026, 1),
                 digest_for("k", 2, 2026, 1), digest_for("k", 1, 2027, 1),
                 digest_for("k", 1, 2026, 2)}) == 5,
            detail="changing key, league, season or cycle each yields a distinct digest")
    _assert("23: digest ignores week entirely (week is not a parameter)",
            digest_for("k", LEAGUE_ID, SEASON, CYCLE)
            == digest_for("k", LEAGUE_ID, SEASON, CYCLE),
            detail="digest_for takes no week argument by construction")

    # ── S13 · POR Rev 1.4 §4.2 — the weekly scope composition ─────────────
    #
    # THIS SECTION CALLS THE REAL SELECTOR, not the suite's `scope_mix=None`
    # wrapper. Everything above measures the ordering contract with the
    # composition deliberately off; this measures the composition, and it does
    # so through `_selector` with NO scope_mix argument at all — so it is also
    # the assertion that the governed mix is what a caller who passes nothing
    # actually gets.
    print("\n-- S13: scope composition, POR Rev 1.4 §4.2 --")

    _assert("25: the governed mix is 3 TEAM + 1 MATCHUP, in that priority order",
            DEFAULT_SCOPE_MIX == ((SCOPE_TEAM, 3), (SCOPE_MATCHUP, 1)),
            detail=str(DEFAULT_SCOPE_MIX))

    # The real Gate-1 shape: 35 TEAM, 29 MATCHUP.
    catalog_shaped = _scoped(35, 29)

    composed = _selector(league_id=LEAGUE_ID, season=SEASON, week=5,
                         rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                         eligible=catalog_shaped, used_fresh_keys=())

    # MEASURED ACROSS MANY LEAGUES AND CYCLES, not on one fixture. A single
    # draw proves nothing either way: an unconstrained ranking lands on 3/1 by
    # chance often enough that one sample could pass with the composition
    # switched off. So both halves are swept over the same 60 (league, cycle)
    # pairs — the composition must hold on EVERY one, and the unconstrained
    # ranking must fail on SOME, which is the defect §4.2 exists to correct.
    _sweep = [(lg, cyc) for lg in range(1, 21) for cyc in range(1, 4)]

    def _shape(lg, cyc, **kw):
        return _scopes(_selector(
            league_id=lg, season=SEASON, week=5, rotation_cycle=cyc,
            phase=PHASE_REGULAR, eligible=catalog_shaped,
            used_fresh_keys=(), **kw))

    _off_mix = [(lg, cyc, m.count(SCOPE_TEAM), m.count(SCOPE_MATCHUP))
                for lg, cyc in _sweep
                for m in [_shape(lg, cyc)]
                if (m.count(SCOPE_TEAM), m.count(SCOPE_MATCHUP)) != (3, 1)]
    _assert("26: EVERY default four-slot REGULAR draw is 3 TEAM + 1 MATCHUP, "
            f"across {len(_sweep)} league/cycle pairs",
            not _off_mix,
            detail=str(_off_mix[:3]) if _off_mix
                   else f"{len(_sweep)}/{len(_sweep)} drew 3 TEAM + 1 MATCHUP")

    # THE CONTROL, and the measurement the ruling was made on.
    _uncomposed = [(_shape(lg, cyc, scope_mix=None).count(SCOPE_TEAM))
                   for lg, cyc in _sweep]
    _uncomposed_31 = sum(1 for t in _uncomposed if t == 3)
    _assert("27: the unconstrained ranking does NOT hold the mix, so #26 is "
            "the composition and not the fixture",
            _uncomposed_31 < len(_sweep),
            detail=f"unconstrained held 3 TEAM on {_uncomposed_31}/"
                   f"{len(_sweep)} pairs; most common shape was "
                   f"{max(set(_uncomposed), key=_uncomposed.count)} TEAM")

    _assert("28: a composed draw is still deterministic — same inputs, same "
            "slate",
            _keys(_selector(league_id=LEAGUE_ID, season=SEASON, week=5,
                            rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                            eligible=catalog_shaped, used_fresh_keys=()))
            == _keys(composed))

    _assert("29: caller order cannot influence a composed draw either",
            _keys(_selector(league_id=LEAGUE_ID, season=SEASON, week=5,
                            rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                            eligible=list(reversed(catalog_shaped)),
                            used_fresh_keys=())) == _keys(composed))

    _assert("30: slots are still laid out in GLOBAL rank order — the "
            "composition chooses membership, not order",
            [e.definition_key for e in composed.slate]
            == [d.definition_key for d in rank_definitions(
                [d for d in catalog_shaped
                 if d.definition_key in set(_keys(composed))],
                league_id=LEAGUE_ID, season=SEASON, rotation_cycle=CYCLE)],
            detail=str(_keys(composed)))

    _assert("31: no definition appears twice in a composed slate",
            len(set(_keys(composed))) == 4, detail=str(_keys(composed)))

    # ── the deficit table of §4.2.1, carry configuration by carry
    #    configuration. `fresh_allocation` is public precisely so this can be
    #    read directly rather than inferred from four finished slates.
    _allocations = {
        (): ((SCOPE_TEAM, 3), (SCOPE_MATCHUP, 1)),
        (SCOPE_TEAM,): ((SCOPE_TEAM, 2), (SCOPE_MATCHUP, 1)),
        (SCOPE_MATCHUP,): ((SCOPE_TEAM, 3), (SCOPE_MATCHUP, 0)),
        (SCOPE_MATCHUP, SCOPE_MATCHUP): ((SCOPE_TEAM, 2), (SCOPE_MATCHUP, 0)),
        (SCOPE_TEAM, SCOPE_TEAM, SCOPE_TEAM): ((SCOPE_TEAM, 0),
                                               (SCOPE_MATCHUP, 1)),
        (SCOPE_TEAM,) * 4: ((SCOPE_TEAM, 0), (SCOPE_MATCHUP, 0)),
    }
    _bad = [
        (carried, fresh_allocation(DEFAULT_SCOPE_MIX, list(carried),
                                   4 - len(carried)), expected)
        for carried, expected in _allocations.items()
        if fresh_allocation(DEFAULT_SCOPE_MIX, list(carried),
                            4 - len(carried)) != expected
    ]
    _assert("32: the §4.2.1 deficit table holds in every carry configuration",
            not _bad, detail=str(_bad) if _bad else "6 configurations checked")

    # A carry is not displaced, and the fresh draws fill the deficit around it.
    carried_matchup = _scoped(35, 29)
    carry_key = "m_001"
    with_carry = _selector(
        league_id=LEAGUE_ID, season=SEASON, week=6, rotation_cycle=CYCLE,
        phase=PHASE_REGULAR,
        eligible=[d for d in carried_matchup if d.definition_key != carry_key],
        continuations=[Continuation(carry_key, 1, SCOPE_MATCHUP)],
        used_fresh_keys=())
    carry_mix = _scopes(with_carry)
    _assert("33: a carried MATCHUP takes the MATCHUP slot and the three fresh "
            "draws are all TEAM",
            with_carry.slate[0].definition_key == carry_key
            and with_carry.slate[0].is_continuation
            and carry_mix.count(SCOPE_TEAM) == 3
            and carry_mix.count(SCOPE_MATCHUP) == 1,
            detail=f"{_keys(with_carry)} -> {carry_mix.count(SCOPE_TEAM)} TEAM")

    # §4.2.3 — the slate is filled to four even when a scope is exhausted.
    starved = _selector(league_id=LEAGUE_ID, season=SEASON, week=7,
                        rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                        eligible=_scoped(1, 9), used_fresh_keys=())
    starved_mix = _scopes(starved)
    _assert("34: a scope that cannot fill its share falls through to the other "
            "rather than shortening the slate (§4.2.3)",
            len(starved.slate) == 4 and starved.reset_required is False
            and starved_mix.count(SCOPE_TEAM) == 1,
            detail=f"{starved_mix.count(SCOPE_TEAM)} TEAM / "
                   f"{starved_mix.count(SCOPE_MATCHUP)} MATCHUP, "
                   f"{len(starved.slate)} slots")

    _assert("35: cross-scope fallback is deterministic too",
            _keys(_selector(league_id=LEAGUE_ID, season=SEASON, week=7,
                            rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                            eligible=_scoped(1, 9), used_fresh_keys=()))
            == _keys(starved))

    # §4.2.3 — exhaustion is still TOTAL, never per scope. Three candidates
    # cannot fill four fresh slots whatever their scopes are.
    exhausted = _selector(league_id=LEAGUE_ID, season=SEASON, week=8,
                          rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                          eligible=_scoped(2, 1), used_fresh_keys=())
    _assert("36: a reset is signalled on TOTAL exhaustion, not on a scope "
            "running dry",
            exhausted.reset_required is True
            and starved.reset_required is False,
            detail=f"3 candidates -> reset={exhausted.reset_required}; "
                   f"10 candidates, 1 TEAM -> reset={starved.reset_required}")

    # §4.2.5 — the postseason is excluded, and so is a slot count the mix was
    # not written for.
    post = _selector(league_id=LEAGUE_ID, season=SEASON, week=16,
                     rotation_cycle=CYCLE, phase=PHASE_POSTSEASON,
                     eligible=_scoped(35, 29), used_fresh_keys=())
    _assert("37: POSTSEASON is not composed — it ranks as it always did "
            "(§4.2.5)",
            _keys(post) == _keys(_selector(
                league_id=LEAGUE_ID, season=SEASON, week=16,
                rotation_cycle=CYCLE, phase=PHASE_POSTSEASON,
                eligible=_scoped(35, 29), used_fresh_keys=(), scope_mix=None)))

    _assert("38: a slot count the mix was not written for is NOT rescaled — it "
            "gets the pre-Rev-1.4 ranking (§4.2.5)",
            _keys(_selector(league_id=LEAGUE_ID, season=SEASON, week=5,
                            rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                            eligible=_scoped(35, 29), used_fresh_keys=(),
                            slot_count=6))
            == _keys(_selector(league_id=LEAGUE_ID, season=SEASON, week=5,
                               rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                               eligible=_scoped(35, 29), used_fresh_keys=(),
                               slot_count=6, scope_mix=None)))

    # An unscoped candidate in a composed draw is REFUSED, never defaulted —
    # defaulting would file every unscoped definition under one scope and
    # quietly change the mix.
    raised = None
    try:
        _selector(league_id=LEAGUE_ID, season=SEASON, week=5,
                  rotation_cycle=CYCLE, phase=PHASE_REGULAR,
                  eligible=_defs(12), used_fresh_keys=())
    except PoolRotationError as exc:
        raised = exc
    _assert("39: a composed draw refuses an unscoped candidate rather than "
            "guessing its scope",
            raised is not None and raised.reason == REASON_MISSING_SCOPE,
            detail=str(raised)[:90] if raised else "did not raise")

    # ── the artifact and the constant may not drift ────────────────────────
    from betting.pool_catalog import load_catalog
    _cat = load_catalog()
    _assert("40: the governed catalog's weekly_slate_composition IS "
            "DEFAULT_SCOPE_MIX (load_catalog refuses any other)",
            _cat.weekly_scope_mix == DEFAULT_SCOPE_MIX,
            detail=f"catalog rev {_cat.revision} carries "
                   f"{_cat.weekly_scope_mix}")

    # Purity of the selector module: code only, comments and docstrings stripped.
    import io
    import tokenize
    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "betting", "pool_rotation.py")
    with open(src_path, encoding="utf-8") as fh:
        raw = fh.read()
    code = " ".join(t.string for t in tokenize.generate_tokens(io.StringIO(raw).readline)
                    if t.type not in (tokenize.COMMENT, tokenize.STRING))
    banned = ["hash", "random", "shuffle", "Session", "query", "requests",
              "urllib", "sqlalchemy", "pickle", "repr", "eval", "exec",
              "datetime", "time"]
    hits = [b for b in banned if b in code.split()]
    _assert("24: selector CODE uses no builtin hash, no randomness, no ORM, no "
            "network, no clock (comments and docstrings stripped via tokenize)",
            not hits, detail=f"banned identifiers in code: {hits}" if hits
                             else "none present")


if __name__ == "__main__":
    main()
    print()
    if _failures:
        print(f"RESULT: {len(_failures)} assertion(s) FAILED")
        for label in _failures:
            print(f"  - {label}")
        sys.exit(1)
    print("RESULT: all build_week_slate assertions PASSED")
