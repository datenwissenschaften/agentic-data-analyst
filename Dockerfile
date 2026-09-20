FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_CATALOG_PATH=/app/data/sample \
    SPARK_MASTER=local[2]

RUN apt-get update \
    && apt-get install --yes --no-install-recommends openjdk-21-jre-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install . \
    && useradd --create-home --uid 10001 analyst \
    && mkdir -p /app/data/sample \
    && agentic-data-generate --output /app/data/sample \
    && chown -R analyst:analyst /app

USER analyst
EXPOSE 8000

CMD ["uvicorn", "agentic_data_analyst.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
