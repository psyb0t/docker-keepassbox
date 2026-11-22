import hashlib
import io
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from construct import ConstructError, Container
from lxml.etree import XMLSyntaxError
from pykeepass import PyKeePass, create_database
from pykeepass.exceptions import CredentialsError, HeaderChecksumError, PayloadChecksumError
from pykeepass.kdbx_parsing.kdbx import KDBX
from pykeepass.kdbx_parsing.kdbx4 import kdf_uuids

from .errors import Problem
from .models import AESKdf, Argon2, Security

MIB = 1024**2
MAX_VAULT_BYTES = 32 * MIB
MAX_HEADER_BYTES = MIB
VAR_BYTES, VAR_U32, VAR_U64 = 0x42, 0x04, 0x05
KDBX_ARGON = {"argon2id": "argon2id", "argon2d": "argon2"}
INVALID_DATABASE = (
    ConstructError,
    HeaderChecksumError,
    PayloadChecksumError,
    XMLSyntaxError,
    AttributeError,
    AssertionError,
    KeyError,
    ValueError,
)


def crypto_settings(header) -> Security:
    values = header.dynamic_header
    cipher = values.cipher_id.data
    compression = values.compression_flags.data.compression
    if header.major_version == 3:
        kdf = AESKdf(algorithm="aes-kdf", rounds=values.transform_rounds.data)
    else:
        items = values.kdf_parameters.data.dict
        algorithm = items["$UUID"].value
        if algorithm == kdf_uuids["aeskdf"]:
            kdf = AESKdf(algorithm="aes-kdf", rounds=items["R"].value)
        else:
            names = {kdf_uuids[key]: value for value, key in KDBX_ARGON.items()}
            if algorithm not in names or "A" in items or "K" in items:
                raise Problem("UNSUPPORTED_KDF", "Unsupported vault KDF", 422)
            memory = items["M"].value
            if memory % MIB:
                raise Problem("UNSUPPORTED_KDF", "Vault memory must be a whole MiB", 422)
            kdf = Argon2(
                algorithm=names[algorithm],
                memoryMiB=memory // MIB,
                iterations=items["I"].value,
                parallelism=items["P"].value,
                version=items["V"].value,
            )
    return Security(cipher=cipher, kdf=kdf, compression=compression)


def enforce_memory(security: Security, limit: int):
    if isinstance(security.kdf, Argon2) and security.kdf.memoryMiB > limit:
        raise Problem("KDF_LIMIT", "Vault exceeds the configured KDF memory limit", 422)


def open_vault(file: BinaryIO, password: str | None, key: bytes | None, memory_limit: int):
    try:
        file.seek(0, os.SEEK_END)
        if file.tell() > MAX_VAULT_BYTES:
            raise Problem("FILE_LIMIT", "Vault file exceeds the size limit", 422)
        file.seek(0)
        header = KDBX.subcons[0].parse(file.read(MAX_HEADER_BYTES)).value
        enforce_memory(crypto_settings(header), memory_limit)
        file.seek(0)
        return PyKeePass(file, password=password, keyfile=io.BytesIO(key) if key else None)
    except CredentialsError:
        raise Problem("INVALID_CREDENTIALS", "Vault credentials were rejected", 403) from None
    except INVALID_DATABASE:
        raise Problem("INVALID_VAULT", "Vault format or settings are unsupported", 422) from None


def blank_vault(password: str | None, key: bytes | None):
    seed = io.BytesIO()
    create_database(seed, password=password, keyfile=io.BytesIO(key) if key else None)
    return open_vault(seed, password, key, 1024)


def apply_crypto(vault, settings: Security):
    header = vault.kdbx.header.value
    if header.major_version != 4:
        raise Problem("FORMAT_REQUIRED", "Security changes require a KDBX 4 vault", 409)
    dynamic = header.dynamic_header
    dynamic.cipher_id.data = settings.cipher
    dynamic.compression_flags.data.compression = settings.compression
    kdf = settings.kdf
    if isinstance(kdf, AESKdf):
        fields = (("R", VAR_U64, kdf.rounds),)
        algorithm = "aeskdf"
    else:
        fields = (
            ("I", VAR_U64, kdf.iterations),
            ("M", VAR_U64, kdf.memoryMiB * MIB),
            ("P", VAR_U32, kdf.parallelism),
            ("V", VAR_U32, kdf.version),
        )
        algorithm = KDBX_ARGON[kdf.algorithm]
    values = (
        ("$UUID", VAR_BYTES, kdf_uuids[algorithm]),
        ("S", VAR_BYTES, os.urandom(32)),
        *fields,
    )
    # Construct's KDBX writer uses the lookahead byte to terminate this dictionary.
    dynamic.kdf_parameters.data.dict = Container(
        {
            key: Container(
                key=key,
                type=kind,
                value=value,
                next_byte=values[index + 1][1] if index + 1 < len(values) else 0,
            )
            for index, (key, kind, value) in enumerate(values)
        }
    )


@contextmanager
def open_local(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise OSError("Not a regular file")
        yield file


def revision(file: BinaryIO) -> str:
    file.seek(0)
    if file.read(1) == b"":
        raise Problem("INVALID_VAULT", "The vault file is empty", 422)
    file.seek(0)
    if os.fstat(file.fileno()).st_size > MAX_VAULT_BYTES:
        raise Problem("FILE_LIMIT", "Vault file exceeds the size limit", 422)
    return hashlib.file_digest(file, "sha256").hexdigest()


def verified_save(
    db,
    path: Path,
    password: str | None,
    key: bytes | None,
    memory_limit: int,
    prior: str | None,
) -> str:
    fd, name = tempfile.mkstemp(prefix=".vault-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w+b") as file:
            db.password = password
            db.keyfile = io.BytesIO(key) if key else None
            db.save(file)
            file.flush()
            os.fsync(file.fileno())
            open_vault(file, password, key, memory_limit)
            next_revision = revision(file)
        if prior is None:
            try:
                os.link(temp, path, follow_symlinks=False)
            except FileExistsError:
                raise Problem("VAULT_EXISTS", "Vault already exists", 409) from None
        else:
            with open_local(path) as original:
                if revision(original) != prior:
                    raise Problem("VAULT_CONFLICT", "Vault changed on disk", 409)
                history = path.with_suffix(".previous")
                backup = temp.with_suffix(".backup")
                try:
                    os.link(path, backup, follow_symlinks=False)
                    os.replace(backup, history)
                finally:
                    backup.unlink(missing_ok=True)
            os.replace(temp, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        return next_revision
    finally:
        temp.unlink(missing_ok=True)
