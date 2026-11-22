import asyncio
import tomllib
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

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
Limit = Annotated[int, Field(ge=1, le=100)]
Offset = Annotated[int, Field(ge=0, le=100_000)]
Search = Annotated[str, Field(max_length=256)]
Index = Annotated[int, Field(ge=0, le=100_000)]
PROJECT_FILE = Path(__file__).resolve().parents[2] / "pyproject.toml"


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

    app = FastAPI(title="KeePassBox", version=version, lifespan=lifespan)

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

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    @app.get("/version")
    async def version_info():
        return {"name": "keepassbox", "version": version}

    def expose(method: str, path: str, status: int = 200):
        def decorate(operation):
            app.add_api_route(
                path,
                operation,
                methods=[method],
                status_code=status,
                operation_id=operation.__name__,
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

    @expose("GET", "/v1/vaults")
    def list_vaults(limit: Limit = 50, offset: Offset = 0) -> dict:
        """List vaults visible to this client."""
        return store.list_vaults(ACTOR.get(), limit, offset)

    @expose("POST", "/v1/vaults", 201)
    def create_vault(body: VaultCreate) -> dict:
        """Create and unlock a new KDBX vault with the specified security settings."""
        return store.create(ACTOR.get(), body)

    @expose("GET", "/v1/vaults/{vault}")
    def get_vault(vault: Slug) -> dict:
        """Return an unlocked vault's format, revision and cryptographic settings."""
        return store.get(ACTOR.get(), vault)

    @expose("POST", "/v1/vaults/{vault}/unlock")
    def unlock_vault(vault: Slug, body: Credentials) -> dict:
        """Unlock a vault with its password or operator-provisioned key-file alias."""
        return store.unlock(ACTOR.get(), vault, body)

    @expose("POST", "/v1/vaults/{vault}/lock")
    def lock_vault(vault: Slug) -> dict:
        """Remove the vault and unlock credentials from the active cache."""
        return store.lock_vault(ACTOR.get(), vault)

    @expose("PATCH", "/v1/vaults/{vault}/security")
    def update_vault_security(vault: Slug, body: SecurityChange) -> dict:
        """Change cipher, KDF and compression on an existing KDBX 4 vault."""
        return store.security(ACTOR.get(), vault, body)

    @expose("POST", "/v1/vaults/{vault}/rekey")
    def rekey_vault(vault: Slug, body: Rekey) -> dict:
        """Replace the vault's password, key file, or both."""
        return store.rekey(ACTOR.get(), vault, body)

    @expose("GET", "/v1/vaults/{vault}/groups")
    def list_groups(vault: Slug) -> list[dict]:
        """List groups and their parent IDs."""
        return store.groups(ACTOR.get(), vault)

    @expose("POST", "/v1/vaults/{vault}/groups", 201)
    def create_group(vault: Slug, body: GroupCreate) -> dict:
        """Create a group beneath the requested parent, or beneath the root."""
        return store.add_group(ACTOR.get(), vault, body)

    @expose("GET", "/v1/vaults/{vault}/entries")
    def list_entries(vault: Slug, q: Search = "", limit: Limit = 50, offset: Offset = 0) -> dict:
        """List metadata, with optional text filtering by title, username and tags."""
        return store.entries(ACTOR.get(), vault, q, limit, offset)

    @expose("GET", "/v1/vaults/{vault}/entries/{entry}")
    def get_entry(vault: Slug, entry: UUID) -> dict:
        """Read an entry's metadata."""
        return store.get_entry(ACTOR.get(), vault, entry)

    @expose("POST", "/v1/vaults/{vault}/entries", 201)
    def create_entry(vault: Slug, body: EntryCreate) -> dict:
        """Create an entry and persist it in the vault."""
        return store.add_entry(ACTOR.get(), vault, body)

    @expose("PATCH", "/v1/vaults/{vault}/entries/{entry}")
    def update_entry(vault: Slug, entry: UUID, body: EntryUpdate) -> dict:
        """Update or move an entry, preserving its previous version in history."""
        return store.update_entry(ACTOR.get(), vault, entry, body)

    @expose("DELETE", "/v1/vaults/{vault}/entries/{entry}")
    def trash_entry(vault: Slug, entry: UUID) -> dict:
        """Move an entry to the vault's recycle bin."""
        return store.trash(ACTOR.get(), vault, entry)

    @expose("POST", "/v1/vaults/{vault}/entries/{entry}/reveal")
    def reveal_entry_field(vault: Slug, entry: UUID, field: Literal["password", "notes"]) -> dict:
        """Reveal one protected field. Return the value only to an authorized caller."""
        return store.reveal(ACTOR.get(), vault, entry, field)

    @expose("PUT", "/v1/vaults/{vault}/entries/{entry}/totp")
    def set_entry_totp(vault: Slug, entry: UUID, body: OTPSetup) -> dict:
        """Store an authenticator setup URI or Base32 seed as a protected field."""
        return store.set_totp(ACTOR.get(), vault, entry, body)

    @expose("POST", "/v1/vaults/{vault}/entries/{entry}/totp/code")
    def generate_entry_totp(vault: Slug, entry: UUID) -> dict:
        """Generate the current TOTP code without returning the seed."""
        return store.totp(ACTOR.get(), vault, entry)

    @expose("POST", "/v1/passwords/generate")
    def new_password(body: PasswordOptions) -> dict:
        """Create a cryptographically random password without writing it to a vault."""
        scope(ACTOR.get(), "entries:write")
        return {"password": generate_password(body)}

    @expose("PUT", "/v1/vaults/{vault}/entries/{entry}/fields/{name}")
    def set_entry_field(vault: Slug, entry: UUID, name: Slug, body: FieldUpdate) -> dict:
        """Write a protected custom field."""
        return store.set_field(ACTOR.get(), vault, entry, name, body)

    @expose("POST", "/v1/vaults/{vault}/entries/{entry}/fields/{name}/reveal")
    def reveal_custom_field(vault: Slug, entry: UUID, name: Slug) -> dict:
        """Reveal one protected custom field."""
        return store.field(ACTOR.get(), vault, entry, name)

    @expose("GET", "/v1/vaults/{vault}/entries/{entry}/attachments")
    def list_entry_attachments(vault: Slug, entry: UUID) -> list[dict]:
        """List attachment names and indexes."""
        return store.attachments(ACTOR.get(), vault, entry)

    @expose("POST", "/v1/vaults/{vault}/entries/{entry}/attachments", 201)
    def add_entry_attachment(vault: Slug, entry: UUID, body: AttachmentCreate) -> dict:
        """Store up to 32 KiB of base64-encoded attachment data in the vault."""
        return store.add_attachment(ACTOR.get(), vault, entry, body)

    @expose("GET", "/v1/vaults/{vault}/entries/{entry}/attachments/{index}")
    def get_entry_attachment(vault: Slug, entry: UUID, index: Index) -> dict:
        """Read the selected attachment as base64."""
        return store.attachment(ACTOR.get(), vault, entry, index)

    app.mount("/mcp", mcp_app)
    return app
