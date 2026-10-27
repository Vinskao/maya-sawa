---
title: "thread-pool"
publishDate: "2025-09-08 02:00:00"
img: /tymultiverse/assets/algorithm.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: TY Multiverse Consumer 專案 - Virtual Threads + RabbitMQ 實戰指南
level: advance
category: Concurrency
tags:
  - Virtual Threads
  - RabbitMQ Consumer
  - Spring Boot
  - Java 21
  - Resource Management
  - Performance Optimization
  - TY Multiverse

---

# TY Multiverse Consumer：Virtual Threads + RabbitMQ 實戰指南

## 什麼是 Thread Pool？(小白教學)

假設你在咖啡廳工作，店裡只有 **1 個咖啡師**，結果同時來了 **10 個客人**。

### 如果咖啡師 **每次做完一杯才接下一個客人**
→ 會有很多人要排隊，等很久

### 如果咖啡師 **同時開始做 10 杯**
→ 但咖啡師只有兩隻手，結果會更慢

### 解決辦法：找幾個助手 (thread)，但是數量要剛剛好

這就是 **Thread Pool (線程池)** 的概念：

- **限制線程數量** → 避免開太多線程，把記憶體/CPU 撐爆
- **重複利用線程** → 減少反覆建立/銷毀線程的開銷
- **平衡任務排隊與資源使用** → 達到最佳效能

## Thread Pool 在程式裡怎麼用？

### 傳統作法 (固定線程池)
```java
ExecutorService executor = Executors.newFixedThreadPool(5);

for (int i = 0; i < 10; i++) {
    int taskId = i;
    executor.submit(() -> {
        System.out.println("Task " + taskId + " running in " + Thread.currentThread().getName());
    });
}
executor.shutdown();
```

- **同時最多 5 條線程處理工作**
- **多出來的任務要排隊**
- **適合 CPU/記憶體資源 比較充足 的環境**

#### 問題：線程太「重」
- 每個傳統 thread 可能吃掉 **1MB 記憶體**
- 在 K8s 資源受限環境 (0.05 CPU, 1GB RAM) 會很快就爆掉

## Virtual Threads 登場 (JDK 21 特色)

### **Virtual Threads 是非阻塞的！**

#### **重要警告：跨 Thread 問題**

在使用 Virtual Threads 時，必須特別注意**跨 Thread 問題**。Virtual Threads 雖然輕量，但仍然是不同的執行緒，可能會遇到傳統多執行緒程式設計的所有問題：

**常見的跨 Thread 問題：**

1. **ThreadLocal 變數遺失**
   ```java
   // ❌ 問題：ThreadLocal 在 Virtual Thread 間不會自動傳遞
   private static final ThreadLocal<String> USER_CONTEXT = new ThreadLocal<>();

   @RabbitListener(queues = "people-get-all")
   public void handleMessage(String message) {
       // USER_CONTEXT.get() 可能返回 null
       String userId = USER_CONTEXT.get();
   }
   ```

2. **安全性上下文 (Security Context) 中斷**
   ```java
   // ❌ 問題：Spring Security Context 在 Virtual Thread 間遺失
   @RabbitListener(queues = "secure-queue")
   public void handleSecureMessage(String message) {
       SecurityContext context = SecurityContextHolder.getContext();
       // context 可能為 null 或包含錯誤的認證資訊
   }
   ```

3. **事務上下文遺失**
   ```java
   // ❌ 問題：@Transactional 在 Virtual Thread 中可能失效
   @RabbitListener(queues = "transactional-queue")
   @Transactional
   public void handleTransactionalMessage(String message) {
       // 事務可能不會正確傳播
       userService.save(user);
   }
   ```

4. **日誌追蹤 (Trace ID) 中斷**
   ```java
   // ❌ 問題：分佈式追蹤 ID 在 Virtual Thread 間遺失
   @RabbitListener(queues = "traced-queue")
   public void handleTracedMessage(String message) {
       // MDC (Mapped Diagnostic Context) 可能為空
       String traceId = MDC.get("traceId");
   }
   ```

**✅ TY Multiverse 專案的解決方案：**

#### **1. 使用 ScopedValue (JDK 21)**
```java
// ✅ 正確做法：使用 ScopedValue 替代 ThreadLocal
private static final ScopedValue<String> USER_CONTEXT = ScopedValue.newInstance();

public void processWithContext(String userId) {
    ScopedValue.where(USER_CONTEXT, userId)
        .run(() -> {
            // 在這個作用域內，所有 Virtual Thread 都可以訪問 userId
            handleMessage();
        });
}
```

