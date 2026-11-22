import json
import shlex
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

from .models import Scope
from .responses import ProblemResponse

JSON = "application/json"
DEMO_VAULT = "demo"
DEMO_ENTRY = "11111111-1111-4111-8111-111111111111"
DEMO_GROUP = "22222222-2222-4222-8222-222222222222"
DEMO_REVISION = "0" * 64
PATH_EXAMPLES = {
    "vault": "${KEEPASSBOX_VAULT:-demo}",
    "entry": "${KEEPASSBOX_ENTRY}",
    "name": "recovery",
    "index": "0",
}
QUERY_EXAMPLES = {
    ("GET", "/v1/vaults"): {"limit": 10, "offset": 0},
    ("GET", "/v1/vaults/{vault}/entries"): {"q": "email", "limit": 10, "offset": 0},
    ("POST", "/v1/vaults/{vault}/entries/{entry}/reveal"): {"field": "password"},
}

TAGS = (
    "Service",
    "Vaults",
    "Groups",
    "Entries",
    "Protected fields",
    "TOTP",
    "Attachments",
    "Passwords",
)
CREDENTIALS = {"password": "example-vault-password"}
SECURITY = {
    "cipher": "aes256",
    "kdf": {"algorithm": "aes-kdf", "rounds": 100_000},
    "compression": True,
}
VAULT_STATE = {"id": DEMO_VAULT, "unlocked": True}
VAULT = {
    **VAULT_STATE,
    "name": "Demo vault",
    "format": "4.0",
    "revision": DEMO_REVISION,
    "security": SECURITY,
}
ENTRY_INPUT = {"title": "Demo email", "username": "demo@example.invalid"}
ENTRY = {
    **ENTRY_INPUT,
    "id": DEMO_ENTRY,
    "url": "",
    "tags": [],
    "groupId": DEMO_GROUP,
    "hasTotp": False,
}
ATTACHMENT = {"name": "demo.txt", "contentBase64": "ZGVtbw=="}

