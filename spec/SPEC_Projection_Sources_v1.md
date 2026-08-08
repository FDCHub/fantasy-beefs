# Fantasy Beefs — Projection Sources Spec: FantasyPros & Yahoo

> Replaces: `FANTASYPROS_PROVIDER_SPEC.md`
> Location: `fantasy-beefs/tools/`
> Created: June 9, 2026
> Status: Ready to build · Rev 1
> Feeds: `engine/projection_engine.py`

---

## Purpose

Define the three projection sources available to the Decision Engine:
FantasyPros (consensus analyst aggregate), Yahoo (platform projections),
and Consensus (50/50 blend of both). The source is a per-GM preference.
The engine always receives the same `RawProj` shape regardless of source.

---

## Architecture

```
ProjectionSource (ABC)
  ├── FantasyProsSource    → FantasyPros REST API · x-api-key auth
  ├── YahooSource          → Yahoo /stats projected · OAuth session
  └── ConsensusSource      → 50/50 weighted blend of raw stat lines

ProjectionEngine(source: ProjectionSource)
  └── converts RawProj → fantasy points using league scoring rules
```

Scoring happens once, inside `ProjectionEngine`. Sources never return
fantasy points — only raw production stats. The blend in `ConsensusSource`
operates on raw stat lines before scoring, never on scored totals.

---

## RawProj Dataclass

```python
@dataclass
class RawProj:
    # Identity
    fpid:             str | None   # FantasyPros player ID
    yahoo_player_id:  str | None   # Yahoo player ID (bridge between sources)
    name:             str
    position:         str          # QB | RB | WR | TE | K | DST
    team:             str
    bye_week:         int | None

    # Passing
    pass_att:         float
    pass_yds:         float
    pass_tds:         float
    pass_int:         float

    # Rushing
    rush_att:         float
    rush_yds:         float
    rush_tds:         float

    # Receiving
    rec_rec:          float        # receptions
    rec_yds:          float
    rec_tds:          float

    # Misc
    fumbles:          float
    ret_tds:          float
    two_pt_tds:       float
```

Unknown fields default to 0.0. Neither source is required to populate
every field — missing fields are 0.0, not errors.

---

## Source 1 — FantasyProsSource

**Endpoint:**
```
GET https://api.fantasypros.com/public/v2/json/nfl/2025/projections
  ?position={pos}&scoring=PPR&week={week}
```

**Positions:** QB, RB, WR, TE, K, DST — one call per position = 6 calls per week fetch.

**Auth:** `x-api-key: {FANTASYPROS_API_KEY}` header. Key loaded from env var.

**Field mapping (from `stats` object):**
- `fpid` → `fpid`
- `player_yahoo_id` → `yahoo_player_id`
- `rush_att`, `rush_yds`, `rush_tds` → direct
- `rec_rec`, `rec_yds`, `rec_tds` → direct
- `pass_att`, `pass_yds`, `pass_tds`, `pass_int` → direct
- `fumbles`, `ret_tds`, `2pt_tds` → direct
- `points_ppr` / `points_half` → **ignored** (engine scores from raw stats)

**Acceptance:** Jalen Hurts raw stat line from FantasyPros, scored under
mock league rules (0.5 PPR, 5pt pass TDs), matches hand-verified total.
Same stat line under a 4pt pass TD config produces a different total —
proving scoring lives in the engine, not the source.

---

## Source 2 — YahooSource

**Endpoint:**
```
GET https://fantasysports.yahooapis.com/fantasy/v2/league/{league_key}
    /players;player_keys={keys}/stats;type=projected;week={week}
```

**Auth:** Yahoo OAuth 2.0 session (existing `scripts/yahoo_auth.py` flow).
yfpy 17.0.0 does not wrap this endpoint — hit it raw via the OAuth session.

**Field mapping:** Yahoo returns a `player_stats` object per player.
Map equivalent fields to `RawProj`. `yahoo_player_id` is the native ID.
`fpid` will be `None` for Yahoo-only requests.

**Note:** Yahoo projected stats endpoint confirmed available via existing
OAuth. Field-level mapping requires a live response audit — complete this
before marking `YahooSource` as built.

**Acceptance:** Same player, same week — Yahoo raw stat line scored under
mock league rules produces a plausible point total. `yahoo_player_id`
matches the player's ID in the Yahoo roster data.

---

## Source 3 — ConsensusSource

**Mechanic:** Fetch `RawProj` from both `FantasyProsSource` and
`YahooSource`. Match players by `yahoo_player_id` (the common bridge).
Blend each raw stat field at configured weights (default 50/50):

```python
blended_stat = (fp_stat * fp_weight) + (yahoo_stat * yahoo_weight)
# default: fp_weight = 0.5, yahoo_weight = 0.5
```

Unmatched players (present in one source but not the other) fall back
to the available source at full weight.

**Acceptance:** A known player's blended stat line is exactly the
arithmetic mean of the two source lines at default weights. Unmatched
player returns single-source line without error.

---

## Per-GM Preference

Stored in DB as a team/league setting. Three options:

| Value | Source used |
|---|---|
| `fantasypros` | FantasyProsSource only |
| `yahoo` | YahooSource only |
| `consensus` | ConsensusSource (50/50 blend) |

Default: `consensus`. GM can change per their team settings.
Passed into `ProjectionEngine` at request time — the engine is
source-agnostic and never reads this preference directly.

---

## Build Order

```
1. FantasyProsSource     [QWEN]       — API confirmed working, shape known
2. YahooSource           [QWEN]       — after Yahoo field audit (one live call)
3. ConsensusSource       [QWEN]       — after both sources pass acceptance
4. Per-GM preference DB field         — small schema addition
```

---

## Field Audit Required (YahooSource gate)

Before building `YahooSource`, run one live call against the Yahoo
projected stats endpoint and document the exact field names returned.
Update this spec with the confirmed mapping before Qwen builds the module.

---

*Fantasy Beefs — Projection Sources Spec · June 9, 2026*
*Our Thing. Your League.*
