from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from maya_sawa.databases.market_macro_db import MarketMacroDatabase, MacroFetchRun
from maya_sawa.services import market_macro


def database():
    db = object.__new__(MarketMacroDatabase)
    db.engine = create_engine('sqlite://')
    db.sessions = sessionmaker(bind=db.engine)
    with db.engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE maya_sawa_macro_fetch_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, started_at DATETIME, finished_at DATETIME, status TEXT, http_status INTEGER, record_count INTEGER, detail TEXT)')

    @event.listens_for(db.engine, 'before_cursor_execute', retval=True)
    def replace_postgres_lock(connection, cursor, statement, parameters, context, many):
        return ('SELECT 1', ()) if 'pg_advisory_xact_lock' in statement else (statement, parameters)
    return db


def test_budget_rejections_are_not_new_upstream_requests():
    db = database()
    with db.sessions.begin() as session:
        for _ in range(8):
            session.add(MacroFetchRun(source='FRED', started_at=datetime.now(timezone.utc), status='error',
                                     record_count=0, detail='rateObservations:fred_daily_or_minute_budget_exhausted'))
    assert db.reserve_source_call('FRED', daily_limit=1) is not None
    assert db.reserve_source_call('FRED', daily_limit=1) is None


def test_summary_errors_do_not_double_charge_a_failed_request(monkeypatch):
    db = database()
    monkeypatch.setattr(market_macro, 'market_macro_db', db)
    market_macro._record_run('PMI', 'error', detail='upstream_http_503')
    with db.sessions() as session:
        assert session.query(MacroFetchRun).one().status == 'diagnostic_error'
    assert db.reserve_source_call('PMI', daily_limit=1) is not None
