.PHONY: help sync pre-commit pytest test

help:
	cat Makefile

sync-dev:
	uv sync --extra dev

pre-commit:
	uv run pre-commit run --all-files

pytest:
	uv run pytest

test: sync-dev pre-commit pytest
