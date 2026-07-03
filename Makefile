.PHONY: up down ingest extract load-graph test seed-demo s3-push s3-pull \
        ocr-up ocr-down ocr-status \
        ingest-docx ingest \
        test-sample test-docx test-pdf test-all \
        pack

# ── App stack ────────────────────────────────────────────────────────
up:
	docker compose up -d --build

down:
	docker compose down

test:
	cd backend && .venv/bin/python -m pytest tests/test_e2e.py -v

seed-demo:
	PYTHONPATH=backend backend/.venv/bin/python scripts/seed_demo.py

extract:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --step extract

load-graph:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --step load

s3-push:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --push-s3

s3-pull:
	PYTHONPATH=backend backend/.venv/bin/python scripts/run_pipeline.py --pull-s3

# ── Docling OCR server ───────────────────────────────────────────────
ocr-up:
	docker compose -f data/docker-compose.yml up -d --build
	@echo "Waiting for Docling to be ready..."
	@until curl -fsS http://localhost:28080/health > /dev/null 2>&1; do sleep 5; printf '.'; done
	@echo "\nDocling ready at http://localhost:28080"

ocr-down:
	docker compose -f data/docker-compose.yml down

ocr-status:
	docker compose -f data/docker-compose.yml ps

# ── Ingestion ────────────────────────────────────────────────────────
ingest-docx:
	python scripts/process_incoming.py --only-docx

ingest:
	python scripts/process_incoming.py

# ── Smoke-тесты ──────────────────────────────────────────────────────
TEST_DIR = data/test_run

test-sample:
	python scripts/prepare_test_sample.py

test-docx:
	python scripts/process_incoming.py --only-docx --source $(TEST_DIR)

test-pdf:
	python scripts/process_incoming.py --only-pdf --source $(TEST_DIR)

test-all: test-docx test-pdf
	python scripts/test_report.py --source $(TEST_DIR)

# ── Export ───────────────────────────────────────────────────────────
PACK_NAME ?= processed_$(shell date +%Y%m%d_%H%M%S).tar.gz

pack:
	tar -czf $(PACK_NAME) data/processed/
	@echo "Archive: $(PACK_NAME)  ($(shell du -sh $(PACK_NAME) | cut -f1))"
