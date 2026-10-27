---
title: "recursive-deletion-in-bst"
publishDate: "2025-09-13 10:00:00"
img: /tymultiverse/assets/algorithm.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: Understanding BST Recursive Deletion Algorithm
level: advance
category: Algorithm
tags:
  - Algorithm
  - Data Structure
  - Binary Search Tree
  - Recursion
  - TreeNode
---

# BST 遞歸刪除演算法詳解

## 概述

二元搜尋樹 (Binary Search Tree, BST) 的刪除操作是資料結構中的經典問題，特別是處理有兩個子節點的情況時，需要使用「後繼節點替換」的巧妙策略。本文將深入剖析這個演算法的核心邏輯，解答常見的疑惑點。

---

## BST 刪除的三種情況

```
BST 節點刪除的三種情況
├─ 情況一：葉子節點 (無子節點)
│  ├─ 直接刪除該節點
│  └─ 返回 null 給父節點
├─ 情況二：只有一個子節點
│  ├─ 返回該子節點替換當前節點
│  └─ 保持樹的結構完整性
└─ 情況三：有兩個子節點
   ├─ 找到後繼節點 (右子樹最小值)
   ├─ 用後繼節點值替換當前節點值
   └─ 遞歸刪除後繼節點
```

---

## 核心邏輯解析

### 葉子節點的處理

```java
if (root.left == null) {
    return root.right;  // 對於葉子節點，這會返回 null
}
```

當要刪除的節點是葉子節點時：
- `root.left` 為 null
- `root.right` 為 null
- 返回 `root.right` (即 null)
- 父節點會收到這個 null 值，並將其指標設為 null

### 單子節點的處理

```java
if (root.left == null) {
    return root.right;  // 返回右子節點
} else if (root.right == null) {
    return root.left;   // 返回左子節點
}
```

這種情況直接返回存在的子節點，保持樹的連續性。

---

## 雙子節點的處理 (核心難點)

### 後繼節點的尋找

```java
// 後繼節點 (右子樹中最小的)
TreeNode successor = root.right;
while(successor.left != null){
    successor = successor.left;
}
```

後繼節點是右子樹中最小的節點，總是位於右子樹的最左邊。

### 值替換與遞歸刪除

```java
// 將要被刪除的節點的值，換成後繼節點的值
root.val = successor.val;

// 刪除那個已經被「借走」了值的後繼節點
root.right = deleteNode(root.right, successor.val);
```

這是演算法最巧妙的部分，包含兩個關鍵步驟：

---

## 解答常見疑惑

### 疑惑一：葉子節點的處理是否正確？

**問題**：當節點是葉子時，`if (root.left == null)` 條件成立，返回 `root.right` 會不會有問題？

**解答**：
```
葉子節點處理流程
├─ root.left == null ✓ (條件成立)
├─ root.right == null (對於葉子節點)
├─ 返回 root.right (即 null)
├─ 父節點收到 null，正確斷開連結
└─ 完美處理葉子節點情況
```

### 疑惑二：為什麼要替換值而不是指標？

**問題**：為什麼不直接改變指標，而是要複製後繼節點的值？

**解答**：
```
值替換 vs 指標替換
├─ 值替換優勢
│  ├─ 保持樹結構不變
│  ├─ 避免複雜指標操作
│  ├─ 只需要改變一個節點的內容
│  └─ 邏輯簡單清晰
├─ 指標替換缺點
│  ├─ 需要處理多個指標
│  ├─ 可能破壞樹的平衡
│  └─ 程式碼複雜度大幅增加
```

### 疑惑三：遞歸刪除的必要性？

**問題**：為什麼不能在找到後繼節點時就直接刪除，而要用遞歸？

**解答**：
```
遞歸刪除的必要性
├─ 後繼節點可能有右子節點
│  ├─ 後繼節點最多只有一個右子節點
│  └─ 這是 BST 性質決定的
├─ 統一處理邏輯
│  ├─ 所有刪除操作使用相同函式
│  └─ 避免重複程式碼
├─ 自動處理指標重連
│  ├─ 遞歸返回正確的子樹結構
│  └─ 父節點自動更新指標
```

---

## 實際執行範例

### 範例樹狀結構

```
原始樹狀結構
        50
       /  \
     30    70
    / \   /  \
  20  40 60  80
```

### 刪除節點 50 的過程

**步驟 1：找到要刪除的節點**
```
找到節點 50，有兩個子節點
├─ 左子樹：30
└─ 右子樹：70
```

**步驟 2：找到後繼節點**
```
後繼節點：右子樹的最小值 = 60
├─ 從根的右子節點 70 開始
├─ 檢查 70.left 是否為 null？否
├─ 往左走到 60
├─ 檢查 60.left 是否為 null？是
└─ 找到後繼節點：60
```