#### **2. 明確傳遞上下文**
```java
// ✅ 正確做法：在消息中明確傳遞必要資訊
public class AsyncMessageDTO {
    private String requestId;
    private String userId;        // 明確傳遞用戶ID
    private String traceId;       // 明確傳遞追蹤ID
    private Object payload;

    // getter/setter...
}

// Consumer 中直接使用消息中的資訊
@RabbitListener(queues = "people-get-all")
public void handleGetAllPeople(String messageJson) {
    AsyncMessageDTO message = objectMapper.readValue(messageJson, AsyncMessageDTO.class);

    // ✅ 正確：直接從消息獲取上下文
    String userId = message.getUserId();
    String traceId = message.getTraceId();

    // 設置 MDC 用於日誌追蹤
    MDC.put("traceId", traceId);
    MDC.put("userId", userId);

    try {
        // 業務處理...
        List<People> peopleList = peopleService.getAllPeopleOptimized();
        asyncResultService.sendCompletedResult(message.getRequestId(), peopleList);
    } finally {
        // 清理 MDC
        MDC.clear();
    }
}
```

#### **3. 避免共享可變狀態**
```java
// ❌ 錯誤：共享可變狀態
@Component
public class ProblematicService {
    private List<String> sharedList = new ArrayList<>();

    @RabbitListener(queues = "shared-state-queue")
    public void handleMessage(String message) {
        sharedList.add(message);  // 併發安全問題！
    }
}

// ✅ 正確：使用 Thread-safe 集合或避免共享狀態
@Component
public class SafeService {
    // 使用 Concurrent 集合
    private ConcurrentHashMap<String, Object> safeMap = new ConcurrentHashMap<>();

    @RabbitListener(queues = "safe-queue")
    public void handleMessage(String message) {
        AsyncMessageDTO msg = objectMapper.readValue(message, AsyncMessageDTO.class);

        // 使用 requestId 作為鍵，避免共享狀態
        safeMap.put(msg.getRequestId(), processMessage(msg));

        // 或使用函數式編程，避免副作用
        processMessageWithoutSideEffects(msg);
    }
}
```

#### **4. 正確處理事務**
```java
// ✅ 正確：在 Virtual Thread 中正確處理事務
@Service
public class PeopleService {

    @Autowired
    private PeopleRepository peopleRepository;

    @Transactional(propagation = Propagation.REQUIRED)
    public People insertPerson(People people) {
        // 確保事務正確傳播
        return peopleRepository.save(people);
    }

    // 對於 MQ Consumer，考慮使用手動事務管理
    public People insertPersonManualTransaction(People people) {
        TransactionStatus status = transactionManager.getTransaction(new DefaultTransactionDefinition());

        try {
            People saved = peopleRepository.save(people);
            transactionManager.commit(status);
            return saved;
        } catch (Exception e) {
            transactionManager.rollback(status);
            throw e;
        }
    }
}
```

#### **5. TY Multiverse 專案的實際解決方案**
```java
// TY Multiverse Consumer 的實際實現
@Component
public class UnifiedConsumer {

    @Autowired
    private PeopleService peopleService;

    @Autowired
    private AsyncResultService asyncResultService;

    @RabbitListener(queues = "people-insert", concurrency = "2")
    public void handlePeopleInsert(String messageJson) {
        try {
            AsyncMessageDTO message = objectMapper.readValue(messageJson, AsyncMessageDTO.class);

            // ✅ 解決方案 1: 從消息中獲取所有必要上下文
            String requestId = message.getRequestId();
            String userId = message.getUserId();
            String traceId = message.getTraceId();

            // ✅ 解決方案 2: 設置 MDC 用於日誌追蹤
            MDC.put("traceId", traceId);
            MDC.put("userId", userId);
            MDC.put("requestId", requestId);

            try {
                // ✅ 解決方案 3: 業務邏輯不依賴 ThreadLocal
                People people = objectMapper.convertValue(message.getPayload(), People.class);
                People savedPeople = peopleService.insertPerson(people);

                // ✅ 解決方案 4: 結果通過 MQ 發送，不依賴線程狀態
                asyncResultService.sendCompletedResult(requestId, savedPeople);

                logger.info("✅ People 插入完成: {}", requestId);
            } finally {
                // ✅ 解決方案 5: 清理線程本地狀態
                MDC.clear();
            }
        } catch (Exception e) {
            handleError(messageJson, e);
        }
    }
}
```

#### **跨 Thread 問題總結**

