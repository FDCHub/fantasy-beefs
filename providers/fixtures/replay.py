"""Fixture replay — the offline transport (§3, §16, C-1).

`FixtureTransport` satisfies providers.base.ProviderTransport exactly. That is
the whole design: identity, normalization, finality and persistence cannot tell
it from `YahooLiveTransport`, so certifying them against recorded data certifies
the same code that would run live. A separate "test mode" inside the live
transport would have certified a branch that production never takes.

NO CREDENTIALS, NO NETWORK, NO CLOCK. This class reads files. It holds no token,
opens no socket, and takes its `observed_at` from the manifest's `replay_now`
rather than from `datetime.now` — which is what makes the 24-hour Gate-2
staleness tests (§14, C-13) deterministic instead of dependent on when the suite
happened to run.

A MISSING FIXTURE RAISES. It does not return an empty payload. An empty return
would look to the layers above exactly like "the provider has no data for that
week", which is a meaningful state (§6 horizon, end of schedule) that must not
be forgeable by a missing file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from providers.errors import ProviderTransportError
from providers.fixtures.record import CAPTURED, SYNTHETIC, payload_sha256

#: Where the committed corpus lives.
DEFAULT_CORPUS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "corpus")


@dataclass(frozen=True)
class LoadedFixture:
    fixture_id: str
    provenance: str
    layer: str
    endpoint: str
    league_key: str
    season: int | None
    week: int | None
    payload: object
    manifest: dict

    @property
    def declared_sha256(self) -> str:
        return self.manifest.get("payload_sha256", "")

    def verify(self) -> None:
        """Re-hash the payload on disk and compare to the manifest.

        Run on every load, not only in certification. A fixture whose bytes
        drifted from its manifest is either a bad edit or a bad merge, and
        either way the manifest's provenance claim no longer describes the
        payload it is attached to.
        """
        actual = payload_sha256(self.payload)
        if actual != self.declared_sha256:
            raise ProviderTransportError(
                f"fixture {self.fixture_id} payload SHA-256 {actual} does not "
                f"match its manifest's {self.declared_sha256}. The manifest's "
                f"provenance claim no longer describes this payload; refusing "
                f"to replay it.")
        if self.provenance not in (CAPTURED, SYNTHETIC):
            raise ProviderTransportError(
                f"fixture {self.fixture_id} declares provenance "
                f"{self.provenance!r}, which is neither CAPTURED nor SYNTHETIC. "
                f"§16 permits no third value and no default.")


def load_corpus(directory: str | None = None) -> dict[str, LoadedFixture]:
    """Load and verify every fixture in a corpus directory, by fixture_id."""
    directory = directory or DEFAULT_CORPUS_DIR
    if not os.path.isdir(directory):
        return {}

    out: dict[str, LoadedFixture] = {}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".manifest.json"):
            continue
        fixture_id = name[: -len(".manifest.json")]
        with open(os.path.join(directory, name), encoding="utf-8") as handle:
            manifest = json.load(handle)
        payload_path = os.path.join(directory, f"{fixture_id}.json")
        if not os.path.exists(payload_path):
            raise ProviderTransportError(
                f"fixture {fixture_id} has a manifest but no payload file.")
        with open(payload_path, encoding="utf-8") as handle:
            payload = json.load(handle)

        fixture = LoadedFixture(
            fixture_id=fixture_id,
            provenance=manifest.get("provenance", "<undeclared>"),
            layer=manifest.get("layer", "<undeclared>"),
            endpoint=manifest.get("endpoint", ""),
            league_key=manifest.get("league_key", ""),
            season=manifest.get("season"),
            week=manifest.get("week"),
            payload=payload,
            manifest=manifest,
        )
        fixture.verify()
        out[fixture_id] = fixture
    return out


def provenance_counts(corpus: dict[str, LoadedFixture]) -> dict[str, int]:
    """Exact CAPTURED / SYNTHETIC counts — the §17 C-2 report line."""
    counts = {CAPTURED: 0, SYNTHETIC: 0}
    for fixture in corpus.values():
        counts[fixture.provenance] = counts.get(fixture.provenance, 0) + 1
    return counts


class FixtureTransport:
    """Offline ProviderTransport backed by a recorded corpus.

    `is_fixture_transport` is a class attribute rather than an isinstance check
    at the call site, so C-1 can assert "the transport in use is a fixture one"
    by reading an attribute — a claim that survives subclassing and does not
    require the certification harness to import the live class (which is the
    point: an offline run must not need yfpy present).
    """

    provider = "yahoo"
    is_fixture_transport = True

    def __init__(self, corpus_dir: str | None = None,
                 corpus: dict[str, LoadedFixture] | None = None,
                 frozen_now: datetime | None = None) -> None:
        self._corpus = corpus if corpus is not None else load_corpus(corpus_dir)
        self._frozen_now = frozen_now
        #: Every fetch this transport served, for C-1's evidence that fixture
        #: transport was DEFINITELY used rather than merely available.
        self.fetch_log: list[tuple[str, str, int | None]] = []

    def __repr__(self) -> str:
        return f"<FixtureTransport {len(self._corpus)} fixtures (offline)>"

    # ── Lookup ────────────────────────────────────────────────────────────────

    def _find(self, *, endpoint: str, league_key: str,
              week: int | None = None, team_key: str | None = None
              ) -> LoadedFixture:
        for fixture in self._corpus.values():
            if fixture.layer != "L1_RAW":
                continue
            if fixture.endpoint != endpoint or fixture.league_key != league_key:
                continue
            if week is not None and fixture.week != week:
                continue
            if team_key is not None and \
                    fixture.manifest.get("team_key") != team_key:
                continue
            return fixture
        raise ProviderTransportError(
            f"no L1 fixture for endpoint={endpoint!r} league={league_key!r} "
            f"week={week!r} team={team_key!r}. Refusing to return an empty "
            f"payload: an empty result is a MEANINGFUL provider state (end of "
            f"schedule, §6 horizon) and must not be forgeable by a missing "
            f"file.")

    # ── ProviderTransport ─────────────────────────────────────────────────────

    def observed_at(self) -> datetime:
        """The frozen replay instant, or the corpus's declared replay_now.

        Falls back to the real clock only when neither is available, and that
        fallback is not reachable from certification — every fixture written by
        providers/fixtures/build_corpus.py declares replay_now.
        """
        if self._frozen_now is not None:
            return self._frozen_now
        for fixture in self._corpus.values():
            replay_now = fixture.manifest.get("replay_now")
            if replay_now:
                stamp = datetime.fromisoformat(replay_now)
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                return stamp
        return datetime.now(timezone.utc)

    def fetch_league(self, league_key: str):
        self.fetch_log.append(("league", league_key, None))
        return self._find(endpoint="league", league_key=league_key).payload

    def fetch_scoreboard(self, league_key: str, week: int):
        self.fetch_log.append(("scoreboard", league_key, week))
        return self._find(endpoint="scoreboard", league_key=league_key,
                          week=week).payload

    def fetch_teams(self, league_key: str):
        self.fetch_log.append(("teams", league_key, None))
        return self._find(endpoint="teams", league_key=league_key).payload

    def fetch_team_roster(self, league_key: str, team_key: str, week: int):
        self.fetch_log.append(("roster", f"{league_key}/{team_key}", week))
        return self._find(endpoint="roster", league_key=league_key, week=week,
                          team_key=team_key).payload

    # ── Corpus access, for certification ──────────────────────────────────────

    @property
    def corpus(self) -> dict[str, LoadedFixture]:
        return dict(self._corpus)

    def l2_fixtures(self) -> dict[str, LoadedFixture]:
        return {k: v for k, v in self._corpus.items()
                if v.layer == "L2_NORMALIZED"}