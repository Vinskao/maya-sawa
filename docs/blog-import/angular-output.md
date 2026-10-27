---
title: "angular-output"
publishDate: "2025-12-26 13:00:00"
img: /tymultiverse/assets/angular.png
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  探索 Angular 17.3 中引入的 Signal-based Outputs (output()) 如何取代傳統的 @Output 裝飾器，提供更簡潔且效能更好的組件間通信方式。
level: advance
category: Angular
tags:
  - angular
  - signals
  - typescript
---

# Angular Signal-based Outputs 深度解析

## 🚀 從零開始：TypeScript 基礎概念

在深入探討 Angular 的 `output()` 之前，讓我們先建立必要的 TypeScript 基礎知識。這些概念對於理解 `readonly` 修飾符至關重要。

### 什麼是 TypeScript？

**TypeScript** 是 JavaScript 的超集（Superset），為 JavaScript 添加了**靜態類型系統**。簡單來說：

```typescript
// JavaScript (動態類型)
let name = "John";
name = 123; // 允許，運行時才會出錯

// TypeScript (靜態類型)
let name: string = "John";
name = 123; // 編譯錯誤！TypeScript 會在開發時就發現這個錯誤
```

### 類別屬性（Class Properties）的基本概念

在 TypeScript 中，類別的屬性可以有**修飾符（Modifiers）**來控制它們的行為：

```typescript
class Example {
  // 公開屬性（預設）
  public normalProperty: string = "可以修改";

  // 私有屬性（只能在類別內部使用）
  private secretProperty: string = "外部看不到";

  // 保護屬性（子類別可以使用）
  protected familyProperty: string = "給子類用的";

  // 唯讀屬性（只能讀取，不能修改）
  readonly immutableProperty: string = "不能改！";
}
```

### 🔍 深入理解 `readonly` 修飾符

#### `readonly` 的基本含義

`readonly` 是 TypeScript 的**屬性修飾符**，它的作用是**防止屬性被重新賦值**。

```typescript
class Person {
  // 普通屬性：可以隨意修改
  name: string = "John";

  // 唯讀屬性：只能讀取，不能修改
  readonly id: number = 123;

  constructor() {
    this.name = "Jane"; // ✅ 可以修改
    this.id = 456; // ❌ 編譯錯誤！
  }

  updateName(newName: string) {
    this.name = newName; // ✅ 可以修改
    this.id = 789; // ❌ 編譯錯誤！
  }
}
```

#### 為什麼要用 `readonly`？

1. **防止意外修改**：保護重要的數據不會被不小心改變
2. **表達意圖**：告訴其他開發者「這個屬性不應該被修改」
3. **編譯時期檢查**：在開發時就發現潛在的錯誤，而非運行時

#### `readonly` vs `const` 的差異

```typescript
// const: 用於變數宣告
const PI = 3.14159; // 不能重新賦值

class Circle {
  readonly radius: number; // 屬性修飾符

  constructor(radius: number) {
    this.radius = radius; // ✅ 建構函式中可以設定
    // this.radius = 10; // ❌ 之後就不能改了
  }
}
```

### 屬性修飾符的位置

在 TypeScript 中，修飾符**總是寫在屬性名稱前面**：

```typescript
class Component {
  // 語法： [修飾符] 屬性名稱: 類型 [= 初始值]

  public name: string = "component";     // 公開屬性
  private count: number = 0;             // 私有屬性
  protected config: object = {};         // 保護屬性
  readonly version: string = "1.0.0";    // 唯讀屬性

  // 也可以組合使用
  public readonly apiKey: string = "secret"; // 公開但唯讀
}
```

### 實際應用場景

#### 場景 1：組件狀態
```typescript
class LoadingButton {
  readonly buttonId: string; // 按鈕 ID 不應該改變

  isLoading: boolean = false; // 可以改變的狀態
  clickCount: number = 0;    // 可以改變的計數

  constructor(id: string) {
    this.buttonId = id; // 在建構函式中設定
  }
}
```

#### 場景 2：API 響應
```typescript
class ApiResponse {
  readonly statusCode: number;   // HTTP 狀態碼不會改變
  readonly requestId: string;    // 請求 ID 不會改變

  data: any;                     // 數據可能會被後續處理
  isCached: boolean = false;     // 快取狀態可能改變
}
```

### 常見問題解答

**Q: 為什麼要寫在前面？**
A: 這是 TypeScript 的語法規則，所有修飾符都放在屬性名稱前面，這樣可以清楚地表達屬性的訪問權限和可變性。

**Q: 如果不加修飾符呢？**
A: 預設是 `public`，表示任何地方都可以訪問和修改。

