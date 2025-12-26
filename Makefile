.PHONY: help

help:
	cat Makefile


.PHONY: dev
dev:
	uv sync --extra dev

.PHONY: pre-commit
pre-commit:
	uv run python -m pre_commit run --all-files
