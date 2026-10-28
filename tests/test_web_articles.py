"""Linked news articles (TechNews digests link to the full story) become reports of their own, like the first PDF report."""
from datetime import date
from pathlib import Path

from maya_sawa.services import web_articles as web

HTML = (Path(__file__).parent / "fixtures" / "technews_article.html").read_text(encoding="utf-8")
URL = "https://finance.technews.tw/2026/10/22/test-company-ai-server-target-price/?utm_source=tg_pm&utm_medium=telegram"


def test_extracts_title_date_and_only_the_story_text():
    article = web.extract_article(HTML, URL)
    assert article["title"] == "測試公司 AI 伺服器出貨強勁，外資調升目標價至 900 元"
    assert article["published_at"] == date(2026, 10, 22)                     # from the dated URL
    assert article["url"] == "https://finance.technews.tw/2026/10/22/test-company-ai-server-target-price/"  # tracking removed
    text = article["text"]
    assert text.startswith("外資某券商發布研究報告") and "目標價調升至 900 元" in text and "年增 30%" in text and "壓縮毛利率" in text
    for noise in ("googletag", "${result", "鼓勵", "咖啡", "首圖來源", "延伸閱讀", "短短一句"):
        assert noise not in text


def test_an_empty_or_too_thin_page_is_not_an_article():
    assert web.extract_article("<html><body><p>Not found</p></body></html>", URL) is None
    assert web.extract_article('<article><div class="indent"><p>只有一句很短的話。</p></div></article>', URL) is None


def test_only_the_news_sites_a_channel_is_allowed_to_link_to_are_fetched():
    assert web.allowed("https://finance.technews.tw/2026/10/22/a/")
    assert web.allowed("https://technews.tw/2026/10/22/a/")
    assert not web.allowed("https://evil.example/technews.tw/")
    assert not web.allowed("http://169.254.169.254/latest/meta-data")
    assert not web.allowed("https://technewsXtw.example/")
    assert not web.allowed("ftp://technews.tw/a")


def test_fetch_follows_the_short_link_but_refuses_a_redirect_off_the_allowed_sites():
    class Response:
        def __init__(self, url, text): self.url, self.text, self.status_code = url, text, 200
        def raise_for_status(self): pass

    class Client:
        def __init__(self, final): self.final, self.asked = final, []
        def get(self, url, **kwargs):
            self.asked.append(url)
            return Response(self.final, HTML)
    ok = Client(URL)
    assert web.fetch_article("https://pse.is/9s9l52", client=ok, delay=0)["title"].startswith("測試公司")
    assert ok.asked == ["https://pse.is/9s9l52"]
    assert web.fetch_article("https://pse.is/zzz", client=Client("https://evil.example/x"), delay=0) is None
    assert web.fetch_article("javascript:alert(1)", client=ok, delay=0) is None
