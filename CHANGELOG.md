# Changelog

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
