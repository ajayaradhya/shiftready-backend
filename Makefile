.PHONY: lint format test test-unit test-integration help

# Dev shortcuts — assumes ruff, mypy installed in active venv (pip install ruff mypy)

lint:
	ruff check . --exclude scripts
	ruff format --check . --exclude scripts
	mypy app/ --ignore-missing-imports --no-strict-optional

format:
	ruff format . --exclude scripts
	ruff check . --fix --exclude scripts

# Unit tests only — no emulator required
test-unit:
	pytest tests/ --ignore=tests/integration -v

# Integration tests — requires Firestore emulator on 127.0.0.1:8089
# Start with: gcloud beta emulators firestore start --host-port=127.0.0.1:8089
test-integration:
	@echo "Ensure Firestore emulator is running: gcloud beta emulators firestore start --host-port=127.0.0.1:8089"
	pytest tests/integration/ -v

# Default: unit tests only
test: test-unit

# Playwright e2e — runs against prod (or E2E_BASE_URL).
# Copy ../shiftready-ui/.env.e2e.example to .env.e2e and fill credentials first.
test-e2e:
	cd ../shiftready-ui && npx playwright test

test-e2e-ui:
	cd ../shiftready-ui && npx playwright test --ui

help:
	@echo "lint              ruff check + format check + mypy"
	@echo "format            auto-fix ruff format + lint violations"
	@echo "test-unit         unit tests (mocked, no emulator)"
	@echo "test-integration  integration tests (Firestore emulator required)"
	@echo "test              alias for test-unit"
	@echo "test-e2e          Playwright e2e against prod (configure ../shiftready-ui/.env.e2e)"
	@echo "test-e2e-ui       Playwright e2e with interactive UI"
