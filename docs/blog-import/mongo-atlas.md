---
title: "mongo-atlas"
publishDate: "2024-02-25 13:00:00"
img: /tymultiverse/assets/mongodb-logo.jpg
img_alt: mongo pic
description: |
  2024/02/25
category: Database
tags:
  - MongoDB Atlas
  - Node.js
  - Mongoose
---

# MongoDB Atlas

Atlas 是 MongoDB 的線上版本，一樣是一個 NoSQL 資料庫。

## Cluster

要開始使用 Atlas，首先需要創建一個 Cluster。Cluster 是一種資料庫部署架構，在 Cluster 中可以進一步創建數據庫（DB）。

## 連線

當連線至數據庫時，Atlas 提供多個不同的驅動程式（drivers）供選擇，根據後端環境選擇適合的驅動程式。以下以 Node.js 環境為例，展示如何進行設定。

連線時，需要在後端設定：

```javascript
// app.js
require("dotenv").config();
let mongoose = require("mongoose");
const mongoURI = process.env.MONGO_URI;
mongoose.connect(mongoURI, { useNewUrlParser: true, useUnifiedTopology: true });
```

```javascript
// .env
MONGO_URI=mongodb+srv://xxx:password@xxx.sgkbzzx.mongodb.net/?retryWrites=true&w=majority&appName=xx
```

### 取得 MONGO_URI

瀏覽器 > Atlas 主頁 > 側邊欄的 Database > 剛剛新建的 Cluster 控制板上的 Connect 按鈕 >
Connect to your application 下的 Drivers 擴展鍵 >>>
選擇 Driver 後，在 Add your connection string into your application code 即可下看到 connection string (MONGO_URI)。

---

## Mongoose

透過 Mongoose.js 可以實現從 Node.js 中的 CRUD 程式對 MongoDB Atlas 進行資料庫操作。

### 創造一張表

這張表有 name、age、favoriteFoods、DOB、Class 五個欄位及對應的格式。

```javascript
let peopleSchema = new mongoose.Schema({
  name: { type: String, required: true },
  age: Number,
  favoriteFoods: [String],
  DOB: String,
  Class: [String],
});
```

使用 mongoose.model() 方法來定義一個名為 Person 的模型， Person 與 MongoDB 中的 "Person" 集合相關聯，之後都用這個名詞 Person 進行 CRUD 對表操作。

```javascript
let Person = mongoose.model("Person", peopleSchema);
```

### 新增

```javascript
const createAndSavePerson = (done) => {
  let Sorane = new Person({
    name: "Sorane",
    age: 29,
    favoriteFoods: ["milkshakes", "coconuts"],
    DOB: "5/31/1994",
    Class: ["Ancient Japanese", "Warlord"],
  });
  Sorane.save((error, data) => {
    if (error) {
      console.log(error);
    } else {
      done(null, data);
    }
  });
};
```

### 搜尋

```javascript
Person.findById("65254c2c1b665c28e085e329", (error, result) => {
  if (error) {
    console.log(error);
  } else {
    console.log(result);
  }
});
// 回傳
// {
//   favoriteFoods: [ 'apples' ],
//   Class: [],
//   _id: 65254c2c1b665c28e085e329,
//   name: 'Jason Bourne',
//   age: 36,
//   __v: 0
// }
```

### 修改

```javascript
const findAndUpdate = (personName, done) => {
  const ageToSet = 20;

  Person.findOneAndUpdate(
    { name: personName },
    { age: ageToSet },
    { new: true },
    (error, updatedData) => {
      if (error) {
        console.log(error);
      } else {
        done(null, updatedData);
      }
    }
  );
};
```

### 刪除

```javascript
const removeById = (personId, done) => {
  Person.findByIdAndRemove(personId, (error, deletedRecord) => {
    if (error) {
      console.log(error);
    } else {
      done(null, deletedRecord);
    }
  });
};
```

## 進階操作與最佳實踐

- **安全性：** 設定 IP 白名單與啟用 SSL，保護資料連線安全。
- **性能優化：** 依據工作負載調整索引與資源配額，定期檢視性能報告。
- **自動備份：** 使用 Atlas 的自動備份及恢復功能，確保資料穩定性與持續性。
