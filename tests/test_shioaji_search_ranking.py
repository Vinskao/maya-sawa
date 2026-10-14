from types import SimpleNamespace

from maya_sawa.services.shioaji_market import ShioajiMarketService, _is_warrant


def _stock(code, name):
    return SimpleNamespace(code=code, name=name, security_type="STK")


def test_warrants_are_recognised_by_code_range_and_name():
    assert _is_warrant("040629", "創意統一5A購03")
    assert _is_warrant("04618T", "創意中信63售03")
    assert _is_warrant("712345", "某某元大購01")
    assert not _is_warrant("3443", "創意")
    assert not _is_warrant("00878", "國泰永續高股息")
    assert not _is_warrant("00631L", "元大台灣50正2")


def test_name_search_puts_the_common_stock_first_and_drops_warrants(monkeypatch):
    contracts = [_stock("040629", "創意統一5A購03"), _stock("04618T", "創意中信63售03"),
                 _stock("3443", "創意"), _stock("00999", "創意概念ETF")]
    monkeypatch.setattr(ShioajiMarketService, "_iter_contracts", staticmethod(lambda _stocks: contracts))
    api = SimpleNamespace(Contracts=SimpleNamespace(Stocks=object()))
    results = ShioajiMarketService._search_contracts(api, "創意", "stock")
    assert [row["code"] for row in results] == ["3443", "00999"]
