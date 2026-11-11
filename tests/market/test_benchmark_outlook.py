"""2026-11-11: the benchmark sets one annual AI long-term outlook that daily readings and holding analyses build on."""
import pytest
from fastapi import HTTPException

from maya_sawa.api.market import AGENT_PRODUCT_TYPES, analysis_target
from maya_sawa.services.benchmark_outlook import validate_outlook_content
from maya_sawa.services.daily_maya_sources import validate_sources
from maya_sawa.services.podcast_feed import describe_sources

OUTLOOK = """【年度格局】2026
一句話：AI 資本支出仍在擴張，瓶頸從 GPU 轉向 HBM、先進封裝與電力。

T1 雲端資本支出持續擴張
依據：Alphabet、Microsoft 股東年報對資料中心投資的說法（benchmark 年報主張）
環節：雲端服務商、AI 加速器、先進製程晶圓代工
短線印證指標：四家 CSP 每季資本支出指引、台積電月營收
反證：兩家以上 CSP 下修資本支出指引

T2 HBM 供給是加速器出貨上限
依據：SK 海力士事業報告書
環節：AI 記憶體（HBM）、測試機台
短線印證指標：HBM 報價與 SK 海力士季報
反證：HBM 供給轉為過剩
"""


def test_outlook_is_one_shared_record_the_agent_may_write():
    assert analysis_target("ai", "outlook") == ("outlook", "AI")
    with pytest.raises(HTTPException):
        analysis_target("2330", "outlook")
    assert "outlook" in AGENT_PRODUCT_TYPES


def test_outlook_needs_a_year_and_numbered_themes_each_with_evidence_stages_signals_and_a_falsifier():
    assert validate_outlook_content(OUTLOOK)["themes"] == ["T1", "T2"]
    for broken in (OUTLOOK.replace("【年度格局】2026", "年度格局"),
                   OUTLOOK.replace("反證：HBM 供給轉為過剩", ""),
                   OUTLOOK.replace("短線印證指標：四家 CSP 每季資本支出指引、台積電月營收", ""),
                   "【年度格局】2026\n一句話：只有結論。"):
        with pytest.raises(ValueError):
            validate_outlook_content(broken)


class Analyses:
    def read(self, kind, code):
        return {"history": [{"revision": 3}] if (kind, code) == ("outlook", "AI") else []}


def test_daily_reading_may_cite_the_outlook_and_show_notes_name_it():
    validate_sources(["outlook:AI:3"], Analyses())
    with pytest.raises(ValueError):
        validate_sources(["outlook:AI:4"], Analyses())
    assert describe_sources(["outlook:AI:3"]) == ["TY Multiverse 年度 AI 長線格局（第 3 版）"]
