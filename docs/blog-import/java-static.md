---
title: "java-static"
publishDate: "2024-02-24 12:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/02/24
category: Java
tags:
  - static
  - final
  - Java
---

#### 權限修飾

```java
public class Dog{}
```

```java
class Dog{}
```

如果這兩類別在同個 package 中，是可以互相訪問的。

如果一個在 org.service package、一個在 org.controller package，就只有 public 類別可以透過 import 被訪問。

#### final

如果成員、區域變數宣告 final，就要馬上設值且不能再變動。

```java
final int x = 1;
```

如果類別宣告 final，就不能被繼承也不能繼承類別，也不可以實作介面。

```java
public final class Xxx extends Zzz{}; // 錯，不能繼承類別
```

```java
public class Ooo extends Xxx{}; // 錯，不能被繼承
```

```java
public final class Xxx implements Yyy{};// 錯，不能實作介面
```

final 類別可以被實作嗎？只有介面才能被實作。

#### 認識 static 基本概念

想像一下，你有一個學校，static 就像是「學校的公共財產」，所有學生都可以使用，但不屬於任何特定學生。

**static 變數：** 屬於整個類別，不是屬於某個物件實例。

```java
public class School {
    // 這是學校的公共財產，所有學生共享
    public static String schoolName = "台中一中";

    // 這是學生的個人財產，每個學生都有自己的
    public String studentName;
}
```

**為什麼要用類別名稱呼叫？**

```java
public class Test {
    public static void main(String[] args) {
        // 正確：用類別名稱呼叫 static 變數
        System.out.println(School.schoolName);

        // 錯誤：不能用物件實例呼叫 static 成員（雖然語法允許，但不建議）
        School student = new School();
        System.out.println(student.schoolName); // 技術上可行，但概念錯誤
    }
}
```

#### JVM 載入類別的過程

要理解 static，就必須先知道 JVM 是如何載入類別的。想像 JVM 是一個圖書館管理員，負責管理所有的書（類別）。

**類別載入時機：**
當你第一次使用一個類別時，JVM 才會把它載入記憶體。這就像圖書館不會預先把所有書都拿出來，只在有人借書時才拿出來。

#### static 區塊：類別的「開門儀式」

static 區塊就像是類別的「開門儀式」，當 JVM 第一次載入這個類別時，就會自動執行這個儀式，而且只執行一次。

```java
public class Restaurant {
    // 廚房在餐廳開門前就準備好了
    static String status = "準備中";

    // 開門儀式：餐廳開門時要做的事
    static {
        System.out.println("餐廳正在準備開門...");
        status = "營業中";
        System.out.println("餐廳已經開門了！");
    }

    public static void main(String[] args) {
        System.out.println("餐廳狀態：" + status);
    }
}
```

**執行結果：**
```
餐廳正在準備開門...
餐廳已經開門了！
餐廳狀態：營業中
```

#### static 區塊的執行順序

如果一個類別有多個 static 區塊，它們會按照寫的順序執行，就像儀式的步驟一樣。

```java
public class Restaurant {
    static String status = "未開門";

    // 第一個儀式步驟
    static {
        System.out.println("步驟1：清潔環境");
        status = "清潔中";
    }

    // 第二個儀式步驟
    static {
        System.out.println("步驟2：準備食材");
        status = "準備中";
    }

    // 第三個儀式步驟
    static {
        System.out.println("步驟3：正式開門");
        status = "營業中";
    }

    public static void main(String[] args) {
        System.out.println("最終狀態：" + status);
    }
}
```

#### 建構子 vs static 區塊：誰先執行？

建構子是在「建立物件」時執行的，而 static 區塊是在「類別載入」時執行的。

**執行時機差異：**
- static 區塊：類別第一次被使用時執行，只執行一次
- 建構子：每次建立新物件時執行，可執行多次

```java
public class House {
    static int totalHouses = 0;

    // 類別載入時執行：就像蓋社區大門
    static {
        System.out.println("社區大門已經蓋好了！");
    }

    // 建構子：每次蓋新房子時執行
    public House() {
        totalHouses++;
        System.out.println("又蓋好一棟房子了！目前總共有：" + totalHouses + "棟");
    }

    public static void main(String[] args) {
        System.out.println("開始蓋房子...");

        House house1 = new House(); // 會執行建構子
        House house2 = new House(); // 會執行建構子
        House house3 = new House(); // 會執行建構子
    }
}
```

**執行結果：**
```
社區大門已經蓋好了！
開始蓋房子...
又蓋好一棟房子了！目前總共有：1棟
又蓋好一棟房子了！目前總共有：2棟
又蓋好一棟房子了！目前總共有：3棟
```

#### 建構子可以修改 static 變數嗎？

可以！因為 static 變數是所有物件共享的，建構子修改它會影響全體。

