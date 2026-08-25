"""Regression proof for the Account Summary's Final POR pot read model."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import ledger.ledger as ledger_module
from db.schema import Base, League, Team
from economy.championship_pots import pot_balances
from economy.economy_events import fantasystakes_championship_account
from economy.league_settings_view import in_season_rows
from ledger.ledger import post as ledger_post
from reports.my_account import get_my_account_summary


def _database(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    ledger_module._LedgerBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(ledger_module, "engine", engine)
    monkeypatch.setattr(ledger_module, "SessionLocal", factory)
    return factory()


def _credit(db, account: str, cents: int, *, door: str = "test_read_model"):
    ledger_post([("world", -cents), (account, cents)], door=door, session=db)


def test_account_summary_uses_only_its_league_season_pot(monkeypatch):
    db = _database(monkeypatch)
    try:
        db.add_all([
            League(id=1, name="Current", season=2026),
            League(id=2, name="Other league", season=2026),
            League(id=3, name="Uninitialized", season=2026),
            Team(id=11, league_id=1, team_name="A", owner="A",
                 email="a@example.test", provider="demo",
                 provider_team_key="demo:1:a"),
            Team(id=21, league_id=2, team_name="B", owner="B",
                 email="b@example.test", provider="demo",
                 provider_team_key="demo:2:b"),
            Team(id=31, league_id=3, team_name="C", owner="C",
                 email="c@example.test", provider="demo",
                 provider_team_key="demo:3:c"),
        ])
        db.flush()

        current = fantasystakes_championship_account(1, 2026)
        _credit(db, current, 146_000)
        _credit(db, fantasystakes_championship_account(1, 2025), 22_222)
        _credit(db, fantasystakes_championship_account(2, 2026), 33_333)

        # These decoys make the retired bridge return a conspicuously wrong
        # value rather than passing because all account families happen to be
        # equal or empty.
        _credit(db, "championship", 91_111)
        _credit(db, "championship:1", 82_222)
        _credit(db, "championship:2", 73_333)
        _credit(db, "championship:3", 64_444)
        db.commit()

        summary = get_my_account_summary(11, db)
        settings_current = next(
            row for row in in_season_rows(db, league_id=1, season=2026)
            if row.id == "current-fs-pot"
        )
        assert summary.championship_pot_cents == 146_000
        assert summary.championship_pot_cents == settings_current.amount_cents
        assert summary.championship_pot_cents == pot_balances(
            db, league_id=1, season=2026,
        ).fantasystakes_cents

        assert get_my_account_summary(21, db).championship_pot_cents == 33_333
        assert get_my_account_summary(31, db).championship_pot_cents == 0
    finally:
        db.close()
