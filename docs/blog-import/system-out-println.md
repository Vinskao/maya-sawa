---
title: "system-out-println"
publishDate: "2024-02-27T12:00:00.000Z"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/02/27
category: Java
tags:
  - System
  - out
  - println
  - Java
---

#### System

這是一個靜態類別，就是 System.out.print 中的 System，其中包含 out 屬性，就是 System.out.print 中的 out，out 是 PrintStream 類別的一個實例。

```java
public final class System {
    public static final InputStream in = null;

    public static final PrintStream out = null;

    public static final PrintStream err = null;

    public static native long currentTimeMillis();

    public static native void sleep(long millis) throws InterruptedException;

    // 其他方法...
}
```

#### PrintStream

PrintStream 類別是 java.io 套件中的一個特定類，它繼承自 OutputStream 抽象類別。這是一個實體類別，其中有 print 方法。就是 System.out.print 中的 print。

out 是 System 類別的一個公共靜態成員變量，表示標準輸出流。 這意味著 out 可以被其他類別存取和使用，PrintStream 類透過建構子傳入 out，並在 PrintStream 中對 out 用 print 方法。

```java
public class PrintStream {

    public PrintStream(OutputStream out) {
        // ...
    }
    public void print(int i) {
        // ...
    }

    public void print(double d) {
        // ...
    }

    public void print(String s) {
        // ...
    }
    // 其他方法...
}
```
