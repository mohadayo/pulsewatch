.PHONY: test test-python test-go test-ts lint up down build clean

## Run all tests
test: test-python test-go test-ts

## Run Python tests
test-python:
	cd services/analytics && pip install -q -r requirements.txt && pytest -v

## Run Go tests
test-go:
	cd services/checker && go test -v ./...

## Run TypeScript tests
test-ts:
	cd services/gateway && npm install --silent && npm test

## Run all linters
lint: lint-python lint-go lint-ts

## Lint Python
lint-python:
	cd services/analytics && pip install -q -r requirements.txt && flake8 --max-line-length=120 app.py

## Lint Go
lint-go:
	cd services/checker && go vet ./...

## Lint TypeScript
lint-ts:
	cd services/gateway && npm install --silent && npx eslint src/ --ext .ts

## Start all services with Docker Compose
up:
	docker compose up --build -d

## Stop all services
down:
	docker compose down

## Build all Docker images
build:
	docker compose build

## Remove all containers, images, and volumes
clean:
	docker compose down --rmi all --volumes --remove-orphans