```java
public class Counter {
    static int globalCount = 0;

    static {
        globalCount = 100; // 起始值設為100
        System.out.println("初始全域計數器：" + globalCount);
    }

    public Counter() {
        globalCount++; // 每個物件建立時，全域計數器加1
    }

    public static void main(String[] args) {
        System.out.println("建立物件前，全域計數器：" + Counter.globalCount);

        Counter obj1 = new Counter();
        System.out.println("建立第一個物件後：" + Counter.globalCount);

        Counter obj2 = new Counter();
        System.out.println("建立第二個物件後：" + Counter.globalCount);
    }
}
```

#### 靜態方法只能訪問靜態成員

static 方法就像是「類別等級的工具」，它不能直接使用「物件等級的東西」。

```java
public class Calculator {
    // static 變數：類別等級
    private static final double PI = 3.14159;

    // 物件變數：實例等級
    private String calculatorName;

    // static 方法：只能使用 static 成員
    public static double calculateCircleArea(double radius) {
        return PI * radius * radius; // 可以用 PI
        // return calculatorName; // 錯誤！不能用物件變數
    }

    // 普通方法：可以同時使用 static 和物件成員
    public void printResult(double radius) {
        double area = calculateCircleArea(radius); // 可以呼叫 static 方法
        System.out.println(calculatorName + "計算結果：" + area); // 也可以用物件變數
    }
}
```

#### 什麼情況下會觸發類別載入？

想像 JVM 是一個圖書館管理員，他很懶，只在有人真正需要某本書時，才會把書從儲藏室拿出來。

**會讓 JVM 載入類別的情況：**
1. **執行 main 方法** - 程式開始運行時
2. **建立物件** - 使用 `new` 關鍵字時
3. **呼叫 static 方法或存取 static 變數** - 直接使用類別名稱時
4. **使用反射** - 像 `Class.forName()` 這種程式化載入

```java
public class Library {
    static String bookStatus = "在儲藏室";

    static {
        bookStatus = "已經借出去了";
        System.out.println("書被拿出來了！");
    }

    public static void readBook() {
        System.out.println("正在讀書...");
    }
}

public class Student {
    public static void main(String[] args) {
        System.out.println("學生來圖書館了");

        // 情況1：呼叫 static 方法，觸發類別載入
        Library.readBook();

        // 情況2：存取 static 變數，也會觸發類別載入
        System.out.println("書的狀態：" + Library.bookStatus);
    }
}
```

**輸出結果：**
```
學生來圖書館了
書被拿出來了！  <- static 區塊執行了，表示類別被載入
正在讀書...
書的狀態：已經借出去了
```

#### 特殊的例外：不會觸發類別載入的情況

有些情況看起來像在「使用」類別，但 JVM 很聰明，知道這不會真的需要把類別載入。

**1. 讀取編譯時期就確定的常數**

```java
public class Constants {
    // 這是編譯時期就確定的常數
    public static final int MAX_USERS = 100;

    // 這需要運行時計算
    public static int CURRENT_USERS = 50;

    static {
        System.out.println("Constants 類別被載入了！");
    }
}

public class Test {
    public static void main(String[] args) {
        // 不會觸發類別載入，因為編譯器已經知道 MAX_USERS = 100
        System.out.println("最大使用者數：" + Constants.MAX_USERS);

        System.out.println("--- 分隔線 ---");

        // 會觸發類別載入，因為需要讀取 CURRENT_USERS 的實際值
        System.out.println("目前使用者數：" + Constants.CURRENT_USERS);
    }
}
```

**2. 宣告陣列（但不建立物件）**

```java
public class Test {
    public static void main(String[] args) {
        // 只是在宣告陣列，不會載入 MyClass
        Constants[] users;

        // 只有真正建立物件時，才會載入
        // users = new Constants[10]; // 這行才會觸發載入
    }
}
```

#### 如何觀察類別載入過程？

想要知道 JVM 什麼時候載入類別，可以用這些方法：

**方法1：印出訊息（最簡單）**
```java
public class MyClass {
    static {
        System.out.println("MyClass 被 JVM 載入了！");
    }
}
```

**方法2：使用除錯器**
在 static 區塊的第一行設定中斷點，程式執行到那裡時會停下來。

**方法3：JVM 參數觀察**
```bash
java -verbose:class MyProgram
```
這樣 JVM 會印出所有載入的類別名稱。

#### 總結：JVM 與 static 的關係

1. **JVM 負責管理類別的生命週期**
2. **static 成員在類別載入時就存在**
3. **static 區塊是類別的初始化儀式**
4. **建構子是物件的初始化儀式**
5. **static 區塊總是比建構子先執行**

理解這個時機差異很重要，因為它影響程式的行為和效能！

## 設計原則與進階應用注意事項

- **靜態成員：** 使用時請注意避免過度依賴，造成類之間高耦合及難以測試。
- **Final 修飾：** 用於不可變物件或常數設定，確保資料一致性，防止意外修改。
- **static 區塊：** 用於複雜的靜態變數初始化，注意執行順序和時機。
- **類別初始化：** 理解 JVM 載入時機，避免不必要的類別初始化影響效能。
- **實戰建議：** 善用 static 與 final 搭配各種設計模式（例如單例），提高程式穩定性與安全性。
