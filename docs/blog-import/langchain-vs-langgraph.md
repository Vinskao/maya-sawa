---
title: "langchain-vs-langgraph"
publishDate: "2025-09-05 15:30:00"
img: /tymultiverse/assets/langchain.png
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  LangChain vs LangGraph 精要教學指南：深入比較兩個 LLM 框架的差異、應用場景與實作範例，幫助開發者選擇適合的工具建構 AI 應用
level: advance
category: AI
tags:
  - LangChain
  - LangGraph
  - LLM Framework
  - AI Development
  - Prompt Engineering
---

# LangChain vs LangGraph：精要教學指南

這份教學將之前討論的內容（包括 LangChain 的程式碼範例、Context Engineering 圖解、Prompt Chaining 概念，以及 LangGraph 的核心優勢）整理成一個精簡的比較框架。重點是幫助初學者理解這兩個工具的差異與應用。

LangChain 和 LangGraph 都是由 LangChain 團隊開發的開源框架，用來建構基於大語言模型 (LLM，如 ChatGPT) 的應用，但它們的焦點不同：LangChain 更注重快速組裝 LLM 應用，LangGraph 則專注於複雜的狀態化工作流程。

我會先介紹基礎概念，然後比較它們，最後特別說明初學者必須知道的知識。教學會用簡單比喻、步驟解釋和範例，讓內容易懂。

## 1. 什麼是 LangChain？

LangChain 是一個框架，用來簡化 LLM 應用的開發。它讓你能輕鬆整合提示 (prompts)、模型、資料來源和工具，形成一個「鏈條」(chain)來處理任務。核心是 LCEL (LangChain Expression Language)，它像一個管道系統，讓你用 `|` 符號連接不同組件。

### 主要功能：

- **建構簡單到中等的 LLM 應用**，如文字提取、轉換格式
- **支持 Prompt Chaining**：把複雜任務拆分成多步驟鏈條，每步用一個專注的提示處理，前一步輸出傳給下一步
- **整合外部工具**，如 RAG (Retrieval-Augmented Generation，從資料庫檢索資訊)

### 簡單比喻：
LangChain 像一個工具箱，你可以用裡面的零件（提示、模型、解析器）快速組裝一個機器（應用），適合處理單一或短鏈任務。

### 範例（從之前程式碼）：

```python
# 安裝：pip install langchain langchain-community langchain-openai langgraph
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

llm = ChatOpenAI(temperature=0)  # 初始化 LLM

# 第一步提示：提取規格
prompt_extract = ChatPromptTemplate.from_template("Extract the technical specifications from the following text:\n\n{text_input}")

# 第二步提示：轉成 JSON
prompt_transform = ChatPromptTemplate.from_template("Transform the following specifications into a JSON object with 'cpu', 'memory', and 'storage' as keys:\n\n{specifications}")

# 建構鏈條
extraction_chain = prompt_extract | llm | StrOutputParser()
full_chain = {"specifications": extraction_chain} | prompt_transform | llm | StrOutputParser()

# 執行
input_text = "The new laptop model features a 3.5 GHz octa-core processor, 16GB of RAM, and a 1TB NVMe SSD."
final_result = full_chain.invoke({"text_input": input_text})
print(final_result)  # 輸出 JSON
```

這是 Prompt Chaining 的應用：先提取，再轉換，提高可靠性。

## 2. 什麼是 LangGraph？

LangGraph 是 LangChain 的擴展框架，專為建構複雜、狀態化 (stateful) 的代理 (agent) 或工作流程設計。它像一個「圖形」(graph)，允許你定義節點 (nodes，如 LLM 呼叫) 和邊緣 (edges，如條件分支)，處理長時間運行、多步驟的任務。

### 主要功能：

- **支持狀態管理**：記住過去步驟的結果（短期/長期記憶）
- **處理分支、循環和人工介入** (human-in-the-loop)
- **整合 LangChain 組件**，但更注重持久執行和調試
- **適合 Agentic 系統**：AI 代理能規劃、推理和執行多步任務

### 簡單比喻：
LangGraph 像一個流程圖軟體，你可以畫出分支路徑，讓機器人 (代理) 根據情況調整路線，適合長跑任務（如聊天機器人記住對話歷史）。

### 範例（基於之前內容的擴展）：

如果用 LangGraph 改寫上述範例，你可以定義一個圖形：

- **節點1**：提取規格 (用 LangChain 的 chain)
- **節點2**：轉換 JSON
- **邊緣**：如果提取失敗，回到節點1 或加入人工檢查

LangGraph 提供檢查點 (checkpointing)，讓流程中斷後能從中繼續。

### 核心優勢（從之前解釋）：

