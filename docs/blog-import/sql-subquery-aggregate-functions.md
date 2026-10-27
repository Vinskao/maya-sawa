---
title: "sql-subquery-aggregate-functions"
publishDate: "2024-02-29 22:00:00"
img: /tymultiverse/assets/SQL.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/02/29
category: Database
tags:
  - Subquery
  - Count
  - Sum
  - SQL
---

#### 子查詢

在查詢的 WHERE 中使用某變數 = (SELECT ...)就是子查詢的唯一用法。

子查詢是一種查詢條件，所以遵照原本 WHERE 的用法。

```sql
SELECT username
FROM customer
WHERE id = (SELECT MAX(id) FROM customer);
```

#### 聚合函數

以下是常見的聚合函數：

- COUNT()： 用於計算行數或非 NULL 值的數量。
- SUM()： 用來計算數值列的總和。
- AVG()： 用於計算數值列的平均值。
- MIN()： 用來找出數值列的最小值。
- MAX()： 用來找出數值列的最大值。
- GROUP_CONCAT()： 用於將行合併成一個字串，通常與 GROUP BY 一起使用。

只能在 SELECT 後面放聚合函數。

計算 order_to_meal 表的總行數。

```sql
SELECT COUNT(*) FROM order_to_meal;
```

計算 quantity 欄位 非 null 欄位共幾個。

```sql
SELECT COUNT(quantity) FROM order_to_meal;
```

計算 quantity 欄位數字加總。

```sql
SELECT SUM(quantity) FROM order_to_meal;
```

如果故意 SUM()放一個被能加總的欄位？
出現 error：Operand data type xxx is invalid for sum operator.

聚合函數也可以搭配 WHERE 限定搜尋條件範圍。

```sql
SELECT COUNT(*) FROM order_to_meal WHERE quantity = 6;
```

```sql
SELECT SUM(quantity) FROM order_to_meal WHERE quantity = 7;
```

```sql

```

## 進階查詢技巧與注意事項

- **子查詢效能：** 大量資料查詢時，建議優化子查詢或考慮 JOIN 替代，以避免效能瓶頸。
- **類型匹配：** 確認運算欄位資料類型正確，避免使用不支援聚合的欄位導致錯誤。
- **查詢優化：** 利用 EXPLAIN 查詢計劃，找出並改善查詢效率低下的部分。
