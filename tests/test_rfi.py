"""Tests for RFI (Request for Information) tracker endpoints."""


def test_list_rfis_empty(client, auth_headers, assessment):
    r = client.get(f"/assessments/{assessment.id}/rfis", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_rfis_unauthenticated(client, assessment):
    r = client.get(f"/assessments/{assessment.id}/rfis")
    assert r.status_code == 401


def test_create_and_close_rfi(client, auth_headers, assessment):
    r = client.post(f"/assessments/{assessment.id}/rfis", headers=auth_headers, json={
        "title": "Need Evidence", "description": "Please provide logs",
        "priority": "high", "control_id": "T-1",
        "requested_by": "", "assigned_to": "Bob", "due_date": None,
    })
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "Need Evidence"
    assert data["priority"] == "high"
    assert data["status"] == "open"
    assert data["control_id"] == "T-1"
    assert data["assigned_to"] == "Bob"
    assert data["responses"] == []
    rfi_id = data["id"]

    # Close the RFI
    r = client.patch(f"/assessments/{assessment.id}/rfis/{rfi_id}",
                     headers=auth_headers, json={"status": "closed"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "closed"
    assert data["closed_at"] is not None


def test_update_rfi_fields(client, auth_headers, assessment):
    r = client.post(f"/assessments/{assessment.id}/rfis", headers=auth_headers, json={
        "title": "UpdateMe", "description": "", "priority": "low",
        "control_id": "T-2", "requested_by": "", "assigned_to": "", "due_date": None,
    })
    rfi_id = r.json()["id"]

    r = client.patch(f"/assessments/{assessment.id}/rfis/{rfi_id}",
                     headers=auth_headers, json={
                         "title": "Updated RFI", "priority": "critical",
                         "assigned_to": "Carol",
                     })
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "Updated RFI"
    assert data["priority"] == "critical"
    assert data["assigned_to"] == "Carol"


def test_filter_rfis_by_status(client, auth_headers, assessment):
    r = client.post(f"/assessments/{assessment.id}/rfis", headers=auth_headers, json={
        "title": "StatusFilterRFI", "description": "", "priority": "medium",
        "control_id": "T-1", "requested_by": "", "assigned_to": "", "due_date": None,
    })
    rfi_id = r.json()["id"]

    r = client.get(f"/assessments/{assessment.id}/rfis?status=open", headers=auth_headers)
    assert r.status_code == 200
    assert all(rfi["status"] == "open" for rfi in r.json())

    # Close it so filter for "closed" returns it
    client.patch(f"/assessments/{assessment.id}/rfis/{rfi_id}",
                 headers=auth_headers, json={"status": "closed"})
    r = client.get(f"/assessments/{assessment.id}/rfis?status=closed", headers=auth_headers)
    assert r.status_code == 200
    assert any(rfi["id"] == rfi_id for rfi in r.json())


def test_add_response_updates_rfi_status(client, auth_headers, assessment):
    r = client.post(f"/assessments/{assessment.id}/rfis", headers=auth_headers, json={
        "title": "RespondMe", "description": "", "priority": "low",
        "control_id": "T-1", "requested_by": "", "assigned_to": "", "due_date": None,
    })
    rfi_id = r.json()["id"]
    assert r.json()["status"] == "open"

    r = client.post(
        f"/assessments/{assessment.id}/rfis/{rfi_id}/responses",
        headers=auth_headers,
        json={"response_text": "Here is the evidence", "responder_name": ""},
    )
    assert r.status_code == 201
    resp_data = r.json()
    assert resp_data["response_text"] == "Here is the evidence"
    assert resp_data["responder_name"] == "testadmin"

    # RFI should now show as responded
    r = client.get(f"/assessments/{assessment.id}/rfis", headers=auth_headers)
    rfi = next(rfi for rfi in r.json() if rfi["id"] == rfi_id)
    assert rfi["status"] == "responded"
    assert len(rfi["responses"]) == 1


def test_rfi_response_includes_in_list(client, auth_headers, assessment):
    r = client.post(f"/assessments/{assessment.id}/rfis", headers=auth_headers, json={
        "title": "MultiResponse", "description": "", "priority": "medium",
        "control_id": "T-1", "requested_by": "", "assigned_to": "", "due_date": None,
    })
    rfi_id = r.json()["id"]

    for text in ("First reply", "Second reply"):
        client.post(
            f"/assessments/{assessment.id}/rfis/{rfi_id}/responses",
            headers=auth_headers,
            json={"response_text": text, "responder_name": ""},
        )

    r = client.get(f"/assessments/{assessment.id}/rfis", headers=auth_headers)
    rfi = next(rfi for rfi in r.json() if rfi["id"] == rfi_id)
    assert len(rfi["responses"]) == 2


def test_update_rfi_not_found(client, auth_headers, assessment):
    r = client.patch(f"/assessments/{assessment.id}/rfis/999999",
                     headers=auth_headers, json={"title": "Ghost"})
    assert r.status_code == 404


def test_add_response_rfi_not_found(client, auth_headers, assessment):
    r = client.post(
        f"/assessments/{assessment.id}/rfis/999999/responses",
        headers=auth_headers,
        json={"response_text": "Nobody home", "responder_name": ""},
    )
    assert r.status_code == 404


def test_create_rfi_unauthenticated(client, assessment):
    r = client.post(f"/assessments/{assessment.id}/rfis", json={
        "title": "Anon", "description": "", "priority": "low",
        "control_id": "T-1", "requested_by": "", "assigned_to": "", "due_date": None,
    })
    assert r.status_code == 401
