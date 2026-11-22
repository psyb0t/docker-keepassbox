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
    algorithm: Literal["argon2id", "argon2d"] = Field(
        default="argon2id", description="Argon2 variant."
    )
    memoryMiB: int = Field(
        default=64, ge=8, le=1024, description="Memory in MiB. The server can impose a lower cap."
    )
    iterations: int = Field(default=3, ge=1, le=100, description="Number of Argon2 passes.")
    parallelism: int = Field(default=2, ge=1, le=16, description="Number of Argon2 lanes.")
    version: Literal[16, 19] = Field(
        default=19, description="Argon2 version. 16 is 1.0 and 19 is 1.3."
    )


class AESKdf(Input):
    algorithm: Literal["aes-kdf"] = Field(description="Selects AES-KDF.")
    rounds: int = Field(ge=1, le=100_000_000, description="Number of AES transformation rounds.")


class Security(Input):
    cipher: Cipher = Field(default="aes256", description="Cipher used to encrypt the KDBX file.")
    kdf: Annotated[Argon2 | AESKdf, Field(discriminator="algorithm")] = Field(
        default_factory=Argon2,
        description="Key derivation settings. Omit for the Argon2id defaults.",
        json_schema_extra={"default": Argon2().model_dump()},
    )
    compression: bool = Field(
        default=True, description="Compress the vault payload before encryption."
    )


class Credentials(Input):
    model_config = ConfigDict(
        json_schema_extra={
            "description": "Supply at least one non-null credential factor.",
            "anyOf": [
                {"required": [factor], "properties": {factor: {"type": "string"}}}
                for factor in ("password", "keyFile")
            ],
        }
    )
    password: SecretStr | None = Field(
        default=None,
        min_length=1,
        max_length=1024,
        description="Vault password. Supply a password, a key file alias, or both.",
    )
    keyFile: Slug | None = Field(
        default=None,
        description="Alias of a key file installed for this owner. Send the alias without the .keyx extension.",
    )

    @model_validator(mode="after")
    def require_factor(self):
        if self.password is None and self.keyFile is None:
            raise ValueError("Provide a vault password or a key file")
        return self


class VaultCreate(Input):
    id: Slug = Field(description="New vault ID. It must be unused within this owner.")
    name: Title = Field(description="Display name for the new vault.")
    credentials: Credentials = Field(description="Credentials used to encrypt the new vault.")
    security: Security = Field(
        default_factory=Security,
        description="Cipher, key derivation and compression settings.",
        json_schema_extra={"default": Security().model_dump()},
    )


class SecurityChange(Input):
    revision: Revision = Field(description="Current revision from the vault details response.")
    security: Security = Field(
        description="Complete security settings. Omitted fields take their defaults."
    )


class Rekey(Input):
    revision: Revision = Field(description="Current revision from the vault details response.")
    credentials: Credentials = Field(
        description="Complete replacement credential set. Resend a factor to keep it."
    )


class EntryCreate(Input):
    title: Title = Field(description="Display title of the entry.")
    groupId: UUID | None = Field(
        default=None, description="Group UUID. Omit to create in the root group."
    )
    username: Text = Field(default="", description="Account username.")
    password: Protected = Field(
        default=SecretStr(""), description="Account password stored in the vault."
    )
    url: Text = Field(default="", description="Service address associated with the entry.")
    notes: Text = Field(default="", description="Notes stored with the entry.")
    tags: list[Title] = Field(
        default_factory=list,
        max_length=32,
        description="Labels used to organize and search entries.",
        json_schema_extra={"default": []},
    )


class EntryUpdate(Input):
    title: Title | None = Field(default=None, description="New display title.")
    groupId: UUID | None = Field(
        default=None, description="Destination group UUID from the group list."
    )
    username: Text | None = Field(
        default=None, description="New account username. Use an empty string to clear it."
    )
    password: Protected | None = Field(
        default=None, description="New account password. Use an empty string to clear it."
    )
    url: Text | None = Field(
        default=None, description="New service address. Use an empty string to clear it."
    )
    notes: Text | None = Field(
        default=None, description="New notes. Use an empty string to clear them."
    )
    tags: list[Title] | None = Field(
        default=None,
        max_length=32,
        description="Replacement labels. Use an empty array to clear them.",
    )


class GroupCreate(Input):
    name: Title = Field(description="Display name of the new group.")
    parentId: UUID | None = Field(
        default=None, description="Parent group UUID. Omit to create under the root."
    )


class OTPSetup(Input):
    value: SecretStr = Field(
        min_length=1,
        max_length=2048,
        description="Base32 seed or otpauth TOTP URI. The seed must decode to at least 10 bytes. The code must use 6 to 8 digits and a period of 10 to 120 seconds.",
    )


class FieldUpdate(Input):
    value: Protected = Field(description="Value stored as a protected custom field.")


class AttachmentCreate(Input):
    name: Title = Field(description="File name displayed in the entry.")
    contentBase64: SecretStr = Field(
        min_length=4,
        max_length=44_000,
        description="Standard Base64. Decoded data must be nonempty and at most 32 KiB.",
    )


class PasswordOptions(Input):
    length: int = Field(
        default=32, ge=16, le=256, description="Number of characters in the generated password."
    )
    symbols: bool = Field(
        default=True, description="Include punctuation along with letters and digits."
    )
