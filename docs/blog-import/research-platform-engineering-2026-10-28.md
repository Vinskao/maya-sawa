---
slug: research-platform-engineering-2026-10-28
title: "不加依賴的 OpenTimestamps：把每天的資料庫修訂錨定到比特幣"
description: "自己解析 .ots 證明檔、合併三個 calendar 的收據、升級成比特幣區塊證明，並讓任何人能從公開 API 重算指紋。含程式碼、替代方案比較、測試與踩過的坑。"
category: Software Engineering
tags: [Software Engineering, OpenTimestamps, Python, Merkle Tree, PostgreSQL, TDD]
publishDate: "2026-10-28T17:00:00+08:00"
---

## 問題

**輸入**：一張自己管理的 PostgreSQL 表（`maya_sawa_market_ai_analysis_revision`），每列是一則 AI 分析的不可變版本，帶有 `updated_at`。
**輸出**：一份第三方可以獨立驗證的證明，內容是「台北時間某一天寫入的這些版本，在某個比特幣區塊之前就已存在，之後沒被改過」。
**限制**：
- 不付手續費，不持有錢包或私鑰。
- 不增加 Python 套件，維持現有的依賴集。
- 只有一個 pod（`replicas: 1`），重啟或重跑都不能重複蓋章。
- 驗證者只需要公開 API，不用信任站方。

**為什麼需要**：`updated_at` 是站方自己寫的欄位，管理者事後可以改任何一列，或把今天寫的分析補成上週的日期。資料庫本身的時間戳記無法證明「先有判斷，後有行情」。

## 原理

OpenTimestamps（OTS）把「證明某個 32 位元組雜湊在某時間點已存在」拆成兩步：

1. **Calendar 收件**：把雜湊 POST 到公開的 calendar 伺服器（`/digest`）。伺服器把全世界送來的雜湊組成 Merkle tree，每隔一段時間把根放進一筆比特幣交易，手續費由伺服器吸收。它立刻回傳一段「從你的雜湊到它內部承諾值的操作序列」，結尾是 *pending* attestation（寫明 calendar URI）。
2. **升級**：交易進區塊後，用承諾值 GET `/timestamp/<hex>`，會拿到剩下的路徑：從承諾值一路做到該區塊的 Merkle root，結尾是 *Bitcoin* attestation（區塊高度）。404 代表還沒進區塊。

`.ots` 證明檔就是這棵操作樹的序列化格式。每個節點有兩種內容：

- **attestation**：8 位元組標籤加上 payload。pending 標籤是 `83dfe30d2ef90c8e`，Bitcoin 標籤是 `0588960d73d71901`。
- **operation**：例如 `0xf0` append、`0xf1` prepend、`0x08` sha256，各帶一個子節點。

一個節點有多個分支時，除了最後一個分支，其餘分支前面都加 `0xff`。長度與高度都用 LEB128 varuint 編碼。驗證時從原始雜湊沿操作走到 Bitcoin attestation，最後的訊息必須等於該區塊 header 裡的 Merkle root（位元組順序反轉）。

## 實作

程式碼在 `maya_sawa/services/analysis_timestamps.py`（commit `885e619`）。

### 1. 解析：遞迴下降，限制深度與長度

```python
def parse_timestamp(stream, depth=0) -> Timestamp:
    if depth > 256:
        raise ValueError("proof too deep")
    node = Timestamp()
    while True:
        tag = stream.read(1)
        if not tag:
            raise ValueError("truncated proof")
        more = tag == b"\xff"
        if more:
            tag = stream.read(1)
        if tag == b"\x00":
            node.attestations.append((stream.read(8), _read_varbytes(stream)))
        elif tag[0] in BINARY_OPS:
            node.ops.append((tag[0], _read_varbytes(stream), parse_timestamp(stream, depth + 1)))
        elif tag[0] in UNARY_OPS or tag[0] == 0x67:
            node.ops.append((tag[0], None, parse_timestamp(stream, depth + 1)))
        else:
            raise ValueError(f"unknown proof operation {tag.hex()}")
        if not more:
            return node
```

**不變式**：`serialize(parse_timestamp(x)) == x`，也就是解析後寫回要逐位元組相同。所以節點裡的 attestation 與 op 都保留讀入順序，不用 dict。`_read_varbytes` 設 8192 位元組上限、深度上限 256，因為 calendar 回應是外部輸入，不能讓它造成無限遞迴或吃光記憶體。時間與空間都是 O(證明大小)。

