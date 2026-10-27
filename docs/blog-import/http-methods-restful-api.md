---
title: "http-methods-restful-api"
publishDate: "2024-02-26 14:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/02/26
category: API
tags:
  - RESTful API
  - HTTP GET
  - HTTP POST
  - HTTP PUT
  - HTTP DELETE
  - HTTP PATCH
  - Java
---

### HTTP 請求標準格式

```bash
# 請求行（Request Line）
METHOD /path?query=value HTTP/1.1

# 請求標頭（Headers）
Host: example.com
Content-Type: application/json
Authorization: Bearer token
Accept: application/json

# 請求主體（Body）- 僅 POST、PUT、PATCH 等方法需要
{
    "key": "value"
}
```

#### 格式說明

1. **請求行**
   - METHOD：HTTP 方法（GET、POST、PUT 等）
   - /path：資源路徑
   - ?query=value：查詢參數（可選）
   - HTTP/1.1：HTTP 版本

2. **請求標頭**
   - Host：目標主機
   - Content-Type：內容類型
   - Authorization：認證資訊
   - Accept：期望的回應格式

3. **請求主體**
   - 用於傳送資料
   - 通常為 JSON 或 XML 格式
   - GET 和 DELETE 方法通常不需要

#### HTTP 方法

HTTP 方法是指定在與 Web 伺服器或其他資源進行通訊時所採取的操作，是 HTTP 協定的一部分，用於定義客戶端對伺服器進行的請求的性質，常見的 HTTP 方法包括 GET、POST、PUT、DELETE 等。

HTTP 1.1 協定有明定 HTTP 方法 的傳資料方式。

GET 方法： 用於從伺服器檢索資源的資料，通常不對伺服器資源進行修改。應該是冪等的，並且成功找到資源時返回 200 (OK)。

從名為 /products 的資源中獲取 ID 為 123 的產品資訊：

```bash
GET /products?id=123
Host: product.com
```

POST 方法： 用於向伺服器提交資料，通常用於新增資源或執行特定的操作。不是冪等的，可能導致資源的變化，並且呼叫兩個相同的 POST 請求可能導致兩個不同的資源。可以用來新增或透過傳入的參數來搜尋。

```bash
POST /endpoint HTTP/1.1
Host: example.com
Content-Type: application/json

{
    "key": "value"
}
```

PUT 方法： 用於將資料傳送到指定的資源，更新現有資源。應該是冪等的，成功更新現有資源時返回 200 (OK)。

```bash
PUT /products/123 HTTP/1.1
Host: product.com
Content-Type: application/json
{
    "price": 109.99
}
```

PATCH 方法： 用於對指定的資源進行部分修改。與 PUT 不同，它通常用於部分更新資源。

```bash
PATCH /products/123 HTTP/1.1
Host: product.com
Content-Type: application/json
{
    "price": 109.99
}
```

HEAD 方法與 GET 方法類似，但僅返回 HTTP 標頭，不返回實際內容。通常用於檢查資源的元資訊，如文件的修改日期等。

```bash
Copy code
HEAD /products?id=123 HTTP/1.1
Host: product.com
```

DELETE 方法用於從指定的資源刪除資料。

```bash
DELETE /products/123 HTTP/1.1
Host: product.com
```

#### REST 架構

REST 將 Web 看作是一個巨大的資源集合，每個資源都可以通過一個唯一的 URI 來識別，並且客戶端和伺服器之間的通訊是無狀態的。REST 通常基於 HTTP 協定，使用 HTTP 方法（GET、POST、PUT、DELETE 等）來執行對資源的操作。

關鍵是約束一個 API 使用一個 HTTP 方法的功能。

#### RESTful 架構

"RESTful" 一詞是從 "REST" 衍生而來的形容詞，用於描述符合 REST 原則和約束的系統或服務。換句話說，當一個系統或服務遵循了 REST 的設計原則，並使用了 REST 的架構風格時，我們就可以稱其為 "RESTful"。

RESTful 架構另外還設定了一些原則：

1. 強調使用 URL 來唯一地識別資源。每個資源都有一個唯一的 URL，而且使用 HTTP 方法來操作這些 URL。
2. RESTful 架構強調狀態無狀態性，即每個請求都應該包含所有必要的資訊，而不依賴於先前的請求。
3. RESTful 通常使用 JSON 或 XML 等標準的資料格式來傳遞資料。
