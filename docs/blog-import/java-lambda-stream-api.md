---
title: "java-lambda-stream-api"
publishDate: "2024-03-04 17:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/02/26
category: Java
tags:
  - Lambda
  - ->
  - "::"
  - Java
---

#### Lambda 表達式

Lambda 表達式是 Java 8 中引入的一個重要特性，它可以用來建立匿名函數（或稱為閉包），從而實現函數式程式設計的一些特性。 Lambda 表達式主要用於簡化函數式介面（Functional Interface）的實作。

```java
// Lambda 表達式範例
Runnable runnable = () -> System.out.println("Hello Lambda!");
Consumer<String> consumer = (String s) -> System.out.println(s);
Function<String, Integer> function = (String s) -> s.length();
```

#### ::

Java 8 中，雙冒號 :: 是一種新的語法，用於建立方法參考（Method Reference）。 它可以簡化 Lambda 表達式。

假設有以下功能可以被調用。

```java
public class SomeClass {
    public static void someMethod(String s) {
        System.out.println(s);
    }
}
```

分別用 Lambda、::調用以上方法：

- 用 Lambda 調用 someMethod()。

  ```java
  Consumer<String> consumer = (String s) -> SomeClass.someMethod(s);
  ```

- 用 :: 調用 someMethod()。

  ```java
  Consumer<String> consumer = SomeClass::someMethod;
  ```

#### Stream 流

使用 Stream 來處理集合、數組或其他元素的序列。可分為資料來源、中間操作、終端操作(操作共 2 類)來討論流的功能實現。中間操作與終端操作的差異是:

- 中間操作：只有轉換或處理流中的元素，在終端操作被調用時才會執行。
- 終端操作：決定數據最終型態，一旦終端操作被調用，流就會被消耗並且不能再被使用。

stream 後面一定要加終端操作，但不一定要加中間操作。

##### 資料來源

流的資料來源有以下三種：

- 集合： 可以使用集合類（如 List、Set、Map 等）的 stream() 方法來創建流。

  1.  new ArrayList<>().stream()

  ```java
  Stream<Object> streamArrayList = new ArrayList<>().stream();
  ```

  2. new HashSet<>().stream()

  ```java
  Stream<Object> streamHashSet = new HashSet<>().stream();
  ```

  3. new HashMap<>().entrySet().stream()

  ```java
  Stream<Map.Entry<Object, Object>> streamEntrySet = new HashMap<>().entrySet().stream();
  ```

  4. new HashMap<>().keySet().stream()

  ```java
  Stream<Object> streamKeySet = new HashMap<>().keySet().stream();
  ```

  5. new HashMap<>().values().stream()

  ```java
  Stream<Object> streamValues = new HashMap<>().values().stream();
  ```

- 數組： 可以使用.stream() 方法來將數組轉換為流。

  1. Arrays.stream(array)

  ```java
  int[] array = {1, 2, 3, 4, 5};
  IntStream stream = Arrays.stream(array);
  ```

- 文件： 可以使用 Files.lines() 方法來讀取文件的每一行並將其轉換為流。例如：Files.lines(Paths.get("file.txt"))。

##### 中間操作

篩選： 使用 filter() 方法來根據條件過濾流中的元素。

映射： 使用 map() 方法將流中的每個元素映射到另一個值。

排序： 使用 sorted() 方法對流中的元素進行排序。

去重： 使用 distinct() 方法去除流中的重複元素。

限制： 使用 limit() 方法來限制流中元素的數量。

跳過： 使用 skip() 方法來跳過流中的前幾個元素。

##### 終端操作

收集： 使用 collect() 方法將流中的元素收集到一個集合中。

迭代： 使用 forEach() 方法對流中的每個元素進行遍歷並執行指定的操作。

匹配： 使用 anyMatch()、allMatch() 或 noneMatch() 方法來檢查流中的元素是否符合指定的條件。

計數： 使用 count() 方法來計算流中的元素數量。

查找： 使用 findAny() 或 findFirst() 方法來查找流中的任意一個元素或第一個元素。

彙總： 使用 reduce 將流中的元素進行累加、組合或者進行其他的彙總操作。它接受一個組合函數（binary operator）作為參數，並使用這個函數來將流中的元素進行累加或者組合。

##### filter 搭配 collect 排序並收集流中元素

以下將用不同方式排序這個陣列 int[] array = {5, 1, 3, 2, 4};。

1. Array to ArrayList

