"""Tests for assessment CRUD, lifecycle, control notes, coverage, and cloning."""


def test_list_assessments(client, auth_headers, assessment):
    r = client.get("/assessments", headers=auth_headers)
    assert r.status_code == 200
    assert any(a["id"] == assessment.id for a in r.json())


def test_list_assessments_filter_by_status(client, auth_headers, assessment):
    r = client.get("/assessments?status=draft", headers=auth_headers)
    assert r.status_code == 200
    assert all(a["status"] == "draft" for a in r.json())


def test_list_assessments_unauthenticated(client):
    r = client.get("/assessments")
    assert r.status_code == 401


def test_create_assessment(client, auth_headers, framework):
    r = client.post("/assessments", headers=auth_headers, json={
        "name": "New Assessment", "framework_id": framework.id,
        "scope_notes": "test scope", "is_recurring": False,
        "recurrence_days": None, "tool_ids": [],
    })
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "New Assessment"
    assert data["status"] == "draft"
    assert data["framework_name"] == "TestFW"
    assert data["scope_notes"] == "test scope"

    client.delete(f"/assessments/{data['id']}", headers=auth_headers)


def test_create_assessment_missing_framework_returns_404(client, auth_headers):
    r = client.post("/assessments", headers=auth_headers, json={
        "name": "Bad Assessment", "framework_id": 999999,
        "scope_notes": "", "is_recurring": False,
        "recurrence_days": None, "tool_ids": [],
    })
    assert r.status_code == 404


def test_get_assessment(client, auth_headers, assessment):
    r = client.get(f"/assessments/{assessment.id}", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == assessment.id
    assert data["name"] == "Test Assessment"
    assert data["status"] == "draft"


def test_get_assessment_not_found(client, auth_headers):
    r = client.get("/assessments/999999", headers=auth_headers)
    assert r.status_code == 404


def test_delete_assessment(client, auth_headers, framework, admin_user):
    r = client.post("/assessments", headers=auth_headers, json={
        "name": "DeleteMe", "framework_id": framework.id,
        "scope_notes": "", "is_recurring": False,
        "recurrence_days": None, "tool_ids": [],
    })
    assert r.status_code == 201
    a_id = r.json()["id"]

    r = client.delete(f"/assessments/{a_id}", headers=auth_headers)
    assert r.status_code == 204

    r = client.get(f"/assessments/{a_id}", headers=auth_headers)
    assert r.status_code == 404


def test_assessment_lifecycle_submit_and_approve(client, auth_headers, assessment):
    # Draft → in_review
    r = client.post(f"/assessments/{assessment.id}/lifecycle", headers=auth_headers,
                    json={"action": "submit_for_review", "comments": "ready for review"})
    assert r.status_code == 200
    assert r.json()["action"] == "submit_for_review"

    r = client.get(f"/assessments/{assessment.id}", headers=auth_headers)
    assert r.json()["status"] == "in_review"

    # in_review → approved (admin only)
    r = client.post(f"/assessments/{assessment.id}/lifecycle", headers=auth_headers,
                    json={"action": "approve", "comments": "approved"})
    assert r.status_code == 200

    r = client.get(f"/assessments/{assessment.id}", headers=auth_headers)
    assert r.json()["status"] == "approved"

    # Archive so teardown delete works cleanly
    client.post(f"/assessments/{assessment.id}/lifecycle", headers=auth_headers,
                json={"action": "archive", "comments": ""})


def test_assessment_invalid_lifecycle_transition_returns_400(client, auth_headers, assessment):
    # Cannot approve a draft assessment directly
    r = client.post(f"/assessments/{assessment.id}/lifecycle", headers=auth_headers,
                    json={"action": "approve", "comments": ""})
    assert r.status_code == 400


def test_get_signoffs(client, auth_headers, assessment):
    client.post(f"/assessments/{assessment.id}/lifecycle", headers=auth_headers,
                json={"action": "submit_for_review", "comments": "signoff test"})
    r = client.get(f"/assessments/{assessment.id}/signoffs", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1
    assert r.json()[0]["action"] == "submit_for_review"


def test_assessment_results(client, auth_headers, assessment):
    r = client.get(f"/assessments/{assessment.id}/results", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "score" in data
    assert "total_controls" in data
    assert "controls" in data
    assert data["total_controls"] == 3
    assert data["assessment_name"] == "Test Assessment"


def test_assessment_recommendations(client, auth_headers, assessment):
    r = client.get(f"/assessments/{assessment.id}/recommendations", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_clone_assessment(client, auth_headers, assessment):
    r = client.post(f"/assessments/{assessment.id}/clone", headers=auth_headers,
                    json={"name": "Cloned Assessment"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Cloned Assessment"
    assert data["framework_id"] == assessment.framework_id
    assert data["status"] == "draft"

    client.delete(f"/assessments/{data['id']}", headers=auth_headers)


def test_control_notes_default_when_not_set(client, auth_headers, assessment):
    r = client.get(f"/assessments/{assessment.id}/controls/T-1/notes", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["control_id"] == "T-1"
    assert data["notes"] == ""
    assert data["is_applicable"] is True


def test_control_notes_upsert(client, auth_headers, assessment):
    r = client.patch(
        f"/assessments/{assessment.id}/controls/T-1/notes",
        headers=auth_headers,
        json={"notes": "Updated note text", "evidence_url": "https://example.com"},
    )
    assert r.status_code == 200
    assert r.json()["notes"] == "Updated note text"

    # Verify it persists
    r = client.get(f"/assessments/{assessment.id}/controls/T-1/notes", headers=auth_headers)
    assert r.json()["notes"] == "Updated note text"
    assert r.json()["evidence_url"] == "https://example.com"


def test_control_override_status(client, auth_headers, assessment):
    r = client.patch(
        f"/assessments/{assessment.id}/controls/T-2/notes",
        headers=auth_headers,
        json={"override_status": "covered", "override_justification": "compensating control"},
    )
    assert r.status_code == 200
    assert r.json()["override_status"] == "covered"
    assert r.json()["override_justification"] == "compensating control"


def test_control_override_invalid_status_returns_422(client, auth_headers, assessment):
    r = client.patch(
        f"/assessments/{assessment.id}/controls/T-1/notes",
        headers=auth_headers,
        json={"override_status": "bad_value"},
    )
    assert r.status_code == 422


def test_control_ownership_upsert(client, auth_headers, assessment):
    r = client.patch(
        f"/assessments/{assessment.id}/controls/T-1/ownership",
        headers=auth_headers,
        json={"owner": "Alice", "team": "Security", "evidence_owner": "Bob"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["owner"] == "Alice"
    assert data["team"] == "Security"
    assert data["evidence_owner"] == "Bob"


def test_assessment_tools_update(client, auth_headers, assessment):
    r = client.patch(f"/assessments/{assessment.id}/tools", headers=auth_headers,
                     json={"tool_ids": []})
    assert r.status_code == 200
    assert r.json()["tool_count"] == 0


def test_assessment_history(client, auth_headers, assessment):
    r = client.get("/assessments/history", headers=auth_headers)
    assert r.status_code == 200
    assert any(a["id"] == assessment.id for a in r.json())
    # history entries include score
    entry = next(a for a in r.json() if a["id"] == assessment.id)
    assert "score" in entry
    assert "total_controls" in entry