**Q: `readonly` 可以用在方法上嗎？**
A: 不行，`readonly` 只適用於屬性，不適用於方法。

現在你已經掌握了 `readonly` 的基礎知識，讓我們回到 Angular 的 `output()` 函式...

## 什麼是組件輸出（Component Outputs）？

在 Angular 中，**輸出屬性（Output Properties）** 是組件間通信的重要機制。它允許**子組件向父組件發送事件和數據**，實現從下到上的數據流。這是 Angular 單向數據流的關鍵部分。

`readonly addItemEvent = output();` 代表的是 Angular 在 17.3 版本中引入的 **Signal-based Outputs**（基於 Signal 的輸出），這是對傳統 `@Output() addItemEvent = new EventEmitter();` 的現代化替代方案。

## 基本語法與函式簽章

### 標準語法

```typescript
readonly eventName = output<T>();
```

### 函式參數詳解

`output<T>()` 函式接受一個可選的泛型參數：

- **`T`**：指定輸出事件所攜帶的數據類型
- **返回值**：返回 `OutputEmitterRef<T>` 類型的物件
- **無參數時**：預設為 `output<void>()`，表示不攜帶數據的事件

### 實際使用範例

```typescript
// 基本事件（無數據）
readonly itemDeleted = output();

// 攜帶特定類型數據的事件
readonly itemAdded = output<Item>();
readonly countChanged = output<number>();
readonly userSelected = output<UserData>();

// 複雜對象類型
readonly formSubmitted = output<{valid: boolean, data: FormData}>();
```

## 語法解析：每個部分的深入含義

### 1. `output()` 函式

**核心功能**：
- 建立一個輸出屬性，讓子組件可以向父組件發送訊號
- 回傳 `OutputEmitterRef<T>` 實例，這個物件具有 `emit()` 方法
- 在 Angular 的 Signals 系統中註冊該輸出

**技術細節**：
- 內部使用 Angular 的 Signals 機制進行變更偵測
- 不依賴 Zone.js，可以在無 Zone 環境中正常運作
- 與 `input()` 函式形成對稱的 API 設計

### 2. `readonly` 修飾符

**安全性考量**：
- 防止意外重新賦值輸出屬性
- 確保輸出物件的引用不會被改變
- 這是 **Angular 官方強烈推薦的寫法**

**為什麼需要 readonly？**
```typescript
// ❌ 危險：可能意外重新賦值
addItemEvent = output();

// 某處程式碼不小心...
this.addItemEvent = new EventEmitter(); // 破壞了原有的輸出機制

// ✅ 安全：編譯時期就阻止錯誤
readonly addItemEvent = output();
// this.addItemEvent = ...; // TypeScript 編譯錯誤
```

### 3. 事件名稱命名

**命名慣例**：
- 使用 **camelCase** 格式
- 通常以動詞結尾，表示發生的動作
- 應描述事件的本質，而非具體行為

```typescript
// 好的命名
readonly itemAdded = output<Item>();
readonly userLoggedIn = output<User>();
readonly formSubmitted = output<FormData>();
readonly selectionChanged = output<SelectedItem[]>();

// 不推薦的命名
readonly click = output(); // 太過籠統
readonly data = output(); // 沒有動作意味
```

## 與傳統 @Output 的對比分析

### 傳統 @Output 寫法

```typescript
import { Component, EventEmitter, Output } from '@angular/core';

@Component({...})
export class ChildComponent {
  @Output() itemAdded = new EventEmitter<Item>();

  addItem(item: Item) {
    this.itemAdded.emit(item);
  }
}
```

### 新版 output() 寫法

```typescript
import { Component, output } from '@angular/core';

@Component({...})
export class ChildComponent {
  readonly itemAdded = output<Item>();

  addItem(item: Item) {
    this.itemAdded.emit(item);
  }
}
```

## 四大核心優勢詳解

### 🎯 更簡潔的語法結構

**裝飾器 vs 函式**：
- **傳統方式**：需要 `@Output()` 裝飾器 + `EventEmitter` 實例化
- **新方式**：單一函式呼叫，與 `input()` API 完全一致

**程式碼行數比較**：
```typescript
// 傳統：3 行 + import EventEmitter
@Output() itemAdded = new EventEmitter<Item>();

// 新版：1 行 + import output
readonly itemAdded = output<Item>();
```

### 🔍 增強的類型推導能力

**自動類型推斷**：
```typescript
// 無需顯式指定類型，TypeScript 可自動推斷
readonly itemAdded = output(); // 推斷為 output<unknown>

// 明確指定類型，提供最佳類型安全
readonly itemAdded = output<Item>();
```

