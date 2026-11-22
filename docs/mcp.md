---
title: MCP
description: Connect Codex, Claude Code, OpenClaw, or another MCP client to KeePassBox with Streamable HTTP and a scoped bearer token.
nav_order: 4
---

# MCP

Use the base URL from `keepassbox url` for a local instance or the HTTPS URL for a remote instance. Append `/mcp` for a Streamable HTTP client. Use the bearer token from `keepassbox token` on a default install. For custom clients, use the token assigned in the [access file](install.md#access-file-example).

## Connect a client

For Codex, export the token before starting Codex:

```bash
export KEEPASSBOX_TOKEN="${KEEPASSBOX_TOKEN:-$(keepassbox token)}"
```

Add the server to `~/.codex/config.toml`. Replace the URL if you chose a different port or use remote HTTPS:

```toml
[mcp_servers.keepassbox]
url = "http://localhost:8000/mcp"
bearer_token_env_var = "KEEPASSBOX_TOKEN"
```

For Claude Code and Codex, the [psyb0t agents marketplace](https://github.com/psyb0t/agents) lists the KeePassBox plugin. For OpenClaw, install the [plugin and skill](https://github.com/psyb0t/docker-keepassbox#agent-integrations). Set `KEEPASSBOX_URL` to the instance's base URL, such as `http://localhost:8000`, and set `KEEPASSBOX_TOKEN` in the plugin process environment. The bridge appends `/mcp`.

## Call a tool

Call `tools/list` to see the tool names and inputs. Tools mirror the [REST operations](api.md). When REST takes a JSON body, pass those fields under `body` in the MCP tool.

Use `reveal_entry_field` with `vault`, `entry`, and `field: "password"` to read an entry's password, or `generate_entry_totp` with `vault` and `entry` to get a code. The installer token can call both tools.

List vaults as your token's owner from Bash. If you manage Docker yourself or use a remote instance, set `KEEPASSBOX_URL` and `KEEPASSBOX_TOKEN` before running this example.

```bash
base="${KEEPASSBOX_URL:-$(keepassbox url)}"
token="${KEEPASSBOX_TOKEN:-$(keepassbox token)}"
curl -fsS "${base%/}/mcp" \
  --header @<(printf 'Authorization: Bearer %s\n' "$token") \
  --header 'Accept: application/json, text/event-stream' \
  --json '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "list_vaults",
      "arguments": {"limit": 10, "offset": 0}
    }
  }'
```

For an event-stream response, read the JSON on the `data:` line. A successful list returns `items` and `total` under `result.structuredContent`. Missing or rejected bearer tokens return HTTP 401. A tool can return `result.isError: true` in an HTTP 200 response.

To create an entry, replace `VAULT_ID_FROM_LIST` with an unlocked vault's ID from that response. If the list is empty, create one with the [REST walkthrough](api.md#try-it-with-curl).

```json
{
  "vault": "VAULT_ID_FROM_LIST",
  "body": {
    "title": "Demo account",
    "username": "demo@example.invalid"
  }
}
```

Use a native or server-side client. The server rejects requests carrying an `Origin` header and applies the [REST request body limit](api.md#endpoint-reference) to MCP. The MCP Registry entry helps clients discover KeePassBox. A self-hosted instance still needs the [installation and access configuration](install.md).
