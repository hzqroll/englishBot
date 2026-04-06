FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends sqlite3 fonts-noto-cjk && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
COPY deploy/config.example.yaml ./config.yaml

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

EXPOSE 8080

CMD ["python", "-m", "src.main"]
