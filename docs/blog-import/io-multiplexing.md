---
title: "io-multiplexing"
publishDate: "2025-08-27 01:00:00"
img: /tymultiverse/assets/algorithm.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: 高併發架構深度剖析：從 I/O 多工技術到事件驅動設計的完整演進
level: advance
category: Concurrency
tags:
  - System Programming
  - I/O Multiplexing
  - Web Frameworks
  - Performance
  - OS Kernel
---

# 高併發架構深度剖析：I/O 多工技術與事件驅動設計

## 前言

現代 Web 開發的性能瓶頸，往往在於如何高效處理大量併發連線。本文從操作系統的 I/O 多工技術出發，深入探討事件驅動架構的設計理念，並比較不同 Web 框架的實現方式，為高併發系統架構設計提供完整指南。

從底層的 select/poll/epoll，到應用層的事件迴圈設計，再到具體框架的選擇，這篇文章將帶你完整理解現代 Web 架構的演進之路。

## OS 的「三種聽電話方法」

想像電腦要「接電話」（處理很多 socket 連線）。

### **1️⃣ select()：傳統點名法（效率最差）**
```c
// 像老師每天要點名一整個班級，每次都要從頭數到尾
int select(int nfds, fd_set *readfds, fd_set *writefds, fd_set *exceptfds, struct timeval *timeout);
```

**缺點：**
- 每次都要掃描所有 socket
- O(n) 複雜度，人一多就慢
- 最大監聽數量有限（通常 1024）

### **2️⃣ poll()：改善版點名法**
```c
// 改善一點，不用 bitset，但還是一個一個問：「你有事嗎？」
int poll(struct pollfd *fds, nfds_t nfds, int timeout);
```

**優點：** 支援更多 socket（理論上無上限）
**缺點：** 還是 O(n)，效率沒有根本改善

### **3️⃣ epoll/kqueue/IOCP：智慧舉手系統（現代標準）**
```c
// Linux epoll：學生自己舉手，有事再叫老師
int epoll_create(int size);
int epoll_ctl(int epfd, int op, int fd, struct epoll_event *event);
int epoll_wait(int epfd, struct epoll_event *events, int maxevents, int timeout);
```

**核心優勢：**
- **O(1) 複雜度**：不管多少 socket，效能都一樣
- **事件驅動**：OS 主動通知，不用輪詢
- **無上限**：理論上可以監聽數百萬個 socket

## Event Loop（事件迴圈）

有了 epoll/kqueue/IOCP 這些「聰明的點名系統」，程式就可以：

### **工作流程：**
1. **註冊監聽**：把「這個 socket 有事時要通知我」交給 OS
2. **OS 監控**：OS kernel 幫忙盯著所有 socket
3. **事件通知**：一旦有事件，OS 通知 event loop
4. **處理事件**：event loop 派 coroutine 去處理

### **效能優勢：**
- **一個 thread** 就能管理幾千上萬連線
- **不會傻傻地每個都檢查**
- **資源利用率極高**

### **Process（行程）與 Worker（工作程序）**

#### **Process（行程，程序）的本質**
**核心定義：** Process = 作業系統給一個程式分配的獨立資源單位。

**它可以是什麼：**
- Web server、資料庫、桌面應用
- 背景守護程式、系統服務
- 任何正在執行的程式

**關鍵特徵：**
- **隔離性**：其他 process crash 不會影響我
- **獨立記憶體**：不能直接存取別人 process 的變數
- **CPU 排程**：系統輪流給 process CPU 時間

**比喻：** 一間餐廳，有自己的廚房、冰箱、員工，不跟別家共享。

#### **Node.js Process 的特別代表性**
Node.js 世界最能體現 process 的本質：

**預設架構：** 只開「一個 process」跑 event loop。

