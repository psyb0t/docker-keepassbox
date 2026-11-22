# KeePassBox

KeePassBox serves KeePass vaults over FastAPI and FastMCP. The service layer owns vault state and access checks. The KDBX adapter owns serialization and engine-specific settings.

Run `make lint`, `make test`, and `make build` before shipping code changes. Tests create synthetic databases.

GitHub Pages publishes `docs/`. Keep the front matter on each page, use relative Markdown links within the site, and run `make docs-build` after editing it.

The REST reference reads `docs/reference/openapi.json`. Edit the FastAPI annotations or operation metadata, then run `make generate-docs` after API or version changes.