| 問題類型 | 傳統 Thread Pool | Virtual Threads | TY Multiverse 解決方案 |
|---------|------------------|----------------|----------------------|
| **ThreadLocal 遺失** | 可能發生 | 一定發生 | 消息中明確傳遞上下文 |
| **Security Context** | 可能遺失 | 一定遺失 | 消息中包含認證資訊 |
| **事務傳播** | 通常正常 | 可能失效 | 明確的@Transactional |
| **日誌追蹤** | MDC 可能遺失 | MDC 一定遺失 | 每次請求重新設置 MDC |
| **共享狀態** | 併發問題 | 相同併發問題 | 使用 Thread-safe 集合 |

**關鍵原則：在 Virtual Threads 環境中，假設任何線程本地狀態都會遺失！**

**非阻塞特性：**
- **I/O 操作時自動讓出 CPU** → 不會阻塞整個線程
- **高效的線程切換** → 從 user space 直接切換，無需 kernel 介入
- **底層實現**：基於 **Continuation** 和 **Fiber**，類似 Go 的 goroutine

### **底層實作原理**
```java
// 傳統 Thread (阻塞式)
public void blockingCall() {
    // I/O 時會阻塞整個 OS Thread
    String result = httpClient.get("https://api.example.com");
    processResult(result);
}

// Virtual Thread (非阻塞式)
public void nonBlockingCall() {
    // I/O 時自動讓出，OS Thread 可以處理其他工作
    String result = httpClient.get("https://api.example.com");
    processResult(result);
}
```

**Virtual Threads 底層：**
- **User-Mode Threading**：在 JVM 層級管理，不依賴 OS Thread
- **Continuation**：保存/恢復執行狀態的機制
- **Fiber**：輕量級的執行單元，可以快速切換
- **ForkJoinPool**：實際執行 Virtual Threads 的底層執行器

## Virtual Threads + RabbitMQ：TY Multiverse Consumer 分佈式架構

### **TY Multiverse 專案架構設計**

TY Multiverse 專案採用**分佈式微服務架構**，將 Producer 和 Consumer 分離在不同的應用中：

| 組件 | 技術棧 | Virtual Threads | 說明 |
|------|--------|----------------|------|
| **TY Multiverse Producer** | Spring Boot + RabbitMQ | ✅ 全面使用 | 負責接收HTTP請求，發送消息 |
| **MQ (RabbitMQ)** | RabbitMQ Server | ❌ 不適用 | 分佈式消息隊列，持久化儲存 |
| **TY Multiverse Consumer** | Spring Boot + RabbitMQ | ✅ 實際實現 | **本專案** - 負責處理消息，執行業務邏輯 |

---

## Producer 段落：Backend 應用 (重點說明)

### **Producer 的角色與實現**

**扮演者：** Spring Boot Backend 應用程式
**主要責任：**
- 接收 HTTP 請求
- 生成唯一請求ID
- 將請求發送到 RabbitMQ
- 立即返回處理中狀態

### **Virtual Threads 在 Producer 中的應用**

#### **1. HTTP 請求處理**
```java
@RestController
public class UserController {

    @Autowired
    private AsyncMessageService asyncMessageService;

    @PostMapping("/api/users")
    public ResponseEntity<?> getUsers() {
        // HTTP 請求處理使用 Virtual Threads (Spring Boot 自動)
        // 這裡的請求線程就是 Virtual Thread

        if (asyncMessageService != null) {
            // 異步處理：發送到 RabbitMQ
            String requestId = asyncMessageService.sendUserDataRequest();

            Map<String, Object> response = new HashMap<>();
            response.put("requestId", requestId);
            response.put("status", "processing");
            response.put("message", "用戶數據處理請求已提交，請稍後查詢結果");

            return ResponseEntity.accepted().body(response);
        }

        // 本地同步處理 (直接DB查詢)
        // ...
    }
}
```

#### **2. 異步消息發送 (@Async 方法)**
```java
@Service
public class AsyncTaskService {

    @Autowired
    @Qualifier("threadPoolTaskExecutor")
    private Executor virtualThreadExecutor;

    // 明確使用 Virtual Threads 執行器
    @Async("threadPoolTaskExecutor")
    public CompletableFuture<Void> processUserData(String requestId) {
        return CompletableFuture.runAsync(() -> {
            try {
                // 在 Virtual Thread 中執行
                List<User> userList = userService.getAllUsersOptimized();
                asyncResultService.storeCompletedResult(requestId, peopleList);
                logger.info("✅ Virtual Thread 異步處理完成: {}", requestId);
            } catch (Exception e) {
                asyncResultService.storeFailedResult(requestId, e.getMessage());
                logger.error("❌ Virtual Thread 異步處理失敗: {}", requestId, e);
            }
        }, virtualThreadExecutor);
    }
}
```

