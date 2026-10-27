---
title: "speech-to-speech-framework"
publishDate: "2025-09-19 15:30:00"
img: /tymultiverse/assets/langchain.png
img_alt: Real-time speech AI framework illustration
description: |
  Pipecat 語音 AI 框架完整指南：從 Python 基礎到實時語音處理，掌握現代語音 AI 應用開發的核心技術與最佳實踐
level: advance
category: AI
tags:
  - Pipecat
  - Speech AI
  - Real-time Processing
  - Python Framework
  - Voice Interface
---
# Pipecat 語音 AI 框架指南

## 前言

Pipecat 是一個專門為實時語音 AI 應用設計的 Python 框架。

## 術語表

| 術語 | 說明 |
|------|------|
| Frame | 數據傳輸單位 |
| Processor | 處理幀的組件 |
| Pipeline | 連接處理器的處理鏈 |
| STT | 語音轉文字 |
| TTS | 文字轉語音 |
| VAD | 語音活動檢測 |
---

## Python 基礎

### 非同步程式設計 (Asyncio 核心)

Pipecat 框架的核心是**異步程式設計**，特別依賴 Python 的 `asyncio` 模組來處理即時音頻流和多個 AI 服務的並發操作。

#### **為什麼需要 Asyncio？**

在即時語音 AI 應用中，我們需要同時處理：
- 🎤 **音頻輸入流**：持續接收用戶語音
- 🔄 **語音轉文字**：即時轉換語音為文字
- 🤖 **AI 推理**：處理對話邏輯
- 🔊 **文字轉語音**：即時生成語音回應
- 📡 **音頻輸出流**：持續播放 AI 語音

傳統的同步程式設計無法有效處理這些並發任務，`asyncio` 提供了解決方案。

#### **Asyncio 核心概念**

**協程 (Coroutine)**：
```python
# 基本協程定義
async def process_audio_frame(frame):
    # 處理音頻幀
    await asyncio.sleep(0.01)  # 非阻塞等待
    return processed_frame

# 協程調用
result = await process_audio_frame(audio_frame)
```

**事件循環 (Event Loop)**：
```python
# Asyncio 事件循環
async def main():
    # 並發執行多個任務
    tasks = [
        process_audio_input(),
        process_stt_service(),
        process_llm_service(),
        process_tts_service(),
        process_audio_output()
    ]

    # 等待所有任務完成
    await asyncio.gather(*tasks)

# 啟動事件循環
asyncio.run(main())
```

**任務 (Task)**：
```python
# 創建並行任務
async def run_pipeline():
    # 創建任務但不等待
    audio_task = asyncio.create_task(process_audio_stream())
    llm_task = asyncio.create_task(process_conversation())

    # 等待特定任務完成
    audio_result = await audio_task

    # 取消不需要的任務
    llm_task.cancel()

    return audio_result
```

#### **Pipecat 中的 Asyncio 應用**

**幀處理管道**：
```python
# 典型的 Pipecat 處理流程
async def process_frame_pipeline(frame, direction):
    # 1. 驗證幀
    await validate_frame(frame)

    # 2. 路由處理
    if isinstance(frame, AudioFrame):
        result = await process_audio_frame(frame)
    elif isinstance(frame, TextFrame):
        result = await process_text_frame(frame)
    else:
        result = frame

    # 3. 傳遞給下一個處理器
    await pass_to_next_processor(result, direction)

    return result
```

**並發服務調用**：
```python
# 同時調用多個 AI 服務
async def call_multiple_services(text_input):
    # 並發執行
    openai_task = asyncio.create_task(call_openai_service(text_input))
    anthropic_task = asyncio.create_task(call_anthropic_service(text_input))

    # 獲取最快的回應
    done, pending = await asyncio.wait(
        [openai_task, anthropic_task],
        return_when=asyncio.FIRST_COMPLETED
    )

    # 取消未完成的任務
    for task in pending:
        task.cancel()

    # 返回最快完成的結果
    return done.pop().result()
```

#### **Asyncio 最佳實踐**

**錯誤處理**：
```python
# 正確的錯誤處理
async def safe_process_frame(frame):
    try:
        result = await process_frame(frame)
        return result
    except asyncio.TimeoutError:
        print("處理超時")
        return None
    except Exception as e:
        print(f"處理錯誤: {e}")
        return None
```

**資源管理**：
```python
# 使用 async context manager
async def process_with_resources():
    async with aiofiles.open('audio.wav', 'rb') as audio_file:
        data = await audio_file.read()
        processed = await process_audio_data(data)
        return processed
```

