.PHONY: setup test test-unit test-integration lint format typecheck run-server clean

setup:
	uv sync --extra server --extra cli --group dev

test: test-unit test-integration

test-unit:
	uv run pytest tests/unit -v

test-integration:
	uv run pytest tests/integration -v

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy src/

run-server:
	uv run resync serve --transport stdio

run-server-http:
	uv run resync serve --transport http --port 8787

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis dist build *.egg-info
