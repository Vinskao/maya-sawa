---
title: "nio"
publishDate: "2025-09-16 18:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: 深入理解 Java NIO：非阻塞 I/O 的核心原理與實戰應用
level: advance
category: Concurrency
tags:
  - Java
  - NIO
  - I/O
  - Non-blocking
  - Reactor Pattern
  - Network Programming
  - Performance Optimization
---

# 用簡單方式理解 NIO

## 前言

在高併發網路程式設計中，I/O 效能是關鍵瓶頸。Java NIO（New I/O）作為解決方案，徹底改變了我們處理網路連線的方式。本文將用簡單易懂的方式，帶你理解 NIO 的核心原理與實戰應用。

---

## 一、傳統 BIO（Blocking I/O）的問題

### 傳統模式的缺陷

```
傳統 BIO 模式
├─ 一個連線 = 一個專屬執行緒
├─ accept()、read()、write() 都是阻塞的
├─ 遇到大量連線時問題重重
```

一個連線（Socket）要一個專屬執行緒去處理。`accept()`、`read()`、`write()` 都是**阻塞**的。

#### 重要澄清：阻塞的兩種類型

在討論阻塞 I/O 時，需要區分兩種不同的阻塞：

**等待就緒的阻塞**：`accept()`、`read()` 等待網路資料到來
- ✅ **不使用 CPU**：執行緒處於睡眠狀態，OS 不會分配 CPU 時間
- ✅ **不消耗系統資源**：只是等待，不做任何計算
- ✅ **本質是「空等」**：就像在餐廳等位，服務員會通知你

**真正操作的阻塞**：資料讀寫時的 CPU 記憶體複製
- ❌ **使用 CPU**：需要進行資料複製、編碼解碼等計算
- ❌ **真正在「幹活」**：執行實際的業務邏輯
- ❌ **這個階段很短**：通常是毫秒級，效能很高

這種區分很重要，因為只有第一種阻塞才是問題所在！

### 執行緒池的緩衝作用

現代多執行緒一般都使用**執行緒池**，可以讓執行緒的建立和回收成本相對較低：

```java
// 現代執行緒池模式
ExecutorService threadPool = Executors.newFixedThreadPool(200);
ServerSocket server = new ServerSocket(8080);

while (true) {
    Socket socket = server.accept();  // 阻塞等待連線
    threadPool.execute(() -> {
        // 重用執行緒處理業務
        handleRequest(socket);
    });
}
```

#### ✅ 執行緒池的優勢
- **資源重用**：避免頻繁建立銷毀執行緒
- **天然漏斗**：自動緩衝處理不了的請求
- **負載平滑**：避免系統瞬間壓力過大

在**活動連線數不高（< 單機 1000）**的情況下，這種模型相當不錯：
- 每個連線專注自己的 I/O，程式設計模型簡單
- 不需要過多考慮系統過載、限流等問題
- 開發效率高，維護成本低

### 執行緒的「昂貴」本質

雖然執行緒池緩解了部分問題，但執行緒本身仍是**很貴的資源**：

#### 執行緒的三大成本

**1. 建立和銷毀成本極高**
- 在 Linux 系統中，執行緒本質就是一個輕量級行程
- 建立執行緒需要呼叫系統函數 `clone()`，涉及複雜的系統資源分配
- 銷毀時需要回收所有資源，包括記憶體、檔案描述符等
- 即使是執行緒池，也無法完全消除這種成本

**2. 記憶體消耗巨大**
- Java 執行緒棧一般至少分配 512KB ~ 1MB
- 除了棧空間，還要有執行緒的控制結構（Thread object）
- 1000 個執行緒就能消耗 500MB ~ 1GB 記憶體
- 在容器化環境中，這會嚴重影響資源利用率

**3. 切換成本極高**
- 作業系統切換執行緒時需要儲存/恢復執行緒上下文
- 上下文包括：暫存器值、程式計數器、棧指標等
- 現代 CPU 上下文切換大約需要 1000 ~ 2000 個 CPU 週期
- 如果執行緒數過高，切換時間可能超過執行時間

