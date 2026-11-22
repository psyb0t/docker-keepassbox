from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .models import Security


class ProblemResponse(BaseModel):
    code: str = Field(description="Stable error code for clients.")
    message: str = Field(description="Human-readable summary of the failure.")
    details: dict = Field(description="Reserved for additional error details. Currently empty.")


class Health(BaseModel):
    ok: Literal[True] = Field(description="The process answered the HTTP health check.")


class Version(BaseModel):
    name: str = Field(description="Service name.")
    version: str = Field(description="Version of the running service.")


class Page[T](BaseModel):
    items: list[T] = Field(description="Items in the requested page.")
    total: int = Field(description="Number of matching items before pagination.")


class VaultState(BaseModel):
    id: str = Field(description="Vault ID within this owner.")
    unlocked: bool = Field(description="Whether this owner's vault is open in memory.")


class VaultDetails(VaultState):
    name: str | None = Field(description="Display name, or null if the vault has no name.")
    format: str = Field(description="On-disk KDBX format version.")
    revision: str = Field(
        description="Hash of the current encrypted revision. Use it for security changes and rekey."
    )
    security: Security = Field(description="Current cipher, KDF and compression settings.")


class Group(BaseModel):
    id: UUID = Field(description="Group identifier.")
    name: str | None = Field(description="Display name, or null if unset.")
    parentId: UUID | None = Field(description="Parent group UUID, or null for the root group.")


class EntryMetadata(BaseModel):
    id: UUID = Field(description="Entry identifier.")
    title: str | None = Field(description="Display title, or null if unset.")
    username: str | None = Field(description="Account username, or null if unset.")
    url: str | None = Field(description="Associated service address, or null if unset.")
    tags: list[str] = Field(description="Labels attached to the entry.")
    groupId: UUID = Field(description="UUID of the group containing the entry.")
    hasTotp: bool = Field(description="Whether the entry stores a TOTP setup value.")


class TrashedEntry(BaseModel):
    id: UUID = Field(description="UUID of the entry moved to the recycle bin.")
    trashed: Literal[True] = Field(description="Confirms the move to the recycle bin.")


class ProtectedValue(BaseModel):
    value: str | None = Field(
        description="Plaintext field value, or null for an unset built-in field."
    )


class TotpSetup(BaseModel):
    id: UUID = Field(description="Entry UUID.")
    hasTotp: Literal[True] = Field(description="Confirms that TOTP setup was stored.")


class TotpCode(BaseModel):
    code: str = Field(description="Current TOTP code as a string so leading zeroes are preserved.")
    expiresAt: int = Field(description="Expiration time in Unix seconds.")


class Password(BaseModel):
    password: str = Field(description="Generated password. Copy it before discarding the response.")


class Name(BaseModel):
    name: str = Field(description="Name of the stored field or attachment.")


class AttachmentInfo(Name):
    index: int = Field(description="Zero-based attachment position in the entry.")


class AttachmentData(Name):
    contentBase64: str = Field(description="Attachment bytes encoded using standard Base64.")
