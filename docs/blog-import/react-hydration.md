---
title: "react-hydration"
publishDate: "2026-01-02 13:00:00"
img: /tymultiverse/assets/react.png
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  從根本探討為什麼需要服務端渲染 (SSR)，以及 SSR 為什麼會更快。深入解析 React Hydration 機制，通過實際主題切換按鈕案例，學習如何正確處理 SSR/CSR 協作，避免常見的 hydration 失敗問題。
level: advance
category: React
tags:
  - react
  - hydration
  - astro
  - ssr
  - frontend
---

# 從 SSR 到 Hydration：現代前端渲染的完整指南

## 🎯 核心問題：按鈕看得見卻點不動

想像一下，你花了一整天開發了一個美觀的主題切換按鈕。上線後，按鈕看起來完美無缺，但當使用者點擊時...**什麼反應都沒有**。

這不是單純的程式碼錯誤，而是現代前端渲染架構的核心問題：**Hydration 失敗**。

本文將從這個具體問題出發，帶你深入理解：
- 為什麼需要服務端渲染 (SSR)
- SSR 到底為什麼會快
- React Hydration 的工作原理
- 如何解決實際的 hydration 問題

## 🌟 第一幕：網頁渲染的演進之路

### 從靜態到動態：前端框架的興起

**早期網路時代**：網頁就是靜態 HTML 文件。
```html
<!-- 簡單的靜態頁面 -->
<h1>歡迎來到我的網站</h1>
<p>這是一個靜態頁面。</p>
```

**JavaScript 革命**：前端框架讓網頁變得高度互動。
- React、Vue、Angular 的誕生
- 單頁應用 (SPA) 的流行
- **但帶來了新的問題**：首屏渲染速度慢

### CSR (客戶端渲染) 的致命缺陷

傳統 SPA 採用完全的客戶端渲染：

```html
<!-- 初始 HTML -->
<html>
<body>
  <div id="root"></div>  <!-- 👈 空的容器 -->
  <script src="app.js"></script>  <!-- 👈 巨大的 JS bundle -->
</body>
</html>
```

**使用者的痛苦體驗**：
1. ⬇️ 下載 HTML（幾 KB，幾乎瞬間）
2. ⬇️ 下載 JavaScript bundle（200-2000KB，需要 1-5 秒）
3. ⚙️ 瀏覽器執行 JavaScript，生成頁面內容
4. 👁️ **使用者終於看到內容**

**結果**：**2-5 秒的空白畫面**，使用者體驗極差。

## 🚀 第二幕：SSR 的誕生與速度革命

### SSR：服務端渲染的魔法

為了解決 CSR 的問題，**服務端渲染** 應運而生：

```html
<!-- SSR 生成的完整 HTML -->
<html>
<body>
  <div id="root">
    <h1>歡迎來到我的網站</h1>
    <p>這是完整渲染的內容</p>
    <button>點擊我</button>
  </div>
  <script src="app.js"></script>
</body>
</html>
```

**使用者體驗的飛躍**：
1. ⬇️ 下載完整 HTML（立即看到內容）
2. ⬇️ 同時下載 JavaScript（背景載入）
3. ⚙️ JavaScript 載入完成，頁面變得互動

### 為什麼 SSR 會這麼快？揭開 Critical Rendering Path 的神秘面紗

#### 1. 瀑布流等待 vs 並行處理

**CSR 的串聯等待**：
```
HTML 下載 → JS 下載 → JS 執行 → 內容生成 → 用戶看到畫面
   ↓         ↓         ↓         ↓            ↓
  50ms     2-5秒     500ms     200ms        總計: 3-7秒
```

**SSR 的並行優化**：
```
HTML 生成 → HTML + JS 同時下載 → 內容立即顯示 → JS 注水互動
   ↓              ↓                    ↓            ↓
  100ms        1-3秒               立即顯示       互動恢復
```

#### 2. 網路傳輸的根本差異

| 資源類型 | 大小 | 載入時間 | 解析複雜度 |
|---------|------|---------|-----------|
| **HTML** | 5-20KB | ~50-200ms | 瀏覽器原生，瞬間完成 |
| **JS Bundle** | 200-2000KB | 1-5秒 | 需要解析、編譯、執行 |

**關鍵洞察**：**傳輸時間差異高達 40-100 倍**！

#### 3. 運算資源的差異

- **手機端 CPU**：通常比伺服器弱，JavaScript 執行較慢
- **伺服器端**：專用硬體，生成 HTML 比手機運算 DOM 快得多
- **電池消耗**：SSR 減少客戶端運算，節省電池

#### 4. 效能指標的量化改善

