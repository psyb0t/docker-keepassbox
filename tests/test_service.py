import base64
import errno
import json
import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pykeepass import PyKeePass

from keepassbox import engine
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
def config(tmp_path: Path):
    access = Access(
        clients=[
            Client(owner="one", token=TOKEN),
            Client(owner="one", token=READER, scopes={"entries:read"}),
            Client(owner="two", token=OTHER, scopes=SCOPES),
            *(Client(owner="one", token=f"{TOKEN}-{scope}", scopes={scope}) for scope in SCOPES),
        ]
    )
    return Config(tmp_path, access)


@pytest.fixture
def client(config):
    with TestClient(create_app(config)) as http:
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


def mcp_request(client, method, params=None, token=TOKEN):
    response = client.post(
        "/mcp",
        headers={**auth(token), "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    if response.headers["Content-Type"].startswith("text/event-stream"):
        messages = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        (message,) = (message for message in messages if message.get("id") == 1)
    else:
        message = response.json()
    assert message["id"] == 1
    assert "error" not in message, message
    return message["result"]


def test_description_endpoints(client):
    version = client.get("/version").json()
    assert version["name"] == "keepassbox"
    for path in ("/openapi.json", "/docs", "/redoc"):
        denied = client.get(path)
        assert denied.status_code == 401
        assert denied.headers["WWW-Authenticate"] == "Bearer"
        assert client.get(path, headers=auth()).status_code == 200
    schema = client.get("/openapi.json", headers=auth()).json()
    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }
    assert "security" not in schema["paths"]["/healthz"]["get"]
    assert schema["paths"]["/openapi.json"]["get"]["security"] == [{"HTTPBearer": []}]
    assert set(
        operation["tags"][0]
        for methods in schema["paths"].values()
        for operation in methods.values()
    ) == {tag["name"] for tag in schema["tags"]}
    for path, operations in schema["paths"].items():
        if not path.startswith("/v1/"):
            continue
        for operation in operations.values():
            assert operation["security"] == [{"HTTPBearer": []}]
            assert operation["x-required-scope"] in SCOPES
            assert operation["description"]
            assert operation["x-codeSamples"][0]["lang"] == "curl"
            for parameter in operation.get("parameters", ()):
                assert parameter["description"]
                assert "required" in parameter
                if parameter["in"] in {"path", "query"}:
                    assert parameter["schema"]["examples"]
                    assert (
                        parameter["in"] == "path"
                        or parameter["required"]
                        or "default" in parameter["schema"]
                    )
            if body := operation.get("requestBody"):
                content = body["content"]["application/json"]
                assert body["required"] and "example" in content
                request_model = content["schema"]["$ref"].rsplit("/", 1)[-1]
                assert all(
                    field["description"]
                    for field in schema["components"]["schemas"][request_model][
                        "properties"
                    ].values()
                )
            statuses = operation["responses"]
            assert statuses["422"]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ProblemResponse",
            }
            success = next(value for status, value in statuses.items() if status.startswith("2"))
            response = success["content"]["application/json"]["schema"]
            assert "$ref" in response or response.get("type") == "array"
            assert "example" in success["content"]["application/json"]
            for status, record in statuses.items():
                if status.startswith(("4", "5")):
                    for code, example in record["content"]["application/json"]["examples"].items():
                        assert example["value"]["code"] == code and example["description"]
    result = mcp_request(
        client,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "KeePassBox tests", "version": "1"},
        },
    )
    assert result["serverInfo"]["name"] == "KeePassBox"
    assert result["serverInfo"]["version"] == version["version"]


