# 使用官方 Python 映像作為基礎映像
FROM python:3.12-slim

# 設定工作目錄
WORKDIR /app

# 定義 build arguments
ARG OPENAI_API_KEY
ARG OPENAI_ORGANIZATION
ARG POSTGRES_CONNECTION_STRING
ARG REDIS_HOST
ARG REDIS_CUSTOM_PORT
ARG REDIS_PASSWORD
ARG REDIS_QUEUE_QA_KM
ARG PUBLIC_API_BASE_URL

# 複製 pyproject.toml 和 poetry.lock
COPY pyproject.toml poetry.lock ./

# 安裝 Poetry
RUN pip install --no-cache-dir poetry

# 使用 Poetry 安裝 Python 依賴項
RUN poetry config virtualenvs.create false \
    && poetry install --no-root --only main

# 複製其餘的專案文件
COPY . .

# 設定環境變數
ENV OPENAI_API_KEY=${OPENAI_API_KEY}
ENV OPENAI_ORGANIZATION=${OPENAI_ORGANIZATION}
ENV OPENAI_API_BASE=https://api.openai.com/v1
ENV POSTGRES_CONNECTION_STRING=${POSTGRES_CONNECTION_STRING}
ENV REDIS_HOST=${REDIS_HOST}
ENV REDIS_CUSTOM_PORT=${REDIS_CUSTOM_PORT}
ENV REDIS_PASSWORD=${REDIS_PASSWORD}
ENV REDIS_QUEUE_QA_KM=${REDIS_QUEUE_QA_KM}
ENV PUBLIC_API_BASE_URL=${PUBLIC_API_BASE_URL}

# 暴露 FastAPI 預設的埠
EXPOSE 8000

# 啟動命令
CMD ["sh", "-c", "PYTHONPATH=. poetry run uvicorn maya_sawa.main:app --host 0.0.0.0 --port 8000"]

