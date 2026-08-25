# FINDING — the demo showcase's FantasyStakes Matchups are invisible to the Action read model

**Raised:** UIRECON Wave 4B, while wiring the settled-wager result card (§13).
**Status:** **CLOSED** by *UIRECON Wave 4 demo matchup visibility reconciliation*.
The fix is recorded in the Resolution section at the foot of this file; the
diagnosis below is preserved as written, including the two places it was wrong.
**Severity when open:** the demo showed a GM zero FantasyStakes Matchups, on
every tab, in every week — including the seven weeks in which that GM
demonstrably wagered.

> **Two corrections to the original diagnosis, found during the fix.**
>
> 1. The new-model entry point is named **`issue_proposal_challenge`**
>    (`beefs/proposal_lifecycle.py:467`), not `open_challenge`. The name used
>    below does not exist in the repository.
> 2. The finding treated the legacy engine as the wrong path for the demo to be
>    on. It is not: `betting/versus_legacy_guard.py` classifies
>    `beefs.beef_engine` as a **governed** FantasyStakes path — the product it
>    exists to refuse is the single-GM `POST /bets/place` wager, which has no
>    `beef_challenge_id`. The engine creates real GM-versus-GM matchups that
>    fund, settle and post to the ledger. The defect was one unset column, not
>    the choice of path.

---

## What was observed

Running the application against a seeded showcase database (`fs_w3verify_test`,
PostgreSQL 16, demo league id 1, visitor seated on ordinal 7 / *Pain Sanders*):

```
GET /league/1/action/me
  → counts {action: 0, waiting: 0, live: 0, completed: 0}
```

Wrap Up therefore reports *"No wagers for week 11"* on the live week and *"No
wagers for week 10"* on a past one, and the Action tab draws four empty rails.

The database says otherwise. Team 7 is a participant in eight challenges, seven
of them settled with a terminal `bets.status` on both sides:

| challenge | week | challenger bet | challenged bet |
|---|---|---|---|
| 3  | 1  | won     | lost    |
| 5  | 2  | won     | lost    |
| 7  | 3  | won     | lost    |
| 13 | 5  | lost    | won     |
| 16 | 6  | won     | lost    |
| 20 | 7  | lost    | won     |
| 25 | 9  | won     | lost    |
| 32 | 11 | pending | pending |

## Why the read model cannot see them

`reports/action_read_model.gm_action_state` selects on the league:

```python
.filter(BeefChallenge.league_id == league_id, ...)
```

Every challenge in the showcase carries `league_id = NULL`:

```
 no_league | new_model | count
-----------+-----------+-------
        33 |         0 |    33
```

Two challenge-creation paths coexist in the corpus, and they populate different
columns:

* `beefs/proposal_lifecycle.open_challenge` — the **new model**. Sets
  `league_id`, `response_status`, `challenge_mode`, `wager_type`. This is the
  shape `action_read_model` reads.
* `beefs/beef_engine.issue_challenge` — the **legacy** path. Sets `status`,
  `challenger_odds`, `challenged_odds` and the rest of the legacy columns, and
  sets **no `league_id`** (see `beef_engine.py:1039`).

`demo/gameplay.py` drives the legacy path — `issue_challenge` followed by
`respond_to_challenge(accept=True)` — so every wager the showcase plays out is a
legacy-model row with a null league, and the read model correctly reports that
this GM has no wagers *in league 1*.

The `league_id` filter dates from `ef3a74b` (POSTMVP-LR-WP3C), well before this
wave. **Nothing in Wave 4 caused this**; Wave 4 is where it became visible,
because §13 asked the Wrap Up surface to draw a settled wager and there was
never one to draw.

## What this does and does not block

It does **not** block the Wave 4 result card. `reports/action_read_model` was
extended (read-only) to carry `bets.status` through as `outcome`, and
`week.matchupResultCard` renders it; both are exercised against the test
fixture, whose wagers are created through the new model and therefore do carry a
league. The card is correct and certified.

What it blocks is the **demo** ever reaching that card — and, more seriously,
the demo ever showing a GM a FantasyStakes Matchup at all.

## Why it was not fixed here

Wave 4 §15 states that any new backend work must be read-only, and names wager
commands among the systems not to modify:

> If you discover the required preview/result information cannot be exposed
> without altering those systems: STOP and report the gap before making the
> change.

Every available repair alters one of them:

1. **Set `league_id` in `beef_engine.issue_challenge`** — a change to a wager
   command, and one that would alter the rows every existing legacy caller
   writes.
2. **Move `demo/gameplay.py` onto `proposal_lifecycle.open_challenge`** — a
   change to how the showcase creates and funds wagers, which moves the demo's
   economics onto a different funding path (`economy/challenge_funding`) and
   would change the seeded fingerprint.
3. **Backfill `league_id` on existing rows** — a data migration.
4. **Relax the read model's league filter** — this would make the read model
   report wagers it cannot attribute to a league, which is a correctness
   regression dressed as a fix.

