.PHONY: install lint type test run-api run-daemon

install:
	python -m venv .venv
	.venv/bin/pip install -e ".[dev]"

lint:
	ruff check packages apps tests

type:
	mypy packages apps --ignore-missing-imports

test:
	pytest tests/ -v

run-api:
	uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8080

run-daemon:
	python -m apps.daemon.main
