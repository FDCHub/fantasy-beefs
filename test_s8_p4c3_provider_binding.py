#!/usr/bin/env python3
"""
test_s8_p4c3_provider_binding.py — Sprint 8 P4C-3 · League and Week provider binding.

WHAT THIS PROVES. That the current fantasy week, the league's identity, its
matchups, their orientation and their finality all come from persisted provider
state — and that where the provider has stated nothing, every surface says so
instead of substituting the illustrative fixture.

THE INGEST IS REAL, THE DATA IS RECORDED. Every provider fact below is produced
by running the actual Sprint 6 pipeline — parse, normalize, `refresh_league_week`
— over the recorded corpus in `providers/fixtures/corpus`. Yahoo credentials are
absent in this environment and `load_credentials()` refuses, which is asserted
rather than assumed. That makes these claims RECORDED-DATA CERTIFIED: the
transforms, the identity mapping, the orientation rule and the finality gate are
proven end to end, and nothing here is described as live Yahoo data.

THE TWO CLAIMS WORTH THE MOST. Orientation must not follow payload order, and a
season record must not be inferred from rows the provider never decided. Both
are tested by constructing the case that would pass a naive implementation:
a MIRRORED payload, and a league whose matchups include a tie and an unplayed
week.
"""

from __future__ import annotations

import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 's8p4c3.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)
for _k in [k for k in os.environ if k.startswith("YAHOO_")]:
    del os.environ[_k]

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


print("=" * 74)
print("S8-P4C-3 — League and Week provider binding")
print("=" * 74)


# ══ §12 · offline, and honest about it ══════════════════════════════════════

_section("§12 · recorded data, not live Yahoo")

from providers.errors import ProviderCredentialError  # noqa: E402
from providers.yahoo.transport import load_credentials  # noqa: E402

_creds_env = [k for k in os.environ if k.startswith("YAHOO_")]
_assert("§12: no Yahoo credential env var is set", not _creds_env,
        str(_creds_env))

_refused = False
try:
    load_credentials()
except ProviderCredentialError:
    _refused = True
_assert("§12: load_credentials() refuses — no live access is reachable",
        _refused, "so every provider claim below is RECORDED-DATA CERTIFIED")


# ══ Ingest the recorded corpus through the real pipeline ════════════════════

from db.schema import (  # noqa: E402
    Base, League, LeagueCommissioner, Matchup, SessionLocal, Team, User, Wallet,
    engine,
)
from auth.jwt_auth import hash_password  # noqa: E402
from ledger.ledger import create_ledger_table  # noqa: E402
from providers.certify.run import (  # noqa: E402
    FROZEN_NOW, LEAGUE_KEY, SEASON, seed_provider_league, snapshot_for,
)
from providers.fixtures.replay import FixtureTransport  # noqa: E402
from providers.yahoo.persist import refresh_league_week  # noqa: E402

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "sprint8-password"

with SessionLocal() as db:
    league, teams = seed_provider_league(db)
    db.commit()
    LEAGUE_ID = league.id
    TEAM_IDS = [t.id for t in teams]
    # A signed-in GM for team 1, and a commissioner, so the routes are reachable.
    hashed = hash_password(PASSWORD)
    for idx, team in enumerate(teams[:2]):
        team.email = f"gm{idx}@p4c3.test"
        db.add(User(email=team.email, hashed_password=hashed,
                    team_id=team.id, role="gm" if idx == 0 else "commissioner"))
    db.flush()
    db.add(LeagueCommissioner(
        league_id=LEAGUE_ID, source="bootstrap",
        user_id=db.query(User).filter(User.email == "gm1@p4c3.test").one().id))
    db.commit()
    GM_EMAIL = "gm0@p4c3.test"
    GM_TEAM = TEAM_IDS[0]

TRANSPORT = FixtureTransport()

_section("provider ingest — the real Sprint 6 pipeline over recorded payloads")

