---
title: "java-string-repeat-stringbuilder"
publishDate: "2024-02-28 23:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/02/26
category: Java
tags:
  - String
  - StringBuilder
  - Java
---

#### 使用 API：repeat()

repeat(int count)是 String 類別的方法，用於建立由該字串重複特定次數形成的新字串。 此方法是 Java 11 中新增的功能。

```java
String str = "Java Exercises!";
System.out.println(str.repeat(3));
// Java Exercises!Java Exercises!Java Exercises!
```

如果不使用 repeat 需要怎麼達成相同結果?

##### StringBuilder

StringBuilder 是 Java 中用於動態建構字串的一個類別。

```java
public class T1 {
    public String repeat(int count) {
        if (count <= 0) {
            return "";
        }

        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < count; i++) {
            sb.append("Java Exercises!");
        }
        return sb.toString();
    }

    public static void main(String[] args) {
        T1 t1 = new T1();
        System.out.println(t1.repeat(3));
        // Java Exercises!Java Exercises!Java Exercises!
    }
}
```

##### StringBuilder 接龍

```java
StringBuilder sb = new StringBuilder();
sb.append("Hello");
sb.append(" ");
sb.append("World");
String result = sb.toString(); // "Hello World"
```

##### StringBuilder 帶有初始容量

```java
StringBuilder sb = new StringBuilder(20); // 初始容量為20
sb.append("This is a long string that may require resizing.");
// StringBuilder在內部會根據需要自動擴展其緩衝區的大小以容納更多的字元。 如果字串的長度超過了初始容量，StringBuilder會自動重新分配一個更大的緩衝區
```

如果不使用 repeat 及 StringBuilder 需要怎麼達成相同結果? 用+=。

```java
public class T1 {
    public static void main(String[] args) {
        String str = "Java Exercises!";
        System.out.println(repeat2(str, 3));
        // Java Exercises!Java Exercises!Java Exercises!
    }

    public static String repeat2(String str, int count) {
        if (count <= 0) {
            return "";
        }

        String repeated = "";
        for (int i = 0; i < count; i++) {
            repeated += str;
        }

        return repeated;
    }
}
```

#### 半塔

```
*
**
***
****
*****
```

###### 1. 使用 repeat()

```java
int totalHeight = 5;
String space = " ";
String star = "*";

for (int i = 0; i < totalHeight + 1 ; i++){
    System.out.print(star.repeat(i));
    System.out.println();
}
```

###### 2. 使用 repeat()，並用 StringBuilder 打包

```java
public class Pyramid {
    int totalHeight = 5;
    String space = " ";
    String star = "*";
    public static void main(String[] args) {
        Pyramid p = new Pyramid();
        System.out.println(p.halfPyramid1());
    }
    public String halfPyramid1(){
        StringBuilder rs = new StringBuilder();
        for (int i = 0; i < totalHeight + 1 ; i++){
            rs.append(star.repeat(i)).append("\n");
        }
        return rs.toString();
        // 如果不呼叫.toString()方法，result將保持為一個StringBuilder物件而不是一個字串物件。
    }
}
```

###### 3. 只用 StringBuilder 與迴圈

為了要換行，使用兩個 for。

```java
// 其他設定跟上面一樣
public String halfPyramid2(){
    StringBuilder rs = new StringBuilder();
    for (int i = 0; i < totalHeight + 1 ; i++){
        // 外迴圈執行6次
        for(int j = 0; j < i; j++){
            // 內迴圈執行5次，5層的*
            // 第1行（i=0），內迴圈不會執行，因為j<i為false
            // 第2行（i=1），內循環執行1次，新增1個星號
            // 第3行（i=2），內循環執行2次，新增2個星號
            // ...
            // 第6行（i=5），內循環執行5次，新增5個星號
            rs.append(star);
        }
        rs.append("\n"); // 內迴圈每次執行完出來就換行
    }
    return rs.toString();
}
```

#### 鬆金字塔

```
    *
   * *
  * * *
 * * * *
* * * * *
```

n + 1 就是我們要的金字塔每層數量。

- n = 0，1 個。
- n = 1，2 個。
- n = 2，3 個。
- n = 3，4 個。

###### 1. 使用 repeat()

