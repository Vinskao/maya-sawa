"""Response schemas and ready-to-run query examples for the public market-data routes (shown on the site's API page).

Shapes follow what the routes return today (checked against production responses); values that depend on the source are
described loosely on purpose. Examples use codes that have data: 2330 (Taiwan), LITE / 6857 (held at IBKR), BTC / ETH (Binance).
"""

_str, _num, _bool = {"type": "string"}, {"type": "number"}, {"type": "boolean"}


def _obj(properties: dict, description: str = "") -> dict:
    schema = {"type": "object", "properties": properties}
    return {**schema, "description": description} if description else schema


def _arr(items: dict) -> dict:
    return {"type": "array", "items": items}


_DATASET = _obj({"code": _str, "market": _str, "conid": {"type": "integer"}, "kind": _str, "period": _str, "status": _str,
                 "fetchedAt": _str, "payload": {"type": "object"}}, "一種資料集（quote／history_raw／profile／financials）的最新一筆")
_TECHNICAL = _obj({"ma5": _num, "ma10": _num, "ma20": _num, "ma60": _num, "asOf": _str, "sessions": {"type": "integer"},
                   "rsi14Wilder": _num, "rangeHigh": _num, "rangeLow": _num, "change5dPercent": _num, "change20dPercent": _num},
                  "由日線算出的均線、RSI 與區間；資料不足時為 null")

HISTORY = _obj({
    "code": _str, "view": {"type": "string", "enum": ["daily", "ownership"]}, "start": _str, "end": _str,
    "collecting": {**_bool, "description": "true 表示這檔還沒有資料、已排入補抓，稍後再查"},
    "points": _arr(_obj({"date": _str, "code": _str, "name": _str,
                         "sources": {"type": "object", "description": "鍵為資料來源（如 twse:daily-price），值為該來源當日的欄位"}})),
    "coverage": _arr(_obj({"date": _str, "source": _str, "status": _str, "detail": _str})),
}, "個股日線與籌碼，每個交易日一個 point")

FUNDAMENTALS = _obj({
    "code": _str,
    "monthlyRevenue": _arr(_obj({"period": _str, "publishedAt": _str, "name": _str, "industry": _str, "unit": _str, "revenue": _num,
                                 "previousRevenue": _num, "yearAgoRevenue": _num, "momPercent": _num, "yoyPercent": _num,
                                 "ytdRevenue": _num, "source": _str})),
    "incomeStatements": _arr({"type": "object"}), "balanceSheets": _arr({"type": "object"}),
    "metrics": _obj({"monthly": _arr({"type": "object"}), "quarterly": _arr({"type": "object"}),
                     "balance": _arr({"type": "object"}), "cashFlow": _arr({"type": "object"})}),
    "historyPending": _bool, "source": _str, "checkedAt": _str, "staleSources": _arr(_str), "errors": _arr(_str),
}, "月營收與季度財報（官方資料）")

OVERSEAS = _obj({
    "code": _str, "market": {"type": "string", "enum": ["US", "JP", "KR", "HK", "CRYPTO"]}, "name": _str,
    "quoteAsset": {**_str, "description": "僅 CRYPTO：計價幣別（USDT）"}, "source": _str, "persisted": _bool,
    "datasets": _obj({"quote": _DATASET, "history_raw": _DATASET, "profile": _DATASET, "financials": _DATASET}),
    "coverage": {"type": "object", "description": "各資料集最近一次抓取的狀態；失敗時 detail 說明原因"},
    "daily": _arr(_obj({"date": _str, "timestamp": _str, "open": _num, "high": _num, "low": _num, "close": _num,
                        "volume": _num, "rawVolume": {**_num, "description": "僅 IBKR"}, "volumeFactor": {**_num, "description": "僅 IBKR"},
                        "quoteVolume": {**_num, "description": "僅 Binance：以 USDT 計的成交額"}, "trades": {**_num, "description": "僅 Binance"}})),
    "technical": _TECHNICAL, "gaps": _arr(_str),
}, "海外標的或加密貨幣：資料庫中保存的報價、日線與技術摘要（不連券商、不含帳戶資料）")

ANALYSIS = _obj({
    "code": _str, "productType": {"type": "string", "enum": ["stock", "futures", "crypto", "macro", "macro-node", "research"]},
    "analysis": {"type": ["object", "null"], "description": "目前版本（model、content、revision、updatedAt）；尚未撰寫時為 null"},
    "history": _arr({"type": "object"}), "historyLimit": {"type": "integer"},
    "writeMethod": _str, "writeAccess": _str, "instructions": _str,
}, "AI 分析的目前版本與最近歷史版本")


def example(venue: str, title: str, path: str) -> dict:
    return {"venue": venue, "title": title, "path": path}


HISTORY_EXAMPLES = [example("台股", "台積電 2330，2026 年 10 月日線與籌碼", "/market/dashboard/history/2330?start=2026-10-01&end=2026-10-31"),
                    example("台股", "台積電 2330，持股結構（集保／外資）", "/market/dashboard/history/2330?view=ownership")]
FUNDAMENTALS_EXAMPLES = [example("台股", "台積電 2330 月營收與財報", "/market/dashboard/fundamentals/2330")]
OVERSEAS_EXAMPLES = [example("IBKR 美股", "Lumentum（LITE），market=US", "/market/dashboard/overseas/LITE?market=US"),
                     example("IBKR 日股", "Advantest（6857），market=JP", "/market/dashboard/overseas/6857?market=JP"),
                     example("Binance", "比特幣現貨（BTC/USDT），market=CRYPTO", "/market/dashboard/overseas/BTC?market=CRYPTO"),
                     example("Binance", "以太幣現貨（ETH/USDT），market=CRYPTO", "/market/dashboard/overseas/ETH?market=CRYPTO")]
ANALYSIS_EXAMPLES = [example("台股", "台積電 2330 的 AI 分析", "/market/dashboard/analysis/2330?productType=stock"),
                     example("IBKR 美股", "Lumentum（LITE）的 AI 分析", "/market/dashboard/analysis/LITE?productType=stock"),
                     example("Binance", "比特幣（BTC）的 AI 分析", "/market/dashboard/analysis/BTC?productType=crypto")]