- **持久執行**：自動恢復失敗
- **人工介入**：隨時檢查/修改狀態
- **全面記憶**：短期 (當前任務) + 長期 (跨會話)
- **調試**：用 LangSmith 視覺化路徑
- **部署**：生產級擴展

## 3. LangChain vs LangGraph：比較表

用表格比較，讓初學者一目了然：

| 方面 | LangChain | LangGraph |
|------|-----------|-----------|
| **焦點** | 快速建構 LLM 鏈條和簡單應用 | 複雜狀態化代理和工作流程 |
| **結構** | 線性鏈條 (chains) 用 LCEL 連接 | 圖形結構 (graphs) 支持分支/循環 |
| **適合任務** | 單一/短鏈任務，如文字提取+轉換 | 長時間、多步驟任務，如代理規劃+執行 |
| **狀態管理** | 基本 (需手動添加記憶) | 內建全面記憶 (短期/長期) |
| **Prompt Chaining** | 支持基本鏈接，提高可靠性 | 擴展為圖形，支持更複雜鏈接+條件 |
| **Context Engineering** | 支持提示工程、RAG 等技巧 | 整合這些技巧到狀態化圖形中 |
| **優點** | 簡單易上手，快速原型 | 穩健、持久，適合生產級應用 |
| **缺點** | 不適合複雜分支或長跑任務 | 學習曲線較陡，需了解圖形概念 |
| **整合** | 核心框架 | 基於 LangChain，可無縫整合工具 |
| **工具** | LCEL、提示模板、輸出解析器 | 節點/邊緣、檢查點、LangSmith 調試 |

### 何時選擇？

- **用 LangChain**：如果你是初學者，想快速試 LLM 應用，或任務是線性的（如之前程式碼的規格提取）
- **用 LangGraph**：當任務需要狀態（如記住對話）、分支（如根據結果選擇下一步），或長時間運行（如 AI 聊天機器人）

## 4. 特別說明：初學者必須知道的知識

作為初學者，別急著寫複雜程式，先掌握這些基礎，逐步練習。這些是從之前內容提煉的必備點，避免常見錯誤：

### LLM 基礎：

LLM（如 OpenAI 的 ChatOpenAI）是核心引擎，但它們容易「忘記」上下文或出錯。所以用框架如 LangChain 來管理提示和輸出。

**必須知道**：設定 API 密鑰（e.g., `OPENAI_API_KEY`），用 `.env` 文件儲存，避免硬編碼。

### Prompt Engineering（從 Context Engineering 圖）：

設計清晰提示是關鍵。例如，用 `{變數}` 佔位符，讓提示可重用。

**必須知道**：提示越具體，輸出越準。初學者常犯錯：提示太模糊，導致模型「猜測」。

### Prompt Chaining：

別用單一提示處理複雜任務，拆成小步驟（divide-and-conquer）。

**必須知道**：這提高可靠性，但初學者需注意輸出格式（用 `StrOutputParser` 轉文字，或 `JSONParser` 轉結構化）。

### Context Engineering 技巧（從圖解）：

包括 RAG（查資料）、記憶（記住歷史）、結構化輸出（e.g., JSON）。

**必須知道**：這些技巧可組合用。初學者從 Prompt Engineering 開始，漸進到 RAG（需資料來源如向量資料庫）。

### 安裝與環境：

**必須知道**：用 `pip install langchain langchain-community langchain-openai langgraph`。Python 3.8+，測試在 Jupyter Notebook 中。

**常見坑**：忘記 import 套件，或溫度 (temperature) 設太高導致輸出隨機。

### 生態系統與資源（從 LangGraph 解釋）：

LangChain + LangGraph + LangSmith（調試） + LangGraph Platform（部署）。

**必須知道**：免費資源如 LangChain Academy（課程）、Templates（範本）、Forum（社群）。初學者從範例開始，複製修改。

### 常見錯誤與建議：

**錯誤**：忽略狀態，導致代理「失憶」。

**建議**：從 LangChain 簡單鏈開始，練習 5-10 個範例，再進 LangGraph。閱讀官方文件（langchain.com/docs），並用 `print()` 調試中間輸出。

## 總結

LangChain 和 LangGraph 都是強大的 LLM 開發框架，選擇哪個取決於你的需求：

- **初學者**：從 LangChain 開始，掌握基礎概念
- **進階應用**：當需要複雜狀態管理時，升級到 LangGraph
- **生產環境**：LangGraph 提供更好的持久性和調試能力

記住，最好的學習方式是動手實作。從簡單的 Prompt Chaining 開始，逐步建立對 LLM 應用的理解，然後根據需求選擇合適的工具。
