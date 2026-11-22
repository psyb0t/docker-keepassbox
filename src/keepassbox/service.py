import base64
import binascii
import secrets
import string
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from uuid import UUID

from pykeepass.entry import Entry
from pyotp import TOTP, parse_uri

from . import engine
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
    Scope,
    SecurityChange,
    VaultCreate,
)

MAX_KEY_BYTES = 1024 * 1024
SAFE_SYMBOLS = "!@#$%^&*_-+="
PASSWORD_FIELDS = {"password", "notes"}
ATTACHMENT_LIMIT = 32 * 1024


@dataclass
class Active:
    db: object
    revision: str
    expiry: float
    password: str | None
    key: bytes | None


def scope(actor: Client, permission: Scope):
    if permission not in actor.scopes:
        raise Problem("FORBIDDEN", "This token lacks the required permission", 403)


def entry_info(entry) -> dict:
    return {
        "id": str(entry.uuid),
        "title": entry.title,
        "username": entry.username,
        "url": entry.url,
        "tags": entry.tags,
        "groupId": str(entry.group.uuid),
        "hasTotp": bool(entry.otp),
    }


def page(items, limit: int, offset: int) -> dict:
    return {"items": items[offset : offset + limit], "total": len(items)}


def generate_password(options: PasswordOptions) -> str:
    groups = [string.ascii_lowercase, string.ascii_uppercase, string.digits]
    if options.symbols:
        groups.append(SAFE_SYMBOLS)
    alphabet = "".join(groups)
    chars = [secrets.choice(group) for group in groups]
    chars.extend(secrets.choice(alphabet) for _ in range(options.length - len(groups)))
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def otp_from(value: str) -> TOTP:
    try:
        if value.startswith("otpauth://"):
            otp = parse_uri(value)
            if not isinstance(otp, TOTP):
                raise ValueError("Expected TOTP")
        else:
            otp = TOTP("".join(value.split()).upper())
        if not 6 <= otp.digits <= 8 or not 10 <= otp.interval <= 120:
            raise ValueError("Unsupported TOTP parameters")
        if len(otp.byte_secret()) < 10:
            raise ValueError("Seed is too short")
        otp.now()
        return otp
    except (TypeError, ValueError, binascii.Error, OverflowError):
        raise Problem("INVALID_TOTP", "The TOTP setup value is invalid", 422) from None


