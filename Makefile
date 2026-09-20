.PHONY: install data format lint typecheck test check api mcp

install:
	poetry install --extras dev

data:
	poetry run agentic-data-generate --output data/sample

format:
	poetry run ruff check --fix .
	poetry run ruff format .

lint:
	poetry run ruff check .
	poetry run ruff format --check .

typecheck:
	poetry run mypy

test:
	poetry run pytest

check: format lint typecheck test

api:
	poetry run uvicorn agentic_data_analyst.api.app:app --reload

mcp:
	poetry run agentic-data-mcp
