---
title: "r2dbc"
publishDate: "2025-09-28 10:00:00"
img: /tymultiverse/assets/java.jpg
img_alt: R2DBC reactive database connectivity logo with non-blocking operations
description: R2DBC 在 TY Multiverse Backend 中的完整應用指南，從基礎概念到專案實戰，涵蓋反應式程式設計、非阻塞操作、高併發處理等核心場景。
level: advance
category: Spring Boot
tags:
  - R2DBC
  - Reactive Programming
  - Spring WebFlux
  - Database
  - Backend Development
---

# R2DBC 基礎概念

## R2DBC 是什麼？

R2DBC (Reactive Relational Database Connectivity) 是一個**反應式程式設計**的資料庫連接規範，專為非阻塞式資料庫操作而設計。它允許在高併發場景下更有效地利用系統資源。

簡單來說，R2DBC 讓資料庫操作變成「非阻塞」的——不需要等待資料庫回應，就可以繼續處理其他任務。

## 為什麼需要 R2DBC？

在傳統的 JDBC 中，每個資料庫操作都會阻塞當前執行緒：

```java
// 傳統 JDBC - 阻塞式
List<User> users = userRepository.findAll(); // 必須等到資料庫返回結果
System.out.println("操作完成"); // 這行要等到上面執行完才會執行
```

R2DBC 則是非阻塞的：

```java
// R2DBC - 非阻塞式
Flux<User> users = userRepository.findAll(); // 立即返回，不會阻塞
users.subscribe(user -> System.out.println(user)); // 資料準備好時才執行
System.out.println("操作已發起"); // 這行立即執行
```

# R2DBC vs JDBC 差異

## 1. 執行模型差異

### JDBC：同步阻塞
- 每個查詢阻塞執行緒直到結果返回
- 每個資料庫連接綁定一個執行緒
- 高併發時需要大量執行緒

### R2DBC：非同步非阻塞
- 查詢發起後立即返回，不阻塞執行緒
- 事件驅動模型，一個執行緒處理多個連接
- 更少的執行緒處理更高的併發

## 2. 效能比較

| 場景 | JDBC | R2DBC |
|------|------|-------|
| 低併發 (100 QPS) | ✅ 簡單直接 | ⚠️ 額外複雜度 |
| 高併發 (10K QPS) | ❌ 需大量執行緒 | ✅ 資源利用率高 |
| I/O 密集操作 | ❌ 執行緒浪費 | ✅ 高效處理 |

# 快速上手：基本設定

## 依賴配置

```xml
<!-- Maven -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-data-r2dbc</artifactId>
</dependency>
<dependency>
    <groupId>io.r2dbc</groupId>
    <artifactId>r2dbc-postgresql</artifactId> <!-- 或其他資料庫驅動 -->
</dependency>
```

## 應用配置

```yaml
spring:
  r2dbc:
    url: r2dbc:postgresql://localhost:5432/mydb
    username: myuser
    password: mypass
```

## 實體類別

```java
@Table("users")
public class User {
    @Id
    private Long id;
    private String name;
    private String email;
    private LocalDateTime createdAt;

    // 建構函數、getters、setters
}
```

# 核心 Reactive 類型理解

## Mono：單個結果

Mono 代表 0 或 1 個結果的非同步操作：

```java
// 根據 ID 查詢單個用戶
Mono<User> findById(Long id) {
    return userRepository.findById(id);
}

// 使用方式
userRepository.findById(1L)
    .subscribe(user -> System.out.println("找到用戶: " + user.getName()),
               error -> System.err.println("錯誤: " + error),
               () -> System.out.println("操作完成"));
```

## Flux：多個結果

Flux 代表 0 到 N 個結果的序列：

```java
// 查詢所有用戶
Flux<User> findAll() {
    return userRepository.findAll();
}

// 使用方式
userRepository.findAll()
    .subscribe(user -> System.out.println(user.getName()),
               error -> System.err.println("錯誤: " + error),
               () -> System.out.println("處理完所有用戶"));
```

