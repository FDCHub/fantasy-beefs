# FR-8.7-LOG-1 — Feed logging must not convert committed settlement into reported failure

**Revision:** Rev1 (2026-07-24).

**Status:** SHIPPED.
**Implementation baseline:** HEAD `21ec171`, branch `remediation/foundation-phase-1`. Every line anchor and the red proof were measured against that tree.
**Shipped at:** `59be320` — 3 files changed, 367 insertions, 8 deletions. Pushed to `origin/remediation/foundation-phase-1`. **Not deployed.**
**Class:** Session ownership and failure containment. **Not money-path** — no ledger postings, no cents, no escrow, no rounding, no conservation change.
**Gate applied:** PostgreSQL regression suite. Opus Math Review skipped by ruling (no math to review).
**Supersedes:** the retracted locked shape in FR-8.7-LOG-2.

---

## 1. Issue summary

`settle_week` committed its economic transaction at line 781, then called `log_settlement_events(pending, db)` at 782 on its own session. That function commits at `feed/league_feed.py:297` — a third commit in the `settle_week` call graph, behind a name that reads as a logger.

If any part of the feed work raised, SQLAlchemy left the settlement session in a failed transaction. The report-building block at 785–800 then threw. Money durable; caller told it failed. `api/main.py:908` returned 500. `notifications/tuesday_sync.py:837` returned `StepResult(False, "settlement failed")`.

## 2. Why a fresh feed session alone was insufficient

This is the correction that FR-8.7-LOG-2's original ruling missed, and it is the substance of this spec.

`pending` holds ORM `Bet` objects owned by the settlement session (`settlement_engine.py:497-506`). `SessionLocal = sessionmaker(bind=engine)` at `db/schema.py:40` takes SQLAlchemy's default `expire_on_commit=True` — the string appears nowhere in the repo. So the commit at 781 expires every object in `pending`.

`log_settlement_events` then read `bet.beef_challenge_id` at `league_feed.py:248`. SQLAlchemy loads an expired attribute through `object_session(bet)` — the settlement session — regardless of which session the function was handed.

Measured, PostgreSQL 16 / SQLAlchemy 2.0.49: under a fresh-feed-session shape, the only SQL emitted during feed work was an expired-attribute refresh **on the settlement session**. A real server-side failure there poisoned it and the report block raised `InFailedSqlTransaction`.

**The safe boundary is therefore not "a separate session." It is: no settlement-owned ORM instance may be dereferenced inside the feed operation.**

## 3. Binding constraints

1. **The challenge-ID snapshot is built before the commit at 781.** Built after, it triggers the exact refresh the fix eliminates. Carries an inline invariant comment at line 783. **Do not move it below `db.commit()`.**
2. **`log_settlement_events` takes `list[int]`, never ORM objects.** A `list`-typed parameter invites a future attribute read that raises `AttributeError` inside the try/except, swallowing it and silently losing the week's feed events. The integer type makes the hole unreachable.
3. **The commit at `league_feed.py:297` is untouched.** LOG-2 declined to modify the function because the commit-on-passed-session pattern is module-wide (FR-8.7-LOG-3). Changing an input type does not touch that pattern, so the objection did not apply — but the commit is byte-identical and this edit does not diverge the function from its four siblings.
4. **Log with `%`-style lazy args, never `extra={}`.** Verified: `extra` renders nothing under this repo's plain stdlib logging (no `dictConfig`, no `fileConfig`, no custom formatter). The Q6 obligation to name league_id and week would have been silently unmet.

## 4. Changes as shipped

### 4a — `feed/league_feed.py`, lines 236–251 only

Signature became `settled_challenge_ids: list[int]`. Loop became `for cid in settled_challenge_ids:`. The `if cid is None or cid in seen: continue` guard and the `seen` set retained. Docstring rewritten to state that scalar IDs are required and no settlement-owned ORM instance may cross the boundary.

Everything from line 253 down, including the commit at 297, byte-identical. Lines 266 and 272 untouched (FR-8.7-LOG-5 deferral).

### 4b — `betting/settlement_engine.py`, imports

Existing `db.schema` import at line 34 extended with `SessionLocal` — no new import line. `_log = logging.getLogger(__name__)` added after the imports, matching `betting/per_bet_lock.py:33`. The local `SessionLocal` import in the `__main__` block and the two bare `logging.info` calls at 382 and 460 left alone.

### 4c — `betting/settlement_engine.py`, lines 781–782 replaced

