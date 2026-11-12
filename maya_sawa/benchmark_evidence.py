"""Bounded semiconductor evidence excerpts with stable original PDF page numbers."""

import re

UPLOADER = "tw-benchmark-annual"
PROFILE = 'benchmark-evidence-v2'

FOCUS = re.compile(
    r"產業(?:趨勢|展望|變化)|市場(?:展望|需求|趨勢|規模)|需求(?:成長|增加|減少|放緩|帶動|回升|下滑)|"
    r"製程|奈米|電晶體|異質整合|封裝|HBM|CoWoS|晶圓|薄膜|蝕刻|濺鍍|植入|研磨|"
    r"潔淨|無塵室|良率|可靠度|驗證|特氣|靶材|產能|量產|試產|送樣|擴建|第二來源|供應鏈|"
    r"客戶導入|設備交期|技術路線|研發計畫|資金.*(?:設備|擴產)|"
    # English (SEC annual reports, Advantest) and Korean (DART) annual reports
    r"capital expenditure|data ?cent(?:er|re)|AI infrastructure|accelerat|GPU|TPU|custom silicon|"
    r"demand|capacity|ramp|yield|roadmap|process node|advanced packaging|supply (?:chain|constraint)|"
    r"tester|test time|SoC test|memory test|export restrictions?|order cancell|inventory correction|"
    r"出口限制|訂單取消|庫存調整|需求疲弱|產能過剩|"
    r"수요|생산능력|설비투자|양산|공정|고대역폭|데이터센터",
    re.I,
)
FINANCIAL = re.compile(
    r"營業收入|營收|淨利|淨損|毛利|每股盈餘|資產負債|現金流量|"
    r"股利|股東名冊|董事酬金|銷售金額|銷貨金額|獲利|新[臺台]幣|(?:仟|千|百萬|億)元|\bEPS\b|"
    r"net income|earnings per share|dividend|stockholders.? equity|share repurchase|executive compensation|"
    r"당기순이익|배당",
    re.I,
)
SPECIFIC = re.compile(
    r"\d\s*(?:奈米|nm|μm|吋)|奈米片|電晶體|異質整合|HBM|CoWoS|"
    r"量產|試產|送樣|第二來源|供應風險|單一供應|驗證|(?:產業|市場)(?:趨勢|展望|需求)|"
    r"capital expenditures?|data ?cent(?:er|re)s?|HBM\d?|\d\s*nm|ramp|capacity constraint",
    re.I,
)

OPERATING = re.compile(
    r'需求|擴產|擴充|產能|量產|良率|瓶頸|限制|延遲|供應風險|'
    r'demand|capacity|ramp|yield|constraint|restriction|delay|shortage|수요|생산능력|양산', re.I)


def select_pages(pages: list[str], max_chars: int = 16_000) -> list[str]:
    """Keep technical and forward-looking statements, with bounded space per page."""
    selected = [""] * len(pages)
    seen = set()
    candidates = []
    for index, page in enumerate(pages):
        # Chinese sentence marks, English/Korean sentence ends, or blank lines.
        for raw in re.split(r"(?<=[。！？；])|(?<=[.!?])\s+(?=[A-Z가-힣])|\n{2,}", page):
            sentence = re.sub(r"\s+", " ", raw).strip()
            # Keep complete statements, not TOC headings or oversized tables.
            if not 12 <= len(sentence) <= 600:
                continue
            if sentence in seen or not FOCUS.search(sentence) or (FINANCIAL.search(sentence) and not OPERATING.search(sentence)):
                continue
            seen.add(sentence)
            candidates.append((index, sentence))
    ranked = sorted(enumerate(candidates), key=lambda item: -len(SPECIFIC.findall(item[1][1])))
    remaining = max_chars
    used = {}
    accepted = []
    for order, (index, sentence) in ranked:
        cost = len(sentence) + 1
        if cost <= remaining and used.get(index, 0) + cost <= 1200:
            remaining -= cost
            used[index] = used.get(index, 0) + cost
            accepted.append((order, index, sentence))
    for _, index, sentence in sorted(accepted):
        selected[index] = "\n".join(filter(None, (selected[index], sentence)))
    return selected


def validate_evidence(claims: list[dict], pages: list[str]) -> None:
    for claim in claims:
        page, evidence = claim.get("page"), claim.get("evidence")
        if (type(page) is not int or not 1 <= page <= len(pages)
                or not isinstance(evidence, str) or not evidence.strip()
                or evidence.strip() not in pages[page - 1]):
            raise ValueError("Evidence must be a verbatim excerpt from its selected PDF page")
