FROM ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 AS uv
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src PATH=/app/.venv/bin:$PATH
RUN groupadd --gid 10001 keepassbox && useradd --uid 10001 --gid keepassbox --no-create-home keepassbox && install -d -m 0700 -o keepassbox -g keepassbox /data

FROM base AS tooling
COPY --from=uv /uv /usr/local/bin/uv

FROM tooling AS deps
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-build --no-cache

FROM deps AS dev
RUN uv sync --locked --no-install-project --no-build --no-cache
COPY src/ ./src/
COPY tests/ ./tests/
USER 10001:10001

FROM base AS runtime
LABEL io.modelcontextprotocol.server.name="io.github.psyb0t/keepassbox"
COPY --from=deps /app/.venv /app/.venv
COPY pyproject.toml ./
COPY src/ ./src/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=3s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).close()"]
ENTRYPOINT ["python", "-m", "keepassbox"]
