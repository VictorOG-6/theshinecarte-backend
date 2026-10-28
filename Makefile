 .DEFAULT_GOAL := help

# Configuration
IMAGE_NAME ?= expense-tracker-api
TAG ?= latest
REGISTRY ?= myregistry
COMPOSE_FILE ?= docker-compose.yml
ENV_FILE ?= .env

# Detect OS
ifeq ($(OS),Windows_NT)
	SHELL := cmd.exe
	RM := del /f /q
	MKDIR := mkdir
	DETECTED_OS := Windows
else
	SHELL := /bin/bash
	RM := rm -f
	MKDIR := mkdir -p
	DETECTED_OS := $(shell uname -s)
endif

.PHONY: help
help: ## Show this help message
	@echo Usage: make [target]
	@echo.
	@echo Available targets:
	@echo   help           Show this help message
	@echo   check-env      Check if .env file exists
	@echo   build          Build Docker image for production
	@echo   build-dev      Build Docker image for development
	@echo   up             Start all services
	@echo   down           Stop all services
	@echo   logs           View logs from all services
	@echo   logs-app       View logs from app service only
	@echo   restart        Restart all services
	@echo   clean          Remove all containers and volumes
	@echo   test           Run tests in Docker container
	@echo   shell          Open shell in app container
	@echo   db-migrate     Run database migrations
	@echo   db-rollback    Rollback last migration
	@echo   create-admin   Create initial admin user
	@echo   lint           Run linting
	@echo   format         Format code
	@echo   tag            Tag image for registry
	@echo   push           Push image to registry
	@echo   deploy         Build and deploy image
	@echo   health         Check health of all services

.PHONY: check-env
check-env: ## Check if .env file exists
ifeq ($(OS),Windows_NT)
	@if not exist $(ENV_FILE) ( \
		echo Error: $(ENV_FILE) file not found && \
		echo Please create $(ENV_FILE) from .env.example && \
		exit /b 1 \
	)
else
	@test -f $(ENV_FILE) || \
		(echo "Error: $(ENV_FILE) file not found" && \
		echo "Please create $(ENV_FILE) from .env.example" && \
		exit 1)
endif

.PHONY: build
build: check-env ## Build Docker image for production
	@echo Building production image...
	docker build --target production --tag $(IMAGE_NAME):$(TAG) --tag $(IMAGE_NAME):latest -f Dockerfile .
	@echo Build complete!

.PHONY: build-dev
build-dev: check-env ## Build Docker image for development
	@echo Building development image...
	docker build --target development --tag $(IMAGE_NAME):dev -f Dockerfile .
	@echo Development build complete!

.PHONY: build-no-cache
build-no-cache: check-env ## Build without cache
	@echo Building without cache...
	docker build --no-cache --target production --tag $(IMAGE_NAME):$(TAG) --tag $(IMAGE_NAME):latest -f Dockerfile .
	@echo Build complete!

.PHONY: up
up: check-env ## Start all services
	@echo Starting services...
	docker compose -f $(COMPOSE_FILE) up -d
	@echo Services started!
	@echo API available at http://localhost:8000
	@echo Docs available at http://localhost:8000/docs

.PHONY: up-build
up-build: check-env ## Start services and rebuild
	@echo Starting services with rebuild...
	docker compose -f $(COMPOSE_FILE) up -d --build
	@echo Services started!

.PHONY: up-watch
up-watch: check-env ## Start services in foreground with logs
	@echo Starting services with logs...
	docker compose -f $(COMPOSE_FILE) up

.PHONY: dev
dev: check-env ## Start development server locally (outside Docker)
	@echo Starting development server...
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

.PHONY: dev-debug
dev-debug: check-env ## Start development server with debug logging
	@echo Starting development server with debug mode...
	uvicorn main:app --reload --host 0.0.0.0 --port 8000 --log-level debug

.PHONY: prod-local
prod-local: check-env ## Run production server locally (outside Docker)
	@echo Starting production server...
	uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

.PHONY: down
down: ## Stop all services
	@echo Stopping services...
	docker compose -f $(COMPOSE_FILE) down
	@echo Services stopped!

.PHONY: db-only
db-only: check-env ## Start only database services (PostgreSQL + Redis)
	@echo Starting database services only...
	docker compose -f $(COMPOSE_FILE) up -d postgres redis
	@echo Database services started!
	@echo PostgreSQL: localhost:5432
	@echo Redis: localhost:6379

.PHONY: logs
logs: ## View logs from all services
	docker compose -f $(COMPOSE_FILE) logs -f

.PHONY: logs-app
logs-app: ## View logs from app service only
	docker compose -f $(COMPOSE_FILE) logs -f app

.PHONY: ps
ps: ## Show running containers
	docker compose -f $(COMPOSE_FILE) ps

.PHONY: restart
restart: down up ## Restart all services

.PHONY: restart-app
restart-app: ## Restart only app service
	@echo Restarting app service...
	docker compose -f $(COMPOSE_FILE) restart app
	@echo App restarted!

.PHONY: clean
clean: ## Remove all containers and volumes
	@echo Cleaning up...
	docker compose -f $(COMPOSE_FILE) down -v --remove-orphans
	@echo Cleanup complete!

.PHONY: clean-images
clean-images: clean ## Remove containers, volumes, and images
	@echo Removing images...
	-docker rmi $(IMAGE_NAME):$(TAG) 2>nul || echo Image not found
	-docker rmi $(IMAGE_NAME):latest 2>nul || echo Image not found
	-docker rmi $(IMAGE_NAME):dev 2>nul || echo Image not found
	@echo Images removed!

