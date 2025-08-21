.PHONY: help lint format typecheck test run-paper clean install fetch

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies
	pip install -r requirements.txt

lint: ## Run ruff linter
	ruff check .

format: ## Format code with black
	black .

typecheck: ## Run mypy type checker
	mypy bot/

test: ## Run tests with pytest
	pytest -q tests/

run-paper: ## Run the bot in paper trading mode
	source venv/bin/activate && python -m bot.runner.pipeline --config configs/paper.yaml --profile paper

fetch: ## Fetch data from configured sources
	python -m scripts.fetch_only --config configs/fetch.yaml --profile prod

clean: ## Clean up build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
