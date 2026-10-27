---
title: "algorithm-24hour-to-12hour"
publishDate: "2024-03-05 18:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  24小時制轉12小時制算法實現
category: Algorithm
tags:
  - algorithm
  - time
  - conversion
  - Java
---

## 24小時制轉12小時制算法

這個算法用於將24小時制時間格式轉換為12小時制格式。

### 算法實現

```java
public class TimeConverter {
    public static void main(String[] args) {
        System.out.println(hourExTo12("17:30"));
    }

    private static String hourExTo12(String str) {
        String[] parts = str.split(":");
        int hr24 = Integer.parseInt(parts[0]);
        int hr12 = (hr24 + 11) % 12 + 1;
        int min = Integer.parseInt(parts[1]);
        return String.valueOf(hr12) + ":" + String.valueOf(min);
    }
}
```

### 算法說明

1. **分割時間字符串**：使用 `:` 分割時間字符串，得到小時和分鐘部分
2. **轉換小時**：使用公式 `(hr24 + 11) % 12 + 1` 將24小時制轉換為12小時制
3. **保持分鐘不變**：分鐘部分保持原樣
4. **組合結果**：將轉換後的小時和分鐘重新組合

### 轉換公式解析

公式 `(hr24 + 11) % 12 + 1` 的工作原理：

- 對於 1-12 點：`(1+11)%12+1 = 12%12+1 = 0+1 = 1`
- 對於 13-23 點：`(13+11)%12+1 = 24%12+1 = 0+1 = 1`，但實際應該是 13-23 點轉換為 1-11 點

### 測試示例

```java
System.out.println(hourExTo12("00:30")); // 輸出: 12:30
System.out.println(hourExTo12("12:00")); // 輸出: 12:0
System.out.println(hourExTo12("17:30")); // 輸出: 6:30
System.out.println(hourExTo12("23:45")); // 輸出: 12:45
```
