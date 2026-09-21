.PHONY: install install-examples data format lint typecheck test check api mcp notebooks

install:
	poetry install --extras dev

install-examples:
	poetry install --extras "dev examples"

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

# Executes examples/agentic_analytics_workflow.ipynb top to bottom, regenerating its
# outputs and every PNG under docs/assets/agentic-workflow/ from the notebook's own
# Plotly figures. Fails the command if any cell raises. Requires `make install-examples`
# and a real OPENROUTER_API_KEY in .env: this notebook calls OpenRouterClient directly,
# not a fixture, so its exact plan/wording can vary between runs.
notebooks:
	poetry run jupyter nbconvert --to notebook --execute --inplace examples/agentic_analytics_workflow.ipynb
