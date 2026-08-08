# FantasyStakes — Client Architecture Specification, Version 1

**Status:** Governing — current
**Date:** 2026-08-04
**Applies to:** the MVP production client (modules 12–17)
**Selected approach:** Progressive enhancement — modular vanilla JavaScript

---

## 0. Authority

> This document governs the **implementation architecture** of the MVP client.
>
> `spec/SPEC_Mobile_UI_UX_Rev4_1.md` remains the Product of Record for visual design, navigation, screen purpose, user flow, user-visible terminology, layout, and visual behavior. **This specification selects an implementation approach; it does not reopen the accepted UX.**
>
> Where this document and Rev4.1 appear to disagree about what the user sees, Rev4.1 governs. Where they appear to disagree about how the client is structured, this document governs.

Upstream game, wager, accounting, settlement, and economy protocols remain authoritative for underlying mechanics. **§3 of this document is subordinate to them and exists to keep them authoritative.**

The canonical UI artifact is `spec/FantasyStakes_UIUX_Prototype_Rev4_1.html`, SHA-256 pinned in the Rev4.1 header, hosted byte-identically at `tools/prototype/index.html`. It is self-contained static HTML/CSS/JS with zero external dependencies. **The production client is built by progressively enhancing that accepted design, not by re-deriving it.**

---

## 1. Structure

The production client **must not** be one monolithic HTML file with global mutable state.

Proposed minimum structure. Exact filenames may be refined during implementation; the seven boundaries in §2–§8 are governing and may not be.

```
tools/
  index.html
  css/
    app.css
  js/
    app.js               bootstrap and composition root
    api.js               boundary 1 — the only request layer
    state.js             boundary 2 — the only client-state boundary
    navigation.js        five-tab routing
    formatting.js        display formatting of server-provided values
    components/          shared cards, summary strips, status badges,
                         horizontal rows, navigation
    screens/
      league.js
      action.js
      ledger.js
      wrap_up.js
      rules_settings.js
```

`tools/prototype/index.html` remains in place, unchanged and byte-identical to the canonical artifact. It is design authority and is not the production client.

---

## 2. Boundary 1 — API client

- **One shared request layer.** All server communication passes through `api.js`.
- Authentication and session handling live there and nowhere else.
- Error handling is **normalized** at this boundary: every screen receives errors in one shape.
- **No duplicated screen-specific fetch wrappers.** A screen that needs a new endpoint adds a method to the shared layer; it does not construct its own request.

---

## 3. Boundary 2 — State

- **One deliberate client-state boundary** (`state.js`).
- It may hold: league, user, week, balances, refresh status, and navigation.
- **No screen may maintain an independent financial truth.** A screen renders from the shared boundary; it does not keep a private copy of a balance, obligation, or settlement figure and reason from it.

---

## 4. Boundary 3 — Financial authority · **binding**

> **The browser may format and display server-returned values. It must not derive any financially authoritative value.**

### 4.1 Prohibited in client code

Client code must not independently:

- sum ledger entries to produce a balance or subtotal;
- calculate obligations;
- calculate escrow;
- calculate Current Settle;
- determine available Credits;
- determine payouts;
- reconcile accounts;
- infer settlement state from component line items.

### 4.2 Required of the server

**Any aggregate or subtotal carrying ledger, escrow, obligation, payout, or settlement meaning must be returned by the server as an authoritative field.**

Where the accepted Rev4.1 design shows such a figure and no endpoint currently returns it, the endpoint is extended. **The client is never the place the gap is closed.**

### 4.3 Permitted client arithmetic

Only non-authoritative visual behavior: dimensions, pagination, animation, and formatting a server-provided number.

Formatting means presentation of a value the server already computed — currency symbols, thousands separators, sign, decimal places, relative dates. It does not mean deriving the value.

### 4.4 Why this boundary exists

The accounting model's own axiom is that **balance is never a stored, directly-mutated number** — it is always derived from ledger entries by the server, and any code path that writes a balance directly is a defect by definition.

A browser that sums line items to produce a subtotal reintroduces exactly that defect on the display side, where it is harder to detect and impossible to test with the ledger suites. Two open findings already record this failure mode occurring **server-side**: one where a derived surface computes a payout with a retired formula, and one where a report states a payout against balances it read from the wrong source. In both, the ledger was right and the derived surface was wrong.

