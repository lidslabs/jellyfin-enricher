# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

# ffmpeg is required by yt-dlp for audio extraction (theme songs) and
# video+audio stream merging (trailers). curl/unzip are used to fetch Deno
# below. ca-certificates for HTTPS.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        curl \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp moves fast. Pin a known-good version; bump the ARG and rebuild
# when YouTube breaks something. We install via pip (not apt) to control the
# exact version independently of Debian's package freeze.
ARG YTDLP_VERSION=2026.06.09

# yt-dlp (2026.06.09+) requires a JavaScript runtime for full YouTube format
# extraction; Deno is yt-dlp's default and needs no extra --js-runtimes flag.
# Without this, downloads fall back to limited format APIs (android-vr-player).
# Bump this when yt-dlp's minimum Deno version moves; current floor is 2.3.
ARG DENO_VERSION=v2.8.3
RUN curl -fsSL -o /tmp/deno.zip \
        "https://github.com/denoland/deno/releases/download/${DENO_VERSION}/deno-x86_64-unknown-linux-gnu.zip" \
    && unzip -q /tmp/deno.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip

# Make the runtime UID/GID match your host media owner so written files have
# correct permissions. Override at build time:
#   docker build --build-arg PUID=$(id -u) --build-arg PGID=$(id -g) ...
ARG PUID=1000
ARG PGID=1000

RUN groupadd -g ${PGID} enricher \
    && useradd -m -u ${PUID} -g enricher -s /bin/bash enricher \
    && mkdir -p /var/lib/enricher \
    && chown -R enricher:enricher /var/lib/enricher

WORKDIR /app
COPY requirements.txt .

# yt-dlp's [default] and [curl-cffi] are INDEPENDENT optional-dependency groups
# in its pyproject.toml — installing [default] alone does NOT pull curl_cffi.
# Both are required for the enricher:
#   [default]   → yt-dlp-ejs (JS challenge solver), mutagen, brotli, certifi,
#                 pycryptodomex, requests, urllib3, websockets
#   [curl-cffi] → curl_cffi for TLS/JA3 fingerprint impersonation, required
#                 by --impersonate (see app/config.py:ytdlp_impersonate)
# curl_cffi's version is pinned by yt-dlp itself — do NOT add curl_cffi to
# requirements.txt or it will fight yt-dlp's version constraint.
# See: https://github.com/yt-dlp/yt-dlp#impersonation

RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "yt-dlp[default,curl-cffi]==${YTDLP_VERSION}"

COPY --chown=enricher:enricher app/ ./app/

USER enricher

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/var/lib/enricher

VOLUME ["/var/lib/enricher"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=3).status==200 else 1)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