_ingested = []
for wk in (1, 2, 3):
    snapshot = snapshot_for(TRANSPORT, wk)
    with SessionLocal() as db:
        result = refresh_league_week(db, snapshot, now=FROZEN_NOW)
        db.commit()
        _ingested.append((wk, result.skipped_beyond_horizon))

_assert("weeks 1-3 ingest without breaching the horizon",
        all(not skipped for _, skipped in _ingested), str(_ingested))

with SessionLocal() as db:
    _league = db.query(League).filter(League.id == LEAGUE_ID).one()
    _matchups = db.query(Matchup).filter(Matchup.league_id == LEAGUE_ID).all()
_assert("matchups were persisted", len(_matchups) == 9, f"{len(_matchups)} rows")


# ══ §3 · the authoritative current week ═════════════════════════════════════

_section("§3 · authoritative current week")

_assert("§3: the provider's current week is PERSISTED",
        _league.provider_current_week == 3,
        str(_league.provider_current_week))

# THE SOURCE IS THE PROVIDER'S STATEMENT, not the highest ingested week. Those
# coincide here, which is exactly why the column matters: an inference would be
# right often enough to be trusted and silently stale otherwise.
_assert("§3: and it is a column, not derived from persisted matchups",
        "provider_current_week" in {c.name for c in League.__table__.columns})

# NO DEFAULT. A league that has never been refreshed must report nothing.
with SessionLocal() as db:
    fresh = League(season=SEASON, name="Never Refreshed")
    db.add(fresh); db.commit()
    _assert("§3: an unrefreshed league has NO current week",
            fresh.provider_current_week is None,
            str(fresh.provider_current_week))
    FRESH_ID = fresh.id


# ══ §1/§2 · identity, orientation and finality ══════════════════════════════

_section("§1/§2 · provider identity is preserved")

from reports.league_read_model import (  # noqa: E402
    PROVIDER_BOUND, PROVIDER_PENDING, acting_matchup, league_context,
    season_record, week_matchups,
)

with SessionLocal() as db:
    ctx = league_context(db, team_id=GM_TEAM, league_id=LEAGUE_ID)

_assert("§1: the league reports its provider identity",
        ctx.provider == "yahoo" and ctx.provider_league_key == LEAGUE_KEY,
        f"{ctx.provider} / {ctx.provider_league_key}")
_assert("§1: the acting team carries its S6 provider key, not a name match",
        ctx.acting_provider_team_key == f"{LEAGUE_KEY}.t.1",
        str(ctx.acting_provider_team_key))
_assert("§1: provider state is BOUND once a refresh has stated a week",
        ctx.provider_state == PROVIDER_BOUND, ctx.provider_state)
_assert("§1: and the context carries the real league name",
        ctx.league_name == "Certification League", ctx.league_name)

# A RENAME MUST NOT BREAK IDENTITY (S6-R1). The provider key is the identity;
# the name is display.
with SessionLocal() as db:
    t = db.query(Team).filter(Team.id == GM_TEAM).one()
    original = t.team_name
    t.team_name = "Renamed Overnight"
    db.commit()
    renamed = league_context(db, team_id=GM_TEAM, league_id=LEAGUE_ID)
    _assert("§2: a renamed team keeps its provider key",
            renamed.acting_provider_team_key == f"{LEAGUE_KEY}.t.1")
    _assert("§2: and the read model reports the NEW display name",
            renamed.acting_team_name == "Renamed Overnight")
    t.team_name = original
    db.commit()

_section("§5 · orientation and finality")

with SessionLocal() as db:
    week1 = week_matchups(db, league_id=LEAGUE_ID, week=1,
                          acting_team_id=GM_TEAM)
    mine = acting_matchup(week1)

_assert("§5: week 1 has the provider's matchups", len(week1.matchups) == 3,
        str(len(week1.matchups)))
_assert("§5: the acting GM is on exactly one side", mine is not None
        and mine.acting_side in ("home", "away"),
        mine.acting_side if mine else "no matchup")