ERRORS = {
    "UNAUTHORIZED": (401, "Bearer token required", "Supply a valid bearer token."),
    "FORBIDDEN": (
        403,
        "This token lacks the required permission",
        "Check the required scope and send the request without an Origin header.",
    ),
    "INVALID_CREDENTIALS": (
        403,
        "Vault credentials were rejected",
        "Check the vault password and key file.",
    ),
    "VAULT_NOT_FOUND": (404, "Vault was not found", "Check the vault ID and the token's owner."),
    "KEY_NOT_FOUND": (
        404,
        "Configured key file was not found",
        "Check that the key file alias exists for this owner.",
    ),
    "GROUP_NOT_FOUND": (404, "Group was not found", "Get the group UUID from the group list."),
    "ENTRY_NOT_FOUND": (404, "Entry was not found", "Get the entry UUID from the entry list."),
    "TOTP_NOT_FOUND": (404, "Entry has no TOTP configuration", "Set up TOTP for the entry first."),
    "FIELD_NOT_FOUND": (
        404,
        "Custom field was not found",
        "Check the custom field name or set it first.",
    ),
    "ATTACHMENT_NOT_FOUND": (
        404,
        "Attachment was not found",
        "Get the current index from the entry's attachment list.",
    ),
    "VAULT_EXISTS": (409, "Vault already exists", "Choose an unused vault ID."),
    "VAULT_CONFLICT": (
        409,
        "Vault revision has changed",
        "Fetch the latest revision. If the file changed on disk, reopen the vault first.",
    ),
    "FORMAT_REQUIRED": (
        409,
        "Security changes require a KDBX 4 vault",
        "Use a KDBX 4 vault to change cipher or KDF settings.",
    ),
    "BODY_LIMIT": (
        413,
        "Invalid or oversized request body",
        "Send Content-Length. The request body can be at most 64 KiB.",
    ),
    "INVALID_REQUEST": (
        422,
        "Request validation failed",
        "Check the request parameters and JSON body against the schema.",
    ),
    "INVALID_KEY_FILE": (
        422,
        "Configured key file has an invalid size",
        "Check the installed key file. It must be nonempty and at most 1 MiB.",
    ),
    "INVALID_VAULT": (
        422,
        "Vault format or settings are unsupported",
        "Check whether the vault opens in KeePassXC and uses supported KDBX settings.",
    ),
    "FILE_LIMIT": (
        422,
        "Vault file exceeds the size limit",
        "The vault file can be at most 32 MiB.",
    ),
    "UNSUPPORTED_KDF": (
        422,
        "Unsupported vault KDF",
        "Use supported KDF settings. Argon2 memory must be a whole MiB.",
    ),
    "KDF_LIMIT": (
        422,
        "Vault exceeds the configured KDF memory limit",
        "Lower the Argon2 memory or raise the configured server cap.",
    ),
    "INVALID_TOTP": (
        422,
        "The TOTP setup value is invalid",
        "Check the Base32 seed or TOTP setup URI and its settings.",
    ),
    "INVALID_ATTACHMENT": (
        422,
        "Attachment must be valid base64",
        "Encode the file using standard Base64.",
    ),
    "ATTACHMENT_LIMIT": (
        422,
        "Attachment exceeds inline transfer limit",
        "Inline transfers are limited to 32 KiB of decoded data. Uploads must be nonempty.",
    ),
    "VAULT_LOCKED": (423, "Unlock the vault first", "Unlock the vault and retry."),
    "STORE_UNAVAILABLE": (
        503,
        "Vault storage is unavailable",
        "Check the data directory, permissions, and available space.",
    ),
}
AUTH_ERRORS = ("UNAUTHORIZED", "FORBIDDEN")
COMMON_ERRORS = (*AUTH_ERRORS, "INVALID_REQUEST")
BODY_METHODS = {"POST", "PUT", "PATCH"}
STORAGE = ("STORE_UNAVAILABLE",)
ACTIVE = ("VAULT_NOT_FOUND", "VAULT_LOCKED", *STORAGE)
ENTRY_ACCESS = (*ACTIVE, "ENTRY_NOT_FOUND")
ENGINE = ("INVALID_CREDENTIALS", "INVALID_VAULT", "FILE_LIMIT", "UNSUPPORTED_KDF", "KDF_LIMIT")
KEY = ("KEY_NOT_FOUND", "INVALID_KEY_FILE")
SAVE = ("VAULT_CONFLICT", *ENGINE)
ENTRY_WRITE = (*ENTRY_ACCESS, *SAVE)


@dataclass(frozen=True)
class Operation:
    group: str
    scope: Scope
    response: Any
    request: dict | None = None
    errors: tuple[str, ...] = ()