@pytest.mark.parametrize("transport", ["rest", "mcp"])
def test_complete_vault_workflow(client, transport):
    exercised = set()
    if transport == "rest":
        paths = client.get("/openapi.json", headers=auth()).json()["paths"]
        rest_scopes = {
            operation["operationId"]: operation["x-required-scope"]
            for path, methods in paths.items()
            if path.startswith("/v1/")
            for operation in methods.values()
        }

    def call(tool, method, route, *, args=None, body=None, status=200):
        exercised.add(tool)
        if transport == "mcp":
            arguments = dict(args or {})
            if body is not None:
                arguments["body"] = body
            result = mcp_request(client, "tools/call", {"name": tool, "arguments": arguments})
            assert not result.get("isError"), result
            data = result["structuredContent"]
            if tool in {"list_groups", "list_entry_attachments"}:
                return data["result"]
            return data
        response = client.request(
            method, route, json=body, headers=auth(f"{TOKEN}-{rest_scopes[tool]}")
        )
        assert response.status_code == status, response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        return response.json()

    vaults = "/v1/vaults"
    args = {"vault": "demo"}
    credentials = {"password": PASSWORD}
    security = {"cipher": "twofish", "kdf": {"algorithm": "aes-kdf", "rounds": 100_000}}
    original = call(
        "create_vault",
        "POST",
        vaults,
        status=201,
        body={
            "id": "demo",
            "name": "Fixture",
            "credentials": credentials,
            "security": {"kdf": security["kdf"]},
        },
    )
    assert original["name"] == "Fixture"
    assert original["format"].startswith("4.")
    assert call("get_vault", "GET", VAULT, args=args) == original
    assert call("list_vaults", "GET", vaults) == {
        "items": [{"id": "demo", "unlocked": True}],
        "total": 1,
    }
    assert call("lock_vault", "POST", f"{VAULT}/lock", args=args) == {
        "id": "demo",
        "unlocked": False,
    }
    assert call("unlock_vault", "POST", f"{VAULT}/unlock", args=args, body=credentials) == original
    updated = call(
        "update_vault_security",
        "PATCH",
        f"{VAULT}/security",
        args=args,
        body={
            "revision": original["revision"],
            "security": security,
        },
    )
    assert updated["security"]["cipher"] == "twofish"
    rotated = call(
        "rekey_vault",
        "POST",
        f"{VAULT}/rekey",
        args=args,
        body={
            "revision": updated["revision"],
            "credentials": {"password": ROTATED},
        },
    )
    assert rotated["revision"] not in {original["revision"], updated["revision"]}

    groups = f"{VAULT}/groups"
    (root,) = call("list_groups", "GET", groups, args=args)
    group = call(
        "create_group",
        "POST",
        groups,
        args=args,
        status=201,
        body={
            "name": "Fixture group",
            "parentId": root["id"],
        },
    )
    assert group["parentId"] == root["id"]
    assert group in call("list_groups", "GET", groups, args=args)

    password = call(
        "new_password",
        "POST",
        "/v1/passwords/generate",
        body={"length": 16, "symbols": False},
    )["password"]
    assert len(password) == 16 and password.isalnum()
    entries = f"{VAULT}/entries"
    created = call(
        "create_entry",
        "POST",
        entries,
        args=args,
        status=201,
        body={
            "title": "Échantillon",
            "password": password,
            "notes": "fixture note",
        },
    )
    entry_args = {**args, "entry": created["id"]}
    entry = f"{entries}/{created['id']}"
    assert call("get_entry", "GET", entry, args=entry_args) == created
    moved = call("update_entry", "PATCH", entry, args=entry_args, body={"groupId": group["id"]})
    assert moved["groupId"] == group["id"]
    assert call("list_entries", "GET", entries, args=args) == {"items": [moved], "total": 1}
    assert "password" not in moved and "notes" not in moved
    for name, value in (("notes", "fixture note"), ("password", password)):
        assert call(
            "reveal_entry_field",
            "POST",
            f"{entry}/reveal?field={name}",
            args={**entry_args, "field": name},
        ) == {"value": value}

    assert call(
        "set_entry_totp",
        "PUT",
        f"{entry}/totp",
        args=entry_args,
        body={
            "value": "JBSWY3DPEHPK3PXP",
        },
    ) == {"id": created["id"], "hasTotp": True}
    otp = call("generate_entry_totp", "POST", f"{entry}/totp/code", args=entry_args)
    assert set(otp) == {"code", "expiresAt"}
    assert len(otp["code"]) == 6 and otp["code"].isdigit()

    field = f"{entry}/fields/recovery"
    field_args = {**entry_args, "name": "recovery"}
    assert call(
        "set_entry_field",
        "PUT",
        field,
        args=field_args,
        body={
            "value": "fixture recovery code",
        },
    ) == {"name": "recovery"}
    assert call("reveal_custom_field", "POST", f"{field}/reveal", args=field_args) == {
        "value": "fixture recovery code",
    }
    attachments = f"{entry}/attachments"
    payload = {"name": "demo.txt", "contentBase64": "Zml4dHVyZQ=="}
    assert call(
        "add_entry_attachment",
        "POST",
        attachments,
        args=entry_args,
        body=payload,
        status=201,
    ) == {"name": "demo.txt"}
    assert call("list_entry_attachments", "GET", attachments, args=entry_args) == [
        {"index": 0, "name": "demo.txt"},
    ]
    assert (
        call(
            "get_entry_attachment",
            "GET",
            f"{attachments}/0",
            args={**entry_args, "index": 0},
        )
        == payload
    )

    assert call("trash_entry", "DELETE", entry, args=entry_args) == {
        "id": created["id"],
        "trashed": True,
    }
    assert call("list_entries", "GET", entries, args=args) == {"items": [], "total": 0}
    if transport == "mcp":
        tools = mcp_request(client, "tools/list")["tools"]
        assert exercised == {tool["name"] for tool in tools}
    else:
        assert exercised == rest_scopes.keys()


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert error["details"] == {}