**效能優化**：
```python
# 批次處理優化
async def batch_process_frames(frames):
    # 限制並發數量
    semaphore = asyncio.Semaphore(10)

    async def process_with_limit(frame):
        async with semaphore:
            return await process_single_frame(frame)

    # 並發處理但限制數量
    tasks = [process_with_limit(frame) for frame in frames]
    results = await asyncio.gather(*tasks)

    return results
```

#### **Asyncio 與 Pipecat 的關係**

Pipecat 框架的設計完全基於 `asyncio`：
- **FrameProcessor**：每個處理器都是協程
- **Pipeline**：協程鏈的組合
- **Transport**：異步通信層
- **Service**：異步 AI 服務調用

理解 `asyncio` 是掌握 Pipecat 的關鍵，因為框架的所有核心組件都依賴異步編程模式。

### Python 底線使用

| 模式 | 示例 | 說明 |
|------|------|------|
| `_var` | `self._balance` | 約定私有，可訪問但不建議修改 |
| `__var` | `self.__balance` | 真正私有，Python 會改名 |
| `__method__` | `__init__`, `__str__` | 特殊方法，自動調用 |
| `_` | `for _ in range(5)` | 丟棄不需要的值 |
| `var_` | `class_` | 避免關鍵字衝突 |

約定私有、真正私有和特殊方法的示例。

---

## Pipecat 框架基礎

### Maya 專案結構

```
maya/
├── main.py          # 入口點
├── bot.py           # 機器人邏輯
├── config.py        # 配置管理
├── services.py      # 服務工廠
├── processors.py    # 自定義處理器
└── custom_tts.py    # 自定義 TTS
```

### Java 開發者對照表

| Pipecat | Java/Spring |
|---------|-------------|
| Frame | DTO/Message |
| Processor | @Service |
| Pipeline | Filter Chain |
| `__init__` | Constructor |
| `_var` | protected |
| `__var` | private |
| `asyncio` | CompletableFuture |

---

## Pipecat 核心概念

### 三大核心組件

#### Frame（幀）
數據傳輸單位，包含 TranscriptionFrame、TTSSpeakFrame、InterruptionFrame 等。

#### Processor（處理器）
所有處理器的基類，實現單一職責原則。

**Java 開發者類比**：Pipecat 的 Processor 就像 Java 中的 Service 或 Handler。

核心設計理念：
- **單一職責**：一個 Processor 只專注於一項任務
- **可組合性**：Processor 可以像樂高積木一樣被組裝

就像 Java Spring 的 `@Service` 一樣，每個 Processor 都是獨立的、可重用的組件。

#### Pipeline（流水線）
連接處理器的鏈，實現責任鏈模式。

---

## FrameProcessor 架構

### 內部結構
包含上游/下游處理器引用、時鐘管理、輸入輸出隊列等組件。

### 優先隊列設計
支持高優先級和低優先級幀的分別處理。

### 幀流向控制
支持順流和逆流兩個方向的數據傳輸。

## Pipeline 連接機制

### 自動連接邏輯
動態鏈接所有處理器，形成完整的處理鏈。

### Maya 的流水線
包含音頻輸入、靜音過濾、語音處理、對話處理、語音輸出等環節。

---

## AI 服務設計

### 服務層次結構
```python
AIService (基礎服務)
├── STTService (語音轉文字)
├── TTSService (文字轉語音)
├── LLMService (大語言模型)
└── VisionService (視覺服務)
```

### 服務工廠模式
統一管理不同類型服務的創建。

### 服務生命週期
服務的啟動、運行和停止過程管理。

---

## STTMuteFilter - 解決語音中斷

### 問題根源
語音 AI 的「自我中斷」問題：
```
用戶說話 → AI 回應 → 喇叭播放 AI 語音
           ↓
麥克風收到 AI 聲音 → VAD 認為用戶還在說話
           ↓
發送 InterruptionFrame → TTS 被中斷
```

### Java 開發者思維
STTMuteFilter 類似 AOP 攔截器：

```java
// Java AOP
@Around("execution(* SttService.process(..))")
public Object muteInterceptor(ProceedingJoinPoint pjp) {
    if (botIsSpeaking) return null;  // 攔截
    return pjp.proceed();            // 繼續
}
```

