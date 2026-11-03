# 市場快報語音（準備中）

市場語音唯讀 API 現已接入服務，Learn 頁會列出已完成的語音並播放資料庫中的完整音檔。版本佇列、Azure Speech REST provider、全文分段/MP3 合併及月字數預留閘門已實作並測試；排程只會在兩個明確啟用旗標、key、支援區域和正數月字數上限都存在時啟動，預設關閉。實際 Azure API 尚未呼叫，正式部署狀態尚未核實。

## 預定資料流程

```mermaid
flowchart LR
    A[公開分析新版本或已審核每日精讀] --> Q[(持久化版本工作佇列)]
    Q --> W[注入式全文合成 worker]
    W --> T[依原文段落切分至 2000 字元]
    T --> S[語音服務]
    S --> V[驗證與合併完整音訊]
    V --> D[(資料庫保存版本及完整音檔)]
    D --> API[公開清單與音訊 API]
    API --> L[Learn 市場快報播放器]
    M[已審核每日精讀 API] --> H[首頁每日精讀]
```

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> processing
    processing --> ready: 所有片段完成並驗證
    processing --> retry: 暫時失敗
    retry --> processing
    processing --> failed: 不可重試或超過限制
    processing --> blocked: 月字數上限會被超過
```

## 接線與成本控制實作補充

1. 確認用戶提供的總經評論是完整版本，而不是只轉換新增段落。新分析版及已審核每日精讀會依版本入持久化佇列；worker 對完整來源文字合成，完成後寫入完整音檔。版本 id 去重，內容雜湊不同則拒絕覆寫。
2. 先以測試固定分段不遺漏文字、百分比與小數不能在小數點切開，再實作分段。
3. Azure Speech Studio（2026-11-03 讀取）顯示資源 `ty-multiverse-speech-f0` 位於 `eastus`、F0，語音目錄已選中「Xiaoyu Dragon HD Flash Latest」，voice 為 `zh-CN-Xiaoyu:DragonHDFlashLatestNeural`。尚未呼叫 API，所以端到端合成、可用免費餘額、實際計費及超額費率仍未驗證。Azure 網路規則已由使用者在先前回合確認只允許 OKE SSH 節點出口 IP `140.245.44.81`。Microsoft 公開價目列出 F0 Neural 每月 50 萬字元免費，但沒有清楚列出 HD Flash 是否適用該 F0 額度；PAYG 價目將 Neural/Neural HD Flash 按字元計價，實際金額依帳戶、地區和幣別顯示。不可把通用 Neural 免費額度視為本資源的可用餘額或 HD Flash entitlement。
4. 官方 TTS REST 支援依資源區域選 regional endpoint；此資源使用 `https://eastus.tts.speech.microsoft.com/cognitiveservices/v1`、`Ocp-Apim-Subscription-Key`、SSML 和 MP3 output。公開 Selected Networks/IP allowlist 模式使用此 endpoint，不需 custom domain；Microsoft 的 custom domain 指引是 Private Endpoint/Private Link 情境，若後續改用私有端點必須改 endpoint/DNS。此為依目前公網 IP allowlist 架構的選擇，端到端仍待 dry-run 驗證。
5. key 只由 `AZURE_SPEECH_KEY` 注入，region 由環境設定。provider 分段完整來源文字，使用 FFmpeg concat demuxer stream-copy 合併 MP3，而非直接串接 MP3 bytes；每個請求間隔保守 3.1 秒，避免超過 F0 每分鐘 20 個 synthesis request 的公開限制。單元測試用 FFmpeg 生成兩段獨立 MP3，合併後用 FFmpeg 完整解碼並用 ffprobe 核對時長。
5. `MARKET_AUDIO_AUTOGEN_ENABLED` 與 `MARKET_AUDIO_AZURE_ENABLED` 預設皆關閉；只有兩者、key、支援區域和 `MARKET_AUDIO_MONTHLY_CHARACTER_LIMIT` 正數都存在時，服務才嘗試啟動 worker。PostgreSQL advisory lock 限制整個叢集同一時間只有一個 worker，並以 3.1 秒間隔限制 F0 request 頻率。月字數在每次外部請求前以資料庫原子預留（重試也計入），超過上限時不呼叫 provider，工作標記為 `blocked`。這是本地字元 ceiling，**不是 $1 美元硬上限**；沒有經核實的實際 rate 前不得把它換算或宣稱為美元保證。Azure 預算警報同樣不保證停止消費。

測試：後端 `poetry run python -m pytest tests/market/test_market_audio_azure.py tests/market/test_market_audio_merge.py tests/market/test_market_audio_worker.py tests/market/test_market_audio_api.py tests/market/test_market_audio_db.py tests/market/test_audio_text.py tests/market/test_daily_maya_api.py tests/market/test_daily_maya_db.py tests/market/test_daily_maya_sources.py tests/market/test_daily_maya_editorial.py -q`（34 passed）；前端以 Codex Node 24 執行 `node_modules/vitest/vitest.mjs run tests/market/dailyMayaRoutes.test.ts tests/seo/homeSeo.test.ts`（10 passed）。缺口：未呼叫真實 Azure API、無經核實的 $1 美元硬上限、正式部署未驗證、實際帳戶免費餘額與帳單仍未確認。

## 開發方法

1. 先固定分段不切壞數值、音訊必須有完整原文等測試，再做資料庫與唯讀 API；後端啟動時用既有市場資料庫 engine 初始化音訊表並註冊路由。
2. 前端只經同源 Astro server routes 讀公開清單及音訊串流，避免把後端內網位址暴露給瀏覽器；播放器使用 `preload=none`，不會自動下載或觸發 TTS 費用。
3. Azure key 僅能由 `ty-multiverse-speech-f0` 資源安全注入 `AZURE_SPEECH_KEY`，不得寫入原始碼或日誌；Azure 網路 allowlist 只保留 `140.245.44.81`。先確認免費用量與 SKU 價格，再用可控的小型全文 dry-run 記錄 request/response、計費字元和音訊完整度。
4. 新分析版/已審核每日精讀會排入持久化工作，worker 有重試與失敗上限，REST provider 可注入；自動 worker 預設關閉，且只允許取得 PostgreSQL leader lock 的 pod 啟動。只有驗證真實 endpoint、免費額度、rate 和能接受的月字數後，才設定兩個啟用旗標及字數上限。若需 $1 美元硬上限，先以可核對的實際費率做原子美元帳本；目前不得宣稱字數 cap 等於美元 cap。

官方核對（2026-11-03）：[HD Flash voice 清單與 API 適用性](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/high-definition-voices)、[Speech TTS REST endpoint 與 request 格式](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech)、[Azure Speech 價目](https://azure.microsoft.com/en-us/pricing/details/speech/)、[Private Endpoint 的 custom-domain 規則](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-private-link)。官方價目不能驗證個別 Azure resource 剩餘免費額度或實際帳單；Speech Studio 已顯示該 voice 選中，但尚未生成音訊。