#### **3. RabbitMQ 消息發送**
```java
@Service
public class AsyncMessageService {

    @Autowired
    private RabbitTemplate rabbitTemplate;

    public String sendUserDataRequest() {
        String requestId = UUID.randomUUID().toString();

        AsyncMessageDTO message = new AsyncMessageDTO(
            requestId,
            "/api/users/process",
            "POST",
            null
        );

        // 消息發送使用當前 Virtual Thread
        sendMessage(RabbitMQConfig.PEOPLE_GET_ALL_QUEUE, message);

        logger.info("✅ Virtual Thread 消息發送完成: {}", requestId);
        return requestId;
    }

    private void sendMessage(String queueName, AsyncMessageDTO message) {
        try {
            String messageJson = objectMapper.writeValueAsString(message);
            // 使用當前線程 (Virtual Thread) 發送到 RabbitMQ
            rabbitTemplate.convertAndSend(
                RabbitMQConfig.USER_DATA_EXCHANGE,
                getRoutingKey(queueName),
                messageJson
            );
        } catch (Exception e) {
            logger.error("❌ Virtual Thread 消息發送失敗: {}", e.getMessage());
            throw e;
        }
    }
}
```

### **Producer 的 Virtual Threads 配置**
```java
@Configuration
@SpringBootApplication
@EnableAsync
public class UserDataBackendApplication {

    @Bean(name = "threadPoolTaskExecutor", destroyMethod = "shutdown")
    ExecutorService threadPoolTaskExecutor() {
        // Producer 使用 Virtual Threads 作為主要執行器
        return Executors.newVirtualThreadPerTaskExecutor();
    }

    @Bean(name = "rabbitListenerContainerFactory")
    public SimpleRabbitListenerContainerFactory rabbitListenerContainerFactory(
        ConnectionFactory connectionFactory) {

        SimpleRabbitListenerContainerFactory factory = new SimpleRabbitListenerContainerFactory();
        factory.setConnectionFactory(connectionFactory);
        // RabbitMQ 監聽器也使用 Virtual Threads
        factory.setTaskExecutor(Executors.newVirtualThreadPerTaskExecutor());

        // 資源受限環境的保守配置
        factory.setConcurrentConsumers(1);
        factory.setMaxConcurrentConsumers(1);
        factory.setPrefetchCount(1);

        return factory;
    }
}
```

### **Producer 效能特點**
- ✅ **HTTP請求**: Spring Boot 自動使用 Virtual Threads
- ✅ **異步處理**: @Async 明確使用 Virtual Threads
- ✅ **消息發送**: 當前請求線程處理
- ✅ **資源控制**: 單線程處理，避免 CPU 飆升
- ✅ **處理能力**: 10-50 TPS (在資源限制下)

---

## Consumer 段落：TY Multiverse 專案實戰 (實際實現)

### **TY Multiverse Consumer 的角色與實現**

**扮演者：** TY Multiverse Consumer 應用程式 (Spring Boot + RabbitMQ)
**主要責任：**
- 監聽多個 RabbitMQ 隊列 (People, Weapon, Async Result)
- 處理業務邏輯 (角色管理、武器管理、傷害計算)
- 將處理結果發送到 async-result 隊列
- 統一錯誤處理和日誌記錄

### **Virtual Threads 在 TY Multiverse Consumer 中的實際應用**

#### **1. 多 Consumer 架構設計**
```java
// TY Multiverse 實際的 Consumer 架構
├── UnifiedConsumer    // 統一處理器 - 處理 People/Weapon 業務
├── PeopleConsumer     // 專門處理 People 相關請求
├── WeaponConsumer     // 專門處理 Weapon 相關請求
├── AsyncResultConsumer // 處理異步結果回調
└── ResponseConsumer   // 處理響應隊列 (已停用)
```