# Repository 層實作

## 基本 CRUD 操作

```java
@Repository
public interface UserRepository extends ReactiveCrudRepository<User, Long> {

    // 基本 CRUD 由 ReactiveCrudRepository 提供：
    // - Mono<User> findById(Long id)
    // - Flux<User> findAll()
    // - Mono<User> save(User user)
    // - Mono<Void> deleteById(Long id)

    // 自訂查詢方法
    Flux<User> findByName(String name);
    Mono<User> findByEmail(String email);
    Flux<User> findByCreatedAtAfter(LocalDateTime date);
}
```

## 自訂查詢示例

```java
@Repository
public interface UserRepository extends ReactiveCrudRepository<User, Long> {

    // 簡單屬性查詢
    Flux<User> findByName(String name);

    // 複雜條件查詢
    Flux<User> findByNameAndEmail(String name, String email);

    // 使用 @Query 註解的自訂 SQL
    @Query("SELECT * FROM users WHERE created_at > :date ORDER BY name")
    Flux<User> findRecentUsers(@Param("date") LocalDateTime date);

    // 分頁查詢
    Flux<User> findAllBy(Pageable pageable);
}
```

# Service 層實作

## 基本服務模式

```java
@Service
public class UserService {

    private final UserRepository userRepository;

    public UserService(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    // 查詢所有用戶
    public Flux<User> getAllUsers() {
        return userRepository.findAll();
    }

    // 根據 ID 查詢用戶
    public Mono<User> getUserById(Long id) {
        return userRepository.findById(id);
    }

    // 創建新用戶
    public Mono<User> createUser(User user) {
        user.setCreatedAt(LocalDateTime.now());
        return userRepository.save(user);
    }

    // 更新用戶
    public Mono<User> updateUser(Long id, User updatedUser) {
        return userRepository.findById(id)
                .flatMap(existingUser -> {
                    existingUser.setName(updatedUser.getName());
                    existingUser.setEmail(updatedUser.getEmail());
                    return userRepository.save(existingUser);
                });
    }

    // 刪除用戶
    public Mono<Void> deleteUser(Long id) {
        return userRepository.deleteById(id);
    }
}
```

# Controller 層實作

## REST API 實作

```java
@RestController
@RequestMapping("/api/users")
public class UserController {

    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    // 獲取所有用戶
    @GetMapping
    public Flux<User> getAllUsers() {
        return userService.getAllUsers();
    }

    // 根據 ID 獲取用戶
    @GetMapping("/{id}")
    public Mono<User> getUserById(@PathVariable Long id) {
        return userService.getUserById(id);
    }

    // 創建用戶
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Mono<User> createUser(@RequestBody User user) {
        return userService.createUser(user);
    }

    // 更新用戶
    @PutMapping("/{id}")
    public Mono<User> updateUser(@PathVariable Long id, @RequestBody User user) {
        return userService.updateUser(id, user);
    }

    // 刪除用戶
    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public Mono<Void> deleteUser(@PathVariable Long id) {
        return userService.deleteUser(id);
    }
}
```

# 進階模式與最佳實務

## 錯誤處理

```java
@Service
public class UserService {

    public Mono<User> getUserById(Long id) {
        return userRepository.findById(id)
                .switchIfEmpty(Mono.error(new UserNotFoundException(id)));
    }

    public Mono<User> createUser(User user) {
        return userRepository.findByEmail(user.getEmail())
                .flatMap(existing -> Mono.error(new EmailAlreadyExistsException()))
                .then(userRepository.save(user.setCreatedAt(LocalDateTime.now())));
    }
}
```

## 事務管理

