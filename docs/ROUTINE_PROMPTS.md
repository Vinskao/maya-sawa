# 排程提示詞放在 repo（routines/*.md）

2026-11-02 起，Default 環境的八個排程把完整指示放在 `maya-sawa/routines/<名稱>.md`，排程本身的提示詞只是一段短指標：
「讀 routines/<名稱>.md，完整照做」。排程清單與時間見 [MARKET_AGENT_KEY.md](MARKET_AGENT_KEY.md)。

## 為什麼

網域改成 `tymultiverse.cc` 後，雲端環境把已棄用的 `peoplesystem.tatdvsonorth.com` 擋掉，十個排程的提示詞卻都寫死舊網址。
更新一個排程要把整份提示詞（6–7 KB）重送一次、回應又原樣回傳兩次，換網址要做十次大的編輯，也容易打錯字。
指示放進 repo 以後，換網址或改規則是一個可審查、可測試的 commit。

```mermaid
flowchart TD
    Cron[claude.ai 排程觸發] --> Stub[短提示詞：讀 routines/名稱.md 照做]
    Stub --> Clone[雲端環境 clone maya-sawa main]
    Clone --> File[routines/名稱.md：網址、規則、儲存、通知、用量回報]
    File --> Proxy[送往 tymultiverse.cc/maya-sawa/ 的請求<br/>由代理加 X-Market-Agent-Key]
    Proxy --> API[maya-sawa market API]
    Stub -->|讀不到檔案| Stop[停止，POST /market/notify attention，不憑記憶執行]
```

## 目前遷移的排程

| 指示檔 | 排程 |
|---|---|
| `market-us-macro-sonnet.md` / `market-us-macro-opus.md` | 市場 AI 分析｜美股與總經（Sonnet／Opus 輪班），週二至週六 07:30 |
| `market-taiwan-sonnet.md` / `market-taiwan-opus.md` | 市場 AI 分析｜台股收盤後（Sonnet／Opus 輪班），週一至週五 21:15 |
| `weekly-maintenance-{backend,maya-sawa,frontend}.md` | 每週維護，各自週三／週六／週日 01:00 |
| `report-claim-extraction.md` | 市場報告｜萃取主張，每天 20:30 |
| `GPT_REPORT_CLAIM_EXTRACTION.md` | GPT 萃取並提交隔離提案；Claude 只做審核與資料庫寫入。API 部署後才切換雲端排程 |

**未遷移（原因）：**
- 日記敘事：打的是 `/tymb/diary/agent`（另一個後端），而 agent key 的 network secret 路徑前綴只限 `/maya-sawa/`；要先決定它的 key 怎麼給。
- 每週技術探討文：跑在另一個環境（TY Blog Weekly），網路設定獨立。
- 審核 GPT 每週提案：2026-11-02 建立時就直接寫新網址，仍是完整提示詞。

## 開發方法

1. 先量問題：列出每個排程提示詞出現舊網域的次數與段落（兩個美股／台股組各 13–17 處，其餘 1–3 處）。
2. 先寫測試（`tests/automation/test_routine_prompts.py`）：每個遷移的排程有指示檔；指示檔不得出現舊網域（唯一例外是一句說它已棄用）；
   API 呼叫都指向 `tymultiverse.cc/maya-sawa/`；檔案不含金鑰樣式、也不教排程自己設驗證標頭；寫入類排程保留「代理加 key」說明與用量回報步驟。
   確認紅（目錄不存在）後再產生檔案。
3. 用腳本從排程當下的提示詞產生檔案（網址、「網址」段落、「network secret 送往哪個主機」一句由程式替換，不靠手打），再跑測試。
4. 推上 `main` 之後才把排程提示詞換成指標（排程是在執行時 clone `main`，順序反了會讀不到檔案）。
5. 逐個手動觸發一次，讀執行紀錄確認它讀到了檔案、API 通、通知與用量回報成功。
6. 之後改規則或網址：改 `routines/*.md`、跑測試、推 `main`，不需要再動排程。

**限制與風險：** 排程若讀不到檔案就不會做事（指標要求它停止並用 attention 通知）。指示檔在 `main`，所以改它等於改排程行為，推送前要有測試與審查。
測試：`poetry run python -m pytest tests/automation/test_routine_prompts.py -q`。

## 2026-11-11 海外標的缺研究圖：流程缺口與修正

6834-JP（精工技研）有 AI 分析卻沒有研究圖，研究分頁是空的。逐檔比對 dashboard 與 `analysis/{code}?productType=research` 後，缺口有四個：

| 缺口 | 原本 | 現在 |
|---|---|---|
| 沒有任何規則要求「沒有研究圖就建立」 | 排程只在「新證據改變技術節點」時**更新**既有研究圖；第一版都是人工請模型做的（6857-JP 是 2026-10-25 人工覆核寫的） | 台股例程第 7.1 節、美股例程第 3.3 節：讀到 `analysis: null` 就依 `research-guide.md` 建立第一版，再寫 AI 分析；單輪最多新建三檔 |
| 台股例程開頭寫「日本、韓國標的不在本例程範圍」 | 後面的段落卻要它讀日韓資料，實際上有寫日韓 AI 分析，但研究圖沒人負責 | 明確把 dashboard 列出的日韓標的納入，紀錄代碼用 `6857-JP`、`000660-KR` |
| 美股例程寫研究圖「排程不能寫」 | 新的美國標的永遠不會有研究圖 | 已有的不改寫，沒有的建立第一版 |
| 「新增標的」觸發訊息只要求第一份 AI 分析 | 新加入的標的沒有研究圖 | 訊息同時要求建立研究圖（`market_automation.analyze_added`） |

```mermaid
flowchart TD
  D[GET dashboard：列出全部標的] --> C{紀錄代碼}
  C -->|台股 2454| T[台股收盤後例程 21:15]
  C -->|日韓 6834-JP、000660-KR| T
  C -->|美國 META-US| U[美股與總經例程 07:30]
  T --> R{GET productType=research<br/>analysis 是 null？}
  U --> R
  R -->|是| N[依 research-guide.md 建立第一版<br/>PUT expectedRevision 0，單輪最多三檔]
  R -->|否| K[有新證據才更新]
  N --> A[寫或更新 AI 分析]
  K --> A
```

仍未處理：報告主張的事件觸發（`fire_analysis_event`）只接受四位數台股代碼，海外代碼的新主張要等每日例程才會反映。

### 開發方法

1. 先量：用 dashboard 清單逐檔打 `analysis/{code}` 的 stock 與 research，列出哪一檔缺哪一種（6834-JP：stock 有、research 無）。
2. 讀四份例程指示與 `market_automation.py`，找出誰負責建立研究圖：沒有人。
3. 先寫測試：`tests/automation/test_routine_prompts.py`（四份市場例程都要有「沒有研究圖」的建立規則並指向 `research-guide.md`；台股例程不得再排除日韓、要寫出 `6857-JP` 代碼格式；美股例程不得再寫「排程不能寫」）與 `tests/automation/test_added_instrument_prompt.py`（新增標的訊息要求研究圖）。確認紅再改。
4. 改 `routines/market-*.md` 與 `market_automation.py`，推 `main`；排程下一次執行就會讀到。
5. 驗證：下一輪執行後 `GET /maya-sawa/market/dashboard/analysis/6834-JP?productType=research` 應有 revision 1，研究分頁出現供應鏈與技術圖。