```java
int totalHeight = 5;
String space = " ";
String sonStar = "* ";

for (int i=0; i < totalHeight; i++){
    // run 6 times
    System.out.print(space.repeat(totalHeight-i-1));
    System.out.print(sonStar.repeat(i+1));
    System.out.println();
}
```

###### 2. 使用 repeat()，並用 StringBuilder 打包

```java
// 其他設定跟上面一樣
public String sonPyramid1(){
    StringBuilder rs = new StringBuilder();
    for (int i =0 ; i < totalHeight; i++){
        // run 5 times
        rs.append(space.repeat(totalHeight - i - 1));
        // 第1圈i=0，重複4次空格
        // 第2圈i=1，重複3次空格
        // 第5圈i=4，重複0次空格
        rs.append(sonStar.repeat(i + 1)).append("\n");
        // 第1圈i=0，重複1次星號
        // 第2圈i=1，重複2次星號
        // 第5圈i=4，重複5次星號
    }
    return rs.toString();
    // 塔上會有一行空白列
}
```

###### 3. 只用 StringBuilder 與迴圈

```java
// 其他設定跟上面一樣
public String sonPyramid2(){
    StringBuilder rs = new StringBuilder();
    for (int i =0 ; i < totalHeight; i++){
        // run 6 times
        for(int j = 0; j < totalHeight - i -1; j++){
            rs.append(space);
            // 第1圈i=0，重複4次空格
            // 第2圈i=1，重複3次空格
            // 第5圈i=4，重複0次空格
        }
        for(int j = 0; j < i + 1; j++){
            rs.append(sonStar);
            // 第1圈i=0，重複1次星號
            // 第2圈i=1，重複2次星號
            // 第5圈i=4，重複5次星號， j < i+1 所以j 在第5圈應該跑 5次
        }
        rs.append("\n");
    }
    return rs.toString();
}
```

#### 金字塔

```
     *
    ***
   *****
  *******
 *********
```

2n + 1 就是我們要的金字塔每層數量。

- n = 0，1 個。
- n = 1，3 個。
- n = 2，5 個。
- n = 3，7 個。

###### 1. 使用 repeat()

```java
int totalHeight = 5;
String space = " ";
String star = "*";

for (int i = 0; i < totalHeight; i++){
    // 執行5次
    // 空格分別重複4、3、2、1、0次
    System.out.print(space.repeat(totalHeight - i -1));
    // 空格分別重複1、3、5、7、9次
    System.out.println(star.repeat(2 * i + 1));
}
```

###### 2. 使用 repeat()，並用 StringBuilder 打包

```java
public String triPyramid1(){
    StringBuilder rs = new StringBuilder();
    for (int i = 0; i < totalHeight; i++){
        rs.append(space.repeat(totalHeight - i -1));
        rs.append(star.repeat(2 * i + 1)).append("\n");
    }
    return rs.toString();
}
```

###### 3. 只用 StringBuilder 與迴圈

```java
public String triPyramid2(){
    StringBuilder rs = new StringBuilder();
    for (int i = 0; i < totalHeight; i++){
        for(int j = 0; j < totalHeight - i - 1; j++){
            rs.append(space);
        }
        // 在每行中加上星號，每層星號數量為2n+1
        for(int j = 0; j < 2 * i + 1; j++) {
            rs.append(star);
        }
        rs.append("\n"); // 要放迴圈外，因為只需要重複5次
    }
    return rs.toString();
}
```

#### 斜晶塔

```
    *
   * *
  * * *
 * * * *
* * * * *
 * * * *
  * * *
   * *
    *
```

###### 1. 使用 repeat()

```java
int totalHeight = 5;
String star = "*";
String starSpace = "* ";

for (int i=0; i < totalHeight; i++){
    System.out.print(space.repeat(totalHeight-i));
    System.out.print(starSpace.repeat(i));
    System.out.println();
}

for (int i = totalHeight ; i > 0; i--){
    System.out.print(space.repeat(totalHeight-i));
    System.out.print(starSpace.repeat(i));
    System.out.println();
}
```

###### 2. 使用 repeat()，並用 StringBuilder 打包