- **First Contentful Paint (FCP)**: 從 2-5秒 ⬇️ 降至 0.2-0.5秒
- **Time to Interactive (TTI)**: 從 3-8秒 ⬇️ 降至 1-3秒
- **Largest Contentful Paint (LCP)**: 顯著改善
- **SEO 友好度**: 從 0 ⬇️ 升至 100

## 🔄 第三幕：Hydration 的魔法 - 讓靜態變互動

### React 的雙重生命：兩個不同的世界

React 程式碼會在**兩個完全不同的環境**中運行：

#### 🌐 伺服器端 (Server Side)
**運行環境**：Node.js 或 Edge Runtime（如 Vercel、Cloudflare）

**任務**：負責「運算」出 HTML
- 讀取資料庫、API 資料
- 執行 React 組件邏輯
- 將 `<App />` 轉換成純文字 HTML

**關鍵限制**：**沒有瀏覽器環境**
- ❌ `window` 物件不存在
- ❌ `document` 物件不存在
- ❌ `localStorage` 無法存取
- ❌ 任何 DOM API 都無法使用

#### 🖥️ 客戶端 (Client Side / Browser)
**運行環境**：使用者的瀏覽器

**任務**：負責「互動」
- 處理點擊事件 (`onClick`)
- 管理狀態變化
- 執行動畫和過渡
- 存取瀏覽器專用 API

### Hydration：讓靜態 HTML 恢復生命

**問題**：伺服器傳來的 HTML 是「死」的
- ✅ 有正確的外觀
- ✅ 有正確的內容
- ❌ 點擊沒有反應
- ❌ 沒有事件處理器

**解決方案**：**Hydration (注水)**

```javascript
// 1. SSR 生成靜態 HTML
<button>點擊我</button>

// 2. 客戶端 Hydration
ReactDOM.hydrateRoot(document.getElementById('root'), <App />);

// 3. 結果：相同的 HTML，現在充滿生命力
<button onClick={handleClick}>點擊我</button>
```

**Hydration 的四個階段**：
1. **服務端渲染**：React 在伺服器生成 HTML
2. **客戶端接管**：React 在客戶端重新執行，比較 HTML
3. **事件綁定**：附加事件處理器，恢復互動性
4. **狀態同步**：恢復應用狀態和 Context

## 💥 第四幕：Hydration 失敗的真實案例

### 場景重現：主題切換按鈕的災難

**原始程式碼**：
```astro
<!-- Nav.astro -->
<ThemeProvider client:load>
  <ThemeToggle />
</ThemeProvider>
```

```tsx
// ThemeToggle.tsx
export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  return <button onClick={toggleTheme}>切換主題</button>;
}
```

**使用者體驗**：
- ✅ 按鈕正常顯示
- ❌ 點擊完全無反應
- ❌ 控制台無錯誤訊息

### 根本原因剖析：伺服器 vs 客戶端的資料衝突

**Hydration 失敗的經典場景**：

```javascript
// 伺服器端（沒有 localStorage 權限）
const theme = 'light'; // 只能用預設值
// 生成 HTML：<button>亮色主題</button>

// 客戶端（可以讀取使用者設定）
const theme = localStorage.getItem('theme') || 'dark';
// 期望生成：<button>暗色主題</button>
```

**災難性結果**：
1. React 在 Hydration 時發現 HTML 不匹配
2. 可能放棄綁定事件處理器
3. 按鈕看起來正常，但完全不能點擊

**為什麼會發生這種情況？**
- 伺服器沒有瀏覽器環境，無法讀取 `localStorage`
- 客戶端有完整環境，可以讀取使用者偏好設定
- 兩邊的渲染結果不一致，Hydration 失敗

## 🛠️ 第五幕：解決方案與最佳實務

### 核心問題的解決策略

#### 方案一：client:load (預設，但有風險)

```astro
<ThemeProvider client:load>
  <ThemeToggle />
</ThemeProvider>
```

**適用場景**：不依賴瀏覽器專用 API 的組件

#### 方案二：client:only (徹底解決，但犧牲效能)

```astro
<ThemeProvider client:only="react">
  <ThemeToggle />
</ThemeProvider>
```

**適用場景**：依賴 `localStorage`、`window` 等瀏覽器 API 的組件

### 完整的修復方案

#### 1. 選擇正確的 Client 指令

```astro
<!-- 修改前：有風險 -->
<ThemeProvider client:load>
  <ThemeToggle />
</ThemeProvider>

<!-- 修改後：100% 可靠 -->
<ThemeProvider client:only="react">
  <ThemeToggle />
</ThemeProvider>
```

#### 2. 增強組件健壯性

