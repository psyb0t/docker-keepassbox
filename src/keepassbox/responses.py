from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from .models import Security


class ProblemResponse(BaseModel):
    code: str
    message: str
    details: dict


class Health(BaseModel):
    ok: Literal[True]


class Version(BaseModel):
    name: str
    version: str


class Page[T](BaseModel):
    items: list[T]
    total: int


class VaultState(BaseModel):
    id: str
    unlocked: bool


class VaultDetails(VaultState):
    name: str | None
    format: str
    revision: str
    security: Security


class Group(BaseModel):
    id: UUID
    name: str | None
    parentId: UUID | None


class EntryMetadata(BaseModel):
    id: UUID
    title: str | None
    username: str | None
    url: str | None
    tags: list[str]
    groupId: UUID
    hasTotp: bool


class TrashedEntry(BaseModel):
    id: UUID
    trashed: Literal[True]


class ProtectedValue(BaseModel):
    value: str | None


class TotpSetup(BaseModel):
    id: UUID
    hasTotp: Literal[True]


class TotpCode(BaseModel):
    code: str
    expiresAt: int


class Password(BaseModel):
    password: str


class Name(BaseModel):
    name: str


class AttachmentInfo(Name):
    index: int


class AttachmentData(Name):
    contentBase64: str
