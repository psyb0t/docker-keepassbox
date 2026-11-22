from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    model_validator,
)


def xml_safe(value):
    text = value.get_secret_value() if isinstance(value, SecretStr) else value
    if any(
        not (
            char in "\t\n\r"
            or "\u0020" <= char <= "\ud7ff"
            or "\ue000" <= char <= "\ufffd"
            or "\U00010000" <= char <= "\U0010ffff"
        )
        for char in text
    ):
        raise ValueError("Value contains characters unsupported by KDBX")
    return value


Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
Title = Annotated[str, StringConstraints(min_length=1, max_length=256), AfterValidator(xml_safe)]
Text = Annotated[str, StringConstraints(max_length=8192), AfterValidator(xml_safe)]
Protected = Annotated[SecretStr, Field(max_length=8192), AfterValidator(xml_safe)]
Revision = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Scope = Literal["vaults:create", "entries:read", "entries:write", "secrets:read", "vaults:admin"]
Cipher = Literal["aes256", "chacha20", "twofish"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Argon2(Input):
    algorithm: Literal["argon2id", "argon2d"] = "argon2id"
    memoryMiB: int = Field(default=64, ge=8, le=1024)
    iterations: int = Field(default=3, ge=1, le=100)
    parallelism: int = Field(default=2, ge=1, le=16)
    version: Literal[16, 19] = 19


class AESKdf(Input):
    algorithm: Literal["aes-kdf"]
    rounds: int = Field(ge=1, le=100_000_000)


class Security(Input):
    cipher: Cipher = "aes256"
    kdf: Annotated[Argon2 | AESKdf, Field(discriminator="algorithm")] = Field(
        default_factory=Argon2
    )
    compression: bool = True


class Credentials(Input):
    password: SecretStr | None = Field(default=None, min_length=1, max_length=1024)
    keyFile: Slug | None = None

    @model_validator(mode="after")
    def require_factor(self):
        if self.password is None and self.keyFile is None:
            raise ValueError("Provide a vault password or a key file")
        return self


class VaultCreate(Input):
    id: Slug
    name: Title
    credentials: Credentials
    security: Security = Field(default_factory=Security)


class SecurityChange(Input):
    revision: Revision
    security: Security


class Rekey(Input):
    revision: Revision
    credentials: Credentials


class EntryCreate(Input):
    title: Title
    groupId: UUID | None = None
    username: Text = ""
    password: Protected = SecretStr("")
    url: Text = ""
    notes: Text = ""
    tags: list[Title] = Field(default_factory=list, max_length=32)


class EntryUpdate(Input):
    title: Title | None = None
    groupId: UUID | None = None
    username: Text | None = None
    password: Protected | None = None
    url: Text | None = None
    notes: Text | None = None
    tags: list[Title] | None = Field(default=None, max_length=32)


class GroupCreate(Input):
    name: Title
    parentId: UUID | None = None


class OTPSetup(Input):
    value: SecretStr = Field(min_length=1, max_length=2048)


class FieldUpdate(Input):
    value: Protected


class AttachmentCreate(Input):
    name: Title
    contentBase64: SecretStr = Field(min_length=4, max_length=44_000)


class PasswordOptions(Input):
    length: int = Field(default=32, ge=16, le=256)
    symbols: bool = True