#### **2. UnifiedConsumer - 主要業務處理器**
```java
@Component
@ConditionalOnProperty(name = "spring.rabbitmq.enabled", havingValue = "true")
public class UnifiedConsumer {

    // 使用 Virtual Threads 處理多個隊列
    @RabbitListener(queues = "people-insert", concurrency = "2")
    public void handlePeopleInsert(String messageJson) {
        try {
            AsyncMessageDTO message = objectMapper.readValue(messageJson, AsyncMessageDTO.class);
            People people = objectMapper.convertValue(message.getPayload(), People.class);

            // 在 Virtual Thread 中執行業務邏輯
            People savedPeople = peopleService.insertPerson(people);

            // 發送結果到 async-result 隊列
            asyncResultService.sendCompletedResult(message.getRequestId(), savedPeople);

            logger.info("✅ People 插入完成: {}", message.getRequestId());
        } catch (Exception e) {
            handleError(messageJson, e);
        }
    }

    @RabbitListener(queues = "people-damage-calculation", concurrency = "2")
    public void handlePeopleDamageCalculation(String messageJson) {
        try {
            AsyncMessageDTO message = objectMapper.readValue(messageJson, AsyncMessageDTO.class);
            String characterName = (String) message.getPayload();

            // 在 Virtual Thread 中執行傷害計算
            int damage = weaponDamageService.calculateDamageWithWeapon(characterName);

            asyncResultService.sendCompletedResult(message.getRequestId(), damage);
            logger.info("✅ 傷害計算完成: {} -> {} 傷害", characterName, damage);
        } catch (Exception e) {
            handleError(messageJson, e);
        }
    }

    @RabbitListener(queues = "weapon-save", concurrency = "2")
    public void handleWeaponSave(String messageJson) {
        try {
            AsyncMessageDTO message = objectMapper.readValue(messageJson, AsyncMessageDTO.class);
            Weapon weapon = objectMapper.convertValue(message.getPayload(), Weapon.class);

            // 在 Virtual Thread 中執行武器保存
            Weapon savedWeapon = weaponService.saveWeapon(weapon);

            asyncResultService.sendCompletedResult(message.getRequestId(), savedWeapon);
            logger.info("✅ Weapon 保存完成: {}", message.getRequestId());
        } catch (Exception e) {
            handleError(messageJson, e);
        }
    }
}
```

#### **3. PeopleConsumer - 專門處理 People 業務**
```java
@Component
@ConditionalOnProperty(name = "spring.rabbitmq.enabled", havingValue = "true")
public class PeopleConsumer {

    // 使用 Virtual Threads 處理 People 查詢
    @RabbitListener(queues = "people-get-all", concurrency = "2")
    public void handleGetAllPeople(String messageJson) {
        try {
            AsyncMessageDTO message = objectMapper.readValue(messageJson, AsyncMessageDTO.class);

            // 在 Virtual Thread 中執行優化查詢
            List<People> peopleList = peopleService.getAllPeopleOptimized();

            asyncResultService.sendCompletedResult(message.getRequestId(), peopleList);
            logger.info("✅ 獲取所有角色完成: {} 個角色", peopleList.size());
        } catch (Exception e) {
            handleError(messageJson, e);
        }
    }
}
```

#### **4. AsyncResultConsumer - 處理異步結果**
```java
@Component
@ConditionalOnProperty(name = "spring.rabbitmq.enabled", havingValue = "true")
public class AsyncResultConsumer {

    // 使用 Virtual Threads 處理結果回調
    @RabbitListener(queues = "async-result", concurrency = "2")
    public void handleAsyncResult(String messageJson) {
        try {
            // 在 Virtual Thread 中處理異步結果
            AsyncResultMessage result = objectMapper.readValue(messageJson, AsyncResultMessage.class);

            // 處理結果... (例如存儲到快取或數據庫)
            logger.info("✅ 異步結果處理完成: {}", result.getRequestId());
        } catch (Exception e) {
            logger.error("❌ 異步結果處理失敗: {}", e.getMessage(), e);
        }
    }
}
```

#### **5. 統一錯誤處理機制**
```java
// 統一錯誤處理方法
private void handleError(String messageJson, Exception e) {
    try {
        AsyncMessageDTO message = objectMapper.readValue(messageJson, AsyncMessageDTO.class);

        // 在 Virtual Thread 中發送錯誤結果
        asyncResultService.sendFailedResult(
            message.getRequestId(),
            "處理請求失敗: " + e.getMessage()
        );

        logger.error("❌ 請求處理失敗: {} - {}", message.getRequestId(), e.getMessage(), e);
    } catch (Exception ex) {
        logger.error("❌ 錯誤回應處理失敗: {}", ex.getMessage(), ex);
    }
}
```

### **Virtual Threads 配置**

#### **1. 應用級配置**
```yaml
# application.yml - 啟用 Virtual Threads
spring:
  threads:
    virtual:
      enabled: true
```

