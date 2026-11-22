from pathlib import Path

import pytest
from pykeepass import PyKeePass

from keepassbox import engine
from keepassbox.errors import Problem
from keepassbox.models import AESKdf, Argon2, PasswordOptions, Security
from keepassbox.service import generate_password, otp_from

FIXTURE_PASSWORD = "example-fixture-password"


@pytest.mark.parametrize("cipher", ["aes256", "chacha20", "twofish"])
@pytest.mark.parametrize("compression", [False, True])
@pytest.mark.parametrize(
    "kdf",
    [
        AESKdf(algorithm="aes-kdf", rounds=100_000),
        Argon2(algorithm="argon2id", memoryMiB=8, iterations=2, version=16),
        Argon2(algorithm="argon2id", memoryMiB=8, iterations=2, version=19),
        Argon2(algorithm="argon2d", memoryMiB=8, iterations=2, version=16),
        Argon2(algorithm="argon2d", memoryMiB=8, iterations=2, version=19),
    ],
)
def test_encrypted_round_trip(tmp_path: Path, cipher, compression, kdf):
    path = tmp_path / "probe.kdbx"
    settings = Security(cipher=cipher, compression=compression, kdf=kdf)
    vault = engine.blank_vault(FIXTURE_PASSWORD, None)
    entry = vault.add_entry(vault.root_group, "Probe", "alice", "example-secret")
    entry.save_history()
    entry.add_attachment(vault.add_binary(b"sample attachment"), "sample.txt")
    engine.apply_crypto(vault, settings)
    initial = engine.verified_save(vault, path, FIXTURE_PASSWORD, None, 512, None)
    assert len(initial) == 64
    reopened = PyKeePass(path, password=FIXTURE_PASSWORD)
    assert engine.crypto_settings(reopened.kdbx.header.value) == settings
    saved = reopened.find_entries(uuid=entry.uuid, first=True)
    assert saved.attachments[0].binary == b"sample attachment"
    assert len(saved.history) == 1


def test_rfc_totp_and_invalid_seed():
    otp = otp_from("otpauth://totp/Example?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&digits=8")
    assert otp.at(59) == "94287082"
    with pytest.raises(Problem, match="invalid"):
        otp_from("not a base32 secret!")


def test_password_and_memory_policy():
    password = generate_password(PasswordOptions(length=64, symbols=True))
    assert len(password) == 64
    assert any(char.islower() for char in password)
    assert any(char.isupper() for char in password)
    assert any(char.isdigit() for char in password)
    assert any(not char.isalnum() for char in password)
    with pytest.raises(Problem, match="KDF memory limit"):
        engine.enforce_memory(Security(kdf=Argon2(memoryMiB=512)), 256)


def test_create_and_reopen_512_mib_vault(tmp_path):
    path = tmp_path / "memory.kdbx"
    settings = Security(cipher="chacha20", kdf=Argon2(memoryMiB=512, iterations=2))
    vault = engine.blank_vault(FIXTURE_PASSWORD, None)
    engine.apply_crypto(vault, settings)
    engine.verified_save(vault, path, FIXTURE_PASSWORD, None, 512, None)
    with path.open("rb") as file:
        with pytest.raises(Problem, match="KDF memory limit"):
            engine.open_vault(file, FIXTURE_PASSWORD, None, 511)
        reopened = engine.open_vault(file, FIXTURE_PASSWORD, None, 512)
    assert engine.crypto_settings(reopened.kdbx.header.value) == settings
