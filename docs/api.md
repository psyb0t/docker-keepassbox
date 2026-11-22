---
title: REST API guide
description: Create and unlock KeePass vaults, set ciphers and Argon2 parameters, manage entries, and retrieve TOTP codes through REST.
nav_order: 3
---

# REST API

The installer serves REST at `http://127.0.0.1:8000/v1`. Send `Authorization: Bearer <token>` with each request. Look up an operation in the [REST API reference]({{ '/reference/' | relative_url }}). Each endpoint shows its parameters, required scope, curl example, and responses. For agent tools, see [MCP](mcp.md).

## Access

The installer token has all five scopes, including permission to retrieve passwords and TOTP codes over REST and MCP. In `v0.2.0` and later, omit `scopes` to give a custom token all five permissions for its owner. Set a nonempty list from the table below to restrict a token. The `v0.1.1` image requires an explicit list in custom access files.

See the [access file example](install.md#access-file-example) for a full-access token and a restricted token.

| Scope | Operations |
| --- | --- |
| `vaults:create` | Create a writable vault in the caller's owner directory. |
| `entries:read` | List vaults, lock and unlock them, and read vault settings and record metadata. |
| `entries:write` | Create and change entries, groups, fields, attachments and TOTP setup. Generate passwords. |
| `secrets:read` | Read protected fields, attachment contents, and current codes. |
| `vaults:admin` | Update vault security settings and rekey. |

Owners isolate storage and unlocked state. Tokens assigned to the same owner share the unlocked state. Give separate owners to clients that should have separate vaults.

## Try it with curl

[Start KeePassBox](install.md), then run these examples against a test instance in one Bash session with curl 7.82 or newer, jq, and OpenSSL. They create a demo vault with sample credentials. For a remote instance, set `KEEPASSBOX_URL` to its HTTPS base URL first. For a custom client, set `KEEPASSBOX_TOKEN` to its assigned token.

```bash
export KEEPASSBOX_URL="${KEEPASSBOX_URL:-$(keepassbox url)}"
export KEEPASSBOX_TOKEN="${KEEPASSBOX_TOKEN:-$(keepassbox token)}"
base="${KEEPASSBOX_URL%/}"

kb() {
  curl -fsS --header @<(printf 'Authorization: Bearer %s\n' "$KEEPASSBOX_TOKEN") "$@"
}

kb "$base/v1/vaults"
```

An owner with no vaults gets HTTP 200 and this response.

```json
{
  "items": [],
  "total": 0
}
```

Create a vault for the rest of the walkthrough.

```bash
vault="demo-$(openssl rand -hex 4)"
export KEEPASSBOX_VAULT="$vault"
jq -n --arg id "$vault" '{
  id: $id,
  name: "Demo vault",
  credentials: {password: "example-demo-password"}
}' | kb --json @- "$base/v1/vaults"
```

Create an entry, read back its sample password, and generate a TOTP code:

```bash
entries="$base/v1/vaults/$vault/entries"
entry=$(kb --json '{
  "title": "Demo account",
  "username": "demo@example.invalid",
  "password": "example-entry-password"
}' "$entries" | jq -er '.id')
export KEEPASSBOX_ENTRY="$entry"

kb --data '' "$entries/$entry/reveal?field=password"
kb -X PUT --json '{"value":"JBSWY3DPEHPK3PXP"}' "$entries/$entry/totp"
kb --data '' "$entries/$entry/totp/code"
kb "$entries?limit=10&offset=0"
```

The code response contains a `code` string and `expiresAt` in Unix seconds. The entries response contains `items` and `total` and leaves out secrets.

Lock the vault and unlock it again with the demo password:

```bash
kb --data '' "$base/v1/vaults/$vault/lock"
kb --json '{"password":"example-demo-password"}' "$base/v1/vaults/$vault/unlock"
```

## Endpoint reference

Send JSON bodies with `Content-Type: application/json`. POST, PUT, and PATCH require a `Content-Length` header and accept up to 64 KiB of request data. For a POST without a body, send a zero-length body as in the examples above. Vault IDs, key aliases, and custom field names use 1 to 64 lowercase letters, digits, hyphens, and underscores. The first character must be a letter or digit. Group and entry IDs are UUIDs.

Browse the [REST API reference]({{ '/reference/' | relative_url }}) or [download the OpenAPI document]({{ '/reference/openapi.json' | relative_url }}). To get the schema for your running version, run `kb "$base/openapi.json" > keepassbox-openapi.json`.

The reference examples default to the vault ID `demo`. The walkthrough sets `KEEPASSBOX_VAULT` and `KEEPASSBOX_ENTRY` for its test vault and entry. If you skip the walkthrough, substitute your own IDs. Set `KEEPASSBOX_GROUP` to a group UUID for the create-group example, and `KEEPASSBOX_REVISION` to the current vault revision before updating security or rekeying. Fetch a new revision after a write.

### Credentials and encryption

A credentials object must contain `password`, `keyFile`, or both. A vault password can have 1 to 1024 characters. Set `keyFile` to an [operator-provisioned alias](install.md#vault-files-and-backups). Send the whole security object when changing settings. This one sets Argon2id to 512 MiB:

```json
{
  "cipher": "chacha20",
  "compression": true,
  "kdf": {
    "algorithm": "argon2id",
    "memoryMiB": 512,
    "iterations": 2,
    "parallelism": 2,
    "version": 19
  }
}
```

Other cipher values are `aes256` and `twofish`. Other KDFs are `argon2d` and `aes-kdf`. AES-KDF takes `rounds` and has no memory setting. The default is AES-256 with Argon2id at 64 MiB, three iterations, and two lanes. Supported KDBX 3 files can be opened and edited with their original security settings. Cipher and KDF changes require KDBX 4.

Argon2 accepts 8 to 1024 MiB, subject to the [configured memory limit](install.md#environment-variables), 1 to 100 iterations, 1 to 16 lanes, and version 16 or 19. AES-KDF accepts 1 to 100 million rounds. Compression defaults to `true`.

Pass the `revision` from the unlocked vault to a security update or rekey. A stale revision returns HTTP 409. After an external file change, lock and reopen the vault before writing again.

Update the demo vault's cipher and KDF:

```bash
revision=$(kb "$base/v1/vaults/$vault" | jq -er '.revision')
jq -n --arg revision "$revision" '{
  revision: $revision,
  security: {
    cipher: "chacha20",
    kdf: {algorithm: "argon2id", memoryMiB: 512, iterations: 2, parallelism: 2}
  }
}' | kb -X PATCH --json @- "$base/v1/vaults/$vault/security"
```

To change credentials, fetch a fresh revision and send it with `credentials` to `POST /v1/vaults/{vault}/rekey`. Rekey replaces the entire credential set. Send the current password or key alias again if you want to keep that factor. The [previous encrypted revision](install.md#vault-files-and-backups) requires its old credentials.

Use KeePassXC for desktop integrations, hardware unlock, merge and sync, format conversion, and entry history restore.

## Errors

KeePassBox application errors return `code`, `message`, and `details`. Use the code to decide what to do.

| HTTP | Example code | What to check |
| --- | --- | --- |
| 401 | `UNAUTHORIZED` | Check the bearer token. |
| 403 | `FORBIDDEN` | Check the token's scopes. |
| 403 | `INVALID_CREDENTIALS` | Check the vault password and key file. |
| 404 | `VAULT_NOT_FOUND` | Check the vault ID and the token's owner. |
| 409 | `VAULT_CONFLICT` | Fetch a fresh revision. If another client wrote to the file directly, reopen the vault first. |
| 409 | `VAULT_EXISTS` | Choose an unused vault ID. |
| 409 | `FORMAT_REQUIRED` | Cipher and KDF changes require KDBX 4. |
| 413 | `BODY_LIMIT` | Send a body at most 64 KiB with `Content-Length`. |
| 422 | `INVALID_REQUEST` | Check the request against the OpenAPI schema. |
| 423 | `VAULT_LOCKED` | Unlock the vault and retry. |
| 503 | `STORE_UNAVAILABLE` | Check the data directory, permissions, and free space. |

Use a native or server-side HTTP client. Protected routes reject requests that carry an `Origin` header. Fetch the schema with the bearer header rather than opening `/docs` in an ordinary browser tab.
