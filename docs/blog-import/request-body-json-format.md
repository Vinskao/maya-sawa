---
title: "request-body-json-format"
publishDate: "2024-03-19 22:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/03/19
category: API
tags:
  - RequestBody
  - Java
---

#### 傳入 json 的兩種方式

1. Map
2. POJO

##### 透過 Map<String, String>傳入

請求的 JSON 資料會被映射到一個 Map<String, String> 對象中，其中的鍵值對表示了 JSON 物件的屬性和值。

示例中，我們從 map 中取得了名為 "id" 的屬性，並將其作為參數傳遞給 requestedService.findById() 方法進行處理。

```java
public ResponseEntity<?> handleRequest(@RequestBody Map<String, String> map) {
    String id = map.get("id");
    requestedService.findById(id);
}
```

##### 透過 POJO 傳入

請求的 JSON 資料會被映射到一個自定義的 Java Bean（例如 IdDto）對象中，該對象的屬性與 JSON 物件的屬性相對應。

```java
public ResponseEntity<?> handleRequest(@RequestBody IdDto idDto) {
    requestedService.findById(idDto.getId());
}
```