```python
# Pipecat STTMuteFilter
class STTMuteFilter(FrameProcessor):
    async def process_frame(self, frame, direction):
        if self._is_muted and isinstance(frame, InputAudioRawFrame):
            return  # 攔截音頻幀
        await self.push_frame(frame, direction)  # 放行其他幀
```

### 工作原理
監測機器人說話狀態，動態控制靜音開關。

### 靜音策略
支持總是靜音、只第一次靜音、函數調用時靜音等多種策略。

---

## Pipecat 設計模式與架構理念

### 設計原則

Pipecat 框架的核心設計理念可以總結為：

1. **單一職責原則**：每個處理器只負責一項特定任務
2. **開放封閉原則**：可以擴展功能而不修改現有代碼
3. **依賴倒置原則**：高層模塊不依賴低層模塊的具體實現
4. **組合優於繼承**：通過組合創建複雜功能

### 架構模式分析

#### **處理器模式 (Processor Pattern)**

Pipecat 的核心是處理器模式，每個處理器都是獨立的、可組合的組件。

**簡單示例**：
```python
# 處理器模式的應用
async def process_audio(frame):
    # 每個處理器只做一件事
    normalized = await normalize_audio(frame)    # 音頻標準化
    transcribed = await transcribe_audio(normalized)  # 語音轉文字
    response = await generate_response(transcribed)    # 生成回應
    return response
```

#### **責任鏈模式 (Chain of Responsibility)**

Pipeline 實現了責任鏈模式，每個處理器都有機會處理或傳遞數據。

**簡單示例**：
```python
# 責任鏈模式的應用
def process_request(request):
    # 按順序處理
    if validate_request(request):     # 第一個處理器
        if authenticate_user(request): # 第二個處理器
            if authorize_access(request): # 第三個處理器
                return process_business_logic(request) # 最終處理器
    return None
```

#### **工廠模式 (Factory Pattern)**

ServiceFactory 實現了工廠模式，統一管理服務創建。

**簡單示例**：
```python
# 工廠模式的應用
def create_service(service_type):
    services = {
        "openai": lambda: OpenAILLMService(),
        "anthropic": lambda: AnthropicLLMService(),
        "google": lambda: GoogleLLMService()
    }
    return services[service_type]()
```

#### **策略模式 (Strategy Pattern)**

STTMuteFilter 實現了策略模式，支持不同的靜音策略。

**簡單示例**：
```python
# 策略模式的應用
def process_mute(audio_frame, strategy):
    strategies = {
        "always": lambda: True,                    # 總是靜音
        "smart": lambda: detect_speech(audio_frame), # 智慧靜音
        "never": lambda: False                     # 不靜音
    }
    should_mute = strategies[strategy]()
    return None if should_mute else audio_frame
```

### 設計模式的應用場景

#### **觀察者模式 (Observer Pattern)**

用於監控和日誌系統的實現。

**簡單示例**：
```python
# 觀察者模式的應用
def notify_observers(event, observers):
    for observer in observers:
        observer.on_event(event)  # 通知所有觀察者

# 使用方式
metrics_logger = MetricsLogger()
error_handler = ErrorHandler()
notify_observers("request_processed", [metrics_logger, error_handler])
```

#### **裝飾器模式 (Decorator Pattern)**

用於功能增強和橫切關注點的處理。

**簡單示例**：
```python
# 裝飾器模式的應用
def log_execution(func):
    def wrapper(*args, **kwargs):
        print(f"執行 {func.__name__}")
        result = func(*args, **kwargs)
        print(f"{func.__name__} 完成")
        return result
    return wrapper

@log_execution
def process_frame(frame):
    return frame  # 實際處理邏輯
```

#### **模板方法模式 (Template Method Pattern)**

用於標準化處理流程的實現。

**簡單示例**：
```python
# 模板方法模式的應用
def process_request_template(request):
    # 標準化處理流程
    validate_request(request)      # 1. 驗證請求
    authenticate_user(request)     # 2. 用戶認證
    authorize_access(request)      # 3. 權限檢查
    process_business_logic(request) # 4. 業務邏輯
    send_response(request)         # 5. 發送回應
```

### 架構設計的核心理念

#### **1. 模組化設計 (Modular Design)**

Pipecat 的核心優勢在於其模組化架構，可以輕鬆替換或增減組件。

**簡單示例**：
```python
# 模組化組裝
modules = [
    AudioInputModule(),
    STTModule(),
    LLMModule(),
    TTSModule(),
    AudioOutputModule()
]

# 可以動態增減模組
modules.append(NoiseReductionModule())  # 添加降噪模組
modules.remove(STTModule())             # 移除語音識別模組
```