**這個 process 不只處理 HTTP request，還處理：**
- **I/O 事件**：讀檔案、DB 查詢、網路 socket
- **計時器**：setTimeout、setInterval
- **系統訊號**：SIGINT（Ctrl+C）
- **事件監聽**：fs.watch 檔案變動
- **Promise/microtask**：排進 microtask queue

**Node Process 本質：** 「一個 event loop + 一堆系統 API callback queue」，request 只是其中一種事件。

#### **Worker（工作程序）**
**定義：** 一個特殊角色的 process → 專門拿來「處理 request」。

**本質：** worker = process（只不過工作是「處理 request」）。

**常見例子：**
- **Gunicorn/Uvicorn**：一個 worker = 一個 process
- **Celery worker**：從 queue 抓任務執行的 process

**比喻：** 如果 process 是餐廳，worker 就是專門做「接單 + 煮菜」的餐廳。

**⚡ 與事件迴圈的關係：**
- **傳統 worker**：thread-per-request，資源浪費
- **事件迴圈 worker**：一個 worker 管理萬級連線，資源高效

## 框架如何使用這些技術？

重點：**你不用自己挑選 select/epoll/kqueue**。

### **框架的智慧選擇：**
- **Linux** → 自動使用 `epoll`
- **macOS/FreeBSD** → 自動使用 `kqueue`
- **Windows** → 自動使用 `IOCP`

### **底層實現：**
- **Spring WebFlux** → Netty 自動選擇
- **Django ASGI** → uvicorn/daphne 自動選擇
- **Node.js** → libuv 自動選擇

## 事件迴圈 vs 框架：誰是誰的「原住民」？

理解了 I/O 多工的技術後，讓我們來看看不同框架如何與事件迴圈共存。

### **Node.js：天生的事件迴圈原住民**

```javascript
// Node.js 從一開始就是事件驅動
const http = require('http');

const server = http.createServer((req, res) => {
  // 所有 async/await/Promise 最終都會變成 libuv callback
  someAsyncOperation().then(result => {
    res.end(result);
  });
});

server.listen(3000);
```

**核心特點：**
- **單執行緒 + libuv event loop**
- **所有 I/O 都是非阻塞的**
- **沒有「傳統阻塞模式」的選擇**
- **JS 世界裡一切都是 callback → event loop → callback**

### **☕ Spring Boot：雙重人格的框架**

#### **人格一：傳統 MVC（阻塞模式）**
```java
@RestController
public class TraditionalController {
    @GetMapping("/sync")
    public String syncEndpoint() {
        // Thread 會在這裡卡住等待 I/O
        return blockingDatabaseCall(); // ❌ 阻塞 I/O
    }
}
```

#### **人格二：WebFlux（事件迴圈模式）**
```java
@RestController
public class ReactiveController {
    @GetMapping("/reactive")
    public Mono<String> reactiveEndpoint() {
        // 不會卡住 thread，event loop 繼續處理其他請求
        return reactiveDatabaseCall(); // ✅ 非阻塞 I/O
    }
}
```

**核心差異：**
- **MVC**：Thread Pool + 阻塞 I/O（1 萬連線 = 1 萬 thread）
- **WebFlux**：Netty + 事件迴圈（1 萬連線 = 幾十個 thread）

### **Python：WSGI vs ASGI 的世代差異**

#### **傳統 WSGI（阻塞模式）**
```python
# Flask/Django 傳統模式
from flask import Flask
app = Flask(__name__)

@app.route('/')
def hello():
    return blocking_database_call()  # ❌ 阻塞 I/O
```

#### **現代 ASGI（事件迴圈模式）**
```python
# FastAPI/Django Channels
from fastapi import FastAPI
app = FastAPI()

@app.get('/')
async def hello():
    return await async_database_call()  # ✅ 非阻塞 I/O
```

**核心差異：**
- **WSGI**：同步阻塞，thread-per-request
- **ASGI**：async/await + uvloop 事件迴圈

### **為什麼 Java/Python 不做「原生事件迴圈」？**

