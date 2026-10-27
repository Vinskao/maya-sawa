---
title: "jpa"
publishDate: "2024-02-26 16:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/02/26
category: Spring Boot
tags:
  - JPA
  - Java
---

# Java Persistence API (JPA)

## Overview

JPA 是 Java 平台上的 ORM 標準，它使您能夠在 Java 層面上定義資料查詢方法，而無需編寫傳統的 CRUD 指令，同時利用命名規約自動產生 SQL 查詢。

## Query Method Conventions

透過方法名稱，JPA 可自動生成相應的查詢。例如：

```java
List<User> findByUsername(String username);
```

### 常用的命名關鍵字

- **findBy**：開始查詢，後跟屬性名稱。  
- **Between**：指定範圍查詢。  
- **And**：連接多個查詢條件。  
- **Like**：模糊查詢。  
- **GreaterThan**：查詢大於指定數值。  
- **OrderBy**：排序查詢結果。

### 示例方法

```java
// 根據年齡範圍查詢用戶
List<User> findByAgeBetween(int minAge, int maxAge);

// 根據用戶名稱和郵箱查詢用戶
List<User> findByUsernameAndEmail(String username, String email);

// 進行模糊查詢
List<User> findByUsernameLike(String username);

// 以年齡降序排序查詢大於指定年齡的用戶
List<User> findByAgeGreaterThanOrderByAgeDesc(int age);
```

## JPA 方法的回傳類型

### Optional

用來安全地處理可能為 null 的實體：

```java
Optional<Bean> findById(Long id);
```

### Set

確保返回集合中的元素唯一：

```java
Set<Bean> findAllBeans();
```

### Map

以唯一 id 作為 key 快速存取資料：

```java
Map<Long, Bean> findAllBeansWithIdMapping();
```

### Stream

利用 Java 8 的 Stream 進一步操作資料：

```java
Stream<Bean> findAllBeansAsStream();
```

#### Stream 操作示例

- **過濾**：
  ```java
  Stream<Bean> beansStartingWithA = findAllBeansAsStream()
      .filter(bean -> bean.getName().startsWith("A"));
  ```
- **映射**：
  ```java
  Stream<String> beanNames = findAllBeansAsStream()
      .map(Bean::getName);
  ```
- **排序**：
  ```java
  Stream<Bean> sortedBeans = findAllBeansAsStream()
      .sorted(Comparator.comparing(Bean::getName));
  ```