**步驟 3：值替換**
```
值替換過程
├─ root.val = successor.val
├─ 50 節點的值變為 60
├─ 現在根節點值是 60
├─ 樹中原本的 60 (後繼節點) 仍然存在
└─ 即將被刪除以消除重複
```

**步驟 4：遞歸刪除後繼節點**
```
刪除後繼節點 60
├─ 呼叫 deleteNode(root.right, 60)
├─ 在右子樹中尋找 60 (位於 70 的左子樹)
├─ 找到 60，發現它是葉子節點 (無子節點)
├─ 刪除 60，返回 null 給其父節點 70
└─ 70.left 更新為 null
```

**最終結果**
```
刪除完成後的樹
        60          ← 原來的 50 變為 60
       /  \
     30    70       ← 70 保持不變
    / \     \
  20  40     80     ← 60 被刪除，70 只有右子節點 80
```

---

## 程式碼實現

```java
public TreeNode deleteNode(TreeNode root, int key) {
    if (root == null) {
        return null;
    }

    if (key < root.val) {
        root.left = deleteNode(root.left, key);
    } else if (key > root.val) {
        root.right = deleteNode(root.right, key);
    } else {
        // 找到要刪除的節點
        if (root.left == null) {
            return root.right;
        } else if (root.right == null) {
            return root.left;
        }

        // 有兩個子節點的情況
        TreeNode successor = root.right;
        while (successor.left != null) {
            successor = successor.left;
        }

        // 值替換
        root.val = successor.val;

        // 遞歸刪除後繼節點
        root.right = deleteNode(root.right, successor.val);
    }

    return root;
}
```

---

## 時間複雜度分析

```
BST 刪除操作時間複雜度
├─ 平均情況：O(log n)
│  ├─ 尋找目標節點：O(log n)
│  ├─ 尋找後繼節點：O(log n)
│  └─ 刪除後繼節點：O(log n)
├─ 最壞情況：O(n)
│  └─ 當樹退化為鏈表時
└─ 空間複雜度：O(log n)
   └─ 遞歸呼叫棧的深度
```

---

## 關鍵洞察

1. **葉子節點的巧妙處理**：`if (root.left == null)` 同時處理了「無左子節點」和「葉子節點」兩種情況

2. **後繼節點的特性**：右子樹的最小值最多只有一個右子節點，這使得刪除操作變得簡單

3. **值替換策略**：透過替換值而非指標，保持樹結構穩定，同時避免複雜的指標操作

4. **遞歸的威力**：將複雜的雙子節點刪除問題，分解為簡單的單子節點刪除問題

5. **統一的處理邏輯**：所有刪除情況都使用相同的遞歸函式，程式碼簡潔優雅

這個演算法展示了遞歸思維和資料結構設計的精妙之處，值得深入學習和理解。

---

## 當目標節點不存在時的處理

### 問題情境

當我們嘗試刪除一個不存在於 BST 中的節點時，會發生什麼事？為什麼遞歸函數能夠保持樹的原狀？

### 具體例子說明

假設我們有一棵 BST，要刪除值為 25 的節點：

```
原始 BST
      50
     /  \
   30    70
  / \   /  \
20  40 60  80
```

**步驟 1：從根節點開始比較**
```
比較過程
├─ 當前節點：50
├─ 目標值：25
├─ 25 < 50，遞歸到左子樹
└─ 呼叫：deleteNode(root.left, 25)
```

**步驟 2：繼續在左子樹比較**
```
左子樹比較
├─ 當前節點：30
├─ 目標值：25
├─ 25 < 30，遞歸到左子樹
└─ 呼叫：deleteNode(30.left, 25)
```

**步驟 3：到達葉子節點附近**
```
葉子節點處理
├─ 當前節點：20
├─ 目標值：25
├─ 25 > 20，應該遞歸到右子樹
├─ 但 20.right == null
└─ 呼叫：deleteNode(null, 25)
```

**步驟 4：遇到空節點**
```
空節點處理
├─ 當前節點：null
├─ 函數返回：null
├─ 20.right 原本就是 null
└─ 樹結構完全沒有改變
```

### 為什麼樹能維持原狀？

```
維持原狀的原因分析
├─ 遞歸終止條件
│  ├─ 當 root == null 時，直接返回 null
│  └─ 不會執行任何刪除操作
├─ 指標不變性
│  ├─ 父節點收到 null 後
│  ├─ 會將其子指標設為 null
│  └─ 但原本就是 null，所以無變化
├─ 遞歸回溯
│  ├─ 每一層遞歸都返回正確的值
│  └─ 但由於沒有實際刪除，樹結構保持完整
```

### 程式碼層面的驗證

