FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system mini && adduser --system --ingroup mini mini

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --upgrade pip && \
    python -m pip install .

RUN mkdir -p /data && chown -R mini:mini /app /data
USER mini

EXPOSE 8000

CMD ["sh", "-c", "uvicorn miniai.app:app --host 0.0.0.0 --port ${PORT:-8000}"]