def test_concurrent_writes_and_conflicting_rekeys(client, tmp_path):
    create(client)
    count = 6
    start = Barrier(count)

    def write(index):
        start.wait(timeout=10)
        return add_entry(client, f"Concurrent entry {index}")

    with ThreadPoolExecutor(max_workers=count) as workers:
        ids = set(workers.map(write, range(count)))
    listed = client.get(f"{VAULT}/entries", headers=auth()).json()
    assert listed["total"] == count
    assert {item["id"] for item in listed["items"]} == ids
    revision = client.get(VAULT, headers=auth()).json()["revision"]
    rotate_start = Barrier(2)

    def rekey(password):
        rotate_start.wait(timeout=10)
        return client.post(
            f"{VAULT}/rekey",
            headers=auth(),
            json={"revision": revision, "credentials": {"password": password}},
        )

    passwords = ("fixture-rotation-one", "fixture-rotation-two")
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = dict(zip(passwords, workers.map(rekey, passwords), strict=True))
    assert sorted(response.status_code for response in responses.values()) == [200, 409]
    winner = next(password for password, response in responses.items() if response.is_success)
    db = PyKeePass(tmp_path / "one" / "demo.kdbx", password=winner)
    assert {str(entry.uuid) for entry in db.entries} == ids
    prior = PyKeePass(tmp_path / "one" / "demo.previous", password=PASSWORD)
    assert {str(entry.uuid) for entry in prior.entries} == ids


def test_interrupted_replacement_restart_and_backup(config, tmp_path, monkeypatch):
    path = tmp_path / "one" / "demo.kdbx"
    with TestClient(create_app(config)) as client:
        create(client)
        kept = add_entry(client, "Persisted")
        original = path.read_bytes()
        replace = os.replace

        def fail_primary_replacement(source, destination):
            if destination == path:
                raise OSError(errno.ENOSPC, "synthetic disk full")
            replace(source, destination)

        with monkeypatch.context() as fault:
            fault.setattr(engine.os, "replace", fail_primary_replacement)
            assert_error(
                client.post(f"{VAULT}/entries", headers=auth(), json={"title": "Lost write"}),
                503,
                "STORE_UNAVAILABLE",
            )
        assert_error(client.get(VAULT, headers=auth()), 423, "VAULT_LOCKED")
        assert path.read_bytes() == original
        assert path.with_suffix(".previous").read_bytes() == original
        assert list(path.parent.glob(".vault-*")) == []

    with TestClient(create_app(config)) as restarted:
        assert_error(restarted.get(VAULT, headers=auth()), 423, "VAULT_LOCKED")
        unlocked = restarted.post(f"{VAULT}/unlock", headers=auth(), json={"password": PASSWORD})
        assert unlocked.status_code == 200, unlocked.text
        items = restarted.get(f"{VAULT}/entries", headers=auth()).json()["items"]
        assert [item["id"] for item in items] == [kept]
        assert add_entry(restarted, "Retried") != kept
    assert [entry.title for entry in PyKeePass(path, password=PASSWORD).entries] == [
        "Persisted",
        "Retried",
    ]


