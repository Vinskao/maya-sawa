---
title: "java-treenode"
publishDate: "2025-09-10 16:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/02/26
category: Java
tags:
  - Java
  - List
  - Set
  - Map
  - Array
  - TreeNode
  - Binary Tree
  - Data Structure
---

# Java TreeNode 深入解析

## BST 插入節點的遞歸解法

Exactly, that's the correct way to handle the base case. The line `if(root == null) return new TreeNode(val);` is the key to the entire recursive solution. When the recursion finds a null spot, it creates a new node and returns it, and that return value is then used to link the new node back into the tree.

## TreeNode 的底層實現

TreeNode 的底層實現是一個簡單的類別或結構體，用來代表二元樹中的一個節點。在絕大多數的程式語言中，它通常會包含以下三個核心屬性：

- **val (值)**: 這個屬性儲存了節點本身的值。在 LeetCode 的題目中，這通常是一個整數 (int)。

- **left (左子節點)**: 這個屬性是一個指向另一個 TreeNode 物件的指標 (pointer) 或參考 (reference)。它指向當前節點的左子樹的根節點。如果沒有左子節點，這個指標就是 null。

- **right (右子節點)**: 和 left 類似，它指向當前節點的右子樹的根節點。如果沒有右子節點，這個指標就是 null。

簡單來說，TreeNode 就像是一個帶有兩個連結的容器。這兩個連結（left 和 right）讓你可以將多個 TreeNode 物件串聯起來，形成一個完整的樹狀結構。

## Java TreeNode 實現

在 Java 中，TreeNode 的實現大致會長這樣：

```java
public class TreeNode {
    int val;
    TreeNode left;
    TreeNode right;

    // 預設建構子
    TreeNode() {}

    // 帶值的建構子
    TreeNode(int val) {
        this.val = val;
    }

    // 完整建構子
    TreeNode(int val, TreeNode left, TreeNode right) {
        this.val = val;
        this.left = left;
        this.right = right;
    }
}
```

## TreeNode 作為簡單的 Bean 結構

你的觀察非常準確，從底層來看，TreeNode 確實只是一個簡單的 Java Bean (或 POJO) 結構。它沒有任何複雜的方法或業務邏輯，其主要作用就是作為一個資料容器，用來封裝和組織二元樹節點的資訊。

這個簡單的結構，正是它能夠被廣泛應用於二元樹演算法的關鍵。透過 val、left 和 right 這三個屬性，我們可以輕易地建構出各種複雜的樹狀結構，並透過對指標的操縱來實現各種演算法。

既然你已經掌握了這個核心概念，你還想了解更多關於在 BST 中插入節點的完整程式碼實現嗎？
