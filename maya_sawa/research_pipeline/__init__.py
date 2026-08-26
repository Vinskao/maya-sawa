"""Research Zone AI 更新管線（deterministic core）。

本 package 只負責「證據 -> change set -> deterministic merge -> validation」的
純函式核心，不含 LLM、OCI、FastAPI 或 Celery 依賴。
"""
