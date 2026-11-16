"""Plain-language check for the daily reading (docs/DAILY_MAYA_BRIEF.md, 2026-11-16).

Listeners hear terms such as "金融壓力指數低於零" or "壓力在折現率" with no idea what they mean. The first time one of these
terms appears, the script must say in a sentence what it measures and which way is good or bad. This is a coarse automatic check
(a marker word has to follow the first mention); the reviewer still reads the explanation for sense.
"""
import re

WINDOW = 110  # characters after the first mention in which an explanation has to start

# term -> (words that signal an explanation follows, an example sentence shown to the writer)
GLOSSARY: dict[str, tuple[tuple[str, ...], str]] = {
    "金融壓力指數": (("代表", "平均", "意思", "表示", "是指"),
                 "金融壓力指數是衡量金融市場緊張程度的指標，零代表歷史平均，低於零表示市場比平常更平靜、壓力較小"),
    "折現率": (("換算", "現值", "今天的價值", "未來的獲利", "未來獲利", "未來的現金", "折成"),
              "折現率是把公司未來賺的錢換算成今天價值時用的利率，利率越高，股票今天的合理價格越低；要寫清楚指的是哪個利率，例如十年期實質利率"),
    "實質利率": (("扣掉", "扣除", "通膨", "物價"),
              "實質利率是名目利率扣掉通膨預期後真正的資金成本"),
    "淨流動性": (("聯準會", "扣掉", "扣除", "市場上", "可動用", "可用"),
              "淨流動性是市場上實際可動用的美元資金，大約是聯準會資產負債表扣掉財政部帳戶與隔夜逆回購"),
    "高收益債利差": (("風險較高", "垃圾債", "信用風險", "比公債", "多付", "額外"),
                "高收益債利差是風險較高的公司債殖利率比公債多出的部分，越大代表市場越擔心違約"),
}


def missing_explanations(text: str) -> list[tuple[str, str]]:
    """[(term, example)] for every glossary term whose first mention is not followed by an explanation within WINDOW characters."""
    missing = []
    for term, (markers, example) in GLOSSARY.items():
        at = text.find(term)
        if at < 0:
            continue
        after = text[at + len(term): at + len(term) + WINDOW]
        before = text[max(0, at - 40): at]
        if not any(marker in after or marker in before for marker in markers):
            missing.append((term, example))
    return missing


def explain_message(missing: list[tuple[str, str]]) -> str:
    lines = [f"「{term}」第一次出現時要用一句白話說明它的意思與好壞方向，例如：{example}" for term, example in missing]
    return "聽眾聽不懂專有名詞：" + "；".join(lines) + "。請改寫後重新提交（說明要用中文逗號與句號，不要括號）。"
