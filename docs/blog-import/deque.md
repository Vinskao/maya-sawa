---
title: "deque"
publishDate: "2025-03-05 18:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  Deque (ArrayDeque) 標準語法速查表，包含 Stack、Queue 和雙端操作的完整語法對照
category: Algorithm
tags:
  - algorithm
  - data-structure
  - deque
  - Java
  - stack
  - queue
---

# Deque (ArrayDeque) 標準語法速查

## 操作對照表

| 目的 | Stack (LIFO: 後進先出) | Queue (FIFO: 先進先出) | 雙端操作 (Deque) |
|------|------------------------|------------------------|------------------|
| **新增** | `push(E e)`：新增到頭部 | `add(E e)` / `offer(E e)`：新增到尾部 | `addFirst(E e)` / `addLast(E e)` |
| **移除** | `pop()`：從頭部移除並返回 | `remove()` / `poll()`：從頭部移除並返回 | `removeFirst()` / `removeLast()` |
| **查看** | `peek()`：查看頭部元素（不移除） | `element()` / `peek()`：查看頭部元素（不移除） | `getFirst()` / `getLast()` |

## 使用範例

### Stack 操作 (LIFO)
```java
Deque<Integer> stack = new ArrayDeque<>();

// 新增元素到頭部
stack.push(1);
stack.push(2);
stack.push(3);

// 查看頭部元素
System.out.println(stack.peek()); // 輸出: 3

// 移除頭部元素
System.out.println(stack.pop());  // 輸出: 3
System.out.println(stack.pop());  // 輸出: 2
```

### Queue 操作 (FIFO)
```java
Deque<Integer> queue = new ArrayDeque<>();

// 新增元素到尾部
queue.add(1);
queue.add(2);
queue.add(3);

// 查看頭部元素
System.out.println(queue.peek()); // 輸出: 1

// 移除頭部元素
System.out.println(queue.poll()); // 輸出: 1
System.out.println(queue.poll()); // 輸出: 2
```

### 雙端操作
```java
Deque<Integer> deque = new ArrayDeque<>();

// 雙端新增
deque.addFirst(1);  // 頭部新增
deque.addLast(2);   // 尾部新增
deque.addFirst(3);  // 頭部新增

// 雙端查看
System.out.println(deque.getFirst()); // 輸出: 3
System.out.println(deque.getLast());  // 輸出: 2

// 雙端移除
System.out.println(deque.removeFirst()); // 輸出: 3
System.out.println(deque.removeLast());  // 輸出: 2
```

## 重要特性

- **ArrayDeque** 是 Deque 接口的高效實現
- 支持 **Stack** 和 **Queue** 兩種操作模式
- 提供 **雙端操作** 的靈活性
- **無容量限制**，自動擴展
- **非線程安全**，需要外部同步
