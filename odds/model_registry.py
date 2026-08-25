"""
odds/model_registry.py — P3-D2 / Rev 9 MODEL-A: the immutable simulation-model
version registry.

WHY THIS EXISTS. Rev 9 §0 makes the **model version** one of the three things a
Dynamic Handshake freezes, alongside each side's maximum exposure and the escrow
ceiling. The reason is money: at Final Lock the engine re-derives the opponent's
Derived Stake from final probabilities, and the difference between that and the
Handshake ceiling is refunded as real BAB. If the model that produces those
probabilities can drift between Handshake and Final Lock — a deploy that retunes
a variance constant, say — then the refund is computed under rules the GMs never
agreed to, while the record claims otherwise.

Before this module there was nothing to freeze. `BeefProposal.pricing_model_id`
and `pricing_calc_version` existed as free-text columns with no referent: no
registry, no binding to engine behaviour, populated with literals like "mc-v1" in
tests. Freezing that label and re-simulating under whatever constants happened to
be deployed would have recorded a provenance claim the run could not honour. This
registry gives the label a referent.

THE MEMBERSHIP RULE (Rev 9 / MODEL-A). A value belongs to the model version if
changing it can alter the returned probability given **byte-identical projection
inputs and lineups**. Everything that varies per challenge — the projection
dataset, Yahoo lineups, injury *status* values, player/team/week identity, and
the derived seed itself — is a LIVE INPUT and is deliberately NOT here. The
distinction is load-bearing at Final Lock, which must reuse the frozen MODEL
while reading CURRENT projections; conflating the two would either freeze the
lineups (wrong — Dynamic is live until Final Lock) or unfreeze the model (wrong —
the refund would move).

    frozen at Handshake:  model_version_id + model_config_hash
    live until Final Lock: projections, lineups, injury status, resulting odds

IMMUTABILITY IS STRUCTURAL, NOT CONVENTIONAL. Every config is a frozen dataclass
built from tuples, the registry is a MappingProxyType, and `MODEL_V1`'s content
hash is pinned by a literal in the P3-D2 suite. Editing a shipped version fails
loudly rather than silently repricing every Dynamic wager that froze it.
Changing a probability-affecting default means MINTING A NEW VERSION; existing
referenced versions stay executable forever, because a challenge that froze
`sim-v1` must still be able to Final-Lock under `sim-v1` years later.

THE HASH IS DETECTION, NOT A LOOKUP KEY. `model_config_hash()` proves the
registry entry a challenge froze has not been edited underneath it. It never
reconstructs configuration — resolution is always by `model_version_id`, and the
hash is compared afterwards. A hash that could rebuild config would be a second
source of truth for the same fact.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from types import MappingProxyType
from typing import Mapping


class ModelRegistryError(ValueError):
    """Base for registry refusals. Subclasses are distinct TYPES so callers and
    tests branch on type, never on message text."""


class UnknownModelVersionError(ModelRegistryError):
    """The requested model_version_id is not in the registry.

    At Final Lock this is fatal and NOT substitutable: Rev 9 forbids falling back
    to the currently active version, because that would silently reprice the
    wager under rules the parties never froze."""


class ModelConfigHashMismatchError(ModelRegistryError):
    """The resolved config's content hash differs from the hash frozen at
    Handshake — the registry entry was edited after a challenge froze it.

    Fatal at Final Lock. The frozen model is, by definition, no longer
    reproducible."""


# ── Scoring (probability-affecting: it shifts every projection) ───────────────

@dataclass(frozen=True)
class SimScoring:
    """Frozen scoring settings. Mirrors the engine's ScoringSettings shape but is
    immutable and hashable, because it is part of the versioned model."""
    scoring_type:     str
    rec_points:       float
    pass_td_points:   float
    rush_td_points:   float
    rec_td_points:    float
    bonus_100yd_rush: float
    bonus_100yd_rec:  float


# ── The versioned model configuration ─────────────────────────────────────────

@dataclass(frozen=True)
class SimModelConfig:
    """Everything that can change a probability given identical inputs.

    NO PROJECTION, LINEUP, PLAYER, TEAM, WEEK OR SEED FIELD APPEARS HERE, and the
    P3-D2 suite asserts that structurally over the field set with a positive
    control. `seed_method` names the *rule* used to derive a seed; the derived
    seed value is computed from live identity and is not stored.

    Mapping-shaped data is held as sorted tuples of pairs rather than dicts: a
    dict is mutable and its iteration order would leak into the content hash.
    """
    model_version_id: str

    # Algorithm identity
    algorithm:      str      # what the simulator does, as a named rule
    rng_algorithm:  str      # the generator family, e.g. numpy PCG64
    seed_method:    str      # the seed DERIVATION RULE, never a seed value

    # Sampling
    n_sims:                 int
    std_pct:                float
    min_std:                float
    truncate_draws_at_zero: bool
    starter_correlation:    str    # explicit ABSENCE is still a modelling choice

    # Projection transformation
    points_round_dp: int
    scoring:             SimScoring
    injury_multipliers:  tuple[tuple[str, float], ...]
    avg_stats:           tuple[tuple[str, tuple[tuple[str, float], ...]], ...]
    fp_reference:        tuple[tuple[str, float], ...]

    # Probability derivation
    tie_rule:               str
    probability_complement: str

    # ── accessors (read-only views over the frozen tuples) ────────────────

    def injury_multiplier(self, status: str | None) -> float:
        """The multiplier for a live injury STATUS. The status is a live input;
        this table is model config."""
        key = (status or "").lower()
        for name, mult in self.injury_multipliers:
            if name == key:
                return mult
        return 1.0

    def avg_stats_for(self, position: str) -> dict[str, float]:
        table = dict(self.avg_stats)
        row = table.get(position) or table.get("FLEX")
        return dict(row)

    def fp_ref(self, key: str) -> float:
        return dict(self.fp_reference)[key]


# ── Content hashing (detection only) ──────────────────────────────────────────

def model_config_hash(config: SimModelConfig) -> str:
    """A stable content hash over the config's full field set.

    Canonical JSON with sorted keys over the dataclass, so the digest depends on
    VALUES and not on declaration or iteration order. Used only to detect that a
    registry entry changed after a challenge froze it; it is never a lookup key
    and never reconstructs configuration.
    """
    canonical = json.dumps(asdict(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── v1 — the CURRENT production model, captured exactly ───────────────────────
#
# EVERY VALUE BELOW IS LIFTED VERBATIM FROM odds/odds_engine_headless.py AS IT
# STOOD AT COMMIT 79a81cf5, BEFORE PARAMETERISATION. That is what makes the
# legacy-equivalence gate meaningful: v1 is not a fresh opinion about good
# defaults, it is a faithful capture of the model already pricing Locked wagers,
# so parameterising the engine cannot move a single existing probability.

MODEL_V1 = SimModelConfig(
    model_version_id = "sim-v1",

    algorithm      = "montecarlo_normal_sum_independent_starters_v1",
    rng_algorithm  = "numpy_default_rng_pcg64",
    # Two branches, both pre-existing: matchup-seeded when a shared matchup id is
    # supplied, team-pair-seeded otherwise. The RULE is config; the integer it
    # produces is derived from live identity and is not stored here.
    seed_method    = "matchup_or_team_pair_week_v1",

    n_sims                 = 10_000,     # was N_SIMS
    std_pct                = 0.20,       # was STD_PCT
    min_std                = 0.5,        # was MIN_STD
    truncate_draws_at_zero = True,       # was np.maximum(draws, 0.0)
    # Starter draws are independent normals summed per trial — there is no
    # covariance structure. Recording the ABSENCE is deliberate: adding
    # correlation later is a probability-affecting change and must mint a new
    # version rather than silently alter sim-v1.
    starter_correlation    = "none_independent_normals",

    points_round_dp = 4,             # was round(..., 4) in _adjust_for_scoring
    scoring = SimScoring(               # was the HALF_PPR default parameter
        scoring_type     = "half_ppr",
        rec_points       = 0.5,
        pass_td_points   = 5.0,
        rush_td_points   = 6.0,
        rec_td_points    = 6.0,
        bonus_100yd_rush = 0.0,
        bonus_100yd_rec  = 0.0,
    ),
    injury_multipliers = (               # was INJURY_MULTIPLIERS
        ("doubtful",     0.25),
        ("ir",           0.00),
        ("out",          0.00),
        ("questionable", 0.60),
    ),
    avg_stats = (                        # was _AVG_STATS
        ("DEF",  (("c100", 0.00), ("pass_td", 0.0), ("r100", 0.00), ("rec", 0.0), ("rec_td", 0.00), ("rush_td", 0.00))),
        ("FLEX", (("c100", 0.10), ("pass_td", 0.0), ("r100", 0.08), ("rec", 3.5), ("rec_td", 0.35), ("rush_td", 0.35))),
        ("K",    (("c100", 0.00), ("pass_td", 0.0), ("r100", 0.00), ("rec", 0.0), ("rec_td", 0.00), ("rush_td", 0.00))),
        ("QB",   (("c100", 0.00), ("pass_td", 1.8), ("r100", 0.02), ("rec", 0.0), ("rec_td", 0.00), ("rush_td", 0.20))),
        ("RB",   (("c100", 0.03), ("pass_td", 0.0), ("r100", 0.15), ("rec", 3.5), ("rec_td", 0.20), ("rush_td", 0.70))),
        ("TE",   (("c100", 0.08), ("pass_td", 0.0), ("r100", 0.00), ("rec", 3.5), ("rec_td", 0.35), ("rush_td", 0.00))),
        ("WR",   (("c100", 0.18), ("pass_td", 0.0), ("r100", 0.01), ("rec", 5.0), ("rec_td", 0.50), ("rush_td", 0.05))),
    ),
    fp_reference = (                     # was _FP_* module constants
        ("pass_td", 4.0),
        ("rec",     1.0),
        ("rec_td",  6.0),
        ("rush_td", 6.0),
    ),

    # The comparison beef_engine already performs: strict `>`, so a tied
    # simulated trial does not count as a challenger win. Naming it makes it
    # versioned instead of implicit.
    tie_rule               = "strict_greater_than_ties_favour_neither",
    probability_complement = "one_minus_p",
)


# ── v2 — the CSPS/IPRM projection path ────────────────────────────────────────
#
# WHAT MAKES IT A DIFFERENT MODEL, AND WHY IT IS A NEW VERSION RATHER THAN AN
# EDIT. v1 takes a FantasyPros PPR scalar and re-scores it here, in
# `_adjust_for_scoring`, using position-average stat tables — `avg_stats` and
# `fp_reference` exist for exactly that. v2 takes a mean that CSPS has ALREADY
# scored under the league's own certified rule set and IPRM has attached a
# distribution to. Running v1's re-scoring over a v2 mean would convert it a
# second time, which is the double-conversion hazard the Phase 0 audit named.
#
# So v2 declares those tables EMPTY. They are not unused-by-accident; they are
# absent because the step they serve does not exist on this path, and a v2 run
# that called `_adjust_for_scoring` would raise rather than quietly re-score.
#
# THREE FIELDS DIFFER IN VALUE, AND EACH IS A DELIBERATE VERSIONED CHOICE:
#
#   scoring                 v1 carries the league rates because it does the
#                           conversion. v2 does not convert, so it names the
#                           owner instead: the CSPS scoring profile, whose id
#                           and version travel on every IPRM result and into the
#                           simulation fingerprint. Rates here would be a second
#                           source of scoring truth.
#
#   truncate_draws_at_zero  v1 clamps every draw at zero. That was right for a
#                           FantasyPros PPR scalar, which cannot be negative,
#                           and wrong for a league-scored total, which can be:
#                           the reconciled Titans defence scored -1.00 in its
#                           points-allowed band and Tyrone Tracy's -5 receiving
#                           yards scored -0.50. Clamping would silently truncate
#                           the left tail of every defence and turnover-prone
#                           quarterback. v2 does not clamp — and because that is
#                           a probability-affecting change, it mints a version
#                           rather than editing v1.
#
#   std_pct / min_std       IDENTICAL to v1, on purpose. IPRM derives each
#                           player's sigma with v1's own rule,
#                           max(|mean| x 0.20, 0.5), so sim-v2 changes what the
#                           mean is built from and not how far it is trusted to
#                           move. They are repeated here so a v2 run is
#                           self-describing.
#
# starter_correlation stays "none_independent_normals": sim-v1 assumes
# independence, no approved correlation structure exists, and adding one would
# be a research change rather than an integration.

MODEL_V2 = SimModelConfig(
    model_version_id = "sim-v2",

    algorithm      = "montecarlo_normal_sum_independent_starters_csps_iprm_v2",
    rng_algorithm  = "numpy_default_rng_pcg64",
    seed_method    = "matchup_or_team_pair_week_v1",

    n_sims                 = 10_000,
    std_pct                = 0.20,
    min_std                = 0.5,
    truncate_draws_at_zero = False,
    starter_correlation    = "none_independent_normals",

    points_round_dp = 4,
    # Scoring is owned by the CSPS profile named on each IPRM result, not by
    # this config. The zeros are unreachable on the v2 path and the marker says
    # so out loud.
    scoring = SimScoring(
        scoring_type     = "csps_profile_owned",
        rec_points       = 0.0,
        pass_td_points   = 0.0,
        rush_td_points   = 0.0,
        rec_td_points    = 0.0,
        bonus_100yd_rush = 0.0,
        bonus_100yd_rec  = 0.0,
    ),
    injury_multipliers = (
        ("doubtful",     0.25),
        ("ir",           0.00),
        ("out",          0.00),
        ("questionable", 0.60),
    ),
    # Empty because v2 performs no PPR re-scoring. See the note above.
    avg_stats    = (),
    fp_reference = (),

    tie_rule               = "strict_greater_than_ties_favour_neither",
    probability_complement = "one_minus_p",
)


# ── The registry ──────────────────────────────────────────────────────────────

_REGISTRY: Mapping[str, SimModelConfig] = MappingProxyType({
    MODEL_V1.model_version_id: MODEL_V1,
    MODEL_V2.model_version_id: MODEL_V2,
})

# The version minted onto NEW pricing and NEW Handshakes only.
#
# AN ALREADY-HANDSHAKEN DYNAMIC CHALLENGE MUST NEVER CONSULT THIS. Rev 9 §5: the
# refresh and Final Lock both resolve `challenge.dynamic_model_version_id`. If
# this constant advances to sim-v2 tomorrow, every in-flight Dynamic wager still
# Final-Locks under the version it froze — that is the entire point of freezing
# one.
ACTIVE_MODEL_VERSION_ID = "sim-v1"


def resolve_model_config(model_version_id: str) -> SimModelConfig:
    """Resolve a version id to its immutable config.

    RAISES rather than falling back. Rev 9 is explicit that a Final Lock which
    cannot resolve its frozen version must post nothing and leave the wager
    recoverable — substituting the active model would reprice real money under
    rules nobody froze.
    """
    config = _REGISTRY.get(model_version_id)
    if config is None:
        raise UnknownModelVersionError(
            f"Model version {model_version_id!r} is not in the registry. Known "
            f"versions: {sorted(_REGISTRY)}. A frozen version is never "
            f"substituted with the active one."
        )
    return config


def resolve_active_model_config() -> SimModelConfig:
    """The config for NEW pricing/Handshake only. Never for an existing
    Dynamic challenge — see ACTIVE_MODEL_VERSION_ID."""
    return resolve_model_config(ACTIVE_MODEL_VERSION_ID)


def registry_version_ids() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def resolve_and_verify(model_version_id: str, expected_hash: str) -> SimModelConfig:
    """Resolve a frozen version AND prove it has not been edited since freezing.

    The two failures are distinct types on purpose: an unknown version means the
    entry is gone, a hash mismatch means it is present but changed. Both are
    fatal at Final Lock and both must leave the wager recoverable, but an
    operator needs to know which one happened.
    """
    config = resolve_model_config(model_version_id)
    actual = model_config_hash(config)
    if actual != expected_hash:
        raise ModelConfigHashMismatchError(
            f"Model version {model_version_id!r} resolved, but its content hash "
            f"{actual} does not match the hash frozen at Handshake "
            f"{expected_hash}. The registry entry was edited after this "
            f"challenge froze it, so the frozen model is no longer reproducible."
        )
    return config
