# Fantasy Beefs — BAB Top-Off UI/UX Design Spec

**Date:** 2026-07-21
**Branch:** UI/UX feature branch (folds into the merge-back package)
**Status:** Six surfaces designed and locked. Backend rules flagged for the main VAL-10 thread — this spec designs *to* them, it does not implement them.

---

## 0 — What a BAB Top-Off is

A BAB Top-Off gives a GM additional in-app BAB during the season. No real money moves through Fantasy Beefs; any real-money settlement happens privately outside the app. The app only records the league's agreed BAB balances and activity. This makes a top-off a **BAB issuance event** (internal accounting), which is why it lives in the app — unlike buy-in confirmation, which was cut because the app tracks no payments.

---

## 1 — Locked terminology (used verbatim on every surface)

- **Season BAB Allocation** — the full season amount assigned to a GM under the League Economy Tier. May be released over time; NOT the opening wallet balance.
- **League Economy Tier** — the commissioner's economy configuration (allocation, weekly minimum, fees, split). Not a "buy-in" or payment.
- **BAB Top-Off Cap** — the max total extra BAB a GM may receive all season. = Season BAB Allocation × locked cap percentage.
- **Top-Offs received** — cumulative BAB already issued to the GM this season.
- **Remaining BAB Top-Off Capacity** — cap minus received. The gold number.
- **Available to Bet** — Wallet balance + current-week released BAB. Committed/escrowed BAB is NOT subtracted again (it already left the spendable accounts). "Free to bet" is retired.
- **Rejected in full** — the over-cap error state. No partial approval, no cap, no rewrite.
- **Commissioner Self-Approved** — the self-approval disclosure label.
- **Locked for this season** — the cap setting's post-initialization state. The cap locks at **season initialization** (snapshot point), not merely "at kickoff."

Currency: every money figure carries `$` per the global rule (BAB and real dollars alike). The "not real cash" message lives in the rules copy, not the number format.

---

## 2 — The surfaces

**2.1 — GM entry point (My Ledger).**
The Top-offs row shows the cap math **before** the button, so the GM sees eligibility without opening anything:
> **BAB Top-Offs** — Cap: $140 · Received: $60 · Remaining: $80 — **[Request Top-Off]**

Secondary entry point: when a wager fails for insufficient BAB, the error offers a **[Request BAB Top-Off]** button that **deep-links into the same request flow** — not a special wager-specific top-off:
> You don't have enough BAB for this wager. Available to Bet: $20. [Request BAB Top-Off]

**2.2 — GM request flow (four panels).**
- *Panel 1 — Summary:* Current BAB Wallet, Available to Bet, BAB Top-Off Cap, Top-Offs received this season, Remaining BAB Top-Off Capacity, league cap %, and the "BAB is internal; real-world settlement happens outside the app" note. Action: **Request BAB**.
- *Panel 2 — Enter Amount:* maximum shown prominently ("You may request up to $80"), amount field with quick picks ($10 / $25 / $50 / Maximum). No automatic reduction.
- *Panel 3 — Review:* Requested $50 · Remaining before $80 · Remaining if approved $30 · "Approval required from Commissioner" · "No BAB is added until approval." Action: **Submit Request**.
- *Panel 4 — Submitted:* "Top-Off Request Pending" with requested amount, submit time, "Commissioner decision pending." Actions: View request · Cancel request (while cancellation remains permitted).

The pending request also shows as a **status row on My Ledger** — it does **not** go into the wager-focused My Action feed.

**2.3 — Commissioner Pending Top-Offs Queue (Commish zone).**
Badge: "BAB Top-Off Requests · 3." Each card: GM and team, requested amount, BAB Top-Off Cap, Top-Offs already issued, remaining capacity before approval, submit time, Approve/Reject. Tapping **Approve opens a review panel — not one-tap issuance.**

*Approval panel:* Requested $50 · Current remaining capacity $80 · Remaining after approval $30 · "Capacity will be checked again when you approve" · activity-log disclosure. Actions: **Approve $50** · Reject. If capacity changed at approval time, the request is **rejected in full** (no partial): "This request can no longer be approved. The GM now has only $30 of Remaining BAB Top-Off Capacity. The request was rejected in full."

**2.4 — Commissioner Self-Approval (deliberate friction).**
No one-screen "Add BAB" control, ever — even for a sole commissioner. He must: (1) submit a normal request from My Ledger, (2) see it in the queue, (3) open it as a self-approval, (4) give a mandatory reason, (5) confirm public disclosure. The self-approval screen is visually distinct:
> **Commissioner Self-Approval** — You are requesting and approving BAB for your own team. This uses the same cap as every other GM and will be disclosed in the league activity log.
> Required: **Reason for self-approval** (text)
> Required: ☐ I understand this self-approval will be visible to the league.
> Action: **Self-Approve $50**