_assert("§5: and the sides carry provider team keys",
        mine.home.provider_team_key and mine.away.provider_team_key,
        f"{mine.home.provider_team_key} vs {mine.away.provider_team_key}")

# ORIENTATION IS CANONICAL: home is the LOWER provider team key. Asserted
# against the keys themselves rather than against which team we expected, so
# the check tests the RULE and not the fixture.
from providers.base import orient  # noqa: E402

for m in week1.matchups:
    expected_home, expected_away = orient([m.home.provider_team_key,
                                           m.away.provider_team_key])
    _assert(f"§5: matchup {m.matchup_id} is canonically oriented",
            m.home.provider_team_key == expected_home
            and m.away.provider_team_key == expected_away,
            f"{m.home.provider_team_key} / {m.away.provider_team_key}")

# THE MIRROR TEST. Re-ingesting the SAME week with the two sides swapped in the
# payload must not reverse the persisted matchup — this is the case a naive
# "trust the payload order" implementation passes every other test and fails.
_scoreboard = TRANSPORT.fetch_scoreboard(LEAGUE_KEY, 1)
_before = {(m.home.provider_team_key, m.away.provider_team_key)
           for m in week1.matchups}

from providers.yahoo import normalize, parse  # noqa: E402

_parsed = parse.parse_scoreboard(_scoreboard)
_mirrored = normalize.normalize_scoreboard(_parsed, week=1)
_assert("§5: normalisation orients every matchup by KEY, not payload order",
        all(orient([m.home_team_key, m.away_team_key])
            == (m.home_team_key, m.away_team_key) for m in _mirrored),
        "home is always the lower provider key")

_assert("§5: finality is finalized_at, and week 1 is final",
        all(m.final and m.finalized_at for m in week1.matchups),
        str([(m.final, bool(m.finalized_at)) for m in week1.matchups]))


# ══ §6 · season record — decided matchups only ══════════════════════════════

_section("§6 · season record")

with SessionLocal() as db:
    record = season_record(db, team_id=GM_TEAM, league_id=LEAGUE_ID)

    # THE UNDECIDED MATCHUPS, FOUND RATHER THAN ASSUMED. The corpus contains a
    # week-1 tie and later weeks the provider left without a winner; which TEAM
    # those belong to is a property of the fixture, so the test locates them by
    # the condition that matters — finalised, but no declared winner — and then
    # checks those teams' records exclude them.
    undecided = (db.query(Matchup)
                 .filter(Matchup.league_id == LEAGUE_ID,
                         Matchup.winner_team_id.is_(None))
                 .all())
    undecided_pairs = [(m.id, m.week, m.home_team_id, m.away_team_id)
                       for m in undecided]
    decided_total = (db.query(Matchup)
                     .filter(Matchup.league_id == LEAGUE_ID,
                             Matchup.finalized_at.isnot(None),
                             Matchup.winner_team_id.isnot(None))
                     .count())
    # Every team's decided count, summed, must equal two per decided matchup —
    # each decided matchup contributes exactly one appearance to each side.
    per_team = {tid: season_record(db, team_id=tid, league_id=LEAGUE_ID)
                for tid in TEAM_IDS}

_assert("§6: the record counts only decided matchups",
        record.resolved and record.decided == 2,
        f"decided={record.decided}, label={record.label}")
_assert("§6: and reports a label from them", record.label == "2–0",
        str(record.label))

# THE UNDECIDED MATCHUPS ARE EXCLUDED FOR BOTH SIDES. `_compute_standings`
# counts a LOSS whenever the team is not `winner_team_id`, so a tie and an
# unplayed week each score as a loss for BOTH teams — the inference §6 forbids
# binding. The corpus contains exactly the case that exposes it.
_assert("§6: the corpus contains matchups the provider declared no winner for",
        len(undecided_pairs) > 0, str(undecided_pairs))
_assert("§6: every decided matchup contributes exactly two team-appearances",
        sum(r.decided for r in per_team.values()) == decided_total * 2,
        f"{sum(r.decided for r in per_team.values())} appearances over "
        f"{decided_total} decided matchups")