```java
public TreeNode deleteNode(TreeNode root, int key) {
    // 當節點不存在時的處理
    if (root == null) {
        return null;  // 直接返回，不改變任何東西
    }

    if (key < root.val) {
        // 遞歸到左子樹，但左子樹可能不存在
        root.left = deleteNode(root.left, key);
        // 如果左子樹原本就是 null，deleteNode 會返回 null
        // root.left 仍然是 null，樹不變
    } else if (key > root.val) {
        // 類似邏輯適用於右子樹
        root.right = deleteNode(root.right, key);
    }
    // 如果找到節點，才會執行刪除邏輯

    return root;  // 返回原來的根，樹結構完整
}
```

### 關鍵洞察

1. **空節點的安全處理**：`if (root == null) return null` 確保了當節點不存在時，不會發生任何副作用

2. **指標賦值的冪等性**：即使我們執行 `root.left = null`，如果 `root.left` 原本就是 `null`，那麼這個操作就是冪等的（不會改變結果）

3. **遞歸的穩定性**：遞歸函數始終返回正確的值，無論是找到了要刪除的節點還是沒有找到

4. **樹結構的保全性**：當目標節點不存在時，整個遞歸過程就像是一次「尋找之旅」，找到了就刪除，找不到就安全返回，樹的結構完全不受影響

這個特性使得 BST 的刪除操作具有高度的**安全性**和**預測性**，無論輸入什麼值，都不會意外破壞樹的結構。

---

## 為什麼要替換 root.right 而不是直接替換 root？

### 你的疑問

你問得很好！為什麼我們要用 `root.right = deleteNode(root.right, successor.val)` 來替換 `root.right`，而不是直接用 `root = successor` 來替換整個 `root`？

### 讓我們用具體例子來理解

假設我們有一棵 BST，要刪除根節點 50：

```
原始樹狀結構
        50
       /  \
     30    70
    / \   /  \
  20  40 60  80
```

**如果我們直接用 `root = successor`：**

```java
// 錯誤的做法
TreeNode successor = findSuccessor(root.right);  // successor = 60
root = successor;  // 直接替換整個 root
```

**這樣會發生什麼？**

```
錯誤結果：直接替換 root
        60          ← 現在 root 指向 60
       /  \
     30    70       ← 30 和 70 仍然連接
    / \   /  \
  20  40 60  80     ← 但現在有兩個 60！
         ^
         └── 這是原來的 60，沒有被刪除！
```

**問題在哪裡？**
1. 原來的 60 節點沒有被刪除，樹中有重複值
2. 30 和 40 的連接關係被破壞
3. BST 的結構被嚴重破壞

### 正確的做法：替換 root.right

```java
// 正確的做法
root.val = successor.val;  // 先替換值：50 變成 60
root.right = deleteNode(root.right, successor.val);  // 然後刪除重複的 60
```

**執行過程：**

**步驟 1：值替換**
```
值替換後
        60          ← 50 變成 60
       /  \
     30    70       ← 右子樹保持不變
    / \   /  \
  20  40 60  80     ← 原來的 60 還在，需要刪除
```

**步驟 2：刪除重複節點**
```
呼叫：deleteNode(root.right, 60)
├─ 在右子樹中尋找 60
├─ 找到 60（70 的左子節點）
├─ 60 是葉子節點，直接刪除
├─ 返回 null 給 70.left
└─ 70.left = null
```

**最終正確結果**
```
正確的結果
        60          ← 原本的 50 節點
       /  \
     30    70       ← 右子樹根節點
    / \     \
  20  40     80     ← 60 被刪除，70 只有右子節點
```

### 為什麼不能直接替換 root？

```
直接替換 root 的問題
├─ 指標問題
│  ├─ root 原本指向 50
│  ├─ successor 指向 60
│  └─ 替換後，30 和 40 的連接會丟失
├─ 重複值問題
│  ├─ 原來的 60 節點沒有被刪除
│  └─ 樹中會有兩個 60
├─ 結構破壞
│  ├─ 整個左子樹可能會丟失
│  └─ BST 性質被徹底破壞
```

### 正確做法的核心邏輯

```
正確的雙子節點刪除邏輯
├─ 值替換階段
│  ├─ root.val = successor.val
│  ├─ 只改變值，不改變指標
│  └─ 保持樹的結構完整
├─ 清理階段
│  ├─ root.right = deleteNode(root.right, successor.val)
│  ├─ 在右子樹內部刪除 successor
│  └─ 重建右子樹的正確結構
```

### 關鍵差異總結

