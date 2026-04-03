"""Tests for tool catalog endpoints."""

import json


def test_list_tools(client, auth_headers):
    r = client.get("/tools", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_tools_unauthenticated(client):
    r = client.get("/tools")
    assert r.status_code == 401


def test_create_and_delete_tool(client, auth_headers):
    r = client.post("/tools", headers=auth_headers, json={
        "name": "ToolCRUD_Test", "category": "EDR",
        "description": "test tool", "capabilities": ["endpoint-protection"],
    })
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "ToolCRUD_Test"
    assert "endpoint-protection" in data["capabilities"]

    r = client.delete(f"/tools/{data['id']}", headers=auth_headers)
    assert r.status_code == 204


def test_create_duplicate_tool_returns_409(client, auth_headers):
    r = client.post("/tools", headers=auth_headers, json={
        "name": "DupToolTest", "category": "EDR", "description": "", "capabilities": [],
    })
    assert r.status_code == 201
    tool_id = r.json()["id"]

    r = client.post("/tools", headers=auth_headers, json={
        "name": "DupToolTest", "category": "EDR", "description": "", "capabilities": [],
    })
    assert r.status_code == 409

    client.delete(f"/tools/{tool_id}", headers=auth_headers)


def test_delete_nonexistent_tool_returns_404(client, auth_headers):
    r = client.delete("/tools/999999", headers=auth_headers)
    assert r.status_code == 404


def test_download_template(client, auth_headers):
    r = client.get("/tools/template/download", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert "name" in data[0]
    assert "capabilities" in data[0]


def test_upload_tools_json(client, auth_headers):
    tools = [
        {"name": "UploadedToolA", "category": "SIEM", "description": "",
         "capabilities": ["log-collection"]},
        {"name": "UploadedToolB", "category": "NGFW", "description": "",
         "capabilities": []},
    ]
    r = client.post(
        "/tools/upload",
        headers=auth_headers,
        files={"file": ("tools.json", json.dumps(tools).encode(), "application/json")},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["added"] == 2
    assert data["skipped"] == 0

    all_tools = client.get("/tools", headers=auth_headers).json()
    for t in all_tools:
        if t["name"] in ("UploadedToolA", "UploadedToolB"):
            client.delete(f"/tools/{t['id']}", headers=auth_headers)


def test_upload_tools_skips_duplicates(client, auth_headers):
    r = client.post("/tools", headers=auth_headers, json={
        "name": "ExistingToolUpload", "category": "EDR", "description": "",
        "capabilities": [],
    })
    tool_id = r.json()["id"]

    tools = [{"name": "ExistingToolUpload", "category": "EDR",
              "description": "", "capabilities": []}]
    r = client.post(
        "/tools/upload",
        headers=auth_headers,
        files={"file": ("tools.json", json.dumps(tools).encode(), "application/json")},
    )
    assert r.status_code == 201
    assert r.json()["skipped"] == 1

    client.delete(f"/tools/{tool_id}", headers=auth_headers)


def test_upload_invalid_json_returns_422(client, auth_headers):
    r = client.post(
        "/tools/upload",
        headers=auth_headers,
        files={"file": ("tools.json", b"not valid json", "application/json")},
    )
    assert r.status_code == 422


def test_create_tool_requires_auth(client):
    r = client.post("/tools", json={
        "name": "UnauthedTool", "category": "EDR", "description": "", "capabilities": [],
    })
    assert r.status_code == 401