#### **1️⃣ 語言設計的歷史包袱**
- **Java**：從 JDK 1.0 就定位「多執行緒 + JVM」，Thread/synchronized 是核心
- **Python**：GIL + CPython 的設計，讓多執行緒一直很尷尬
- **JavaScript**：從誕生就沒有多執行緒包袱，直接事件迴圈為核心

#### **2️⃣ 生態系統的向後相容**
- **舊程式碼太多**：如果強制轉事件迴圈，數百萬行的同步程式要重寫
- **函式庫相容**：Hibernate、MyBatis、Django ORM 等同步庫無法直接跑在 async 模式
- **漸進式遷移**：Java/Python 選擇「並存」策略，讓開發者慢慢轉移

#### **3️⃣ 開發體驗的差異**
- **同步程式碼**：寫起來簡單，直覺
- **非同步程式碼**：callback hell、async/await 複雜度較高
- **除錯困難**：事件迴圈的 stack trace 很難追蹤

### **框架對比表：誰跑在事件迴圈上？**

| 框架 | 模式 | 底層技術 | 連線處理方式 | 是否事件迴圈 |
|------|------|----------|--------------|---------------|
| **Node.js** | 單一模式 | libuv + epoll/kqueue/IOCP | 單執行緒管理所有 | ✅ 原生 |
| **Spring MVC** | 傳統 | Tomcat/Jetty + Thread Pool | Thread-per-request | ❌ 阻塞 |
| **Spring WebFlux** | 現代 | Netty + 事件迴圈 | 少量 thread 管理大量連線 | ✅ 現代 |
| **Django WSGI** | 傳統 | Gunicorn + Thread Pool | Thread-per-request | ❌ 阻塞 |
| **Django ASGI** | 現代 | uvicorn/daphne + uvloop | 事件迴圈 + 多 worker | ✅ 現代 |
| **FastAPI** | 現代 | uvicorn + uvloop | 事件迴圈 | ✅ 現代 |

### **模式對比表：事件迴圈 vs 傳統同步 vs 消息隊列**

| 模式                   | I/O 模型                             | 任務排程 / Producer-Consumer      | CPU 密集                         | Memory 使用                  | 適合場景                  | 面試說法                          |
| -------------------- | ---------------------------------- | ----------------------------- | ------------------------------ | -------------------------- | --------------------- | ----------------------------- |
| **事件迴圈 + 消息隊列**      | 非阻塞 async / coroutine / event loop | Broker 實現可靠 Producer/Consumer | CPU 密集任務丟 thread pool / worker | 少量 thread + memory 省       | 高併發 API + 分布式任務       | 「高併發 I/O + 可擴展事件驅動架構」         |
| **傳統同步 + 消息隊列**      | 每個請求一個 thread，阻塞 I/O               | Broker 實現可靠 Producer/Consumer | CPU 密集直接在 thread 執行            | 每個請求占用一個 thread → memory 貴 | 分布式任務、企業後端            | 「同步 I/O + EDA，容易理解但 memory 貴」 |
| **事件迴圈（單純內存 queue）** | 非阻塞 async / coroutine / event loop | 內存 queue 管理任務，僅進程內有效          | CPU 密集需多事件迴圈或 thread pool      | 少量 thread，memory 省         | I/O 密集、單進程 / 單 worker | 「事件驅動但不算完整 EDA，適合高併發輕量任務」     |

### **事件迴圈的局限性：為什麼 Node.js 不是後端主流？**

儘管事件迴圈很強大，但它也有天生限制：

#### **1️⃣ CPU 密集任務的痛點**
```javascript
// 這個運算會卡住整個 event loop！
app.get('/heavy-calculation', (req, res) => {
  for(let i = 0; i < 1000000000; i++) {
    // 重運算... 會讓其他請求延遲！
  }
  res.send('Done');
});
```

**解決方案：**
- 丟到 C++ addon
- 用 Worker Threads
- 分散到其他微服務

