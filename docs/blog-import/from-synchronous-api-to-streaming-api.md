---
title: "from-synchronous-api-to-streaming-api"
publishDate: "2025-09-08 14:30:00"
img: /tymultiverse/assets/django.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  深入探討從傳統同步 API 轉型到串流 API 的完整架構變更，包括技術原理、實作細節、效能優化與部署策略，幫助開發者建構即時響應的現代化應用
level: advance
category: Spring Boot
tags:
  - API Design
  - Streaming
  - WebSocket
  - Real-time
  - Architecture
---

# 從同步 API 到串流 API：架構轉型完整指南

在現代 Web 應用中，**「即時回應」**已經成為使用者的基本期待。無論是 AI 聊天、影音串流，還是股價/比賽的即時推播，都需要一種比傳統 API 更靈活的方式。

這篇文章會帶你從 同步 API（一次回傳整包結果），走到 串流 API（邊處理邊回傳），並逐步拆解原理、架構、程式碼和最佳實踐。即使你是第一次聽到 Streaming API，也能跟著理解並想像它的應用場景。

## 生活比喻：同步 vs 串流

**同步 API**：像去餐廳點菜，要等主廚把整道菜做好後才端上來。

**串流 API**：像去吃鐵板燒，廚師邊煎邊上桌，你一邊看、一邊吃。

→ 在等待的過程中，串流會讓人感覺更快、更有互動感。

## 為什麼要轉型？

### 傳統同步 API（HTTP 請求-回應）

**運作**：前端發請求 → 後端計算 → 一次回傳 JSON

**缺點**：
- 長時間等待，使用者看不到進度
- 無法中途打斷
- 適合 CRUD，不適合長任務（AI 生成、影音轉檔）

### 串流 API（Streaming Response）

**運作**：前端發請求 → 保持連線 → 後端邊算邊傳

**好處**：
- 使用者能「邊等邊看」結果，例如 AI 回答逐字出現
- 可以隨時中斷 / 切換請求
- 特別適合聊天 AI、即時數據、直播彈幕等場景

## 架構轉換大圖

| 元件 | 同步 API | Streaming API |
|------|----------|---------------|
| 前端 | `fetch()` 拿完整結果 | WebSocket 連線，逐步接收 |
| 後端 | REST Endpoint | WebSocket Endpoint，持續推送 |
| 資料庫 | 儲存整段訊息 | 新增 `streaming_messages`，存分段 |
| 中介層 | Celery 任務排程 | Redis 快取狀態，記錄進度 |

## 核心資料設計

### Redis：管理會話狀態

```json
{
  "history": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi, how can I help you?"}
  ],
  "last_updated": "2025-09-08T10:00:00"
}
```

- 快速存取對話
- 多台伺服器共享（水平擴展）

### PostgreSQL：存流式訊息

| 欄位 | 說明 |
|------|------|
| `session_id` | 聊天連線 ID |
| `chunk_sequence` | 分段序號 |
| `content` | AI 回應文字片段 |
| `is_complete` | 是否為最後結束 |
| `created_at` | 時間戳 |

**查詢範例**：
```sql
SELECT content 
FROM streaming_messages 
WHERE session_id = 'abc123' 
ORDER BY chunk_sequence;
```

### 前端事件流（WebSocket）

**常見事件**：
- `user_message`：使用者發送
- `ai_response_chunk`：AI 部分回應
- `ai_response_complete`：AI 完成
- `status`：狀態更新
- `error`：錯誤通知

**體驗流程**：
輸入後 → 顯示「正在輸入...」 → 逐字回覆 → 完成 → 開放下一句輸入

## ⚡ 流程比較

### 同步模式

1. User → HTTP 請求
2. Server → 生成完整結果
3. User → 一次收到 JSON

體驗：長時間空白，突然跳出結果

### Streaming 模式

1. User → 發送 `user_message`
2. Server → 推送 `status`（正在處理）
3. Server → 持續傳送 `chunk`（文字片段）
4. Server → 傳送 `complete`
5. User → 即時看到逐字輸出

體驗：像聊天一樣自然

## 正確實作流程

### 訊息傳輸流程

1. **User 發送訊息**
   - 前端 → WebSocket → 後端

2. **後端處理**
   - 儲存 `user_message` 到 Redis/PostgreSQL（記錄對話歷史）
   - 開始呼叫 AI API（OpenAI、Llama 等）

