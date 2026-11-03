.PHONY: install lint typecheck test check

install:
	cd listener && npm ci
	cd agent && uv sync

lint:
	cd listener && npm run lint
	cd agent && uv run ruff check . && uv run ruff format --check .

typecheck:
	cd listener && npm run typecheck
	cd agent && uv run mypy

test:
	cd listener && npm test
	cd agent && uv run pytest

check: lint typecheck test
