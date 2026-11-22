from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pykeepass import PyKeePass

from keepassbox.config import Access, Client, Config
from keepassbox.server import create_app

TOKEN = "example-owner-token-do-not-use-in-production"
READER = "example-reader-token-do-not-use-in-production"
OTHER = "example-other-token-do-not-use-in-production"
PASSWORD = "example-fixture-password"
ROTATED = "example-rotated-password"
ENTRY_PASSWORD = "example-stored-password"
SCOPES = {"vaults:create", "entries:read", "entries:write", "secrets:read", "vaults:admin"}
VAULT = "/v1/vaults/demo"


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(tmp_path: Path):
    access = Access(
        clients=[
            Client(owner="one", token=TOKEN, scopes=SCOPES),
            Client(owner="one", token=READER, scopes={"entries:read"}),
            Client(owner="two", token=OTHER, scopes=SCOPES),
        ]
    )
    with TestClient(create_app(Config(tmp_path, access))) as http:
        yield http


def create(client, vault="demo"):
    response = client.post(
        "/v1/vaults",
        headers=auth(),
        json={
            "id": vault,
            "name": "Demo vault",
            "credentials": {"password": PASSWORD},
            "security": {"cipher": "aes256", "kdf": {"algorithm": "aes-kdf", "rounds": 100_000}},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_entry(client, title="Example", group=None):
    response = client.post(
        f"{VAULT}/entries",
        headers=auth(),
        json={
            "title": title,
            "groupId": group,
            "username": "alice",
            "password": ENTRY_PASSWORD,
            "notes": "example private note",
            "tags": ["test"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_auth_isolation_and_validation(client):
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/v1/vaults").status_code == 401
    assert client.get("/v1/vaults", headers=auth("forged-token")).status_code == 401
    assert (
        client.get("/v1/vaults", headers={**auth(), "Origin": "https://example.com"}).status_code
        == 403
    )
    create(client)
    entry = add_entry(client)
    assert client.get("/v1/vaults", headers=auth(OTHER)).json()["items"] == []
    assert client.get(f"{VAULT}/entries", headers=auth(OTHER)).status_code == 404
    response = client.post(f"{VAULT}/entries/{entry}/reveal?field=password", headers=auth(READER))
    assert response.status_code == 403
    assert ENTRY_PASSWORD not in client.get(f"{VAULT}/entries", headers=auth(READER)).text
    invalid = client.post(
        "/v1/vaults",
        headers=auth(),
        json={
            "id": "../../bad",
            "name": "Test",
            "credentials": {"password": PASSWORD},
        },
    )
    assert invalid.status_code == 422
    assert PASSWORD not in invalid.text
    assert client.get("/v1/vaults?limit=0", headers=auth()).status_code == 422


def test_rekey_and_security_preserve_data(client, tmp_path):
    created = create(client)
    entry_id = add_entry(client)
    crypto = {
        "cipher": "chacha20",
        "kdf": {
            "algorithm": "argon2id",
            "memoryMiB": 16,
            "iterations": 2,
            "parallelism": 2,
        },
    }
    stale = client.patch(
        f"{VAULT}/security",
        headers=auth(),
        json={
            "revision": created["revision"],
            "security": crypto,
        },
    )
    assert stale.status_code == 409
    current = client.get(VAULT, headers=auth()).json()
    changed = client.patch(
        f"{VAULT}/security",
        headers=auth(),
        json={
            "revision": current["revision"],
            "security": crypto,
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["security"]["cipher"] == "chacha20"
    rotated = client.post(
        f"{VAULT}/rekey",
        headers=auth(),
        json={
            "revision": changed.json()["revision"],
            "credentials": {"password": ROTATED},
        },
    )
    assert rotated.status_code == 200, rotated.text
    assert client.post(f"{VAULT}/lock", headers=auth()).status_code == 200
    assert client.get(VAULT, headers=auth()).status_code == 423
    assert (
        client.post(f"{VAULT}/unlock", headers=auth(), json={"password": PASSWORD}).status_code
        == 403
    )
    assert (
        client.post(f"{VAULT}/unlock", headers=auth(), json={"password": ROTATED}).status_code
        == 200
    )
    db = PyKeePass(tmp_path / "one" / "demo.kdbx", password=ROTATED)
    assert db.entries[0].password == ENTRY_PASSWORD
    assert str(db.entries[0].uuid) == entry_id
    assert (tmp_path / "one" / "demo.previous").is_file()


def test_entry_operations_and_totp(client):
    create(client)
    group = client.post(f"{VAULT}/groups", headers=auth(), json={"name": "Tests"}).json()
    ids = [add_entry(client, f"Item {index}", group["id"]) for index in range(5)]
    for offset, count in ((0, 2), (2, 2), (4, 1), (5, 0), (30, 0)):
        page = client.get(f"{VAULT}/entries?limit=2&offset={offset}", headers=auth()).json()
        assert page["total"] == 5
        assert [item["id"] for item in page["items"]] == ids[offset : offset + count]
    endpoint = f"{VAULT}/entries/{ids[1]}"
    response = client.patch(endpoint, headers=auth(), json={"title": "Updated"})
    assert response.status_code == 200, response.text
    assert client.get(f"{VAULT}/entries?q=updated", headers=auth()).json()["total"] == 1
    assert client.get(f"{VAULT}/entries/{ids[1]}", headers=auth()).json()["title"] == "Updated"
    assert (
        client.put(f"{endpoint}/totp", headers=auth(), json={"value": "invalid!"}).status_code
        == 422
    )
    assert (
        client.put(
            f"{endpoint}/totp", headers=auth(), json={"value": "JBSWY3DPEHPK3PXP"}
        ).status_code
        == 200
    )
    code = client.post(f"{endpoint}/totp/code", headers=auth())
    assert code.status_code == 200, code.text
    assert code.headers["Cache-Control"] == "no-store"
    assert len(code.json()["code"]) == 6 and code.json()["expiresAt"] % 30 == 0
    assert client.delete(endpoint, headers=auth()).status_code == 200
    assert client.get(f"{VAULT}/entries", headers=auth()).json()["total"] == 4


def test_mcp_tools_enforce_same_owner(client):
    create(client)
    headers = {**auth(), "Accept": "application/json, text/event-stream"}
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "list_vaults",
            "arguments": {},
        },
    }
    assert client.post("/mcp", json=request).status_code == 401
    output = client.post("/mcp", headers=headers, json=request)
    assert output.status_code == 200, output.text
    assert "demo" in output.text
    other = client.post("/mcp", headers={**headers, **auth(OTHER)}, json=request)
    assert other.status_code == 200, other.text
    assert "demo" not in other.text


def test_literal_entry_and_protected_fields(client):
    create(client)
    title = 'Alice "quoted" & Bob'
    entry_id = add_entry(client, title)
    endpoint = f"{VAULT}/entries/{entry_id}"
    assert client.get(endpoint, headers=auth()).json()["title"] == title
    assert (
        client.patch(endpoint, headers=auth(), json={"title": "invalid\u0000"}).status_code == 422
    )
    fields = f"{endpoint}/fields/recovery"
    assert (
        client.put(fields, headers=auth(), json={"value": "example-recovery-code"}).status_code
        == 200
    )
    assert client.post(f"{fields}/reveal", headers=auth(READER)).status_code == 403
    assert client.post(f"{fields}/reveal", headers=auth()).json() == {
        "value": "example-recovery-code",
    }
    payload = "c2FtcGxlIGF0dGFjaG1lbnQ="
    files = f"{endpoint}/attachments"
    created = client.post(
        files,
        headers=auth(),
        json={
            "name": "test.txt",
            "contentBase64": payload,
        },
    )
    assert created.status_code == 201, created.text
    assert client.get(files, headers=auth(READER)).json() == [{"index": 0, "name": "test.txt"}]
    assert client.get(f"{files}/0", headers=auth(READER)).status_code == 403
    assert client.get(f"{files}/0", headers=auth()).json()["contentBase64"] == payload


def test_key_file_is_scoped_and_required(client, tmp_path):
    keys = tmp_path / "one" / "keys"
    keys.mkdir(parents=True)
    (keys / "example.keyx").write_bytes(b"Synthetic fixture key".ljust(32, b"x"))
    request = {"id": "demo", "name": "Test", "credentials": {"keyFile": "example"}}
    assert client.post("/v1/vaults", headers=auth(OTHER), json=request).status_code == 404
    result = client.post("/v1/vaults", headers=auth(), json=request)
    assert result.status_code == 201, result.text
    client.post(f"{VAULT}/lock", headers=auth())
    assert (
        client.post(f"{VAULT}/unlock", headers=auth(), json={"password": PASSWORD}).status_code
        == 403
    )
    assert (
        client.post(f"{VAULT}/unlock", headers=auth(), json={"keyFile": "example"}).status_code
        == 200
    )
