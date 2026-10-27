---
title: "java-collections-list-set-map"
publishDate: "2024-03-04 16:00:00"
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
---

# List, Set, Map & Array in Java

## Overview

本文詳細介紹了 Java 中常用的資料結構：List、Set、Map 以及 Array。透過各自的特性、操作與示例程式碼，幫助您理解如何有效地管理資料集合。

## java.util.List

### Characteristics

1. **有序性**：元素依照插入順序排列。  
2. **允許重複**：相同元素可以多次出現。  
3. **可變性**：可利用 `add()`、`remove()`、`clear()`、`set()` 等方法修改集合內容。

### Example

```java
List<String> list = new ArrayList<>();
list.add("apple");
list.add("banana");
list.add("apple"); // 允許重複
System.out.println(list.get(2)); // 輸出: apple
System.out.println(list);        // 輸出: [apple, banana, apple]
list.remove("banana");
System.out.println(list);        // 輸出: [apple, apple]
list.clear();
System.out.println(list);        // 輸出: []
```

### 遍歷 List

使用 for-each 迴圈：

```java
List<String> listStrings = new ArrayList<>();
listStrings.add("Red");
listStrings.add("Green");
listStrings.add("Orange");

for (String element : listStrings) {
    System.out.println(element);
}
```

### 加總 List 中的數字

#### For-Each 迴圈

```java
List<Integer> numbers = new ArrayList<>();
numbers.add(5);
numbers.add(10);
numbers.add(15);

int sum = 0;
for (int num : numbers) {
    sum += num;
}
```

#### 使用 Stream API

```java
Integer[] n = {5, 10, 15, 20, 25};
int sum2 = Arrays.stream(n).reduce(0, Integer::sum);
```

## java.util.Set

### Characteristics

1. **無序性**：Set 不保證元素的順序。  
2. **唯一性**：重複元素只會保留一份。  
3. **可變性**：可以使用 `add()`、`remove()`、`clear()` 修改內容。

### Example

```java
Set<String> set = new HashSet<>();
set.add("apple");
set.add("banana");
set.add("apple"); // 重複會被忽略
System.out.println(set.size()); // 輸出: 2
set.remove("apple");
System.out.println(set.size()); // 輸出: 1
```

### 遍歷並加總 Set

加入元素：

```java
Set<Integer> set2 = new HashSet<>();
set2.addAll(Arrays.asList(2, 3, 5, 6)); // 新增 [2, 3, 5, 6]
```

加總：

```java
int sum = 0;
for (int n : set2) {
    sum += n;
}
System.out.println(sum); // 輸出: 16
```

或使用 Iterator：

```java
Iterator<Integer> iterator = set2.iterator();
while(iterator.hasNext()){
    Integer n = iterator.next();
    sum += n;
}
```

## java.util.Map

### Characteristics

1. **Key-Value 儲存**：每個元素以 key-value 形式存放。  
2. **Key 唯一**：鍵值必須唯一，值則可以重複。  
3. **無序性**：元素順序不固定。

### Example

```java
Map<String, Integer> myMap = new HashMap<>();
myMap.put("apple", 3);
myMap.put("banana", 2);
myMap.put("apple", 5); // 覆蓋之前的值
System.out.println(myMap); // 輸出: {banana=2, apple=5}
myMap.remove("banana");
System.out.println(myMap); // 輸出: {apple=5}
myMap.clear();
System.out.println(myMap); // 輸出: {}
```

### 遍歷 Map

#### 使用 keySet()

```java
for (Integer key : myMap.keySet()) {
    String value = myMap.get(key);
    System.out.println(value);
}
```

#### 使用 entrySet()

```java
for (Map.Entry<Integer, String> entry : myMap.entrySet()) {
    Integer key = entry.getKey();
    String value = entry.getValue();
    System.out.printf("Key: %d; Value: %s%n", key, value);
}
```

#### 使用 forEach() (Java 8+)

```java
myMap.forEach((key, value) -> {
    System.out.println(value);
});
```

## Array in Java

陣列在實例化時必須指定固定長度，其預設值為零（對於數值型別）。

```java
int[] myArray = new int[5];
myArray[0] = 10;
myArray[1] = 20;
myArray[2] = 30;
System.out.println(myArray[2]); // 輸出: 30
System.out.println(myArray[3]); // 輸出: 0 (預設值)
```

