# OSM Meet Your Mappers - Docker Compose Management

.PHONY: help production dev initialization up-prod up-dev up-init down clean logs logs-prod logs-dev status

# Default target
help:
	@echo "Available commands:"
	@echo "  make production     - Start services with production profile"
	@echo "  make dev           - Start services with development profile"
	@echo "  make initialization - Start services with initialization profile"
	@echo "  make up-prod       - Start production services in background"
	@echo "  make up-dev        - Start development services in background"
	@echo "  make up-init       - Start initialization services in background"
	@echo "  make down          - Stop and remove all containers"
	@echo "  make clean         - Stop containers and remove volumes"
	@echo "  make logs          - Show logs for all services"
	@echo "  make logs-prod     - Show logs for production services"
	@echo "  make logs-dev      - Show logs for development services"
	@echo "  make status        - Show container status"

# Production profile
production:
	docker compose --profile production up

up-prod:
	docker compose --profile production up -d

# Development profile
dev:
	docker compose --profile dev up

up-dev:
	docker compose --profile dev up -d

# Initialization profile
initialization:
	docker compose --profile initialization up

up-init:
	docker compose --profile initialization up -d

# Management commands
down:
	docker compose down

clean:
	docker compose down -v

# Logging
logs:
	docker compose logs -f

logs-prod:
	docker compose --profile production logs -f

logs-dev:
	docker compose --profile dev logs -f

# Status
status:
	docker compose ps