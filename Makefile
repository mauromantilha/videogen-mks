PY ?= .venv/bin/python
BIN := $(dir $(PY))

.PHONY: install hooks lint format types imports limits test cov check run

install:            ## instala o projeto + ferramentas de dev
	$(PY) -m pip install -e ".[dev]"

hooks:              ## ativa os hooks de pre-commit
	$(BIN)pre-commit install

lint:               ## ruff (regras + formatação)
	$(BIN)ruff check .
	$(BIN)ruff format --check .

format:             ## aplica formatação
	$(BIN)ruff check --fix .
	$(BIN)ruff format .

types:              ## mypy --strict
	$(BIN)mypy

imports:            ## contratos de camadas (import-linter)
	$(BIN)lint-imports

limits:             ## guardião das 300 linhas (RNF-05)
	$(PY) scripts/check_limits.py

test:
	$(BIN)pytest

cov:
	$(BIN)pytest --cov --cov-report=term-missing

check: lint types imports limits test   ## o mesmo que o CI

run:
	$(BIN)uvicorn videogen.main:app --reload --workers 1
