---
title: "consumer"
publishDate: "2025-08-23 10:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: A comprehensive guide to consumer design and architecture in message queue systems, covering backend producer to RabbitMQ to consumer to database patterns.
level: advance
category: Spring Boot
tags:
  - Message Queue
  - RabbitMQ
  - Consumer
  - Architecture
  - Spring Boot
  - Database
---

## Overview

在現代分散式系統中，生產者-消費者模式是建構可擴展、解耦應用程式的基礎。本文探討典型流程中消費者的設計與架構：**後端 (生產者) → RabbitMQ → 消費者 → 資料庫**。

## 架構流程

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Backend   │──▶│  RabbitMQ   │───▶│  Consumer   │──▶│  Database   │
│ (Producer)  │    │   Broker    │    │ (Worker)    │    │             │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

## 關鍵組件

### 1. 後端生產者
- **目的**：產生訊息並發佈到 RabbitMQ
- **責任**：
  - 訊息建立與序列化
  - 路由鍵分配
  - 錯誤處理與重試邏輯
  - 訊息確認

### 2. RabbitMQ 中介
- **目的**：處理訊息路由與傳遞的訊息隊列中介軟體
- **功能特性**：
  - 訊息持久化
  - 交換器與隊列管理
  - 死信隊列
  - 訊息確認

### 3. 消費者 (工作者)
- **目的**：從 RabbitMQ 處理訊息並執行業務邏輯
- **責任**：
  - 訊息消費與反序列化
  - 業務邏輯執行
  - 資料庫操作
  - 錯誤處理與重試機制
  - 訊息確認

### 4. 資料庫
- **目的**：已處理資料的持久化儲存
- **考量點**：
  - 交易管理
  - 連線池
  - 資料一致性
  - 效能優化

## 消費者設計模式

### 1. 基本消費者模式
```java
@Component
public class BasicConsumer {

    @RabbitListener(queues = "my-queue")
    public void processMessage(Message message) {
        try {
            // 反序列化訊息
            MyData data = deserialize(message);

            // 處理業務邏輯
            processBusinessLogic(data);

            // 儲存到資料庫
            saveToDatabase(data);

            // 確認訊息
            acknowledgeMessage(message);

        } catch (Exception e) {
            // 處理錯誤並可能拒絕訊息
            handleError(message, e);
        }
    }
}
```

### 2. 批次處理模式
```java
@Component
public class BatchConsumer {

    @RabbitListener(queues = "batch-queue", containerFactory = "batchListenerContainerFactory")
    public void processBatch(List<Message> messages) {
        List<MyData> dataList = new ArrayList<>();

        for (Message message : messages) {
            dataList.add(deserialize(message));
        }

        // 處理批次
        processBatchLogic(dataList);

        // 批次儲存到資料庫
        batchSaveToDatabase(dataList);
    }
}
```

### 3. 死信隊列模式
```java
@Component
public class DeadLetterConsumer {

    @RabbitListener(queues = "dlq-queue")
    public void processDeadLetter(Message message) {
        // 記錄失敗訊息
        logFailedMessage(message);

        // 分析失敗原因
        analyzeFailure(message);

        // 可能重試或封存
        handleDeadLetter(message);
    }
}
```

## Consumer Architecture Considerations

### 1. Scalability
- **Horizontal Scaling**: Multiple consumer instances
- **Load Balancing**: RabbitMQ's built-in load balancing
- **Connection Pooling**: Efficient resource management

### 2. Reliability
- **Message Acknowledgment**: Manual vs automatic acknowledgment
- **Dead Letter Queues**: Handling failed messages
- **Retry Mechanisms**: Exponential backoff strategies
- **Circuit Breakers**: Preventing cascade failures
- **Prefetch Control**: Backpressure mechanism to prevent consumer overload

### 3. 背壓與流量控制
- **預取計數**：限制每個消費者未確認訊息數量
- **中介檢查**：RabbitMQ 在傳送訊息前檢查消費者容量
- **消費者控制**：Java 消費者可透過 basicQos() 控制訊息流

