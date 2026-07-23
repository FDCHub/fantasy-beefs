# FantasyBeefs Response Card Specification

## Rev 1.1 (Canonical)

**Status:** LOCKED

**Change log:**

* Rev 1.1 — Section 10: Revive restricted to the original issuer. Section 6: Countered card made perspective-aware (issuer actionable, recipient read-only). Section 11: recipient may see the read-only pending-counter view. No new card state introduced; taxonomy remains five cards.
* Rev 1.0 — Initial canonical specification.
**Owner:** FantasyBeefs Product Specification
**Purpose:** Defines every response card shown after a Versus Challenge is created. This document is the single source of truth for all response-card behavior. UI specifications shall reference this document rather than duplicate its contents.

---

# 1. Purpose

Response Cards communicate the lifecycle of a challenge after issuance.

They serve four purposes:

1. Show the current state.
2. Explain what happened.
3. Show what changed.
4. Present the only legal next action(s).

Response Cards never alter protocol behavior. They visualize the deterministic protocol defined in the Game Specification.

---

# 2. Supported Response Cards

Exactly five response cards exist.

| Card      | Terminal | User Action                |
| --------- | -------- | -------------------------- |
| Incoming  | No       | Accept / Counter / Decline |
| Accepted  | Yes      | View only                  |
| Countered | No       | Issuer: Accept / Decline · Recipient: View only |
| Declined  | Yes      | Revive                     |
| Expired   | Yes      | Revive                     |

No additional response cards may be introduced in Version 1.0.

---

# 3. Universal Card Layout

Every response card uses the same visual structure.

```
----------------------------------------------------

STATUS BADGE

Challenge Title

Opponent

Fantasy Week

------------------------------------

Original Challenge

------------------------------------

Current Terms

------------------------------------

Was → Is Comparison

------------------------------------

Explanation

------------------------------------

Primary Action Button(s)

----------------------------------------------------
```

Cards intentionally remain text-first.

No avatars.

No animations.

No sportsbook styling.

---

# 4. Incoming Card

## Purpose

Displayed to the challenged GM when an unanswered challenge exists.

This is the only card permitting negotiation.

---

### Status Badge

```
INCOMING
```

Yellow.

---

### Displays

Challenge

Opponent

Challenge Type

Current Odds

Current Stakes

Expiration Countdown

---

### Buttons

Primary

```
Accept
```

Secondary

```
Counter
```

Tertiary

```
Decline
```

---

### Behavior

Accept immediately executes the Handshake.

Counter proposes new issuer Anchor Stake only.

Decline immediately terminates the challenge.

No escrow moves during Counter.

---

# 5. Accepted Card

## Purpose

Displayed after both parties agree.

This is a permanent historical record.

---

### Status Badge

```
ACCEPTED
```

Green.

---

### Displays

Accepted Odds

Accepted Stakes

Handshake Time

Maximum Exposure

Final Lock Time

---

### Was / Is Table

If acceptance changed pricing from the original offer:

|                |  Was |   Is |
| -------------- | ---: | ---: |
| Odds           | +120 | +128 |
| Your Stake     |  $20 |  $20 |
| Opponent Stake |  $24 |  $26 |

Otherwise display:

```
No pricing changes at acceptance.
```

---

### Explanation

> Your opponent accepted the challenge.
>
> Odds were recalculated using current projections at the moment of acceptance.
>
> These accepted terms now establish the Handshake.
>
> Your maximum exposure can only stay the same or decrease before kickoff.

---

### Buttons

None.

Read only.

---

# 6. Countered Card

## Purpose

Displayed after the recipient proposes a different Anchor Stake.

The Countered card is perspective-aware. Both parties see the same card state, but the issuer view is actionable and the recipient view is read-only.

---

### Status Badge

```
COUNTERED
```

Blue.

---

## 6.1 Issuer View

The original issuer sees the actionable Countered card.

---

### Displays

Original Offer

Counter Offer

Current Preview Odds

Current Derived Stake

Expiration Countdown

---

### Was / Is Table

Example

|                |  Was |   Is |
| -------------- | ---: | ---: |
| Your Stake     |  $25 |  $40 |
| Opponent Stake |  $31 |  $50 |
| Odds           | +124 | +126 |

---

### Explanation

