"""2026-11-16: the daily reading has to explain indicators in plain words the first time they appear."""
from maya_sawa.services import daily_maya_glossary as g

SPOKEN_AS_PUBLISHED_ON_1116 = ("量的部分，美國淨流動性連續兩週回升到五點八四兆美元，金融壓力指數低於零，高收益債利差百分之三點二，信用沒有緊縮。"
                               "價的部分，十年期實質利率升到百分之二點八六，傳導邏輯是，資金與信用不是壓力所在，壓力來自折現率，高本益比的股票評價最先被壓縮。")


def terms(text):
    return [t for t, _ in g.missing_explanations(text)]


def test_the_reading_that_confused_the_listener_is_flagged_term_by_term():
    assert set(terms(SPOKEN_AS_PUBLISHED_ON_1116)) == {"金融壓力指數", "折現率", "實質利率", "淨流動性", "高收益債利差"}


def test_a_plain_explanation_right_after_the_first_mention_passes():
    text = ("金融壓力指數是衡量金融市場緊張程度的指標，零代表歷史平均，目前低於零，表示市場比平常平靜。"
            "壓力來自折現率，折現率就是把公司未來賺的錢換算成今天價值時用的利率，這裡指十年期實質利率，也就是名目利率扣掉通膨預期後的資金成本。")
    assert terms(text) == []


def test_only_the_first_mention_needs_the_explanation_and_unlisted_terms_are_ignored():
    text = "折現率就是把未來獲利換算成現值的利率。之後再提折現率就不必重複說明。毛利率是另一回事。"
    assert terms(text) == []
    assert terms("今天毛利率上升，營收年增。") == []


def test_an_explanation_far_from_the_term_does_not_count():
    far = "金融壓力指數低於零。" + "市場很安靜，" * 30 + "代表平均。"
    assert terms(far) == ["金融壓力指數"]


def test_the_message_tells_the_writer_what_to_add():
    message = g.explain_message(g.missing_explanations("金融壓力指數低於零。"))
    assert "金融壓力指數" in message and "零代表歷史平均" in message and "重新提交" in message