#### 系統級後果

當執行緒數量過多時，可能出現：
- **系統 load 飆高**：CPU 忙於執行緒切換
- **CPU sy 使用率 > 20%**：系統呼叫時間過長
- **系統陷入不可用狀態**：看起來在工作，實際效率極低

#### 負載不穩定性

最危險的是**鋸齒狀系統負載**：
```
網路環境波動 → 大量請求同時返回
     ↓
大量阻塞執行緒同時甦醒
     ↓
系統負載壓力瞬間暴衝
     ↓
可能導致雪崩效應
```

即使有執行緒池，這種問題依然存在，只是被緩衝了而已。

#### BIO 的適用範圍
```java
// 傳統 BIO 伺服器
ServerSocket server = new ServerSocket(8080);
while (true) {
    Socket socket = server.accept();  // 阻塞等待連線
    new Thread(() -> {
        // 每個連線一個執行緒
        InputStream in = socket.getInputStream();
        int data = in.read();  // 阻塞讀取
        // 處理業務邏輯...
    }).start();
}
```

結論：BIO 可以應付小規模（< 1000 連線），但遇到高併發就崩。

---

## 二、幾種 I/O 模型的比較

### I/O 操作的兩個階段

```
一次 I/O 分兩步：
├─ 階段一：等待就緒（能不能讀寫）- 這個階段可能很慢
└─ 階段二：真正操作（搬資料，CPU 記憶體複製）- 這個階段很快
```

### 三種 I/O 模型對比

| 模型 | 等待就緒 | 資料操作 | 特點 |
|------|----------|----------|------|
| **BIO** | 傻等（阻塞） | 同步處理 | 簡單但低效 |
| **NIO** | 詢問狀態 | 同步處理 | 非阻塞，高效 |
| **AIO** | 系統通知 | 非同步處理 | 最先進但複雜 |

#### 差別在於「等的方式」

**BIO**：我要讀（結果卡住）
```java
int data = inputStream.read();  // 沒資料就卡住
```

**NIO**：我能不能讀？（能再去讀）
```java
if (channel.isReadable()) {      // 先檢查能不能讀
    int data = channel.read();   // 再讀
}
```

**AIO**：幫我讀好再通知我
```java
channel.read(buffer, attachment, completionHandler);  // 系統讀好後通知
```

---

## 三、NIO 的本質：事件模型

### Reactor 模式（事件驅動）

NIO 把「等」交給 Selector，程式不用自己開一堆執行緒來傻等。

#### 核心流程

```java
// 1. 把 Socket 註冊到 Selector
Selector selector = Selector.open();
ServerSocketChannel serverChannel = ServerSocketChannel.open();
serverChannel.configureBlocking(false);  // 設定為非阻塞
serverChannel.register(selector, SelectionKey.OP_ACCEPT);

// 2. 用一個 IO 執行緒跑迴圈
while (true) {
    int readyChannels = selector.select();  // 等事件（非阻塞）
    Set<SelectionKey> keys = selector.selectedKeys();

    for (SelectionKey key : keys) {
        if (key.isAcceptable()) {
            // 新連線
            ServerSocketChannel server = (ServerSocketChannel) key.channel();
            SocketChannel client = server.accept();
            client.configureBlocking(false);
            client.register(selector, SelectionKey.OP_READ);
        } else if (key.isReadable()) {
            // 可讀
            SocketChannel client = (SocketChannel) key.channel();
            ByteBuffer buffer = ByteBuffer.allocate(1024);
            int bytesRead = client.read(buffer);
            if (bytesRead > 0) {
                // 處理資料...
            }
        }
        // ... 其他事件處理
    }
}
```

#### 單執行緒處理萬連線

```
單執行緒就能處理成千上萬連線，因為它只是：
├─ 「挑出能處理的 I/O」
├─ 再交給處理器
└─ 不需要為每個連線維護獨立執行緒
```

#### Reactor 模式的程式碼實現

