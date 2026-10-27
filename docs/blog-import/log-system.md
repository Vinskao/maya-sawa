---
title: "log-system"
publishDate: "2025-09-15 10:00:00"
img: /tymultiverse/assets/algorithm.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: TY Multiverse 專案 - 從傳統日誌系統升級到現代雲端日誌系統的完整指南
category: DevOps
tags:
  - 日誌系統
  - SLF4J
  - Logback
  - MDC
  - 關聯ID
  - 雲端日誌
  - 結構化日誌
  - 全鏈路追蹤
  - TY Multiverse

---

# 從傳統日誌到雲端日誌：打造結構化、可追溯的日誌系統

## 前言

假設您的專案目前使用了 **SLF4J + Logback** 的標準組合，這是一個穩定且廣泛使用的選擇。目前的日誌系統已經具備基本的日誌記錄功能，並透過 `application.yml` 實現了不同環境的日誌等級控制。

這份教學文章將引導您如何將現有的系統升級為更現代、更強大，且特別適合雲端環境的日誌系統。

## 第一步：理解傳統日誌的限制

您目前的日誌系統採用了純文字格式。雖然這種格式在開發階段查看終端機日誌很方便，但在雲端環境中會面臨幾個挑戰：

### 難以追溯與關聯
當一個請求從 API 進入，觸發多個內部服務甚至跨服務的事件時，很難將所有相關的日誌串聯起來。

### 搜尋效率低
雲端日誌平台如 GCP 或 AWS 的日誌服務，雖然能全文檢索，但要找出特定使用者、特定訂單或特定請求的所有日誌，需要使用複雜的關鍵字或正規表達式，效率低且容易出錯。

### 缺乏結構化資料
日誌內容只是一段文字，無法直接在日誌平台中對特定欄位（例如 `userId`、`orderId`）進行篩選、聚合或統計分析。

## 第二步：核心概念 — 關聯 ID (Correlation ID)

要解決上述問題，最核心的解決方案就是引入 **關聯 ID (Correlation ID)**。

**關聯 ID 是一個全局唯一的標識符（例如一個 UUID）**，它代表了從一個請求開始到結束的整個處理過程。無論這個請求在後端經歷了多少個方法呼叫、多少個異步事件甚至跨服務調用，這個 ID 都會被傳遞並記錄在每一條日誌中。

這就像是給每個請求發放一張專屬的「護照」。所有與該請求相關的日誌都會在護照上蓋章，讓您只需搜尋這張護照號碼，就能找到所有相關的日誌記錄。

## 第三步：實現方案 — SLF4J MDC (Mapped Diagnostic Context)

文章中提到的 ThreadLocal 概念，在 SLF4J 的生態系中已經有標準的實作，那就是 **MDC (Mapped Diagnostic Context)**。

**MDC 是一個以執行緒為作用域的鍵值對 (key-value) 容器。** 您可以把關聯 ID 放入 MDC 中，日誌框架（如 Logback）就能自動將這個 ID 附加到該執行緒產生的每一條日誌上。這完美地解決了「不污染方法簽名」和「避免全域變數」的問題。

### 具體實作步驟：

#### **1. 在請求的入口點生成或獲取關聯 ID**
- **對於 API 請求**：檢查 HTTP 請求標頭（例如 `X-Request-ID`）。如果客戶端提供了，就使用它；如果沒有，就生成一個新的 UUID。
- **對於定時任務或事件驅動**：在任務開始時生成一個 UUID。

#### **2. 將關聯 ID 放入 MDC**
```java
import org.slf4j.MDC;

// ... 在請求入口點
String correlationId = getOrCreateCorrelationIdFromRequest(request);
MDC.put("correlationId", correlationId);

// 之後的日誌會自動帶上這個 ID
logger.info("Handling API request for user: {}", userId);

// ... 在請求結束時
MDC.remove("correlationId"); // 記得移除，避免執行緒重用時造成資料污染
```

#### **3. 修改 Logback 配置以包含 MDC 中的資料**
在 `logback-spring.xml` 或 `application.yml` 中，修改日誌格式。

```xml
<appender name="STDOUT" class="ch.qos.logback.core.ConsoleAppender">
  <encoder>
    <pattern>%d{yyyy-MM-dd HH:mm:ss.SSS} [%thread] %-5level %logger{36} - [CorrelationId:%X{correlationId}] %msg%n</pattern>
  </encoder>
</appender>
```

### **TY Multiverse 專案的實際實現**

在 TY Multiverse Consumer 中，我們已經在處理 MQ 消息時正確使用了 MDC：

