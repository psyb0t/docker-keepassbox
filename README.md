# KeePassBox

[![CI](https://github.com/psyb0t/docker-keepassbox/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/psyb0t/docker-keepassbox/actions/workflows/pipeline.yml)
[![version](https://raw.githubusercontent.com/psyb0t/docker-keepassbox/badges/version.svg)](https://github.com/psyb0t/docker-keepassbox/releases)
[![license](https://raw.githubusercontent.com/psyb0t/docker-keepassbox/badges/license.svg)](LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/psyb0t/keepassbox?style=flat-square)](https://hub.docker.com/r/psyb0t/keepassbox)

Put KeePass behind REST and MCP. Create a vault, rotate its master password, turn Argon2 up to 512 MiB, or grab a TOTP code from the terminal. You can open the same `.kdbx` in KeePassXC.

## Contents

- [Quick start](#quick-start)
- [What it does](#what-it-does)
- [Agent integrations](#agent-integrations)
- [Documentation](#documentation)
- [Development](#development)
- [Sponsor](#sponsor)
- [License](#license)

## Quick start

Run this as your regular Docker user on Linux. You need Docker Compose, curl, and OpenSSL. Install jq to use the token command.

```sh
curl -fsSL https://raw.githubusercontent.com/psyb0t/docker-keepassbox/main/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"
keepassbox start
```

If your shell can't find the command, run `~/.local/bin/keepassbox start`. Run `keepassbox token` to get the installer-generated bearer token. It can manage its owner's vaults, read passwords, and generate TOTP codes. REST is at `http://localhost:8000/v1`, and MCP is at `http://localhost:8000/mcp`.

The installer puts the Compose files and vaults in `~/.config/keepassbox/` by default and uses the published `psyb0t/keepassbox:latest` image. See the [install guide](https://psyb0t.github.io/docker-keepassbox/install/) to pin a version, change the port, or upgrade. Enable the [Tailscale sidecar](https://psyb0t.github.io/docker-keepassbox/install/#tailscale-access) for private HTTPS access over your tailnet.

## What it does

- Create and unlock multiple vaults with a master password, a configured key file, or both.
- Change the KDBX 4 cipher, KDF, Argon2 memory, iterations, parallelism, and compression. Rotate the password or key file separately.
- Create groups, search entries, move or trash them, and edit passwords, notes, tags, protected fields, and small attachments.
- Save a TOTP seed or URI inside an entry and return the current code and expiry.
- Give each bearer token access to one owner's vaults. Restrict individual tokens with a custom [scope list](https://psyb0t.github.io/docker-keepassbox/api/#access).

Ordinary edits preserve entry history. See the [REST guide](https://psyb0t.github.io/docker-keepassbox/api/) for a walkthrough and the [API reference](https://psyb0t.github.io/docker-keepassbox/reference/) for endpoint parameters, examples, and errors.

## Agent integrations

Connect a Streamable HTTP MCP client to `http://localhost:8000/mcp` and configure its bearer token. See [MCP configuration](https://psyb0t.github.io/docker-keepassbox/mcp/).

```sh
openclaw skills install @psyb0t/docker-keepassbox
openclaw plugins install clawhub:@psyb0t/keepassbox
```

Configure `KEEPASSBOX_URL` and `KEEPASSBOX_TOKEN` for the OpenClaw bridge.

## Documentation

Read the [KeePassBox docs](https://psyb0t.github.io/docker-keepassbox/) for install options, vault security settings, and the REST and MCP commands.

## Development

```sh
make lint
make test
make sec
make build
```

The tests run in Docker with synthetic KDBX files. The engine tests check encrypted round trips and TOTP. Integration tests call both transports.

## Sponsor

[Sponsor on GitHub](https://github.com/sponsors/psyb0t)

<a href="https://www.buymeacoffee.com/psyb0t"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-blue.png" alt="Buy Me a Coffee" height="60" width="217"></a>

## License

[GPL-3.0](LICENSE). The vault engine uses [PyKeePass](https://github.com/libkeepass/pykeepass).