讓我們用更具體的程式碼來理解 Reactor 模式的核心：

```java
interface ChannelHandler {
    void channelReadable(Channel channel);
    void channelWritable(Channel channel);
}

class Channel {
    Socket socket;
    Event event; // 读、写或者连接事件
}

// IO线程主循环 - 最简单的Reactor模式
class IoThread extends Thread {
    public void run() {
        Channel channel;
        while((channel = Selector.select()) != null) { // 选择就绪的事件和对应的连接
            if(channel.event == Event.ACCEPT) {
                registerNewChannelHandler(channel); // 如果是新连接，则注册一个新的读写处理器
            }
            if(channel.event == Event.WRITE) {
                getChannelHandler(channel).channelWritable(channel); // 如果可以写，则执行写事件
            }
            if(channel.event == Event.READ) {
                getChannelHandler(channel).channelReadable(channel); // 如果可以读，则执行读事件
            }
        }
    }
}

// 所有channel的对应事件处理器映射
Map<Channel, ChannelHandler> handlerMap;
```

這個程式很簡短，也是**最簡單的 Reactor 模式**：註冊所有感興趣的事件處理器，單執行緒輪詢選擇就緒事件，執行事件處理器。

#### ⚡ NIO 如何解決執行緒瓶頸

由上面的示例我們大概可以總結出 NIO 是怎麼解決掉執行緒的瓶頸並處理海量連線的：

**從阻塞讀寫到事件輪詢**：
```
BIO：一個連線 = 一個執行緒阻塞讀寫
NIO：單執行緒輪詢事件，找到可讀寫的網路描述符進行操作
```

**I/O 操作的本質區分**：
- **事件的輪詢是阻塞的**：沒有可幹的事情必須要阻塞等待
- **剩餘的 I/O 操作都是純 CPU 操作**：讀、寫、資料複製等
- **沒有必要開啟多執行緒**：因為大部分時間都在 CPU 計算，不是等待

**連線數大的時候的好處**：
- 因為執行緒的節約，執行緒切換帶來的問題也隨之解決
- 為處理海量連線提供了可能
- 單執行緒處理 I/O 的效率非常高，沒有執行緒切換，只是拼命的讀、寫、選擇事件

#### 多核利用與執行緒模型優化

單執行緒處理 I/O 的效率確實非常高，但現代伺服器一般都是多核處理器，如果能夠利用多核心進行 I/O，無疑對效率會有更大的提高。

仔細分析一下我們需要的執行緒，其實主要包括以下幾種：

**1. 事件分發器**
- 單執行緒選擇就緒的事件
- 負責監聽所有連線的狀態變化

**2. I/O 處理器**
- 包括 connect、read、write 等純 CPU 操作
- 一般開啟 CPU 核心個數的執行緒就可以
- 負責實際的資料讀寫和編碼解碼

**3. 業務執行緒**
- 在處理完 I/O 後，業務一般還會有自己的業務邏輯
- 有的還會有其他的阻塞 I/O，如 DB 操作、RPC 等
- 只要有阻塞，就需要單獨的執行緒處理

這種分工讓 NIO 能夠充分發揮多核處理器的效能，同時又避免了傳統 BIO 的執行緒浪費問題。

---

## 四、優化與多執行緒

### 單執行緒的極限

單執行緒已經很省資源，但現代伺服器有多核 → 可以分工：

```
事件分發器：專門等 Selector（1 個執行緒）
I/O 處理器：負責快速的讀寫（開 CPU 核心數個）
業務執行緒：做 DB 查詢、邏輯處理（這可能會阻塞，必須分開）
```

### ⚠️ 重要注意事項

- **一個 socket 只能被一個 IO 執行緒管理**
- **如果連線量再大，可以「分組」（多個 Selector）**
- **業務邏輯處理必須與 I/O 分離**

#### 進階架構示例

