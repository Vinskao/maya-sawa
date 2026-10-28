import httpx
import pytest

from maya_sawa.services import telegram_notify as tn


def test_format_marks_attention_and_trims_long_body():
    update = tn.format_message("update", "台股分析", "更新 12 檔")
    assert update.startswith("✅ 台股分析") and "更新 12 檔" in update
    attention = tn.format_message("attention", "週報文章", "需要登入 Claude")
    assert attention.startswith("⚠️ 需要處理 · 週報文章")
    assert len(tn.format_message("update", "t", "x" * 9000)) <= tn.MAX_LENGTH


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        tn.format_message("spam", "t", "b")


def test_secret_looking_text_is_masked():
    text = tn.format_message("attention", "t", "token 123456789:ABCdefGhIJKlmNoPQRsTUVwxyz0123456789 key sk-abcdefghijklmnopqrstuvwx")
    assert "ABCdef" not in text and "sk-abcdef" not in text and "已遮蔽" in text


def test_send_is_silent_without_token_or_chat(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert tn.send("update", "t", "b") == {"sent": False, "reason": "not configured"}


def test_send_posts_only_to_the_owner_chat(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    seen = {}

    def handler(request: httpx.Request):
        seen["url"], seen["json"] = str(request.url), __import__("json").loads(request.content)
        return httpx.Response(200, json={"ok": True})

    result = tn.send("update", "標題", "內容", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert result == {"sent": True}
    assert seen["url"] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert seen["json"]["chat_id"] == "42" and seen["json"]["text"] == "✅ 標題\n內容"


def test_send_failure_is_reported_without_leaking_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"ok": False})))
    result = tn.send("update", "t", "b", client=client)
    assert result["sent"] is False and "123:abc" not in str(result)


NAMES = {"3008": "大立光", "3017": "奇鋐", "8996": "高力", "2330": "台積電", "META": "Meta Platforms", "TXF": "台指期"}


def test_codes_get_their_names():
    body = ("結論改變：\n3008 賣→中立：對齊研究圖三項皆中性，無新硬資料支持賣\n"
            "3017 買→中立；8996 買→中立：交貨回研究圖中性（存貨天數偏高）")
    assert tn.name_codes(body, NAMES) == (
        "結論改變：\n3008 大立光 賣→中立：對齊研究圖三項皆中性，無新硬資料支持賣\n"
        "3017 奇鋐 買→中立；8996 高力 買→中立：交貨回研究圖中性（存貨天數偏高）")


def test_codes_already_named_are_left_alone():
    assert tn.name_codes("3008 大立光 賣→中立；台積電 2330 買；奇鋐(3017) 中立", NAMES) == \
        "3008 大立光 賣→中立；台積電 2330 買；奇鋐(3017) 中立"


def test_only_known_codes_change_and_numbers_inside_values_do_not():
    text = "META 買、TXF 中立，目標價 3008.5、2026-10-28 更新 9999 檔、存貨 2330天、BTC-CRYPTO"
    assert tn.name_codes(text, NAMES) == \
        "META Meta Platforms 買、TXF 台指期 中立，目標價 3008.5、2026-10-28 更新 9999 檔、存貨 2330天、BTC-CRYPTO"
    assert tn.name_codes(text, {}) == text
