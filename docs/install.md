---
title: Install
---

# Install

Start with the [Compose quick start](https://github.com/psyb0t/docker-keepassbox#quick-start). The image also runs directly with a writable volume at `/data` and a read-only access file at `/run/secrets/keepassbox_access`. It uses UID and GID 10001 and listens on port 8000.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `KEEPASSBOX_ACCESS_FILE` | `/run/secrets/keepassbox_access` | JSON list of scoped clients. The file must exist at startup. |
| `KEEPASSBOX_DATA_DIR` | `/data` | Mounted vault directory. |
| `KEEPASSBOX_IDLE_SECONDS` | `600` | Idle time before the service drops unlocked vault state. |
| `KEEPASSBOX_KDF_MAX_MIB` | `512` | Maximum Argon2 memory allowed when opening or writing a vault. |

An owner named `automation` sees files at `/data/automation/<id>.kdbx`. To open an existing database, stop any other writer, place a copy in the appropriate owner directory, and unlock it with the API. The service also reads provisioned key files at `/data/automation/keys/<alias>.keyx`. Alias references stay scoped to the same owner. Give UID 10001 access and keep an independent copy of each key file.

The service serializes vault operations and retains the previous encrypted revision as `<id>.previous`. The previous revision still uses the prior password, key file, and KDF. Keep backups independently of this one-revision recovery file. Run one service process against each managed volume.

Set the container memory above the KDF cap plus service overhead. The supplied 1 GiB limit is for the default 512 MiB KDF cap. Use vault files from trusted sources. KeePassBox bounds file size and KDF parameters, and the container memory limit covers unexpected resource use during decrypt or decompress.
