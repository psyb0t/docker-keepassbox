---
title: MCP
description: Connect Codex, Claude Code, OpenClaw, or another MCP client to KeePassBox with Streamable HTTP and a scoped bearer token.
nav_order: 4
---

# MCP

Point your client at `http://localhost:8000/mcp` with the bearer token from `keepassbox token`. Use a token for the vault owner and scopes you want that client to have. Use HTTPS for a remote instance.

For Codex, load the bearer token from your environment:

```toml
[mcp_servers.keepassbox]
url = "http://localhost:8000/mcp"
bearer_token_env_var = "KEEPASSBOX_TOKEN"
```

For Claude Code and Codex, the [psyb0t agents marketplace](https://github.com/psyb0t/agents) lists the KeePassBox plugin. For OpenClaw, install the [plugin and skill](https://github.com/psyb0t/docker-keepassbox#agent-integrations). The OpenClaw bridge reads the base URL and token from its environment.

Call `tools/list` to see the tool names and inputs. Tools mirror the [REST operations](api.md). When REST takes a JSON body, pass those fields under `body` in the MCP tool.
