---
title: "sql-clauses"
publishDate: "2024-03-04 15:00:00"
img: /tymultiverse/assets/SQL.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: An in-depth guide on using WHERE, HAVING, and GROUP BY in SQL queries.
category: Database
tags:
  - SQL
  - WHERE
  - HAVING
  - GROUP BY
---

# SQL WHERE & HAVING Clauses

## Overview

本文件詳盡解釋了 SQL 中的 `WHERE` 與 `HAVING` 子句，分別介紹如何過濾原始資料與分組後的結果。文中提供了多個應用實例，說明各自的使用場景和注意事項。

## WHERE Clause

`WHERE` 子句用於根據條件篩選資料表中的原始行。它只能作用於未經聚合的資料。

### Examples

```sql
SELECT * FROM employees WHERE salary > 50000;
```

```sql
SELECT * FROM employees WHERE age > 30 AND department = 'IT';
```

```sql
SELECT * FROM employees WHERE department IN ('IT', 'HR', 'Finance');
```

```sql
SELECT * FROM employees WHERE salary BETWEEN 40000 AND 60000;
```

```sql
SELECT * FROM employees WHERE last_name LIKE 'Sorane%';
```

```sql
SELECT * FROM employees WHERE middle_name IS NULL;
```

```sql
-- 將 first_name 欄位的值轉換為大寫，然後與 'JOHN' 進行比較。
SELECT * FROM employees WHERE UPPER(first_name) = 'JOHN';
```

### Using the LIKE Operator

`LIKE` 用於進行模糊查詢：

```sql
SELECT birth FROM customer WHERE birth LIKE '1995%';
```

也可以用來對日期進行篩選：

```sql
SELECT birth FROM customer WHERE YEAR(birth) = 1995;
```

## HAVING Clause

`HAVING` 子句用於在 GROUP BY 後對聚合後的資料進行篩選。必須先使用 GROUP BY 才能使用 HAVING。

### GROUP BY Basics

當使用聚合函數時，SELECT 中所有的非聚合欄位必須包含在 GROUP BY 中。

#### Single Column Grouping

```sql
SELECT price FROM order_to_meal GROUP BY price;
```

#### Multiple Columns Grouping

```sql
SELECT price, meal_id FROM order_to_meal GROUP BY price, meal_id ORDER BY meal_id DESC;
```

```sql
SELECT price, meal_id, order_id FROM order_to_meal GROUP BY price, meal_id, order_id ORDER BY order_id DESC;
```

### Aggregation Filtering with HAVING

按部門篩選平均工資大於 50000 的記錄：

```sql
SELECT department, AVG(salary)
FROM employees
GROUP BY department
HAVING AVG(salary) > 50000;
```

使用多個條件進行過濾：

```sql
SELECT department, AVG(salary)
FROM employees
GROUP BY department
HAVING AVG(salary) > 50000 AND COUNT(*) > 10;
```

計算和過濾：

```sql
SELECT department, AVG(salary)
FROM employees
GROUP BY department
HAVING COUNT(*) * AVG(salary) > 500000;
```

使用別名過濾：

```sql
SELECT department, AVG(salary) AS avg_salary
FROM employees
GROUP BY department
HAVING avg_salary > 50000;
```

確認聚合結果不為 NULL：

```sql
SELECT department, AVG(salary)
FROM employees
GROUP BY department
HAVING AVG(salary) IS NOT NULL;
```




## SQL Injection
SQL Injection 是「把惡意 SQL 當作使用者輸入」，讓程式錯誤地執行攻擊者想要的查詢。