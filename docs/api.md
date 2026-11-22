---
title: REST API
---

# REST API

Use `Authorization: Bearer <token>` for `/v1` and `/mcp`. Fetch the OpenAPI schema at `/openapi.json` with the same header.

## Access

| Scope | Operations |
| --- | --- |
| `vaults:create` | Create a writable vault in the caller's owner directory. |
| `entries:read` | List vaults, lock and unlock them, and read vault settings and record metadata. |
| `entries:write` | Create and change entries, groups, fields, attachments and TOTP setup. Generate passwords. |
| `secrets:read` | Read protected fields, attachment contents, and current codes. |
| `vaults:admin` | Update vault security settings and rekey. |

Owners isolate storage and unlocked state. Tokens assigned to the same owner share the unlocked state. Give separate owners to clients that should have separate vaults.

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

Create accepts `id`, `name`, `credentials`, and optional `security`. Credentials accept `password`, `keyFile` (a configured alias), or both. Security is a full settings object. The following settings use 512 MiB:

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

## Entries and groups

List or create using `/v1/vaults/{vault}/entries` and `/v1/vaults/{vault}/groups`. Entry metadata excludes passwords, notes, OTP seeds, custom field values, and attachment contents. Entry and vault lists accept `limit` and `offset`. Entry lists also accept `q`.

Use `GET`, `PATCH`, or `DELETE` at `/v1/vaults/{vault}/entries/{entry}`. Deleting an entry moves it to the recycle bin. Write an OTP seed or URI with `PUT .../totp` and generate a code with `POST .../totp/code`. The code response includes an expiry as Unix seconds.

Reveal a password or note with `POST .../reveal?field=password` or `?field=notes`. Store a protected field with `PUT .../fields/{name}` and read it through `POST .../fields/{name}/reveal`. The KDBX entry stores these fields with a `custom:` prefix. Attachments use `GET` and `POST .../attachments` and `GET .../attachments/{index}`. Inline transfer is capped at 32 KiB per attachment.
