# settle_week Race Review

Extracted for review purposes only. Full function bodies, no partial snippets. Nothing has been modified — see the originating file/line ranges noted under each header.

**Note:** the request asked for "the call site" (singular), but `_assert_slate_fresh()` is actually invoked from **two** places in `notifications/tuesday_sync.py`, in two different functions. Both are included below rather than guessing which one was meant.

---

## 1. `notifications/tuesday_sync.py` — `_assert_slate_fresh()`

Lines 206-288.

```python
def _assert_slate_fresh(
    league_id: int,
    week: int,
    db: Session,
    *,
    yahoo_home_ids: set[int] | None = None,
    check_refreshed: bool = False,
) -> tuple[bool, str, int]:
    """
    Single source of truth for "is the matchup slate complete and refreshed?"

    Returns (is_fresh, reason, db_count).

    Always checks:
      - db_count > 0  (seed must have run)

    When yahoo_home_ids is provided (step 0 / _step_refresh_scores):
      - Checks exact set identity between DB home_team_ids and Yahoo's translated
        return, in both directions:
          missing = db_home_ids - yahoo_home_ids  (DB game Yahoo dropped)
          extra   = yahoo_home_ids - db_home_ids  (game Yahoo invented)
        Either non-empty set fails the gate.  Count equality alone does not
        pass — a duplicate plus a missing game has identical counts but fires
        both sets.
      - yahoo_home_ids contains DB IDs (after TeamResolver translation), so the
        comparison is in the same namespace as the DB query.

    When check_refreshed=True (step 1 self-guard / _step_settle_bets):
      - Checks that all matchup rows have refreshed_at IS NOT NULL.
      - NULL means _step_refresh_scores did not complete for that row.
      - Requires migration: migrations/add_matchup_refreshed_at.py.
      - Score values (0.0, etc.) are never used to infer freshness — only the
        timestamp is authoritative.  A genuine 0-0 final with a non-NULL
        refreshed_at is correctly treated as fresh.
    """
    from sqlalchemy import text

    rows = db.execute(
        text(
            "SELECT home_team_id, refreshed_at FROM matchups "
            "WHERE league_id = :lid AND week = :week"
        ),
        {"lid": league_id, "week": week},
    ).fetchall()

    db_count = len(rows)

    if db_count == 0:
        return (
            False,
            f"week {week}: no matchups in DB for league_id={league_id} — seed not run?",
            0,
        )

    if yahoo_home_ids is not None:
        db_home_ids = {row[0] for row in rows}
        missing     = db_home_ids - yahoo_home_ids  # DB games Yahoo dropped
        extra       = yahoo_home_ids - db_home_ids  # games Yahoo invented
        if missing or extra:
            parts: list[str] = []
            if missing:
                parts.append(f"missing from Yahoo: {sorted(missing)}")
            if extra:
                parts.append(f"invented by Yahoo (not in DB): {sorted(extra)}")
            return (
                False,
                f"week {week}: slate mismatch — {'; '.join(parts)}",
                db_count,
            )

    if check_refreshed:
        unrefreshed = [row[0] for row in rows if row[1] is None]
        if unrefreshed:
            return (
                False,
                (f"week {week}: {len(unrefreshed)} matchup(s) have NULL refreshed_at — "
                 f"refresh did not complete "
                 f"(home_team_ids: {sorted(unrefreshed)})"),
                db_count,
            )

    return (True, f"week {week}: {db_count} matchup(s) — slate complete and fresh",
            db_count)
```

---

## 2. `notifications/tuesday_sync.py` — call site 1: `_step_refresh_scores()`

Lines 331-480. Invokes `_assert_slate_fresh()` at line 435 with `yahoo_home_ids=` set (no `check_refreshed`).

