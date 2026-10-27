---
title: "map-reduce"
publishDate: "2025-09-14 01:00:00"
img: /tymultiverse/assets/algorithm.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: MapReduce 分布式計算模型深度剖析：從 Unix 管線到大數據處理的完整演進
level: advance
category: Algorithm
tags:
  - Big Data
  - Distributed Computing
  - MapReduce
  - Hadoop
  - HDFS
  - Data Processing
---

MapReduce 完整解讀：從 Unix、Producer-Consumer 到 JavaScript 的對照

在大數據系統中，MapReduce 是最具代表性的計算模型之一。它看似複雜，其實核心思想與我們日常用過的 Unix 工具、Producer-Consumer 模式、甚至 JavaScript 的 map/reduce 方法 都有共通之處。本文將從這些熟悉的概念出發，逐步拆解 MapReduce 的本質。

## 1. MapReduce 是什麼？

MapReduce 可以簡單理解為：

**Map（映射）**：逐筆處理資料，轉換成 (key, value) 對。

**Reduce（歸約）**：將相同 key 的值聚合起來，產生結果。

舉例來說，若要計算 Web log 中最熱門的 URL：

**Map**：輸入每一行 log，取出 URL → (url, 1)。

**Shuffle**：系統自動將相同 URL 的紀錄分組在一起。

**Reduce**：對每組 (url, 1) 累加 → (url, count)。

這和我們在 Linux 下用管線處理日誌幾乎一樣：

```bash
cat access.log | awk '{print $7}' | sort | uniq -c | sort -nr
```

差別是 MapReduce 可以同時在上千台機器上並行運算，處理單機根本塞不下的資料量。

## 2. 分布式文件系統 HDFS

MapReduce 的強大，來自於它和 **分布式文件系統 HDFS** 的結合。
HDFS 的運作方式：

- 檔案會被切成數百 MB 的「檔案區塊」，分散存放在不同機器的硬碟。
- NameNode 負責記錄「哪個區塊在哪台機器」。
- 為了防止故障，每個區塊會有多份副本，分佈在不同機器。

這樣的設計，讓我們能夠用「許多便宜的普通機器」拼湊出超大儲存系統，而不是依賴昂貴的專用存儲。

## 3. MapReduce 的執行流程

以下是 MapReduce 的完整運行步驟：

1. **輸入切分**：大檔案切成多個區塊，每個區塊分配一個 Map Task。
2. **Map 階段**：Mapper 處理自己的區塊，輸出 (key, value)。
3. **Shuffle（洗牌）**：系統自動根據 key，把資料分派到對應的 Reducer，並且排序。
4. **Reduce 階段**：Reducer 聚合同一個 key 的所有 value，產生結果。
5. **輸出**：結果寫回 HDFS，分散成多個檔案。

簡單比喻：

- **Map** = 老師批改自己班級的試卷。
- **Shuffle** = 把同一科目的試卷集中給一位科目老師。
- **Reduce** = 該科目老師統計成績，生成成績表。

## 4. 與 Producer-Consumer 的比較

MapReduce 的流程和 **Producer-Consumer 模式** 也很相似：

| 元件 | MapReduce | Producer-Consumer |
|------|-----------|-------------------|
| Producer | Map 任務，產生 (key, value) | Producer，產生任務 |
| Queue / Broker | Shuffle，分區 & 排序 & 傳輸 | 任務佇列 |
| Consumer | Reduce 任務，聚合結果 | Consumer，處理任務 |

但也有差異：

- **Shuffle 更聰明**：不只是傳輸，還要確保同一個 key 的資料集中到同一 Reducer，並排好序。
- **MapReduce 是批次**：必須等 Map 任務結束，Reduce 才能開始；Producer-Consumer 則可即時流式處理。

可以說：**MapReduce = 加強版的 Producer-Consumer，內建分流、排序、聚合機制**。

## 5. 與 JavaScript 的 map/reduce 方法比較

很多人學過 JavaScript 的 `map()` 和 `reduce()`，這讓理解 MapReduce 更容易。

