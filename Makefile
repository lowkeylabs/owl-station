.PHONY: help

help:
	cat Makefile


.PHONY: dev
dev:
	uv sync --extra dev

.PHONY: sync pre-commit pytest test
sync:
	uv sync --extra dev

pre-commit:
	uv run pre-commit run --all-files

pytest:
	uv run pytest

test: sync pre-commit pytest
