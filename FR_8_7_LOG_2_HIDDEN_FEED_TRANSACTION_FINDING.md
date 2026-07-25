# FR-8.7-LOG-2 — Feed logger owns a hidden third transaction on the settlement session

**Revision:** **Rev2 (2026-07-24) — AMENDED, not original.** Amended per `Findings_Register` §18.2 after two independent reviews converged (no cross-contamination) on a defect this finding never examined. The four amendments below are authoritative over the Rev1 text where they conflict; the Rev1 rulings are **retained in place** — the overruled Q4 and the retracted snippet remain visible as history.
**Status:** Finding, ruled (Rev1); **AMENDED Rev2** — no longer closed on the original terms. Gates FR-8.7-LOG-1. Rev1 source verified against HEAD `21ec171`; Rev2 amendments verified against the shipped fix at `59be320`.
**Class:** Architecture / session-lifecycle. Not economic (no BAB change), but changes the failure surface of the settlement service and must be resolved before LOG-1's fix is designed.

---

## Rev2 amendments (2026-07-24)

Two independent reviews converged, with no cross-contamination, on a defect this finding never examined. These amendments govern where they conflict with the Rev1 text below; the Rev1 rulings are retained, annotated, as history.

**Amendment 1 — Option 1 (call-site isolation) was insufficient; it does not isolate.** `pending` holds ORM `Bet` objects owned by the settlement session; `expire_on_commit` defaults `True` (the string appears nowhere in the repo). Reading `bet.beef_challenge_id` at `league_feed.py:248` refreshes through `object_session(bet)` — the *settlement* session — no matter which session the function was handed. Measured on PostgreSQL 16. **Corrected fix (shipped, `59be320`):** `settle_week` collects `settled_challenge_ids` as SCALAR ints from `pending` BEFORE `db.commit()`, and `log_settlement_events` now takes `settled_challenge_ids: list[int]` — no settlement-owned ORM object crosses into the feed session.

**Amendment 2 — Q4 OVERRULED.** "No settlement-session rollback" is false for the shape as ruled, and too broad even for the corrected shape. Its reasoning failed on both halves: the report block runs *after* the except clause, so no report state exists at the catch, and that block performs only reads — there was nothing uncommitted to discard. `db.rollback()` after 781 is a verified no-op on a healthy idle session and is **retained defensively** in the shipped fix. The defensible claim is narrow: *a failure originating in the isolated feed transaction cannot poison the settlement session.* Post-commit failures arising in the report block itself remain possible — tracked as **FR-8.7-LOG-4**.

**Amendment 3 — recon classification.** LOG-2 never examined settlement-owned ORM objects crossing the proposed boundary; the Rev1 text mentions `beef_challenge_id`, ORM object ownership, and session expiry nowhere. **This was an existence-check / recon miss, not a rejected argument** — the corrective attaches to the recon step, not to the reasoning.

**Amendment 4 — the Rev1 "locked shape" snippet is RETRACTED.** Four verified defects in that snippet:

| # | Defect | Consequence |
|---|---|---|
| 1 | False session isolation | Amendment 1 |
| 2 | `SessionLocal` not imported at module scope — only at `settlement_engine.py:1046` inside `__main__` | `NameError` |
| 3 | `logger` undefined in that module | `NameError` **inside the except block** — converts a swallowed feed failure into a raised one after commit. LOG-1's bug delivered by LOG-1's fix |
| 4 | `extra={...}` renders nothing under this repo's plain stdlib logging | The Q6 signal fires without naming league or week — the one thing Q6 exists to guarantee |

The shipped fix (`59be320`) corrects all four: module-scope `from db.schema import … SessionLocal …`; `_log = logging.getLogger(__name__)`; `%`-style lazy args naming `week` and `league_id` (no `extra={}`); the scalar-id boundary (Amendment 1).

**Sustained and upgraded (asserted → verified):** Q3 sole caller (repo-wide grep, all 139 `.py` files, three hits); Q5 atomicity (forced mid-batch failure persisted 0 rows); Q6 no idempotency (`feed_events` carries only a non-unique `Index("ix_feed_league_created", league_id, created_at)`); LOG-3 count accurate as written (commits at 135/161/185/233/297 — five total, four siblings; the 428 commit sits in a `__main__` demo).

---

## Issue summary

`settle_week` performs its economic commit at line 781 (payouts, ledger postings, COMPLETED flip — all durable there). It then calls `log_settlement_events(pending, db)` at line 782, passing **its own session**. `log_settlement_events` (`feed/league_feed.py`) does not merely log: it writes feed rows on that shared session and **independently commits at `feed/league_feed.py:297`**. This is a third commit in the `settle_week` call graph, hidden behind a function named as a logger.

Three consequences, all verified:

