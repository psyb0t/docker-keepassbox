# Docs build

Run `make docs-build` from the repository root. It exports OpenAPI from FastAPI, builds the REST pages with Docusaurus, and writes the static site to `website/build/`. Edit the guides in `docs/`. Keep examples and endpoint descriptions in the FastAPI schema.

The Documentation workflow calls the shared GitHub Pages workflow with the checked-in OpenAPI path. The same `make docs-build` target exports the schema and builds the site. GitHub Pages uses GitHub Actions as its publishing source.

Run `make docs-audit` to check the locked dependencies. Postman's build-time dependency on Faker 5.5.3 still reports [GHSA-qxc2-j82w-r537](https://github.com/advisories/GHSA-qxc2-j82w-r537). Postman's collection library uses Faker 5 APIs and cannot take the patched major version unchanged. Docs generation runs without network access against the repository's own OpenAPI export. The public endpoint pages show fixed curl examples and have no request editor.
