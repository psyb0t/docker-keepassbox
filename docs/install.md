---
title: Install KeePassBox
description: Install KeePassBox from the published Docker image with Compose, pin a release, and keep encrypted vaults between upgrades.
nav_order: 2
---

# Install KeePassBox

## Docker Compose installer

Run the installer as your regular Docker user on a Linux host with Docker Compose, curl, and OpenSSL. Install jq to use the token command.

```bash
curl -fsSL https://raw.githubusercontent.com/psyb0t/docker-keepassbox/main/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"
keepassbox start
keepassbox token
```

The [installer](https://github.com/psyb0t/docker-keepassbox/blob/main/install.sh) writes Compose and its settings to `${XDG_CONFIG_HOME:-$HOME/.config}/keepassbox/`, installs the wrapper in `~/.local/bin/`, and generates an access token in `access.local.json`. Run `keepassbox config` to print the configuration directory. If the command isn't on your PATH, use `~/.local/bin/keepassbox`.

The host listens on `127.0.0.1:8000`. If that port is taken or you want a pinned image, pass the options to the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/psyb0t/docker-keepassbox/main/install.sh \
  | bash -s -- --port 8010 --version v0.2.1
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

From the directory containing both files, start the service and check health:

```bash
docker compose up -d --wait
curl -fsS http://127.0.0.1:8000/healthz
```

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

The access file contains plaintext bearer tokens. Restrict who can read it. With one client, `keepassbox token` prints that client's token. With multiple owners, use `keepassbox token --owner automation` to select an owner with exactly one client. For multiple clients under the same owner, use the intended client's token from the file directly. A token with `entries:read` can also lock the shared vault or unlock it with the correct vault credentials. Reading from an unlocked vault extends its idle timer.

Restart the installer-managed service after saving or revoking a token. This also locks open vaults.

```bash
keepassbox stop
keepassbox start
```

### Environment variables

The installer's `.env` configures Compose and the Tailscale sidecar. To set application variables, add them under `services.keepassbox.environment` in `$(keepassbox config)/compose.yaml` or your own Compose file. Keep the existing service keys.

```yaml
services:
  keepassbox:
    environment:
      KEEPASSBOX_IDLE_SECONDS: "900"
      KEEPASSBOX_KDF_MAX_MIB: "512"
```

Apply changes with `keepassbox start` for an installer-managed setup or `docker compose up -d --wait` for direct Compose. Use `keepassbox url` to print the local base URL with the configured port.

| Variable | Default | Purpose |
| --- | --- | --- |
| `KEEPASSBOX_ACCESS_FILE` | `/run/secrets/keepassbox_access` | JSON object with a `clients` array. The file must exist at startup. |
| `KEEPASSBOX_DATA_DIR` | `/data` | Mounted vault directory. |
| `KEEPASSBOX_IDLE_SECONDS` | `600` | Idle time before the service drops unlocked vault state. Accepts 5 to 86400 seconds. |
| `KEEPASSBOX_KDF_MAX_MIB` | `512` | Maximum Argon2 memory allowed when opening or writing a vault. Accepts 64 to 1024 MiB. |

## Vault files and backups

An owner named `automation` sees files at `/data/automation/<id>.kdbx` inside the container. The installer keeps those under `data/automation/` in the configuration directory. To import an existing vault, stop any other writer, put a copy in that owner directory, and unlock it with the API. Use `data/automation/keys/<alias>.keyx` for a configured key file. Keep a separate backup of each key file.

KeePassBox saves one previous encrypted revision as `<id>.previous`. Each vault update replaces it. Keep independent backups of the vaults and store any key files separately. To restore, stop all writers, preserve a copy of the current vault, and use a copy of the backup as the owner's `<id>.kdbx`. Preserve file ownership and permissions. Restart the service and unlock with the password and key file from that revision.

Set the container memory above the KDF cap plus service overhead. The supplied 1 GiB limit is for the default 512 MiB KDF cap. Use vault files from trusted sources. KeePassBox bounds file size and KDF parameters, and the container memory limit covers unexpected resource use during decrypt or decompress.
