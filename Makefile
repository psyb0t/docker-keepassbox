IMAGE ?= psyb0t/keepassbox:local
DEV_IMAGE ?= keepassbox-dev:local
LOCK_IMAGE := keepassbox-lock:local
DOCS_IMAGE := node:24.21.0-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20
OPENAPI_IMAGE := openapitools/openapi-generator-cli:v7.27.0@sha256:949efd0d5cf3c093ef169887b2ebe0879ee2e8074b6476264232ce4fd8ef46d0
OPENAPI_DOCUMENT := docs/reference/openapi.json
DEV_RUN := docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges $(DEV_IMAGE)
DOCS_RUN := docker run --rm --cap-drop ALL --security-opt no-new-privileges \
	--user "$$(id -u):$$(id -g)" -e HOME=/tmp -e COREPACK_HOME=/work/.corepack \
	-v "$(CURDIR)/website:/work" -w /work

.PHONY: build dev-image pkg-lock lint format test test-unit test-integration sec generate-docs docs-lock docs-audit docs-build help
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

generate-docs: dev-image ## Export and validate the public OpenAPI document
	@mkdir -p .testing
	@set -eu; \
		spec="$$(mktemp "$(CURDIR)/.testing/openapi.XXXXXX.json")"; \
		trap 'rm -f -- "$$spec"' EXIT; \
		$(DEV_RUN) python -c 'import json; from pathlib import Path; from keepassbox.config import Access, Config; from keepassbox.server import create_app; app = create_app(Config(Path("/tmp"), Access.model_construct(clients=[]))); print(json.dumps(app.openapi(), indent=2))' > "$$spec"; \
		docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
			--user "$$(id -u):$$(id -g)" -v "$$spec:/openapi.json:ro" \
			$(OPENAPI_IMAGE) validate -i /openapi.json; \
		chmod 0644 "$$spec"; \
		mv "$$spec" $(OPENAPI_DOCUMENT)

docs-lock: ## Refresh the Docusaurus lockfile
	$(DOCS_RUN) $(DOCS_IMAGE) corepack pnpm install --lockfile-only

docs-audit: ## Scan the locked Docusaurus dependencies
	$(DOCS_RUN) $(DOCS_IMAGE) corepack pnpm audit

docs-build: generate-docs ## Generate the API pages and build the static docs site
	mkdir -p website/.content website/.assets/reference
	cp docs/index.md docs/install.md docs/api.md docs/mcp.md website/.content/
	cp $(OPENAPI_DOCUMENT) website/.assets/reference/openapi.json
	$(DOCS_RUN) $(DOCS_IMAGE) corepack pnpm install --frozen-lockfile
	$(DOCS_RUN) --network none $(DOCS_IMAGE) corepack pnpm run build

help: ## List targets
	@awk 'BEGIN { FS = ":.*## " } /^[a-z-]+:.*## / { printf "%-16s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