```java
@RabbitListener(queues = "people-insert", concurrency = "2")
public void handlePeopleInsert(String messageJson) {
    try {
        AsyncMessageDTO message = objectMapper.readValue(messageJson, AsyncMessageDTO.class);

        // ✅ 從消息中獲取 traceId 並設置到 MDC
        String traceId = message.getTraceId();
        MDC.put("traceId", traceId);
        MDC.put("requestId", message.getRequestId());
        MDC.put("userId", message.getUserId());

        try {
            // 業務處理...
            People people = objectMapper.convertValue(message.getPayload(), People.class);
            People savedPeople = peopleService.insertPerson(people);

            asyncResultService.sendCompletedResult(message.getRequestId(), savedPeople);
            logger.info("✅ People 插入完成: {}", message.getRequestId());
        } finally {
            // ✅ 清理 MDC，避免執行緒重用造成污染
            MDC.clear();
        }
    } catch (Exception e) {
        handleError(messageJson, e);
    }
}
```

## 第四步：結構化日誌輸出

為了讓雲端日誌平台更好地解析日誌，我們需要將日誌輸出格式從純文字改為 **JSON 格式**。

**Logback 透過 Encoder 支援多種輸出格式。** 您可以使用現成的 JSON Encoder，例如 LogstashEncoder。

### **1. 導入必要的依賴**
```xml
<dependency>
    <groupId>net.logstash.logback</groupId>
    <artifactId>logstash-logback-encoder</artifactId>
    <version>7.4</version>
</dependency>
```

### **2. 修改 Logback 配置，使用 LogstashEncoder**
```xml
<appender name="STDOUT" class="ch.qos.logback.core.ConsoleAppender">
    <encoder class="net.logstash.logback.encoder.LogstashEncoder">
        <customFields>{"app":"ty-multiverse-consumer", "environment":"${spring.profiles.active}"}</customFields>
    </encoder>
</appender>
```

這樣一來，每一條日誌都會被格式化成一個 JSON 物件，其中包含了日誌等級、時間戳、類別名稱，以及最重要的 MDC 欄位（例如 `correlationId`）。

### **JSON 日誌格式示例**
```json
{
  "@timestamp": "2025-09-15T10:00:00.123+08:00",
  "@version": "1",
  "message": "✅ People 插入完成: req-123456",
  "logger_name": "com.ty.multiverse.consumer.UnifiedConsumer",
  "thread_name": "VirtualThread-1",
  "level": "INFO",
  "level_value": 20000,
  "app": "ty-multiverse-consumer",
  "environment": "dev",
  "traceId": "550e8400-e29b-41d4-a716-446655440000",
  "requestId": "req-123456",
  "userId": "user-789"
}
```

## 第五步：處理跨服務追蹤

當您的系統未來擴展到多個微服務時，單純的 MDC 無法解決跨服務追溯的問題。

### **解決方案：**

#### **1. 將關聯 ID 傳遞到下游服務**
當一個服務發送 HTTP 請求或發布事件給另一個服務時，需要將關聯 ID 放入請求標頭或事件的 metadata 中。

**HTTP 請求示例：**
```java
@RestController
public class PeopleController {

    @Autowired
    private RestTemplate restTemplate;

    @PostMapping("/api/people/process")
    public ResponseEntity<?> processPeople(@RequestBody People people,
                                          @RequestHeader(value = "X-Trace-Id", required = false) String traceId) {

        // 獲取或生成 traceId
        if (traceId == null) {
            traceId = UUID.randomUUID().toString();
        }

        // 設置到 MDC
        MDC.put("traceId", traceId);

        try {
            // 發送請求到下游服務時，攜帶 traceId
            HttpHeaders headers = new HttpHeaders();
            headers.set("X-Trace-Id", traceId);

            HttpEntity<People> requestEntity = new HttpEntity<>(people, headers);
            ResponseEntity<String> response = restTemplate.postForEntity(
                "http://downstream-service/api/process", requestEntity, String.class);

            return ResponseEntity.ok(response.getBody());
        } finally {
            MDC.remove("traceId");
        }
    }
}
```

#### **2. 在下游服務的入口點重新設定 MDC**
下游服務接收到請求或事件後，從標頭或 metadata 中取出關聯 ID，並使用 `MDC.put()` 重新設定。

