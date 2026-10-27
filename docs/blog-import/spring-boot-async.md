---
title: "spring-boot-async"
publishDate: "2025-08-26 01:00:00"
img: "/tymultiverse/assets/java.jpg"
img_alt: "A bright pink sheet of paper used to wrap flowers curves in front of rich blue background"
description: "Spring Boot 非同步處理深度解析：從 @Async 到 WebFlux 的完整指南"
level: advance
category: Spring Boot
tags: ["Spring Boot", "Java", "Async", "Reactive", "WebFlux", "Netty"]
---

# Spring Boot 非同步處理深度解析

## 概述

Spring Boot 的非同步處理主要有兩大模式，底層 I/O 模型完全不同：

### **模式一：同步 I/O + Thread Pool**
- **代表技術：** Spring MVC + @Async + Tomcat
- **本質：** 傳統阻塞 I/O，透過 Thread Pool 模擬非同步
- **適用：** 傳統企業應用，開發簡單但資源利用率有限

### **模式二：原生非阻塞 Async**
- **代表技術：** WebFlux + Netty + Reactive Streams
- **本質：** 真正的非阻塞 I/O + Event Loop
- **適用：** 高併發應用，資源利用率極高但學習成本較大

本文將深入比較這兩種模式的差異，協助你選擇最適合的非同步處理方案。

## 底層 I/O 模型差異：為什麼「一個 loop 可以管理成千上萬 socket」？

### **傳統 Blocking I/O（同步邏輯）**

**OS 只提供「執行」功能：**
```
呼叫 read(socket) → 如果沒資料，Thread 直接卡住等待 → 有資料才回傳
```

**結果：**
- **1 萬個連線 = 1 萬個 Thread**
- 每個 Thread：Stack memory（~1MB）+ Context switching overhead
- Thread 數量爆炸 → 效能崩潰

### **I/O Multiplexing（非阻塞邏輯）**

**OS 提供「監控服務」：**
```
應用程式：「OS，幫我監控這 10,000 個 socket，誰有資料就通知我」
OS kernel：「好，我用 epoll/kqueue 幫你盯著」
（某些 socket 有資料時）
OS kernel：「第 53、892、4999 個 socket 準備好了」
Event Loop：「收到，處理這 3 個 socket 的 callback」
```

**核心技術：**
- **Linux**: `epoll()` - 高效率 O(1) 事件通知
- **BSD/Mac**: `kqueue()` - 類似 epoll 的事件機制  
- **Windows**: `IOCP` - I/O Completion Port

**結果：**
- **1 萬個連線 = 1 個 Event Loop Thread**
- Thread 只在「事件發生時」才處理，不會阻塞等待
- 沒有 Thread 爆炸問題

### **關鍵差異**

| 模式 | OS 角色 | Thread 用量 | 效率 |
|------|---------|-------------|------|
| **Blocking I/O** | 只執行讀寫 | 每連線 1 個 | O(n) Thread |
| **I/O Multiplexing** | 監控 + 批次通知 | 共用 1 個 | O(1) Thread |

**比喻：** 傳統模式像「每個客戶配一個專員」，非阻塞模式像「一個總機接聽所有來電，有事才轉接」。

## Spring Boot 非同步處理的深度解析

Spring Boot 支援多種非同步處理方式，每種都有不同的底層機制和適用場景：

### **模式一：Spring MVC + Tomcat + @Async**

**底層機制：** Servlet API（Blocking I/O）+ Thread Pool

```java
@RestController
public class AsyncController {
    @Async
    @GetMapping("/async")
    public CompletableFuture<String> asyncEndpoint() {
        return CompletableFuture.supplyAsync(() -> {
            // Thread Pool 中的 worker thread 執行同步 I/O
            return blockingDatabaseCall();
        });
    }
}
```

