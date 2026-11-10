import pytest

from maya_sawa.benchmark_evidence import select_pages, validate_evidence


def test_selects_forward_industry_and_process_evidence_with_original_page_numbers():
    pages = [
        "營業收入較去年增加，稅後淨利為新台幣三億元。",
        "市場展望：AI 加速器需求帶動先進封裝產能擴建。\n二奈米製程採用奈米片電晶體，預計下半年量產。\n每股盈餘為 10 元。",
        "股東名冊\n董事酬金",
        "風險事項：高純度特氣仰賴單一供應來源，將進行第二來源驗證。",
    ]
    result = select_pages(pages)
    assert len(result) == 4
    assert result[0] == result[2] == ""
    assert "先進封裝產能擴建" in result[1]
    assert "奈米片電晶體" in result[1]
    assert "每股盈餘" not in result[1]
    assert "第二來源驗證" in result[3]


def test_evidence_must_match_selected_text_on_cited_page():
    pages = ["", "預計下半年量產。"]
    validate_evidence([{"page": 2, "evidence": "預計下半年量產"}], pages)
    with pytest.raises(ValueError):
        validate_evidence([{"page": 1, "evidence": "預計下半年量產"}], pages)
    with pytest.raises(ValueError):
        validate_evidence([{"page": 2, "evidence": "已經量產"}], pages)