.PHONY: prune
prune: ## Prune Docker system
	@echo Pruning Docker system...
	docker system prune -f
	@echo Prune complete!

.PHONY: test
test: ## Run tests in Docker container
	@echo Running tests...
	docker compose -f $(COMPOSE_FILE) exec app pytest -v

.PHONY: test-cov
test-cov: ## Run tests with coverage
	@echo Running tests with coverage...
	docker compose -f $(COMPOSE_FILE) exec app pytest --cov=app --cov-report=html --cov-report=term

.PHONY: shell
shell: ## Open shell in app container
	docker compose -f $(COMPOSE_FILE) exec app /bin/bash

.PHONY: shell-db
shell-db: ## Open PostgreSQL shell
	docker compose -f $(COMPOSE_FILE) exec postgres psql -U expense_user -d expense_tracker

.PHONY: shell-redis
shell-redis: ## Open Redis CLI
	docker compose -f $(COMPOSE_FILE) exec redis redis-cli

.PHONY: db-migrate
db-migrate: ## Run database migrations
	@echo Running migrations...
	docker compose -f $(COMPOSE_FILE) exec app alembic upgrade head
	@echo Migrations complete!

.PHONY: db-rollback
db-rollback: ## Rollback last migration
	@echo Rolling back migration...
	docker compose -f $(COMPOSE_FILE) exec app alembic downgrade -1
	@echo Rollback complete!

.PHONY: db-revision
db-revision: ## Create new migration (use MESSAGE=your_message)
	@echo Creating new migration...
	docker compose -f $(COMPOSE_FILE) exec app alembic revision --autogenerate -m "$(MESSAGE)"
	@echo Migration created!

.PHONY: db-history
db-history: ## Show migration history
	docker compose -f $(COMPOSE_FILE) exec app alembic history

.PHONY: db-current
db-current: ## Show current migration version
	docker compose -f $(COMPOSE_FILE) exec app alembic current

.PHONY: create-admin
create-admin: check-env db-migrate ## Create initial admin user
	@echo Creating admin user...
	docker compose -f $(COMPOSE_FILE) exec app python scripts/create_admin.py
	@echo Admin creation complete!

.PHONY: lint
lint: ## Run linting
	@echo Running linters...
	docker compose -f $(COMPOSE_FILE) exec app ruff check .
	docker compose -f $(COMPOSE_FILE) exec app black --check .

.PHONY: lint-local
lint-local: ## Run linting
	@echo Running linters...
	black .
	ruff check --fix .

.PHONY: format
format: ## Format code
	@echo Formatting code...
	docker compose -f $(COMPOSE_FILE) exec app black .
	docker compose -f $(COMPOSE_FILE) exec app ruff check --fix .
	@echo Formatting complete!

.PHONY: type-check
type-check: ## Run type checking
	@echo Running type checker...
	docker compose -f $(COMPOSE_FILE) exec app mypy app

.PHONY: tag
tag: ## Tag image for registry
	@echo Tagging image...
	docker tag $(IMAGE_NAME):$(TAG) $(REGISTRY)/$(IMAGE_NAME):$(TAG)
	docker tag $(IMAGE_NAME):$(TAG) $(REGISTRY)/$(IMAGE_NAME):latest
	@echo Tagged: $(REGISTRY)/$(IMAGE_NAME):$(TAG)

.PHONY: push
push: tag ## Push image to registry
	@echo Pushing to registry...
	docker push $(REGISTRY)/$(IMAGE_NAME):$(TAG)
	docker push $(REGISTRY)/$(IMAGE_NAME):latest
	@echo Push complete!

.PHONY: deploy
deploy: build push ## Build and deploy image
	@echo Deployment complete!

.PHONY: health
health: ## Check health of all services
	@echo Checking service health...
	@docker compose -f $(COMPOSE_FILE) ps
	@echo.
	@echo Checking API health endpoint...
ifeq ($(OS),Windows_NT)
	@curl -f http://localhost:8000/health || echo API health check failed
else
	@curl -f http://localhost:8000/health || (echo "API health check failed" && exit 1)
endif
	@echo.
	@echo Health check complete!

.PHONY: init
init: ## Initialize project (copy .env.example to .env)
ifeq ($(OS),Windows_NT)
	@if not exist .env copy .env.example .env
	@echo .env file created from .env.example
	@echo Please update .env with your configuration
else
	@if [ ! -f .env ]; then cp .env.example .env; fi
	@echo ".env file created from .env.example"
	@echo "Please update .env with your configuration"
endif

.PHONY: setup
setup: init build up db-migrate ## Complete project setup
	@echo Project setup complete!
	@echo Application should be running at http://localhost:8000

.PHONY: backup-db
backup-db: ## Backup database
	@echo Creating database backup...
	docker compose -f $(COMPOSE_FILE) exec -T postgres pg_dump -U expense_user expense_tracker > backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo Backup created!

.PHONY: restore-db
restore-db: ## Restore database from backup (use BACKUP_FILE=filename)
	@echo Restoring database from $(BACKUP_FILE)...
	docker compose -f $(COMPOSE_FILE) exec -T postgres psql -U expense_user expense_tracker < $(BACKUP_FILE)
	@echo Database restored!

.PHONY: info
info: ## Show project information
	@echo Project: $(IMAGE_NAME)
	@echo Tag: $(TAG)
	@echo Registry: $(REGISTRY)
	@echo OS: $(DETECTED_OS)
	@echo Docker Compose File: $(COMPOSE_FILE)