#### **2. 數據流驅動 (Data Flow Driven)**

Pipecat 採用數據流驅動的設計理念，處理器根據數據類型決定行為。

**簡單示例**：
```python
# 數據流驅動
def route_frame(frame):
    if isinstance(frame, AudioFrame):
        return process_audio(frame)
    elif isinstance(frame, TextFrame):
        return process_text(frame)
    elif isinstance(frame, CommandFrame):
        return process_command(frame)
    else:
        return frame  # 透傳
```

#### **3. 異步優先 (Async-First)**

Pipecat 從設計之初就採用異步優先的架構，支持並發處理多個任務。

**簡單示例**：
```python
# 異步優先處理
async def process_parallel(frame):
    # 並發執行多個任務
    tasks = [
        validate_frame(frame),
        process_audio(frame),
        update_metrics(frame)
    ]
    results = await asyncio.gather(*tasks)
    return results
```

#### **4. 可擴展性 (Extensibility)**

Pipecat 的架構具備良好的可擴展性，可以輕鬆集成新的處理器和第三方服務。

**簡單示例**：
```python
# 可擴展的架構
def add_custom_processor(pipeline, processor_class):
    processor = processor_class()
    pipeline.add_processor(processor)
    return pipeline

# 使用第三方服務
def integrate_service(service_client):
    async def process_with_service(frame):
        response = await service_client.process(frame)
        return response
    return process_with_service
```

### 設計模式的綜合應用

Pipecat 框架將多種設計模式有機結合：

#### **具體結構示例**：

**工廠模式 + 策略模式**：
```python
# 服務創建結構
services = {
    "openai": {"class": OpenAILLMService, "config": {"model": "gpt-4o"}},
    "anthropic": {"class": AnthropicLLMService, "config": {"model": "claude-3"}},
    "google": {"class": GoogleLLMService, "config": {"model": "gemini-pro"}}
}

def create_service(service_name, strategy="default"):
    service_info = services[service_name]
    service_class = service_info["class"]
    config = service_info["config"]

    # 根據策略調整配置
    if strategy == "fast":
        config["temperature"] = 0.1
    elif strategy == "creative":
        config["temperature"] = 0.9

    return service_class(**config)
```

**責任鏈模式 + 觀察者模式**：
```python
# Pipeline 處理鏈結構
class ProcessingChain:
    def __init__(self):
        self.processors = []
        self.observers = []

    def add_processor(self, processor):
        self.processors.append(processor)
        # 通知觀察者
        for observer in self.observers:
            observer.on_processor_added(processor)

    def process(self, data):
        result = data
        for processor in self.processors:
            result = processor.process(result)
            # 通知觀察者處理結果
            for observer in self.observers:
                observer.on_processing_step(result)
        return result
```

**裝飾器模式 + 模板方法模式**：
```python
# 處理器裝飾結構
def logging_decorator(processor_func):
    def wrapper(*args, **kwargs):
        print(f"開始處理: {processor_func.__name__}")
        start_time = time.time()

        # 模板方法：標準處理流程
        result = processor_func(*args, **kwargs)

        end_time = time.time()
        print(f"處理完成: {processor_func.__name__}, 耗時: {end_time - start_time:.2f}s")

        return result
    return wrapper

@logging_decorator
def process_audio_frame(frame):
    # 具體處理邏輯
    return normalized_frame
```

這種設計讓 Pipecat 既保持了架構的清晰性，又具備了極強的靈活性和擴展性。

---

## Pipecat 內建 LLM 服務詳解

### 服務依賴層次結構

Pipecat 提供了完整的 LLM 服務生態系統：

**具體結構**：
```
AIService (抽象基類)
├── LLMService (大語言模型)
│   ├── OpenAILLMService
│   │   ├── GPT-4o
│   │   ├── GPT-4o-mini
│   │   └── GPT-3.5-turbo
│   ├── AnthropicLLMService
│   │   ├── Claude-3-Opus
│   │   ├── Claude-3-Sonnet
│   │   └── Claude-3-Haiku
│   └── GoogleLLMService
│       ├── Gemini-1.5-Pro
│       └── Gemini-1.5-Flash
```

### 服務初始化示例

#### **具體結構示例**：