Pre-commit sorted-set collection of `settled_challenge_ids`, filtering `None`, with the binding-invariant comment. Then `db.commit()`. Then the feed block guarded by `if settled_challenge_ids:`, opening `with SessionLocal() as feed_db:` and calling `log_settlement_events(settled_challenge_ids, feed_db)`. On `except Exception:` — `db.rollback()` first, then `_log.exception(...)` with `%`-style args naming week and league_id.

Lines 785 onward unchanged.

Diffstat: `settlement_engine.py` +27/-2, `league_feed.py` +10/-6.

## 5. Test — the ship gate

`test_fr87_log1_feed_isolation_pg.py`, PostgreSQL, 3 scenarios. First feed-path test coverage in the repo.

**Binding assertion:** while the real `log_settlement_events` executes, statements issued through the settlement session number exactly zero. Asserted on the success path and the forced-failure path.

**Liveness assertion:** statements through `feed_db` during the same phase exceed zero. Without it the binding assertion passes trivially on a skipped or mis-patched body.

Instrumentation: the real function is **wrapped, never mocked**. `do_orm_execute` and `after_begin` listeners on `sqlalchemy.orm.Session`, both gated on `_PHASE["feed"]`, both attributing by `is` comparison on the `Session` object.

**Trap, recorded:** do not attribute by connection. The pool hands both sessions the same DBAPI connection once the commit at 781 releases it, producing a false clean read. This was hit during design.

Red-to-green: 9 assertions red at baseline, all green after. Binding count read 13 on the success path and 8 on the forced-failure path before the fix, 0 after.

## 6. Regression evidence

Eight suites, 226 assertions, all green, all exit 0.

| Suite | Backend | Result |
|---|---|---|
| `test_fr87_log1_feed_isolation_pg.py` (new) | PG | all pass |
| `test_fr87_empty_week_completion_pg.py` | PG | 11/11 |
| `test_beef_settlement_escrow_close_pg.py` | PG | 27/27 |
| `test_fr87_prelock_validation_sqlite.py` | SQLite | 11/11 |
| `test_settle_the_lineup.py` | SQLite | 4/4 |
| `test_roster_slots_capture.py` | SQLite | 35/35 |
| `test_ledger.py` | SQLite | 47/47 |
| `test_ledger_beef_conversion.py` | SQLite | 12/12 |
| `test_pool_engine_conversion.py` | SQLite | 79/79 |

The two PG suites and the new test ran via the `test_support_postgres` harness against `pg-fantasy-test`. All six SQLite suites ran with a temp SQLite `DATABASE_URL` exported in the same shell invocation before Python started — floor asserted, not relying on an unconnected engine.

## 7. What this fix does and does not guarantee

**Guarantees:** a feed failure cannot convert a committed settlement into a reported failure.

**Does not guarantee:** that no post-commit failure can. The report block at 785–800 performs settlement-session work after the economic commit — `expire_all()`, `query(Wallet)`, lazy `w.team`. A failure there still raises after money is durable. No change at 782 reaches it. Tracked as **FR-8.7-LOG-4**.

## 8. Out of scope — explicit deferrals

| Deferred | ID |
|---|---|
| Report block remains an unprotected post-commit surface | FR-8.7-LOG-4 |
| `league_feed.py:266,272` compute payout as `amount * odds` while settlement pays actual escrow cents (FR-5.9/5.10) | FR-8.7-LOG-5 |
| Module-wide commit-on-passed-session pattern; five committing functions, `log_challenge_expired` diverging | FR-8.7-LOG-3 |
| Scenario 4 — forced failure via a real server-side error rather than a Python-level `RuntimeError` | FR-8.7-LOG-6 |
| Broader feed-path coverage | FR-8.7-LOG-6 |
| `recover_week` reaches 782 via `settle_week:1037` and inherits the report-block exposure | folded into LOG-4 |

`league_feed.py:266` and `:272` were neither edited nor commented, per ruling.

## 9. Verification method

All source claims read from live source, not from prior documents. The two target files were confirmed byte-identical to `21ec171`, and the branch tip served the same bytes, so anchors were current. Behaviour was measured on PostgreSQL 16 with SQLAlchemy pinned to 2.0.49 (the `requirements.txt` pin), not inferred.

Repo-wide caller audit across all 139 `.py` files returned three hits for `log_settlement_events`: the import at `settlement_engine.py:36`, the call at 782, the definition at `league_feed.py:236`. Sole caller confirmed, not asserted.