```java
public String shard1(){
    StringBuilder rs = new StringBuilder();
    for (int i =0 ; i < totalHeight; i++){
        // run 5 times
        rs.append(space.repeat(totalHeight - i -1));
        rs.append(sonStar.repeat(i + 1)).append("\n");
    }
    for (int i = totalHeight - 1  ; i > 0; i--){
        // run 4 times
        // 第1圈i=4，重複1次空格
        // 第2圈i=3，重複2次空格
        // 第4圈i=1，重複4次空格
        rs.append(space.repeat(totalHeight - i));
        // 第1圈i=4，重複4次星號
        // 第2圈i=3，重複3次星號
        // 第4圈i=1，重複1次星號
        rs.append(sonStar.repeat(i)).append("\n");
    }
    return rs.toString();
}
```

###### 3. 只用 StringBuilder 與迴圈

```java
public String shard2(){
    StringBuilder rs = new StringBuilder();

    for (int i =0 ; i < totalHeight; i++){
        // run 5 times
        for(int j = 0; j < totalHeight - i - 1; j++){
            rs.append(space);
        }
        for(int j = 0; j < i + 1; j++){
            rs.append(sonStar);
        }
        rs.append("\n");
    }

    for (int i = totalHeight - 1  ; i > 0; i--){
        // run 4 times
        // 第1圈j=5-4=1，重複1次空格
        // 第2圈j=5-3=2，重複2次空格
        // 第4圈j=5-1=4，重複4次空格
        for(int j = totalHeight - i; j > 0; j--){
            rs.append(space);
        }
        // 第1圈j=4，重複4次*
        // 第2圈j=3，重複3次*
        // 第4圈j=1，重複1次*
        for(int j = i; j > 0; j--) {
            rs.append(sonStar);
        }
        rs.append("\n");
    }
    return rs.toString();
}
```

#### 正晶塔

```
     *
    ***
   *****
  *******
 *********
  *******
   *****
    ***
     *
```

###### 1. 使用 repeat()

使用 String.repeat(n) 方法，其中 n 是 0 或負數，則會返回一個空字串。

```java
int totalHeight = 5;
String space = " ";
String star = "*";

for (int i = 0; i < totalHeight; i++){
    System.out.print(space.repeat(totalHeight - i));
    if (i > 0) {
        System.out.println(star.repeat(i)+star.repeat(i)+star);
    } else {
        System.out.println(star);
    }
}
for (int i = totalHeight ; i > 1; i--){
    System.out.print(space.repeat(totalHeight - i + 2));
    System.out.println(star.repeat(i - 1) + star.repeat(i - 2));
}
```

###### 2. 使用 repeat()，並用 StringBuilder 打包

```java
public String diamond1(){
    StringBuilder rs = new StringBuilder();
    for (int i = 0; i < totalHeight; i++){
        rs.append(space.repeat(totalHeight - i -1));
        rs.append(star.repeat(2 * i + 1)).append("\n");
    }
    // 執行4次
    for (int i = totalHeight-2 ; i >= 0; i--){
        // 第1圈i=3，重複5-3-1=1次空格
        // 第2圈i=2，重複5-2-1=2次空格
        // 第4圈i=0，重複5-0-1=4次空格
        rs.append(space.repeat(totalHeight - i -1));
        // 第1圈i=3，重複7次*
        // 第2圈i=2，重複5次*
        // 第4圈i=0，重複1次*
        rs.append(star.repeat(2 * i + 1)).append("\n");
    }
    return rs.toString();
}
```

###### 3. 只用 StringBuilder 與迴圈

```java
public String diamond2(){
    StringBuilder rs = new StringBuilder();
    for (int i = 0; i < totalHeight; i++){
        for(int j = 0; j < totalHeight - i - 1; j++){
            rs.append(space);
        }
        for(int j = 0; j < 2 * i + 1; j++) {
            rs.append(star);
        }
        rs.append("\n");
    }
    for (int i = totalHeight-2 ; i >= 0; i--){ // 需要確保在計算空格數量時不會出現數組越界的情況
        for(int j = totalHeight - i - 1; j > 0; j--){
            rs.append(space);
        }
        for(int j = 2 * i + 1; j > 0; j--){
            rs.append(star);
        }
        rs.append("\n");
    }
    return rs.toString();
}
```

## 進階應用與優化技巧

- **效能考量：** 推薦優先使用 `StringBuilder` 實現字串連接，避免使用 + 運算子導致記憶體重複配置。
- **應用場景：** 除了印出圖形，這些方法也可用於製作進度條、生成報表或輔助教學範例。
- **其他方法：** 可以嘗試利用 Stream API 或遞迴方式實現其他圖形生成案例。
