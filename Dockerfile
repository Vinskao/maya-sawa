# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

# Install Poetry from the default PyPI index (the Tsinghua mirror is not
# reachable from the CI build network and timed out).
RUN pip install --no-cache-dir poetry

# Copy dependency definitions
COPY pyproject.toml poetry.lock ./

# Install dependencies to system site-packages (since we are in a container)
# Serialize system package updates: concurrent uninstalls can remove dist-info
# while another pip process is scanning it (e.g. certifi / charset-normalizer).
RUN poetry config virtualenvs.create false \
    && poetry config installer.max-workers 1 \
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

# Traditional Chinese font for the Instagram text cards (maya_sawa/services/social/card.py). Two pinned,
# checksum-verified OTF weights (~11MB) instead of apt's full fonts-noto-cjk (~90MB). SIL Open Font License.
RUN python -c "import hashlib, os, urllib.request; base = 'https://github.com/notofonts/noto-cjk/raw/Sans2.004/Sans/SubsetOTF/TC/'; fonts = {'NotoSansTC-Regular.otf': '5bab0cb3c1cf89dde07c4a95a4054b195afbcfe784d69d75c340780712237537',          'NotoSansTC-Bold.otf': '55420b259eb119bf5f2a0aadba10cf9d736c12d64ab93e78546d69ef5f43558b'}; os.makedirs('/usr/share/fonts/noto-tc', exist_ok=True); [open('/usr/share/fonts/noto-tc/' + name, 'wb').write(data) if hashlib.sha256(data).hexdigest() == digest  else exit(name + ' checksum mismatch')  for name, digest in fonts.items() for data in [urllib.request.urlopen(base + name, timeout=120).read()]]"

# Graphviz lays out and draws the research Mermaid flowcharts for the social posts (services/social/diagram.py).
# fontconfig finds the Noto Sans TC files above ("Noto Sans TC"); no-install-recommends keeps the layer small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends graphviz fontconfig \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# Runtime configuration (OpenAI / DB / Redis / ...) is injected by
# k8s/deployment.yaml through envsubst, and the build passes no secret
# build-args, so the image deliberately bakes in no ARG/ENV defaults.

# Copy project files (__pycache__ and *.py[cod] are excluded by .dockerignore)
COPY . .

# Expose port
EXPOSE 8000

# Start command
CMD ["sh", "-c", "uvicorn maya_sawa.main:app --host 0.0.0.0 --port 8000"]