**核心特徵：**
- **Thread-per-request 模式**：每個請求綁定一條 thread
- **Thread Pool 切換**：使用 `@Async` 將工作轉移到 worker thread
- **本質**：同步阻塞 I/O + Thread Pool 模擬非同步
- **限制**：worker thread 仍會阻塞，無法充分利用系統資源

### **模式二：Spring WebFlux + Netty**

**底層機制：** Event Loop + 非阻塞 I/O + Reactive Streams

```java
@RestController
public class ReactiveController {
    private final WebClient webClient;

    public ReactiveController(WebClient webClient) {
        this.webClient = webClient;
    }

    @GetMapping("/reactive")
    public Mono<String> reactiveEndpoint() {
        return webClient.get()
            .uri("https://api.example.com/data")
            .retrieve()
            .bodyToMono(String.class);
        // 整個 pipeline 都是非阻塞的
    }
}
```

**核心特徵：**
- **Event Loop 模式**：單一 thread 處理成千上萬連線
- **真正的非阻塞 I/O**：搭配 R2DBC、WebClient 等非阻塞 driver
- **Reactive Pipeline**：使用 Mono/Flux 建構非阻塞處理鏈
- **資源效率**：一個 event loop thread 可處理數千連線

### **Driver 層級的 Socket 使用差異**

**同步 Driver（JDBC、psycopg2）：**
```
socket.send(SQL) → socket.recv() 阻塞等待 → Thread 卡住直到 DB 回應
```
- **問題：** 每個 DB 查詢都佔用一個 Thread

**非同步 Driver（R2DBC、asyncpg）：**
```
socket.send(SQL) → 註冊到 epoll → Event Loop 監聽
DB 回應 → OS 通知 Event Loop → 執行 callback → 處理結果
```
- **優勢：** 一個 Event Loop Thread 處理成千上萬 DB 連線

## ❓ 「真正非阻塞」vs「Thread Pool 模擬」

### **@Async：Thread Pool 切換（偽非阻塞）**
```java
@Async
@GetMapping("/async")
public CompletableFuture<String> async() {
    return CompletableFuture.supplyAsync(() ->
        jdbcTemplate.queryForObject(sql, String.class)  // 同步 JDBC，Thread 仍阻塞
    );
}
```
**本質：** Servlet Thread → Worker Thread，但 Worker Thread 還是會在 `socket.recv()` 阻塞

### **WebFlux：Event Loop（真正非阻塞）**
```java
@GetMapping("/reactive")
public Mono<String> reactive() {
    return r2dbcTemplate.queryForObject(sql, String.class);  // 非阻塞 R2DBC
}
```
**本質：** Event Loop Thread 發出 SQL → 註冊 epoll → 立即處理其他請求 → DB 回應時才執行 callback

## 完整技術對照表

| 技術棧 | I/O 模型 | 執行模式 | Thread 用量 | 併發能力 | 適用場景 |
|--------|----------|----------|-------------|----------|----------|
| **Tomcat + JDBC** | Blocking I/O | Thread-per-request | 高（1:1） | 低 | 傳統應用 |
| **Tomcat + @Async** | Blocking I/O | Thread Pool | 中等 | 中等 | 企業應用 |
| **WebFlux + Netty** | Non-blocking I/O | Event Loop | 極低 | 極高 | 高併發服務 |

## 架構選擇指南

### **選擇 Tomcat + @Async 的時機**
- 傳統企業應用
- 有大量現成同步程式碼
- 開發周期要求較短
- 併發需求不高

### **選擇 WebFlux + Netty 的時機**
- 高併發應用（數千+併發）
- 即時資料處理
- 微服務架構
- 需要最大化資源利用

## 效能實戰：同步 vs 非同步的真實對比

讓我們用實際數據來說話，看看在真實場景中，同步處理器和非同步處理器的表現差異。

### 測試場景說明

**測試環境：**
- 每個請求都需要 2 秒的長時間運算（模擬真實業務邏輯）
- 使用 OkHttp 客戶端，預設 10 秒 timeout
- 分別測試 Java 8 和 Java 12 環境

