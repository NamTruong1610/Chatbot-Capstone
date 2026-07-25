# Makefile — command surface from CLAUDE.md. Targets not yet implemented in the current
# phase fail loudly with a pointer to the build plan rather than pretending to work
# (CLAUDE.md rule 2: never silently default).

PYTHON ?= python3
VENV   ?= .venv
BIN     = $(VENV)/bin

.PHONY: help install lint test dev services crawl eval sweep clean

help:
	@echo "install   deps into $(VENV) (editable + dev extras)"
	@echo "lint      ruff + mypy"
	@echo "test      pytest, no network, no services"
	@echo "--- later phases ---"
	@echo "dev services crawl eval sweep   (not yet implemented — see docs/07)"

install:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"
	# Chromium for the Playwright rendering backend (FR-CRAWL-02). If the browser is
	# provisioned externally, skip this and point CHATBOT_CHROMIUM_PATH at the binary.
	$(BIN)/playwright install chromium

lint:
	$(BIN)/ruff check src tests
	$(BIN)/mypy

test:
	$(BIN)/pytest

# --- Later phases: defined so the surface is visible, but not yet built. ---
dev services crawl eval sweep:
	@echo "make $@ is not implemented yet — see docs/07-build-plan.md" && exit 1

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +