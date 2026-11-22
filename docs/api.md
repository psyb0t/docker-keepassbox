---
title: REST API
description: Create and unlock KeePass vaults, set ciphers and Argon2 parameters, manage entries, and retrieve TOTP codes through REST.
nav_order: 3
---

# REST API

Use `Authorization: Bearer <token>` for `/v1` and `/mcp`. Fetch the OpenAPI schema at `/openapi.json` with the same header.

## Access

The installer token has all five scopes, including permission to retrieve passwords and TOTP codes over REST and MCP. In builds from `main`, omit `scopes` to give a custom token all five permissions for its owner. Set a nonempty list from the table below to restrict a token. The `v0.1.1` image requires an explicit list in custom access files.

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

[Start KeePassBox](install.md), then run these examples in Bash with `curl`, `jq`, and `openssl`. They create a fresh demo vault with sample credentials. Run them against a test instance.

```bash
base=http://127.0.0.1:8000
token=$(keepassbox token)
vault="demo-$(openssl rand -hex 4)"

kb() {
  curl -fsS --header @<(printf 'Authorization: Bearer %s\n' "$token") "$@"
}

kb "$base/healthz"

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

## Vaults

```text
GET   /v1/vaults
POST  /v1/vaults
GET   /v1/vaults/{vault}
POST  /v1/vaults/{vault}/unlock
POST  /v1/vaults/{vault}/lock
PATCH /v1/vaults/{vault}/security
POST  /v1/vaults/{vault}/rekey
```

Create accepts `id`, `name`, `credentials`, and optional `security`. Set `password`, `keyFile` (a configured alias), or both. Send the whole security object when changing settings. This one sets Argon2id to 512 MiB:

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

To change credentials, fetch a fresh revision and send it with `credentials` to `POST /v1/vaults/{vault}/rekey`. Keep the old credentials if you need to open the [previous encrypted revision](install.md#vault-files-and-backups).

## Entries and groups

List or create using `/v1/vaults/{vault}/entries` and `/v1/vaults/{vault}/groups`. Entry metadata excludes passwords, notes, OTP seeds, custom field values, and attachment contents. Entry and vault lists accept `limit` and `offset`. Entry lists also accept `q`.

Use `GET`, `PATCH`, or `DELETE` at `/v1/vaults/{vault}/entries/{entry}`. Deleting an entry moves it to the recycle bin. Write an OTP seed or URI with `PUT .../totp` and generate a code with `POST .../totp/code`. The code response includes an expiry as Unix seconds.

Reveal a password or note with `POST .../reveal?field=password` or `?field=notes`. Store a protected field with `PUT .../fields/{name}` and read it through `POST .../fields/{name}/reveal`. The KDBX entry stores these fields with a `custom:` prefix. Attachments use `GET` and `POST .../attachments` and `GET .../attachments/{index}`. Inline transfer is capped at 32 KiB per attachment.

Use KeePassXC for desktop integrations, hardware unlock, merge and sync, format conversion, and entry history restore.

## Errors

API errors return a JSON object with `code`, `message`, and `details`. Use the code to decide what to do.

| HTTP | Example code | What to check |
| --- | --- | --- |
| 401 | `UNAUTHORIZED` | Check the bearer token. |
| 403 | `FORBIDDEN` | Check the token's scopes. |
| 404 | `VAULT_NOT_FOUND` | Check the vault ID and the token's owner. |
| 409 | `VAULT_CONFLICT` | Fetch a fresh revision. If another client wrote to the file directly, reopen the vault first. |
| 413 | `BODY_LIMIT` | Send a body at most 64 KiB with `Content-Length`. |
| 422 | `INVALID_REQUEST` | Check the request against the OpenAPI schema. |
| 423 | `VAULT_LOCKED` | Unlock the vault and retry. |
