# FantasyStakes 1.0.0-rc1 — Release Notes

**Internally certified launch baseline.** The software is complete and proved.
Yahoo-backed commercial go-live and the remote production environment remain
externally gated — see *Known external blockers* at the end, which is not a
formality.

---

## What FantasyStakes is

A companion overlay to a supported Yahoo Fantasy football league. It does not
replace the Yahoo league; it adds a stakes layer on top of it, with Yahoo's own
results as the authority for who won.

A commissioner authenticates with Yahoo, connects their league, configures the
economy, and activates the season. Members join, play, and watch a Ledger.

## The application

Five tabs, and only five:

**Standings · Play · Status · Wrap Up · Account**

Mobile-first, installable as a PWA, responsive from 320px, keyboard-operable
throughout, with a single universal upper-left close control on every
dismissible surface.

## Credits

FantasyStakes runs on virtual **Credits**. The UI writes `$` as shorthand —
`$100` means 100 Credits.

Credits have **no cash value**. They cannot be purchased, deposited, withdrawn
or redeemed. There is no payment processing anywhere in the product.

## The economy

Configured by the commissioner before activation, then **frozen**:

| Setting | Range | Default |
|---|---|---|
| Weekly Bet Minimum | $1 – $100 | $10 |
| Championship Pot Contribution | $1 – $1,000 | $80 |
| Skunk Fee | $1 – $100 | $10 |

The regular-season week count comes from authoritative league state, not a
constant. Each player's **Season-Opening Allocation** is

```
weekly_bet_minimum × regular_season_week_count  +  championship_pot_contribution
```

The Skunk Fee is contingent and is excluded from the opening allocation.

## Versus

Head-to-head wagers on real matchups. Moneyline, Spread and Over/Under all
derive from **one authoritative matchup simulation**: moneyline from simulated
win probability, spread from the median simulated margin, total from the median
simulated combined score — each rounded half-up to the nearest 0.5 fantasy
point. Whole-number lines are permitted and pushes stay valid. Favourite
negative, underdog positive.

The backend line is authoritative for display, quote, wager creation,
persistence and settlement. The frontend performs no authoritative arithmetic.

Lifecycle: issue → revive → counter → locked accept / dynamic handshake →
settlement, replay-safe throughout.

## Pools

League-wide weekly Pools with a governed catalog and rotation: open, pick,
claim, close, settle. Missing provider data fails closed rather than settling on
a guess. All members may keep playing eligible Pools after their own postseason
elimination.

## Weekly Minimum and Skunk

Each **regular-season** week, a GM who wagers less than the Weekly Bet Minimum
has the shortfall swept to the championship pot — covered by their wallet where
funded, carried as a receivable where not. There is no Weekly Minimum in the
postseason.

Each completed regular-season week, the largest margin-of-defeat loser is
assessed the Skunk Fee, split on a tie, once per league-week, into the Skunk
Pot. At regular-season close the entire Pot goes to the highest cumulative
regular-season Points For — wins, seeding and titles are irrelevant, postseason
PF is excluded, ties split, residual cent ordered deterministically. No
postseason Skunk.

## Postseason and the championship

The championship playoff track, plus the **official third-place exception**: the
championship-week matchup between the two teams that lost the immediately
preceding semifinals.

Championship-week Versus eligibility is finalists and official third-place
participants only; other consolation and placement teams are ineligible. Yahoo
results are authoritative, ambiguous provider state fails closed, and there is
no commissioner override of an authoritative Yahoo result.

The championship pot pays **60 / 30 / 10**, residual cent to first, and cannot
close without an authoritative third-place result. Settlement is idempotent.

## Authentication

Production sign-in is **Sign in with Yahoo** — OpenID Connect over OAuth 2.0
Authorization Code Flow with **PKCE S256**, plus state and nonce. Yahoo's `sub`
is the immutable identity; email is contact and display only. There is no
production password login, and development authentication cannot be reached
through any user-controlled production flag.

## Per-user Yahoo authorization

A Yahoo-backed league reads on **its own commissioner's grant**:

```
league → provider_credential_user_id → that user's Yahoo grant
       → canonical refresh → Yahoo transport
```

Tokens are stored server-side only, sealed with AES-256-GCM under an
environment-managed key, and each ciphertext is bound to its own row — a grant
copied between users does not open. There is no fallback to a repository
operator token, to `YAHOO_PRIVATE_JSON`, to `secrets/private.json`, or to
another member's grant. A missing, disconnected or rejected grant fails closed.

Demo mode depends on no Yahoo credential at all.

## Attribution

Yahoo-backed data carries *Fantasy data provided by Yahoo Fantasy*, linking to
Yahoo Fantasy Football. Demo shows no Yahoo attribution.

## Data and operations

**PostgreSQL** is the authoritative store. A fresh deployment builds its schema
in one step; an existing one is upgraded by one command, `python -m
migrations.run`, in a deterministic manifest order with every application
recorded in `schema_migrations`.

Production surfaces: `/health` (liveness), `/ready` (readiness — database,
configuration and migration head), `/version` (release identity). Startup
refuses in production without `DATABASE_URL`, `FS_TOKEN_ENCRYPTION_KEY` or
`JWT_SECRET_KEY`, and never substitutes a development value.

An emergency write-disable refuses authoritative economic writes with a named
reason code while reads keep working. A read-only recovery audit
(`python -m ops.audit`) checks Ledger balance, protected accounts, grant
integrity and decryptability, credential owners and stuck claims — and never
repairs anything. A post-deploy smoke test (`python -m ops.smoke`) verifies a
deployment without changing it.

## Recovery, release and rollback

PostgreSQL committed state is the recovery authority. Nothing depends on process
memory, browser state or worker logs, and no procedure asks anyone to
reconstruct a wallet.

A real backup / destroy / restore drill is part of the test suite: `pg_dump`,
database destroyed, `pg_restore`, then invariants — Ledger balanced, wallets
identical, sealed grants byte-identical and still opening with a separately held
key, frozen economy exact, settled work still settled, reruns producing no
duplicate economics.

Releases are safe mid-season: additive migrations only, prior settled rows never
rewritten, and an application rollback that leaves committed history readable.
The frontend deploys independently whenever API compatibility holds, and the
service worker's cache namespace is derived from the release identifier — a new
release is a new namespace, with no hand-maintained version to forget.

## Known external blockers

These are **not resolved** and are not represented as resolved.

1. **Yahoo Fantasy API authorization / access enablement.** The application is
   registered and the agreement is in place, but the last measured probe showed
   OAuth refresh succeeding while every Fantasy resource returned HTTP 403,
   *"This application is not authorized to perform this action"* — including
   endpoints that require no league access. Until this clears, no Yahoo-backed
   league can sync.
2. **Yahoo storage/retention boundary review.** Credential grants are stored;
   Yahoo Fantasy Information is not. The contractual question behind that
   architecture is unresolved.
3. **Real per-user Yahoo live reconfirmation.** No live credentials exist in the
   certification environment, so the per-user path has not been re-measured
   against Yahoo since it was built.
4. **Yahoo transport/parser contract**, pending authorized payload evidence.
5. **Postseason Yahoo evidence**, pending authorized access.
6. **Remote production environment.** Railway services, PostgreSQL, secrets,
   backups and domain are not yet provisioned or smoke-tested remotely.

Demo mode is unaffected by all six.

---

*FantasyStakes 1.0.0-rc1 — internally certified software baseline. Commercial
Yahoo-backed launch remains externally gated.*