### 同步處理器（Synchronous Handler）的表現

從測試數據可以發現：

**小規模請求（200 個以內）：**
- 平均回應時間都在 2.5 秒內，表現穩定
- 系統資源充足，每個請求都能及時處理

**中規模請求（400 個）：**
- 回應時間明顯拉長，最大值達到 4.2 秒，平均約 3.4 秒
- 系統開始出現資源爭奪現象

**大規模請求（2000 個）：**
- 近半請求因為超過 10 秒沒有回應而失敗
- 系統完全不堪負荷，資源耗盡

有趣的是，即使是先執行的請求，也不見得佔到優勢。在 400 個和 800 個請求的測試中，即使先啟動的請求，回應時間也可能超過 4 秒。這種現象顯示，在資源爭奪戰中，「先到先得」的優勢並不明顯。

**結論：** 在這個配置下，Spring MVC 大概能應付 800 個並發請求而不會有 timeout 問題，超過這個量就很危險了。

### 非同步處理器（Asynchronous Handler）的表現

換上非同步處理器後，結果卻出人意料：

**Java 8 環境：**
- 即使是 2000 個請求，平均時間只拉長到 6.2 秒
- 沒有任何 timeout，全部請求都成功完成
- 表現超乎預期地好

**Java 12 環境：**
- 表現卻非常糟糕，即使請求超過 20 個，成功數量都只有 12 個
- 比同步處理器還要差

### 背後的關鍵差異：Worker Threads 數量

觀察數據可以發現，主要差異在於 **worker threads 的數量**：

**Java 12 環境的問題：**
- worker threads 最多只有 3 個
- 所有請求都被排隊在這 3 個 worker 身上
- 即使 asynchronous handler 很快回傳 `CompletableFuture`，executor threads 的增加速度也放緩，但回應時間仍然降不下來

**Java 8 環境的優勢：**
- worker threads 數量是請求的兩倍（因為 `countAsync` 和 `saveAsync` 各建立一個 thread）
- 執行完後，worker threads 也很快降到 0
- 回應時間表現明顯優於 Java 12

### 淺顯易懂的整合說法

簡單來說：

**同步處理器就像傳統餐廳：**
- 每個客人來都要配一個專屬服務生
- 服務生要等廚房做好菜才能離開
- 客人一多，服務生就不夠用了

**非同步處理器就像現代速食店：**
- 點餐員只負責點餐，馬上就有空
- 廚房分工處理（countAsync、saveAsync 等）
- 但關鍵在於「廚房工人數量」決定一切

Java 8 能自動開足夠的廚房工人，Java 12 卻很保守，只開 3 個工人。所以 Java 8 的非同步表現超好，Java 12 反而比同步還差。

**實戰建議：**
- 如果你的應用需要處理大量並發請求，別只看理論，先實際測試不同 JDK 版本的表現
- Worker threads 的數量往往是效能瓶頸的關鍵
- 效能測試比架構辯論更重要

## 快速配置

**WebFlux 配置：**
```java
@Configuration
public class WebFluxConfig {
    @Bean
    public WebClient webClient() {
        return WebClient.builder().build();
    }
}
```

**@Async 配置：**
```java
@Configuration
@EnableAsync
public class AsyncConfig {
    @Bean
    public Executor taskExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(4);
        executor.setMaxPoolSize(8);
        executor.setQueueCapacity(100);
        executor.initialize();
        return executor;
    }
}
```

## 總結

### **核心技術演進**
1. **Blocking I/O 時代**：OS 只提供「執行讀寫」→ Thread 爆炸問題
2. **I/O Multiplexing 時代**：OS 提供「監控 + 批次通知」→ Event Loop 解決方案
3. **Spring Boot 實踐**：從 @Async（Thread Pool 模擬）到 WebFlux（真正非阻塞）

