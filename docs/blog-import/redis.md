---
title: "redis"
publishDate: "2025-09-28 10:00:00"
img: /tymultiverse/assets/redis.png
img_alt: Redis database logo with data structures and performance metrics
description: Redis 在 TY Multiverse Backend 中的完整應用指南，從基礎概念到專案實戰，涵蓋非同步結果、分散式鎖、快取等核心場景。
level: advance
category: Database
tags:
  - Redis
  - Caching
  - Distributed Systems
  - Backend Development
---

# Redis 是什麼？為什麼快？

Redis 是一個**基於記憶體的 Key-Value 資料庫**，特色是：

- **所有資料存在記憶體** → 不需要像傳統資料庫一樣頻繁讀寫硬碟。
- **單執行緒模型** → 所有指令依序執行，不需要加鎖，避免了多執行緒的競爭開銷。
- **非阻塞 I/O** → Redis 透過 epoll/kqueue 多路複用技術，可以同時處理成千上萬的連線。

👉 **簡單說**：Redis 就像「一個超快的白板筆記本」，只要你記得 key，就能瞬間找到對應的 value。

# 設計背後的理由

## 記憶體為核心 → 需要高效結構

- Redis 完全基於記憶體存儲（Memory-first DB），不像傳統 DB 依賴磁碟與索引。
- 因此設計了操作時間複雜度可控、低延遲的資料結構（O(1)、O(logN)）：
  - **String** → 單值存取最快（O(1)）
  - **Hash** → 減少 key 爆炸、節省記憶體
  - **List** → 可當佇列，操作頭尾元素為 O(1)
  - **Set** → 天然去重，支援集合運算

## 簡化常見應用場景

Redis 不是要取代關聯式資料庫，而是要「補強快取 + 協調 + 即時計算」。因此挑選了後端最常見、覆蓋度高的結構：

- 需要快取值 → String
- 需要存物件屬性 → Hash
- 需要佇列/排程 → List
- 需要集合運算（好友、標籤、去重） → Set

→ 這些場景已涵蓋約 80% 的分散式系統需求。

## 支援高併發與分散式協調

如果只有 String，所有功能都要靠字串拼接與自訂序列化，笨重且容易出錯。Redis 直接提供多種結構，讓伺服器之間協調任務更直覺：

- **Hash** → 儲存任務狀態
- **List** → 佇列化工作分派
- **Set** → 控制唯一性／去重
- **Pub/Sub** → 即時事件通知

## 降低開發者心智成本

與其讓工程師用 String 自行封裝 JSON、再寫 parser，Redis 乾脆內建 Hash / List / Set，能直接操作「半結構化資料」，
減少膠水程式碼與重複造輪子，降低錯誤率與認知負擔。

# Redis 在 TY Multiverse Backend 中的三大應用

## (A) 非同步結果查詢（Async Result）

### 場景
用戶請求需要耗時計算（例如 Producer 投遞後端任務）。

### 解法
1. 先回覆 **202 Accepted**，告訴客戶端「任務已受理」。
2. 任務完成後，把結果寫入 Redis → `async:result:{requestId}`。
3. 客戶端用 requestId 輪詢查詢。

### ✨ Redis 為什麼適合？
- **支援 TTL（過期時間）** → 結果自動清理（30 分鐘）。
- **高速讀取** → 適合大量輪詢，不會壓垮主資料庫。

### 🔄 幂等性保證的詳細工作流程

#### 完整的處理邏輯
在非同步訊息系統中，為了防止重複處理和確保結果一致性，我們實現了基於 Redis 的幂等性保證機制。

##### 四種可能的執行路徑

###### 路徑1：首次正常處理
```java
setIfAbsent 返回 true（鍵不存在，設置成功）
alreadyProcessed 为 null（Mono.empty()）
```
觸發 `switchIfEmpty` → `cachedFlow.switchIfEmpty(queryFlow)`
最終執行 `queryFlow`（資料庫查詢）

