# KeePassBox

KeePassBox serves KeePass vaults over FastAPI and FastMCP. The service layer owns vault state and access checks. The KDBX adapter owns serialization and engine-specific settings.

Run `make lint`, `make test`, and `make build` before shipping code changes. Tests create synthetic databases.

GitHub Pages deploys the Docusaurus build from `website/build/`. Edit the authored guides in `docs/` and run `make docs-build` to generate the static site under its Pages base path.

Docusaurus generates the REST endpoint pages from `docs/reference/openapi.json`. Edit the FastAPI annotations or operation metadata, then run `make generate-docs` after API or version changes. The tracked JSON also serves the existing OpenAPI download URL.
