"""Free macro series survive a pod restart (2026-10-20: a deploy emptied ~45 cards for the rest of the day).

The process-local cache was the only copy of CBC/DGBAS/PMI/FRED-cached series. Each restart refetched every
source against per-day budgets that survive restarts, so after a few deploys the new pod could not refill
anything and the API returned 14 of ~60 indicators until the budgets rolled over.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from maya_sawa.databases import market_macro_db as macro_db_module
from maya_sawa.services import market_macro


class FakeStore:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.fail = False

    def save_cached_series(self, entries):
        if self.fail:
            raise RuntimeError("db down")
        for entry in entries:
            self.rows[entry["code"]] = entry

    def load_cached_series(self, max_age_days=30):
        return list(self.rows.values())


def _restart(monkeypatch):
    monkeypatch.setattr(market_macro, "_macro_local_cache", market_macro.LocalTTLCache(max_entries=128))


def _snapshot_without_db(monkeypatch):
    monkeypatch.setattr(market_macro.market_macro_db, "snapshot",
        lambda months: {"status": "ready", "indicators": [], "events": [], "sources": []})


def test_cached_series_come_back_after_a_restart_with_their_original_fetch_time(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(market_macro.market_macro_db, "save_cached_series", store.save_cached_series)
    monkeypatch.setattr(market_macro.market_macro_db, "load_cached_series", store.load_cached_series)
    _snapshot_without_db(monkeypatch)
    _restart(monkeypatch)
    service = market_macro.MarketMacroService()
    service._cache_free_series([{"code": "TW_CPI", "period": "2026-08", "value": "1.6"},
                                {"code": "TW_CPI", "period": "2026-09", "value": "1.9"}],
                               market_macro.DGBAS_SERIES, "DGBAS", "https://nstatdb.dgbas.gov.tw/dgbasAll/")
    fetched_at = store.rows["TW_CPI"]["fetchedAt"]

    _restart(monkeypatch)
    restarted = market_macro.MarketMacroService()
    assert restarted.restore_free_series_cache() == 1
    result = market_macro.asyncio.run(restarted.get(24))
    tw_cpi = next(item for item in result["indicators"] if item["code"] == "TW_CPI")
    assert tw_cpi["value"] == "1.9" and tw_cpi["referencePeriod"] == "2026-09"
    assert tw_cpi["fetchedAt"] == fetched_at


def test_a_restored_fresh_series_is_not_refetched_so_restarts_do_not_spend_the_budget(monkeypatch):
    store = FakeStore()
    store.rows["TW_PMI"] = {"code": "TW_PMI", "name": "Taiwan PMI", "unit": "index", "frequency": "monthly",
        "source": "CIER", "sourceUrl": "https://www.cier.edu.tw/pmi-trend/",
        "fetchedAt": (datetime.now(UTC) - timedelta(hours=1)).isoformat(), "freshForSeconds": 12 * 3600,
        "history": [{"period": "2026-09", "value": "52.1"}]}
    monkeypatch.setattr(market_macro.market_macro_db, "load_cached_series", store.load_cached_series)
    reserved = []
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *a, **k: reserved.append(a) or None)
    _restart(monkeypatch)
    service = market_macro.MarketMacroService()
    service.restore_free_series_cache()
    service._fetch_pmi_series()
    assert reserved == []


def test_a_database_outage_does_not_stop_the_in_memory_cache(monkeypatch):
    store = FakeStore()
    store.fail = True
    monkeypatch.setattr(market_macro.market_macro_db, "save_cached_series", store.save_cached_series)
    _restart(monkeypatch)
    service = market_macro.MarketMacroService()
    assert service._cache_free_series([{"code": "TW_CPI", "period": "2026-09", "value": "1.9"}],
        market_macro.DGBAS_SERIES, "DGBAS", "https://nstatdb.dgbas.gov.tw/dgbasAll/") == 1
    assert market_macro._macro_local_cache.get("series:TW_CPI")["history"][-1]["value"] == "1.9"


def test_store_keeps_one_row_per_series_and_drops_entries_older_than_the_fallback_window():
    database = object.__new__(macro_db_module.MarketMacroDatabase)
    database.engine = create_engine("sqlite://")
    database.sessions = sessionmaker(bind=database.engine)
    macro_db_module.MacroCachedSeries.__table__.create(database.engine)
    now = datetime.now(UTC)
    entry = {"code": "TW_CPI", "fetchedAt": now.isoformat(), "history": [{"period": "2026-09", "value": "1.9"}]}
    database.save_cached_series([entry])
    database.save_cached_series([{**entry, "history": [{"period": "2026-10", "value": "2.0"}]}])
    database.save_cached_series([{"code": "OLD", "fetchedAt": (now - timedelta(days=31)).isoformat(), "history": []}])
    loaded = database.load_cached_series(max_age_days=30)
    assert [item["code"] for item in loaded] == ["TW_CPI"]
    assert loaded[0]["history"] == [{"period": "2026-10", "value": "2.0"}]
