# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies with mirror for better network reliability
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn && \
    pip install --no-cache-dir poetry

# Copy dependency definitions
COPY pyproject.toml poetry.lock ./

# Install dependencies to system site-packages (since we are in a container)
# Configure Poetry for better network reliability
RUN poetry config virtualenvs.create false \
    && poetry config installer.max-workers 10 \
    && poetry config experimental.new-installer false \
    && poetry install --no-root --only main --verbose \
    && pip cache purge \
    && rm -rf /root/.cache/pypoetry

# Final stage
FROM python:3.12-slim

WORKDIR /app

# Copy installed dependencies from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Build arguments for env vars
ARG OPENAI_API_KEY
ARG OPENAI_ORGANIZATION
ARG DB_HOST
ARG DB_PORT
ARG DB_DATABASE
ARG DB_USERNAME
ARG DB_PASSWORD
ARG DB_SSLMODE
ARG REDIS_HOST
ARG REDIS_CUSTOM_PORT
ARG REDIS_PASSWORD
ARG REDIS_QUEUE_MAYA
ARG PUBLIC_API_BASE_URL

# Set environment variables
ENV OPENAI_API_KEY=${OPENAI_API_KEY}
ENV OPENAI_ORGANIZATION=${OPENAI_ORGANIZATION}
ENV OPENAI_API_BASE=https://api.openai.com/v1
ENV DB_HOST=${DB_HOST}
ENV DB_PORT=${DB_PORT}
ENV DB_DATABASE=${DB_DATABASE}
ENV DB_USERNAME=${DB_USERNAME}
ENV DB_PASSWORD=${DB_PASSWORD}
ENV DB_SSLMODE=${DB_SSLMODE}
ENV REDIS_HOST=${REDIS_HOST}
ENV REDIS_CUSTOM_PORT=${REDIS_CUSTOM_PORT}
ENV REDIS_PASSWORD=${REDIS_PASSWORD}
ENV REDIS_QUEUE_MAYA=${REDIS_QUEUE_MAYA}
ENV PUBLIC_API_BASE_URL=${PUBLIC_API_BASE_URL}

# Copy project files
COPY . .

# Clean up
RUN find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true \
    && find . -type f -name '*.pyc' -delete \
    && find . -type f -name '*.pyo' -delete

# Expose port
EXPOSE 8000

# Start command
CMD ["sh", "-c", "uvicorn maya_sawa.main:app --host 0.0.0.0 --port 8000"]

