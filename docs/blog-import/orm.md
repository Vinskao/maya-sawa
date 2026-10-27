---
title: "orm"
publishDate: "2025-05-24 10:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: Understanding ORM
category: Database
tags:
  - JPA ORM
  - Django ORM
---

## ORM 概述

ORM（物件關聯對應）是一種程式設計技術，用來把物件導向程式中的類別（Class）與資料庫中的資料表（Table）建立對應關係，讓開發者不用手寫 SQL 語句，就能進行新增、查詢、更新、刪除（CRUD）操作。

## ORM 運作機制

### 反射使用情境

| 情境 | 說明 |
|------|------|
| **寫通用框架** | 比如 Spring、JPA、JUnit 不知道你會傳什麼類別，只能等「執行時」讀取 |
| **只拿到類別名稱字串** | 例如從設定檔或資料庫讀到 `com.example.User`，無法直接寫程式碼引用，只能用 `Class.forName(...)` |
| **動態註解處理** | 不知道哪個方法被標註了 `@Transactional`、`@Controller`，只能用反射去掃描類別結構 |
| **執行期間建立 Proxy 或攔截邏輯** | AOP、懶載入、ORM 映射都需要在執行時「動態介入方法行為」 |
| **泛型或抽象實現** | 例如設計一個只處理 `T` 的通用儲存邏輯，要靠反射知道 `T` 是誰 |

### 框架設計考量

- 你（框架作者）根本不知道使用者會建立什麼類別
- 因此：
  - 你 不能寫死程式碼去 `new MyService()`
  - 你 不能寫死程式碼去操作 `Product`
  - 唯一能做的是「啟動時掃描 classpath」，找出這些類別 → 用 反射操作

### 註解處理機制

為什麼不知道哪個方法標註了 `@Transactional`？
- 因為你（Spring）並不是程式碼的撰寫者，只是程式碼的掃描者
- 你（框架）怎麼知道這段程式碼裡有這個註解？
  - → 除非你「掃描所有 class，分析每個 method 是否標註了某個註解」
  - 這只能靠 Reflection

### 運作流程

#### 1. 啟動時（Mapping）
- 用 Reflection 讀取 `@Entity`, `@Table`, `@Column` 註解
- 建立 metadata
- 記錄「類別 ↔ 資料表」和「屬性 ↔ 欄位」的對應關係

#### 2. 執行時（查詢/存資料）
- 用 Reflection 動態操作物件：
  - 建立新實體
    - 使用 `newInstance()` 或建構子反射建立實體
    - 不依賴 IoC 容器，而是直接通過反射機制
    - 實體建立後由 ORM 的 Session/EntityManager 管理生命週期
  - 將資料庫欄位值灌進欄位
  - 或從物件欄位中取值做成 SQL

### 常見問題

| 問題 | 解答 |
|------|------|
| Reflection 只能用在抽象類別？ | ❌ 錯，任何類別都可以 |
| `@Entity`、`@Column` 是怎麼作用的？ | 啟動時用 Reflection 掃描註解建立對應關係 |
| ORM 是否會建立新 class？ | ❌ 一般不會<br>但為了延遲載入或攔截行為，會動態建立 Proxy class（subclass） |
| Proxy class 是包覆還是繼承？ | 是**繼承原類別**，不是包覆（Decorator） |

### 進階機制
- 使用 CGLIB/ByteBuddy 建立代理類別
- 實現延遲載入（Lazy Loading）
- 攔截方法呼叫（AOP）

| 項目 | Mapping | Reflection |
|------|---------|------------|
| 作用時間 | 應用啟動時 | 執行時期（Runtime） |
| 用途 | 決定欄位對應、規則 | 設定物件欄位、讀取資料 |
| 技術手段 | Annotation Parsing | `java.lang.reflect.Field`、`Method` |
| 是否修改程式碼 | ❌ 不會改 bytecode | ❌ 不會改 bytecode |

## ORM 框架比較

| 功能 | JPA/Hibernate | Django ORM | MyBatis |
|------|--------------|------------|---------|
| 自動生成 SQL | 是 | 是 | ❌ 否 |
| Entity 與 Table 對應 | 是（@Entity） | 是（Model） | 部分（需配置） |
| 自動管理資料狀態 | 是 | 是 | ❌ 否 |
| 延遲載入 / 快取 | 是（session） | 是（QuerySet） | ❌ 否（要自己控制） |
| 使用 DDL 自動建表 | 是（schema auto） | 是（migrations） | ❌ 否 |
| 查詢語言 | JPQL | Django ORM API | XML/SQL |
| 交易管理 | 是（@Transactional） | 是（atomic） | 部分（需配置） |

## JPA/Hibernate 實作原理

### 1. 類別與資料表映射
- 使用 `@Entity`, `@Table`, `@Column` 註解
- 建立映射模型（mapping model）
- 管理實體生命週期

### 2. 查詢處理
```java
// 查詢範例
entityManager.find(User.class, 1L);
// 生成 SQL
SELECT * FROM users WHERE id = 1;
```

### 3. 快取機制
- 第一級快取（Session）
- 第二級快取（跨 Session）
- 查詢快取

### 4. 延遲載入
- 使用代理物件
- 攔截方法呼叫
- 按需載入關聯資料

## Django ORM 實作原理

### 1. Model 定義
```python
class User(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

### 2. 查詢處理
```python
# 查詢範例
User.objects.get(id=1)
# 生成 SQL
SELECT * FROM auth_user WHERE id = 1;
```

### 3. 資料庫遷移
- 自動追蹤模型變更
- 生成遷移檔案
- 版本控制

### 4. 查詢優化

#### N+1 查詢問題解決
**核心原則**：只要避免在迴圈內部進行資料庫查詢，就能有效解決 SQL 的 N+1 問題。

這個核心原則背後的邏輯是：在處理一組資料時，我們應該盡量將所有的資料庫操作打包成單一、高效的查詢，而不是針對每一個項目都重複發出請求。

**常見優化方法**：
- `select_related()`：外鍵關聯（一次性 JOIN 查詢）
- `prefetch_related()`：多對多關聯（批量預載入）
- `only()`/`defer()`：欄位選擇（減少資料傳輸）

**範例對比**：
```python
# ❌ N+1 問題：在迴圈中查詢
users = User.objects.all()
for user in users:
    print(user.profile.name)  # 每個 user 都會觸發一次資料庫查詢

# ✅ 優化後：一次性查詢
users = User.objects.select_related('profile').all()
for user in users:
    print(user.profile.name)  # 不會觸發額外的資料庫查詢
```
