---
title: MCP
description: Connect Codex, Claude Code, OpenClaw, or another MCP client to KeePassBox with Streamable HTTP and a scoped bearer token.
nav_order: 4
---

# MCP

Point your client at `http://localhost:8000/mcp` with the bearer token from `keepassbox token`. It grants full access to the installer's owner, including password retrieval and TOTP. For custom tokens, see [access settings](api.md#access). Use HTTPS for a remote instance.

## Connect a client

For Codex, export the token before starting Codex:

```bash
export KEEPASSBOX_TOKEN="$(keepassbox token)"
```

Add the server to your Codex configuration:

```toml
[mcp_servers.keepassbox]
url = "http://localhost:8000/mcp"
bearer_token_env_var = "KEEPASSBOX_TOKEN"
```

For Claude Code and Codex, the [psyb0t agents marketplace](https://github.com/psyb0t/agents) lists the KeePassBox plugin. For OpenClaw, install the [plugin and skill](https://github.com/psyb0t/docker-keepassbox#agent-integrations). Set `KEEPASSBOX_URL` to the instance's base URL, such as `http://localhost:8000`, and set `KEEPASSBOX_TOKEN` in the plugin process environment. The bridge appends `/mcp`.

## Call a tool

Call `tools/list` to see the tool names and inputs. Tools mirror the [REST operations](api.md). When REST takes a JSON body, pass those fields under `body` in the MCP tool.

Use `reveal_entry_field` with `vault`, `entry`, and `field: "password"` to read an entry's password, or `generate_entry_totp` with `vault` and `entry` to get a code. The installer token can call both tools.

List vaults as your token's owner from Bash:

```bash
token=$(keepassbox token)
curl -fsS http://127.0.0.1:8000/mcp \
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

The result contains `items` and `total` under `result.structuredContent`. An empty list means the owner has no vaults. To create an entry, call `create_entry` with arguments such as these. The vault must exist and be unlocked.

```json
{
  "vault": "demo",
  "body": {
    "title": "Demo account",
    "username": "demo@example.invalid"
  }
}
```
