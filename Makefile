SHELL := /bin/bash

# Joined with the *interpreter's* os.pathsep (":" on POSIX, ";" on Windows) rather than
# a hardcoded separator, so this Makefile works unmodified on Linux/macOS dev machines
# and on native Windows Python (this repo was built and locally run on the latter).
PY_PATH_DIRS := packages packages/policy-sdk packages/tool-sdk services services/mission-engine services/agent-runtime services/model-gateway services/event-service services/artifact-service
export PYTHONPATH := $(shell python -c "import os,sys; print(os.pathsep.join(sys.argv[1:]))" $(PY_PATH_DIRS))

# Exactly the modules spec §27 names for the ">=80% coverage, core domain logic"
# target: permission evaluator, budget evaluator, state transitions, event builder,
# runtime adapter, model gateway, output validator. Deliberately excludes API routes,
# the worker loop, and DB/object-store-backed code — those need the integration suite
# (a real Postgres/Redis/MinIO) to exercise meaningfully, not more unit tests.
# Mix of directory paths and dotted module names — pytest-cov silently ignores a bare
# `path/to/file.py` passed to --cov (no error, no data), so a single-file target must
# be given as a dotted module name instead (resolvable because pyproject.toml's
# `pythonpath` already puts "packages" and each service root on sys.path).
CORE_DOMAIN_MODULES := packages/policy-sdk/policy_sdk contracts.events contracts.output_contract services/mission-engine/mission_engine/states services/agent-runtime/agent_runtime/adapters model_gateway.gateway services/model-gateway/model_gateway/routing

.PHONY: up down logs migrate seed demo test test-unit test-coverage-core test-integration test-e2e test-resilience test-security api worker admin-web install

install:
	pip install -r requirements.txt
	cd apps/admin-web && npm install

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	alembic upgrade head

seed:
	python infrastructure/scripts/seed.py

demo:
	python infrastructure/scripts/run_demo_mission.py

api:
	uvicorn api.app.main:app --app-dir services --reload --port 8000

worker:
	python -m worker.main

admin-web:
	cd apps/admin-web && npm run dev

test: test-unit

test-unit:
	pytest -m unit -v --cov --cov-report=term-missing

test-coverage-core:
	pytest -m unit -v $(foreach m,$(CORE_DOMAIN_MODULES),--cov=$(m)) --cov-report=term-missing --cov-fail-under=80

test-integration:
	pytest -m integration -v

test-e2e:
	pytest -m e2e -v

test-resilience:
	pytest -m resilience -v -s

test-security:
	pytest -m security -v
