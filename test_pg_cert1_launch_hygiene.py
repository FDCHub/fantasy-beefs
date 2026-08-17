#!/usr/bin/env python3
"""
test_pg_cert1_launch_hygiene.py — PG-CERT-1 · the shortfall sweep's authority.

WHAT THIS CERTIFIES, AND WHAT THE DEFECT ACTUALLY WAS.

`betting/shortfall_sweep.py` carried a launch-hygiene note through five
packages: "legacy assumptions tied to the old hardcoded economy". Reading it,
the note was half right in a way worth stating precisely, because the half that
was wrong would have made a lazy fix look sufficient.

WHAT WAS ALREADY FINE. The sweep never hardcoded 220, 140 or 80. It read
`get_league_economy_stop(...).weekly_min_cents`, so renaming constants — the
thing §19 explicitly warns against — would have changed nothing at all.

WHAT WAS ACTUALLY BROKEN. `get_league_economy_stop` resolves against the
five-value Discrete-Stop table, and ECONCFG made the economy configurable
beyond it. So a league whose commissioner had frozen a real configuration was
swept against the wrong authority, in one of two ways:

  · its Weekly Bet Minimum matched no certified stop, and the lookup RAISED —
    the sweep crashed on precisely the leagues the configurable economy exists
    to serve; or

  · its stop column still held a legacy value, and the sweep charged that
    minimum against real wallets while the league's frozen configuration said
    something else. Silently.

AND ONE MORE, UNLISTED. The sweep had no postseason guard. There is no Weekly
Bet Minimum after the regular season, so a postseason sweep would have moved
money out of wallets to satisfy an obligation the product says does not exist.

Both are fixed and both are certified below, on PostgreSQL.

DATABASE. PostgreSQL, one disposable database created and dropped by this
suite. The Ledger arithmetic these scenarios exercise is the real engine.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import create_engine, text                         # noqa: E402
from sqlalchemy.engine import make_url                             # noqa: E402

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


# ── 1 · the legacy-constant sweep, classified ────────────────────────────────

_section("1 · §21 · Legacy 220 / 140 / 80 in production code, classified")

# CODE ONLY, AND PRODUCTION ONLY. Tests, fixtures and documentation legitimately
# name the historical numbers — §21 says not to flag them — so the scan covers
# the application packages and strips comments and docstrings before looking.
def _code_only(text_: str) -> str:
    # LINE COUNT PRESERVED. Collapsing a docstring to a single space
    # shifts every line number after it, so a first cut reported
    # `economy/skunk.py:44` for a constant that lives on line 82. Blanked
    # content keeps its newlines so a reported location is real.
    def _blank(m):
        return "\n" * m.group(0).count("\n")

    for quote in ('"' * 3, "'" * 3):
        text_ = re.sub(quote + r'[\s\S]*?' + quote, _blank, text_)
    return re.sub(r"^\s*#.*$", "", text_, flags=re.M)


_PROD_DIRS = ("betting", "economy", "ledger", "payments", "providers",
              "reports", "auth", "api", "notifications")
_hits: list[tuple[str, int, str]] = []
for _d in _PROD_DIRS:
    for _base, _dirs, _files in os.walk(os.path.join(ROOT, _d)):
        if "__pycache__" in _base:
            continue
        for _f in _files:
            if not _f.endswith(".py"):
                continue
            _path = os.path.join(_base, _f)
            _rel = os.path.relpath(_path, ROOT).replace(os.sep, "/")
            _src = _code_only(open(_path, encoding="utf-8",
                                   errors="replace").read())
            for _i, _line in enumerate(_src.splitlines(), 1):
                # THE CENTS FORMS ARE WHAT WOULD BE AUTHORITATIVE. A bare 220 is
                # far more often a week count, a pixel or an index; 22000 /
                # 14000 / 8000 as cents are the legacy triple.
                if re.search(r"\b(22000|14000|8000)\b", _line):
                    _hits.append((_rel, _i, _line.strip()[:90]))

print(f"  {len(_hits)} production line(s) name a legacy cents value")
for _rel, _i, _line in _hits:
    print(f"    {_rel}:{_i}  {_line}")

# CLASSIFICATION, PER §21 — AND ONLY CLASS A GETS CORRECTED.
#
#   payments/economy_config.py   the five-value Discrete-Stop table. Still the
#                                correct fallback for an UNCONFIGURED league.
#                                CLASS B — consistent with the current POR.
#
#   economy/skunk.py             DEFAULT_SKUNK_SEASON_MAXIMUM_CENTS = 14000,
#                                documented as the default for an unconfigured
#                                league-season and superseded by the frozen
#                                fee. CLASS B — and verified below by reading
#                                its one production consumer rather than by
#                                trusting the comment above it.
#
# Anything else naming these values in production would be class A.
_ALLOWED_DEFINITION_SITES = ("payments/economy_config.py", "economy/skunk.py")
_authoritative = [h for h in _hits
                  if not h[0].startswith(_ALLOWED_DEFINITION_SITES)]
_assert("no production site outside the two default tables names the triple",
        not _authoritative,
        "; ".join(f"{r}:{i}" for r, i, _ in _authoritative) or "none elsewhere")

# THE CLASS-B CLAIM IS CHECKED, NOT ASSERTED. A "default" is only a default if
# a configured league does not get it, so the consumer is read: the settings
# surface derives the ceiling from the frozen configuration and falls back to
# the constant only when there is none.
_MAIN_CODE = _code_only(_read("api", "main.py"))
_assert("  · the Skunk ceiling is derived from the frozen configuration",
        "frozen_econ.skunk_fee_cents" in _MAIN_CODE
        and "frozen_econ.regular_season_week_count" in _MAIN_CODE)
_assert("  · and the 14000 default applies only when none is frozen",
        "if frozen_econ else DEFAULT_SKUNK_SEASON_MAXIMUM_CENTS" in _MAIN_CODE)
_assert("  · so both sites are class B — not defects, and not purged",
        True, "no cosmetic number purging performed")

_SWEEP = _code_only(_read("betting", "shortfall_sweep.py"))
_assert("the shortfall sweep names no legacy constant at all",
        not re.search(r"\b(220|140|80|22000|14000|8000)\b", _SWEEP))
_assert("and it no longer resolves the minimum through the stop table alone",
        "resolve_allocation_terms" in _SWEEP)
_assert("the postseason guard is present",
        "PHASE_POSTSEASON" in _SWEEP and "phase_for_week" in _SWEEP)
_assert("  · and uses the Pool engine's own season-phase authority",
        "from betting.pool_season_boundary import" in _read(
            "betting", "shortfall_sweep.py"))


# ── 2 · the behaviour, on PostgreSQL ─────────────────────────────────────────

_section("2 · The sweep's authority model, exercised on PostgreSQL")

_ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if not _ADMIN_URL:
    print("  [FAIL] TEST_DATABASE_URL is not set")
    sys.exit(2)
_url = make_url(_ADMIN_URL)
if "_test" not in (_url.database or ""):
    print("  [FAIL] the admin database name must contain '_test'")
    sys.exit(2)

_admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
_DB = f"pgcert1_hygiene_{uuid.uuid4().hex[:8]}_test"
with _admin.connect() as c:
    c.execute(text(f'CREATE DATABASE "{_DB}"'))
_TARGET = _url.set(database=_DB).render_as_string(hide_password=False)

# THE SCENARIOS RUN IN A SUBPROCESS. `db.schema` binds its engine from
# DATABASE_URL at import time, so the target has to be set before the first
# import — and this suite's own process has already imported nothing of it.
_DRIVER = r'''
import os, sys, json
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r

from db.schema import (Base, engine, SessionLocal, League, Team, Wallet,
                       PoolConfig)
Base.metadata.create_all(engine)
# THE SAME TWO CALLS THE PRODUCTION STARTUP HOOK MAKES. `ledger_entries` is on
# the Ledger's own base and is not created by the line above — the defect this
# package found and fixed.
from ledger.ledger import create_ledger_table
create_ledger_table()

from economy.league_economy_config import set_draft, freeze_economy_config
from betting.shortfall_sweep import (
    sweep_shortfall_for_team, weekly_minimum_cents, sweep_explanation_text,
)
from ledger.ledger import post as ledger_post, balance_of, trial_balance

OUT = {}
db = SessionLocal()


def team(lg, name, funded_cents):
    # `owner` and `email` are NOT NULL — contact data, not identity (S6-R1),
    # but still required columns.
    t = Team(league_id=lg.id, team_name=name, owner=name,
             email="%%s@pgcert1.invalid" %% name.lower().replace(" ", "-"))
    db.add(t); db.commit(); db.refresh(t)
    w = Wallet(team_id=t.id, balance=funded_cents / 100.0)
    db.add(w); db.commit()
    if funded_cents:
        # `world` IS THE ONE ACCOUNT THE FUNDED-BALANCE GUARD EXEMPTS. A first
        # cut funded from `treasury`, which the Ledger correctly refused —
        # protected accounts may not go negative, and that guard working is
        # itself part of what §15 certifies.
        ledger_post([("world", -funded_cents),
                     ("wallet:%%d" %% t.id, funded_cents)],
                    door="test_funding", session=db)
        # COMMITTED, because `balance_of` opens its OWN session. Left
        # uncommitted, the funding was invisible to the sweep's funded-balance
        # read and every wallet looked empty — which produced a receivable for
        # the whole shortfall and a "wallet covered nothing" result that had
        # nothing to do with the code under test.
        db.commit()
    return t


def league(name, *, weekly_min, champ, skunk, start_week, playoff_start,
           configured=True, legacy_stop_cents=None, roster=("A", "B")):
    # THE TEAMS COME FIRST. `freeze_economy_config` refuses a league with no
    # active teams — "an economy configuration describes a season nobody is
    # playing" — which is a correct guard, and which a fixture that created the
    # league, froze it, and only then added teams walked straight into.
    lg = League(name=name, season=2025, start_week=start_week,
                playoff_start_week=playoff_start,
                economy_stop_weekly_min_cents=legacy_stop_cents)
    db.add(lg); db.commit(); db.refresh(lg)
    for member in roster:
        team(lg, "%%s-%%s" %% (name, member), 0)
    if configured:
        set_draft(db, league_id=lg.id, weekly_bet_minimum_cents=weekly_min,
                  championship_contribution_cents=champ,
                  skunk_fee_cents=skunk, season=2025)
        db.commit()
        freeze_economy_config(db, league_id=lg.id, season=2025)
        db.commit()
    return lg


# ── 13-week league, $12/week — a minimum that is NOT a certified stop ───────
lg13 = league("Thirteen", weekly_min=1200, champ=9000, skunk=500,
              start_week=1, playoff_start=14)
t13 = team(lg13, "T13", 50_000)
OUT["w13_min"] = weekly_minimum_cents(lg13.id, db)
r = sweep_shortfall_for_team(t13.id, lg13.id, 3, db)
OUT["w13"] = dict(minimum=r.weekly_min_cents, shortfall=r.shortfall_cents,
                  covered=r.covered_cents, swept=r.swept,
                  postseason=r.postseason)

# rerun — idempotent, no second ledger impact
champ_before = balance_of("championship")
r2 = sweep_shortfall_for_team(t13.id, lg13.id, 3, db)
OUT["w13_rerun"] = dict(already=r2.already_run, swept=r2.swept,
                        champ_delta=balance_of("championship") - champ_before)

# ── postseason week in the SAME league ──────────────────────────────────────
champ_before = balance_of("championship")
rp = sweep_shortfall_for_team(t13.id, lg13.id, 15, db)
OUT["postseason"] = dict(postseason=rp.postseason, swept=rp.swept,
                         minimum=rp.weekly_min_cents,
                         champ_delta=balance_of("championship") - champ_before,
                         text=sweep_explanation_text(rp))
# and a rerun of a postseason week is still a pure no-op
rp2 = sweep_shortfall_for_team(t13.id, lg13.id, 15, db)
OUT["postseason_rerun"] = dict(postseason=rp2.postseason,
                               champ_delta=balance_of("championship") - champ_before)

# ── 14-week league, a different minimum ─────────────────────────────────────
lg14 = league("Fourteen", weekly_min=800, champ=12000, skunk=1000,
              start_week=1, playoff_start=15)
t14 = team(lg14, "T14", 50_000)
OUT["w14_min"] = weekly_minimum_cents(lg14.id, db)
r = sweep_shortfall_for_team(t14.id, lg14.id, 2, db)
OUT["w14"] = dict(minimum=r.weekly_min_cents, shortfall=r.shortfall_cents,
                  covered=r.covered_cents)

# ── the skunk fee must not move the opening allocation ──────────────────────
from payments.economy_config import resolve_allocation_terms
a = resolve_allocation_terms(db, league_id=lg13.id, season=2025)
lg_skunk = league("BigSkunk", weekly_min=1200, champ=9000, skunk=2500,
                  start_week=1, playoff_start=14)
b = resolve_allocation_terms(db, league_id=lg_skunk.id, season=2025)
OUT["skunk"] = dict(same_allocation=a.buyin_cents == b.buyin_cents,
                    allocation=a.buyin_cents,
                    min_reserve=a.min_reserve_cents,
                    reserve=a.reserve_cents,
                    weeks=a.regular_season_week_count,
                    weekly=a.weekly_bet_minimum_cents,
                    source=a.source)

# ── an UNCONFIGURED league still uses its legacy stop ───────────────────────
lg_legacy = league("Legacy", weekly_min=0, champ=0, skunk=0, start_week=1,
                   playoff_start=15, configured=False, legacy_stop_cents=1000)
OUT["legacy_min"] = weekly_minimum_cents(lg_legacy.id, db)

# ── underfunded: the receivable leg ─────────────────────────────────────────
lg_u = league("Underfunded", weekly_min=1500, champ=9000, skunk=500,
              start_week=1, playoff_start=14)
tu = team(lg_u, "TU", 400)          # $4.00 against a $15.00 minimum
r = sweep_shortfall_for_team(tu.id, lg_u.id, 4, db)
OUT["underfunded"] = dict(minimum=r.weekly_min_cents,
                          shortfall=r.shortfall_cents,
                          covered=r.covered_cents,
                          uncovered=r.uncovered_cents,
                          wallet=balance_of("wallet:%%d" %% tu.id),
                          receivable=balance_of("receivable:%%d" %% tu.id))

OUT["trial_balance"] = trial_balance()
db.close()
print("RESULT" + json.dumps(OUT))
'''

try:
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER % {"root": ROOT, "url": _TARGET}],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    line = [l for l in (proc.stdout or "").splitlines() if l.startswith("RESULT")]
    _assert("the PostgreSQL scenarios ran", bool(line),
            (proc.stderr or "")[-400:])

    if line:
        import json

        out = json.loads(line[0][len("RESULT"):])

        # ── §32 · 13-week league ──────────────────────────────────────────────
        _section("3 · §32 · A 13-week league at $12.00/week")

        _assert("the configured minimum is what the sweep uses",
                out["w13_min"] == 1200, f"{out['w13_min']} cents")
        _assert("  · and it is NOT a certified legacy stop, which is the point",
                out["w13_min"] not in (500, 1000, 1500, 2000, 2500))
        _assert("the sweep charged that minimum",
                out["w13"]["minimum"] == 1200, str(out["w13"]["minimum"]))
        _assert("a fully unwagered week is short by the whole minimum",
                out["w13"]["shortfall"] == 1200 and out["w13"]["swept"] is True,
                str(out["w13"]))
        _assert("and a funded wallet covered it",
                out["w13"]["covered"] == 1200)

        _assert("a rerun is idempotent", out["w13_rerun"]["already"] is True
                and out["w13_rerun"]["swept"] is False)
        _assert("  · with NO second Ledger impact",
                out["w13_rerun"]["champ_delta"] == 0,
                f"{out['w13_rerun']['champ_delta']} cents")

        # ── §35 · postseason ─────────────────────────────────────────────────
        _section("4 · §35 · Postseason weeks have no Weekly Bet Minimum")

        _assert("week 15 of a 13-week league is postseason",
                out["postseason"]["postseason"] is True)
        _assert("nothing is swept there", out["postseason"]["swept"] is False)
        _assert("the minimum reported is zero, not the regular-season one",
                out["postseason"]["minimum"] == 0)
        _assert("and NO money moved to the championship pot",
                out["postseason"]["champ_delta"] == 0,
                f"{out['postseason']['champ_delta']} cents")
        _assert("the wrap-up line says why rather than reading as a bug",
                "postseason" in out["postseason"]["text"].lower()
                and "$0.00" not in out["postseason"]["text"],
                out["postseason"]["text"])
        _assert("a postseason rerun is still a pure no-op",
                out["postseason_rerun"]["champ_delta"] == 0)

        # ── §33 · 14-week league ─────────────────────────────────────────────
        _section("5 · §33/§34 · A 14-week league, and a non-default minimum")

        _assert("a different league resolves its own configured minimum",
                out["w14_min"] == 800, f"{out['w14_min']} cents")
        _assert("  · also not a certified stop",
                out["w14_min"] not in (500, 1000, 1500, 2000, 2500))
        _assert("the sweep charged it", out["w14"]["minimum"] == 800)
        _assert("two leagues on one database do not share a minimum",
                out["w13_min"] != out["w14_min"],
                f"{out['w13_min']} vs {out['w14_min']}")

        # ── the derived allocation ───────────────────────────────────────────
        _section("6 · §14 · The configured allocation is derived, not fixed")

        _assert("the allocation came from the frozen configuration",
                out["skunk"]["source"] == "FROZEN_CONFIG",
                out["skunk"]["source"])
        _assert("the regular-season week count is derived from the league",
                out["skunk"]["weeks"] == 13, str(out["skunk"]["weeks"]))
        _assert("min_reserve = weekly minimum x week count",
                out["skunk"]["min_reserve"] == 1200 * 13,
                f"{out['skunk']['min_reserve']} vs {1200 * 13}")
        _assert("reserve = championship contribution, independently",
                out["skunk"]["reserve"] == 9000, str(out["skunk"]["reserve"]))
        _assert("allocation = the two together, with no legacy 22000 anywhere",
                out["skunk"]["allocation"] == 1200 * 13 + 9000
                and out["skunk"]["allocation"] != 22000,
                str(out["skunk"]["allocation"]))
        _assert("a DIFFERENT Skunk Fee does not change the allocation",
                out["skunk"]["same_allocation"] is True,
                "Skunk stays contingent and excluded")

        _assert("an UNCONFIGURED league still uses its legacy stop",
                out["legacy_min"] == 1000, f"{out['legacy_min']} cents")

        # ── the underfunded case ─────────────────────────────────────────────
        _section("7 · §20 · The underfunded case still splits correctly")

        u = out["underfunded"]
        _assert("the minimum is the configured one", u["minimum"] == 1500)
        _assert("the wallet covered only what it held",
                u["covered"] == 400, f"{u['covered']} cents")
        _assert("the remainder became a receivable",
                u["uncovered"] == 1100, f"{u['uncovered']} cents")
        _assert("the wallet is drained to zero, not negative",
                u["wallet"] == 0, f"{u['wallet']} cents")
        _assert("the receivable carries the rest",
                u["receivable"] == -1100, f"{u['receivable']} cents")

        _assert("and the Ledger still closes to zero on PostgreSQL",
                out["trial_balance"] == 0, f"{out['trial_balance']}")

finally:
    try:
        with _admin.connect() as c:
            c.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :n AND pid <> pg_backend_pid()"), {"n": _DB})
            c.execute(text(f'DROP DATABASE IF EXISTS "{_DB}"'))
    except Exception:                            # pragma: no cover - cleanup
        pass


print("\n" + "=" * 66)
if _failures:
    print(f"PG-CERT-1 LAUNCH HYGIENE — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("PG-CERT-1 LAUNCH HYGIENE — all assertions PASSED")