**OpenAI 服務初始化結構**：
```python
# 服務配置結構
openai_config = {
    "service_type": "openai",
    "model": "gpt-4o-mini",
    "api_key": os.getenv("OPENAI_API_KEY"),
    "parameters": {
        "temperature": 0.7,
        "max_tokens": 150,
        "top_p": 0.9,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0
    },
    "system_instruction": "你是個友善的AI助手",
    "safety_settings": {
        "content_filter": "moderate",
        "max_retries": 3
    }
}

# 初始化服務
llm_service = OpenAILLMService(**openai_config)
```

**Anthropic 服務初始化結構**：
```python
anthropic_config = {
    "service_type": "anthropic",
    "model": "claude-3-haiku-20240307",
    "api_key": os.getenv("ANTHROPIC_API_KEY"),
    "parameters": {
        "temperature": 0.7,
        "max_tokens": 150,
        "top_p": 0.9,
        "top_k": 250
    },
    "system_instruction": "你是個專業的AI助手",
    "safety_settings": {
        "content_filter": "strict",
        "max_retries": 3
    }
}
```

### 統一的服務接口

Pipecat 的設計理念是統一接口，多樣實現：

**接口結構示例**：
```python
# 統一的服務接口
class UnifiedLLMService:
    async def initialize(self, config: dict) -> bool:
        """服務初始化"""
        pass

    async def generate_response(self, context: dict) -> str:
        """生成回應"""
        pass

    async def stream_response(self, context: dict) -> AsyncGenerator[str, None]:
        """流式回應"""
        pass

    async def get_token_count(self, text: str) -> int:
        """獲取token數量"""
        pass

    async def validate_config(self, config: dict) -> bool:
        """驗證配置"""
        pass
```

### 實際應用場景

#### 1. **簡單對話機器人**
```python
# Pipeline 結構
conversation_pipeline = {
    "input_processor": AudioInputProcessor(),
    "stt_service": OpenAISTTService(),
    "llm_service": OpenAILLMService(model="gpt-4o-mini"),
    "tts_service": ElevenLabsTTSService(),
    "output_processor": AudioOutputProcessor(),
    "connection": "sequential"  # 順序連接
}
```

#### 2. **多模型切換**
```python
# 模型切換結構
model_router = {
    "default_model": "gpt-4o-mini",
    "models": {
        "fast": {
            "service": OpenAILLMService(model="gpt-3.5-turbo"),
            "config": {"temperature": 0.3, "max_tokens": 100}
        },
        "creative": {
            "service": AnthropicLLMService(model="claude-3-haiku"),
            "config": {"temperature": 0.9, "max_tokens": 200}
        },
        "complex": {
            "service": OpenAILLMService(model="gpt-4o"),
            "config": {"temperature": 0.7, "max_tokens": 500}
        }
    },
    "routing_rules": {
        "short_query": "fast",
        "creative_task": "creative",
        "complex_analysis": "complex"
    }
}
```

### 性能優化建議

#### 1. **模型選擇策略**
- **gpt-4o-mini**: 平衡性能與成本，適合一般對話
- **claude-3-haiku**: 快速回應，適合實時應用
- **gemini-pro**: 多模態支援，適合複雜任務

#### 2. **Token 管理**
```python
llm = OpenAILLMService(
    model="gpt-4o-mini",
    max_tokens=100,        # 控制輸出長度
    temperature=0.3,       # 降低創造性，提高一致性
)
```

#### 3. **快取策略**
```python
# 使用記憶體快取減少重複請求
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext

context = OpenAILLMContext()
# 上下文會自動快取對話歷史
```

---

## LangChain 在 Pipecat 中的應用

### 為什麼要整合 LangChain？

雖然 Pipecat 提供了強大的內建 LLM 服務，但 LangChain 提供了更進階的功能：

```python
# LangChain 的優勢
✅ 複雜的提示工程 (Prompt Engineering)
✅ 鏈式推理 (Chain Reasoning)
✅ 工具整合 (Tool Integration)
✅ 記憶管理 (Memory Management)
✅ 多步驟工作流 (Multi-step Workflows)
```

### Maya 專案整合 LangChain

#### **具體整合結構**：

**LangChain 處理器結構**：
```python
# LangChain 處理器配置結構
langchain_processor_config = {
    "processor_type": "langchain",
    "chain_type": "conversation_with_memory",
    "components": {
        "llm": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "temperature": 0.7,
            "max_tokens": 150
        },
        "prompt_template": {
            "system_message": "你是 Maya，一個友善的 AI 助手...",
            "human_message": "{input}",
            "memory_placeholder": "{chat_history}"
        },
        "memory": {
            "type": "conversation_buffer",
            "max_history_length": 10,
            "session_id": "maya_session_{user_id}"
        }
    },
    "integrations": {
        "pipecat_hooks": {
            "on_start_frame": "initialize_memory",
            "on_end_frame": "cleanup_memory",
            "on_error": "handle_langchain_error"
        }
    }
}
```