###### 路徑2：重複請求命中快取
```java
setIfAbsent 返回 false（鍵已存在）
alreadyProcessed 为 Boolean.FALSE
```
直接執行 `cachedFlow`（Redis快取）

###### 路徑3：重複請求快取失效
```java
setIfAbsent 返回 false（鍵已存在）
alreadyProcessed 为 Boolean.FALSE
cachedFlow 返回 Mono.empty()（快取失效）
```
觸發 `switchIfEmpty(queryFlow)`，執行資料庫查詢

###### 路徑4：系統異常重試
```java
setIfAbsent 返回 false（鍵已存在）
alreadyProcessed 为 Boolean.FALSE
```
如果之前處理失敗過，通過快取或重新查詢保證結果一致性

#### ⏱️ 為什麼選擇5分鐘過期時間？

##### 考慮因素：
- **處理時間窗口**：給非同步操作足夠的處理時間
- **重複請求頻率**：防止短時間內大量重複請求
- **資源清理**：避免Redis中累積太多過期鍵
- **業務時效性**：5分鐘內重複請求通常是異常情況

#### 🆚 幂等性 vs 快取的區別

| 特性 | 幂等性保證 | 快取機制 |
|------|------------|----------|
| **目的** | 防止重複處理 | 提升性能 |
| **鍵設計** | `idempotent:{operation}:{requestId}` | `cache:{operation}:{params}` |
| **過期時間** | 較長（5分鐘） | 較短（60秒） |
| **作用範圍** | 全域請求級別 | 資料級別 |

#### 📨 在非同步訊息系統中的重要性
由於使用了 RabbitMQ 非同步訊息佇列，訊息可能因為網路問題、服務重啟等原因被重複投遞。Redis 幂等性保證確保了：

- **訊息重複消費防護**
- **結果一致性**
- **系統容錯性**
- **資源浪費控制**

#### 💡 總結
這個幂等性實現是一個典型的**分散式鎖 + 快取雙重保證的模式**，既防止了重複處理，又提供了性能優化，在非同步訊息處理的場景中特別重要。

## (B) 分散式鎖（避免多實例重複工作）

### 🖥️ 單機鎖 vs 分散式鎖：為什麼需要分散式鎖？

#### 單機情境（單一 JVM）
假設我們有一個後端程式，裡面有個方法 `generateReport()`，會產生報表。如果多個執行緒同時呼叫，可能會造成衝突，所以我們加了 Java 的鎖：

```java
public synchronized void generateReport() {
    // 只允許一個執行緒進來
    doHeavyReportJob();
}
```

或用 `ReentrantLock`：
```java
lock.lock();
try {
    doHeavyReportJob();
} finally {
    lock.unlock();
}
```

這時候，只要程式跑在同一台 JVM 裡，鎖就有效，因為它鎖的是「同一個進程的記憶體」。

#### ☁️ 分散式情境（多節點、多 JVM）
在生產環境裡，我們通常會部署多台機器同時跑同一個程式，例如三台 API server：

```
[ Node A ]    [ Node B ]    [ Node C ]
   JVM           JVM           JVM
```

這時候問題來了：

- `synchronized` 或 `ReentrantLock` 只能管住**自己 JVM 內的執行緒**
- Node A 的鎖完全不會影響 Node B、Node C
- 結果：三台節點的排程器同時啟動 `generateReport()`，大家各自以為自己「拿到鎖」了

**後果**：產生了三份重複報表、同一帳號被扣款三次、同一通知被發送三次。

#### 🔑 為什麼要用分散式鎖？
因為我們需要一個「全域可見」的鎖，讓**所有節點都能共享鎖的狀態**。

Redis 就能扮演這個「鎖的協調者」：
- 不管 Node A / B / C 誰來搶，都要透過 Redis
- Redis 是單執行緒的，可以保證只有第一個成功
- 其他節點看到「鎖已存在」就得等待

**總結**：單機鎖只保護「同一個 JVM 裡的多執行緒」，分散式鎖要保護「多台 JVM、多台機器上的多執行緒」。