```java
List<Integer> list = Arrays.stream(array).boxed().collect(Collectors.toList()); // [5, 1, 3, 2, 4]
List<Integer> sortedList = Arrays.stream(array).sorted().boxed().collect(Collectors.toList()); // [1, 2, 3, 4, 5]
// 不加boxed()會錯，要加基礎型別int轉成參用Integer才能調用方法，reason: no instance(s) of type variable(s) A, T exist so that Collector<T, A, List<T>> conforms to Supplier<R>
```

2. ArrayList to ArrayList

```java
ArrayList<Integer> arrayList = new ArrayList<>();
for (int num : array) {
    arrayList.add(num);
}
List<Integer> streamArrayList = arrayList.stream().sorted().collect(Collectors.toList());
System.out.println(streamArrayList); // [1, 2, 3, 4, 5]
```

3. HashSet to HashSet

沒有加 sorted 就變成排序的結果，因為在 HashSet 中，元素的順序通常是不確定的，它是根據哈希碼來存儲元素的。在某些情況下，將 HashSet 轉換為流並收集回集合時，Java 可能會重新安排元素，以便它們按照它們的自然排序出現，每個 Java 版本可能有差異。

LinkedHashSet 也繼承 HashSet 且不可重複，但是是有序的。所以在使用 sorted 後應該用 LinkedHashSet 來接才合理。

```java
Set<Integer> set = new HashSet<>();
for (int num : array) {
    set.add(num);
}
Set<Integer> streamHashSet = set.stream().collect(Collectors.toCollection(HashSet::new));
// [1, 2, 3, 4, 5]
// HashSet::new 表示調用 HashSet 類的無參數建構子，用來創建一個新的 HashSet 物件
Set<Integer> sortedHashSet = set.stream().sorted().collect(Collectors.toCollection(LinkedHashSet::new));
// [1, 2, 3, 4, 5]
```

4. HashMap to HashMap，使用 entrySet

原始 key 是{1, 2, 3, 4, 5}，value 是{5, 1, 3, 2, 4}。使用 comparingByKey 排序就會是排序 key，comparingByValue 就是排序值。

```java
HashMap<Integer, Integer> originalMap = new HashMap<>();
for(int i=0; i < array.length; i++){
    originalMap.put(i+1, array[i]);
}
LinkedHashMap<Integer, Integer> sortedByKey = originalMap.entrySet().stream()
        .sorted(Map.Entry.comparingByKey())
        .collect(LinkedHashMap::new, (map,entry) -> map.put(entry.getKey(), entry.getValue()),LinkedHashMap::putAll);
        // {1=5, 2=1, 3=3, 4=2, 5=4}

LinkedHashMap<Integer, Integer> sortedByValue = originalMap.entrySet().stream()
        .sorted(Map.Entry.comparingByValue())
        .collect(LinkedHashMap::new, (map,entry) -> map.put(entry.getKey(), entry.getValue()),LinkedHashMap::putAll);
        // {2=1, 4=2, 3=3, 5=4, 1=5}
```

在 collect() 方法中，逗號分隔的每個部分都代表了不同的功能：

1. LinkedHashMap::new, 建立一個 LinkedHashMap 容器。
2. (map, entry) -> 是一個 BiConsumer，是 Lambda 表達式的語法，它接受兩個參數 map 和 entry，將鍵值放入 LinkedHashMap。
3. LinkedHashMap::putAll 表示當元素被收集到 BiConsumer 後，要呼叫 LinkedHashMap 的 putAll 方法，將元素加入新的 LinkedHashMap 中。

##### 用 reduce 加總整數陣列

```java
Integer[] n = {5, 10 ,15 ,20 ,25 };
int sum2 = Arrays.stream(n).reduce(0, Integer::sum);
```

## 深入理解 Lambda 與 Stream

- **Lambda 表達式：** 可大幅簡化匿名內部類的寫法，建議多練習其語法精髓與應用場景。
- **方法參考 (::)：** 快速綁定已存在的方法，適用於靜態與實例方法，提升代碼可讀性。
- **Stream 操作：** 熟悉中間操作與終端操作的執行時機，有助於撰寫高效資料處理流水線。

## 常見最佳實踐

- **資源釋放：** 確認使用後適當關閉或釋放 Stream 資源（例如使用 try-with-resources）。
- **錯誤處理：** 確認在複雜流操作中加入適當的異常捕捉，避免意外中斷。
