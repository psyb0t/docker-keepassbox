import asyncio
import tomllib
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from . import api_docs, responses
from .config import Client, Config
from .errors import Problem
from .models import (
    AttachmentCreate,
    Credentials,
    EntryCreate,
    EntryUpdate,
    FieldUpdate,
    GroupCreate,
    OTPSetup,
    PasswordOptions,
    Rekey,
    SecurityChange,
    Slug,
    VaultCreate,
)
from .service import Store, generate_password, scope

MAX_REQUEST = 64 * 1024
ACTOR: ContextVar[Client] = ContextVar("actor")
Limit = Annotated[
    int, Field(ge=1, le=100, description="Maximum number of items to return.", examples=[10])
]
Offset = Annotated[
    int, Field(ge=0, le=100_000, description="Number of matching items to skip.", examples=[0])
]
Search = Annotated[
    str,
    Field(
        max_length=256,
        description="Case-insensitive substring search across titles, usernames, and tags. Leave empty to list all entries.",
        examples=["email"],
    ),
]
Index = Annotated[
    int,
    Field(
        ge=0,
        le=100_000,
        description="Zero-based index from this entry's attachment list.",
        examples=[0],
    ),
]
VaultID = Annotated[
    Slug, Field(description="Vault ID from the vault list.", examples=[api_docs.DEMO_VAULT])
]
EntryID = Annotated[
    UUID, Field(description="Entry UUID from the entry list.", examples=[api_docs.DEMO_ENTRY])
]
FieldName = Annotated[
    Slug,
    Field(
        description="Custom field name. Omit the internal custom: prefix.", examples=["recovery"]
    ),
]
RevealField = Annotated[
    Literal["password", "notes"],
    Field(description="Built-in field to reveal.", examples=["password"]),
]
PROJECT_FILE = Path(__file__).resolve().parents[2] / "pyproject.toml"
REST_BEARER = HTTPBearer(auto_error=False)


def failure(code: str, message: str, status: int, headers=None):
    return JSONResponse(
        {"code": code, "message": message, "details": {}},
        status_code=status,
        headers=headers,
    )


async def expire(store: Store):
    while True:
        await asyncio.sleep(5)
        await asyncio.to_thread(store.purge_expired)


