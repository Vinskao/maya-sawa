# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

# Install Poetry from the default PyPI index (the Tsinghua mirror is not
# reachable from the CI build network and timed out).
RUN pip install --no-cache-dir poetry

# Copy dependency definitions
COPY pyproject.toml poetry.lock ./

# Install dependencies to system site-packages (since we are in a container)
# Configure Poetry for better network reliability
RUN poetry config virtualenvs.create false \
    && poetry config installer.max-workers 10 \
    && poetry install --no-root --only main --verbose \
    && pip cache purge \
    && rm -rf /root/.cache/pypoetry

# Final stage
FROM python:3.12-slim

WORKDIR /app

# ffmpeg / ffprobe are required by the /videos/merge-videos endpoint.
# The Debian package pulls in the whole SDL2/mesa/GTK/pulseaudio stack (~164MB
# and ~20min of apt work) that a headless server never uses, so copy the static
# binaries instead. Multi-arch, so this still resolves correctly on arm64.
COPY --from=mwader/static-ffmpeg:7.1.1 /ffmpeg /ffprobe /usr/local/bin/

# Copy installed dependencies from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Runtime configuration (OpenAI / DB / Redis / ...) is injected by
# k8s/deployment.yaml through envsubst, and the build passes no secret
# build-args, so the image deliberately bakes in no ARG/ENV defaults.

# Copy project files (__pycache__ and *.py[cod] are excluded by .dockerignore)
COPY . .

# Expose port
EXPOSE 8000

# Start command
CMD ["sh", "-c", "uvicorn maya_sawa.main:app --host 0.0.0.0 --port 8000"]

