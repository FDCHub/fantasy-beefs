"""
test_wp2a_provider_pool_stats_pg.py — WP2A · provider Pool-stat ingestion.

WHAT THIS PROVES. `providers/yahoo/week_snapshot.py` assembles a `ProviderWeek`
that actually carries `roster_entries` and `player_stats`, so the certified
`YahooProviderStatSource` can be constructed from something the running product
produces. Before WP2A the only production assembly built a snapshot with both
collections empty, which is why governed Pool settlement was unreachable.

REUSE, NOT REIMPLEMENTATION. The corpus, the fixture transport and the provider
league seed are taken from `providers/certify/run.py` — the certified harness —
so this suite cannot drift from the artifact the gateway was certified against.

OFFLINE BY CONSTRUCTION. Every fetch goes through `FixtureTransport`. No
credentials, no network, no live Yahoo call.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("JWT_SECRET_KEY", "wp2a-suite-secret")

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP2A suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n== {title} ==")


def main() -> None:
    from db.schema import SessionLocal
    from providers.certify.run import (
        FROZEN_NOW, LEAGUE_KEY, seed_provider_league,
    )
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo.persist import refresh_league_week
    from providers.yahoo.week_snapshot import (
        bind_pool_stat_source, fetch_week_snapshot,
    )

    WEEK = 1

    # ════ 1. ROSTER + PLAYER-STAT INGESTION ═════════════════════════════════
    _section("the production assembly carries rosters and player stats")

    tdb.reset()
    transport = FixtureTransport(frozen_now=FROZEN_NOW)

    bare = fetch_week_snapshot(transport, league_key=LEAGUE_KEY, week=WEEK)
    _assert("without rosters the snapshot carries no roster entries",
            bare.roster_entries == (), str(len(bare.roster_entries)))
    _assert("without rosters the snapshot carries no player stats",
            bare.player_stats == (), str(len(bare.player_stats)))
    _assert("the bare snapshot still carries matchups — this is the shape the "
            "pre-WP2A production path produced",
            len(bare.matchups) > 0, str(len(bare.matchups)))

    full = fetch_week_snapshot(transport, league_key=LEAGUE_KEY, week=WEEK,
                               with_rosters=True)
    _assert("with rosters the snapshot carries roster entries",
            len(full.roster_entries) > 0, str(len(full.roster_entries)))
    _assert("with rosters the snapshot carries player stats",
            len(full.player_stats) > 0, str(len(full.player_stats)))
    _assert("the same matchups are carried either way",
            full.matchups == bare.matchups)
    _assert("the week binding is preserved", full.week == WEEK, str(full.week))
    _assert("the league binding is preserved",
            full.league.league_key == LEAGUE_KEY, full.league.league_key)

    # ════ 2. NO PAYLOAD-ORDER DEPENDENCE ════════════════════════════════════
    _section("assembly order is derived, not inherited")

    team_keys_seen = [e.team_key for e in full.roster_entries]
    first_index = {}
    for i, k in enumerate(team_keys_seen):
        first_index.setdefault(k, i)
    _assert("roster entries are grouped by team in sorted team-key order",
            list(first_index) == sorted(first_index), str(list(first_index)))

    # ════ 3. REPLAY DETERMINISM ═════════════════════════════════════════════
    _section("replay determinism")

    again = fetch_week_snapshot(
        FixtureTransport(frozen_now=FROZEN_NOW),
        league_key=LEAGUE_KEY, week=WEEK, with_rosters=True)
    _assert("a rebuilt snapshot has identical roster entries",
            again.roster_entries == full.roster_entries)
    _assert("a rebuilt snapshot has identical player stats",
            again.player_stats == full.player_stats)
    _assert("a rebuilt snapshot has an identical observed_at",
            again.observed_at == full.observed_at, str(again.observed_at))
    _assert("REBUILD-AT-USE-TIME IS SOUND: the settlement-time snapshot equals "
            "the ingestion-time snapshot",
            (again.league, again.week, again.teams, again.matchups,
             again.roster_entries, again.player_stats)
            == (full.league, full.week, full.teams, full.matchups,
                full.roster_entries, full.player_stats))

    # ════ 4. IDENTITY MAPPING AND STAT SUPPORT ══════════════════════════════
    _section("identity mapping and measured stat support")

    with SessionLocal() as db:
        league, teams = seed_provider_league(db)
        db.commit()
        league_id = league.id
        # Captured while the session is live; these instances detach at exit.
        a_team_ids = {t.id for t in teams}

        refresh_league_week(db, full, now=FROZEN_NOW)
        db.commit()

        source = bind_pool_stat_source(db, full, league_id=league_id)
        supported = source.supported_stats()

        _assert("the bound source advertises passing_yards",
                "passing_yards" in supported)
        _assert("a derived stat with covered inputs is advertised",
                "scrimmage_yards" in supported)
        _assert("an UNMAPPED stat is never advertised (pass_attempts has no "
                "yahoo_stat_id in the governed vocabulary)",
                "pass_attempts" not in supported)
        _assert("a stat derived from an unmapped input is never advertised",
                "opportunities" not in supported)
        _assert("an UNSUPPORTED-BY-YAHOO stat is never advertised",
                "made_field_goal_distance" not in supported)

        # MISSING ROSTER BEHAVIOUR: a snapshot with no rosters must advertise no
        # roster-derived support rather than reporting zeros.
        bare_source = bind_pool_stat_source(db, bare, league_id=league_id)
        bare_supported = bare_source.supported_stats()
        _assert("a snapshot without rosters advertises no passing_yards",
                "passing_yards" not in bare_supported, str(sorted(bare_supported)))
        _assert("MISSING IS UNEVALUABLE, NOT 0.0 — the empty snapshot advertises "
                "strictly less than the full one",
                bare_supported < supported,
                f"{len(bare_supported)} < {len(supported)}")

        db.rollback()

    # ════ 5. CROSS-LEAGUE ISOLATION ═════════════════════════════════════════
    _section("cross-league isolation of provider identity")

    with SessionLocal() as db:
        # Seeded WITHOUT provider identity: `provider_league_key` is unique, so
        # a second league cannot claim the same corpus league even by mistake.
        # That is itself the isolation guarantee — league B has no binding to
        # the corpus, so its resolver must refuse every corpus team key.
        other, _ = seed_provider_league(db, name="Unrelated League",
                                        bind_identity=False)
        db.commit()
        other_id = other.id

        from providers.errors import ProviderIdentityError
        from providers.yahoo.identity import build_team_identity_resolver

        resolver_a = build_team_identity_resolver(db, league_id=league_id)
        a_ids = {resolver_a.to_internal(k)
                 for k in sorted({e.team_key for e in full.roster_entries})}
        _assert("league A's resolver maps the corpus team keys",
                len(a_ids) > 0, str(sorted(a_ids)))

        _assert("every resolved id belongs to league A",
                a_ids <= a_team_ids, f"{sorted(a_ids)} vs {sorted(a_team_ids)}")

        # ISOLATION IS FAIL-CLOSED, AND STRONGER THAN "RESOLVES TO SOMETHING
        # ELSE". An unbound league does not get a resolver that maps the corpus
        # to the wrong teams — it gets no resolver at all. A partial resolver is
        # never returned, because one would silently drop unbound teams from the
        # slate rather than refusing.
        refused = False
        try:
            build_team_identity_resolver(db, league_id=other_id)
        except ProviderIdentityError:
            refused = True
        _assert("an unrelated league cannot obtain a resolver for the corpus "
                "at all — no partial resolver is ever returned",
                refused)
        db.rollback()

    # ════ 6. FINALITY AUTHORITY UNCHANGED ═══════════════════════════════════
    _section("finalized_at remains the finality authority")

    from betting.finality_gate import require_week_final

    with SessionLocal() as db:
        from db.schema import Matchup

        total = (db.query(Matchup)
                 .filter(Matchup.league_id == league_id,
                         Matchup.week == WEEK).count())
        unfinalized = (db.query(Matchup)
                       .filter(Matchup.league_id == league_id,
                               Matchup.week == WEEK,
                               Matchup.finalized_at.is_(None)).count())
        _assert("the refreshed week persisted its matchups",
                total > 0, f"{total} matchup(s)")

        # WHAT IS ACTUALLY TRUE, rather than what was assumed. Corpus week 1 is
        # a COMPLETED week: refresh_league_week set finalized_at on every
        # matchup, so the governed gate must PERMIT it. An earlier draft
        # asserted a refusal and passed only because a wrong call signature
        # raised TypeError — the assertion is now written against the state the
        # database actually holds.
        _assert("corpus week 1 is economically final after refresh",
                unfinalized == 0, f"{unfinalized} unfinalized")

        permitted = False
        try:
            require_week_final(db, league_id=league_id, week=WEEK,
                               context="wp2a-finality-check")
            permitted = True
        except Exception as exc:  # noqa: BLE001
            permitted = f"refused: {type(exc).__name__}"
        _assert("the finality gate permits the final week — finalized_at "
                "remains the sole authority, unchanged by WP2A",
                permitted is True, str(permitted))

        # The NEGATIVE case (a week refused because finalized_at is NULL) is
        # certified by the existing S6 provider-gateway suite and by C-13 in
        # providers/certify/run.py. It is deliberately not duplicated here.
        db.rollback()


if __name__ == "__main__":
    print("\n=== WP2A provider pool-stat ingestion suite (PostgreSQL) ===")
    try:
        main()
    finally:
        tdb.teardown()
    print(f"\n  {len(_failures)} failure(s)")
    if _failures:
        for f in _failures:
            print(f"    FAILED: {f}")
        sys.exit(1)
    print("  ALL PASS")