**編譯時期檢查**：
```typescript
readonly userSelected = output<User>();

// ✅ 正確使用
this.userSelected.emit({id: 1, name: 'John'});

// ❌ 編譯錯誤：類型不匹配
this.userSelected.emit('invalid string'); // Error!
```

### ⚡ 效能與包體大小優化

**RxJS 依賴性**：
- **傳統 @Output**：強制依賴 RxJS 的 `EventEmitter`（繼承自 `Subject`）
- **新版 output()**：零 RxJS 依賴，可在無 RxJS 的專案中減少約 20-30KB

**效能特點**：
- 使用 Angular Signals 的變更偵測機制
- 在無 Zone.js 環境中表現更佳
- 記憶體使用更有效率

### 🔄 Signals 生態系統的一致性

**完整的 Signals API 家族**：
```typescript
// 輸入：從父組件接收數據
readonly user = input<User>();

// 輸出：向父組件發送事件
readonly userChanged = output<User>();

// 內部狀態：組件內部狀態管理
readonly isLoading = signal(false);

// 計算屬性：基於其他 Signals 的衍生狀態
readonly displayName = computed(() => `${this.user().firstName} ${this.user().lastName}`);
```

## 事件發送機制詳解

### emit() 方法的運作原理

```typescript
export class ChildComponent {
  readonly itemAdded = output<Item>();

  addNewItem(item: Item) {
    // 發送事件到父組件
    this.itemAdded.emit(item);

    // 可以連續發送多個事件
    this.itemAdded.emit(anotherItem);
  }
}
```

**事件傳遞流程**：
1. 子組件呼叫 `emit(value)`
2. Angular Signals 系統記錄變更
3. 父組件的 event binding 被觸發
4. 執行對應的處理函式

### 父組件的事件接收

**HTML 範本語法**：
```html
<!-- 標準事件綁定 -->
<app-child (itemAdded)="onItemAdded($event)"></app-child>

<!-- 解構賦值（Angular 17+） -->
<app-child (itemAdded)="onItemAdded($event); totalItems = totalItems + 1"></app-child>

<!-- 無數據事件 -->
<app-child (itemDeleted)="onItemDeleted()"></app-child>
```

**TypeScript 處理邏輯**：
```typescript
export class ParentComponent {
  totalItems = 0;
  items: Item[] = [];

  onItemAdded(newItem: Item) {
    console.log('新項目已添加：', newItem);
    this.items.push(newItem);
    this.totalItems = this.items.length;
  }

  onItemDeleted() {
    console.log('項目已刪除');
    this.totalItems = this.items.length;
  }
}
```

## 類型安全與泛型應用

### 基本類型安全

```typescript
// 基本資料類型
readonly countChanged = output<number>();
readonly isVisible = output<boolean>();
readonly message = output<string>();

// 自訂類型
interface User {
  id: number;
  name: string;
  email: string;
}

readonly userSelected = output<User>();
```

### 複雜對象類型

```typescript
// 表單數據
interface FormResult {
  isValid: boolean;
  data: Record<string, any>;
  errors: string[];
}

readonly formSubmitted = output<FormResult>();

// API 響應
interface ApiResponse<T> {
  success: boolean;
  data: T;
  error?: string;
}

readonly apiCompleted = output<ApiResponse<Item[]>>();
```

### 聯合類型與可選類型

```typescript
// 聯合類型：支援多種可能的數據類型
readonly notification = output<SuccessMessage | ErrorMessage | WarningMessage>();

// 可選屬性
readonly userUpdate = output<Partial<User>>();

// 字面量類型
readonly action = output<'create' | 'update' | 'delete'>();
```

## 實際應用模式與最佳實踐

### 常見使用模式

#### 1. CRUD 操作事件

```typescript
export class DataTableComponent {
  readonly itemCreated = output<Item>();
  readonly itemUpdated = output<Item>();
  readonly itemDeleted = output<ItemId>();
  readonly itemsReordered = output<ItemOrderChange>();
}
```

#### 2. 用戶互動事件

```typescript
export class SearchComponent {
  readonly searchQueryChanged = output<string>();
  readonly searchExecuted = output<SearchCriteria>();
  readonly suggestionSelected = output<string>();
}
```

#### 3. 狀態變更通知

```typescript
export class LoadingButtonComponent {
  readonly clicked = output<void>();
  readonly loadingStateChanged = output<boolean>();
}
```

### 最佳實踐建議