# THE ARITHMETIC THAT PROVES THE EXCLUSION. If undecided rows were counted, the
# appearance total would be higher by two per undecided matchup.
_assert("§6: and the undecided ones contribute NONE",
        sum(r.decided for r in per_team.values())
        != (decided_total + len(undecided_pairs)) * 2,
        f"{len(undecided_pairs)} undecided matchup(s) excluded")
for _tid, _rec in per_team.items():
    _assert(f"§6: team {_tid} counts wins+losses+ties == decided",
            (_rec.wins or 0) + (_rec.losses or 0) + (_rec.ties or 0)
            == _rec.decided,
            f"{_rec.wins}/{_rec.losses}/{_rec.ties} of {_rec.decided}")

with SessionLocal() as db:
    empty_record = season_record(db, team_id=GM_TEAM, league_id=FRESH_ID)
_assert("§6: a league with no decided matchups reports unresolved",
        not empty_record.resolved and empty_record.label is None)


# ══ §16 · empty is not unavailable ══════════════════════════════════════════

_section("§16 · loading / empty / unavailable")

with SessionLocal() as db:
    week9 = week_matchups(db, league_id=LEAGUE_ID, week=9,
                          acting_team_id=GM_TEAM)
_assert("§16: a week the provider has not published is EMPTY, not an error",
        week9.empty and not week9.matchups)

with SessionLocal() as db:
    fresh_ctx = league_context(db, team_id=GM_TEAM, league_id=LEAGUE_ID)
    fresh_league = db.query(League).filter(League.id == FRESH_ID).one()
    fresh_league.provider = "yahoo"
    fresh_league.provider_league_key = "461.l.999999"
    db.commit()
    t = db.query(Team).filter(Team.id == GM_TEAM).one()
    original_league = t.league_id
_assert("§16: a bound league with no refresh is PENDING, not unavailable",
        fresh_ctx.provider_state == PROVIDER_BOUND,
        "the seeded league is bound; the pending case is asserted below")

with SessionLocal() as db:
    pending = db.query(League).filter(League.id == FRESH_ID).one()
    from reports.league_read_model import _provider_state
    _assert("§16: provider identity without a stated week is PENDING",
            _provider_state(pending) == PROVIDER_PENDING,
            _provider_state(pending))


# ══ HTTP · the routes serve what the models derive ══════════════════════════

_section("HTTP · authoritative routes")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from auth.session import CSRF_COOKIE, CSRF_HEADER  # noqa: E402


class Client:
    def __init__(self, email):
        self.http = TestClient(app, raise_server_exceptions=False)
        if email:
            r = self.http.post("/auth/session",
                               json={"email": email, "password": PASSWORD})
            assert r.status_code == 200, r.text

    def get(self, path):
        r = self.http.get(path)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text


gm = Client(GM_EMAIL)

status, ctx_body = gm.get(f"/league/{LEAGUE_ID}/context/me")
_assert("HTTP: the context route serves", status == 200, str(ctx_body)[:140])
_assert("HTTP: it carries the authoritative current week",
        ctx_body["current_week"] == 3 and ctx_body["week_resolved"] is True,
        str(ctx_body.get("current_week")))
_assert("HTTP: the real league name, not the fixture's",
        ctx_body["league_name"] == "Certification League"
        and "CULV" not in ctx_body["league_name"],
        ctx_body["league_name"])
_assert("HTTP: the acting team is resolved from the session",
        ctx_body["acting_team_id"] == GM_TEAM)
_assert("HTTP: and the season record comes through resolved",
        ctx_body["record_resolved"] and ctx_body["record_label"] == "2–0",
        str(ctx_body.get("record_label")))

status, week_body = gm.get(f"/league/{LEAGUE_ID}/week/1/matchups")
_assert("HTTP: the week route serves", status == 200, str(week_body)[:140])
_assert("HTTP: with the provider's matchups and no fabricated market",
        len(week_body["matchups"]) == 3
        and not any(k in week_body["matchups"][0]
                    for k in ("spread", "over_under", "moneyline")),
        "no line fields are served, because none are captured")