```python
def _step_refresh_scores(
    league_id: int,
    week: int,
    db: Session,
) -> tuple[StepResult, RefreshResult]:
    """
    Step 0 — pull the live Yahoo scoreboard for the given week and upsert
    matchup scores into the matchups table.

    Returns (StepResult, RefreshResult).  RefreshResult.settleable is True only
    when all matchups are final, the Yahoo return covers the full DB slate with
    set-exact identity (not just count equality), every team ID resolved, and
    the upsert committed — including refreshed_at = NOW() on every row.

    Translation precedes the slate check because set containment requires
    DB IDs, and those only exist after the TeamResolver runs.
    """
    from db.team_resolver import build_team_resolver, TeamResolverError
    from sqlalchemy import text
    from yahoo_scoreboard import fetch_week_scoreboard

    yahoo_league_id = os.getenv("YAHOO_LEAGUE_ID", "488800")
    t0 = time.monotonic()

    def _not_fresh(
        reason: str, error: str | None = None
    ) -> tuple[StepResult, RefreshResult]:
        ms = int((time.monotonic() - t0) * 1000)
        return (
            StepResult("refresh_scores", False, reason, {"settleable": False}, error, ms),
            RefreshResult(settleable=False, week=week, reason=reason),
        )

    # ── Build team resolver (one DB round-trip) ───────────────────────────────
    try:
        resolver = build_team_resolver(db, league_id)
    except TeamResolverError as exc:
        return _not_fresh(f"week {week}: team resolver failed — {exc}", str(exc))
    except Exception as exc:
        return _not_fresh(f"week {week}: unexpected resolver error — {exc}", str(exc))

    # ── Fetch live scoreboard from Yahoo ─────────────────────────────────────
    try:
        query      = _build_yahoo_query(yahoo_league_id)
        scoreboard = fetch_week_scoreboard(query, week)
    except Exception as exc:
        return _not_fresh(
            f"week {week}: Yahoo fetch failed — {type(exc).__name__}: {exc}",
            str(exc),
        )

    if scoreboard is None:
        return _not_fresh(f"week {week}: season-over anomaly — Yahoo returned None")

    # ── All returned matchups must be final ───────────────────────────────────
    # Early exit before translation — status check is cheap.
    not_final = [m for m in scoreboard if m["status"] != "final"]
    if not_final:
        pairs    = [(m["home_team_id"], m["away_team_id"]) for m in not_final]
        statuses = [m["status"] for m in not_final]
        return _not_fresh(
            f"week {week} not settled: matchup(s) {pairs} not final (statuses: {statuses})"
        )

    # ── Translate Yahoo IDs → DB IDs (all-or-nothing) ────────────────────────
    # Translation must precede the slate check — set containment compares
    # DB home_team_id values, which only exist after resolver runs.
    translated: list[dict] = []
    unresolved: list[str]  = []

    for m in scoreboard:
        try:
            db_home   = resolver.yahoo_to_db(m["home_team_id"])
            db_away   = resolver.yahoo_to_db(m["away_team_id"])
            db_winner = (
                resolver.yahoo_to_db(m["winner_team_id"])
                if m["winner_team_id"] is not None
                else None
            )
        except TeamResolverError as exc:
            unresolved.append(str(exc))
            continue

        translated.append({
            "league_id":      league_id,
            "week":           week,
            "home_team_id":   db_home,
            "away_team_id":   db_away,
            "home_score":     m["home_score"],
            "away_score":     m["away_score"],
            "winner_team_id": db_winner,
        })

    if unresolved:
        return _not_fresh(
            f"week {week}: unresolved team IDs — {'; '.join(unresolved)}"
        )

    # ── Slate completeness — set containment, not count equality ─────────────
    # Six matchups back / six in DB / gate clears — even if one is a duplicate
    # and one real game is missing.  The missing game keeps its stale score and
    # settles anyway.  Set containment closes this: every DB home_team_id must
    # appear in Yahoo's translated return.
    yahoo_home_ids = {row["home_team_id"] for row in translated}
    slate_ok, slate_reason, _ = _assert_slate_fresh(
        league_id, week, db, yahoo_home_ids=yahoo_home_ids
    )
    if not slate_ok:
        return _not_fresh(slate_reason)

    # ── Upsert all rows in one transaction ───────────────────────────────────
    # refreshed_at = NOW() written on both INSERT and UPDATE.
    # _assert_slate_fresh with check_refreshed=True reads this column in step 1
    # to confirm the refresh completed; NULL = never touched by a live refresh.
    upsert_sql = text("""
        INSERT INTO matchups
            (league_id, week, home_team_id, away_team_id,
             home_score, away_score, winner_team_id, refreshed_at)
        VALUES
            (:league_id, :week, :home_team_id, :away_team_id,
             :home_score, :away_score, :winner_team_id, NOW())
        ON CONFLICT (league_id, week, home_team_id)
        DO UPDATE SET
            home_score     = EXCLUDED.home_score,
            away_score     = EXCLUDED.away_score,
            winner_team_id = EXCLUDED.winner_team_id,
            refreshed_at   = NOW()
    """)
    try:
        for row in translated:
            db.execute(upsert_sql, row)
        db.commit()
    except Exception as exc:
        db.rollback()
        return _not_fresh(
            f"week {week}: upsert failed — {type(exc).__name__}: {exc}",
            str(exc),
        )

    ms  = int((time.monotonic() - t0) * 1000)
    msg = (f"week {week}: {len(translated)} matchup score(s) upserted — "
           f"all final, full slate, all IDs resolved")
    return (
        StepResult(
            "refresh_scores", True, msg,
            {"rows_upserted": len(translated), "settleable": True},
            None, ms,
        ),
        RefreshResult(settleable=True, week=week, reason=msg),
    )
```