### 2. 分布式互斥鎖 (Distributed Mutex Lock) 實戰場景

#### lock:order:close 屬於什麼類型的鎖？

`lock:order:close` 屬於**分布式互斥鎖 (Distributed Mutex Lock)**，作用是保證「同一個資源 / 任務」在同一時間只能被**一個節點**執行。

#### 典型場景：定時任務（CronJob）防重複執行

例如：你有 3 台服務器都會跑「每分鐘關閉過期訂單」的任務

**如果沒有鎖**：
- 3 台同時關閉，訂單可能被重複處理
- 同一筆訂單可能被多次標記為「已關閉」

**加鎖後**：
- 只有 1 台成功搶到鎖，其他節點會跳過
- 整個「關閉訂單批次」任務只會被執行一次

👉 所以 `lock:order:close` 是一個**全局任務級的鎖**，不是針對單筆訂單，而是整個「關閉訂單批次」任務。

#### ❓ 是不是 CRUD 前後都要查 Redis 鎖？

**答案：不是所有 CRUD 都要加 Redis 鎖，要看情境。**

##### 1. 不用鎖的情況（大部分 CRUD）
- **一般查詢（Read）**：直接靠資料庫索引
- **一般新增、修改、刪除**：DB 已有唯一鍵、交易鎖保護
- **這些直接靠資料庫（transaction、索引、唯一鍵）就能保證一致性，不需要 Redis 鎖。**

##### 2. 需要鎖的情況（跨機 / 高併發爭用）

###### 定時任務防重複
- 多台機器同時執行批次任務（例如關閉訂單、發送通知）
- → 需要 Redis 全局鎖，保證只有一台跑。

###### 資源爭用（跨機器）
- 多個節點同時操作「同一個資源」，DB 鎖不足以保護時
- 例如：
  - 多個節點同時扣同一個商品庫存（要鎖 `lock:product:123:stock`）
  - 同時更新同一個用戶錢包餘額（要鎖 `lock:user:1001:balance`）

###### 避免重複請求
- 使用者短時間內點了兩次「付款」
- → 透過 Redis 鎖，確保同一個訂單只處理一次。

### 4. 為什麼分散式鎖用 String？

#### 鎖的本質 = 某個「key 是否存在」
分散式鎖的核心邏輯就是：

- 如果這個 key **不存在** → 代表「沒有人持有鎖」，我可以加鎖
- 如果這個 key **存在** → 代表「鎖已被別人持有」，我不能加鎖

👉 這個檢查「有或沒有」的語意，剛好就是 **String key 存不存在** 最直覺。

#### Redis 的 SET key value NX PX 天然支援鎖需求
- **NX** → 保證只有當 key 不存在時才能設置（確保鎖唯一性）
- **PX** → 自動設置過期時間，避免死鎖（機器掛了還一直佔鎖）
- **value** → 存一個唯一識別（通常是 UUID），用來辨識誰持有鎖，釋放時也能比對

### 5. SET NX PX：最簡單的分散式鎖

Redis 的核心命令：
```bash
SET lockKey uniqueValue NX PX 30000
```

- **NX = Not eXist** → 只有 key 不存在時才能設置成功
- **PX 30000** = 設定 TTL（30 秒），避免節點掛掉後鎖永遠不釋放（死鎖）
- **uniqueValue** = 用 UUID 來標識「誰」拿到鎖，避免錯刪

### 6. 判斷是否加鎖成功

#### 成功 (第一次搶到鎖的機器)
- **Redis 回覆 OK**
- 後端開始執行對應的 CRUD / 批次任務

#### 失敗 (鎖已經存在)
- **Redis 回覆 null**
- 後端知道「這個任務正在被別台機器執行」

**有兩種處理方式：**
- **直接跳過** → 什麼都不做（適合定時任務，避免重複跑）
- **重試等待** → sleep 一下再 retry（適合資源搶佔或佇列消費場景）

### 7. 解鎖用 Lua 腳本檢查是不是自己持有的鎖
```lua
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
else
  return 0
end
```

