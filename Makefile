.PHONY: setup test test-unit test-integration lint format typecheck verify run-server run-server-http clean

setup:
	uv sync --extra server --extra cli --group dev --group verify

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

verify:
	uv run python tools/verify_install.py

run-server:
	uv run resync serve --transport stdio

run-server-http:
	uv run resync serve --transport http --port 8787

installer:
	gcc -O2 -static -Wall tools/installer.c -o installer/install.exe

clean:
	uv run python tools/clean.py
