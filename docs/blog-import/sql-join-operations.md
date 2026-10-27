---
title: "sql-join-operations"
publishDate: "2024-02-26 16:00:00"
img: /tymultiverse/assets/SQL.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/02/26
category: Database
tags:
  - INNER JOIN
  - OUTER JOIN
  - LEFT JOIN
  - SQL
---

# SQL JOIN Types

## Overview

本文介紹了 SQL 中不同類型的 JOIN 操作，包括 INNER JOIN、LEFT/RIGHT OUTER JOIN 以及 FULL OUTER JOIN，並通過示例程式碼幫助理解各自的使用場景。

## INNER JOIN

`INNER JOIN` 僅返回兩個表中具有匹配關係的行，未匹配的行將被忽略。

### Example

```sql
SELECT * FROM table1 INNER JOIN table2 ON table1.column = table2.column;
```

## OUTER JOIN

OUTER JOIN 返回一個表中的所有行，即使另一個表中沒有匹配。常見的有：

### LEFT OUTER JOIN

又稱 `LEFT JOIN`，返回左表中的所有行，以及右表中與之匹配的行，未匹配部分以 NULL 補齊。

```sql
SELECT * FROM table1 LEFT OUTER JOIN table2 ON table1.column = table2.column;
```

### RIGHT OUTER JOIN

返回右表中的所有行，以及左表匹配的部分：

```sql
SELECT * FROM table1 RIGHT OUTER JOIN table2 ON table1.column = table2.column;
```

### FULL OUTER JOIN

返回左右兩邊所有行，未匹配部分以 NULL 補齊，即 LEFT JOIN 與 RIGHT JOIN 結果的聯集。

```sql
SELECT *
FROM table1
FULL JOIN table2 ON table1.column = table2.column;
```