1. **總是使用 `readonly`**：保護輸出屬性不被意外修改
2. **明確指定泛型類型**：提供最佳的類型安全和開發體驗
3. **使用描述性事件名稱**：讓父組件清楚了解發生了什麼
4. **保持事件簡單**：每個輸出應只負責一種特定的事件類型
5. **考慮使用介面**：對於複雜的數據結構，定義明確的 TypeScript 介面

### 遷移指南

**從 @Output 遷移到 output()**：

```typescript
// 舊版
@Output() itemAdded = new EventEmitter<Item>();

// 新版
readonly itemAdded = output<Item>();

// 發送事件保持不變
this.itemAdded.emit(item);
```

**父組件使用方式完全相同**，無需修改 HTML 範本。

## 🎯 Angular 17+ 新特性：@defer 指令詳解

除了 Signal-based Outputs，Angular 17 還引入了 `@defer` 指令，這是一個強大的**延遲載入（Deferred Loading）**機制。讓我們深入探討這個革命性的功能。

### 什麼是 @defer？

**`@defer`** 是 Angular 17 中引入的控制流指令，用於**延遲載入組件或組件的一部分**，直到特定條件滿足時才進行渲染。這對於提升應用程式的初始載入效能至關重要。

### 基本語法

```typescript
@defer {
  <comments />
} @placeholder {
  <p>Future comments</p>
} @loading {
  <p>Loading comments...</p>
}
```

### 語法解析

#### 1. `@defer` 區塊 - 主內容
```typescript
@defer {
  <comments />
}
```
- **作用**：定義需要延遲載入的主要內容
- **行為**：當觸發條件滿足時，才會載入和渲染 `<comments />` 組件
- **預設觸發**：組件首次可見時（進入視窗）

#### 2. `@placeholder` 區塊 - 預留位置
```typescript
@placeholder {
  <p>Future comments</p>
}
```
- **作用**：在主內容載入前顯示的替代內容
- **行為**：立即渲染，提供即時的視覺回饋
- **用途**：改善使用者體驗，避免空白區域

#### 3. `@loading` 區塊 - 載入狀態
```typescript
@loading {
  <p>Loading comments...</p>
}
```
- **作用**：在主內容載入期間顯示的載入指示器
- **行為**：主內容開始載入但尚未完成時顯示
- **用途**：提供載入進度的視覺回饋

#### 4. `@error` 區塊 - 錯誤處理
```typescript
@error {
  <p>Failed to load comments</p>
}
```
- **作用**：當載入過程發生錯誤時顯示的內容
- **行為**：載入失敗時自動顯示
- **用途**：提供錯誤處理和降級體驗

### 延遲載入策略

#### 1. 視窗進入 (預設)
```typescript
@defer {
  <comments />
}
```
- **觸發時機**：組件進入視窗時
- **使用場景**：非立即需要的內容，如評論區、相關文章等

#### 2. 互動觸發
```typescript
@defer (on interaction) {
  <modal />
}
```
- **觸發時機**：使用者與元素互動時（如點擊、滑鼠移入）
- **使用場景**：模態框、工具提示、下拉選單等

#### 3. 滑鼠移入觸發
```typescript
@defer (on hover) {
  <tooltip />
}
```
- **觸發時機**：滑鼠移到元素上時
- **使用場景**：工具提示、預覽圖片等

#### 4. 立即觸發
```typescript
@defer (on immediate) {
  <critical-component />
}
```
- **觸發時機**：立即載入（但仍在下一個變更偵測週期）
- **使用場景**：需要立即但不阻塞初始渲染的內容

#### 5. 計時器觸發
```typescript
@defer (on timer(5s)) {
  <delayed-content />
}
```
- **觸發時機**：指定時間後
- **使用場景**：延遲載入的廣告、分析腳本等

#### 6. 條件觸發
```typescript
@defer (when conditionExpression) {
  <conditional-content />
}
```
- **觸發時機**：當條件表達式為 true 時
- **使用場景**：基於狀態的動態載入

### 實際應用範例

#### 範例 1：評論區延遲載入
```typescript
@Component({
  template: `
    <article>
      <h1>{{ article.title }}</h1>
      <p>{{ article.content }}</p>

      <!-- 評論區延遲載入 -->
      @defer {
        <comments [articleId]="article.id" />
      } @placeholder {
        <div class="comments-placeholder">
          <button (click)="loadComments()">載入評論</button>
        </div>
      } @loading {
        <div class="loading-spinner">載入評論中...</div>
      }
    </article>
  `
})
export class ArticleComponent {
  loadComments() {
    // 手動觸發載入
  }
}
```

#### 範例 2：互動式模態框
```typescript
@defer (on interaction) {
  <user-modal [user]="selectedUser" />
} @placeholder {
  <button class="user-button" (click)="openModal()">
    檢視使用者資訊
  </button>
} @loading {
  <div class="modal-loading">載入使用者資料...</div>
}
```