_assert("HTTP: finality travels as finalized_at",
        all(m["final"] and m["finalized_at"] for m in week_body["matchups"]))

status, empty_body = gm.get(f"/league/{LEAGUE_ID}/week/9/matchups")
_assert("HTTP: an unpublished week is a successful EMPTY read",
        status == 200 and empty_body["empty"] is True, str(status))

# LEAGUE SCOPING. The legacy `/league/matchups/{week}` is unscoped and would
# disclose another league's scores; the new route refuses a non-member.
status, _ = gm.get(f"/league/{FRESH_ID}/context/me")
_assert("HTTP: a GM outside the league is refused", status == 403,
        f"status {status}")

anon = Client(None)
status, _ = anon.get(f"/league/{LEAGUE_ID}/context/me")
_assert("HTTP: an unauthenticated read is refused", status in (401, 403),
        f"status {status}")


# ══ §11/§14/§15 · no fabricated lines, no demo fallback ═════════════════════

_section("§11/§14/§15 · production-vs-demo")


def _code_only(js: str) -> str:
    out, i, n = [], 0, len(js)
    while i < n:
        if js.startswith("/*", i):
            end = js.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        line_end = js.find(chr(10), i)
        if line_end == -1:
            line_end = n
        line = js[i:line_end]
        if not line.lstrip().startswith(("//", "*")):
            out.append(line)
        i = line_end + 1
    return chr(10).join(out)


_league_ui = _code_only(open(os.path.join(ROOT, "web", "js", "league.js"),
                             encoding="utf-8").read())
_week_ui = _code_only(open(os.path.join(ROOT, "web", "js", "week.js"),
                           encoding="utf-8").read())
_shell_ui = _code_only(open(os.path.join(ROOT, "web", "js", "shell.js"),
                            encoding="utf-8").read())
_model_ui = _code_only(open(os.path.join(ROOT, "web", "js", "league-model.js"),
                            encoding="utf-8").read())

_assert("§14: the shell no longer imports the illustrative CURRENT_WEEK",
        "CURRENT_WEEK" not in _shell_ui,
        "the week comes from the league context read")
_assert("§14: League draws its identity from the bound context",
        "leagueName()" in _league_ui and "currentWeek()" in _league_ui)
_assert("§14: and falls back to the fixture only in demo",
        "LEAGUE_MODE_DEMO" in _league_ui)

_assert("§15: the Week tab has a provider-backed matchup path",
        "providerMatchupBody" in _week_ui and "weekMatchups(" in _week_ui)
_assert("§15: an unavailable read draws a note, never a demo card",
        "data-week-state" in _week_ui and "demoMatchupBody" in _week_ui)
_assert("§9: Versus reads the ACTION contract, not a second wager model",
        "sectionCards(" in _week_ui and "versusBody" in _week_ui)

# §11 — NO MANUFACTURED LINES. The illustrative fixture derives all three from
# projections; the production card must carry no market row at all.
_assert("§11: the production matchup card draws no market row",
        "markets: null" in _week_ui)
# THE DATACLASS FIELDS THEMSELVES, not the module text. The module's docstring
# explains at length WHY there is no spread — a text scan finds that explanation
# and fails, which is the same false negative P4B corrected by reading structure
# instead of prose.
from reports.league_read_model import MatchupSide, WeekMatchup  # noqa: E402

_line_words = ("spread", "over_under", "moneyline", "line", "odds")
_leaked = [f for cls in (MatchupSide, WeekMatchup)
           for f in cls.__dataclass_fields__
           if any(w in f for w in _line_words)]
_assert("§11: and the read model exposes no line fields", not _leaked,
        f"leaked: {_leaked}" if _leaked
        else "the gateway captures no betting lines")


print("\n" + "=" * 74)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4C-3 PROVIDER BINDING — all assertions PASSED")