def crash_during_replace(config):
    replace = os.replace

    def crash_before_commit(source, destination):
        if Path(destination).suffix == ".kdbx":
            os._exit(86)
        replace(source, destination)

    os.replace = crash_before_commit
    with TestClient(create_app(config)) as client:
        assert client.post(
            f"{VAULT}/unlock", headers=auth(), json={"password": PASSWORD}
        ).is_success
        add_entry(client, "Interrupted write")


def test_hard_exit_before_commit_preserves_last_successful_revision(config):
    with TestClient(create_app(config)) as client:
        create(client)
        kept = add_entry(client, "Persisted before crash")
    path = config.data / "one" / "demo.kdbx"
    before = path.read_bytes()
    worker = multiprocessing.get_context("spawn").Process(
        target=crash_during_replace,
        args=(config,),
    )
    worker.start()
    try:
        worker.join(timeout=20)
        assert worker.exitcode == 86
    finally:
        if worker.is_alive():
            worker.kill()
            worker.join(timeout=5)

    assert path.read_bytes() == before
    assert path.with_suffix(".previous").read_bytes() == before
    with TestClient(create_app(config)) as restarted:
        assert_error(restarted.get(VAULT, headers=auth()), 423, "VAULT_LOCKED")
        assert restarted.post(
            f"{VAULT}/unlock",
            headers=auth(),
            json={"password": PASSWORD},
        ).is_success
        items = restarted.get(f"{VAULT}/entries", headers=auth()).json()["items"]
        assert [item["id"] for item in items] == [kept]
        add_entry(restarted, "Retried after crash")
    assert [entry.title for entry in PyKeePass(path, password=PASSWORD).entries] == [
        "Persisted before crash",
        "Retried after crash",
    ]


def test_external_edit_is_never_overwritten(client, tmp_path):
    create(client)
    path = tmp_path / "one" / "demo.kdbx"
    external = PyKeePass(path, password=PASSWORD)
    external.add_entry(external.root_group, "External edit", "", "")
    external.save()
    revised = path.read_bytes()
    assert_error(
        client.post(f"{VAULT}/entries", headers=auth(), json={"title": "Conflicting edit"}),
        409,
        "VAULT_CONFLICT",
    )
    assert path.read_bytes() == revised
    assert_error(client.get(VAULT, headers=auth()), 423, "VAULT_LOCKED")
    assert client.post(f"{VAULT}/unlock", headers=auth(), json={"password": PASSWORD}).is_success
    items = client.get(f"{VAULT}/entries", headers=auth()).json()["items"]
    assert [item["title"] for item in items] == ["External edit"]


def test_idle_activity_extends_unlock_then_expires(config):
    with TestClient(create_app(Config(config.data, config.access, idle_seconds=1))) as client:
        create(client)
        time.sleep(0.6)
        assert client.get(VAULT, headers=auth(READER)).status_code == 200
        time.sleep(0.6)
        assert client.get(VAULT, headers=auth()).status_code == 200
        time.sleep(1.05)
        assert_error(client.get(VAULT, headers=auth()), 423, "VAULT_LOCKED")
        assert client.get("/v1/vaults", headers=auth()).json()["items"] == [
            {"id": "demo", "unlocked": False},
        ]
        assert client.post(
            f"{VAULT}/unlock", headers=auth(), json={"password": PASSWORD}
        ).is_success