> Your opponent wants to play, but at a different stake.
>
> The counter changes only the issuer's Anchor Stake.
>
> Current odds and derived stakes shown here are previews and will be recalculated again if you accept.
>
> Accepting creates a new Handshake using then-current projections.

---

### Buttons

Primary

```
Accept Counter
```

Secondary

```
Decline
```

---

## 6.2 Recipient View

The recipient who sent the counter sees a read-only Counter Sent presentation.

---

### Displays

Proposed Stake

Preview Terms

Expiration Countdown

---

### Explanation

> You countered with a different stake.
>
> Your opponent must accept or decline.
>
> Terms shown here are previews and will be recalculated at acceptance.

---

### Buttons

None.

Read only.

---

## 6.3 Transition

When the issuer acts, both the issuer view and the recipient view transition together to the Accepted card or the appropriate terminal record.

---

### Rules

Countering never moves escrow.

Countering never creates a wager.

Countering never creates a second counter.

Only one counter may exist.

A counter cannot itself be countered.

---

# 7. Declined Card

## Purpose

Historical record that the recipient chose not to play.

---

### Status Badge

```
DECLINED
```

Gray.

---

### Displays

Original Challenge

Decline Timestamp

---

### Explanation

> Your opponent declined this challenge.
>
> No wager was created.
>
> Any issuer escrow reserved at challenge creation has been released.
>
> You may revive this challenge using current market pricing.

---

### Button

Primary

```
Revive Challenge
```

---

### Revive Behavior

Revive creates an entirely new challenge.

It does **not** reopen the original challenge.

The original remains permanently Declined.

The new challenge receives:

* new Challenge ID
* new timestamp
* new expiration
* fresh odds
* fresh derived stake
* fresh escrow

---

# 8. Expired Card

## Purpose

Historical record that the offer timed out.

---

### Status Badge

```
EXPIRED
```

Gray.

---

### Displays

Original Challenge

Expiration Timestamp

---

### Explanation

> This challenge expired before your opponent responded.
>
> No wager was created.
>
> Any issuer escrow reserved at challenge creation has been released.
>
> You may issue the challenge again using current market pricing.

---

### Button

Primary

```
Revive Challenge
```

Revive behavior is identical to Declined.

---

# 9. Was / Is Comparison Rules

Whenever a value changes before Handshake, response cards shall present a comparison table.

Applicable values include:

* Odds
* Anchor Stake
* Derived Stake
* Potential Win
* Potential Loss

Example

|                |  Was |   Is |
| -------------- | ---: | ---: |
| Odds           | +118 | +126 |
| Your Stake     |  $20 |  $20 |
| Opponent Stake |  $24 |  $26 |

Values that did not change may be omitted.

---

# 10. Revive Protocol

Revive is available only on:

* Declined
* Expired

Revive is available to the original issuer only. The recipient must create a new challenge from their own side.

Revive never reopens an existing challenge.

Instead it performs:

1. Build a new challenge.
2. Fetch current projections.
3. Recalculate odds.
4. Derive new opponent stake.
5. Validate both-side minimums.
6. Reserve issuer escrow.
7. Issue a new challenge.

This guarantees every revived challenge reflects the current market.

---

# 11. Per-Side Behavior

## Issuer

May see:

* Accepted
* Countered
* Declined
* Expired

Never sees Incoming.

---

## Recipient

May see:

* Incoming
* Countered — read-only pending-counter view
* Accepted

Never sees the actionable issuer Countered view.

Never sees Declined.

Never sees Expired.

---

# 12. Visual Language

All response cards use:

* Spartan typography
* White background
* Thin dividers
* No gradients
* No sportsbook styling
* No casino graphics
* Green / Yellow / Blue / Gray status badges only
* One primary action button maximum (except Incoming, which intentionally presents three actions)

---

# 13. Design Principles

Every response card must answer four questions within a few seconds:

1. **What happened?**
2. **What changed?**
3. **Why did it change?**
4. **What can I do now?**

If a card cannot answer all four, the design is incomplete.

---

# 14. Authority

This document is the canonical specification for FantasyBeefs Response Cards.

The following documents shall reference this specification rather than redefining response-card behavior:

* Mobile UI/UX Specification
* Web UI Specification
* Design System
* Frontend Component Library

In the event of any conflict, **this Response Card Specification governs**.
