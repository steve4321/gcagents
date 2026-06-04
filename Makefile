.PHONY: help install dev test lint format typecheck clean run-scheduler dashboard e2e ci-fix

help:
	@echo "GCAgents — make targets"
	@echo "  make install      Install package in dev mode"
	@echo "  make test         Run pytest"
	@echo "  make lint         Ruff lint"
	@echo "  make format       Ruff auto-format"
	@echo "  make typecheck    Mypy strict"
	@echo "  make ci-fix       Run lint + format + typecheck + test"
	@echo "  make run-scheduler   Start the tick scheduler"
	@echo "  make dashboard       Start the dashboard on :8080"
	@echo "  make e2e          Run end-to-end script"
	@echo "  make clean        Remove build artefacts and caches"

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy orchestrator shared agents dashboard

ci-fix: format lint
	make test

run-scheduler:
	python -m orchestrator.main run-scheduler

dashboard:
	python -m dashboard.web.api_server

e2e:
	python scripts/e2e_test.py

bootstrap:
	python scripts/bootstrap.py

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage **/__pycache__
	find . -name "*.pyc" -delete