def test_vault_pagination_and_duplicate_ids(client):
    assert client.get("/v1/vaults", headers=auth()).json() == {"items": [], "total": 0}
    names = ["alpha", "bravo", "charlie", "delta", "echo"]
    for name in reversed(names):
        create(client, name)
    for offset in (0, 2, 4, 5, 200):
        page = client.get(f"/v1/vaults?limit=2&offset={offset}", headers=auth()).json()
        assert page["total"] == len(names)
        assert [item["id"] for item in page["items"]] == names[offset : offset + 2]
    assert_error(
        client.post(
            "/v1/vaults",
            headers=auth(),
            json={"id": "alpha", "name": "Duplicate", "credentials": {"password": PASSWORD}},
        ),
        409,
        "VAULT_EXISTS",
    )


def test_missing_objects_and_attachment_limits(client):
    assert_error(client.get(VAULT, headers=auth()), 404, "VAULT_NOT_FOUND")
    create(client)
    missing = uuid4()
    assert_error(
        client.get(f"{VAULT}/entries/{missing}", headers=auth()),
        404,
        "ENTRY_NOT_FOUND",
    )
    assert_error(
        client.post(
            f"{VAULT}/groups", headers=auth(), json={"name": "Orphan", "parentId": str(missing)}
        ),
        404,
        "GROUP_NOT_FOUND",
    )
    entry = f"{VAULT}/entries/{add_entry(client)}"
    assert_error(client.post(f"{entry}/totp/code", headers=auth()), 404, "TOTP_NOT_FOUND")
    assert_error(
        client.post(f"{entry}/fields/recovery/reveal", headers=auth()), 404, "FIELD_NOT_FOUND"
    )
    assert_error(client.get(f"{entry}/attachments/0", headers=auth()), 404, "ATTACHMENT_NOT_FOUND")
    for content, code in (
        ("!!!?", "INVALID_ATTACHMENT"),
        (base64.b64encode(bytes(32769)).decode(), "ATTACHMENT_LIMIT"),
    ):
        response = client.post(
            f"{entry}/attachments",
            headers=auth(),
            json={"name": "fixture.bin", "contentBase64": content},
        )
        assert_error(response, 422, code)
    content = base64.b64encode(bytes(32768)).decode()
    payload = {"name": "fixture.bin", "contentBase64": content}
    assert client.post(f"{entry}/attachments", headers=auth(), json=payload).status_code == 201
    assert client.get(f"{entry}/attachments/0", headers=auth()).json() == payload


@pytest.mark.parametrize("protocol", ["rest", "mcp"])
def test_transport_rejects_browser_origin_and_large_body(client, protocol):
    route = "/mcp" if protocol == "mcp" else "/v1/vaults"
    assert_error(
        client.post(route, headers={**auth(), "Origin": "https://example.invalid"}, json={}),
        403,
        "FORBIDDEN",
    )
    assert_error(client.post(route, headers=auth(), content=b"x" * 65537), 413, "BODY_LIMIT")
    assert_error(
        client.post(route, headers={**auth(), "Content-Length": "garbage"}, json={}),
        413,
        "BODY_LIMIT",
    )