OPERATIONS = {
    "list_vaults": Operation(
        "Vaults",
        "entries:read",
        {"items": [VAULT_STATE], "total": 1},
        errors=STORAGE,
    ),
    "create_vault": Operation(
        "Vaults",
        "vaults:create",
        VAULT,
        {"id": DEMO_VAULT, "name": "Demo vault", "credentials": CREDENTIALS, "security": SECURITY},
        ("VAULT_EXISTS", *KEY, *ENGINE, *STORAGE),
    ),
    "get_vault": Operation("Vaults", "entries:read", VAULT, errors=ACTIVE),
    "unlock_vault": Operation(
        "Vaults",
        "entries:read",
        VAULT,
        CREDENTIALS,
        ("VAULT_NOT_FOUND", *KEY, *ENGINE, *STORAGE),
    ),
    "lock_vault": Operation("Vaults", "entries:read", {**VAULT_STATE, "unlocked": False}),
    "update_vault_security": Operation(
        "Vaults",
        "vaults:admin",
        {**VAULT, "security": {**SECURITY, "cipher": "chacha20"}},
        {"revision": DEMO_REVISION, "security": {**SECURITY, "cipher": "chacha20"}},
        (*ACTIVE, "FORMAT_REQUIRED", *SAVE),
    ),
    "rekey_vault": Operation(
        "Vaults",
        "vaults:admin",
        VAULT,
        {"revision": DEMO_REVISION, "credentials": {"password": "example-new-vault-password"}},
        (*ACTIVE, *KEY, *SAVE),
    ),
    "list_groups": Operation(
        "Groups",
        "entries:read",
        [{"id": DEMO_GROUP, "name": "Demo vault", "parentId": None}],
        errors=ACTIVE,
    ),
    "create_group": Operation(
        "Groups",
        "entries:write",
        {"id": "33333333-3333-4333-8333-333333333333", "name": "Shared", "parentId": DEMO_GROUP},
        {"name": "Shared", "parentId": DEMO_GROUP},
        (*ACTIVE, "GROUP_NOT_FOUND", *SAVE),
    ),
    "list_entries": Operation(
        "Entries",
        "entries:read",
        {"items": [ENTRY], "total": 1},
        errors=ACTIVE,
    ),
    "get_entry": Operation("Entries", "entries:read", ENTRY, errors=ENTRY_ACCESS),
    "create_entry": Operation(
        "Entries",
        "entries:write",
        ENTRY,
        {**ENTRY_INPUT, "password": "example-entry-password"},
        (*ACTIVE, "GROUP_NOT_FOUND", *SAVE),
    ),
    "update_entry": Operation(
        "Entries",
        "entries:write",
        {**ENTRY, "tags": ["work"]},
        {"tags": ["work"]},
        (*ENTRY_WRITE, "GROUP_NOT_FOUND"),
    ),
    "trash_entry": Operation(
        "Entries",
        "entries:write",
        {"id": DEMO_ENTRY, "trashed": True},
        errors=ENTRY_WRITE,
    ),
    "reveal_entry_field": Operation(
        "Protected fields",
        "secrets:read",
        {"value": "example-entry-password"},
        errors=ENTRY_ACCESS,
    ),
    "set_entry_field": Operation(
        "Protected fields",
        "entries:write",
        {"name": "recovery"},
        {"value": "example-recovery-code"},
        ENTRY_WRITE,
    ),
    "reveal_custom_field": Operation(
        "Protected fields",
        "secrets:read",
        {"value": "example-recovery-code"},
        errors=(*ENTRY_ACCESS, "FIELD_NOT_FOUND"),
    ),
    "set_entry_totp": Operation(
        "TOTP",
        "entries:write",
        {"id": DEMO_ENTRY, "hasTotp": True},
        {"value": "JBSWY3DPEHPK3PXP"},
        (*ENTRY_WRITE, "INVALID_TOTP"),
    ),
    "generate_entry_totp": Operation(
        "TOTP",
        "secrets:read",
        {"code": "012345", "expiresAt": 1800000030},
        errors=(*ENTRY_ACCESS, "TOTP_NOT_FOUND", "INVALID_TOTP"),
    ),
    "list_entry_attachments": Operation(
        "Attachments",
        "entries:read",
        [{"index": 0, "name": ATTACHMENT["name"]}],
        errors=ENTRY_ACCESS,
    ),
    "add_entry_attachment": Operation(
        "Attachments",
        "entries:write",
        {"name": ATTACHMENT["name"]},
        ATTACHMENT,
        (*ENTRY_WRITE, "INVALID_ATTACHMENT", "ATTACHMENT_LIMIT"),
    ),
    "get_entry_attachment": Operation(
        "Attachments",
        "secrets:read",
        ATTACHMENT,
        errors=(*ENTRY_ACCESS, "ATTACHMENT_NOT_FOUND", "ATTACHMENT_LIMIT"),
    ),
    "new_password": Operation(
        "Passwords",
        "entries:write",
        {"password": "Example9DoNotUse"},
        {
            "length": 16,
            "symbols": False,
        },
    ),
}