**下游服務處理示例：**
```java
@RestController
public class DownstreamController {

    @PostMapping("/api/process")
    public ResponseEntity<?> process(@RequestBody People people,
                                    @RequestHeader("X-Trace-Id") String traceId) {

        // ✅ 從請求標頭取出 traceId 並重新設置到 MDC
        MDC.put("traceId", traceId);
        MDC.put("requestId", UUID.randomUUID().toString()); // 生成新的 requestId

        try {
            logger.info("開始處理下游業務邏輯");

            // 業務處理...
            People processed = downstreamService.process(people);

            logger.info("下游業務邏輯處理完成");
            return ResponseEntity.ok(processed);
        } finally {
            MDC.clear();
        }
    }
}
```

### **MQ 跨服務追蹤**

對於 TY Multiverse 專案中的 RabbitMQ 場景：

```java
@Service
public class AsyncMessageService {

    public String sendUserDataRequest() {
        String requestId = UUID.randomUUID().toString();

        AsyncMessageDTO message = new AsyncMessageDTO(
            requestId,
            "/api/users/process",
            "POST",
            null
        );

        // ✅ 在消息中攜帶 traceId
        message.setTraceId(MDC.get("traceId")); // 從當前 MDC 獲取
        message.setUserId(MDC.get("userId"));

        sendMessage(RabbitMQConfig.PEOPLE_GET_ALL_QUEUE, message);
        return requestId;
    }
}
```

如此一來，跨服務的日誌也能透過同一個關聯 ID 串聯起來，真正實現全鏈路追溯。

## 第六步：雲端日誌平台的整合

### **GCP Cloud Logging**
```yaml
# application-gcp.yml
logging:
  config: classpath:logback-gcp.xml
```

```xml
<!-- logback-gcp.xml -->
<configuration>
    <appender name="CLOUD" class="com.google.cloud.logging.logback.LoggingAppender">
        <log>ty-multiverse-consumer</log>
        <resourceType>global</resourceType>
        <encoder class="net.logstash.logback.encoder.LogstashEncoder">
            <customFields>{"service":"ty-multiverse-consumer"}</customFields>
        </encoder>
    </appender>

    <root level="INFO">
        <appender-ref ref="CLOUD"/>
    </root>
</configuration>
```

### **AWS CloudWatch**
```xml
<dependency>
    <groupId>ca.pjer</groupId>
    <artifactId>logback-awslogs-appender</artifactId>
    <version>1.6.0</version>
</dependency>
```

## 第七步：日誌分析與監控

### **日誌查詢示例**
```sql
-- 在 GCP BigQuery 或 Elasticsearch 中查詢
SELECT *
FROM `logs.ty_multiverse_consumer`
WHERE traceId = "550e8400-e29b-41d4-a716-446655440000"
ORDER BY timestamp ASC
```

### **效能監控**
```sql
-- 計算平均響應時間
SELECT
    traceId,
    MIN(timestamp) as start_time,
    MAX(timestamp) as end_time,
    TIMESTAMP_DIFF(MAX(timestamp), MIN(timestamp), MILLISECOND) as duration_ms
FROM `logs.ty_multiverse_consumer`
WHERE DATE(timestamp) = CURRENT_DATE()
GROUP BY traceId
ORDER BY duration_ms DESC
LIMIT 10
```

## 總結

### **升級前後對比**

| 特性 | 傳統日誌 | 結構化日誌 + 關聯 ID |
|------|---------|-------------------|
| **追溯性** | 困難，需要複雜搜尋 | 簡單，搜尋單一 traceId |
| **跨服務追蹤** | 無法實現 | 完整支援 |
| **效能分析** | 困難，手動聚合 | 輕鬆實現 |
| **雲端整合** | 基本支援 | 完美整合 |
| **開發效率** | 低 | 高 |

### **TY Multiverse 專案的最佳實踐**

1. **AsyncMessageDTO 設計**：在消息中明確包含 `traceId`、`requestId`、`userId` 等上下文資訊
2. **MDC 正確使用**：在每個 MQ 處理器中設置 MDC，並在 finally 區塊清理
3. **統一錯誤處理**：確保錯誤日誌也能正確攜帶追蹤資訊
4. **性能考量**：MDC 操作輕量，不會影響 Virtual Threads 的效能

### **實戰建議**

1. **從小處開始**：先在一個關鍵的 API 或 MQ 處理器中實施
2. **漸進式升級**：逐步將所有日誌點都加上結構化資訊
3. **測試驗證**：確保 MDC 不會造成記憶體洩漏
4. **監控效果**：實施後觀察日誌查詢效率的改善

**最終結論：結構化的日誌系統不僅解決了雲端環境的挑戰，更為您的系統提供了強大的可觀測性基礎！**