### 2. 合併多個 calendar：同一訊息的節點直接串接

```python
def merge(nodes: list[Timestamp]) -> Timestamp:
    return Timestamp(attestations=[a for node in nodes for a in node.attestations],
                     ops=[o for node in nodes for o in node.ops])
```

三個 calendar（`a.pool`、`b.pool.opentimestamps.org`、`a.pool.eternitywall.com`）的回應都從同一個雜湊開始，所以合併只要把各自的分支掛在同一個根節點下。只要有一個 calendar 收下就算成功；三個都失敗時拋例外、不存檔，下一個小時再試。

### 3. 升級：走訪樹，用每個 pending 節點當下的訊息去問

```python
def upgrade(node: Timestamp, message: bytes, fetch) -> bool:
    changed = False
    for here, at in list(_walk(node, message)):       # (節點, 走到這裡時的訊息)
        for attestation in list(here.attestations):
            if attestation[0] != PENDING:
                continue
            uri = _read_varbytes(io.BytesIO(attestation[1])).decode()
            raw = fetch(uri, at)                      # GET {uri}/timestamp/{at.hex()}
            if not raw:
                continue                              # 404：還沒進區塊
            extra = parse_timestamp(io.BytesIO(raw))
            if not bitcoin_heights(extra, at):
                continue                              # 回應裡仍只有 pending
            here.attestations.remove(attestation)
            here.attestations += extra.attestations
            here.ops += extra.ops
            changed = True
    return changed
```

重點是：向 calendar 查詢時要帶**走到那個 pending 節點時的訊息**（`at`），不是最初的雜湊。`_walk` 用 generator 邊走邊套用操作，因此每個節點的訊息都只算一次。

### 4. 要蓋章的內容：可從公開 API 重算的 manifest

```python
def revision_hash(row: dict) -> str:
    fields = {key: row[key] for key in ("code", "content", "model", "productType", "revision", "updatedAt")}
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()
```

每天的 manifest 是 `{schema, day, timezone, revisions:[{productType, code, revision, updatedAt, sha256}]}`。它用相同的正規化方式序列化（key 排序、無空白、UTF-8），只對 manifest 的 SHA-256 蓋章。

欄位只取公開 API `GET /market/dashboard/analysis/{code}` 的 `history` 會回傳的那幾個；`updated_by` 不公開，所以不納入。`updatedAt` 也用 API 的格式（`datetime.isoformat()`），否則外部重算的結果會對不上。

### 5. 冪等與排程

- `day` 是主鍵；`stamp_day` 先查 `database.get(day)`，已存在就不蓋。
- 背景工作每小時跑一次：蓋「昨天（台北）」一次，再升級所有 `pending` 的日子。
- 台北日界用 `datetime.combine(day, time(), ZoneInfo("Asia/Taipei")).astimezone(UTC)` 轉成 UTC 區間 `[前一天 16:00, 當天 16:00)`。

### 6. 只連白名單

```python
def calendar_allowed(uri: str) -> bool:
    parts = urllib.parse.urlsplit(uri)
    return (parts.scheme == "https" and parts.hostname is not None and parts.port is None and not parts.username
            and parts.netloc == parts.hostname and parts.hostname.endswith(CALENDAR_HOSTS))
```

pending attestation 裡的 URI 來自外部回應。不檢查的話，惡意或被入侵的 calendar 可以讓伺服器去連任意網址（SSRF）。

## 替代方案

| 方案 | 證明什麼 | 成本 | 要信任誰 | 不選的原因 |
|---|---|---|---|---|
| 自己用私鑰簽章 | 是誰簽的 | 免費 | 站方 | 持有私鑰的人可以隨時簽一份舊日期，證明不了時間 |
| RFC 3161 時間戳記機構（TSA） | 某時間點已存在 | 免費到付費都有 | 該機構與其憑證鏈 | 要信任單一機構；憑證過期後驗證流程較複雜 |
| 把雜湊推到公開 Git repo 或社群貼文 | 平台上的時間 | 免費 | 平台 | 平台的時間可以改，帳號也可能被刪 |
| 自己發比特幣交易（OP_RETURN） | 某區塊前已存在 | 每次手續費 | 比特幣 | 要錢包、私鑰與手續費管理 |
| 官方 OTS 用戶端套件 | 同本方案 | 免費 | 比特幣 | 要多帶依賴；我們只需要 sha256、append、prepend 與兩種 attestation，大約 150 行 |
| **本方案：自寫 `.ots` 解析＋公開 calendar** | 某區塊前已存在 | 免費 | 比特幣（calendar 只影響可用性） | — |

