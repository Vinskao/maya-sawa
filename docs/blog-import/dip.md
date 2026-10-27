---
title: "dip"
publishDate: "2024-02-24 12:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: An introduction to Dependency Injection, DIP, and relevant design patterns in Java.
category: Design Pattern
tags:
  - DIP
  - OCP
  - Design Patterns
  - Java
---

# Dependency Injection & Dependency Inversion Principle (DIP)

## Overview

本文件探討如何藉由依賴注入（Dependency Injection, DI）及依賴反轉原則（Dependency Inversion Principle, DIP）降低高層模組與低層實作之間的耦合度。這樣的設計符合開放封閉原則（OCP），使系統更加靈活與易於維護。

## 問題背景

傳統的設計中，高層模組（例如 `CleanController`）直接依賴於低層實作（例如 `CleanerService`），導致一旦低層模組更換，高層模組也必須修改，增加了系統的脆弱性。

### 緊耦合示例

```java
package org.controller;

public class CleanController {
  private CleanerService cleanerService;
  
  public CleanController(CleanerService cleanerService){
    this.cleanerService = cleanerService;
  }
  
  public void cleaningApi(){
    cleanerService.cleaner();
    cleanerService.clean();
    // 輸出: "Cleaner is..." 與 "Cleaning..."
  }
}
```

```java
package org.service;

public class CleanService {
  public void clean(){
    System.out.print("Cleaning...");
  }
}
```

```java
package org.service;

public class CleanerService {
  public void cleaner(){
    System.out.print("Cleaner is...");
  }
}
```

## DI 與 DIP 的實踐

將依賴改為抽象介面可以解決以上問題，實現高層模組與低層實作之間解耦。

### 定義介面

```java
package org.service;

public interface CleanerService {
  void cleaner();
  void clean();
}
```

### 實作不同的清潔服務

```java
package org.service;

public class StandardCleanerService implements CleanerService {
  @Override
  public void cleaner(){
    System.out.print("Standard Cleaner is...");
  }
  
  @Override
  public void clean(){
    System.out.print("Cleaning...");
  }
}
```

```java
package org.service;

public class AdvancedCleanerService implements CleanerService {
  @Override
  public void cleaner(){
    System.out.print("Advanced Cleaner is...");
  }
  
  @Override
  public void clean(){
    System.out.print("Cleaning...");
  }
}
```

### 更新 Controller

```java
package org.controller;

import org.service.CleanerService;

public class CleanController {
  private CleanerService cleanerService;
  
  public CleanController(CleanerService cleanerService){
    this.cleanerService = cleanerService;
  }
  
  public void cleaningApi(){
    cleanerService.cleaner();
    cleanerService.clean();
    // 依據注入的實作，輸出 "Advanced Cleaner is..." 或 "Standard Cleaner is..." 再接上 "Cleaning..."
  }
}
```