1. **Hidden transaction ownership.** A function named `log_settlement_events` owns and commits a transaction on the caller's session. Nothing in the name signals that it commits, and the 6d spec's crash-surface map — source-locally correct that `settle_week` itself contains two commits (781, and recovery's 1032) — understates the call graph, which performs a third commit at 782 during `settle_week` execution.

2. **Session poisoning.** If any query, insert, flush, or the commit inside `log_settlement_events` raises, SQLAlchemy leaves the shared session in a failed transaction state. The post-782 report-building block (`db.expire_all()` then `db.query(Wallet)…`) then throws `PendingRollbackError`. So a feed-logging failure does not merely lose feed events — it prevents `settle_week` from building and returning its report, causing `settle_week` to raise **after** the economic settlement already committed. This is the mechanism behind LOG-1's misreport: the money is durable, the caller sees an exception.

3. **No feed idempotency.** The feed-event table has **no unique constraint and no natural key** (`league_id, week, event_type, …` are not uniquely indexed). A re-run of `log_settlement_events` double-writes every event. Retry or backfill of the whole call is therefore **not safe** without added idempotency — partial feed writes cannot be re-driven cleanly.

## The six questions, ruled

**1. Should `log_settlement_events` continue committing internally?**
**No.** A function named as a logger owning a commit on the caller's session is the root coupling. Ruling: it should not commit the caller's economic session.

**2. Should it flush only and let the caller own the feed transaction?**
**Rejected in favor of Q3.** Flush-only on the shared session still couples feed failure to the settlement session — a flush can raise and poison the session just as a commit can. Flush-only does not remove the poisoning risk; it only moves the commit. Not sufficient.

**3. Should feed logging use a separate session so its failure cannot poison the settlement/report session?**
**Yes — via isolation at `settle_week`'s call site (Option 1), NOT by changing `log_settlement_events` itself.** Caller audit (verified, HEAD `21ec171`): `settle_week` at line 782 is the **sole production caller** of `log_settlement_events`. The change is therefore made where the problem is — in `settle_week`, which opens its own fresh `SessionLocal()` for the feed write and passes *that* to `log_settlement_events`, leaving its economic/report session untouched by any feed work. `log_settlement_events` itself is not modified: it continues to commit whatever session it is handed, which is now a throwaway feed session, not the settlement session. A failure in the feed session cannot poison the settlement session, so the post-782 report-building block runs cleanly.

Why isolate at the call site rather than change the function: the audit found the hidden-commit-on-caller's-session pattern is **module-wide** in `feed/league_feed.py` — `log_settlement_events` is one of several public functions that commit a passed-in session (see the separate finding note below). Changing `log_settlement_events`'s session ownership would either diverge it from its siblings (inconsistent module) or invite a module-wide refactor (scope creep on a money-path fix). Isolating at `settle_week`'s call site fixes the settlement poisoning without touching the feed module's convention at all. Smallest blast radius; leaves the broader pattern for its own finding.

**4. What rollback is mandatory if feed work fails?**

> **⚠ OVERRULED — Rev2 Amendment 2.** "No settlement-session rollback" is false as ruled and too broad even corrected. `db.rollback()` after 781 IS retained defensively (a verified no-op on a healthy idle session). Narrow defensible claim: a failure originating in the isolated feed transaction cannot poison the settlement session; report-block post-commit failures remain possible (FR-8.7-LOG-4). The Rev1 ruling below is retained as history.

With Option 1 (call-site isolation) adopted, the settlement session is **never** part of the failed feed transaction — the feed work runs entirely on a separate `feed_db`. Therefore **no rollback of the settlement session is performed**, and none should be. A defensive `db.rollback()` on the settlement session would roll back a healthy session *after* its successful economic commit at 781, discarding valid uncommitted report-building state for no reason — it solves a poisoning problem that call-site isolation has already eliminated. The mandatory rollback is on the **feed session alone**, and it is handled automatically: `with SessionLocal() as feed_db:` rolls back and closes `feed_db` on any exception via its context manager. The settlement/report session remains untouched and usable. Verified basis: the post-781 report-building queries only re-read economic state that 781 made durable; with the feed failure quarantined to `feed_db`, those queries never see a poisoned session and run cleanly.

**5. Are partial feed events acceptable, or must all events for the week commit atomically?**
Because the feed session is separate and commits once, all events for the week commit atomically **within the feed session** — either the whole feed batch lands or none does (its single commit is all-or-nothing). Partial feed events are therefore not a normal outcome. A crash mid-feed-write rolls back the whole batch. This is acceptable: a week with no feed events is recoverable (Q6); a week with *half* its feed events would not be, given no idempotency, so all-or-nothing is the safe design.

**6. How is a missing feed batch surfaced for later retry or backfill?**
Given **no feed idempotency** (verified: no unique constraint), automatic retry is unsafe — it double-writes. Ruling: a feed-batch failure is surfaced as an **operational signal** (reliable secondary error log naming league_id, week, and the failure), not auto-retried. Backfill, if ever needed, requires either (a) adding a unique constraint / natural key to the feed table first, or (b) a manual, idempotency-checked repair. Backfill is explicitly **out of scope** for LOG-1/LOG-2 and noted as a separate future finding if it becomes necessary. The immediate obligation is that the failure is *visible*, not that it is *recovered*.

## What this rules for LOG-1

LOG-1's fix is now shaped by LOG-2:

- `settle_week` opens a **fresh `SessionLocal()`** for the feed write and passes it to `log_settlement_events` (Q3, Option 1). `log_settlement_events` is **not** modified — it commits the throwaway feed session it is handed, never the settlement session. This is the structural half of the fix, and it lives entirely at `settle_week`'s call site.
- `settle_week`'s call at 782 is wrapped so a feed failure is caught, a reliable secondary error logged (Q6 — operational visibility), and the successful `SettlementReport` still returned (the truthful-success obligation). The feed session's own context manager handles its rollback/close; the settlement session is **not** rolled back — it was never part of the failed feed transaction (Q4). Locked shape:

> **⚠ RETRACTED — Rev2 Amendment 4.** The snippet below has four verified defects: false session isolation (Amendment 1); `SessionLocal` unimported at module scope; `logger` undefined → `NameError` inside the except (LOG-1's bug delivered by LOG-1's fix); `extra={}` renders nothing under this repo's plain stdlib logging. It is retained as history — **do not use it.** The shipped fix at `59be320` (module-scope `SessionLocal`, `_log = logging.getLogger(__name__)`, `%`-style args naming week+league_id, scalar-id boundary, defensive `db.rollback()`) is authoritative.

  ```python
  try:
      with SessionLocal() as feed_db:
          log_settlement_events(pending, feed_db)
  except Exception:
      logger.exception(
          "Settlement completed but feed logging failed",
          extra={"league_id": league_id, "week": week},
      )
  # continue building and returning the successful report on the untouched
  # settlement session
  ```

- Both live callers (`api/main.py` 500-on-exception, `tuesday_sync.py` `StepResult(False, "settlement failed")`) currently misreport a post-commit feed failure as a settlement failure. Once LOG-1 stops `settle_week` from raising on feed failure, **those callers automatically stop misreporting** — the exception they were catching no longer occurs. No coordinated caller change is required, *provided* the fix reliably prevents the raise. That reliability is why call-site session isolation (Q3) is necessary and a bare try/except on the shared session insufficient: only a feed session fully separate from the settlement/report session guarantees the post-782 report block cannot throw.

## 6d spec amendment (deferred, noted)

The 6d crash-surface map should eventually note: line 781 remains the economic atomicity boundary; line 782 invokes a **separate feed transaction** (its own commit). This adds no eighth economic crash scenario — the feed transaction carries no BAB — but the spec should not imply only three commits exist across the full `settle_week` call graph. To be amended when 6d next revised; not blocking.

## Separate finding noted — module-wide hidden-commit pattern (FR-8.7-LOG-3, candidate)

The caller audit found that `log_settlement_events` is **not** the only function in `feed/league_feed.py` that commits a passed-in session — **four** sibling public functions share the commit-the-caller's-session pattern, while `log_challenge_expired` inconsistently does **not** commit. That inconsistency is itself the signal: the pattern is neither uniform nor deliberate-looking, so it is a latent architectural coupling rather than an intended contract. Any of the four, handed a caller's economic/request session, can commit or poison it; `log_challenge_expired`'s divergence means callers cannot even rely on a consistent rule. `settle_week` is the only path LOG-1/LOG-2 must fix, so the broader pattern is **out of scope here** and recorded as a candidate separate finding (FR-8.7-LOG-3) for whenever the feed module is next touched. It is not launch-blocking and not a money-path defect — no BAB flows through feed events. Flagged so it is a known, recorded coupling rather than a surprise later.

## Options considered (for the record)

| Option | Ruling |
|---|---|
| Leave call as-is; wrap 782 in bare try/except on the settlement session | **Rejected** — bare swallow leaves session poisoned; report block throws `PendingRollbackError`; `settle_week` still raises. |
| Flush-only, caller owns feed commit (Q2) | **Rejected** — flush can still poison the shared session; moves the commit, not the risk. |
| Change `log_settlement_events` to open its own session | **Rejected for LOG-1** — the commit pattern is module-wide; changing this one function diverges it from its siblings or invites a module-wide refactor (scope creep on a money-path fix). |
| **Isolate at `settle_week`'s call site: pass a fresh feed session (Q3, Option 1)** | **ADOPTED** — `settle_week` sole caller (verified); fresh feed session cannot poison settlement/report session; feed module untouched; smallest blast radius. |
| Add feed idempotency + auto-retry | **Deferred** — requires a unique constraint the table lacks; out of scope; future finding if backfill ever needed. |

## Recommendation & reasoning

Adopt Q3 via Option 1 (call-site isolation: `settle_week` opens a fresh feed session) as the structural fix and build LOG-1's behavioral handler on top of it — catch the feed exception, emit operational-visibility logging (Q6), return the successful report, and perform **no** rollback of the settlement session (Q4: it was never in the failed feed transaction; the feed session's context manager handles its own cleanup). Reasoning: the economic transaction is already complete at 781; feed failure should not contaminate the session needed to build the truthful settlement report. Call-site session isolation is the only option that guarantees the report block cannot throw, which is what lets both live callers stop misreporting without a coordinated change. Independent review required before LOG-1 ships — it changes the settlement service's observed failure contract, even though it touches no BAB.