說明：在同一個 Lua 腳本內同時檢查與刪除，確保原子性。

### 8. 可重入鎖（Reentrant Lock）

#### 問題
在 Java `synchronized` 中，如果同一個執行緒已經持有鎖，可以再次進入而不會死鎖。但 Redis 基礎版的鎖做不到。

#### 解法
在 Redis 中，不只存 UUID，還存「重入計數器」：

```bash
// 加鎖
SET lockKey "{ owner: 'UUID-123', count: 2 }" NX PX 30000
```

每次同一個節點再次加鎖 → counter++，解鎖時 → counter--，直到為 0 才真正釋放。

數據結構範例：
```json
lockKey → { "owner": "UUID-123", "count": 2 }
```

👉 這就是**可重入鎖**，防止「同一節點」死鎖。

### 9. 公平鎖（Fair Lock）

#### 問題
一般鎖是「先到先搶」，但在高併發下可能出現**飢餓問題**：某些請求總是搶不到。

#### 解法
在 Redis 裡維護一個「等待隊列」，所有嘗試加鎖的請求會先進入隊列，然後嚴格按照先後順序獲得鎖。

實現方式：
- 用 List（或 ZSet）存放等待者（requestId）
- 每次釋放鎖時，檢查隊列最前面的是誰 → 發放鎖給他

👉 這就是**公平鎖**，類似 Java `ReentrantLock(true)`，避免某些節點一直餓死。

### 10. CountDownLatch（倒數閘門）

#### 問題
有些場景需要「等多個任務都完成再繼續」，例如：需要等待 3 個服務都初始化完，才能對外提供 API。

#### 解法
Redis 可以模擬 Java 的 `CountDownLatch`：

初始化：
```bash
SET latchKey 3
```

每個任務完成後：
```bash
DECR latchKey
```

等待者輪詢：
```bash
GET latchKey
```
直到變成 0 → 代表所有子任務完成。

或用 `BLPOP` 等待通知（更高效）。

👉 這就實現了**跨節點的 CountDownLatch**。

### 11. 為什麼選擇 Redisson？

手寫 `SET NX PX + Lua` 只夠處理最基本的「誰先拿到鎖就誰執行」。

但在真實業務中，需求更複雜：

- **可重入鎖**：避免自己卡住自己
- **公平鎖**：避免某些節點一直餓死
- **CountDownLatch / Semaphore**：需要「同步工具類」
- **看門狗機制**：鎖的 TTL 自動續期，避免長任務還沒完成鎖就過期

👉 **Redisson 優勢**：
- 基於 Redis，封裝好這些邏輯
- 讓用戶端像用 Java 原生 Lock 一樣方便
- 提供豐富的分散式資料結構和同步工具

### ✨ Redisson vs 自實作比較
- **手寫** → 輕量，只需 SET NX PX + Lua
- **Redisson** → 功能完整，但引入更多依賴

## (C) 快取（@Cacheable）

### 場景
傷害計算結果可能重複被請求。

### 解法
在 `WeaponDamageService.calculateDamageWithWeapon` 加上 `@Cacheable("damage-calculations")` → 第一次計算後存 Redis，下次直接取快取。

### ✨ 常見快取問題

- **雪崩**：大量 key 同時過期 → 在 TTL 上加隨機值。
- **穿透**：查詢不存在的資料 → 存空值或用布隆過濾器。
- **擊穿**：熱門 key 突然過期 → 用互斥鎖或預先續期。

# Redis 與 MQ 的整合

Redis 本身不是專業 MQ，雖然有 List / Stream 可以做訊息佇列，但功能（持久化、消費者群組、重試策略）不如專業 MQ 完整。

整合的重點：**Redis 更像是輔助快取 / 任務狀態存放區，而 MQ 才是「訊息流通主幹」。**

## 🔄 Redis + MQ 的典型整合流程

### 1. 任務投遞 + 快速回應

Producer（例如 Web API）把任務訊息送進 MQ（Kafka / RabbitMQ）。

同時，Producer 先在 Redis 寫一筆「任務狀態 = pending」：

