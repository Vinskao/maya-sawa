---
title: "java-time-api-localdatetime-zoneddatetime-duration"
publishDate: "2024-02-25 11:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/02/25
category: Java
tags:
  - LocalDateTime
  - ZonedDateTime
  - Duration
  - Java
---

# Java Time API

## Overview

本文件介紹 Java 日期時間 API，重點介紹 `LocalDateTime`、`ZonedDateTime` 與 `Duration` 的創建、解析及運算方式。

## LocalDateTime

`LocalDateTime` 結合了日期和時間，但不帶時區資訊。

### 示例

```java
LocalDate date = LocalDate.of(2024, 2, 25);
LocalTime time = LocalTime.of(12, 30, 45);
LocalDateTime dateTime = LocalDateTime.of(date, time);
// 輸出: 2024-02-25T12:30:45

LocalDateTime customDateTime = LocalDateTime.of(2024, 2, 25, 12, 30, 45);

LocalDateTime parsedDateTime = LocalDateTime.parse("2024-02-25T12:30:45");
```

## ZonedDateTime

`ZonedDateTime` 在 `LocalDateTime` 基礎上增加了時區資訊，非常適用於多時區應用場景。

### 示例

```java
LocalDateTime localDateTime = LocalDateTime.parse("2024-02-25T12:30:45");
ZonedDateTime customTaipeiTime = ZonedDateTime.of(localDateTime, ZoneId.of("Asia/Taipei"));
```

*注意：直接透過 `ZonedDateTime.parse()` 解析不帶時區資訊的字串會失敗。*

## Duration

`Duration` 用來計算兩個日期時間之間的差異，支持以小時、分鐘、毫秒及奈秒單位進行計算。

### 示例

```java
Duration dur = Duration.between(
    ZonedDateTime.parse("2024-02-25T12:00:00+08:00[Asia/Taipei]"),
    ZonedDateTime.parse("2024-02-25T13:30:00+08:00[Asia/Taipei]")
);
// 輸出: PT1H30M

long hours = dur.toHours();         // 1 小時
long minutes = dur.toMinutes();       // 90 分鐘
long millis = dur.toMillis();         // 5400000 毫秒
long nanos = dur.toNanos();           // 5400000000000 奈秒

System.out.println("Hours: " + hours);
System.out.println("Minutes: " + minutes);
System.out.println("Milliseconds: " + millis);
System.out.println("Nanoseconds: " + nanos);
```