```java
public class NIOServer {
    private static final int BOSS_THREADS = 1;     // 事件分發器
    private static final int WORKER_THREADS = 4;   // I/O 處理器
    private static final int BUSINESS_THREADS = 8; // 業務處理器

    // Boss Group: 處理連線事件
    private EventLoopGroup bossGroup = new NioEventLoopGroup(BOSS_THREADS);

    // Worker Group: 處理 I/O 事件
    private EventLoopGroup workerGroup = new NioEventLoopGroup(WORKER_THREADS);

    // Business Group: 處理業務邏輯
    private ExecutorService businessExecutor = Executors.newFixedThreadPool(BUSINESS_THREADS);
}
```

---

## 五、為什麼 NIO 能解放執行緒

### 傳統 BIO vs NIO 對比

#### BIO 的浪費
```
BIO 模式：
├─ 每個連線一個執行緒
├─ 大部分時間在等待 I/O
├─ 資源極度浪費
└─ 無法擴展到萬級連線
```

#### ✅ NIO 的高效
```
NIO 模式：
├─ 一個執行緒「監控」很多連線
├─ 只有就緒才去處理
├─ 資源利用率極高
└─ 可以輕鬆處理十萬、百萬級連線
```

### 具體效益

| 方面 | BIO | NIO |
|------|-----|-----|
| **執行緒數量** | 數千個 | 數個 |
| **記憶體耗用** | 幾 GB | 幾百 MB |
| **上下文切換** | 頻繁 | 極少 |
| **支援連線數** | 千級 | 萬級/百萬級 |

### 實際應用場景

NIO 讓以下場景成為可能：
- **遊戲伺服器**：同時處理數萬玩家連線
- **IM 系統**：即時訊息服務
- **WebSocket**：全雙工通訊
- **代理伺服器**：負載均衡、高併發代理

---

## 六、客戶端場景

### 傳統客戶端問題

客戶端常用「BIO + 連線池」來解決阻塞，但還是受限於執行緒。

```java
// 傳統客戶端連線池
GenericObjectPool<Socket> connectionPool = new GenericObjectPool<>();
Socket socket = connectionPool.borrowObject();  // 可能阻塞
```

### NIO 客戶端優勢

用 NIO，客戶端也可以：

#### ✅ 資源優化
```java
// NIO 客戶端
Selector selector = Selector.open();
SocketChannel channel = SocketChannel.open();
channel.configureBlocking(false);
channel.register(selector, SelectionKey.OP_CONNECT);

// 一個執行緒處理多個連線
while (true) {
    selector.select();
    // 處理所有就緒的連線...
}
```

#### ✅ 減少連線開銷
- **共享少量執行緒**處理大量連線
- **減少頻繁建立/銷毀連線的開銷**
- **更好的資源控制**

### 實際應用案例

```java
public class NIOClientPool {
    private final Selector selector;
    private final Map<String, SocketChannel> connections;

    public NIOClientPool(int maxConnections) {
        this.selector = Selector.open();
        this.connections = new ConcurrentHashMap<>();
        // 初始化連線池...
    }

    public void sendToServer(String host, int port, ByteBuffer data) {
        SocketChannel channel = getOrCreateConnection(host, port);
        channel.write(data);
    }
}
```

---

## 七、實戰建議與注意事項

### 最佳實踐

#### 1. **選擇合適的場景**
- **小規模應用**：BIO 足夠，開發簡單
- **高併發場景**：NIO 必選
- **超高併發**：考慮 AIO 或 Netty

#### 2. **資源配置建議**
```properties
# 推薦配置
server.tomcat.threads.max=200
server.tomcat.threads.min-spare=10
server.tomcat.accept-count=100

# NIO 特有配置
server.tomcat.protocol=org.apache.coyote.http11.Http11NioProtocol
```

#### 3. **監控重點**
- **連線數量**：避免超過系統限制
- **記憶體使用**：監控 Buffer 分配
- **CPU 使用率**：關注 Selector 的效能

### ⚠️ 常見陷阱

#### 1. **忘記設定非阻塞**
```java
// ❌ 錯誤：還是阻塞的
SocketChannel channel = SocketChannel.open();

// ✅ 正確：設定非阻塞
channel.configureBlocking(false);
```

