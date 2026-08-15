"""Fixture capture: scrubbing, manifests, provenance (§16, C-17).

THE SCRUBBER RUNS BEFORE ANYTHING IS WRITTEN TO DISK, AND ITS OUTPUT IS WHAT
GETS HASHED. That ordering matters: hashing the pre-scrub bytes would put a
digest of credential material into a file committed to Git, and the manifest is
supposed to be safe to publish.

SCRUBBING IS BY KEY AND BY PATTERN, BOTH. Key-based scrubbing catches the fields
we know Yahoo uses (providers/yahoo/transport.CREDENTIAL_KEYS, defined beside
the loader that reads them, so the two cannot drift). Pattern-based scrubbing
catches the ones we do not — a bearer token embedded in a URL, an Authorization
header inside a captured HTTP envelope. Either alone leaves a gap: a key list
cannot anticipate a new field name, and a regex cannot know that `guid` is
sensitive.

A REDACTION IS RECORDED, NOT SILENT. Every substitution appends to the
manifest's `scrub_actions`, so a reviewer can see WHAT was removed from a
fixture without having seen the original. A scrubber that quietly cleaned a
payload would leave no way to tell a clean capture from a heavily-redacted one.

PROVENANCE HAS NO DEFAULT. `write_fixture` requires it as a keyword and
validates it against the two permitted values. Fabricating CAPTURED provenance
for a synthetic payload is the one thing §16 names outright, and the absence of
a default is the mechanical guard against doing it by accident.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from providers.yahoo.transport import CREDENTIAL_KEYS

CAPTURED = "CAPTURED"
SYNTHETIC = "SYNTHETIC"
_PROVENANCE_VALUES = (CAPTURED, SYNTHETIC)

REDACTED = "***REDACTED***"

#: Value-level patterns that indicate credential material regardless of the key
#: it arrived under. Deliberately broad: a false positive costs a redacted test
#: fixture, a false negative costs a leaked token in Git history.
_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bBasic\s+[A-Za-z0-9+/=]{8,}", re.IGNORECASE),
    # Yahoo OAuth2 access tokens are long opaque strings that begin with a
    # recognizable prefix; refresh tokens likewise.
    re.compile(r"\bA[A-Za-z0-9]{20,}~[A-Za-z0-9~._-]{10,}"),
    re.compile(r"(?:access_token|refresh_token|client_secret|consumer_secret)"
               r"\s*[=:]\s*[\"']?[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
)

#: Personally identifying fields that are not credentials but should not enter
#: Git from a real capture. Manager nicknames are display data and are kept —
#: an email is not.
_PII_KEYS = frozenset({"email", "manager_email", "guid_email"})


@dataclass
class FixtureManifest:
    """Everything §16 requires a fixture to declare about itself."""

    fixture_id: str
    provenance: str
    layer: str                    # "L1_RAW" | "L2_NORMALIZED"
    endpoint: str
    league_key: str
    season: int | None = None
    week: int | None = None
    captured_at: str | None = None
    http_status: int | None = None
    client_library: str | None = None
    payload_sha256: str = ""
    scrub_actions: list[str] = field(default_factory=list)
    #: The instant a replay presents as "now". Freezing it is what makes the
    #: 24-hour Gate-2 staleness tests deterministic (§14, C-13).
    replay_now: str | None = None
    notes: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _scrub_text(text: str, actions: list[str], where: str) -> str:
    out = text
    for pattern in _VALUE_PATTERNS:
        out, count = pattern.subn(REDACTED, out)
        if count:
            actions.append(f"{where}: redacted {count} value(s) matching "
                           f"{pattern.pattern[:40]!r}")
    return out


def scrub(node: Any, actions: list[str] | None = None,
          path: str = "$") -> tuple[Any, list[str]]:
    """Recursively remove credential and PII material. Returns (clean, actions).

    Structure is PRESERVED — a redacted field keeps its key and gets a sentinel
    value rather than being deleted. Deleting it would change the payload shape
    the parser is being certified against, which would make the fixture a test
    of a payload Yahoo never sends.
    """
    actions = [] if actions is None else actions

    if isinstance(node, dict):
        clean = {}
        for key, value in node.items():
            here = f"{path}.{key}"
            if key in CREDENTIAL_KEYS:
                clean[key] = REDACTED
                actions.append(f"{here}: credential key redacted")
                continue
            if key in _PII_KEYS:
                clean[key] = REDACTED
                actions.append(f"{here}: PII key redacted")
                continue
            clean[key], _ = scrub(value, actions, here)
        return clean, actions

    if isinstance(node, list):
        clean_list = []
        for index, value in enumerate(node):
            item, _ = scrub(value, actions, f"{path}[{index}]")
            clean_list.append(item)
        return clean_list, actions

    if isinstance(node, str):
        return _scrub_text(node, actions, path), actions

    return node, actions


def payload_sha256(payload: Any) -> str:
    """SHA-256 of the canonical serialization of a scrubbed payload.

    Canonical (sorted keys, fixed separators) so the digest is a property of the
    CONTENT, not of how json.dump happened to lay it out. A digest that changed
    when whitespace changed would report a fixture as modified every time the
    file was reformatted, and would therefore stop being read.
    """
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def write_fixture(directory: str, *, fixture_id: str, provenance: str,
                  layer: str, endpoint: str, league_key: str,
                  payload: Any, season: int | None = None,
                  week: int | None = None, captured_at: str | None = None,
                  http_status: int | None = None,
                  client_library: str | None = None,
                  replay_now: str | None = None,
                  notes: str | None = None) -> FixtureManifest:
    """Scrub, hash and write one fixture plus its manifest.

    `provenance` is REQUIRED and validated. There is no default and no
    inference: §16 forbids fabricating CAPTURED provenance, and the only
    reliable guard against doing it absent-mindedly is that the caller must type
    the word.
    """
    if provenance not in _PROVENANCE_VALUES:
        raise ValueError(
            f"provenance must be one of {_PROVENANCE_VALUES!r}, got "
            f"{provenance!r}. §16: a fixture's provenance is declared, never "
            f"inferred, and CAPTURED is never fabricated.")
    if layer not in ("L1_RAW", "L2_NORMALIZED"):
        raise ValueError(f"layer must be L1_RAW or L2_NORMALIZED, got {layer!r}")

    clean, actions = scrub(payload)
    digest = payload_sha256(clean)

    manifest = FixtureManifest(
        fixture_id=fixture_id, provenance=provenance, layer=layer,
        endpoint=endpoint, league_key=league_key, season=season, week=week,
        captured_at=captured_at, http_status=http_status,
        client_library=client_library, payload_sha256=digest,
        scrub_actions=actions, replay_now=replay_now, notes=notes,
    )

    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, f"{fixture_id}.json"), "w",
              encoding="utf-8", newline="\n") as handle:
        json.dump(clean, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with open(os.path.join(directory, f"{fixture_id}.manifest.json"), "w",
              encoding="utf-8", newline="\n") as handle:
        json.dump(manifest.as_dict(), handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def capture_live(transport, directory: str, *, league_key: str, week: int,
                 season: int, fixture_prefix: str,
                 client_library: str | None = None,
                 team_keys: tuple[str, ...] = ()) -> list[FixtureManifest]:
    """Record L1 fixtures from a LIVE transport. Provenance is CAPTURED.

    THE ONLY FUNCTION IN THE REPOSITORY PERMITTED TO WRITE CAPTURED PROVENANCE,
    and it can only be reached with a live transport in hand — which requires
    real credentials and real network access. That is the mechanical reason the
    corpus is entirely SYNTHETIC: this function has never been able to run,
    because the Yahoo application is not authorized for the Fantasy Sports API
    (the blocker recorded in spec/pool_stat_vocabulary_rev1_0.json).

    It is written and kept ready so that the day authorization lands, capturing
    a real corpus is a command rather than a project.

    `team_keys` additionally captures each team's roster for the week. WP2 added
    it because a week captured without rosters cannot certify the Pool stat
    source against real bytes, which is half of what a captured corpus is for.
    """
    now = datetime.now(timezone.utc).isoformat()
    manifests = []
    for endpoint, fetch in (
        ("league", lambda: transport.fetch_league(league_key)),
        ("teams", lambda: transport.fetch_teams(league_key)),
        ("scoreboard", lambda: transport.fetch_scoreboard(league_key, week)),
    ):
        manifests.append(write_fixture(
            directory,
            fixture_id=f"{fixture_prefix}_{endpoint}_w{week}",
            provenance=CAPTURED, layer="L1_RAW", endpoint=endpoint,
            league_key=league_key, payload=fetch(), season=season,
            week=week, captured_at=now, http_status=200,
            client_library=client_library, replay_now=now,
        ))

    for team_key in team_keys:
        ordinal = team_key.rsplit(".", 1)[-1]
        manifest = write_fixture(
            directory,
            fixture_id=f"{fixture_prefix}_roster_t{ordinal}_w{week}",
            provenance=CAPTURED, layer="L1_RAW", endpoint="roster",
            league_key=league_key,
            payload=transport.fetch_team_roster(league_key, team_key, week),
            season=season, week=week, captured_at=now, http_status=200,
            client_library=client_library, replay_now=now)
        # The roster lookup is keyed on team_key as well as week, so the
        # manifest must carry it or `FixtureTransport._find` cannot serve it.
        manifest.notes = f"team_key={team_key}"
        _rewrite_manifest(directory, manifest, extra={"team_key": team_key})
        manifests.append(manifest)
    return manifests


def _rewrite_manifest(directory: str, manifest: FixtureManifest,
                      *, extra: dict) -> None:
    """Re-emit one manifest with extra top-level keys. Payload untouched.

    The payload hash is computed over the PAYLOAD, never over the manifest, so
    adding a lookup key here cannot invalidate the provenance claim it carries.
    """
    payload = manifest.as_dict()
    payload.update(extra)
    with open(os.path.join(directory, f"{manifest.fixture_id}.manifest.json"),
              "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


#: The weeks a POSTSEASON capture must cover, expressed as a rule rather than as
#: numbers: from the league's own `playoff_start_week` through its
#: `season_final_week`, inclusive.
#:
#: WHY A DEDICATED ENTRY POINT (WP2 §21, §40). C-25 reports the Yahoo
#: PostseasonBracketSource as NOT CERTIFIED because no captured payload exists
#: for a league that has PLAYED a postseason — and a regular-season capture, of
#: which any number could be taken, cannot close that gap. This function states
#: precisely what would: every postseason week's scoreboard and league settings
#: from a real league whose bracket has run to completion.
def capture_postseason(transport, directory: str, *, league_key: str,
                       season: int, playoff_start_week: int,
                       season_final_week: int, fixture_prefix: str,
                       team_keys: tuple[str, ...] = (),
                       client_library: str | None = None
                       ) -> list[FixtureManifest]:
    """Capture every postseason week of a real league. Provenance is CAPTURED.

    THE EXACT EVIDENCE THE YAHOO BRACKET ADAPTER IS BLOCKED ON, and nothing
    beyond it. Each week's scoreboard is recorded as it arrives, scrubbed and
    hashed, so a reviewer can read the raw bytes and answer the four questions
    WP1D's adapter needs an authoritative answer to:

        which teams entered the championship field
        which of the week's matchups are on the championship track
        which matchup is the championship final
        which final-week matchup is the official third-place game

    IT ANSWERS NONE OF THEM ITSELF, AND MUST NOT. Capturing is not certifying.
    If the captured bytes turn out to carry no bracket discriminator, that is a
    finding — the adapter stays unbuilt and Yahoo stays fail-closed — and this
    function's job is to make that finding checkable rather than assumed. Under
    no circumstance may a synthetic payload be written through here; §16 forbids
    fabricating CAPTURED provenance and `write_fixture` validates the word.

    STORAGE BOUNDARY (WP2 §22). What this writes is a fixture corpus for
    OFFLINE CERTIFICATION, not application persistence: nothing here is read by
    a running league, and no Yahoo response is stored in the database. Before a
    capture is committed, the Yahoo storage-boundary review must confirm the
    corpus may hold it.

    ── WHAT THIS DOES NOT YET CAPTURE (WP2B finding) ────────────────────────

    IT COVERS LEAGUE METADATA, TEAMS, PER-WEEK SCOREBOARDS AND ROSTERS — and
    NOT `league/{key}/settings` or `league/{key}/standings`. Those two are named
    in the WP2B evidence set because `num_playoff_teams` (the championship field
    SIZE) and the standings resource are the two places a bracket discriminator
    might live outside the scoreboard, and neither is reachable through the
    current `ProviderTransport`, which exposes only fetch_league / fetch_teams /
    fetch_scoreboard / fetch_team_roster.

    THEY WERE DELIBERATELY NOT ADDED BLIND. Extending the transport and this
    helper for two payloads whose shape nobody has ever seen would be plumbing
    built on an assumption, and WP2B's own gate forbids that. The extension is a
    ten-line change and belongs to the package that can finally run it against a
    real response — see YAHOO_API_AUTHORIZATION_FINDING in providers/certify.
    """
    if playoff_start_week > season_final_week:
        raise ValueError(
            f"playoff_start_week {playoff_start_week} is after "
            f"season_final_week {season_final_week}; there is no postseason "
            f"window to capture.")

    now = datetime.now(timezone.utc).isoformat()
    manifests = [write_fixture(
        directory, fixture_id=f"{fixture_prefix}_league",
        provenance=CAPTURED, layer="L1_RAW", endpoint="league",
        league_key=league_key, payload=transport.fetch_league(league_key),
        season=season, captured_at=now, http_status=200,
        client_library=client_library, replay_now=now,
        notes="postseason capture — league settings and boundaries")]
    manifests.append(write_fixture(
        directory, fixture_id=f"{fixture_prefix}_teams",
        provenance=CAPTURED, layer="L1_RAW", endpoint="teams",
        league_key=league_key, payload=transport.fetch_teams(league_key),
        season=season, captured_at=now, http_status=200,
        client_library=client_library, replay_now=now))

    for week in range(playoff_start_week, season_final_week + 1):
        manifests.append(write_fixture(
            directory, fixture_id=f"{fixture_prefix}_scoreboard_w{week}",
            provenance=CAPTURED, layer="L1_RAW", endpoint="scoreboard",
            league_key=league_key,
            payload=transport.fetch_scoreboard(league_key, week),
            season=season, week=week, captured_at=now, http_status=200,
            client_library=client_library, replay_now=now,
            notes=("postseason week — the bracket evidence C-25 is blocked on")))
        for team_key in team_keys:
            ordinal = team_key.rsplit(".", 1)[-1]
            manifest = write_fixture(
                directory,
                fixture_id=f"{fixture_prefix}_roster_t{ordinal}_w{week}",
                provenance=CAPTURED, layer="L1_RAW", endpoint="roster",
                league_key=league_key,
                payload=transport.fetch_team_roster(league_key, team_key, week),
                season=season, week=week, captured_at=now, http_status=200,
                client_library=client_library, replay_now=now)
            _rewrite_manifest(directory, manifest, extra={"team_key": team_key})
            manifests.append(manifest)
    return manifests
