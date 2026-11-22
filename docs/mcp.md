---
title: MCP
---

# MCP

Use Streamable HTTP at `http://localhost:8000/mcp` with the instance's bearer token. The token determines owner and scopes. Use HTTPS for a remote instance.

For Codex, load the bearer token from your environment:

```toml
[mcp_servers.keepassbox]
url = "http://localhost:8000/mcp"
bearer_token_env_var = "KEEPASSBOX_TOKEN"
```

For OpenClaw, use the [plugin and skill](https://github.com/psyb0t/docker-keepassbox#agent-integrations). The plugin reads the base URL and token from its environment. A direct MCP client can discover tools with `tools/list`. Tool input schemas match the [REST operations](api.md). Where an operation takes a request body, the MCP tool accepts its fields under `body`.
