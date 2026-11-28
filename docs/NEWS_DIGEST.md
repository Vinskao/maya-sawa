# 盤前公告與新聞摘要（每日兩次）

`maya_sawa/services/news_digest.py`：持股、自訂標的、AI 觀察清單的公司公告與新聞，每天兩次整理成一則 Telegram（📢）並存到小鈴鐺。
總經公布（央行決策、CPI、非農）走即時通道，見 [MACRO_RELEASES.md](MACRO_RELEASES.md)。

| 場次 | 時間 | 範圍 | 來源 |
|---|---|---|---|
| 台股盤前 | 平日 08:00 台北 | 4 碼台股 | 證交所／櫃買中心「每日重大訊息」OpenAPI、鉅亨網個股新聞 |
| 美股盤前 | 平日 08:00 紐約（台北冬令 21:00／夏令 20:00）| 美股與其他海外標的（例如 6857-JP，用公司名稱搜新聞）| SEC EDGAR 8-K（data.sec.gov）、Google News RSS |

兩場各看過去 24 小時，市場不重疊，所以不會重複。

```mermaid
flowchart LR
  T[每分鐘檢查 due_session] -->|08:00 台北／08:00 紐約| C[collect：targets 持股＋自訂＋觀察]
  C --> TW[TWSE/TPEx 重大訊息<br/>鉅亨網 stock 標記]
  C --> US[SEC 8-K 附 item 意義<br/>Google News 去除持股異動垃圾]
  TW & US --> P[每檔最多 8 則，公告優先、標題去重]
  P --> G{Gemini Flash<br/>GEMINI_API_KEY}
  G -->|成功| S[每檔一行：利多／利空／中性＋重點]
  G -->|失敗或無金鑰| F[改列標題]
  S & F --> D[deliver：AutomationStore 每場每天一次] --> TG[Telegram 📢 + 小鈴鐺]
```

## 規則與開發方法
- Gemini 只根據給它的公告與新聞寫摘要，不推測股價、不給買賣建議（`build_prompt`）。模型可用 `NEWS_DIGEST_GEMINI_MODEL` 改，預設 `gemini-2.5-flash`。
- SEC 拒絕瀏覽器樣式的 User-Agent，用 `SEC_USER_AGENT`（預設 `maya-sawa research bot`，不帶個人 email）。每次請求間隔 0.2 秒。
- 沒有新資料也會送一則「沒有新公告或新聞」，讓你知道排程有跑。
- 同一個 pod 每場只收集一次（不會在 15 分鐘時段內重複叫 Gemini）；多 pod 由 `news-digest:{tw|us}` + 當地日期去重。
- 解析器都是純函式並有測試：`tests/market/test_news_digest.py`（真實欄位名，例如證交所的「主旨 」有尾端空白、民國日期）。
- AI 排程的深度解讀不變；之後可以改讓排程讀這份摘要，而不是自己搜尋。

## 大盤回顧（Gemini＋Google 搜尋）
持股與觀察清單沒消息時摘要不能是空的，所以每場最前面先放「📈 大盤回顧」：`market_brief_prompt` 交給 Gemini 並開 `google_search` 工具（`gemini_summary(..., search=True)`），
美股場寫最近一個交易日三大指數與費半收盤（點位、漲跌、週線、假期註明）、重點個股與原因、盤前期指、接下來的觀察重點；台股場寫加權指數與三大法人、昨晚美股與台積電 ADR、重點個股、本週觀察重點。
規則：只寫搜尋到的數字、不給建議、15 行內。搜尋失敗時寫「大盤回顧暫時無法產生」，持股段落照常。標題沒有持股消息時不再顯示「（0 則）」。

## 經濟數據預告
每則摘要最上面先列「📅 未來 24 小時經濟數據（台北時間）」，來源是 `maya_sawa_macro_events`（FRED 公布日期＋Finance Calendar 預期值，`market_macro.py` 寫入）。
台北 08:00 那則就會預告當晚 20:30／21:30 的美國數據；同一筆數據兩個來源都有時只列一次，優先用有預期值的那筆（`upcoming_events`）。
限制：行事曆只涵蓋 `FRED_RELEASES` 與 Finance Calendar 篩出的項目；Finance Calendar 失效（401）或 FRED 額度用完時可能漏列，例如 GDP、PCE。