---

## 3. `notifications/tuesday_sync.py` — call site 2: `_step_settle_bets()`

Lines 485-538. Invokes `_assert_slate_fresh()` at line 496 with `check_refreshed=True` (no `yahoo_home_ids`).

```python
def _step_settle_bets(
    league_id: int,
    week: int,
    db: Session,
    *,
    mock_mode: bool = MOCK_EMAIL_MODE,
):
    # DB self-guard — re-derive freshness from the DB before touching any wallet.
    # Reads refreshed_at IS NOT NULL (written by step 0's upsert).
    # This is independent of the gate in run_tuesday_sync and catches direct calls
    # (tests, scripts, future gate bugs) that bypass it.
    fresh_ok, fresh_reason, _ = _assert_slate_fresh(
        league_id, week, db, check_refreshed=True
    )
    if not fresh_ok:
        # The alert itself must never crash the abort path — if the commissioner
        # address is bad or SMTP is down, log and continue to the safe return.
        try:
            _alert_settlement_skipped(league_id, week, fresh_reason, mock_mode, db)
        except Exception as alert_exc:
            import logging
            logging.error(
                "[TuesdaySync] Settlement skip alert failed (guard still active): %s",
                alert_exc,
            )
        return (
            StepResult(
                "settle_bets", False,
                f"ABORTED — DB slate not fresh: {fresh_reason}",
                {"settleable": False, "db_guard_triggered": True, "reason": fresh_reason},
                None, 0,
            ),
            None,
        )

    from betting.settlement_engine import settle_week
    t0 = time.monotonic()
    try:
        report = settle_week(week, db)
        ms     = int((time.monotonic() - t0) * 1000)
        msg    = (f"Settled {report.total_bets} bets: "
                  f"{report.bets_won} won, {report.bets_lost} lost")
        data   = {
            "total_bets":   report.total_bets,
            "bets_won":     report.bets_won,
            "bets_lost":    report.bets_lost,
            "total_staked": round(report.total_staked, 2),
            "total_payout": round(report.total_payout, 2),
            "house_edge":   round(report.house_edge, 2),
        }
        return StepResult("settle_bets", True, msg, data, None, ms), report
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult("settle_bets", False, "settlement failed", {}, str(e), ms), None
```

Note: this call site's `settle_week(week, db)` (line 523 above) does **not** pass `league_id` — it relies on `settle_week()`'s `league_id: int = 1` default, added in the most recent build. Flagged here since it's directly relevant to a race/settlement review: this function already has a real `league_id` in scope and simply isn't threading it through.
