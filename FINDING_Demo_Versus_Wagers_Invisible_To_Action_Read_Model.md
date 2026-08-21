# FINDING — the demo showcase's FantasyStakes Matchups are invisible to the Action read model

**Raised:** UIRECON Wave 4B, while wiring the settled-wager result card (§13).
**Status:** REPORTED, NOT FIXED. Closing it requires changing a wager command or
the demo's gameplay seeding, both of which Wave 4 §15 places out of scope.
**Severity:** the demo shows a GM zero FantasyStakes Matchups, on every tab, in
every week — including the seven weeks in which that GM demonstrably wagered.

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