## 驗證

測試在 `tests/test_analysis_timestamps.py`，共 12 個，全部通過。其中幾個：

- `test_reads_and_rewrites_the_official_example_proof_byte_for_byte`：官方範例 `hello-world.txt.ots` 解析後寫回逐位元組相同，並讀出比特幣區塊 358391。
- `test_a_proof_from_three_calendars_waits_on_each_of_them`：用 2026-10-28 三個 calendar 的真實回應當 fixture，合併後列出三個 pending。
- `test_upgrading_swaps_a_pending_calendar_for_its_bitcoin_path_and_keeps_waiting_on_the_others`：一個 calendar 已確認、一個還在等。
- `test_only_known_public_calendars_are_contacted`：`http://`、非白名單網域、`opentimestamps.org.evil.com` 這種後綴偽裝、IP 位址、`...opentimestamps.org@evil.com` 這種帳密偽裝都會被拒絕。
- `test_hashes_from_the_database_match_hashes_recomputed_from_the_public_analysis_api`：在 SQLite 寫入版本，從 API 的輸出重算指紋，結果與 manifest 一致。
- `test_a_day_is_not_stamped_when_every_calendar_fails`：三個 calendar 全失敗時不寫入資料。

正式環境（`GET /maya-sawa/market/timestamps`，2026-10-29 查詢）：

| 日期（台北） | 版本數 | 狀態 | 比特幣區塊 |
|---|---|---|---|
| 2026-10-27 | 50 | confirmed | 973541 |
| 2026-10-28 | 21 | confirmed | 973584 |

每天的 manifest 和 `.ots` 可從 `/market/timestamps/{day}/manifest` 與 `/proof` 下載，兩個一起拖到 opentimestamps.org 驗證。

## 踩過的坑（維護或仿作前先看）

1. **Git 改了二進位 fixture 的換行**：Windows 的 `core.autocrlf` 把 `.ots` 和 calendar 回應裡的 `0x0a` 換成 `0d0a`，逐位元組測試在另一台機器上就失敗。解法是在 `.gitattributes` 加 `tests/fixtures/ots/* -text`（commit `383b4fe`）。任何二進位 fixture 都要這樣處理。
2. **升級要用節點當下的訊息**：拿原始雜湊去查 `/timestamp/` 只會一直拿到 404。
3. **重算失敗多半是格式差一點**：`updatedAt` 的格式、JSON 是否排序、有沒有空白、`ensure_ascii` 都會改變雜湊。測試要直接比對 API 的輸出，不要比對自己再組一次的 dict。
4. **不要回補過去的日子**：今天才幫上週的資料蓋章，只能證明「今天已存在」，卻容易被讀成「上週就蓋過」。所以只從上線那天的前一天開始蓋。
5. **calendar 回應是不可信輸入**：要有長度上限、深度上限和網域白名單。

## 限制

- 只證明「什麼時候已存在、之後沒改」，不證明是誰寫的，也不證明內容對不對。
- 每天只蓋一份 manifest，粒度是一天；同一天內的先後順序不在證明範圍內。
- 公開 API 每檔只回傳最近 20 個版本，更早的版本仍在清單裡，但外部無法取回原文來重算。
- 驗證者要信任比特幣的區塊 header（opentimestamps.org 或自己的節點）；calendar 停擺只影響「能不能升級」，不影響已確認的證明。

## 參考資料

- OpenTimestamps 官方說明與格式：<https://opentimestamps.org>、<https://github.com/opentimestamps/opentimestamps-client>
- Peter Todd，〈OpenTimestamps: Scalable, Trust-Minimized, Distributed Timestamping with Bitcoin〉（2016）
- 本站實作：`maya_sawa/services/analysis_timestamps.py`、`maya_sawa/databases/analysis_timestamp_db.py`、`docs/ANALYSIS_TIMESTAMPS.md`