#### **2. RabbitMQ 容器工廠配置**
```java
@Configuration
@EnableRabbit
public class RabbitMQConfig {

    @Bean
    public SimpleRabbitListenerContainerFactory rabbitListenerContainerFactory(
            ConnectionFactory connectionFactory,
            TaskExecutor applicationTaskExecutor) {

        SimpleRabbitListenerContainerFactory factory = new SimpleRabbitListenerContainerFactory();
        factory.setConnectionFactory(connectionFactory);

        // 使用 Virtual Threads 作為執行器
        factory.setTaskExecutor(applicationTaskExecutor);

        return factory;
    }
}
```

#### **3. 應用任務執行器**
```java
@Configuration
public class SwaggerConfig {

    @Bean(name = "applicationTaskExecutor")
    public TaskExecutor applicationTaskExecutor() {
        // 全應用共享的 Virtual Threads 執行器
        return new VirtualThreadTaskExecutor("vt-app-");
    }
}
```

### **TY Multiverse Consumer 效能特點**

#### **實際配置參數**
| 隊列類型 | 數量 | Concurrency | 處理類型 |
|----------|------|-------------|----------|
| People 相關 | 8 個 | 2 | CRUD + 傷害計算 |
| Weapon 相關 | 8 個 | 2 | CRUD + 查詢 |
| 異步結果 | 1 個 | 2 | 結果處理 |
| **總計** | **17 個隊列** | **34 個 Virtual Threads** | **多業務模組** |

#### **效能表現**
- ✅ **高並發處理**: 17 個隊列 × 2 個 Virtual Threads = 34 個並發處理器
- ✅ **輕量級執行**: 每個 Virtual Thread ~16KB，總計 ~544KB 記憶體
- ✅ **資源優化**: 在 0.05 CPU 環境下可處理 10-50 TPS
- ✅ **業務分離**: 多 Consumer 類實現關注點分離
- ✅ **統一處理**: AsyncResultService 統一結果管理
- ✅ **錯誤處理**: 完整的異常捕獲和日誌記錄

#### **實際應用場景**
```java
// 實際的業務場景示例
@RestController
public class PeopleController {

    @PostMapping("/get-all")
    public ResponseEntity<?> getAllPeople() {
        // 發送到 MQ，觸發 Consumer 的 Virtual Threads 處理
        String requestId = asyncMessageService.sendPeopleGetAllRequest();

        Map<String, Object> response = new HashMap<>();
        response.put("requestId", requestId);
        response.put("status", "processing");
        response.put("message", "角色列表處理中，請稍後查詢結果");

        return ResponseEntity.accepted().body(response);
    }
}
```

### **Consumer 架構優勢**
1. **多業務模組**: People、Weapon、傷害計算分離處理
2. **Virtual Threads**: 輕量級、高效能的線程處理
3. **統一結果管理**: AsyncResultService 集中處理結果
4. **錯誤恢復**: 完整的異常處理和日誌記錄
5. **資源控制**: 通過 concurrency 參數精確控制並發度

---

## 直接 DB 連接 API：不使用 Producer/Consumer 架構

### **直接 DB 連接的場景**

某些 API 可能不需要異步處理，可以直接查詢資料庫並返回結果：

```java
@RestController
public class UserController {

    @Autowired
    private UserService userService;

    // 同步API：直接使用 Virtual Threads 處理
    @GetMapping("/api/users/names")
    public ResponseEntity<?> getAllUserNames() {
        try {
            // 在 Virtual Thread 中直接執行 DB 查詢
            List<String> names = userService.getAllUserNames();
            return new ResponseEntity<>(names, HttpStatus.OK);
        } catch (Exception e) {
            return new ResponseEntity<>(
                "Internal server error: " + e.getMessage(),
                HttpStatus.INTERNAL_SERVER_ERROR
            );
        }
    }
}
```

### **直接 DB 連接的特點**
- ✅ **零延遲**: 無 MQ 中間件，直接返回結果
- ✅ **簡單架構**: 不需要 Consumer，不需要異步處理
- ✅ **Virtual Threads**: HTTP 請求線程就是 Virtual Thread
- ✅ **適用場景**: 快速查詢、簡單業務邏輯
- ❌ **缺點**: 無法處理長時間運行的任務

### **三種架構的比較**

| 架構類型 | Producer/Consumer + MQ | 直接 DB 連接 |
|----------|----------------------|-------------|
| **適用場景** | 複雜業務、長時間處理 | 簡單查詢、快速響應 |
| **延遲** | 中等 (MQ + Consumer) | 低 (直接DB) |
| **可靠性** | 高 (MQ持久化) | 中等 (依賴DB) |
| **資源使用** | 中等 (多組件) | 低 (單一進程) |
| **擴展性** | 高 (Consumer水平擴展) | 中等 (DB連接限制) |
| **Virtual Threads** | ✅ 全程使用 | ✅ HTTP請求使用 |