3. **AI 流式回覆**
   - AI 回傳「流式片段（chunk）」
   - 每拿到一個 chunk：
     - **立即推送**給前端（WebSocket）
     - **同時寫入**PostgreSQL（存歷史）

4. **完成訊息**
   - AI 結束 → 後端送 `ai_response_complete`
   - 更新 PostgreSQL 最後一筆 `is_complete = true`

### WebSocket 推送原則

**一定要即時、非阻塞**：
- 當 AI 生成一個 chunk，後端應該立刻送到 WebSocket
- 使用**非阻塞 I/O（async I/O）**
- WebSocket 本質是「事件驅動」，邊收邊發

**實作範例**：
```python
# Python (Django Channels)
async def send_chunk(websocket, chunk):
    await websocket.send_text(chunk)  # 非阻塞推送

# Node.js
ws.send(chunk)  # 本身就是非阻塞
```

## 實作路徑（簡化版）

### 前端
- 建立 WebSocket 連線
- 訂閱事件（chunk / complete / error）
- 動態更新聊天框

### 後端
- 新增 WebSocket Consumer（接收 user_message，回傳流式結果）
- AI 回應改用「流式產生器」
- 使用 Redis 保存上下文

### 資料庫
- 新增 streaming_messages 表，紀錄每個分段

### 部署
- 使用 daphne 或 uvicorn 啟動 ASGI
- Redis + PostgreSQL 配合 Channels

## 核心實作項目

| 層級 | 項目 | 說明 |
|------|------|------|
| **前端** | WebSocket 連線 | 建立長連線、處理重連機制 |
| **前端** | 流式訊息顯示 | 即時更新 UI、打字指示器 |
| **後端** | WebSocket 端點 | 處理連線、訊息分發 |
| **後端** | 流式回應生成 | 分塊傳輸、AsyncGenerator |
| **資料庫** | 流式訊息表 | 儲存分片、支援回放 |

### 流式訊息表實現方式

#### 為什麼需要分片？

**分片（Chunk）**：將 AI 的完整回應拆分成多個小片段，逐個傳送給前端。

**原因**：
- **即時性**：AI 生成 1000 字需要 10 秒，分片後用戶每秒都能看到新內容
- **使用者體驗**：避免長時間空白等待，提供「正在輸入」的感覺
- **網路效率**：小片段傳輸更穩定，減少超時風險
- **中斷恢復**：網路斷線時可以從最後一個分片繼續

**分片範例**：
```
完整回應：「你好！我是 AI 助手，很高興為您服務...」
分片 1：「你好！我是」
分片 2：「 AI 助手，」
分片 3：「很高興為您」
分片 4：「服務...」
```

#### 1. 資料表設計
```sql
CREATE TABLE streaming_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    chunk_sequence INTEGER NOT NULL,
    content TEXT NOT NULL,
    is_complete BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 索引優化
CREATE INDEX idx_session_sequence ON streaming_messages(session_id, chunk_sequence);
CREATE INDEX idx_session_complete ON streaming_messages(session_id, is_complete);
```

#### 2. 儲存流程
```python
# 儲存分片
async def save_chunk(session_id: str, chunk: str, sequence: int):
    await StreamingMessage.objects.acreate(
        session_id=session_id,
        chunk_sequence=sequence,
        content=chunk,
        is_complete=False
    )

# 標記完成
async def mark_complete(session_id: str):
    await StreamingMessage.objects.filter(
        session_id=session_id
    ).aupdate(is_complete=True)
```

#### 3. 回放機制
```python
# 重組完整訊息
async def replay_message(session_id: str):
    chunks = await StreamingMessage.objects.filter(
        session_id=session_id
    ).order_by('chunk_sequence').values_list('content', flat=True)
    
    return ''.join(chunks)
```
| **部署** | ASGI 服務器 | 支援 WebSocket 協議 |


## 部署和測試

### 1. 資料庫遷移
```bash
# 執行遷移
python manage.py makemigrations
python manage.py migrate

# 檢查遷移狀態
python manage.py showmigrations
```

### 2. 啟動服務
```bash
# 啟動 Redis
redis-server

# 啟動 Celery Worker
celery -A config worker --loglevel=info

# 啟動 ASGI 服務器
daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

### 3. 測試 WebSocket 連線
```javascript
// 測試腳本
const ws = new WebSocket('ws://localhost:8000/ws/chat/test_session/');
ws.onopen = () => console.log('Connected');
ws.onmessage = (event) => console.log('Message:', JSON.parse(event.data));
ws.send(JSON.stringify({type: 'user_message', content: 'Hello'}));
```
