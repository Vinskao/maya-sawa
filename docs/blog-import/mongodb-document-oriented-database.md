---
title: "mongodb-document-oriented-database"
publishDate: "2024-02-26 22:00:00"
img: /tymultiverse/assets/mongodb-logo.jpg
img_alt: mongo pic
description: |
  2024/02/26
category: Database
tags:
  - Document
  - Document-Oriented Database
---

#### Document

MongoDB 是一種 NoSQL 資料庫，它以文件的形式儲存數據(Document-Oriented Database)，每個文件都是一個獨立的記錄，可以包含各種類型的數據，如字串、整數、數組、嵌套的文檔等。

Document 以鍵值對的形式組織數據，類似 JSON 物件。

```json
{
   "_id": ObjectId("61767f86e774841b20babe2a"),
   "name": "John Doe",
   "age": 30,
   "email": "john.doe@example.com",
   "address": {
       "city": "New York",
       "state": "NY",
       "country": "USA"
   },
   "interests": ["hiking", "photography", "reading"]
}
```

#### BSON

MongoDB 的文件以 BSON（Binary JSON）格式存儲，它是一種二進位表示的 JSON 格式，使得文件可以更有效地進行儲存和傳輸。

每個 MongoDB 文件都可以包含零個或多個字段，每個字段都有一個名稱（鍵）和一個對應的值。

#### Schema-less

MongoDB 是一個無模式（schema-less）或動態模式（dynamic schema）的資料庫，文件可以根據需要靈活地新增或刪除字段，而不需要事先定義資料模型。