#### 範例 3：條件式載入
```typescript
@defer (when showAdvancedFeatures) {
  <advanced-dashboard />
} @placeholder {
  <button (click)="enableAdvancedMode()">
    啟用進階模式
  </button>
}
```

### 效能優勢

#### 1. 初始包體大小減少
- **原理**：延遲載入的組件不會包含在初始 JavaScript 包中
- **效果**：減少初始載入時間，提升 First Contentful Paint (FCP)

#### 2. 記憶體使用優化
- **原理**：未使用的組件不會被實例化
- **效果**：降低應用程式的記憶體佔用

#### 3. 網路流量節省
- **原理**：按需載入，減少不必要的網路請求
- **效果**：改善在慢速網路環境下的使用者體驗

### 技術細節

#### 載入機制
```typescript
// Angular 內部處理流程
1. 渲染 @placeholder 內容
2. 監聽觸發條件
3. 條件滿足時動態載入組件
4. 替換 @placeholder 為實際內容
5. 執行變更偵測和生命週期鉤子
```

#### 組件分割
```typescript
// 自動程式碼分割
// 原始組件
// ├── main.bundle.js (核心)
// └── comments.bundle.js (延遲載入)

// 觸發載入時才下載 comments.bundle.js
```

#### 依賴注入
```typescript
// 延遲載入的組件可以使用完整的 DI 容器
// 與立即載入的組件沒有差異
```

### 最佳實踐

#### 1. 識別延遲載入候選組件
```typescript
// ✅ 適合延遲載入
- 評論區、討論區
- 模態框、對話框
- 工具提示、說明文字
- 進階功能區塊
- 圖片畫廊的詳細資訊

// ❌ 不適合延遲載入
- 主要內容、核心功能
- 導航元件
- 全域狀態相關組件
- 立即需要的用戶介面
```

#### 2. 設計優質的 Placeholder
```typescript
// 提供有意義的預留位置
@placeholder {
  <div class="skeleton-loader">
    <div class="skeleton-title"></div>
    <div class="skeleton-content"></div>
  </div>
}
```

#### 3. 錯誤處理策略
```typescript
@defer {
  <complex-component />
} @error {
  <div class="error-state">
    <p>組件載入失敗，請重新整理頁面</p>
    <button (click)="retry()">重試</button>
  </div>
}
```

#### 4. 效能監控
```typescript
// 使用 Angular DevTools 監控
// - 載入時間
// - 包體大小
// - 記憶體使用量
```

### 瀏覽器支援

- **Chrome/Edge**: 87+
- **Firefox**: 78+
- **Safari**: 14+
- **支援程度**: 現代瀏覽器的原生支援

### 與其他技術的比較

#### vs. 手動延遲載入
```typescript
// 傳統方式：手動處理
@Component({
  template: `
    <div *ngIf="isLoaded; else loading">
      <comments />
    </div>
    <ng-template #loading>
      <p>Loading...</p>
    </ng-template>
  `
})
export class MyComponent implements OnInit {
  isLoaded = false;

  ngOnInit() {
    // 手動載入邏輯
    import('./comments.component').then(() => {
      this.isLoaded = true;
    });
  }
}

// @defer 方式：宣告式
@defer {
  <comments />
} @loading {
  <p>Loading...</p>
}
```

#### 優勢比較
- **程式碼簡潔性**: @defer 更簡潔
- **自動化程度**: @defer 自動處理程式碼分割
- **錯誤處理**: @defer 內建錯誤處理
- **觸發條件**: @defer 支援多種觸發策略

### 遷移指南

#### 從手動延遲載入遷移
```typescript
// 舊方式
<div *ngIf="commentsLoaded">
  <comments />
</div>

// 新方式
@defer (when commentsLoaded) {
  <comments />
}
```

#### 從第三方庫遷移
```typescript
// 如果使用 ngx-loadable 或類似庫
// 可以逐步替換為 @defer

@defer {
  <heavy-component />
} @loading {
  <loading-spinner />
}
```

### 總結

`@defer` 是 Angular 17 的一個革命性功能，它提供了：

- **🚀 效能提升**：減少初始載入時間和包體大小
- **🎯 開發體驗**：宣告式的延遲載入語法
- **🔧 靈活性**：多種觸發條件和狀態處理
- **📱 使用者體驗**：平滑的載入過渡和錯誤處理

這個功能讓 Angular 開發者能夠輕鬆實現現代 web 應用程式的最佳實踐，大幅提升應用程式的效能和使用者體驗。