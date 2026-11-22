# KeePassBox

[![CI](https://github.com/psyb0t/docker-keepassbox/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/psyb0t/docker-keepassbox/actions/workflows/pipeline.yml)
[![version](https://raw.githubusercontent.com/psyb0t/docker-keepassbox/badges/version.svg)](https://github.com/psyb0t/docker-keepassbox/releases)
[![license](https://raw.githubusercontent.com/psyb0t/docker-keepassbox/badges/license.svg)](LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/psyb0t/keepassbox?style=flat-square)](https://hub.docker.com/r/psyb0t/keepassbox)

Self-hosted REST API and MCP server for KeePass. Create a vault, manage entries, and generate TOTP codes. The data lives in real `.kdbx` files you can open in KeePassXC.

## Quick start

```sh
git clone https://github.com/psyb0t/docker-keepassbox.git
cd docker-keepassbox
cp access.example.json access.local.json
openssl rand -hex 32
```

Replace `REPLACE_ME` in `access.local.json` with the generated token. Give the container's UID 10001 read access to that file. On a standard Linux Docker install:

```sh
sudo chown 10001:10001 access.local.json
sudo chmod 0400 access.local.json
docker compose up -d
curl -fsS http://localhost:8000/healthz
```

The Compose file binds to loopback and gives a 512 MiB Argon2 operation room to run. Keep the data volume and back up its encrypted vaults. Use HTTPS through your trusted proxy when connecting remotely. See [deployment](docs/install.md) for paths and key files.

## What it does

- Create and unlock multiple vaults with a master password, a configured key file, or both.
- Change the KDBX 4 cipher, KDF, Argon2 memory, iterations, parallelism, and compression. Rotate the password or key file separately.
- Create and search entries and groups, move or trash entries, and edit passwords, notes, tags, protected fields, and small attachments.
- Save a TOTP seed or URI inside an entry and return the current code and expiry.
- Scope each bearer token to one owner and a set of permissions. REST and MCP use the same checks.

This release covers the [documented API](docs/api.md). KeePassXC desktop integrations, hardware unlock, merge and sync, format conversion, and entry history restore are outside the current API. Ordinary edits preserve entry history already in the file.

## Agent integrations

Connect a Streamable HTTP MCP client to `http://localhost:8000/mcp` and configure its scoped bearer token. See [MCP configuration](docs/mcp.md).

```sh
openclaw skills install @psyb0t/docker-keepassbox
openclaw plugins install clawhub:@psyb0t/keepassbox
```

Configure `KEEPASSBOX_URL` and `KEEPASSBOX_TOKEN` for the OpenClaw bridge.

## Development

```sh
make lint
make test
make sec
make build
```

The tests run in Docker with synthetic KDBX files. The engine tests check encrypted round trips and TOTP. Integration tests call both transports.

## Sponsor

[GitHub Sponsors](https://github.com/sponsors/psyb0t) · [Buy me a coffee](https://www.buymeacoffee.com/psyb0t)

## License

[GPL-3.0](LICENSE). The vault engine uses [PyKeePass](https://github.com/libkeepass/pykeepass).
