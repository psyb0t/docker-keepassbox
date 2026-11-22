---
title: Install KeePassBox
description: Install KeePassBox from the published Docker image with Compose, pin a release, and keep encrypted vaults between upgrades.
nav_order: 2
---

# Install KeePassBox

## Docker Compose installer

Run the installer as your regular Docker user on a Linux host with Docker Compose, curl, and OpenSSL.

```bash
curl -fsSL https://raw.githubusercontent.com/psyb0t/docker-keepassbox/main/install.sh | bash
keepassbox start
keepassbox token
```

The [installer](https://github.com/psyb0t/docker-keepassbox/blob/main/install.sh) writes Compose and its settings to `${XDG_CONFIG_HOME:-$HOME/.config}/keepassbox/`, installs the wrapper in `~/.local/bin/`, and generates an access token in `access.local.json`. Run `keepassbox config` to print the configuration directory. If the command isn't on your PATH, use `~/.local/bin/keepassbox`.

The host listens on `127.0.0.1:8000`. If that port is taken or you want a pinned image, pass the options to the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/psyb0t/docker-keepassbox/main/install.sh \
  | bash -s -- --port 8010 --version v0.1.1
keepassbox start
```

Use `keepassbox status` or `keepassbox logs` to check it. Use `keepassbox stop` to stop it. `keepassbox upgrade` pulls the configured tag and brings the service back up. Run `keepassbox upgrade --version latest` to follow the latest image again, or pass a specific release tag. `keepassbox uninstall` removes the container and command while keeping the vaults and access settings so you can reinstall.

## Manage Docker yourself

The published image is `psyb0t/keepassbox:latest`. Start from the [Compose file](https://github.com/psyb0t/docker-keepassbox/blob/main/compose.yaml) and the [access example](https://github.com/psyb0t/docker-keepassbox/blob/main/access.example.json) if you manage your own stack. Set a long random token in `access.local.json` and make it readable by the container's UID 10001. The image needs a writable volume at `/data` and a read-only access file at `/run/secrets/keepassbox_access`. It listens on port 8000. Use HTTPS through your proxy for remote clients.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `KEEPASSBOX_ACCESS_FILE` | `/run/secrets/keepassbox_access` | JSON list of scoped clients. The file must exist at startup. |
| `KEEPASSBOX_DATA_DIR` | `/data` | Mounted vault directory. |
| `KEEPASSBOX_IDLE_SECONDS` | `600` | Idle time before the service drops unlocked vault state. |
| `KEEPASSBOX_KDF_MAX_MIB` | `512` | Maximum Argon2 memory allowed when opening or writing a vault. |

## Vault files and backups

An owner named `automation` sees files at `/data/automation/<id>.kdbx` inside the container. The installer keeps those under `data/automation/` in the configuration directory. To import an existing vault, stop any other writer, put a copy in that owner directory, and unlock it with the API. Use `data/automation/keys/<alias>.keyx` for a configured key file. Keep a separate backup of each key file.

KeePassBox keeps the previous encrypted revision as `<id>.previous`, using the prior password, key file, and KDF. Keep separate backups and run one writer against each managed volume.

Set the container memory above the KDF cap plus service overhead. The supplied 1 GiB limit is for the default 512 MiB KDF cap. Use vault files from trusted sources. KeePassBox bounds file size and KDF parameters, and the container memory limit covers unexpected resource use during decrypt or decompress.
