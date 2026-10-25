# 大立光 CPO 研究更新

依使用者提供的永豐金豐雲學堂文章，重審 `market_research/3008.json`，覆核日 2026-10-26。

已從瀏覽器讀到文章五節正文，內容標示日期為 **2026-04-28**，不是頁面 SEO 標題中的當月日期；表格細節未完整取得。大立光官方產品頁可核對稜鏡微透鏡陣列與 1D／2D 光纖陣列。NVIDIA 2025-08-26 技術文用來核對 ELS、矽光子調變及微光學／光纖整合分工，不作大立光客戶資格證據。

## 已更新的研究

- 手機光學與 CPO 耦合並行，不畫成手機鏡頭必然升級 CPO 的單一路線。
- 分開雷射發光、PIC 電光調變、稜鏡／微透鏡轉向整形與光纖耦合，避免直接照標題推定台積電是雷射供應商。
- 產品存在、客戶驗證、試產／量產、收入分開；沒有補造客戶、ASP、產能、良率或量產日期。
- 比較改成同波長、通道、光路與可靠度下的插入損耗、回波損耗、對位容差、串擾、良率與每合格通道成本，並納入晶圓級微透鏡整合的替代可能。
- 文中供應商替代、上詮／台積電關係及奇景／玉晶光進度主張，列為待一手核實，未當成已確認供貨或領先幅度。
- 增加採用埠數、元件內容、份額、ASP 到毛利／現金的因果橋與反證條件。維持三軸中性／營運方向中立，未以新題材代替驗證。

財務仍明示為 10/25 所取得的 9 月營收／2026Q2 快照；本次未取得可完整核對的官方 Q3 文件，不把站內舊季度標成最新。研究仍為草稿。證據台帳同步更新 `3008` 區塊，另保留精簡、無私人資料的來源 fixture。

## 驗證

新內容測試先因舊日期與缺 CPO 證據分級而失敗，再更新至綠。命令：

```text
poetry run python -m pytest tests/test_largan_cpo_research.py tests/test_research_review_20261025.py tests/test_market_research.py tests/test_research_etf.py -q
<bundled-node> node_modules/vitest/vitest.mjs run tests/market/researchMermaid.test.ts tests/market/researchMap.test.ts
```

後端 33 項通過；前端 28 項通過，包含實際研究內容的 Mermaid 解析。正式建置與 seed 新版入庫由既有 Jenkins／startup 流程負責，人工編輯保護規則不變。
