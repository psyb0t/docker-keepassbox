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
  | bash -s -- --port 8010 --version v0.2.0
keepassbox start
```

Use `keepassbox status` or `keepassbox logs` to check it. Use `keepassbox stop` to stop it. `keepassbox upgrade` pulls the configured tag and brings the service back up. Run `keepassbox upgrade --version latest` to follow the latest image again, or pass a specific release tag. `keepassbox uninstall` removes the container and command while keeping the vaults and access settings so you can reinstall.

### Tailscale access

The installer can run a [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve) sidecar for private HTTPS access from your tailnet. If KeePassBox is already installed, rerun the installer above to update the command and add the sidecar configuration.

Edit `$(keepassbox config)/.env` and add these settings:

```dotenv
KEEPASSBOX_TAILSCALE_ENABLED=true
KEEPASSBOX_TAILSCALE_HOSTNAME=keepassbox
# KEEPASSBOX_TAILSCALE_AUTHKEY=REPLACE_ME
```

Enable MagicDNS and HTTPS certificates in your tailnet, then run `keepassbox start`. If you left the auth key unset, run `keepassbox logs tailscale` and follow the login URL. Use the device's full HTTPS name from Tailscale for your API base URL and append `/mcp` for MCP. Both still require the KeePassBox bearer token.

To disable the sidecar, set `KEEPASSBOX_TAILSCALE_ENABLED=false` and run `keepassbox start` again. Local access stays on loopback. The sidecar's login state survives disabling, upgrades, and uninstall so it can reconnect later.

## Manage Docker yourself

The published image is `psyb0t/keepassbox:latest`. Start from the [Compose file](https://github.com/psyb0t/docker-keepassbox/blob/main/compose.yaml) and the [access example](https://github.com/psyb0t/docker-keepassbox/blob/main/access.example.json) if you manage your own stack. Set a long random token in `access.local.json` and make it readable by the container's UID 10001. The image needs a writable volume at `/data` and a read-only access file at `/run/secrets/keepassbox_access`. It listens on port 8000. Use HTTPS through your proxy for remote clients.

## Configuration

### Access file example

For an installer-managed setup, edit `$(keepassbox config)/access.local.json`. Keep the generated token and append any new clients to the `clients` array. This example gives two tokens access to the same owner's vaults. The first can manage vaults and read secrets. The second can list entries and inspect metadata.

```json
{
  "clients": [
    {
      "owner": "automation",
      "token": "REPLACE_WITH_EXISTING_INSTALLER_TOKEN",
      "scopes": [
        "vaults:create",
        "entries:read",
        "entries:write",
        "secrets:read",
        "vaults:admin"
      ]
    },
    {
      "owner": "automation",
      "token": "REPLACE_WITH_NEW_RANDOM_TOKEN",
      "scopes": [
        "entries:read"
      ]
    }
  ]
}
```

Generate a different token for each new client with `openssl rand -hex 32`. Use a different `owner` when clients should have separate vaults. The example works with `v0.1.1` and later. See [scope defaults](api.md#access) for when you can omit the list.

Restart the installer-managed service after saving the file:

```bash
keepassbox stop
keepassbox start
```

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `KEEPASSBOX_ACCESS_FILE` | `/run/secrets/keepassbox_access` | JSON object with a `clients` array. The file must exist at startup. |
| `KEEPASSBOX_DATA_DIR` | `/data` | Mounted vault directory. |
| `KEEPASSBOX_IDLE_SECONDS` | `600` | Idle time before the service drops unlocked vault state. |
| `KEEPASSBOX_KDF_MAX_MIB` | `512` | Maximum Argon2 memory allowed when opening or writing a vault. |

## Vault files and backups

An owner named `automation` sees files at `/data/automation/<id>.kdbx` inside the container. The installer keeps those under `data/automation/` in the configuration directory. To import an existing vault, stop any other writer, put a copy in that owner directory, and unlock it with the API. Use `data/automation/keys/<alias>.keyx` for a configured key file. Keep a separate backup of each key file.

KeePassBox keeps the previous encrypted revision as `<id>.previous`, using the prior password, key file, and KDF. Keep separate backups and run one writer against each managed volume.

Set the container memory above the KDF cap plus service overhead. The supplied 1 GiB limit is for the default 512 MiB KDF cap. Use vault files from trusted sources. KeePassBox bounds file size and KDF parameters, and the container memory limit covers unexpected resource use during decrypt or decompress.
