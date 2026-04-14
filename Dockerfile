# linux/amd64: FFglitch binaries from https://ffglitch.org/pub/bin/linux64/
# For ARM64, change the URL/dir to a linux-aarch64 build from https://ffglitch.org/pub/bin/
FROM ubuntu:22.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
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