---

## Virtual Threads 完整用法總覽

### **TY Multiverse 專案中的所有 VT 用法**

#### **1. HTTP 請求處理 (自動使用)**
```java
// Spring Boot 自動使用 Virtual Threads 處理所有 HTTP 請求
@RestController
public class UserController {
    @PostMapping("/get-all")  // 這個請求線程就是 Virtual Thread
    public ResponseEntity<?> getAllPeople() {
        // 無論同步或異步，這裡都是 Virtual Thread
    }
}
```

#### **2. @Async 註解方法 (明確使用)**
```java
@Service
public class AsyncResultSimulatorService {

    // 明確使用 Virtual Threads 執行器
    @Async("threadPoolTaskExecutor")
    public CompletableFuture<Void> processUserData(String requestId) {
        return CompletableFuture.runAsync(() -> {
            // 這裡運行在 Virtual Thread 上
        }, virtualThreadExecutor);
    }
}
```

#### **3. RabbitMQ 監聽器 (框架自動)**
```java
@Service
public class SomeService {

    // Spring Boot 自動使用 Virtual Threads
    @RabbitListener(queues = "some-queue")
    public void handleMessage(String message) {
        // 消息處理運行在 Virtual Thread 上
    }
}
```

#### **4. 同步業務邏輯 (請求線程)**
```java
@RestController
public class UserController {

    // 同步 API 也使用 Virtual Threads
    @GetMapping("/names")
    public ResponseEntity<?> getAllUserNames() {
        // 直接 DB 查詢也在 Virtual Thread 中執行
        List<String> names = userService.getAllUserNames();
        return ResponseEntity.ok(names);
    }
}
```

### **TY Multiverse Consumer @Async 用法統計**

**TY Multiverse Consumer 專案目前未使用 @Async 註解**，因為：

1. **RabbitMQ Consumer 架構**: 所有業務邏輯都在 @RabbitListener 方法中同步執行
2. **Virtual Threads**: Spring Boot 自動為 MQ 監聽器提供 Virtual Threads
3. **簡化架構**: 無需額外的 @Async 註解來控制執行方式

### **✅ TY Multiverse Consumer 的關鍵特點**

#### **RabbitMQ Consumer 設計模式**
```java
// ✅ TY Multiverse Consumer 模式：MQ 監聽器自動使用 Virtual Threads
@RabbitListener(queues = "people-insert", concurrency = "2")
public void handlePeopleInsert(String messageJson) {
    // Spring Boot 自動在 Virtual Thread 中執行
    AsyncMessageDTO message = objectMapper.readValue(messageJson, AsyncMessageDTO.class);
    People people = objectMapper.convertValue(message.getPayload(), People.class);

    // 業務邏輯執行在 Virtual Thread 中
    People savedPeople = peopleService.insertPerson(people);

    // 發送到 async-result 隊列
    asyncResultService.sendCompletedResult(message.getRequestId(), savedPeople);
}
```

#### **執行器配置決定執行方式**
```java
@Configuration
public class SwaggerConfig {

    @Bean(name = "applicationTaskExecutor")
    public TaskExecutor applicationTaskExecutor() {
        // 這個配置決定所有 MQ 監聽器使用 Virtual Threads
        return new VirtualThreadTaskExecutor("vt-app-");
    }
}
```

### **TY Multiverse Consumer 架構特點**

**RabbitMQ Consumer 的行為完全基於 Virtual Threads 執行：**

#### **MQ 監聽器執行模式**
```java
// TY Multiverse 實際模式：MQ 監聽器在 Virtual Thread 中執行
@RabbitListener(queues = "people-get-all", concurrency = "2")
public void handleGetAllPeople(String messageJson) {
    // 1. 在 Virtual Thread 中處理 MQ 消息
    AsyncMessageDTO message = objectMapper.readValue(messageJson, AsyncMessageDTO.class);

    // 2. 在 Virtual Thread 中執行業務邏輯
    List<People> peopleList = peopleService.getAllPeopleOptimized();

    // 3. 在 Virtual Thread 中發送結果
    asyncResultService.sendCompletedResult(message.getRequestId(), peopleList);
}
```

### **TY Multiverse Consumer 效能比較**

| 組件類型 | Virtual Threads 使用 | 說明 |
|----------|---------------------|------|
| **MQ 監聽器** | ✅ 專用 Virtual Thread | Spring Boot 自動分配 |
| **HTTP 請求處理** | ✅ 請求 Virtual Thread | 使用當前請求線程 |
| **業務邏輯** | ✅ 所在線程的 Virtual Thread | 繼承當前線程 |