#### 預取計數詳解
```java
// 設定預取計數為 10
channel.basicQos(10);

// 中介只會在任何時間點傳送最多 10 筆未確認訊息
// 給這個消費者
```

**運作原理：**
1. 消費者透過 `basicQos(prefetchCount)` 設定預取計數
2. 中介追蹤每個消費者的未確認訊息數量
3. 當未確認訊息達到預取上限，中介停止傳送新訊息
4. 消費者處理並確認訊息，釋放可用位置
5. 中介在有可用位置時恢復傳送

#### 確認策略

**自動確認 (autoAck = true)**
- 訊息在接收時立即確認
- 若處理失敗有資料遺失風險
- 適合非關鍵性、發後即忘場景

**手動確認 (autoAck = false)** - **推薦用於可靠性**
- 消費者在處理成功後明確呼叫 `basicAck()`
- 失敗訊息可使用 `basicNack()` 或 `basicReject()`
- 可選擇重新排隊失敗訊息或傳送到死信隊列
- 適用於高可靠性場景（交易、付款、通知）

```java
// 手動確認範例
channel.basicConsume("myQueue", false, (consumerTag, delivery) -> {
    try {
        // 處理訊息
        processMessage(delivery);
        // 成功：確認
        channel.basicAck(delivery.getEnvelope().getDeliveryTag(), false);
    } catch (Exception e) {
        // 失敗：拒絕並可選擇重新排隊
        channel.basicNack(delivery.getEnvelope().getDeliveryTag(), false, true);
    }
}, consumerTag -> {});
```

#### 控制並發數量（線程池）

即使有預取設定，單個消費者可能處理不夠快。使用線程池：

**Spring AMQP（推薦）**
```java
@Bean
public SimpleRabbitListenerContainerFactory rabbitListenerContainerFactory() {
    SimpleRabbitListenerContainerFactory factory = new SimpleRabbitListenerContainerFactory();
    factory.setConnectionFactory(connectionFactory());

    // 預取控制
    factory.setPrefetchCount(10);

    // 並發控制
    factory.setConcurrentConsumers(3);
    factory.setMaxConcurrentConsumers(10);
    factory.setAcknowledgeMode(AcknowledgeMode.MANUAL);

    return factory;
}
```

這會建立 3-10 個並發消費者線程，每個都受預取計數限制。


## 實作範例

### Spring Boot 消費者配置
```java
@Configuration
public class RabbitMQConfig {

    @Bean
    public ConnectionFactory connectionFactory() {
        CachingConnectionFactory factory = new CachingConnectionFactory();
        factory.setHost("localhost");
        factory.setPort(5672);
        factory.setUsername("guest");
        factory.setPassword("guest");
        return factory;
    }

    @Bean
    public SimpleRabbitListenerContainerFactory rabbitListenerContainerFactory() {
        SimpleRabbitListenerContainerFactory factory = new SimpleRabbitListenerContainerFactory();
        factory.setConnectionFactory(connectionFactory());
        factory.setConcurrentConsumers(3);
        factory.setMaxConcurrentConsumers(10);
        factory.setAcknowledgeMode(AcknowledgeMode.MANUAL);
        return factory;
    }
}
```

### 資料庫整合
```java
@Service
@Transactional
public class DataProcessingService {

    @Autowired
    private JdbcTemplate jdbcTemplate;

    public void processAndSave(MyData data) {
        // 處理業務邏輯
        ProcessedData processed = processBusinessLogic(data);

        // 使用交易儲存到資料庫
        saveToDatabase(processed);

        // 更新處理狀態
        updateProcessingStatus(data.getId(), "COMPLETED");
    }

    private void saveToDatabase(ProcessedData data) {
        String sql = "INSERT INTO processed_data (id, content, created_at) VALUES (?, ?, ?)";
        jdbcTemplate.update(sql, data.getId(), data.getContent(), data.getCreatedAt());
    }
}
```

