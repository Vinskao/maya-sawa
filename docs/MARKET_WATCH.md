# AI 觀察名單（自動進出 custom 區）

研究員（排程的 AI）讀研究報告時，若發現一檔**不在儀表板**的台股有具體證據，就提名進 custom 區。
這份名單有明確的進入、停留、離開規則，規則的程式在 `maya_sawa/services/market_watch.py`（純函式，有測試）。

## 狀態

| 狀態 | 意思 |
|---|---|
| `candidate` 候選 | 被提名過，但支持不夠；不顯示在儀表板 |
| `watching` 觀察中 | 顯示在 custom 區，列上「AI 觀察 · 到期 MM/DD」標籤 |
| `expired` 已移出 | 太久沒有報告再提到它 |
| `held` 已買入 | 擁有者買進，變成一般持股（自動區），不再算名單 |

## 規則

- **進入。** 21 天內有兩份**不同**的報告支持（一次提名引用兩份報告即可），或一次 `conviction: high` 的提名。
  只有一份報告時維持候選。同一份報告同一天重複提名只算一次，但可以把 `normal` 升成 `high`。
- **留多久。** 以「最後一次被報告提到」起算 30 天；每次有新的報告支持就續期。30 天沒有人提到，就自動移出（報告的焦點移到別處了）。
- **名額。** 同時最多 3 檔，不佔用擁有者自己的 5 個自選。額滿時，新進的會取代被冷落最久的，但被取代者要已待滿 7 天。
  被取代的回到候選，不是丟掉。
- **買入。** 擁有者買進後（自動區出現該代碼），它從名單移出，成為一般持股。
- **賣出後回來。** 賣掉之後它回到候選；如果近 21 天仍有兩份報告（或一次 high）支持，立刻回到 custom 區，否則等新報告。
- **移出後再回來。** 已移出的標的，只要報告再次提到並達到進入條件，就會回來。
- 名單只收**台股 4 位數代碼**（custom 區的資料、歷史與分析流程是台股的），且不收已是持股的標的。

## API

- `POST /market/watch`（只收 agent key）`{code, name?, reason, reportIds[], conviction}`：提名。`reason` 10–300 字；
  `reportIds` 必須是存在且公開的報告；代碼要查得到。回傳 `{code, status, promoted}`。剛進名單的標的，系統會立刻補歷史資料並產生第一份 AI 分析。
- `GET /market/watch`（公開）：`watching`（含理由、報告數、到期時間）與 `candidates`。
- `GET /market/dashboard` 的 `custom` 會附上觀察中的標的（`source: "ai-watch"`、`reason`、`reports`、`expiresAt`）；
  事件、籌碼摘要與報價訂閱也把它們當自選處理。

到期與買賣是讀取時計算（不靠計時器），所以名單永遠是當下正確的。

## 排程怎麼用

提名規則寫在公開的 `market-ai.md`（「Watchlist nominations」一節），排程每輪開頭都會讀，不需要改排程提示詞。
排程讀 `claims` 時看到報告點名、而儀表板沒有的台股，就依規則提名；每輪最多 3 檔，並先讀 `GET /market/watch` 避免重複。

## 之後可以調的

`PROMOTE_SOURCES`、`PROMOTE_WINDOW_DAYS`、`TTL_DAYS`、`MIN_STAY_DAYS`、`SLOTS` 都在 `market_watch.py` 最上面。
