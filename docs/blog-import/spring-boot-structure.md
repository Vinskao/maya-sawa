---
title: "spring-boot-structure"
publishDate: "2025-05-24T10:00:00.000Z"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: Understanding Spring Boot
category: Spring Boot
tags:
  - IOC
  - AOP
---

## Spring Boot IOC 實作

在 Spring Boot 啟動階段，會自動掃描所有有標註的元件（如 @Service、@Controller 等），並將它們建立成 Bean 放入 IoC 容器中。

之後在執行期間，當某個類別需要用到其他元件時（透過 @Autowired 或建構子參數），Spring 就會自動從 IoC 容器中取出對應的 Bean 來注入，省去手動 new 物件的麻煩，這就是控制反轉（IoC）。

「Bean」指的是：

一個被 Spring IoC 容器管理的物件。

## Spring Boot AOP 實作

### 概述

AOP（Aspect-Oriented Programming）是一個設計風格，在 Spring Boot 中透過 proxy class 實作。實作方式是建立一個攔截物件，呼叫「代理類的同名方法」，並使用 Reflection 的 `method.invoke(...)`，才能在不更動原始程式碼的情況下，達到「方法攔截」與「動態邏輯擴充」的目的。

### 實作原理

Java Reflection API 允許程式在「執行時期」讀取類別、方法、欄位等資訊，並且可以動態呼叫方法。Spring Boot 雖然是在 static void main 中啟動應用程式，但在啟動過程中會掃描所有 Bean 並建立對應實例，放入 IoC 容器。這些 Bean 通常在啟動時就建立好。但當你使用 AOP 時，Spring 會建立一個代理類別，在方法執行階段透過 Reflection 來呼叫實際方法，從而實作「方法攔截」的能力。

#### 代理方式

Spring 提供兩種代理實作方式：

1. **JDK 動態代理**
   - 適用於接口導向的 Bean
   - 使用 `java.lang.reflect.Proxy` 介面
   - 當 Bean 有「實作介面」時使用

2. **CGLIB 動態代理**
   - 適用於沒有介面的 Bean
   - 使用 bytecode 操控建立 subclass
   - 當 Bean 沒有實作任何介面時使用

| 項目          | JDK Proxy                                | CGLIB                                |
| ----------- | ---------------------------------------- | ------------------------------------ |
| **代理方式**    | 動態生成介面實作的代理類                             | 動態生成原始類別的「子類別」                       |
| **是否需要介面**  | 必須有介面                                  | ❌ 不需要介面                              |
| **實作原理**    | 使用 Java 標準 API `java.lang.reflect.Proxy` | 使用第三方函式庫（如 CGLIB）透過 bytecode 操控產生子類別 |
| **不能代理的情況** | 無介面的類別                                   | final 類別或 final 方法（不能被繼承）            |
| **效能**      | 效能較好（因為是標準 API）                          | 效能稍差（動態生成 bytecode）                  |

#### 代理建立流程

1. Spring 啟動並掃描 Bean
2. 建立原始 Bean 例項（例如 UserService）
3. 發現有 @Aspect 或註冊了某些 Advisor（通知邏輯）
4. 如果 Bean 被 AOP 規則匹配（例如 method 上有 @Transactional）：
   - 建立 Proxy
   - 加入前置邏輯（before）
   - 執行原始方法：method.invoke(target, args)
   - 加入後置邏輯（after/afterReturning/afterThrowing）

### 功能說明

#### 可實作功能

1. **方法執行前後加行為**
   - Log 記錄
   - 權限檢查
   - 交易管理
   - 執行時間計算

2. **參數與回傳值處理**
   - 存取方法參數 (`args`)
   - 存取回傳值 (`returnValue`)

3. **例外處理**
   - 統一錯誤處理邏輯

#### 限制

1. **無法操作方法內部區域變數**
   - 無法進入方法內部執行流程

2. **無法插入內部行 Log**
   - 無法存取原始程式碼內部

3. **無法改變方法流程**
   - 無法控制 `if/else` 或迴圈內部行為

### 例外處理能力

1. **攔截例外** - 在 `try/catch` 中包住 `method.invoke(...)`

2. **判斷錯誤類別** - 使用 `if (e instanceof SomeException)`

3. **自動錯誤處理策略** ❌
   - 需要明確定義處理邏輯

4. **自定義規則** - 可定義例外處理規則和錯誤回傳格式

### 實例：@Transactional

Spring 中的 @Transactional 是 AOP 應用的經典範例。當方法或類別標註 @Transactional 時：

1. Spring 建立代理類別（使用 JDK Proxy 或 CGLIB）
   - 資料庫：此時資料庫尚未有任何動作

2. 方法呼叫流程：
   - 方法執行「前」開啟交易（begin transaction）
     - 資料庫：建立一個新的交易（transaction）
     - 資料庫：設定交易隔離層級（isolation level）
     - 資料庫：開始記錄所有 SQL 操作到交易日誌（transaction log）

   - 呼叫 method.invoke(target, args) 執行實際方法
     - 資料庫：執行所有 SQL 操作（INSERT/UPDATE/DELETE）
     - 資料庫：將操作結果暫存在交易緩衝區（transaction buffer）
     - 資料庫：持續記錄操作到交易日誌

   - 方法執行「後」根據結果：
     - 若無例外 → 提交交易（commit）
       - 資料庫：將交易緩衝區的變更寫入實際資料表
       - 資料庫：釋放交易鎖定（transaction locks）
       - 資料庫：標記交易為已完成

     - 若拋出例外 → 回滾交易（rollback）
       - 資料庫：讀取交易日誌
       - 資料庫：將所有變更還原到交易開始前的狀態
       - 資料庫：釋放交易鎖定
       - 資料庫：標記交易為已回滾

當你呼叫 rollback()，資料庫會自動把「在這個交易中做的所有變更」都撤銷掉。
不會造成「再寫一次」，也不需要「自己重寫 SQL」。

| 資料庫                   | 支援交易？ | 說明                 |
| --------------------- | ----- | ------------------ |
| **MySQL (InnoDB 引擎)** | 有支援 | 主流用法，支援 rollback   |
| **PostgreSQL**        | 有支援 | 強大的交易與一致性          |
| **Oracle DB**         | 有支援 | 企業等級交易管理           |
| **MySQL (MyISAM 引擎)** | ❌ 不支援 | 回滾會失敗，只會寫入         |
| **Redis / MongoDB**   | ❌/部分  | 不是真正的 RDBMS，交易支援有限 |

### 注意事項

- Log 無法與原始方法互動
- 只能在 `method.invoke` 前後執行操作