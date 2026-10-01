FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && \
    apt-get install --yes --no-install-recommends gosu && \
    rm -rf /var/lib/apt/lists/* && \
    addgroup --system mini && \
    adduser --system --ingroup mini mini

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN python -m pip install --upgrade pip && \
    python -m pip install .

RUN mkdir -p /data && \
    chown -R mini:mini /app /data && \
    chmod 0755 /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["sh", "-c", "uvicorn miniai.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