class Store:
    def __init__(self, config: Config):
        self.config = config
        self.config.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = RLock()
        self.open: dict[tuple[str, str], Active] = {}

    def purge_expired(self):
        with self.lock:
            for key, active in list(self.open.items()):
                if time.monotonic() >= active.expiry:
                    del self.open[key]

    def directory(self, actor: Client) -> Path:
        path = self.config.data / actor.owner
        path.mkdir(mode=0o700, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise Problem("STORE_UNAVAILABLE", "Vault storage is unavailable", 503)
        return path

    def path(self, actor: Client, vault: str) -> Path:
        return self.directory(actor) / f"{vault}.kdbx"

    def credentials(self, actor: Client, request: Credentials):
        password = request.password.get_secret_value() if request.password else None
        value = None
        if request.keyFile:
            key_directory = self.directory(actor) / "keys"
            if key_directory.is_symlink():
                raise Problem("KEY_NOT_FOUND", "Configured key file was not found", 404)
            path = key_directory / f"{request.keyFile}.keyx"
            try:
                with engine.open_local(path) as file:
                    value = file.read(MAX_KEY_BYTES + 1)
            except OSError:
                raise Problem("KEY_NOT_FOUND", "Configured key file was not found", 404) from None
            if not value or len(value) > MAX_KEY_BYTES:
                raise Problem("INVALID_KEY_FILE", "Configured key file has an invalid size", 422)
        return password, value

    def list_vaults(self, actor: Client, limit: int, offset: int):
        scope(actor, "entries:read")
        with self.lock:
            self.purge_expired()
            paths = sorted(self.directory(actor).glob("*.kdbx"))
            return page(
                [
                    {"id": path.stem, "unlocked": (actor.owner, path.stem) in self.open}
                    for path in paths
                    if path.is_file() and not path.is_symlink()
                ],
                limit,
                offset,
            )

    def create(self, actor: Client, request: VaultCreate):
        scope(actor, "vaults:create")
        engine.enforce_memory(request.security, self.config.memory_mib)
        with self.lock:
            path = self.path(actor, request.id)
            if path.exists() or path.is_symlink():
                raise Problem("VAULT_EXISTS", "Vault already exists", 409)
            password, key = self.credentials(actor, request.credentials)
            db = engine.blank_vault(password, key)
            db.database_name = request.name
            db.root_group.name = request.name
            engine.apply_crypto(db, request.security)
            current = engine.verified_save(db, path, password, key, self.config.memory_mib, None)
            self.remember(actor, request.id, db, current, password, key)
            return self.vault_info(request.id, self.open[actor.owner, request.id])

    def remember(self, actor: Client, vault: str, db, revision: str, password, key):
        self.open[actor.owner, vault] = Active(
            db,
            revision,
            time.monotonic() + self.config.idle_seconds,
            password,
            key,
        )

    def unlock(self, actor: Client, vault: str, request: Credentials):
        scope(actor, "entries:read")
        with self.lock:
            self.purge_expired()
            password, key = self.credentials(actor, request)
            try:
                with engine.open_local(self.path(actor, vault)) as file:
                    current = engine.revision(file)
                    db = engine.open_vault(file, password, key, self.config.memory_mib)
            except FileNotFoundError:
                raise Problem("VAULT_NOT_FOUND", "Vault was not found", 404) from None
            self.remember(actor, vault, db, current, password, key)
            return self.vault_info(vault, self.open[actor.owner, vault])

    def lock_vault(self, actor: Client, vault: str):
        scope(actor, "entries:read")
        with self.lock:
            self.open.pop((actor.owner, vault), None)
            return {"id": vault, "unlocked": False}

    @contextmanager
    def active(self, actor: Client, vault: str, permission: Scope):
        scope(actor, permission)
        with self.lock:
            self.purge_expired()
            active = self.open.get((actor.owner, vault))
            if active is None:
                if not self.path(actor, vault).is_file():
                    raise Problem("VAULT_NOT_FOUND", "Vault was not found", 404)
                raise Problem("VAULT_LOCKED", "Unlock the vault first", 423)
            active.expiry = time.monotonic() + self.config.idle_seconds
            yield active

    @staticmethod
    def vault_info(vault: str, active: Active):
        header = active.db.kdbx.header.value
        return {
            "id": vault,
            "name": active.db.database_name,
            "format": ".".join(map(str, active.db.version)),
            "revision": active.revision,
            "unlocked": True,
            "security": engine.crypto_settings(header).model_dump(),
        }

    def get(self, actor: Client, vault: str):
        with self.active(actor, vault, "entries:read") as active:
            return self.vault_info(vault, active)

    def save(self, actor: Client, vault: str, active: Active):
        try:
            active.revision = engine.verified_save(
                active.db,
                self.path(actor, vault),
                active.password,
                active.key,
                self.config.memory_mib,
                active.revision,
            )
        except (Problem, OSError, ValueError):
            self.open.pop((actor.owner, vault), None)
            raise

    @staticmethod
    def check_revision(expected: str, active: Active):
        if expected != active.revision:
            raise Problem("VAULT_CONFLICT", "Vault revision has changed", 409)

    def security(self, actor: Client, vault: str, request: SecurityChange):
        with self.active(actor, vault, "vaults:admin") as active:
            self.check_revision(request.revision, active)
            engine.enforce_memory(request.security, self.config.memory_mib)
            engine.apply_crypto(active.db, request.security)
            self.save(actor, vault, active)
            return self.vault_info(vault, active)

    def rekey(self, actor: Client, vault: str, request: Rekey):
        with self.active(actor, vault, "vaults:admin") as active:
            self.check_revision(request.revision, active)
            active.password, active.key = self.credentials(actor, request.credentials)
            self.save(actor, vault, active)
            return self.vault_info(vault, active)

    @staticmethod
    def entry(db, entry_id: UUID):
        entry = db.find_entries(uuid=entry_id, first=True)
        if entry is None:
            raise Problem("ENTRY_NOT_FOUND", "Entry was not found", 404)
        return entry

    @staticmethod
    def group(db, group_id: UUID | None):
        group = db.root_group if group_id is None else db.find_groups(uuid=group_id, first=True)
        if group is None:
            raise Problem("GROUP_NOT_FOUND", "Group was not found", 404)
        return group

    @staticmethod
    def in_trash(entry, recycle_id):
        if recycle_id is None:
            return False
        group = entry.group
        while group is not None:
            if group.uuid == recycle_id:
                return True
            group = group.parentgroup
        return False

    def entries(self, actor: Client, vault: str, query: str, limit: int, offset: int):
        with self.active(actor, vault, "entries:read") as active:
            needle = query.casefold()
            recycle = active.db.recyclebin_group
            recycle_id = recycle.uuid if recycle else None
            result = [
                entry_info(entry)
                for entry in active.db.entries
                if not entry.is_a_history_entry
                and not self.in_trash(entry, recycle_id)
                and (
                    not needle
                    or needle in (entry.title or "").casefold()
                    or needle in (entry.username or "").casefold()
                    or any(needle in tag.casefold() for tag in entry.tags)
                )
            ]
            return page(result, limit, offset)

    def get_entry(self, actor: Client, vault: str, entry: UUID):
        with self.active(actor, vault, "entries:read") as active:
            return entry_info(self.entry(active.db, entry))

    def add_entry(self, actor: Client, vault: str, request: EntryCreate):
        with self.active(actor, vault, "entries:write") as active:
            group = self.group(active.db, request.groupId)
            entry = Entry(
                title=request.title,
                username=request.username,
                password=request.password.get_secret_value(),
                url=request.url,
                notes=request.notes,
                tags=request.tags,
                kp=active.db,
            )
            group.append(entry)
            self.save(actor, vault, active)
            return entry_info(entry)

    def update_entry(self, actor: Client, vault: str, entry_id: UUID, request: EntryUpdate):
        with self.active(actor, vault, "entries:write") as active:
            entry = self.entry(active.db, entry_id)
            if request.groupId is not None:
                target = self.group(active.db, request.groupId)
            else:
                target = None
            entry.save_history()
            for key, value in request:
                if value is None or key == "groupId":
                    continue
                setattr(entry, key, value.get_secret_value() if key == "password" else value)
            if target is not None:
                active.db.move_entry(entry, target)
            self.save(actor, vault, active)
            return entry_info(entry)

    def trash(self, actor: Client, vault: str, entry_id: UUID):
        with self.active(actor, vault, "entries:write") as active:
            active.db.trash_entry(self.entry(active.db, entry_id))
            self.save(actor, vault, active)
            return {"id": str(entry_id), "trashed": True}

    def reveal(self, actor: Client, vault: str, entry_id: UUID, field: str):
        if field not in PASSWORD_FIELDS:
            raise Problem("INVALID_FIELD", "That field cannot be revealed", 422)
        with self.active(actor, vault, "secrets:read") as active:
            return {"value": getattr(self.entry(active.db, entry_id), field)}

    def groups(self, actor: Client, vault: str):
        with self.active(actor, vault, "entries:read") as active:
            return [
                {
                    "id": str(group.uuid),
                    "name": group.name,
                    "parentId": str(group.parentgroup.uuid) if group.parentgroup else None,
                }
                for group in active.db.groups
            ]

    def add_group(self, actor: Client, vault: str, request: GroupCreate):
        with self.active(actor, vault, "entries:write") as active:
            parent = self.group(active.db, request.parentId)
            group = active.db.add_group(parent, request.name)
            self.save(actor, vault, active)
            return {"id": str(group.uuid), "name": group.name, "parentId": str(parent.uuid)}

    def set_totp(self, actor: Client, vault: str, entry_id: UUID, request: OTPSetup):
        value = request.value.get_secret_value()
        otp = otp_from(value)
        with self.active(actor, vault, "entries:write") as active:
            entry = self.entry(active.db, entry_id)
            entry.save_history()
            entry.otp = otp.provisioning_uri(name=entry.title)
            self.save(actor, vault, active)
            return {"id": str(entry_id), "hasTotp": True}

    def totp(self, actor: Client, vault: str, entry_id: UUID):
        with self.active(actor, vault, "secrets:read") as active:
            entry = self.entry(active.db, entry_id)
            if not entry.otp:
                raise Problem("TOTP_NOT_FOUND", "Entry has no TOTP configuration", 404)
            otp = otp_from(entry.otp)
            now = int(time.time())
            return {"code": otp.at(now), "expiresAt": now - now % otp.interval + otp.interval}

    def field(self, actor: Client, vault: str, entry_id: UUID, name: str):
        with self.active(actor, vault, "secrets:read") as active:
            value = self.entry(active.db, entry_id).get_custom_property(f"custom:{name}")
            if value is None:
                raise Problem("FIELD_NOT_FOUND", "Custom field was not found", 404)
            return {"value": value}

    def set_field(self, actor: Client, vault: str, entry_id: UUID, name: str, request: FieldUpdate):
        with self.active(actor, vault, "entries:write") as active:
            entry = self.entry(active.db, entry_id)
            entry.save_history()
            entry.set_custom_property(
                f"custom:{name}", request.value.get_secret_value(), protect=True
            )
            self.save(actor, vault, active)
            return {"name": name}

    def attachments(self, actor: Client, vault: str, entry_id: UUID):
        with self.active(actor, vault, "entries:read") as active:
            entry = self.entry(active.db, entry_id)
            return [
                {"index": index, "name": item.filename}
                for index, item in enumerate(entry.attachments)
            ]

    def attachment(self, actor: Client, vault: str, entry_id: UUID, index: int):
        with self.active(actor, vault, "secrets:read") as active:
            items = self.entry(active.db, entry_id).attachments
            if index >= len(items):
                raise Problem("ATTACHMENT_NOT_FOUND", "Attachment was not found", 404)
            item = items[index]
            content = item.binary
            if len(content) > ATTACHMENT_LIMIT:
                raise Problem("ATTACHMENT_LIMIT", "Attachment exceeds inline transfer limit", 422)
            return {
                "name": item.filename,
                "contentBase64": base64.b64encode(content).decode("ascii"),
            }

    def add_attachment(self, actor: Client, vault: str, entry_id: UUID, request: AttachmentCreate):
        with self.active(actor, vault, "entries:write") as active:
            try:
                content = base64.b64decode(request.contentBase64.get_secret_value(), validate=True)
            except (ValueError, binascii.Error):
                raise Problem(
                    "INVALID_ATTACHMENT", "Attachment must be valid base64", 422
                ) from None
            if not content or len(content) > ATTACHMENT_LIMIT:
                raise Problem("ATTACHMENT_LIMIT", "Attachment exceeds inline transfer limit", 422)
            entry = self.entry(active.db, entry_id)
            entry.save_history()
            entry.add_attachment(active.db.add_binary(content), request.name)
            self.save(actor, vault, active)
            return {"name": request.name}
