FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY app.py chainlit.md ./
COPY .chainlit ./.chainlit
RUN uv sync --locked --no-dev

# The app only reads the database, so it is built at image build time and the runtime user cannot change it.
RUN uv run python -m agentic_data_analyst.seed data/speedruns.duckdb \
    && useradd --create-home --uid 10001 analyst \
    && install --directory --owner=analyst /app/logs /app/.files
USER analyst

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "chainlit", "run", "app.py", "--headless", "--host", "0.0.0.0", "--port", "8000"]