### **選擇建議**
- **傳統場景**：Tomcat + @Async（開發簡單）
- **高併發場景**：WebFlux + Netty（資源效率極致）

## 小測驗：Spring Framework 的執行緒謎題

來個小測驗：Spring framework 在呼叫 `startAsync()` 後，讓 request handler 在別的 thread 執行，但執行完後，將結果 serialize 寫入 response 這件事是在哪個 thread 執行呢？

**提示：** 仔細思考 Spring MVC 的執行流程...

### 答案揭曉

答案是：**在原來的 Servlet Thread 中執行**！

為什麼？因為 `startAsync()` 會將當前請求標記為非同步，但 **response 物件仍然綁定在原來的 Servlet Thread**。當非同步任務完成後，Spring 會：

1. 在 worker thread 中完成業務邏輯
2. 切換回原來的 Servlet Thread 來寫入 response
3. 確保 thread safety 和 Servlet 規範的相容性

這就是為什麼即使使用 `@Async`，最終的 response 寫入仍然在 Servlet Thread 中進行的原因。

## 補充：非同步「Wrap」的實現機制

### 「Wrap」的核心概念

「Wrap」的實現，也就是將一個同步（synchronous）方法轉換成非同步（asynchronous）的過程，主要是透過 Java 的 `CompletableFuture` 來完成。

### 執行位置：Service Layer

這個轉換通常在**服務層（Service Layer）**或任何需要呼叫耗時操作的地方執行。

#### 原始同步方法（Repository 層）

```java
// 這是一個假設的同步方法
public User getUserFromDatabase(long userId) {
    // 這裡的程式碼會阻塞，直到查詢完成
    // 假設需要 2 秒鐘
    Thread.sleep(2000);
    return new User("John Doe");
}
```

#### 非同步包裝（Service 層）

```java
@Service
public class UserService {

    @Autowired
    private UserRepository userRepository;

    // 在 Service 層中執行包裝
    public CompletableFuture<User> findUser(long userId) {
        // 使用 CompletableFuture.supplyAsync 將同步方法包裝成非同步任務
        return CompletableFuture.supplyAsync(() -> {
            // 這個 lambda 運算式會在一個獨立的執行緒中執行
            return userRepository.getUserFromDatabase(userId);
        });
    }
}
```

### 執行時機：Runtime（執行時期）

這個「包裝」是在**執行時期（Runtime）**進行的：

1. **立即回傳**：當 `findUser()` 方法被呼叫時，它不會直接執行耗時的資料庫查詢
2. **建立承諾**：而是會立即向呼叫者回傳一個 `CompletableFuture<User>` 物件
3. **非同步執行**：這個 `CompletableFuture` 代表著一個「未來會得到使用者物件」的承諾
4. **背景處理**：實際的資料庫查詢會在 worker thread 中非同步執行

### Controller 中的使用方式

```java
@RestController
public class UserController {

    @Autowired
    private UserService userService;

    @Async  // 使用 @Async 讓整個 handler 在 worker thread 中執行
    @GetMapping("/api/user/{id}")
    public CompletableFuture<ResponseEntity<User>> getUser(@PathVariable Long id) {
        return userService.findUser(id)
            .thenApply(user -> ResponseEntity.ok(user))
            .exceptionally(ex -> ResponseEntity.notFound().build());
    }
}
```

### 關鍵理解點

1. **包裝位置**：在 Service 層進行同步到非同步的轉換
2. **執行時機**：Runtime，非同步建立和執行
3. **Thread 切換**：`@Async` 讓整個 handler 在 worker thread 中執行
4. **Response 寫入**：最終 serialize 回 Servlet Thread 完成

這種設計讓您能夠：
- 保留現有的同步業務邏輯
- 獲得非同步處理的效能優勢
- 保持程式碼的可維護性和清晰度

**關鍵：** 理解 OS 層級的 I/O 模型差異，才能真正掌握非同步處理的精髓！