def create_app(config: Config | None = None):
    config = config or Config.from_env()
    store = Store(config)
    version = tomllib.loads(PROJECT_FILE.read_text(encoding="utf-8"))["project"]["version"]
    mcp = FastMCP(
        "KeePassBox",
        instructions="Manage authorized KeePass vaults and entries.",
        version=version,
        mask_error_details=True,
    )
    mcp_app = mcp.http_app(path="/", stateless_http=True)

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp_app.lifespan(mcp_app):
            purge = asyncio.create_task(expire(store))
            try:
                yield
            finally:
                purge.cancel()
                await asyncio.gather(purge, return_exceptions=True)
                store.open.clear()

    app = FastAPI(
        title="KeePassBox",
        description="Manage KeePass vaults, entries, attachments, and TOTP over REST.",
        version=version,
        lifespan=lifespan,
        openapi_tags=[{"name": tag} for tag in api_docs.TAGS],
    )
    generate_schema = app.openapi

    def openapi():
        return api_docs.complete_schema(generate_schema())

    app.openapi = openapi

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        path = request.url.path
        if path not in {"/docs", "/openapi.json", "/redoc"} and not (
            path.startswith(("/v1/", "/mcp/")) or path == "/mcp"
        ):
            return await call_next(request)
        actor = config.authenticate(request.headers.get("authorization", ""))
        if actor is None:
            return failure(
                "UNAUTHORIZED",
                "Bearer token required",
                401,
                {"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )
        if request.headers.get("origin") is not None:
            return failure("FORBIDDEN", "Browser cross-origin access is disabled", 403)
        if request.method in {"POST", "PUT", "PATCH"}:
            size = request.headers.get("content-length", "")
            if (
                not size.isascii()
                or not size.isdecimal()
                or len(size) > 8
                or int(size) > MAX_REQUEST
            ):
                return failure("BODY_LIMIT", "Invalid or oversized request body", 413)
        if path == "/mcp":
            request.scope["path"] = "/mcp/"
            request.scope["raw_path"] = b"/mcp/"
        token = ACTOR.set(actor)
        try:
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        finally:
            ACTOR.reset(token)

    @app.exception_handler(Problem)
    async def app_problem(_request, error):
        return failure(error.code, str(error), error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _error):
        return failure("INVALID_REQUEST", "Request validation failed", 422)

    @app.exception_handler(OSError)
    async def storage_error(_request, _error):
        return failure("STORE_UNAVAILABLE", "Vault storage is unavailable", 503)

    @app.get(
        "/healthz",
        tags=["Service"],
        response_model=responses.Health,
        responses=api_docs.success_response(200, {"ok": True}),
        openapi_extra={
            "x-codeSamples": [
                {"lang": "curl", "source": api_docs.curl_example("GET", "/healthz", None, False)}
            ]
        },
    )
    async def health():
        """Check whether the HTTP service is responding. This check does not open a vault."""
        return {"ok": True}

    @app.get(
        "/version",
        tags=["Service"],
        response_model=responses.Version,
        responses=api_docs.success_response(200, {"name": "keepassbox", "version": version}),
        openapi_extra={
            "x-codeSamples": [
                {"lang": "curl", "source": api_docs.curl_example("GET", "/version", None, False)}
            ]
        },
    )
    async def version_info():
        """Get the version running on this instance."""
        return {"name": "keepassbox", "version": version}

    def expose(method: str, path: str, response_model, status: int = 200):
        def decorate(operation):
            metadata = api_docs.route_metadata(method, path, operation.__name__, status)
            details = metadata["openapi_extra"]
            description = (
                f"{operation.__doc__}\n\nRequired token scope: `{details['x-required-scope']}`."
            )
            if details.get("x-empty-body"):
                description += (
                    "\n\nSend an empty body with `Content-Length: 0`. `curl --data ''` sets it."
                )
            elif method in api_docs.BODY_METHODS:
                description += "\n\nSend JSON with a `Content-Length` of at most 64 KiB."
            app.add_api_route(
                path,
                operation,
                methods=[method],
                status_code=status,
                operation_id=operation.__name__,
                response_model=response_model,
                description=description,
                dependencies=[Depends(REST_BEARER)],
                **metadata,
            )

            @wraps(operation)
            def tool(*args, **kwargs):
                try:
                    return operation(*args, **kwargs)
                except Problem as error:
                    raise ToolError(f"{error.code}: {error}") from None
                except OSError:
                    raise ToolError("STORE_UNAVAILABLE: Vault storage is unavailable") from None

            mcp.tool(tool)
            return operation

        return decorate

    @expose("GET", "/v1/vaults", responses.Page[responses.VaultState])
    def list_vaults(limit: Limit = 50, offset: Offset = 0) -> dict:
        """List vaults visible to this client."""
        return store.list_vaults(ACTOR.get(), limit, offset)

    @expose("POST", "/v1/vaults", responses.VaultDetails, 201)
    def create_vault(body: VaultCreate) -> dict:
        """Create and unlock a new KDBX vault with the specified security settings."""
        return store.create(ACTOR.get(), body)

    @expose("GET", "/v1/vaults/{vault}", responses.VaultDetails)
    def get_vault(vault: VaultID) -> dict:
        """Return an unlocked vault's format, revision and cryptographic settings."""
        return store.get(ACTOR.get(), vault)

    @expose("POST", "/v1/vaults/{vault}/unlock", responses.VaultDetails)
    def unlock_vault(vault: VaultID, body: Credentials) -> dict:
        """Unlock a vault with its password or operator-provisioned key-file alias."""
        return store.unlock(ACTOR.get(), vault, body)

    @expose("POST", "/v1/vaults/{vault}/lock", responses.VaultState)
    def lock_vault(vault: VaultID) -> dict:
        """Remove the vault and unlock credentials from the active cache."""
        return store.lock_vault(ACTOR.get(), vault)

    @expose("PATCH", "/v1/vaults/{vault}/security", responses.VaultDetails)
    def update_vault_security(vault: VaultID, body: SecurityChange) -> dict:
        """Change cipher, KDF and compression on an existing KDBX 4 vault."""
        return store.security(ACTOR.get(), vault, body)

    @expose("POST", "/v1/vaults/{vault}/rekey", responses.VaultDetails)
    def rekey_vault(vault: VaultID, body: Rekey) -> dict:
        """Replace the complete credential set. Use the current revision and include each factor you want to keep."""
        return store.rekey(ACTOR.get(), vault, body)

    @expose("GET", "/v1/vaults/{vault}/groups", list[responses.Group])
    def list_groups(vault: VaultID) -> list[dict]:
        """List groups and their parent IDs."""
        return store.groups(ACTOR.get(), vault)

    @expose("POST", "/v1/vaults/{vault}/groups", responses.Group, 201)
    def create_group(vault: VaultID, body: GroupCreate) -> dict:
        """Create a group beneath the requested parent, or beneath the root."""
        return store.add_group(ACTOR.get(), vault, body)

    @expose("GET", "/v1/vaults/{vault}/entries", responses.Page[responses.EntryMetadata])
    def list_entries(vault: VaultID, q: Search = "", limit: Limit = 50, offset: Offset = 0) -> dict:
        """List matching entry metadata in an unlocked vault. The result excludes recycled entries and does not contain secret values. The total counts matches before pagination."""
        return store.entries(ACTOR.get(), vault, q, limit, offset)

    @expose("GET", "/v1/vaults/{vault}/entries/{entry}", responses.EntryMetadata)
    def get_entry(vault: VaultID, entry: EntryID) -> dict:
        """Read an entry's metadata."""
        return store.get_entry(ACTOR.get(), vault, entry)

    @expose("POST", "/v1/vaults/{vault}/entries", responses.EntryMetadata, 201)
    def create_entry(vault: VaultID, body: EntryCreate) -> dict:
        """Create an entry and persist it in the vault."""
        return store.add_entry(ACTOR.get(), vault, body)

    @expose("PATCH", "/v1/vaults/{vault}/entries/{entry}", responses.EntryMetadata)
    def update_entry(vault: VaultID, entry: EntryID, body: EntryUpdate) -> dict:
        """Update or move an entry while preserving its previous version in history. Omitted and null fields keep their current values."""
        return store.update_entry(ACTOR.get(), vault, entry, body)

    @expose("DELETE", "/v1/vaults/{vault}/entries/{entry}", responses.TrashedEntry)
    def trash_entry(vault: VaultID, entry: EntryID) -> dict:
        """Move an entry to the vault's recycle bin."""
        return store.trash(ACTOR.get(), vault, entry)

    @expose("POST", "/v1/vaults/{vault}/entries/{entry}/reveal", responses.ProtectedValue)
    def reveal_entry_field(vault: VaultID, entry: EntryID, field: RevealField) -> dict:
        """Reveal one protected field. Return the value only to an authorized caller."""
        return store.reveal(ACTOR.get(), vault, entry, field)

    @expose("PUT", "/v1/vaults/{vault}/entries/{entry}/totp", responses.TotpSetup)
    def set_entry_totp(vault: VaultID, entry: EntryID, body: OTPSetup) -> dict:
        """Store an authenticator setup URI or Base32 seed as a protected field."""
        return store.set_totp(ACTOR.get(), vault, entry, body)

    @expose("POST", "/v1/vaults/{vault}/entries/{entry}/totp/code", responses.TotpCode)
    def generate_entry_totp(vault: VaultID, entry: EntryID) -> dict:
        """Generate the current TOTP code without returning the seed."""
        return store.totp(ACTOR.get(), vault, entry)

    @expose("POST", "/v1/passwords/generate", responses.Password)
    def new_password(body: PasswordOptions) -> dict:
        """Create a cryptographically random password without writing it to a vault."""
        scope(ACTOR.get(), "entries:write")
        return {"password": generate_password(body)}

    @expose("PUT", "/v1/vaults/{vault}/entries/{entry}/fields/{name}", responses.Name)
    def set_entry_field(vault: VaultID, entry: EntryID, name: FieldName, body: FieldUpdate) -> dict:
        """Write a protected custom field."""
        return store.set_field(ACTOR.get(), vault, entry, name, body)

    @expose(
        "POST", "/v1/vaults/{vault}/entries/{entry}/fields/{name}/reveal", responses.ProtectedValue
    )
    def reveal_custom_field(vault: VaultID, entry: EntryID, name: FieldName) -> dict:
        """Reveal one protected custom field."""
        return store.field(ACTOR.get(), vault, entry, name)

    @expose("GET", "/v1/vaults/{vault}/entries/{entry}/attachments", list[responses.AttachmentInfo])
    def list_entry_attachments(vault: VaultID, entry: EntryID) -> list[dict]:
        """List attachment names and indexes."""
        return store.attachments(ACTOR.get(), vault, entry)

    @expose("POST", "/v1/vaults/{vault}/entries/{entry}/attachments", responses.Name, 201)
    def add_entry_attachment(vault: VaultID, entry: EntryID, body: AttachmentCreate) -> dict:
        """Store up to 32 KiB of base64-encoded attachment data in the vault."""
        return store.add_attachment(ACTOR.get(), vault, entry, body)

    @expose(
        "GET", "/v1/vaults/{vault}/entries/{entry}/attachments/{index}", responses.AttachmentData
    )
    def get_entry_attachment(vault: VaultID, entry: EntryID, index: Index) -> dict:
        """Read the selected attachment as base64."""
        return store.attachment(ACTOR.get(), vault, entry, index)

    app.mount("/mcp", mcp_app)
    return app
