---
title: "solid-principles"
publishDate: "2025-05-24 10:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: Understanding SOLID
category: Design Pattern
tags:
  - SRP
  - OCP
  - LSP
  - ISP
  - DIP

---


## OOP 
```
物件導向程式設計 (OOP)
├─ 封裝 (Encapsulation)
│  ├─ 將資料與行為包在物件中
│  ├─ 限制外部直接存取內部狀態
│  └─ 使用 getter/setter 控制存取權限
│
├─ 繼承 (Inheritance)
│  ├─ 子類別繼承父類別功能
│  ├─ 促進程式碼重用
│  └─ 可覆寫（Override）父類方法
│
└─ 多型 (Polymorphism)
   ├─ 相同介面，不同行為
   ├─ 提高程式彈性與擴展性
   └─ 常見方式：介面 + 實作類別
```

## SOLID 概述
```
SOLID 原則（OOP五大原則）
├─ S：單一職責原則（SRP）
│  ├─ 每個類別只做一件事
│  └─ 變更理由應只有一個（例如：業務邏輯 or 資料存取）
│
├─ O：開放封閉原則（OCP）
│  ├─ 對擴展開放，對修改封閉
│  └─ 透過繼承或策略模式，新增功能不必改舊程式
│
├─ L：里氏替換原則（LSP）
│  ├─ 子類應能完全取代父類
│  └─ 替換後程式仍能正確運作
│
├─ I：介面隔離原則（ISP）
│  ├─ 不應強迫實作不需要的方法
│  └─ 多個小型介面 > 一個大型介面
│
└─ D：依賴反轉原則（DIP）
   ├─ 高階模組不應依賴低階模組
   ├─ 應依賴抽象（interface/abstract class）
   └─ 實作透過 DI 注入（如 Spring @Autowired）
```
