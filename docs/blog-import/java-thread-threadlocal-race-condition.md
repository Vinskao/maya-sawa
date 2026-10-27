---
title: "java-thread-threadlocal-race-condition"
publishDate: "2025-05-26 10:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: Understanding Java Thread & ThreadLocal
level: advance
category: Concurrency
tags:
  - ThreadLocal
  - Race Condition
---

## 多執行緒問題

在 Java 的多執行緒環境中，如果多個執行緒同時讀寫同一個變數（共享變數），會導致：

- 資料競爭（Race Condition）：執行緒之間的操作彼此干擾，產生不可預期的錯誤
- 執行緒不安全：結果錯誤，甚至引發例外

## 解決方案

| 解法 | 原理 | 特性 |
|------|------|------|
| **同步鎖**<br>`synchronized`, `ReentrantLock` | 用鎖來保護共享變數，只允許一個執行緒存取 | 保證資料一致性 |
| **ThreadLocal**<br>執行緒局部變數 | 每個執行緒都有自己獨立的一份變數 | 無需加鎖、效能好、天然執行緒安全 |

## ThreadLocal<T> 核心方法

### 1. set(T value)
- 將值設置到目前執行緒的 ThreadLocalMap 裡
- 每個執行緒呼叫 set()，都只影響自己的資料

```java
threadLocal.set("Alice");
```

### 2. get()
- 取得目前執行緒儲存的值
- 取得的是目前執行緒自己儲存的資料，與其他執行緒互不干擾

```java
String value = threadLocal.get();
```

### 3. remove()
- 移除目前執行緒對應的資料，防止記憶體洩漏
- 特別重要在執行緒池中，因為執行緒會被重複使用
- 移除後，該執行緒對 get() 會回傳 null，或下次會重新初始化（若有使用 withInitial()）

```java
threadLocal.remove();
```

## 記憶體洩露機制

### 底層結構
- ThreadLocal 內部使用 ThreadLocalMap 儲存資料
- ThreadLocalMap 是 Thread 類別的一個成員變數
- ThreadLocalMap 使用 ThreadLocal 物件作為 key，使用者資料作為 value

### Entry 的實現
```java
static class Entry extends WeakReference<ThreadLocal<?>> {
    Object value;
    
    Entry(ThreadLocal<?> k, Object v) {
        super(k);  // 將 ThreadLocal 作為弱引用
        value = v; // value 是強引用
    }
}
```

- Entry 繼承 WeakReference，所以 key（ThreadLocal）是弱引用
- 但 value 是直接作為 Entry 的成員變數，形成強引用
- 即使 key 被回收，value 仍然被 Entry 強引用著
- 只有當 Entry 被回收時，value 才會被回收

### 洩露原因
1. **強引用鏈**
   - Thread -> ThreadLocalMap -> Entry[] -> Entry
   - Entry 繼承自 WeakReference<ThreadLocal>
   - 但 Entry 的 value 是強引用

2. **Thread 生命週期**
   - 執行緒池中的 Thread 會被重複使用
   - Thread 存活期間，ThreadLocalMap 不會被回收
   - 即使 ThreadLocal 被回收，value 仍被 Entry 強引用

3. **弱引用失效**
   - ThreadLocal 被回收後，key 變為 null
   - 但 value 仍被強引用，無法被回收
   - 造成記憶體洩露

### 解決方案
1. **主動清理**
   - 使用完 ThreadLocal 後呼叫 remove()
   - 特別在執行緒池環境中必須執行

2. **使用 try-finally**
```java
try {
    threadLocal.set(value);
    // 業務邏輯
} finally {
    threadLocal.remove();
}
```

3. **使用 ThreadLocal 的 withInitial()**
   - 提供初始值
   - 避免 null 值問題
   - 但仍需手動 remove()

## 結果收集方式
雖然變數存在 ThreadLocal 裡，但我們可以讓每個執行緒完成任務後，把結果放回一個共用的容器中（通常是執行緒安全的集合、佇列、或用回傳值的方式）：
1. 用 Future 或 Callable 回傳每個執行緒的結果
2. 每個執行緒將結果存入執行緒安全的集合：ConcurrentLinkedQueue、ConcurrentMap