def curl_example(method: str, path: str, body: dict | None, authenticated: bool) -> str:
    route = path.format_map(PATH_EXAMPLES)
    query = QUERY_EXAMPLES.get((method, path))
    if query:
        route = f"{route}?{urlencode(query)}"

    command = [f"curl --fail-with-body --silent --show-error --request {method}"]
    if authenticated:
        command.append("--header @<(printf 'Authorization: Bearer %s\\n' \"$KEEPASSBOX_TOKEN\")")
    if body is not None:
        data = shlex.quote(json.dumps(body, indent=2))
        if body.get("revision") == DEMO_REVISION:
            command.append(
                f'--json "$(jq --arg revision "$KEEPASSBOX_REVISION" \'.revision = $revision\' <<< {data})"'
            )
        elif body.get("parentId") == DEMO_GROUP:
            command.append(
                f'--json "$(jq --arg parent "$KEEPASSBOX_GROUP" \'.parentId = $parent\' <<< {data})"'
            )
        else:
            command.append(f"--json {data}")
    elif method in BODY_METHODS:
        command.append("--data ''")
    command.append(f'"${{KEEPASSBOX_URL%/}}{route}"')
    return " \\\n  ".join(command)


def success_response(status: int, example: Any) -> dict:
    return {status: {"content": {JSON: {"example": example}}}}


def problem_responses(codes: tuple[str, ...]) -> dict:
    responses = {}
    for code in codes:
        status, message, advice = ERRORS[code]
        response = responses.setdefault(
            status,
            {
                "model": ProblemResponse,
                "description": HTTPStatus(status).phrase,
                "content": {JSON: {"examples": {}}},
            },
        )
        response["description"] += f"\n\n- `{code}`. {advice}"
        response["content"][JSON]["examples"][code] = {
            "summary": code,
            "description": advice,
            "value": {"code": code, "message": message, "details": {}},
        }
    if unauthorized := responses.get(401):
        unauthorized["headers"] = {
            "WWW-Authenticate": {
                "description": "Bearer authentication challenge.",
                "schema": {"type": "string", "const": "Bearer"},
            },
        }
    return responses


def route_metadata(method: str, path: str, name: str, status: int) -> dict:
    docs = OPERATIONS[name]
    codes = (*COMMON_ERRORS, *docs.errors)
    extra: dict[str, Any] = {
        "x-required-scope": docs.scope,
        "x-codeSamples": [
            {"lang": "curl", "source": curl_example(method, path, docs.request, True)}
        ],
    }
    if method in BODY_METHODS:
        codes += ("BODY_LIMIT",)
    if docs.request is not None:
        extra["requestBody"] = {"content": {JSON: {"example": docs.request}}}
    elif method in BODY_METHODS:
        extra["x-empty-body"] = True
    return {
        "tags": [docs.group],
        "response_description": HTTPStatus(status).phrase,
        "responses": {**success_response(status, docs.response), **problem_responses(codes)},
        "openapi_extra": extra,
    }


def complete_schema(schema: dict) -> dict:
    paths = schema["paths"]
    if "/openapi.json" in paths:
        return schema
    schema_errors = {}
    for status, problem in problem_responses(AUTH_ERRORS).items():
        problem.pop("model")
        problem["content"][JSON]["schema"] = {"$ref": "#/components/schemas/ProblemResponse"}
        schema_errors[str(status)] = problem
    paths.setdefault(
        "/openapi.json",
        {
            "get": {
                "operationId": "get_openapi_document",
                "tags": ["Service"],
                "summary": "Download the live OpenAPI document",
                "description": "Get the contract from the running instance. Any valid bearer token can download it.",
                "security": [{"HTTPBearer": []}],
                "x-codeSamples": [
                    {"lang": "curl", "source": curl_example("GET", "/openapi.json", None, True)}
                ],
                "responses": {
                    "200": {
                        "description": "OpenAPI 3.1 document. The example shows only the top-level shape.",
                        "content": {
                            JSON: {
                                "schema": {"type": "object"},
                                "example": {
                                    "openapi": schema["openapi"],
                                    "info": schema["info"],
                                    "paths": {},
                                },
                            }
                        },
                    },
                    **schema_errors,
                },
            },
        },
    )
    for operations in paths.values():
        for operation in operations.values():
            for parameter in operation.get("parameters", ()):
                if description := parameter["schema"].get("description"):
                    parameter.setdefault("description", description)
    return schema