```java
@Service
public class OrderService {

    @Transactional
    public Mono<Order> createOrder(CreateOrderRequest request) {
        return userRepository.findById(request.getUserId())
                .switchIfEmpty(Mono.error(new UserNotFoundException()))
                .flatMap(user -> {
                    Order order = new Order();
                    order.setUserId(user.getId());
                    order.setAmount(request.getAmount());
                    return orderRepository.save(order);
                });
    }
}
```

## 批次操作

```java
@Service
public class UserService {

    // 批次插入
    public Flux<User> createUsersBatch(List<User> users) {
        return Flux.fromIterable(users)
                .map(user -> user.setCreatedAt(LocalDateTime.now()))
                .flatMap(userRepository::save);
    }

    // 批次更新
    public Flux<User> updateUsersBatch(List<User> updates) {
        return Flux.fromIterable(updates)
                .flatMap(update -> userRepository.findById(update.getId())
                        .flatMap(existing -> {
                            existing.setName(update.getName());
                            existing.setEmail(update.getEmail());
                            return userRepository.save(existing);
                        }));
    }
}
```

# 效能優化技巧

## 連接池配置

```yaml
spring:
  r2dbc:
    url: r2dbc:postgresql://localhost:5432/mydb
    username: myuser
    password: mypass
    properties:
      maxSize: 20          # 最大連接數
      initialSize: 5       # 初始連接數
      maxIdleTime: 30m     # 最大空閒時間
      maxCreateConnectionTime: 2s  # 創建連接超時時間
```

## 查詢優化

```java
@Repository
public interface UserRepository extends ReactiveCrudRepository<User, Long> {

    // 使用 LIMIT 限制結果數量
    @Query("SELECT * FROM users ORDER BY created_at DESC LIMIT :limit")
    Flux<User> findRecentUsers(@Param("limit") int limit);

    // 索引友好的查詢
    @Query("SELECT * FROM users WHERE status = :status AND created_at > :since")
    Flux<User> findActiveUsersSince(@Param("status") String status,
                                   @Param("since") LocalDateTime since);
}
```

# 遷移策略：JDBC 到 R2DBC

## 階段性遷移

1. **保持現有 JDBC 架構**
2. **逐步引入 R2DBC 依賴**
3. **新增響應式 Repository**
4. **建立新 API 端點**
5. **逐步替換舊端點**

## 雙重實作示例

```java
// 舊的 JDBC 實作
@Service
public class LegacyUserService {
    // 保持不變
}

// 新的 R2DBC 實作
@Service
public class ReactiveUserService {

    private final UserRepository userRepository;

    // 新實作使用 R2DBC
    public Flux<User> getAllUsersReactive() {
        return userRepository.findAll();
    }
}
```

# 何時選擇 R2DBC？

## 適合使用 R2DBC 的場景

✅ **高併發應用程式**
- 每秒數千請求
- 需要高效資源利用

✅ **微服務架構**
- 與 Spring WebFlux 配合
- 事件驅動系統

✅ **I/O 密集型操作**
- 大量資料庫查詢
- 外部 API 調用

✅ **雲端原生應用**
- 容器化部署
- 自動擴展需求

## 適合使用 JDBC 的場景

✅ **簡單 CRUD 應用**
- 併發需求不高
- 團隊熟悉同步程式設計

✅ **複雜 ORM 需求**
- 需要 Hibernate 進階功能
- 複雜的關聯查詢

✅ **遺留系統整合**
- 現有 JDBC 基礎設施
- 短期專案

## 決策矩陣

| 因素 | JDBC | R2DBC |
|------|------|-------|
| 開發複雜度 | 低 | 中等 |
| 學習曲線 | 平緩 | 陡峭 |
| 資源利用率 | 中等 | 高 |
| 生態系統成熟度 | 高 | 成長中 |
| 團隊熟悉度 | 高 | 需要學習 |

最終選擇取決於你的具體需求、團隊經驗和專案規模。R2DBC 在高併發、響應式應用中有明顯優勢，但需要對反應式程式設計有一定了解。

