"""The first 200 characters of an AI analysis are taken on their own (Threads accepts 200), so they must say what new
evidence changed or kept the rating. On 2026-11-03 the real analyses opened with the data-cutoff header and then price
action (LITE-US: "10/22 單日 -11.5%，低於 MA20，RSI 33.8"); the owner wanted the report / earnings / macro insight first.

tests/fixtures/analysis_openings_2026-11-03.json holds the first 420 characters of five live analyses (public data).
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_analysis_lead", ROOT / "maya_sawa" / "public_scripts" / "check_analysis_lead.py")
lead = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lead)
REAL = json.loads((Path(__file__).parents[1] / "fixtures" / "analysis_openings_2026-11-03.json").read_text(encoding="utf-8"))

GOOD_LITE = ("【結論】買（維持）\n重點：Lumentum 11/2 公布 FY27Q1 營收 12.63 億美元、年增 136.5%，交貨證據比 8 月新聞稿更強；"
             "Marvell 以全股票合併，預計 2028 上半年完成，技術力順風不變，因此維持買進。\n\nLumentum｜資料截點：IB 日線 2026-10-28")
GOOD_CHANGE = ("【結論】中立（由買下調）\n重點：新報告指出 EMIB-T 良率僅 20–30%，9 月營收年增放緩至 8%，"
               "交貨由順風轉中性，兩項順風減為一項，因此下調為中立。\n\n欣興｜資料截點：2026-10-30")
GOOD_NO_NEWS = ("【結論】中立（維持）\n重點：本輪沒有新報告、新財報或新總經數字；下一個證據是 11/12 公布的 10 月營收，"
                "在那之前交貨與循環判斷不變，維持中立。\n\n聯亞｜資料截點：2026-10-30")


@pytest.mark.parametrize("code", sorted(REAL))
def test_every_live_analysis_of_2026_11_03_fails_for_the_reason_the_owner_gave(code):
    problems = lead.check_lead(REAL[code]["opening"])
    assert problems, f"{code} should not pass"
    joined = " ".join(problems)
    assert "資料截點" in joined or "研究期間" in joined or "標題" in joined       # the header comes first


def test_the_price_action_that_led_lite_is_named():
    joined = " ".join(lead.check_lead(REAL["LITE-US"]["opening"]))
    assert "股價" in joined or "均線" in joined or "RSI" in joined or "技術" in joined


@pytest.mark.parametrize("text", [GOOD_LITE, GOOD_CHANGE, GOOD_NO_NEWS])
def test_a_lead_with_new_evidence_a_number_and_a_stance_passes(text):
    assert lead.check_lead(text) == []
    assert len(lead.opening(text)) <= 200


def test_opening_is_exactly_the_first_200_characters_of_the_note():
    text = "【結論】買\n" + "字" * 400
    assert lead.opening(text) == text[:200] and len(lead.opening(text)) == 200


def test_the_rating_line_must_come_first_and_be_one_of_the_three():
    assert any("結論" in p for p in lead.check_lead("重點：營收年增 20%，維持買進。"))
    assert any("結論" in p for p in lead.check_lead("【結論】看多\n重點：營收年增 20%，維持。"))
    assert lead.check_lead(GOOD_LITE.replace("【結論】買（維持）", "【結論】買")) == []   # the stance may sit in the insight line


def test_a_lead_without_a_decision_word_or_without_evidence_or_without_a_number_fails():
    no_stance = "【結論】買\n重點：Lumentum 營收 12.63 億美元，年增 136.5%。"
    assert any("維持" in p or "改變" in p for p in lead.check_lead(no_stance))
    no_evidence = "【結論】買（維持）\n重點：公司很好，市場看好未來發展，因此維持買進，持續觀察。"
    assert any("證據" in p for p in lead.check_lead(no_evidence))
    no_number = "【結論】買（維持）\n重點：新報告認為交貨順利，財報也不錯，因此維持買進，繼續追蹤。"
    assert any("數字" in p for p in lead.check_lead(no_number))


def test_price_and_technical_words_in_the_first_200_characters_fail_but_evidence_words_that_look_similar_do_not():
    price_first = "【結論】買（維持）\n重點：股價單日 -11.5% 跌破 MA20，RSI 33.8；營收年增 136.5%，因此維持買進。"
    problems = lead.check_lead(price_first)
    assert any("股價" in p or "MA20" in p or "RSI" in p for p in problems)
    legit = "【結論】買（維持）\n重點：報告指 DRAM 合約價上漲 18%、營收創新高 2,450 億元，交貨順風，因此維持買進。"
    assert lead.check_lead(legit) == []          # 上漲 / 創新高 of a product price or revenue is evidence, not stock-price action


def test_price_words_after_the_first_200_characters_are_fine():
    text = GOOD_LITE + "\n\n" + "時機：10/22 單日 -11.5%，低於 MA20，RSI 33.8，等回測。" * 3
    assert lead.check_lead(text) == []


def test_macro_commentary_needs_evidence_and_a_number_but_no_rating_line():
    macro = "新公布的 9 月 CPI 年增 3.7%（前值 3.4%）、PPI 6.4%，通膨壓力升高，對 AI 資本支出評價偏逆風，維持中立判讀。"
    assert lead.check_lead(macro, kind="macro") == []
    assert lead.check_lead("市場近期波動加大，投資人需審慎看待後續發展。", kind="macro")


def test_cli_reads_the_save_body_prints_ok_or_the_problems_and_sets_the_exit_code(tmp_path):
    script = str(ROOT / "maya_sawa" / "public_scripts" / "check_analysis_lead.py")
    body = tmp_path / "body.json"
    body.write_text(json.dumps({"model": "m", "content": GOOD_LITE, "expectedRevision": 3}, ensure_ascii=False), encoding="utf-8")
    ok = subprocess.run([sys.executable, script, str(body)], capture_output=True, text=True, encoding="utf-8")
    assert ok.returncode == 0 and ok.stdout.strip().startswith("OK")
    body.write_text(json.dumps({"content": REAL["LITE-US"]["opening"]}, ensure_ascii=False), encoding="utf-8")
    bad = subprocess.run([sys.executable, script, str(body)], capture_output=True, text=True, encoding="utf-8")
    assert bad.returncode == 1 and "NG" in bad.stdout
    missing = subprocess.run([sys.executable, script, str(tmp_path / "none.json")], capture_output=True, text=True, encoding="utf-8")
    assert missing.returncode == 2