**The ledger is conserved; derived surfaces are where the errors live.** This boundary keeps the client from becoming another one.

---

## 5. Boundary 4 — Screens

Each of the five accepted screens is a **separate module**:

| Screen | Module | Backing endpoints exist |
|---|---|---|
| League | `screens/league.js` | ✅ |
| Action | `screens/action.js` | ✅ |
| Ledger | `screens/ledger.js` | ✅ |
| Wrap Up | `screens/wrap_up.js` | ✅ |
| Rules & Settings | `screens/rules_settings.js` | ✅ |

Shared **cards, summary strips, status badges, horizontal rows, and navigation must be reusable components** under `components/`. A visual element appearing on two screens is a component, not a copy.

---

## 6. Boundary 5 — Runtime states

The client must **explicitly** support all seven:

| State | Requirement |
|---|---|
| loading | Distinct from empty. Never render a zero where data has not arrived. |
| empty | A real empty result, distinguishable from loading and from failure. |
| stale | Data known to be older than the current week or refresh cycle must say so. |
| partial data | Some panels resolved, others not — render what resolved, mark what did not. |
| unauthorized | Session absent or rejected. Route to authentication; never render a blank screen. |
| API failure | The normalized error from boundary 1, surfaced legibly. |
| refresh in progress | Distinct from loading — existing data stays visible while it updates. |

**A zero, a blank, and a failure must never be visually identical.** On a money product, a balance that failed to load and a balance of zero are opposite facts.

`loading` and `stale` are load-bearing for this product specifically: ingestion is weekly and gated on data freshness, so "the number you are looking at is from last week" is a real state the client must be able to say.

---

## 7. Boundary 6 — Deployment

- Continue using the **existing FastAPI static-file surface** — the client is served from the application, not from a separate origin.
- **No separate frontend service and no frontend build platform for MVP**, unless a later *measured* blocker proves one necessary.

This preserves the current single-service Railway deployment: one build, one start command, one health check. It also keeps the client same-origin with the API, so no CORS or cross-origin session work is required for MVP.

---

## 8. Boundary 7 — Escape criterion

- **Do not reopen framework selection based on preference.**
- Reconsider **only** if modular progressive enhancement cannot satisfy a **named acceptance requirement** without substantial duplication or unsafe state handling.

A reconsideration must cite the specific acceptance requirement and demonstrate the duplication or the unsafe state handling. "It would be easier with a framework" is not a named acceptance requirement.

---

## 9. Conformance checks

Verifiable per screen, at the screen-level acceptance gate:

| # | Check | Method |
|---|---|---|
| 1 | No screen module constructs its own request | no `fetch(` / `XMLHttpRequest` outside `js/api.js` |
| 2 | No screen holds private financial state | no balance/obligation/payout field assigned outside `js/state.js` |
| 3 | **No client-side financial derivation** | no `reduce`/`+=`/`sum` over ledger, escrow, obligation, payout, or settlement collections in any screen or component |
| 4 | Every displayed aggregate is server-provided | each such figure traces to a named response field |
| 5 | All seven runtime states reachable | per-screen demonstration |
| 6 | Shared visuals are components | no duplicated card/badge/row markup across screens |
| 7 | Same-origin static serving | client loads from the FastAPI static surface with no external host |

**Check 3 is the one that matters most and is the easiest to violate accidentally** — a `reduce` that looks like innocuous display logic is exactly how a client acquires financial authority it was never granted.

---

## 10. Open dependencies

**Not resolved by this specification. Named so they are not discovered late.**

1. **§4.2 may require endpoint additions.** Where Rev4.1 shows an aggregate no endpoint returns, the server is extended. Which figures those are is determined per screen during build, not here.
2. **Rules & Settings is gated.** The commissioner-rules module is classified MVP SOURCE OF TRUTH — HIGH-RISK, SPEC AND TEST REQUIRED. **Do not wire settlement-affecting rule execution to a client before that module has a governing contract and direct tests.**
3. **Wrap Up has no content contract.** The screen's presentation is governed by Rev4.1; what the wrap-up says is governed by nothing. Recorded, not resolved.
