FROM node:22-bookworm-slim AS remotion-deps

WORKDIR /build/engine/remotion
COPY engine/remotion/package.json engine/remotion/package-lock.json ./
RUN npm ci --no-audit --no-fund


FROM node:22-bookworm-slim AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/app/.venv/bin:$PATH \
    CASE_VIDEO_REPO_ROOT=/app \
    CASE_VIDEO_DATA_ROOT=/data/jobs \
    CASE_VIDEO_OBJECT_STORE_ROOT=/data/objects \
    CASE_VIDEO_WORKER_WORKSPACE_ROOT=/work/stages \
    CASE_VIDEO_RENDER_WORKSPACE_ROOT=/work/renders \
    CASE_VIDEO_RENDER_ENGINE_ROOT=/app/engine/remotion \
    REMOTION_BROWSER_EXECUTABLE=/usr/bin/chromium \
    REMOTION_CONCURRENCY=1 \
    REMOTION_HARDWARE_ACCELERATION=disabled \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    PUPPETEER_SKIP_DOWNLOAD=1 \
    XDG_CACHE_HOME=/tmp/.cache \
    XDG_CONFIG_HOME=/tmp/.config \
    HOME=/tmp

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d -m 0755 /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /tmp/postgresql.asc \
    && gpg --batch --dearmor --output /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg /tmp/postgresql.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        ffmpeg \
        fontconfig \
        fonts-noto-cjk \
        postgresql-client-16 \
        python3 \
        python3-pip \
        python3-venv \
        tini \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -f /tmp/postgresql.asc \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" casevideo \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --home-dir /home/casevideo --shell /usr/sbin/nologin casevideo \
    && python3 -m venv /app/.venv

COPY requirements.txt requirements-server.txt ./
RUN /app/.venv/bin/python -m pip install --upgrade pip \
    && /app/.venv/bin/python -m pip install --no-cache-dir -r requirements.txt -r requirements-server.txt

COPY . /app
COPY --from=remotion-deps /build/engine/remotion/node_modules /app/engine/remotion/node_modules

RUN mkdir -p \
        /data/jobs \
        /data/objects \
        /work/stages \
        /work/renders \
        /tmp/case-video \
    && chown -R casevideo:casevideo /data /work /tmp/case-video \
    && chmod -R a-w /app \
    && chmod -R u+rwX /data /work /tmp/case-video

USER ${APP_UID}:${APP_GID}

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "server.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
