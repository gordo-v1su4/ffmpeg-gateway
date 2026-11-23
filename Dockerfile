# linux/amd64: FFglitch binaries from https://ffglitch.org/pub/bin/linux64/
# For ARM64, change the URL/dir to a linux-aarch64 build from https://ffglitch.org/pub/bin/
# ffmpeg pinned to the build every homelab machine uses (proxmox-home docs/ffmpeg-version-pin.md):
# BtbN n8.1.3-39-g660b5aa7db, static GPL, from our checksum-verified copy in RustFS.
FROM debian:trixie-slim AS ffmpeg
ARG FFMPEG_BUILD=n8.1.3-39-g660b5aa7db
ARG FFMPEG_SHA256=b1c6934b4c3cbbbc0e0a39671c012437db99b719d8ec640ba3371a5876115d78
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates xz-utils \
    && curl -fsSL -o /tmp/ffmpeg.tar.xz "https://s3.v1su4.dev/storyception/tools/ffmpeg/${FFMPEG_BUILD}/ffmpeg-${FFMPEG_BUILD}-linux64-gpl-8.1.tar.xz" \
    && echo "${FFMPEG_SHA256}  /tmp/ffmpeg.tar.xz" | sha256sum -c - \
    && mkdir /tmp/ffmpeg && tar -xJf /tmp/ffmpeg.tar.xz -C /tmp/ffmpeg --strip-components=1 \
    && install -m 755 /tmp/ffmpeg/bin/ffmpeg /tmp/ffmpeg/bin/ffprobe /usr/local/bin/

FROM ubuntu:22.04

# The pinned ffmpeg in both places: compose points FFMPEG_PATH/FFPROBE_PATH at /usr/bin.
COPY --from=ffmpeg /usr/local/bin/ffmpeg /usr/local/bin/ffprobe /usr/local/bin/
COPY --from=ffmpeg /usr/local/bin/ffmpeg /usr/local/bin/ffprobe /usr/bin/

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libsdl2-2.0-0 libasound2 libdrm2 libxcb1 \
    python3.11 \
    python3.11-dev \
    python3.11-venv \
    curl \
    ca-certificates \
    unzip \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv

RUN mkdir -p /opt/ffglitch \
    && curl -fsSL -o /tmp/ffglitch.zip "https://ffglitch.org/pub/bin/linux64/ffglitch-0.10.2-linux-x86_64.zip" \
    && unzip -q /tmp/ffglitch.zip -d /tmp \
    && mv /tmp/ffglitch-0.10.2-linux-x86_64/* /opt/ffglitch/ \
    && rm -rf /tmp/ffglitch.zip /tmp/ffglitch-0.10.2-linux-x86_64 \
    && chmod +x /opt/ffglitch/ffedit /opt/ffglitch/ffgac /opt/ffglitch/qjs /opt/ffglitch/fflive

ENV PATH="/opt/ffglitch:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

WORKDIR /app
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN useradd -r -s /bin/false appuser \
    && chmod +x /docker-entrypoint.sh

EXPOSE 3200

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=6 \
    CMD curl -fsS --max-time 3 http://127.0.0.1:3200/health || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3200"]

