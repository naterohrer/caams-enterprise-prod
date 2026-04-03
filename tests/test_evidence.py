"""Tests for evidence file upload, approval, download, and deletion."""


def test_list_evidence_empty(client, auth_headers, assessment):
    r = client.get(f"/assessments/{assessment.id}/evidence", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_evidence_unauthenticated(client, assessment):
    r = client.get(f"/assessments/{assessment.id}/evidence")
    assert r.status_code == 401


def test_upload_and_delete_evidence(client, auth_headers, assessment):
    r = client.post(
        f"/assessments/{assessment.id}/evidence",
        headers=auth_headers,
        data={"control_id": "T-1", "description": "Test evidence file"},
        files={"file": ("test.txt", b"hello world", "text/plain")},
    )
    assert r.status_code == 201
    ev = r.json()
    assert ev["original_filename"] == "test.txt"
    assert ev["control_id"] == "T-1"
    assert ev["approval_status"] == "pending"
    assert ev["description"] == "Test evidence file"
    assert ev["file_size"] == 11

    ev_id = ev["id"]
    r = client.delete(f"/assessments/{assessment.id}/evidence/{ev_id}", headers=auth_headers)
    assert r.status_code == 204

    # Confirm gone
    r = client.get(f"/assessments/{assessment.id}/evidence/{ev_id}/download",
                   headers=auth_headers)
    assert r.status_code == 404


def test_list_evidence_filter_by_control(client, auth_headers, assessment):
    r = client.post(
        f"/assessments/{assessment.id}/evidence",
        headers=auth_headers,
        data={"control_id": "T-2"},
        files={"file": ("filter_test.txt", b"content", "text/plain")},
    )
    assert r.status_code == 201
    ev_id = r.json()["id"]

    r = client.get(f"/assessments/{assessment.id}/evidence?control_id=T-2", headers=auth_headers)
    assert r.status_code == 200
    assert all(e["control_id"] == "T-2" for e in r.json())

    client.delete(f"/assessments/{assessment.id}/evidence/{ev_id}", headers=auth_headers)


def test_upload_evidence_invalid_expires_at_returns_422(client, auth_headers, assessment):
    r = client.post(
        f"/assessments/{assessment.id}/evidence",
        headers=auth_headers,
        data={"control_id": "T-1", "expires_at": "not-a-date"},
        files={"file": ("x.txt", b"x", "text/plain")},
    )
    assert r.status_code == 422


def test_upload_evidence_valid_expires_at(client, auth_headers, assessment):
    r = client.post(
        f"/assessments/{assessment.id}/evidence",
        headers=auth_headers,
        data={"control_id": "T-1", "expires_at": "2030-12-31T00:00:00"},
        files={"file": ("expiring.txt", b"data", "text/plain")},
    )
    assert r.status_code == 201
    ev = r.json()
    assert ev["expires_at"] is not None

    client.delete(f"/assessments/{assessment.id}/evidence/{ev['id']}", headers=auth_headers)


def test_approve_evidence(client, auth_headers, assessment):
    r = client.post(
        f"/assessments/{assessment.id}/evidence",
        headers=auth_headers,
        data={"control_id": "T-1"},
        files={"file": ("approve_me.txt", b"data", "text/plain")},
    )
    ev_id = r.json()["id"]

    r = client.patch(
        f"/assessments/{assessment.id}/evidence/{ev_id}/approval",
        headers=auth_headers,
        json={"action": "approve", "rejection_reason": ""},
    )
    assert r.status_code == 200
    assert r.json()["approval_status"] == "approved"
    assert r.json()["approved_by_name"] == "testadmin"

    client.delete(f"/assessments/{assessment.id}/evidence/{ev_id}", headers=auth_headers)


def test_reject_evidence(client, auth_headers, assessment):
    r = client.post(
        f"/assessments/{assessment.id}/evidence",
        headers=auth_headers,
        data={"control_id": "T-1"},
        files={"file": ("reject_me.txt", b"data", "text/plain")},
    )
    ev_id = r.json()["id"]

    r = client.patch(
        f"/assessments/{assessment.id}/evidence/{ev_id}/approval",
        headers=auth_headers,
        json={"action": "reject", "rejection_reason": "insufficient detail"},
    )
    assert r.status_code == 200
    assert r.json()["approval_status"] == "rejected"
    assert r.json()["rejection_reason"] == "insufficient detail"

    client.delete(f"/assessments/{assessment.id}/evidence/{ev_id}", headers=auth_headers)


def test_download_evidence(client, auth_headers, assessment):
    content = b"downloadable file content"
    r = client.post(
        f"/assessments/{assessment.id}/evidence",
        headers=auth_headers,
        data={"control_id": "T-1"},
        files={"file": ("download_me.txt", content, "text/plain")},
    )
    ev_id = r.json()["id"]

    r = client.get(
        f"/assessments/{assessment.id}/evidence/{ev_id}/download",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.content == content

    client.delete(f"/assessments/{assessment.id}/evidence/{ev_id}", headers=auth_headers)


def test_evidence_not_found_returns_404(client, auth_headers, assessment):
    r = client.get(f"/assessments/{assessment.id}/evidence/999999/download",
                   headers=auth_headers)
    assert r.status_code == 404


def test_delete_evidence_twice_is_safe(client, auth_headers, assessment):
    """Deleting already-deleted evidence should return 404, not crash."""
    r = client.post(
        f"/assessments/{assessment.id}/evidence",
        headers=auth_headers,
        data={"control_id": "T-1"},
        files={"file": ("delete_twice.txt", b"x", "text/plain")},
    )
    ev_id = r.json()["id"]

    r = client.delete(f"/assessments/{assessment.id}/evidence/{ev_id}", headers=auth_headers)
    assert r.status_code == 204

    r = client.delete(f"/assessments/{assessment.id}/evidence/{ev_id}", headers=auth_headers)
    assert r.status_code == 404
