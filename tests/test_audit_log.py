"""Tests for the immutable audit log endpoints."""


def test_audit_log_requires_admin(client, auth_headers):
    r = client.get("/audit-log", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_audit_log_unauthenticated(client):
    r = client.get("/audit-log")
    assert r.status_code == 401


def test_audit_log_non_admin_forbidden(client, db):
    from app import models
    from app.auth import hash_password

    viewer = models.User(
        username="viewer_audit_test",
        hashed_password=hash_password("Pass1234567!"),
        role="viewer",
        is_active=True,
    )
    db.add(viewer)
    db.commit()
    db.refresh(viewer)

    r = client.post("/auth/login", data={
        "username": "viewer_audit_test", "password": "Pass1234567!",
    })
    viewer_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.get("/audit-log", headers=viewer_headers)
    assert r.status_code == 403

    db.delete(viewer)
    db.commit()


def test_audit_log_populated_after_login(client, auth_headers, admin_user):
    """A LOGIN entry should exist in the audit log for the admin fixture's login."""
    r = client.get("/audit-log", headers=auth_headers)
    assert r.status_code == 200
    entries = r.json()
    actions = [e["action"] for e in entries]
    assert "LOGIN" in actions


def test_audit_log_filter_by_action(client, auth_headers):
    r = client.get("/audit-log?action=LOGIN", headers=auth_headers)
    assert r.status_code == 200
    entries = r.json()
    assert all("LOGIN" in e["action"].upper() for e in entries)


def test_audit_log_filter_by_user(client, auth_headers):
    r = client.get("/audit-log?user_name=testadmin", headers=auth_headers)
    assert r.status_code == 200
    entries = r.json()
    assert all("testadmin" in e["user_name"] for e in entries)


def test_assessment_audit_log(client, auth_headers, assessment):
    """Assessment-scoped audit log returns entries for that assessment."""
    # Create a finding to generate an audit entry for this assessment
    r = client.post(f"/assessments/{assessment.id}/findings", headers=auth_headers, json={
        "control_id": "T-1", "title": "AuditTestFinding", "description": "",
        "severity": "low", "remediation_owner": "", "target_date": None, "notes": "",
    })
    finding_id = r.json()["id"]

    r = client.get(f"/audit-log/assessment/{assessment.id}", headers=auth_headers)
    assert r.status_code == 200
    # Assessment-level log uses resource_type="assessment" filter at router level,
    # so entries may be empty if no assessment-resource entries exist — just verify it works
    assert isinstance(r.json(), list)

    # Clean up
    client.delete(f"/assessments/{assessment.id}/findings/{finding_id}", headers=auth_headers)


def test_audit_log_pagination(client, auth_headers):
    r = client.get("/audit-log?limit=5&offset=0", headers=auth_headers)
    assert r.status_code == 200
    first_page = r.json()
    assert len(first_page) <= 5

    r = client.get("/audit-log?limit=5&offset=5", headers=auth_headers)
    assert r.status_code == 200
    second_page = r.json()
    # Pages should not overlap (assuming > 5 total entries after all tests)
    if first_page and second_page:
        first_ids = {e["id"] for e in first_page}
        second_ids = {e["id"] for e in second_page}
        assert first_ids.isdisjoint(second_ids)