| 操作 | 直接替換 root | 正確的替換 root.right |
|------|---------------|----------------------|
| **影響範圍** | 整個樹的結構 | 只影響右子樹 |
| **指標變化** | 破壞原有連接 | 保持原有連接 |
| **重複值處理** | 不處理 | 正確刪除重複值 |
| **BST 性質** | 完全破壞 | 完全保持 |

**所以答案是**：我們要替換 `root.right` 而不是直接替換 `root`，是因為：
1. **保護樹的結構**：避免破壞現有的指標連接
2. **正確刪除重複值**：確保沒有重複節點留在樹中
3. **保持 BST 性質**：維護二元搜尋樹的排序特性

這個設計展示了演算法設計中「最小化干擾」的智慧：我們只改變必要的部分，保持其他部分不變。

---

## 為什麼 root.right 不是 70 而要去找「最左」？

### 你的困惑

你問得非常精準！你看到 `60 ← 原來的 50 變為 60` 這段描述，理解這是透過 `root.val = successor.val` 來進行的值替換。

但是你困惑：既然 `root.val` 已經變成了 60，那麼 `root.right` 應該還是指向 70 才對，為什麼還要去找「最左」？

### 讓我們一步步釐清

假設我們有一棵 BST，要刪除根節點 50：

```
原始樹狀結構
        50
       /  \
     30    70
    / \   /  \
  20  40 60  80
```

**步驟 1：找到後繼節點**
```
後繼節點：右子樹的最小值 = 60
├─ successor 指向的是 60 這個節點
├─ successor.val = 60
└─ successor 位於 70.left
```

**步驟 2：值替換**
```java
root.val = successor.val;  // 50 變成 60
```

```
值替換後的狀態
        60          ← root.val 現在是 60
       /  \
     30    70       ← root.right 仍然指向 70
    / \   /  \
  20  40 60  80     ← 原來的 60 還在這裡！
         ^
         └── successor 指向的節點
```

### 關鍵問題：樹中有兩個 60！

```
此時的問題
├─ 根節點的值是 60（原本的 50）
├─ 右子樹中還有一個 60（原本的 60）
├─ BST 中不能有重複值！
└─ 必須刪除多餘的那個 60
```

### 為什麼要呼叫 `root.right = deleteNode(root.right, successor.val)`？

```java
// successor.val = 60
root.right = deleteNode(root.right, successor.val);
```

**這個呼叫的意思是：**
```
在右子樹中尋找並刪除值為 60 的節點
├─ root.right 指向 70
├─ 在以 70 為根的子樹中尋找 60
├─ 60 位於 70.left
├─ 刪除 60 後，70.left = null
```

**為什麼不是直接操作 successor？**

```
不能直接操作 successor 的原因
├─ successor 是一個區域變數，指向 60 節點
├─ 我們需要更新父節點（70）的指標
├─ 直接刪除 successor 會破壞樹的結構
├─ 必須透過父節點來重新連接
```

### 完整的執行流程

**步驟 1：值替換**
```java
root.val = successor.val;  // 50 → 60
```

**步驟 2：刪除重複節點**
```java
// 在右子樹中尋找並刪除值為 60 的節點
root.right = deleteNode(root.right, 60);
```

**遞歸刪除的詳細過程：**
```
deleteNode(70, 60) 的執行過程
├─ 當前節點：70
├─ 目標值：60
├─ 60 < 70，遞歸到左子樹
├─ 呼叫：deleteNode(70.left, 60)
│
├─ 現在處理 60 這個節點
├─ 找到節點 60（successor）
├─ 60 是葉子節點（無子節點）
├─ 返回 null 給父節點 70
├─ 70.left = null
```

**最終結果**
```
刪除完成
        60          ← 原本的 50，值已替換
       /  \
     30    70       ← 右子樹根節點
    / \     \
  20  40     80     ← 60 已刪除，70 只有右子節點
```

### 為什麼 root.right 一開始是 70？

```
root.right 保持指向 70 的原因
├─ 值替換只改變 root.val，不改變指標
├─ root.right 仍然指向原本的右子樹根節點
├─ 這是「最小化干擾」的設計原則
├─ 保持樹的結構穩定，只改變必要的值
```

### 總結

**所以答案是**：`root.right` 一開始確實指向 70，我們呼叫 `deleteNode(root.right, successor.val)` 是為了：

1. **在右子樹內部**尋找 successor（60）
2. **正確刪除重複節點**，並更新父節點的指標
3. **重建右子樹的結構**，確保沒有重複值

這就是為什麼我們要「找最左」的原因：successor 總是位於右子樹的最左邊，我們需要在右子樹內部找到並刪除它，而不是直接操作 successor 指標。

這個設計確保了：
- ✅ 沒有重複值留在樹中
- ✅ 樹的結構保持正確
- ✅ BST 的排序性質得到維護
- ✅ 所有指標連接都正確重建