```
async:result:{requestId} → { status: "pending" }
```

API 回 202 Accepted → 客戶端開始輪詢 Redis。

**好處：**
- MQ 處理慢也沒關係，客戶端不用直接依賴 MQ。
- Redis 能承受高頻查詢，避免打爆 MQ。

### 2. 消費者處理後更新結果

Consumer 從 MQ 拿到任務，開始處理。

處理完成後，把結果寫回 Redis：

```
async:result:{requestId} → { status: "done", data: ... }
TTL = 30 分鐘
```

客戶端輪詢查 Redis，就能拿到結果。

**這個模式就是專案的 AsyncResultService，只是目前結果是直接從 producer → Redis，也可以換成 producer → MQ → consumer → Redis。**

### 3. Redis 作為補充用途

- **快取**：即使 MQ 堆積很多訊息，客戶端查詢還是 Redis → 快速。
- **分散式鎖**：確保多個 consumer 不會處理同一份資料。
- **重試紀錄**：Consumer 處理失敗時，把失敗次數/狀態寫 Redis，再決定是否丟回 MQ。

## 🆚 Redis Stream vs 專業 MQ

Redis Stream 也能當 MQ，用 XADD / XREADGROUP 管理 consumer group。

適合**中小規模、對延遲很敏感的場景**。

Kafka/RabbitMQ 更適合**大流量 / 高可靠**場景，有完整的訊息重試、順序、回溯能力。

## 🎯 總結

**Redis + MQ 的最佳實踐：**

- **MQ**：負責「傳遞訊息、解耦服務」。
- **Redis**：負責「任務狀態查詢、快取、分散式控制」。

結合起來 → 客戶端不用直接依賴 MQ，透過 Redis 取得結果狀態，系統彈性更高。

# 可選功能：Redis Session

### 配置
已寫好 `@EnableRedisHttpSession`，受 `app.session.enabled` 控制。

### 優點
多節點共享 Session → 使用者登入後不會「在 A 節點正常，換到 B 節點掉線」。

### 目前狀態
預設關閉。

# Redis 核心技術補充

## (A) Redis 資料結構

- **String**：快取數值、JSON、Session。
- **Hash**：存放物件屬性（例如 user:{id} → name, email）。
- **List**：訊息佇列（類似 LinkedList）。
- **Set**：去重、標籤（如「某篇文章的讀者」）。
- **Sorted Set**：排行榜（分數決定排序）。
- **Bitmap/HyperLogLog**：統計 UV、活躍用戶。
- **Stream**：事件流（類似 Kafka）。

👉 **實戰應用**：我們 AsyncResult 就用 String，因為 key-value 最單純，還能 TTL；如果是排行榜就會用 ZSet。

## (B) Redis 高可用與持久化

### RDB
- **快照** → 恢復快，但可能丟失快照後的資料。

### AOF
- **操作日誌** → 資料安全，但檔案大，恢復較慢。

### Cluster
- **16384 slot**，透過 CRC16(key) % 16384 分散 key。

### Sentinel
- **監控 master**，掛了自動選新 master。

## (C) Redis 用戶端選擇

### Jedis
- 阻塞 IO，需要連線池。

### Lettuce（專案使用）
- 基於 Netty，非阻塞 + reactive 支援，自動重連。

# 監控與最佳實踐

## 應用層
Spring Boot Actuator → 健康檢查 Redis 連線。

## Redis 指標
INFO 查看記憶體、命中率、連線數。

## 業務指標
- Async 結果查詢延遲
- 鎖競爭失敗率
- 快取命中率

### 快取命中率（Cache Hit Ratio）

定義：衡量快取是否有效的核心指標。當請求讀取資料時，資料在快取中稱為命中（Hit），不在快取中稱為未命中（Miss）。

公式：

```
Hit Ratio = Cache Hits / (Cache Hits + Cache Misses) × 100%
```

例子：100 次查詢中 80 次命中、20 次未命中 → 命中率 = 80 / 100 = 80%。
