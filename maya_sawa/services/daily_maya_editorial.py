"""Conservative editorial flags; a reviewer must still check evidence and causality."""
import re

_PRICE = re.compile(r'股價|股价|股市價格|收盤價|收盘价|現價|现价')
_TECHNICAL = re.compile(r'均線|均线|\d+\s*[日天]\s*[線线]')
_EVIDENCE = re.compile(r'財報|财报|營收|营收|獲利|获利|法說|法说|指引|報告|报告|訂單|订单|CPI|PCE|PMI|通膨|利率|出口|政策|公告', re.I)
_CAUSE = re.compile(r'因為|由于|由於|因|受|受到|源於|源于')


def review_price_language(content: str) -> list[str]:
    """Flag technical quote recitals and price-first causal framing.

    This is a lexical guard, not proof that a claimed causal link is true.
    """
    issues = []
    for sentence in re.split(r'[。！？\n]+', content or ''):
        if _TECHNICAL.search(sentence):
            issues.append('避免均線及行情數字堆砌')
        match = _PRICE.search(sentence)
        if not match:
            continue
        before = sentence[:match.start()]
        if not (_CAUSE.search(before) and _EVIDENCE.search(before)):
            issues.append('股價只能作為有證據支持的結果')
    return issues