### JavaScript 範例
```javascript
const arr = [1, 2, 3, 4];

// map：平方
const squared = arr.map(x => x * x);
// [1, 4, 9, 16]

// reduce：加總
const sum = arr.reduce((acc, x) => acc + x, 0);
// 10
```

### 差異整理

| 特點 | JS map/reduce | Hadoop MapReduce |
|------|---------------|------------------|
| 資料規模 | 陣列（小，放得下記憶體） | PB 級（分散在上萬台機器） |
| 執行環境 | 單機記憶體 | 分布式叢集 |
| Map | 陣列逐筆轉換 | 每台機器處理一個檔案區塊 |
| Reduce | 聚合成單一值 | 聚合同一 key 的值，輸出到多個檔案 |
| 排序/分流 | 沒有 | 內建 shuffle，確保同 key 同處理 |
| 即時性 | 即時 | 批次處理 |

## 6. 與 Java Stream API 的比較

Java 開發者可以通過 **Java 8 Stream API** 來理解 MapReduce 的概念。Stream API 提供了函數式編程風格的數據處理方式。

### Java Stream 範例
```java
import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;

public class StreamExample {
    public static void main(String[] args) {
        List<Integer> numbers = Arrays.asList(1, 2, 3, 4);

        // map：平方
        List<Integer> squared = numbers.stream()
            .map(x -> x * x)
            .collect(Collectors.toList());
        // [1, 4, 9, 16]

        // reduce：加總
        int sum = numbers.stream()
            .reduce(0, (acc, x) -> acc + x);
        // 10

        // 複雜範例：文字處理
        List<String> words = Arrays.asList("hello", "world", "java", "stream");

        // 統計單詞長度分佈
        Map<Integer, Long> lengthCount = words.stream()
            .collect(Collectors.groupingBy(
                String::length,
                Collectors.counting()
            ));
        // {5=2, 4=1, 6=1}
    }
}
```

### Java MapReduce 實現範例
```java
import org.apache.hadoop.mapreduce.*;
import org.apache.hadoop.io.*;

public class WordCountMapper extends Mapper<LongWritable, Text, Text, IntWritable> {
    private final static IntWritable one = new IntWritable(1);
    private Text word = new Text();

    public void map(LongWritable key, Text value, Context context)
            throws IOException, InterruptedException {
        String line = value.toString();
        StringTokenizer tokenizer = new StringTokenizer(line);

        while (tokenizer.hasMoreTokens()) {
            word.set(tokenizer.nextToken());
            context.write(word, one);  // Map: (word, 1)
        }
    }
}

public class WordCountReducer extends Reducer<Text, IntWritable, Text, IntWritable> {
    public void reduce(Text key, Iterable<IntWritable> values, Context context)
            throws IOException, InterruptedException {
        int sum = 0;
        for (IntWritable val : values) {
            sum += val.get();
        }
        context.write(key, new IntWritable(sum));  // Reduce: (word, count)
    }
}
```

### Java 與其他技術的比較

| 特點 | Java Stream | Java MapReduce | Hadoop MapReduce |
|------|-------------|----------------|------------------|
| 資料規模 | 集合（中等規模） | 大資料集 | PB 級分布式 |
| 執行環境 | JVM 單機 | JVM 分布式 | 跨機器分布式 |
| 並行化 | 內建並行流 | 手動配置 | 自動負載平衡 |
| 容錯性 | 無 | 基本容錯 | 高可用容錯 |
| 學習曲線 | 低 | 中等 | 高 |
| 適用場景 | 資料處理管道 | 大數據批次處理 | 海量數據分析 |

### Java MapReduce 的優勢

1. **類型安全**：編譯時檢查，減少運行時錯誤
2. **性能優化**：JVM 優化 + 分布式處理
3. **生態系統**：Hadoop/Spark 生態豐富
4. **企業應用**：廣泛用於生產環境

學習建議：從 Java Stream API 開始理解函數式數據處理，再進階到 Hadoop MapReduce，最後掌握 Spark 等新世代框架。