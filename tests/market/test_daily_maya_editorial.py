from maya_sawa.services.daily_maya_editorial import review_price_language


def test_rejects_stock_price_level_anywhere_not_financial_data():
    assert review_price_language('財報顯示營收年增 20%。目前股價為 120 元。')
    assert not review_price_language('財報顯示營收年增 20%，DRAM 合約價為 120 美元。')


def test_price_movement_cannot_be_cause_but_can_be_effect():
    assert review_price_language('因為股價大跌，所以公司前景變差。')
    assert review_price_language('股價大跌，因此下調投資判斷。')
    assert not review_price_language('因財報低於預期，今天股價大跌。')


def test_unattributed_price_movement_is_flagged_for_review():
    assert review_price_language('市場消息。今天股價大漲。')


def test_rejects_common_stock_quote_without_copula():
    assert review_price_language('台積電目前股價 120 元。')
    assert review_price_language('收盤價：1,200 元。')


def test_price_quote_allowed_when_relevant_financial_cause_is_present():
    assert not review_price_language('因財報超越預期，台積電目前股價 120 元。')


def test_event_cause_may_include_price_level_and_percentage():
    assert not review_price_language('因財報不如預期，蘋果股價下跌 10%，收於 120 元。')


def test_raw_moving_average_quote_dump_is_flagged():
    assert review_price_language('10/28 收 2,425（+1.04%），5 日 +0.2%、20 日 -3.0%；高於 5 日線 2,407，低於 10 日線 2,430。')
