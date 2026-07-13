.PHONY: install lint type test scan

install:
	python -m venv .venv
	.venv/bin/pip install -e ".[dev]"

lint:
	.venv/bin/ruff check src tests

type:
	.venv/bin/mypy src

test:
	.venv/bin/pytest

scan:
	.venv/bin/spectre --all