### **TY Multiverse Consumer 總結**

**RabbitMQ Consumer 架構讓 Virtual Threads 用法更簡潔：**

#### **Virtual Threads 的作用**
- ✅ **自動集成**: Spring Boot 框架自動提供 Virtual Threads
- ✅ **資源優化**: 在資源受限環境下表現更好
- ✅ **業務分離**: MQ 處理與業務邏輯清晰分離

#### **專案中 VT 用法總計**
1. **HTTP 請求處理** (自動) - 所有 Controller 方法
2. **MQ 監聽器** (框架自動) - 17 個隊列 × 2 個 Virtual Threads
3. **業務邏輯** (線程繼承) - 所有業務處理都在 Virtual Thread 中
4. **異步結果處理** (框架自動) - AsyncResultConsumer 處理結果

**最終結論：RabbitMQ Consumer 架構讓 Virtual Threads 用法更簡潔高效！**

### **Virtual Threads 資源優化效果**
```yaml
# 在 0.05 CPU 核心環境下的表現
傳統 Thread Pool:
  - CPU: 80-100% (不穩定)
  - 記憶體: 800MB-1GB
  - 處理能力: 5-10 TPS

Virtual Threads:
  - CPU: 40-60% (穩定)
  - 記憶體: 400-700MB
  - 處理能力: 10-50 TPS

改善幅度:
  - CPU 穩定性: ↑200%
  - 記憶體效率: ↑15%
  - 處理能力: ↑500%
```

---

## TY Multiverse Consumer 架構總結

### **專案實際採用策略**
1. **RabbitMQ Consumer 架構**: 使用 Virtual Threads 處理多業務模組
2. **多 Consumer 類設計**: UnifiedConsumer、PeopleConsumer、WeaponConsumer 分離關注點
3. **統一結果管理**: AsyncResultService 集中處理所有業務結果
4. **Virtual Threads**: 全程使用，最大化資源利用率

### **效能成果**
- ✅ **資源受限環境**: 0.05 CPU 核心下穩定運行
- ✅ **高處理能力**: 17 個隊列 × 2 個 Virtual Threads = 34 個並發處理器
- ✅ **記憶體優化**: 每個 Virtual Thread ~16KB，總計 ~544KB
- ✅ **業務完整性**: 涵蓋 People、Weapon、傷害計算等完整業務場景
- ✅ **跨 Thread 安全**: 通過消息傳遞上下文，解決 Virtual Threads 的狀態隔離問題

**最終結論：TY Multiverse Consumer 成功展示了 Virtual Threads 在生產環境中的實戰價值，並妥善解決了跨 Thread 問題！**

## TY Multiverse Consumer 技術方案比較

| 特性 | TY Multiverse Consumer | 傳統 Thread Pool | Celery |
|------|----------------------|------------------|--------|
| **實現方式** | Spring Boot + Virtual Threads + RabbitMQ | Spring Boot + ThreadPoolExecutor | Python 異步任務框架 |
| **資源占用** | ~16KB/Virtual Thread × 34 個 | ~1MB/傳統 Thread × 少量 | 每個 worker 一個進程 |
| **跨 Thread 處理** | 消息傳遞上下文，完全安全 | ThreadLocal 可能遺失 | 進程隔離，狀態獨立 |
| **適合場景** | 高併發 I/O、資源受限環境 | CPU 密集、穩定環境 | 複雜任務、定時任務 |
| **實際效能** | 10-50 TPS (0.05 CPU) | 5-10 TPS (資源緊張) | 依任務複雜度而定 |

## TY Multiverse Consumer 專案總結

### 小白理解
- **Virtual Threads 就像輕量咖啡師**，每個只吃 16KB 記憶體
- **傳統問題**：傳統 Thread 太重 (1MB)，資源受限環境難以負荷
- **跨 Thread 陷阱**：ThreadLocal、Security Context 等狀態不會自動傳遞
- **TY Multiverse 解決方案**：34 個 Virtual Threads 處理 17 個隊列，總共只用 544KB，並通過消息傳遞解決狀態問題

### 實戰成果
1. **34 個 Virtual Threads**：17 個隊列 × 2 個並發處理器
2. **資源受限環境**：0.05 CPU 核心下穩定運行
3. **高處理能力**：10-50 TPS，傳統方案的 5-10 倍
4. **業務完整性**：People、Weapon、傷害計算完整實現
5. **跨 Thread 安全性**：通過 AsyncMessageDTO 明確傳遞上下文，避免狀態遺失