import os
from dataclasses import dataclass
from hmac import compare_digest
from pathlib import Path

from pydantic import Field, SecretStr, ValidationError

from .models import Input, Scope, Slug

ACCESS_FILE = Path("/run/secrets/keepassbox_access")
DATA_DIR = Path("/data")


class Client(Input):
    owner: Slug
    token: SecretStr = Field(min_length=32, max_length=256)
    scopes: frozenset[Scope] = Field(min_length=1)


class Access(Input):
    clients: list[Client] = Field(min_length=1, max_length=128)


@dataclass(frozen=True)
class Config:
    data: Path
    access: Access
    idle_seconds: int = 600
    memory_mib: int = 512

    @classmethod
    def from_env(cls):
        try:
            source = Path(os.getenv("KEEPASSBOX_ACCESS_FILE", str(ACCESS_FILE)))
            if source.stat().st_size > 64 * 1024:
                raise ValueError("Access configuration exceeds its size limit")
            access = Access.model_validate_json(source.read_bytes())
            tokens = [client.token.get_secret_value() for client in access.clients]
            if len(tokens) != len(set(tokens)) or any(not token.isascii() for token in tokens):
                raise ValueError("Access tokens must be unique ASCII strings")
            idle = int(os.getenv("KEEPASSBOX_IDLE_SECONDS", "600"))
            memory = int(os.getenv("KEEPASSBOX_KDF_MAX_MIB", "512"))
            if not 5 <= idle <= 86400 or not 64 <= memory <= 1024:
                raise ValueError("Invalid vault resource settings")
        except (OSError, ValidationError, ValueError):
            raise RuntimeError("Missing or invalid KeePassBox configuration") from None
        return cls(Path(os.getenv("KEEPASSBOX_DATA_DIR", str(DATA_DIR))), access, idle, memory)

    def authenticate(self, authorization: str) -> Client | None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.isascii() or not 32 <= len(token) <= 256:
            return None
        match = None
        for client in self.access.clients:
            if compare_digest(client.token.get_secret_value(), token):
                match = client
        return match
