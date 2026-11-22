# Changelog

## Unreleased

- Publish the documentation through the shared GitHub Pages workflow.
- Build the GitHub Pages site with Docusaurus. Find the REST walkthrough and generated endpoint pages under one REST API entry.
- Render the searchable REST reference from OpenAPI, with parameter descriptions, copyable curl requests, response examples, and error codes for each endpoint.
- Check in the exported OpenAPI document for GitHub Pages and reject stale exports in CI.

## 0.2.1

- Publish full REST paths with mobile-friendly tables and add bearer auth, response schemas, and error envelopes to OpenAPI.
- Fix the OpenClaw manifest so the bridge can use environment variables without duplicate plugin configuration.
- Read tokens from valid JSON and require explicit selection when multiple clients are configured. Add `keepassbox url` for the configured local port.
- Clarify runtime configuration, MCP examples, credential replacement, and encrypted backup recovery.

Rerun the installer to update the command. Install jq for `keepassbox token`. If the access file has multiple clients, use `--owner` for a unique owner or use the intended client's token directly.

## 0.2.0

- Add an opt-in Tailscale Serve sidecar to the installer for private HTTPS access to REST and MCP.
- Grant all scopes for the client's owner when the access file omits `scopes`. Explicit scope lists still limit access.
- Install the published image through Docker Compose with a generated token and a `keepassbox` command for starting, upgrading, and uninstalling.
- Document every REST operation, show how to call MCP tools, and include full-access and restricted token examples.
- Test every REST operation and MCP tool, all supported cipher and KDF combinations, concurrent writes, and recovery after interrupted saves.
- Match the documentation site's layout to ModemBox and Mailbox.

Rerun the installer to update an existing `keepassbox` command and add the optional Tailscale configuration. The installer preserves your access file and vaults.

## 0.1.1

- Update FastMCP to a release that includes upstream security fixes.

## 0.1.0

- Serve KeePass vaults through REST and Streamable HTTP MCP with scoped client tokens.
- Create, unlock, and rekey KDBX vaults. Set cipher, KDF, memory, iterations, parallelism, and compression.
- Manage groups, entries, protected fields, and small attachments. Generate passwords and TOTP codes.
- Verify encrypted writes before replacing vaults and retain the previous encrypted revision.