def test_config_from_env(tmp_path, monkeypatch):
    path = tmp_path / "access.local.json"
    monkeypatch.setenv("KEEPASSBOX_ACCESS_FILE", str(path))
    monkeypatch.setenv("KEEPASSBOX_DATA_DIR", str(tmp_path / "vaults"))
    monkeypatch.setenv("KEEPASSBOX_IDLE_SECONDS", "5")
    monkeypatch.setenv("KEEPASSBOX_KDF_MAX_MIB", "1024")
    entry = {"owner": "one", "token": TOKEN, "scopes": ["entries:read"]}

    def invalid():
        with pytest.raises(RuntimeError, match="^Missing or invalid KeePassBox configuration$"):
            Config.from_env()

    invalid()
    for content in (b"invalid JSON", b"x" * 65537):
        path.write_bytes(content)
        invalid()
    for clients in (
        [],
        [entry, entry],
        [{**entry, "token": "é" * 32}],
        [{**entry, "scopes": ["all"]}],
        [{**entry, "scopes": []}],
        [{**entry, "scopes": None}],
    ):
        path.write_text(json.dumps({"clients": clients}), encoding="utf-8")
        invalid()
    path.write_text(
        json.dumps({"clients": [{"owner": "one", "token": TOKEN}, {**entry, "token": READER}]}),
        encoding="utf-8",
    )
    for name, values in (
        ("KEEPASSBOX_IDLE_SECONDS", ("4", "86401", "invalid")),
        ("KEEPASSBOX_KDF_MAX_MIB", ("63", "1025", "invalid")),
    ):
        for value in values:
            with monkeypatch.context() as invalid_env:
                invalid_env.setenv(name, value)
                invalid()
    config = Config.from_env()
    assert config.data == tmp_path / "vaults"
    assert config.idle_seconds == 5 and config.memory_mib == 1024
    assert config.authenticate(f"bEaReR {TOKEN}").owner == "one"
    assert config.authenticate(f"Bearer {TOKEN}").scopes == SCOPES
    assert config.authenticate(f"Bearer {READER}").scopes == {"entries:read"}
    for value in ("", f"Basic {TOKEN}", f"Bearer  {TOKEN}", "Bearer " + "é" * 32):
        assert config.authenticate(value) is None


def test_corrupt_oversized_and_linked_vaults(client, tmp_path):
    owner = tmp_path / "one"
    owner.mkdir()
    (owner / "empty.kdbx").touch()
    (owner / "corrupt.kdbx").write_bytes(b"Not a KeePass vault")
    with (owner / "oversized.kdbx").open("wb") as file:
        file.truncate(32 * 1024 * 1024 + 1)
    target = tmp_path / "outside.kdbx"
    target.write_bytes(b"Do not touch")
    (owner / "linked.kdbx").symlink_to(target)
    for vault, status, code in (
        ("empty", 422, "INVALID_VAULT"),
        ("corrupt", 422, "INVALID_VAULT"),
        ("oversized", 422, "FILE_LIMIT"),
        ("linked", 503, "STORE_UNAVAILABLE"),
    ):
        response = client.post(
            f"/v1/vaults/{vault}/unlock",
            headers=auth(),
            json={"password": PASSWORD},
        )
        assert_error(response, status, code)
        assert PASSWORD not in response.text
    listed = client.get("/v1/vaults", headers=auth()).json()["items"]
    assert {item["id"] for item in listed} == {"empty", "corrupt", "oversized"}
    assert target.read_bytes() == b"Do not touch"


def test_mcp_scope_errors_and_validation(client):
    create(client)
    entry = add_entry(client)
    for token, name, arguments, expected in (
        (READER, "new_password", {"body": {}}, "FORBIDDEN"),
        (READER, "create_group", {"vault": "demo", "body": {"name": "Denied"}}, "FORBIDDEN"),
        (READER, "generate_entry_totp", {"vault": "demo", "entry": entry}, "FORBIDDEN"),
        (
            READER,
            "reveal_entry_field",
            {"vault": "demo", "entry": entry, "field": "password"},
            "FORBIDDEN",
        ),
        (OTHER, "get_vault", {"vault": "demo"}, "VAULT_NOT_FOUND"),
    ):
        result = mcp_request(client, "tools/call", {"name": name, "arguments": arguments}, token)
        assert result["isError"] is True
        assert result["content"][0]["text"].startswith(f"{expected}:")
        assert ENTRY_PASSWORD not in json.dumps(result)
    result = mcp_request(
        client,
        "tools/call",
        {
            "name": "create_vault",
            "arguments": {
                "body": {"id": "../bad", "name": "Fixture", "credentials": {"password": PASSWORD}},
            },
        },
    )
    assert result["isError"] is True
    assert PASSWORD not in json.dumps(result)
