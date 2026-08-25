"""The Yahoo data retention INVENTORY — what is persisted, and what depends on it.

    python -m ops.yahoo_retention              the inventory, grouped
    python -m ops.yahoo_retention --json       machine-readable
    python -m ops.yahoo_retention --gate       only the open contractual gate

WHAT THIS IS. A factual record of every persisted field in this application
whose value originates from Yahoo, every FantasyStakes figure derived from one,
and what would break if any of it had to be deleted. It is maintained BY HAND
and kept honest BY A TEST (`test_c1_yahoo_retention.py`), which fails when a
provider-origin column exists in the schema and is not inventoried here.

WHAT THIS IS EMPHATICALLY NOT. It is not a claim of contractual compliance, not
a retention policy, and not a statement that FantasyStakes is permitted to keep
any of it. The Yahoo agreement's storage question is OPEN. This module records
what the software does so that whoever answers that question can see the whole
surface at once — and so the answer can be implemented against a list rather
than a search.

NOTHING HERE READS, WRITES, DELETES OR EXPIRES ANY DATA. It is a description.
There is no retention timer in this file and no code path that acts on one,
because no such rule has been granted.

── THE THREE KINDS OF STATE, AND WHY THE DISTINCTION DECIDES EVERYTHING ──────

TRANSIENT      A Yahoo API response in memory for the duration of one refresh.
               Never written. Deleting it is free — it is already gone.

PROVIDER_FACT  A Yahoo-originated value written to the database: an identifier,
               a roster slot, a matchup score. This is the surface a retention
               ruling actually governs.

DERIVED        A FantasyStakes figure COMPUTED from a provider fact and then
               stored — a settled wager, a skunk charge, a Championship Score.
               Deleting the provider fact does not delete these, and they cannot
               be recomputed once it is gone.

YAHOO-DERIVED  A FantasyStakes VALUE whose ARRANGEMENT is Yahoo's — the matchup
RELATIONSHIP   pairing is the case. The integers are our own primary keys; which
               two teams meet, and which is home, is Yahoo's fixture. Neither a
               provider fact nor an ordinary derived figure, and recording it as
               either would be false in one direction or the other.

FOREIGN        A provider-origin value from a provider that is NOT Yahoo —
PROVIDER FACT  BALLDONTLIE's player identifiers are the case. Listed because
               this inventory's completeness check flags every provider-named
               column, and the only honest answer for these is neither "not
               provider data" nor "Yahoo's". A Yahoo ruling does not reach them.

TRANSACTIONAL  FantasyStakes' own economic record: ledger entries, allocations,
               distributions, corrections. It contains no Yahoo field at all.
               A retention ruling does not reach it — but its CORRECTNESS was
               established using provider facts, which is why the audit trail
               matters to the question.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

__all__ = [
    "DERIVED", "FOREIGN_PROVIDER_FIELDS", "PROVIDER_FACTS", "REQUIRES_RULING",
    "SAFE_WITHOUT_RULING", "YAHOO_DERIVED_RELATIONSHIPS", "Derived",
    "FOREIGN_PROVIDER_PAYLOAD_COLUMNS", "ForeignProviderField",
    "ProviderField", "YahooDerivedRelationship",
    "foreign_provider_columns", "inventoried_columns", "related_columns",
    "report",
]

#: The contractual question this inventory exists to inform. It is OPEN.
GATE = (
    "The Yahoo agreement's data storage and retention terms have not been "
    "clarified. Nothing in this repository asserts a right to retain Yahoo "
    "data, and no retention period is implemented. This inventory describes "
    "current behaviour so the question can be answered against facts."
)


@dataclass(frozen=True)
class ProviderField:
    """One persisted column whose value originates from Yahoo."""

    table: str
    column: str
    what: str
    #: Why the application holds it at all.
    purpose: str
    #: What stops working if it were deleted. Written plainly, because this is
    #: the sentence a retention decision is actually made against.
    if_deleted: str
    #: True when settled economics or an audit trail depend on this value.
    economic_dependency: bool = False


@dataclass(frozen=True)
class Derived:
    """A FantasyStakes figure computed from provider facts and then stored."""

    name: str
    where: str
    from_fields: tuple
    note: str


@dataclass(frozen=True)
class YahooDerivedRelationship:
    """A column holding a FantasyStakes VALUE whose RELATIONSHIP is Yahoo's.

    ── C2.1 · WHY THIS IS ITS OWN CATEGORY ──────────────────────────────────

    `matchups.home_team_id` and `matchups.away_team_id` are FantasyStakes team
    primary keys. The integers are ours; nothing in them came from Yahoo, and
    calling them Yahoo identifiers would be false — it would put our own primary
    keys inside a deletion scope that has no business reaching them.

    But WHICH TWO TEAMS FACE EACH OTHER IN A GIVEN WEEK, and which is home, is
    Yahoo's fixture. The values are FantasyStakes'; the pairing they express is
    Yahoo-derived. Recording them as neither would leave a reader of this
    inventory unable to answer "is the schedule Yahoo data?" — which is a
    question a retention ruling may well turn on.

    So they are listed, accurately, as a third thing: a relationship derived
    from Yahoo, materialised in FantasyStakes identifiers.
    """

    table: str
    columns: tuple
    values_are: str
    relationship_is: str
    if_deleted: str
    economic_dependency: bool = False


@dataclass(frozen=True)
class ForeignProviderField:
    """A provider-named column whose value did NOT come from Yahoo.

    WP1 — WHY THIS CATEGORY HAD TO EXIST BEFORE THE FIRST ROW OF IT DID. This
    module's name scan flags every `provider_*` column in the schema and demands
    it be accounted for, on the reasoning that an unaccounted provider column is
    Yahoo data nobody inventoried. That reasoning held while Yahoo was the only
    provider. `provider_player_alias` ends that: its columns are provider-origin
    and are not Yahoo's, and the two available answers were both false — leave
    them unlisted (asserting they are not provider data) or list them as Yahoo
    facts (asserting Yahoo supplied them).

    So they are recorded as the third true thing: provider data, from a named
    provider that is not Yahoo, outside the Yahoo retention question and inside
    whatever question that provider's own terms raise.

    THIS IS NOT A YAHOO EXEMPTION HATCH. Everything listed here names the
    provider it came from, and the C1 suite asserts that no column is claimed by
    both this list and the Yahoo inventory — a Yahoo column moved here to quiet
    the scan would have to be claimed under a provider name that is not Yahoo's,
    which is a lie a reader can see rather than an omission a reader cannot.
    """

    table: str
    column: str
    #: The provider this value came from — never "yahoo".
    provider: str
    what: str
    #: Why the application holds it at all.
    purpose: str
    #: What stops working if it were deleted.
    if_deleted: str


# ── PROVIDER FACTS ───────────────────────────────────────────────────────────
#
# Every persisted column below carries a value that came from Yahoo. The list is
# enforced against `db/schema.py` by the C1 suite: a provider-origin column that
# is not here is a test failure, not an oversight nobody noticed.

PROVIDER_FACTS: tuple = (
    # ── identity and connection ──────────────────────────────────────────────
    ProviderField(
        table="users", column="provider_subject",
        what="the Yahoo account's stable OpenID subject identifier",
        purpose="binds a FantasyStakes user to the Yahoo account that signed in",
        if_deleted="that user can no longer sign in with Yahoo; a new sign-in "
                   "would create a second account rather than recognising them",
    ),
    ProviderField(
        table="provider_grants", column="provider_subject",
        what="the Yahoo subject the access grant belongs to",
        purpose="ties a sealed OAuth grant to the account that authorized it",
        if_deleted="the grant cannot be attributed; the league must reconnect",
    ),
    ProviderField(
        table="provider_grants", column="access_token_sealed / refresh_token_sealed",
        what="OAuth tokens, AES-GCM sealed with a context AAD",
        purpose="lets FantasyStakes read the league on the user's authority "
                "rather than on a shared operator credential",
        if_deleted="provider reads stop until a commissioner reconnects; no "
                   "economic record is affected",
    ),
    # ADDED IN C2.1 by an independent source trace of `auth/provider_grant.py`,
    # not by the name scan — `granted_scope` reads as a FantasyStakes field and
    # is not one. `_seal_into` and `refresh_grant` both write
    # `_clean(tokens.get("scope"))`, which is the scope string YAHOO RETURNED in
    # the token response, not the scope this application asked for.
    ProviderField(
        table="provider_grants", column="granted_scope",
        what="the scope string Yahoo returned with the token grant "
             "(`tokens['scope']`), which is Yahoo's answer and may differ from "
             "the scopes requested",
        purpose="records what access the user actually granted, so a read that "
                "fails for lack of permission can be told apart from one that "
                "fails for lack of a token",
        if_deleted="the connection still works; an operator loses the ability "
                   "to see what the user consented to. No economic effect",
    ),
    # ── league, team and player identifiers ──────────────────────────────────
    ProviderField(
        table="leagues", column="provider_league_key",
        what="the Yahoo league key",
        purpose="the join key for every provider read for this league",
        if_deleted="the league cannot be refreshed until it is reconnected",
    ),
    ProviderField(
        table="leagues", column="provider_current_week",
        what="the week Yahoo currently considers live",
        purpose="the postseason boundary and the weekly lifecycle read it",
        if_deleted="week lifecycle and postseason gating lose their boundary",
        economic_dependency=True,
    ),
    ProviderField(
        table="leagues", column="provider_credential_user_id",
        what="which user's grant this league reads on",
        purpose="provider-grant ownership; commissioner assignment",
        if_deleted="the league falls back to unassigned and must be reassigned",
    ),
    ProviderField(
        table="leagues", column="provider_credential_assigned_at",
        what="when that assignment was made",
        purpose="operator visibility into connection provenance",
        if_deleted="provenance of the assignment is lost; reads still work",
    ),
    ProviderField(
        table="teams", column="provider_team_key",
        what="the Yahoo team key",
        purpose="resolves a Yahoo team to a FantasyStakes team on every read",
        if_deleted="matchups and rosters cannot be attributed to a GM",
        economic_dependency=True,
    ),
    ProviderField(
        table="teams", column="provider_team_id",
        what="the Yahoo numeric team id within the league",
        purpose="secondary resolution and conflict diagnosis",
        if_deleted="identity resolution loses a corroborating key",
    ),
    ProviderField(
        table="players", column="provider_player_key",
        what="the Yahoo player key",
        purpose="identifies a player across weeks and rosters",
        if_deleted="roster history cannot be attributed to a player",
    ),
    # ── PLAYER DESCRIPTIVE ATTRIBUTES ────────────────────────────────────────
    #
    # ADDED IN C2.1, AND THE OMISSION IS WORTH RECORDING. These four were
    # persisted from the Yahoo snapshot from the beginning and were missing from
    # the first inventory, because the completeness check looked for columns
    # NAMED `provider_*` or `yahoo_*` and these are named for what they are. An
    # operator deleting "Yahoo data" from the original list would have removed
    # the identifiers and the scores and left every player's name, position and
    # NFL team in place — Yahoo-origin content, retained, while believing the
    # deletion was complete.
    #
    # THE FLOW IS EXACT AND WORTH STATING ONCE:
    #   providers/persist.py `_persist_roster` reads `snapshot.roster_entries`
    #     -> passes entry.name, entry.eligible_positions[0], entry.nfl_team
    #     -> providers/identity.py `resolve_or_create_player`
    #     -> constructs and persists a `Player` row
    # They are written ONLY when a player key is new; an existing Player is
    # returned unchanged, so these are first-sight values rather than a
    # per-refresh copy.
    ProviderField(
        table="players", column="name",
        what="the player's name as Yahoo supplies it "
             "(`ProviderWeek.roster_entries[].name`)",
        purpose="every roster, starter and Pool subject surface names a player "
                "to a human; without it a GM sees an opaque key",
        if_deleted="rosters, starter-dependent Pool subjects and their history "
                   "become unreadable — the rows survive but no surface can say "
                   "who the player was. Nothing economic is recomputed, and no "
                   "settled figure changes",
    ),
    ProviderField(
        table="players", column="position",
        what="the first of Yahoo's eligible positions for the player "
             "(`entry.eligible_positions[0]`, stored as UNKNOWN when absent)",
        purpose="position-aware Pool subjects and roster presentation",
        if_deleted="position-scoped Pool subjects lose the classification they "
                   "were evaluated against for past weeks; already-settled Pool "
                   "outcomes stay settled and their evidence is gone",
        economic_dependency=True,
    ),
    ProviderField(
        table="players", column="nfl_team",
        what="the player's NFL team, per Yahoo (`entry.nfl_team`)",
        purpose="roster presentation and team-scoped analytics",
        if_deleted="team-scoped presentation and analytics lose their basis; no "
                   "settled economic figure changes",
    ),
    ProviderField(
        table="players", column="provider",
        what="which provider supplied this player row — the literal 'yahoo'",
        purpose="marks the row's origin so a multi-source identity map can tell "
                "a Yahoo player from one resolved elsewhere",
        if_deleted="provenance of the player row is lost and cross-source "
                   "identity resolution degrades to name matching",
    ),
    ProviderField(
        table="players", column="yahoo_id",
        what="the Yahoo player id",
        purpose="cross-source player mapping",
        if_deleted="player identity mapping degrades to name matching",
    ),
    ProviderField(
        table="player_id_map", column="yahoo_id",
        what="Yahoo player id in the cross-provider identity map",
        purpose="maps a Yahoo player onto other projection sources",
        if_deleted="projections cannot be joined to Yahoo rosters",
    ),
    ProviderField(
        table="matchups", column="provider_matchup_key",
        what="the Yahoo matchup key",
        purpose="idempotent matchup identity across refreshes",
        if_deleted="a refresh cannot recognise a matchup it already stored",
        economic_dependency=True,
    ),
    # ── the competitive facts themselves ─────────────────────────────────────
    ProviderField(
        table="matchups", column="home_score / away_score",
        what="the Yahoo fantasy points each side scored in a week",
        purpose="the RESULT every FantasyStakes wager settles against",
        if_deleted="settled economics can no longer be independently "
                   "re-derived or audited; every wager already settled on this "
                   "result stays settled, and the evidence for it is gone",
        economic_dependency=True,
    ),
    ProviderField(
        table="matchups", column="winner_team_id",
        what="which side Yahoo's scoring made the winner",
        purpose="the finality predicate wagers and pools settle on",
        if_deleted="settlement outcomes lose their authoritative basis",
        economic_dependency=True,
    ),
    ProviderField(
        table="matchups", column="refreshed_at",
        what="when this matchup was last read from Yahoo",
        purpose="staleness detection and reconciliation",
        if_deleted="stale provider state cannot be distinguished from fresh",
    ),
    ProviderField(
        table="roster_slots", column="slot / player_id / week",
        what="which players a GM started in a given week, per Yahoo",
        purpose="starter-dependent side competitions and analytics",
        if_deleted="starter-based competitions lose their basis for past weeks",
        economic_dependency=True,
    ),
    ProviderField(
        table="provider_conflict", column="provider_value",
        what="a Yahoo value that disagreed with stored state",
        purpose="records a reconciliation conflict for an operator to resolve",
        if_deleted="the audit trail of provider disagreements is lost",
    ),
)


# ── PROVIDER DATA THAT IS NOT YAHOO'S ────────────────────────────────────────
#
# Provider-origin columns from a provider other than Yahoo. They are listed here
# so the name scan in the C1 suite can be satisfied by a TRUE statement about
# them rather than by silence, and so a reader of this inventory can see the
# whole provider surface even though only part of it is Yahoo's.
#
# A YAHOO RETENTION RULING DOES NOT REACH THESE ROWS. What does reach them is
# BALLDONTLIE's own terms, which is a separate open question and is recorded as
# one in REQUIRES_RULING below rather than answered here.

FOREIGN_PROVIDER_FIELDS: tuple = (
    ForeignProviderField(
        table="provider_player_alias", column="provider",
        provider="balldontlie",
        what="which non-Yahoo provider a mapping row belongs to",
        purpose="scopes the mapping, so one canonical player can carry one "
                "subject per provider without the rows colliding",
        if_deleted="the remaining columns describe a subject at no stated "
                   "provider, which is not an identity at all",
    ),
    ForeignProviderField(
        table="provider_player_alias", column="provider_player_key",
        provider="balldontlie",
        what="BALLDONTLIE's own identifier for a player FantasyStakes already "
             "holds a `players` row for",
        purpose="the durable link — once written, a BALLDONTLIE figure reaches "
                "the right canonical player without any name being compared "
                "again",
        if_deleted="every mapping is rediscovered from names on the next "
                   "resolution; nothing economic is lost, because no settled "
                   "record was ever written against this column",
    ),
    ForeignProviderField(
        table="provider_player_alias", column="provider_position",
        provider="balldontlie",
        what="the position BALLDONTLIE reported for that subject when the "
             "mapping was made",
        purpose="an observation an operator can audit a stale mapping against. "
                "Nothing resolves on it",
        if_deleted="a stale mapping is harder to explain; no resolution "
                   "changes, because the resolver never reads it",
    ),
    ForeignProviderField(
        table="provider_player_alias", column="provider_nfl_team",
        provider="balldontlie",
        what="the NFL team BALLDONTLIE reported for that subject when the "
             "mapping was made",
        purpose="the same audit observation as `provider_position`; a trade "
                "moves this value and never the identity",
        if_deleted="as above — an audit aid is lost, not an identity",
    ),    # ── Sprint 2B · component projection snapshots ──---------------------
    #
    # THE FIRST BALLDONTLIE MEASUREMENTS THIS PRODUCT PERSISTS. The WP1 rows
    # above are a mapping — they say who a subject is. These say what
    # BALLDONTLIE FORECAST that subject would do, which is provider content in
    # the fullest sense and is squarely BALLDONTLIE's to set terms about.
    #
    # NO YAHOO VALUE IS STORED IN ANY OF THEM. The canonical `player_id` these
    # rows hang off is a FantasyStakes primary key, and the components are
    # BALLDONTLIE's own figures.
    ForeignProviderField(
        table="provider_component_projection", column="provider",
        provider="balldontlie",
        what="which non-Yahoo provider forecast this subject-week",
        purpose="scopes the snapshot, so a second projection provider could be "
                "stored beside this one without either being mistaken for the "
                "other",
        if_deleted="a forecast attributed to nobody, which no reader may use",
    ),
    ForeignProviderField(
        table="provider_component_projection", column="provider_player_key",
        provider="balldontlie",
        what="BALLDONTLIE's own identifier for the projected subject",
        purpose="ties the snapshot back to the provider's record without "
                "re-resolving it, and lets an operator audit a mapping against "
                "the projection that used it",
        if_deleted="the canonical player_id still identifies the subject; the "
                   "provider-side trace of which record produced it is lost",
    ),
    ForeignProviderField(
        table="provider_component_projection", column="provider_game_id",
        provider="balldontlie",
        what="BALLDONTLIE's identifier for the game the projection is for, "
             "where the payload supplied one",
        purpose="lets a projection be tied to a specific fixture rather than "
                "only to a week number, which matters because postseason week "
                "numbering restarts at 1",
        if_deleted="a projection can still be found by season and week; the "
                   "fixture-level tie is lost",
    ),
    ForeignProviderField(
        table="provider_component_projection", column="provider_record_id",
        provider="balldontlie",
        what="the provider's own row identifier for the projection record, "
             "where one is published",
        purpose="correction detection — BALLDONTLIE publishes no revision "
                "number or change feed, so a re-fetch and diff is the only way "
                "to see a forecast move, and this is what a diff anchors on",
        if_deleted="corrections must be detected from the payload digest "
                   "alone, which still works but names nothing to an operator",
    ),
)


#: NOT A PROVIDER-NAMED COLUMN, AND STILL PROVIDER CONTENT. The name scan in the
#: C1 suite only flags columns spelled `provider_*` or `yahoo*`, so these two
#: would pass unnoticed — and they are the largest BALLDONTLIE payload this
#: product stores. Recorded here so the inventory is honest about volume rather
#: than only about spelling.
FOREIGN_PROVIDER_PAYLOAD_COLUMNS: tuple = (
    ("provider_component_projection", "components",
     "balldontlie", "the normalized component projection itself — forty-odd "
     "forecast quantities per subject-week"),
    ("provider_component_projection", "components_present",
     "balldontlie", "which component keys the provider actually sent, kept "
     "separate because this provider omits every zero"),
)


# ── YAHOO-DERIVED RELATIONSHIPS ──────────────────────────────────────────────
#
# FantasyStakes values whose ARRANGEMENT is Yahoo's. Neither a provider fact nor
# an ordinary derived figure; see `YahooDerivedRelationship`.

YAHOO_DERIVED_RELATIONSHIPS: tuple = (
    YahooDerivedRelationship(
        table="matchups",
        columns=("home_team_id", "away_team_id"),
        values_are="FantasyStakes team primary keys — no Yahoo value is stored "
                   "in either column",
        relationship_is="which two teams meet in a given week, and which side is "
                        "home. That is Yahoo's fixture, resolved onto our keys "
                        "in providers/persist.py `_persist_matchup` via the "
                        "team-key resolver",
        if_deleted="the season's schedule — who played whom — is gone. Every "
                   "matchup wager was settled against this pairing, so the "
                   "settled economics stay settled and the fixture they were "
                   "settled on cannot be reconstructed",
        economic_dependency=True,
    ),
)


# ── DERIVED FANTASYSTAKES STATE ──────────────────────────────────────────────
#
# These are FantasyStakes figures, not Yahoo data. They are listed because they
# were COMPUTED from provider facts and cannot be recomputed without them.

DERIVED: tuple = (
    Derived(
        name="Matchup wager settlement",
        where="betting/settlement_engine.py",
        from_fields=("matchups.home_score", "matchups.away_score",
                     "matchups.winner_team_id"),
        note="settled wagers post ledger entries; the ledger is FantasyStakes' "
             "own record and contains no Yahoo field",
    ),
    Derived(
        name="Skunk charge (widest margin of defeat)",
        where="economy/skunk.py",
        from_fields=("matchups.home_score", "matchups.away_score"),
        note="the margin is computed from Yahoo scores at week close",
    ),
    Derived(
        name="Prop pool settlement",
        where="betting/pool_engine.py, betting/pool_subjects.py",
        from_fields=("matchups.home_score", "matchups.away_score",
                     "roster_slots.slot"),
        note="pool subjects can be starter- and score-dependent",
    ),
    Derived(
        name="Dynamic challenge pricing",
        where="economy/dynamic_challenge.py",
        from_fields=("matchups.home_score", "matchups.away_score"),
        note="pricing inputs only; settled prices are stored on the challenge",
    ),
    Derived(
        name="FantasyStakes Championship Score",
        where="reports/championship_read_model.py",
        from_fields=("matchups.winner_team_id",),
        note="realized net from settled matchups and pools, frozen into an "
             "immutable snapshot at the postseason boundary",
    ),
    Derived(
        name="Yahoo Championship podium",
        where="economy/championship_podium.py",
        from_fields=("matchups.winner_team_id", "leagues.provider_current_week"),
        note="the 60/30/10 payout depends on Yahoo's own postseason result",
    ),
    Derived(
        name="Authoritative result correction",
        where="economy/championship_result_correction.py",
        from_fields=("matchups.winner_team_id",),
        note="a correction restates a RESULT; the economics are re-derived",
    ),
)


# ── THE TWO CATEGORIES THE SPRINT BRIEF ASKS FOR ─────────────────────────────

SAFE_WITHOUT_RULING: tuple = (
    "Recording the inventory itself — this module and its suite.",
    "OAuth tokens sealed at rest (AES-GCM with a context AAD) and never logged.",
    "A commissioner-initiated DISCONNECT that clears the sealed grant for a "
    "league's connection without touching any settled economic record.",
    "Refusing to widen Yahoo scopes beyond openid, email and fspt-r.",
    "Factual attribution — 'Fantasy data provided by Yahoo Fantasy' — with no "
    "claim of sponsorship, endorsement, partnership or affiliation.",
    "Failing closed when provider authority cannot be established, rather than "
    "deleting provider state on a transient failure.",
    "Not asserting, anywhere in code or documentation, that Yahoo data may be "
    "retained indefinitely.",
)

REQUIRES_RULING: tuple = (
    "Whether matchup scores and winners may be retained after a season closes "
    "— they are the evidence settled wagers were settled correctly.",
    "Whether roster/starter history may be retained for past weeks, which "
    "starter-dependent competitions were settled against.",
    "Whether Yahoo identifiers (league, team, player, matchup keys) may be "
    "retained once a league disconnects.",
    "Whether a retention PERIOD applies, and what it is.",
    "Whether deletion must cascade to FantasyStakes DERIVED state, or whether "
    "derived figures may survive the provider facts they came from.",
    "Whether the ledger's economic history — which contains no Yahoo field but "
    "was established using provider facts — is in scope at all.",
    "What a Yahoo-initiated deletion request obliges this application to do.",
    "Whether the BALLDONTLIE identity mappings in `provider_player_alias` may "
    "be retained — a question for BALLDONTLIE's terms, not Yahoo's. They are "
    "inventoried in FOREIGN_PROVIDER_FIELDS so the question has a list to be "
    "answered against, exactly as the Yahoo one does.",
    "Whether BALLDONTLIE component projection SNAPSHOTS in "
    "`provider_component_projection` may be retained, and for how long. This is "
    "the larger of the two BALLDONTLIE questions by volume — every subject, "
    "every week, every refresh — and the product has a specific reason to want "
    "history: the provider serves none, so these rows are the only record of "
    "what was knowable before a game. Again BALLDONTLIE's terms, not Yahoo's.",
)


def inventoried_columns() -> set:
    """`(table, column)` pairs this inventory covers, expanded across `/` forms."""
    pairs = set()
    for f in PROVIDER_FACTS:
        for column in (c.strip() for c in f.column.split("/")):
            pairs.add((f.table, column))
    return pairs


def related_columns() -> set:
    """`(table, column)` pairs classified as Yahoo-derived relationships."""
    return {(r.table, c) for r in YAHOO_DERIVED_RELATIONSHIPS for c in r.columns}


def foreign_provider_columns() -> set:
    """`(table, column)` pairs that are provider data from a provider that is
    NOT Yahoo. Accounted for by this inventory; not governed by it."""
    return ({(f.table, f.column) for f in FOREIGN_PROVIDER_FIELDS}
            | {(t, c) for t, c, _, _ in FOREIGN_PROVIDER_PAYLOAD_COLUMNS})


def report() -> dict:
    return {
        "gate": GATE,
        "gate_open": True,
        "provider_facts": [asdict(f) for f in PROVIDER_FACTS],
        "yahoo_derived_relationships": [
            asdict(r) for r in YAHOO_DERIVED_RELATIONSHIPS],
        "foreign_provider_fields": [asdict(f) for f in FOREIGN_PROVIDER_FIELDS],
        "foreign_provider_payload_columns": [
            {"table": t, "column": c, "provider": p, "what": w}
            for t, c, p, w in FOREIGN_PROVIDER_PAYLOAD_COLUMNS],
        "derived": [asdict(d) for d in DERIVED],
        "safe_without_ruling": list(SAFE_WITHOUT_RULING),
        "requires_ruling": list(REQUIRES_RULING),
        "economic_dependencies": [
            f"{f.table}.{f.column}" for f in PROVIDER_FACTS
            if f.economic_dependency
        ] + [
            f"{r.table}.{'/'.join(r.columns)}"
            for r in YAHOO_DERIVED_RELATIONSHIPS if r.economic_dependency
        ],
    }


def _print_human(only_gate: bool = False) -> None:
    print("YAHOO DATA RETENTION INVENTORY")
    print("=" * 78)
    print()
    print("CONTRACTUAL GATE: OPEN")
    for line in (GATE[i:i + 74] for i in range(0, len(GATE), 74)):
        print(f"  {line}")
    if only_gate:
        return
    print()
    print(f"PERSISTED PROVIDER FACTS ({len(PROVIDER_FACTS)})")
    print("-" * 78)
    for f in PROVIDER_FACTS:
        mark = " [ECONOMIC DEPENDENCY]" if f.economic_dependency else ""
        print(f"  {f.table}.{f.column}{mark}")
        print(f"      what      : {f.what}")
        print(f"      purpose   : {f.purpose}")
        print(f"      if deleted: {f.if_deleted}")
    print()
    print(f"YAHOO-DERIVED RELATIONSHIPS ({len(YAHOO_DERIVED_RELATIONSHIPS)})")
    print("-" * 78)
    for r in YAHOO_DERIVED_RELATIONSHIPS:
        mark = " [ECONOMIC DEPENDENCY]" if r.economic_dependency else ""
        print(f"  {r.table}.{' / '.join(r.columns)}{mark}")
        print(f"      values are      : {r.values_are}")
        print(f"      relationship is : {r.relationship_is}")
        print(f"      if deleted      : {r.if_deleted}")
    print()
    print(f"PROVIDER DATA THAT IS NOT YAHOO'S ({len(FOREIGN_PROVIDER_FIELDS)})")
    print("-" * 78)
    for f in FOREIGN_PROVIDER_FIELDS:
        print(f"  {f.table}.{f.column}  [{f.provider}]")
        print(f"      what      : {f.what}")
        print(f"      purpose   : {f.purpose}")
        print(f"      if deleted: {f.if_deleted}")
    for t, c, p, w in FOREIGN_PROVIDER_PAYLOAD_COLUMNS:
        print(f"  {t}.{c}  [{p}]  (payload column, not provider-named)")
        print(f"      what      : {w}")
    print()
    print(f"DERIVED FANTASYSTAKES STATE ({len(DERIVED)})")
    print("-" * 78)
    for d in DERIVED:
        print(f"  {d.name}  ({d.where})")
        print(f"      from: {', '.join(d.from_fields)}")
        print(f"      note: {d.note}")
    print()
    print("SAFE WITHOUT A YAHOO RETENTION RULING")
    print("-" * 78)
    for s in SAFE_WITHOUT_RULING:
        print(f"  · {s}")
    print()
    print("REQUIRES A YAHOO RETENTION RULING")
    print("-" * 78)
    for s in REQUIRES_RULING:
        print(f"  · {s}")


def main(argv: list | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Yahoo data retention inventory")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--gate", action="store_true")
    args = parser.parse_args(argv)

    if args.json:
        print(json.dumps(report(), indent=2))
        return 0
    _print_human(only_gate=args.gate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