#### **2️⃣ 單執行緒的極限**
- **記憶體洩漏**：一個 bug 就可能讓整個應用崩潰
- **錯誤處理**：uncaughtException 會終止整個 process
- **擴展性**：很難充分利用多核心 CPU

### **結論：事件迴圈是未來的趨勢，但不是唯一解**

1. **WebFlux/ASGI/Node.js**：事件迴圈為核心，適合 I/O 密集應用
2. **傳統 MVC/WSGI**：Thread Pool 為核心，適合 CPU 密集或簡單應用
3. **混合部署**：用傳統框架處理簡單請求，用事件迴圈框架處理高併發

**關鍵洞察：** 事件迴圈不是銀彈，它解決了 I/O 阻塞的問題，但帶來了程式設計複雜度的提升。選擇框架時，要根據你的應用特性來決定！

## 傳統世界 vs 新世界

### **傳統世界：Spring MVC、Django WSGI**

```java
// Spring MVC：一個請求 = 一個 thread
@RestController
public class TraditionalController {
    @GetMapping("/sync")
    public String syncEndpoint() {
        // Thread 會在這裡卡住等待 I/O
        return blockingDatabaseCall();
    }
}
```

**特點：**
- **阻塞式、thread-per-request** 設計
- Thread 在等待資料時直接卡住
- 底層可能還在用 select()/poll()
- 人一多 thread 就爆掉

**比喻：** 「來了一個客人，派一個專屬服務生，服務生要等廚房上菜，就只能乾等，不能去做別的事。」

### **新世界：Spring WebFlux、Django ASGI**

```java
// Spring WebFlux：一個 thread 管理所有請求
@RestController
public class ReactiveController {
    @GetMapping("/reactive")
    public Mono<String> reactiveEndpoint() {
        // 不會卡住 thread，event loop 繼續處理其他請求
        return r2dbcTemplate.queryForObject("SELECT * FROM users", String.class);
    }
}
```

**特點：**
- **非阻塞 + event loop** 設計
- Thread 不會傻傻地卡住
- 用 epoll/kqueue/IOCP 由 OS 幫忙監聽
- 一個 thread 可以管理成千上萬請求

**比喻：** 「只有一個超強管家，他不用每天數學生，而是學生有事自己舉手。」

## 對應表

| OS 聽電話方式 | Spring Boot/Django 傳統版 | Spring Boot/Django 非阻塞版 |
|---------------|---------------------------|-----------------------------|
| **select/poll（傻傻掃）** | Spring MVC (Tomcat 傳統 blocking I/O)<br/>Django WSGI (Gunicorn + sync workers) | 幾乎不用（效率太差） |
| **epoll (Linux)** | 傳統 thread pool 還是阻塞 | **Spring WebFlux** (Netty on Linux)<br/>**Django ASGI** (uvicorn/daphne) |
| **kqueue (macOS/FreeBSD)** | 同上 | **Spring WebFlux** (Netty on macOS)<br/>**Django ASGI** (uvicorn on macOS) |
| **IOCP (Windows)** | 同上 | **Spring WebFlux** (Netty on Windows)<br/>**Django ASGI** (uvicorn on Windows) |

## 總結

### **核心技術演進：**
1. **石器時代**：select() - 一個一個檢查，效率低下
2. **青銅時代**：poll() - 小幅改善，仍有瓶頸
3. **資訊時代**：epoll/kqueue/IOCP - OS 主動通知，效能爆發

### **現代 Web 框架的秘密：**
- **傳統框架**：thread-per-request，靠數量取勝
- **現代框架**：event loop + I/O 多工，靠智慧取勝

### **實戰建議：**
- **新專案**：優先考慮 Spring WebFlux / Django ASGI
- **舊專案**：評估遷移成本 vs 效能收益
- **混合部署**：傳統框架處理簡單請求，現代框架處理高併發

**理解 I/O 多工，就是理解現代 Web 架構的精髓！** 