---
title: "java-access-modifiers"
publishDate: "2024-03-05 18:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/03/05
category: Java
tags:
  - public
  - private
  - protected
  - default
  - Java
---

#### 存取權限修飾詞

- public: 該成員（類別、方法、屬性）可以被所有其他類別訪問。
- private: 該成員僅能被定義它的類別訪問，其他類別無法直接訪問。
- protected: 該成員僅能被定義它的類別以及該類別的子類別訪問。
- default（沒有寫修飾詞）: 該成員僅能被同一個包中的其他類別訪問，不同包中的類別無法訪問。

##### 私有建構子

私有建構子是指只有在該類別內部可以訪問的建構子，外部無法直接使用 new 關鍵字創建該類別的對象，但仍然可以在該類別的其他方法中使用它。

通常情況下一個類別只會有一個私有建構子。這是因為私有建構子通常被用於實現特定的設計模式，如單例模式

```java
public class Singleton {
    private static Singleton instance;

    // 私有建構子，防止外部直接創建實例
    private Singleton() {
    }

    // 全局訪問點，用於獲取唯一實例
    public static Singleton getInstance() {
        if (instance == null) {
            instance = new Singleton();
        }
        return instance;
    }
}
```