Same cap as everyone; cannot raise own cap. This friction makes self-issuance deliberate without blocking the commissioner from playing as a GM.

**2.5 — BAB Top-Off Cap Setting.**
Location: **Rules & Settings → Commissioner → Locked Season Settings.** Snap choices only: Disabled 0% / 50% / 100% (recommended) / 150% / 200%. No custom commissioner-only amount, no mid-season override. Live example:
> Season BAB Allocation: $140 · Selected cap: 150% · Maximum season top-offs per GM: $210
- *Before initialization:* "Editable until the season is initialized."
- *After initialization:* "150% · Locked for this season · Maximum top-offs per GM: $210."

**Lock point: the cap locks when the commissioner initializes the season, and its value is snapshotted then** — not merely "at kickoff." This is an enforcement point, not wording.

**Cap math (terminology, aligned with VAL-10):** BAB Top-Off Cap = **Season BAB Allocation** × locked cap percentage. "Season BAB Allocation" is the full season amount assigned under the League Economy Tier; it may be released over time rather than deposited into the spendable wallet immediately. Do not conflate it with opening wallet balance.

**2.6 — Rejection & status states (kept distinct by design).**
- *Top-offs disabled:* "This league does not permit BAB Top-Offs."
- *No valid season allocation:* "Your BAB Top-Off Cap cannot be calculated because your Season BAB Allocation is unavailable. Contact the Commissioner."
- *Cap exhausted:* "You have used your full BAB Top-Off Cap for this season."
- *Requested above remaining capacity:* "You requested $100, but your Remaining BAB Top-Off Capacity is $80. Submit a new amount."
- *Rejected by commissioner:* "Your $50 Top-Off request was rejected by the Commissioner."

**2.7 — Notifications (deep-link to the relevant request).**
Top-Off request submitted · New Top-Off request for Commissioner · Top-Off approved · Top-Off rejected · Top-Off request no longer eligible · Commissioner self-approved Top-Off.

**2.8 — Rules section copy** (drop-in text for the Rules zone):
> **BAB Top-Offs**
> Each GM may request additional BAB during the season, subject to the league's locked BAB Top-Off Cap. The same cap applies to every GM, including the commissioner. Requests above Remaining BAB Top-Off Capacity are rejected in full. The commissioner approves requests. When no other eligible commissioner exists, the commissioner may self-approve within the same cap, with a written reason and public disclosure.
> BAB is an in-app league accounting unit. Fantasy Beefs does not collect, hold, transfer, or settle real money.

**2.9 — Activity-log entries** (exact strings):
> BAB Top-Off Approved: Team Alpha received $50. Approved by Commissioner.
> Commissioner Self-Approved BAB Top-Off: Commissioner's Team received $50. Reason: Additional BAB for continued league wagering.

---

## 3 — Backend obligations (for the main VAL-10 thread — NOT implemented here)

These are money-path rules the UI is designed to surface. They must be built and gated in the main thread against the live top-off code (`create_bet_topup` / approval path), subject to the money-path review gate. Recorded here so they aren't lost.

| # | Rule | UI surfaces it |
|---|---|---|
| B1 | **Reject in full (R6b — Fraser's ruling, reinstate/confirm in main).** A request exceeding Remaining BAB Top-Off Capacity is rejected without creating or modifying a FaabTransaction. Response states the remaining eligible amount. No partial approval, auto-cap, or silent rewrite. Requested = approved = issued for every applied top-off. | 2.1 reject state; 2.5 rules copy |
| B2 | **Cap re-check at approval.** If prior issuance consumed capacity after the request was created, approval is blocked and the request is rejected in full at approval time (with the same headroom message). | 2.2 queue footer |
| B3 | **Sole-approver gate for self-approval.** Self-approval is offered only when no other eligible commissioner exists. Requires a written reason. Same cap; no cap override. Logged with the disclosure label. | 2.3 self-approval state |
| B4 | **Cap locked at season init.** The cap must be selected before season initialization and becomes immutable once the season is live. Applies equally to all GMs. | 2.4 locked state |
| B5 | **Sub-cent prevention.** Requests must reject sub-cent amounts (integer-cents discipline, consistent with the ledger). | 2.1 amount field |
| B6 | **Issuance is not external capital.** An approved top-off debits a league-season BAB issuance account and credits the GM's wallet — it does NOT debit `world` (that's reserved for real external capital like buy-ins). VAL-10 recon found no such issuance account or door exists yet; both are new keys to pin, and approver/request provenance must be persisted (VAL-10 found approver identity and request↔credit linkage currently absent). | all approval surfaces |

---

## 4 — Prototype status

All six surfaces are wired into the phone prototype (`tools/prototype/index.html`): GM request + reject on My Ledger; pending queue + approve/reject + self-approval demo in the Commish zone. Cap setting shown in the inline design (Settings-zone wiring can follow). Dummy data; navigation and states only — no real logic.
