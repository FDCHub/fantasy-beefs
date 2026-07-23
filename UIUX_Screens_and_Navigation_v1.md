# Fantasy Beefs — UI/UX Screens & Navigation

**Status:** DRAFT — captured 2026-07-09/10. Backend work this pause was
waiting on (Session B2, Finding 5.2) is now COMPLETE — see
`FantasyBeefs_MVP_Dev_Roadmap_v5.md`. This document is ready to resume as
its own frontend build session whenever prioritized. Not yet folded into
the Master Plan's main body (Zone 2) — sits as its own standalone doc
until a UI/UX build session formally adopts it.

---

## Tab structure, ruled

My League → My Action → My Ledger → My Team → Wrap Up → Rules & Settings

---

## Renamed this session

**My Account → My Ledger.** More accurate — a GM's page isn't a single
balance, it's their share of the total ledger (wallet, reserve, Championship
contribution, Skunk obligation, receivables). Fits Tier 2's own rule (plain
English, functional, no decoding required) better than "Account" did.
Complementary to **The Sheet** (Tier 1, the season-end master ledger) —
copy should clarify once: "My Ledger updates all season; The Sheet is the
final word at season's end."

---

## Ruled this session

- **My Commish and Rules merge** into one tab, **Rules & Settings**.
  Read-only settings for every GM; commissioner sees the same tab with
  editing unlocked (toggle, editable Skunk amount, buy-in confirmation
  queue, settlement review).
- **Weekly Wrap-Up gets its own tab**, positioned before Rules & Settings,
  with a browsable archive of past weeks — not buried in another tab, per
  the Creative Bible's "nothing gets forgotten" principle.
- **My Team stays coming-soon for MVP** — confirmed no legit reason to build
  it before launch. Yahoo already shows roster/lineup natively; Beefs is
  read-only against Yahoo forever, so My Team would only ever be a worse
  mirror of an app GMs already use.
- **My League** needs all 4 Versus bet types (Moneyline, Spread, O/U, The
  Lineup), consistently displayed together on every card — not three
  grouped as "Versus" plus Lineup styled as a separate player-prop format.
  **My League splits into two swipeable carousels, not one long scroll:**
  - **Official Matchups** — 6 cards (12-team league), your actual Yahoo
    schedule for the week. Posted odds, computed by the house (Monte
    Carlo), tap to accept directly — no negotiation.
  - **Beef — Open Contracts** — your team against each of the other 10 GMs
    not on your official schedule this week. Same 4 bet types, same odds
    engine, but routed through the Beef propose/counter/accept flow
    ("Putting Out a Contract" → "Taking the Action" / "The Counter") since
    there's no natural pairing for the house to pre-post. **Explicitly
    tagged as not affecting W/L standings** — it's a virtual matchup for
    GMs who want action against someone they're not officially playing.
  - **Clarified mechanic (2026-07-09):** Beef is not a separate bet
    category. It's the acceptance mechanism for the same 4 Versus bet
    types when applied outside the official matchup — confirmed by Fraser
    directly, consistent with the P2.2 spec's line "Beefs transcend the
    weekly matchup — any GM can challenge any GM any week."
- **Pool bets** — all 4 (Biggest Winner, Worst Beat, Special Teams
  Supremacy, Bench Burn) stay in their own labeled section on My League,
  below both carousels — league-wide, no matchup required.
- **My Action** shows: countdown to lock, weekly-minimum progress bar
  ("$X of $10"), this-week's reserve remaining, net winnings/losses (season
  to date), a lightweight obligation nudge (amount + reason, links out to
  My Ledger — not full detail duplicated here), open action list,
  settled-this-week list.
- **My Ledger** is the full ledger / source of truth: The Envelope
  (wagerable vs. reserved split), Championship Pot (with
  collected-vs-contingent breakdown per B2-6.3-R), Skunk Fee Pot, full
  shortfall/receivable breakdown, top-off tracking, buy-in status.
- **Top-offs are tracked and added via My Ledger.**
- **Reserve-ceiling formula reconfirmed:**
  `reserve_needed = remaining_regular_season_weeks × $10`. Prevents
  overspending the $140 betting portion early in the season; distinct from
  Championship's fully-locked $80 reserve. Still unbuilt, launch-blocking,
  already flagged in the Master Plan (blocks the GM pre-bet limit
  notification and the My Action BAB display).

---

## Open, not yet ruled — pick up after backend work

1. **Winnings bucket** — is it a separate tracked account, or a computed
   display split over one wallet balance? Changes whether "spend weekly
   minimum first, then roll to winnings" is a real posting-order rule or
   just a UI presentation choice.
2. **Does the reserve ceiling protect winnings too**, or only the original
   $140 principal? Affects how much a GM can wager the moment they have any
   winnings on the books.
3. **Rules & Settings for the commissioner** — same screen with role-gated
   controls (recommended), or a distinct "Manage" mode within the tab?
4. **Commissioner-approved top-up mechanism**, living in My Action —
   deferred entirely, not yet discussed. Separate from the reserve-ceiling
   formula.
5. **Weekly Wrap-Up vs. League Feed** — same surface, or two distinct
   things (one weekly narrative drop with an archive, one continuous live
   stream of accepted bets/settlements/trash talk)?

---

## Reference — mockup file

`fantasy_beefs_mockup.html`, six-tab version, current as of 2026-07-09. My
League shows two swipeable carousels (Official Matchups, Beef — Open
Contracts) with all 4 Versus bet types consistent on every card, plus the
Pool Bets section below. My Action shows minimum progress + reserve +
nudge. My Team is coming-soon. Rules (read-only) and My Commish (edit
surface) still exist as two separate tabs in this mockup — **not yet
merged into the single Rules & Settings tab** ruled earlier this session.
That merge, plus the My Account → My Ledger rename, are the two known gaps
between this mockup file and the ruled tab structure — next mockup pass
should close both.
