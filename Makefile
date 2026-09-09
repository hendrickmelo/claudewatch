.PHONY: cleanup format lint test

# Run before every commit. Also what CI runs, so a green cleanup means a green CI.
cleanup: format lint test

format:
	uv run --extra dev ruff format src/ test_*.py

lint:
	uv run --extra dev ruff format --check src/ test_*.py
	uv run --extra dev ruff check src/ test_*.py

test:
	uv run python test_status.py
	uv run python test_codex.py
	uv run python test_settings.py
