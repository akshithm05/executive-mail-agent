# Developer workflow shortcuts.
.PHONY: help install lint format typecheck test migrate revision up down logs

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Install dev dependencies
	pip install -r requirements-dev.txt

lint: ## Run Ruff lint checks
	ruff check app tests

format: ## Auto-format with Ruff
	ruff format app tests

typecheck: ## Run mypy
	mypy app

test: ## Run the test suite
	pytest

migrate: ## Apply migrations to the latest revision
	alembic upgrade head

revision: ## Autogenerate a migration (msg="...")
	alembic revision --autogenerate -m "$(msg)"

up: ## Start the local stack
	docker compose -f ../infra/docker-compose.yml up --build

down: ## Stop the local stack
	docker compose -f ../infra/docker-compose.yml down

logs: ## Tail application logs
	docker compose -f ../infra/docker-compose.yml logs -f api