#### 2. **Buffer 管理不當**
```java
// ❌ 錯誤：重複使用 Buffer 忘記清理
ByteBuffer buffer = ByteBuffer.allocate(1024);
buffer.put(data);
// 忘記 flip() 或 clear()

// ✅ 正確：正確的 Buffer 操作
buffer.put(data);
buffer.flip();  // 切換到讀模式
channel.read(buffer);
buffer.clear(); // 清理準備下次使用
```

#### 3. **Selector 記憶體洩漏**
```java
// ❌ 錯誤：忘記取消註冊
SelectionKey key = channel.register(selector, ops);
// 使用完後忘記取消

// ✅ 正確：記得清理
key.cancel();
selector.selectNow(); // 立即更新
```

---

## 八、總結

### NIO 的核心價值

NIO 徹底改變了我們處理網路 I/O 的方式：

#### 從阻塞到非阻塞
- BIO：一個連線一個執行緒，資源浪費
- NIO：事件驅動，多路複用，資源節省

#### 效能提升
- **連線數量**：從千級到萬級/百萬級
- **資源使用**：記憶體減少 90%，CPU 利用率提升
- **擴展性**：線性擴展，無瓶頸

#### 程式設計思維的轉變
- **從同步到事件驅動**
- **從阻塞等待到狀態檢查**
- **從資源浪費到精準控制**

### 適用場景總結

| 場景 | 推薦技術 | 理由 |
|------|----------|------|
| **小規模應用** | BIO | 簡單開發，足夠使用 |
| **Web 服務** | NIO | 高併發，資源節省 |
| **遊戲伺服器** | NIO/Netty | 萬級連線，實時通訊 |
| **微服務** | NIO | 輕量高效，易於擴展 |
| **大資料處理** | AIO | 非同步，最大化效能 |

### 補充：非同步程式設計模式說明

在討論 I/O 模型時，我們經常提到「非同步」這個概念。讓我們來補充說明常見的非同步程式設計模式：

#### 簡單來說：

**回呼函式（Callback）：**

寫法： 任務執行完畢後，會去呼叫您事先定義好的另一個函式。

優點： 在過去，這是處理非同步任務的常見方式。

缺點： 容易產生「回呼地獄（Callback Hell）」。當任務需要一層一層依賴時，程式碼會變得巢狀且難以閱讀和維護。

```javascript
// 回呼地獄示例
getUser(userId, function(user) {
    getPosts(user.id, function(posts) {
        getComments(posts[0].id, function(comments) {
            // 巢狀太深，難以維護
        });
    });
});
```

**CompletableFuture：**

寫法： 透過鏈式呼叫（chaining）的方式，將多個非同步任務串聯起來。例如 `.thenApply()` 或 `.thenCompose()`。

優點： 程式碼的可讀性比回呼函式高很多。您可以像讀故事一樣，一行一行地看到任務的執行順序。

缺點： 儘管比回呼函式清晰，但與完全同步（synchronous）的寫法相比，仍會增加程式碼的複雜度，因為您需要處理回傳的 CompletableFuture 物件。

```java
// CompletableFuture 示例
CompletableFuture<User> future = getUserAsync(userId)
    .thenCompose(user -> getPostsAsync(user.getId()))
    .thenApply(posts -> posts.get(0))
    .thenCompose(post -> getCommentsAsync(post.getId()))
    .thenAccept(comments -> {
        // 處理最終結果
    });
```

#### 與 I/O 模型的關聯

- **BIO**：同步阻塞，程式設計最簡單，但效能最低
- **NIO**：同步非阻塞，透過狀態檢查避免阻塞，效能大幅提升
- **AIO**：非同步非阻塞，通常使用回呼函式或 CompletableFuture 處理結果

在現代 Java 應用中，CompletableFuture 配合 NIO 可以提供更好的程式設計體驗，既保持高效能，又避免回呼地獄的問題。

NIO 讓 Java 在高併發網路程式設計中重獲新生，成為現代分佈式系統的基石。