```tsx
export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    console.log('[ThemeToggle] 組件已掛載');
    setMounted(true);
  }, []);

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    e.stopPropagation();

    console.log('[ThemeToggle] 按鈕被點擊');

    if (typeof toggleTheme === 'function') {
      toggleTheme();
      console.log('[ThemeToggle] 主題切換成功');
    }
  };

  return (
    <button
      onClick={handleClick}
      style={{ cursor: 'pointer', pointerEvents: 'auto' }}
    >
      切換主題
    </button>
  );
}
```

#### 3. 添加備用方案

```javascript
// 當 React Hydration 失敗時的原生備用方案
function initThemeToggleFallback() {
  const button = document.querySelector('.theme-toggle button');

  if (!button) return;

  // 檢查是否已有 React 事件處理器
  const hasReactHandlers = Object.keys(button).some(key =>
    key.startsWith('__react') || key.startsWith('_react')
  );

  if (hasReactHandlers) {
    console.log('[備用方案] React 已接管，跳過備用方案');
    return;
  }

  console.log('[備用方案] 啟動原生主題切換');
  button.addEventListener('click', () => {
    // 原生主題切換邏輯
    const html = document.documentElement;
    const isDark = html.classList.contains('theme-dark');
    const newTheme = isDark ? 'light' : 'dark';

    html.classList.remove('theme-light', 'theme-dark');
    html.classList.add(`theme-${newTheme}`);
    localStorage.setItem('theme', newTheme);
  });
}

// 延遲執行，給 React 時間
setTimeout(initThemeToggleFallback, 1000);
```

### 除錯技巧與最佳實務

#### 1. Hydration 狀態檢查

```javascript
// 在瀏覽器控制台檢查
const button = document.querySelector('.theme-toggle button');
console.log('按鈕元素:', button);
console.log('是否有點擊處理器:', button.onclick);
console.log('React 屬性:', Object.keys(button).filter(k => k.includes('react')));
```

#### 2. 選擇合適的渲染策略

| 組件類型 | 推薦方案 | 原因 |
|---------|---------|------|
| 靜態內容 | `client:load` | 速度快，SEO 友好 |
| 簡單互動 | `client:load` | 平衡效能和功能 |
| 瀏覽器 API 依賴 | `client:only` | 避免 Hydration 失敗 |
| 重型組件 | `client:idle` | 延遲載入，提升首屏 |

#### 3. Context Provider 的正確使用

```tsx
// ✅ 正確做法
function App() {
  return (
    <ThemeProvider>
      <Nav />
    </ThemeProvider>
  );
}

// ❌ 錯誤做法
function Nav() {
  return (
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>
  );
}
```

## 🎬 第六幕：核心原則總結

### 我們學到了什麼

1. **渲染演進的必然性**：從靜態 HTML → CSR → SSR → SSR + Hydration
2. **SSR 速度的根本原因**：Critical Rendering Path 的優化
3. **React 雙重環境的差異**：伺服器端 vs 客戶端
4. **Hydration 失敗的根源**：資料不一致導致的事件處理器遺失
5. **解決方案的取捨**：效能 vs 可靠性

### 核心原則

**當組件依賴瀏覽器專用 API 時**：
- **寧願放棄 SSR 的速度優勢**
- **也要確保功能 100% 正常運作**
- **備用方案是你的最後防線**

### 技術選型的建議

| 優先級 | 考量因素 | 建議選擇 |
|-------|---------|---------|
| **最高** | 功能正確性 | `client:only` |
| **中等** | 效能優化 | `client:load` + 防護措施 |
| **最低** | 完美體驗 | 選擇性 Hydration |

**記住**：好的程式碼不僅要解決問題，還要讓下一個開發者能夠理解為什麼這樣解決。

## 📚 延伸閱讀

- [React 官方文件：Hydration](https://react.dev/reference/react-dom/client/hydrateRoot)
- [Astro 文件：Client Directives](https://docs.astro.build/en/reference/directives-reference/#client-directives)
- [Web.dev：Hydration](https://web.dev/rendering-on-the-web/#server-rendering)

- 添加 `pointer-events: auto !important` 确保点击事件不被阻止
- 为图标和伪元素添加 `pointer-events: none` 确保点击事件传递到按钮

```css
/* 修改前 */
.theme-toggle {
  position: fixed !important;
  /* ... */
}

/* 修改后 */
body .theme-toggle {
  position: fixed !important;
  pointer-events: auto !important;
  /* ... */
}

body .theme-toggle button {
  cursor: pointer !important;
  pointer-events: auto !important;
  /* ... */
}

body .theme-toggle .icon {
  pointer-events: none; /* 圖示不攔截點擊 */
  /* ... */
}
```


