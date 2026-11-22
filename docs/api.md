---
title: REST API
description: Create and unlock KeePass vaults, set ciphers and Argon2 parameters, manage entries, and retrieve TOTP codes through REST.
nav_order: 3
---

# REST API

The installer serves REST at `http://127.0.0.1:8000/v1`. Send `Authorization: Bearer <token>` with each request. The [endpoint reference](#endpoint-reference) lists requests, responses, and scope requirements. For agent tools, see [MCP](mcp.md).

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
base="${KEEPASSBOX_URL:-$(keepassbox url)}"
token="${KEEPASSBOX_TOKEN:-$(keepassbox token)}"
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

## Endpoint reference

Send JSON bodies with `Content-Type: application/json`. POST, PUT, and PATCH require a `Content-Length` header and accept up to 64 KiB of request data. For a POST without a body, send a zero-length body as in the examples above. Vault IDs, key aliases, and custom field names use 1 to 64 lowercase letters, digits, hyphens, and underscores. The first character must be a letter or digit. Group and entry IDs are UUIDs.

### Service endpoints

| Method and path | Scope | Success |
| --- | --- | --- |
| `GET /healthz` | Public | 200, `{"ok":true}` |
| `GET /version` | Public | 200, `name` and `version` |
| `GET /openapi.json` | Any valid token | 200, OpenAPI schema |
{: .api-endpoints }

Save the live OpenAPI schema with `kb "$base/openapi.json" > keepassbox-openapi.json` after defining `kb` above.

### Pagination and search

Vault and entry listings return `items` and the matching `total` before pagination. `limit` defaults to 50 and accepts 1 to 100. `offset` is zero-based, defaults to 0, and accepts 0 to 100000. Entry lists also accept `q`, a case-insensitive substring filter of up to 256 characters on title, username, and tags.

### Vaults

Replace `{vault}` with the vault ID. To unlock a vault with ID `demo`, send `POST /v1/vaults/demo/unlock`.

| Method and path | Request | Success | Scope |
| --- | --- | --- | --- |
| `GET /v1/vaults` | Query `limit`, `offset` | 200, page of `id` and `unlocked` | `entries:read` |
| `POST /v1/vaults` | `id`, `name`, `credentials`, optional `security` | 201, vault details | `vaults:create` |
| `GET /v1/vaults/{vault}` | No body | 200, vault details | `entries:read` |
| `POST /v1/vaults/{vault}/unlock` | Credentials object | 200, vault details | `entries:read` |
| `POST /v1/vaults/{vault}/lock` | Empty body | 200, `id` and `unlocked: false` | `entries:read` |
| `PATCH /v1/vaults/{vault}/security` | `revision` and `security` | 200, updated vault details | `vaults:admin` |
| `POST /v1/vaults/{vault}/rekey` | `revision` and new `credentials` | 200, updated vault details | `vaults:admin` |
{: .api-endpoints }

Vault details have `id`, `name`, `format`, `revision`, `unlocked`, and `security`. Creating a vault unlocks it. A lock clears the owner's cached unlock state for that vault. Vault details, edits, and entry operations need an unlocked vault.

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

### Entries and groups

| Method and path | Request | Success | Scope |
| --- | --- | --- | --- |
| `GET /v1/vaults/{vault}/groups` | No body | 200, array of groups | `entries:read` |
| `POST /v1/vaults/{vault}/groups` | `name`, optional `parentId` | 201, group | `entries:write` |
| `GET /v1/vaults/{vault}/entries` | Query `q`, `limit`, `offset` | 200, page of entry metadata | `entries:read` |
| `POST /v1/vaults/{vault}/entries` | `title` and optional entry fields | 201, entry metadata | `entries:write` |
| `GET /v1/vaults/{vault}/entries/{entry}` | No body | 200, entry metadata | `entries:read` |
| `PATCH /v1/vaults/{vault}/entries/{entry}` | Fields to update | 200, entry metadata | `entries:write` |
| `DELETE /v1/vaults/{vault}/entries/{entry}` | No body | 200, `id` and `trashed: true` | `entries:write` |
{: .api-endpoints }

A group has `id`, `name`, and `parentId`. Omit `parentId` when creating a group under the root. Entry fields are `title`, `groupId`, `username`, `password`, `url`, `notes`, and `tags`. Omit `groupId` to create the entry in the root. On PATCH, fields left out or set to `null` keep their previous values. To move an entry, supply the destination group's UUID. Use an empty string to clear an optional text field or an empty array to clear tags.

Entry metadata contains `id`, `title`, `username`, `url`, `tags`, `groupId`, and `hasTotp`. Deleting moves the entry to the recycle bin and removes it from entry listings.

### Secrets, TOTP, and attachments

| Method and path | Request | Success | Scope |
| --- | --- | --- | --- |
| `POST /v1/vaults/{vault}/entries/{entry}/reveal` | Query `field=password` or `field=notes`; empty body | 200, `value` | `secrets:read` |
| `PUT /v1/vaults/{vault}/entries/{entry}/totp` | `value` with a Base32 seed or `otpauth://totp/` URI | 200, `id` and `hasTotp: true` | `entries:write` |
| `POST /v1/vaults/{vault}/entries/{entry}/totp/code` | Empty body | 200, `code` and `expiresAt` in Unix seconds | `secrets:read` |
| `PUT /v1/vaults/{vault}/entries/{entry}/fields/{name}` | `value` | 200, `name` | `entries:write` |
| `POST /v1/vaults/{vault}/entries/{entry}/fields/{name}/reveal` | Empty body | 200, `value` | `secrets:read` |
| `GET /v1/vaults/{vault}/entries/{entry}/attachments` | No body | 200, array of `index` and `name` | `entries:read` |
| `POST /v1/vaults/{vault}/entries/{entry}/attachments` | `name` and `contentBase64` | 201, `name` | `entries:write` |
| `GET /v1/vaults/{vault}/entries/{entry}/attachments/{index}` | Zero-based `index` from the attachment list | 200, `name` and `contentBase64` | `secrets:read` |
{: .api-endpoints }

TOTP returns the code as a string so leading zeroes survive. Regular entry reads exclude passwords, notes, OTP seeds, protected field values, and attachment contents. Custom fields are stored with a `custom:` prefix in KDBX. Inline attachment transfers accept up to 32 KiB of decoded content.

### Password generation

`POST /v1/passwords/generate` requires `entries:write`. Send `{}` for a 32-character password with symbols, or supply `length` (16 to 256) and `symbols` (boolean). The 200 response contains `password`. The API does not store that password in a vault.

```bash
kb --json '{"length":24,"symbols":true}' "$base/v1/passwords/generate"
```

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
