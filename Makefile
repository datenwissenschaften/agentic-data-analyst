.PHONY: install data lint format typecheck test check fix run

DATABASE = data/speedruns.duckdb

install:
	uv sync --dev

# The seed is deterministic, so the database is rebuilt only when it is missing.
$(DATABASE):
	uv run python -m agentic_data_analyst.seed $(DATABASE)

data: $(DATABASE)

lint:
	uv run ruff check .

format:
	uv run ruff format --check .

typecheck:
	uv run mypy src tests

test:
	uv run pytest

check: lint format typecheck test

fix:
	uv run ruff check --fix .
	uv run ruff format .

run: $(DATABASE)
	uv run chainlit run app.py
