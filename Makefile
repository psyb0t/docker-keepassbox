IMAGE ?= psyb0t/keepassbox:local
DEV_IMAGE ?= keepassbox-dev:local
LOCK_IMAGE := keepassbox-lock:local
DOCS_IMAGE := ghcr.io/actions/jekyll-build-pages:v1.0.13@sha256:6791ebfd912185ed59bfb5fb102664fa872496b79f87ff8b9cfba292a7345041
DEV_RUN := docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges $(DEV_IMAGE)

.PHONY: build dev-image pkg-lock lint format test test-unit test-integration sec docs-build help
build: ## Build the release image
	docker build --target runtime -t $(IMAGE) .

dev-image: ## Build the development image
	docker build --target dev -t $(DEV_IMAGE) .

pkg-lock: ## Resolve or refresh the locked Python dependencies
	docker build --target tooling -t $(LOCK_IMAGE) .
	docker run --rm --user "$$(id -u):$$(id -g)" -e UV_CACHE_DIR=/tmp/uv -v "$(CURDIR):/app" -w /app --entrypoint uv $(LOCK_IMAGE) lock

lint: dev-image ## Check Bash syntax, Python formatting and lint
	bash -n install.sh
	$(DEV_RUN) ruff check --no-cache src tests
	$(DEV_RUN) ruff format --check --no-cache src tests

format: ## Format source and tests through the dev image
	docker run --rm --network none --user "$$(id -u):$$(id -g)" -v "$(CURDIR):/work" -w /work $(DEV_IMAGE) ruff format --no-cache src tests

test: test-unit test-integration ## Run both test suites

test-unit: dev-image ## Run vault format and policy tests
	$(DEV_RUN) pytest -q -p no:cacheprovider tests/test_engine.py

test-integration: dev-image ## Exercise REST and MCP against real KDBX files
	$(DEV_RUN) pytest -q -p no:cacheprovider tests/test_service.py

sec: dev-image ## Gate on source security findings and write SARIF
	$(DEV_RUN) ruff check --no-cache --select S --output-format sarif src > sec.sarif

docs-build: ## Build GitHub Pages locally
	docker run --rm --user "$$(id -u):$$(id -g)" -e HOME=/tmp \
		-e GITHUB_WORKSPACE=/work -e GITHUB_REPOSITORY=psyb0t/docker-keepassbox \
		-e INPUT_SOURCE=docs -e INPUT_DESTINATION=.testing/docs-site -e INPUT_VERBOSE=false \
		-v "$(CURDIR):/work" $(DOCS_IMAGE)

help: ## List targets
	@awk 'BEGIN { FS = ":.*## " } /^[a-z-]+:.*## / { printf "%-16s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