**記憶管理結構**：
```python
# 記憶存儲結構
memory_store_structure = {
    "type": "session_based",
    "storage": {
        "backend": "redis",  # 或 "memory", "file", "database"
        "config": {
            "host": "localhost",
            "port": 6379,
            "db": 0,
            "key_prefix": "maya_memory:"
        }
    },
    "session_management": {
        "session_timeout": 3600,  # 1小時
        "max_sessions_per_user": 5,
        "cleanup_strategy": "lru"  # least recently used
    },
    "memory_types": {
        "conversation_history": {
            "max_messages": 20,
            "format": "message_objects"
        },
        "user_preferences": {
            "storage_key": "user_prefs_{user_id}",
            "update_strategy": "merge"
        },
        "context_facts": {
            "ttl": 86400,  # 24小時
            "importance_scoring": True
        }
    }
}
```

**工具整合結構**：
```python
# 工具整合結構
tool_integration_structure = {
    "tool_registry": {
        "weather_tool": {
            "name": "get_weather",
            "description": "獲取指定城市的天气信息",
            "parameters": {
                "city": {"type": "string", "required": True},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
            },
            "handler": "weather_api_client.get_weather"
        },
        "calculator_tool": {
            "name": "calculate",
            "description": "執行數學計算",
            "parameters": {
                "expression": {"type": "string", "required": True}
            },
            "handler": "math_engine.evaluate"
        }
    },
    "tool_execution": {
        "strategy": "parallel",  # 或 "sequential"
        "timeout": 30,  # 秒
        "error_handling": "fallback_to_llm",
        "permission_system": {
            "enabled": True,
            "tool_permissions": {
                "admin": ["all"],
                "user": ["weather_tool", "calculator_tool"],
                "guest": ["weather_tool"]
            }
        }
    }
}
```

**簡單示例**：
```python
# 創建帶記憶的 LangChain 處理器
from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

# 設計提示模板
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是個友善的AI助手"),
    ("human", "{input}"),
])

# 創建鏈
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
chain = prompt | llm

# 整合到 Pipecat
langchain_processor = LangchainProcessor(chain)
```

### 進階 LangChain 功能

#### 1. **工具整合 (Tool Integration)**

**簡單示例**：
```python
# 自定義工具函數
def get_weather(city: str) -> str:
    return f"{city}的天氣是晴天，溫度25°C"

# 創建帶工具的代理
tools = [get_weather]
llm = ChatOpenAI(model="gpt-4o-mini")
agent = create_openai_functions_agent(llm, tools, prompt)
```

#### 2. **複雜工作流 (Complex Workflows)**

**簡單示例**：
```python
# 條件分支工作流
def route_request(input_text):
    if len(input_text) > 50:
        # 複雜問題使用高級模型
        return complex_chain.invoke({"input": input_text})
    else:
        # 簡單問題使用基礎模型
        return simple_chain.invoke({"input": input_text})
```

### 在 Maya 專案中的應用

**整合方式**：
```python
# 在 Maya 專案中替換處理器
conversation_processor = create_langchain_processor()

pipeline = Pipeline([
    transport.input(),
    stt,
    conversation_processor,  # 使用 LangChain 處理器
    tts,
    transport.output()
])
```

**配置設置**：
```python
# LangChain 配置
LANGCHAIN_MODEL = "gpt-4o-mini"
LANGCHAIN_TEMPERATURE = 0.7
ENABLE_MEMORY = True
```

### 實際部署建議

#### 1. **漸進式遷移**
- 第一階段：使用 Pipecat 內建服務快速上線
- 第二階段：根據需求遷移到 LangChain 獲取進階功能

#### 2. **功能測試**
- 測試基本對話功能
- 測試記憶功能是否正常
- 測試工具整合（如果使用）

### 總結

Pipecat 的內建 LLM 服務提供了**簡單高效**的解決方案，而 LangChain 整合則提供了**強大的擴展能力**：

- **內建服務**：適合快速開發和簡單應用
- **LangChain**：適合複雜的 AI 工作流和企業級應用

你可以根據專案需求選擇合適的方案，也可以從內建服務開始，根據需要逐步遷移到 LangChain 整合。

---