(1) and (2) are the honest candidates. Both are a deliberate product decision
about which wager model the demo runs on, not a UI reconciliation.

## Recommended next step

Decide which model the showcase should demonstrate. If the new proposal
lifecycle is the shipping one — and the Action tab is built entirely around it —
then `demo/gameplay.py` should issue through it, and the legacy `issue_challenge`
path should be reviewed for whether anything still writes production rows
through it. That work is a wave of its own, with its own fingerprint and
economics validation.


---

# RESOLUTION — *UIRECON Wave 4 demo matchup visibility reconciliation*

## What was actually wrong

One column. `beefs/beef_engine.issue_challenge` built its `BeefChallenge`
without `league_id`, though both `Team` rows — whose `league_id` is `NOT NULL` —
were already loaded two lines above the constructor. `beef_challenges.league_id`
has existed and been nullable since the Spec-1 migration, so **no schema change
was needed**, exactly as this finding predicted.

## The option chosen, and why

The finding listed four candidate repairs and called (1) and (2) the honest
ones. **(1) was taken**: the league is derived inside `issue_challenge`.

**(2) — moving the showcase onto `issue_funded_challenge` — was rejected** as
too large a change to make inside a visibility reconciliation: it replaces every
settled record's shape, its funding legs, its escrow accounts and its protocol
events, and the demo fingerprint and D-suite with them.

> **Correction, added by UIRECON Wave 5.** The economic reason first given here
> was wrong. This section claimed the funded lifecycle "quotes an odds-derived
> Derived stake" and would therefore move every GM's exposure. It does not, in
> **Locked** mode: `beefs/versus_quote.proposal_economics` sets
> `quoted_derived_stake_cents` to the issuer's own stake, and its comment says
> so — *"BOTH SIDES STAKE THE SAME AMOUNT in locked mode … exactly as the legacy
> path placed both sides at `effective_amount`"*. Only **Dynamic** leaves the
> Derived side unpriced until Final Lock. Wave 5 seeds its open negotiations
> through the funded path for exactly that reason, and measured a pristine
> showcase before and after to confirm no wallet, standing, Pool figure or
> championship score moves.

## The second half of the fix

Populating the column made the matchups **visible**; it did not make them
**right**. Two further defects surfaced immediately, both in the read model and
both pre-existing:

1. **No terms.** `gm_action_state` read stake, odds, line and moneyline only
   from a `BeefProposal`. An engine-written matchup has none, so every card
   reported a **$0 stake** and no odds — while real Credits sat in a settled
   `Bet`. It now reads the legacy record's own columns and its `Bet` rows, and
   **only when there is no proposal**, so no proposal-lifecycle wager can move.

2. **The wrong rail.** `classify` tested `response_status`, which an
   engine-written row leaves NULL, so a **live** matchup fell through to
   COMPLETED. The legacy `status` vocabulary is now translated one-to-one onto
   the governed one — `pending→offered`, `countered→countered`,
   `accepted→accepted`, `declined→declined`, `expired→expired` — again only
   when the governed column is absent.

## A third defect, found by validating against the ledger

`_settlement` computed a settled wager's net as `stake x odds - stake`. That is
a payout rule `betting/settlement_engine` **retired**: it credits the winner
*both* escrow balances — the pot — and its own comment names the change as
*"the fix itself, not the 2x-amount shortcut it replaces ... never a recomputed
`bet.amount`"*.

The two read models therefore disagreed about the same GM's same wagers:

```
Action    (odds formula)  -1,687 cents
Standings (ledger doors)  -1,500 cents      <- correct
```

`_settlement` now reads the `wager_settled` posting that closed the bet's
escrow, exactly as `betting/pool_result_view` reads the winner-distribution
posting. Action and Standings agree, and both agree with the ledger.

## What did NOT change

- `demo/gameplay.py` — untouched. The showcase still plays through the same
  calls a GM's clicks reach.
- Wager economics, settlement, ledger postings, Locked/Dynamic behaviour,
  quote and Final-Lock behaviour, postseason eligibility, championship scoring,
  replay/idempotency, existing challenge ids.
- A fresh showcase seeded before and after the change is **byte-identical** in
  standings, in all 44 Pool instances with their classifications and
  distributed/rollover cents, in pool claims, and in trial balance.

## One thing the fix deliberately does not reach

Wrap Up's week switch is a locked two-week control (Rev 4.2), so it offers only
the authoritative week and the one before it. Under the showcase's contest
rotation the seated GM has no **settled** wager in either, so the
FANTASYSTAKES MATCHUPS carousel shows their **live** week-11 matchup rather
than a settled result card. That is a property of which weeks the fixture gives
that GM a contest in — not of the read model, which reports all seven of their
settled matchups correctly on Action. Changing it would mean changing
`demo/gameplay.versus_card()`, which changes which contests happen, and with
them the standings and the fingerprint.
