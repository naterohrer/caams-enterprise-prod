"""Tests for findings and risk acceptances."""


def test_list_findings_empty(client, auth_headers, assessment):
    r = client.get(f"/assessments/{assessment.id}/findings", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_findings_unauthenticated(client, assessment):
    r = client.get(f"/assessments/{assessment.id}/findings")
    assert r.status_code == 401


def test_create_and_delete_finding(client, auth_headers, assessment):
    r = client.post(f"/assessments/{assessment.id}/findings", headers=auth_headers, json={
        "control_id": "T-1", "title": "Test Finding",
        "description": "Something is wrong", "severity": "high",
        "remediation_owner": "Alice", "target_date": None, "notes": "",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "Test Finding"
    assert data["severity"] == "high"
    assert data["status"] == "open"
    assert data["created_by_name"] == "testadmin"
    finding_id = data["id"]

    r = client.delete(f"/assessments/{assessment.id}/findings/{finding_id}",
                      headers=auth_headers)
    assert r.status_code == 204


def test_get_finding(client, auth_headers, assessment):
    r = client.post(f"/assessments/{assessment.id}/findings", headers=auth_headers, json={
        "control_id": "T-2", "title": "GetMe", "description": "",
        "severity": "low", "remediation_owner": "", "target_date": None, "notes": "",
    })
    finding_id = r.json()["id"]

    r = client.get(f"/assessments/{assessment.id}/findings/{finding_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["title"] == "GetMe"
    assert r.json()["control_id"] == "T-2"

    client.delete(f"/assessments/{assessment.id}/findings/{finding_id}", headers=auth_headers)


def test_finding_not_found_returns_404(client, auth_headers, assessment):
    r = client.get(f"/assessments/{assessment.id}/findings/999999", headers=auth_headers)
    assert r.status_code == 404


def test_update_finding_status_to_remediated(client, auth_headers, assessment):
    r = client.post(f"/assessments/{assessment.id}/findings", headers=auth_headers, json={
        "control_id": "T-1", "title": "FixMe", "description": "",
        "severity": "medium", "remediation_owner": "", "target_date": None, "notes": "",
    })
    finding_id = r.json()["id"]

    r = client.patch(f"/assessments/{assessment.id}/findings/{finding_id}",
                     headers=auth_headers, json={"status": "remediated"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "remediated"
    assert data["actual_close_date"] is not None

    client.delete(f"/assessments/{assessment.id}/findings/{finding_id}", headers=auth_headers)


def test_update_finding_title_and_severity(client, auth_headers, assessment):
    r = client.post(f"/assessments/{assessment.id}/findings", headers=auth_headers, json={
        "control_id": "T-1", "title": "Original Title", "description": "",
        "severity": "low", "remediation_owner": "", "target_date": None, "notes": "",
    })
    finding_id = r.json()["id"]

    r = client.patch(f"/assessments/{assessment.id}/findings/{finding_id}",
                     headers=auth_headers,
                     json={"title": "Updated Title", "severity": "critical",
                           "notes": "escalated"})
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "Updated Title"
    assert data["severity"] == "critical"
    assert data["notes"] == "escalated"

    client.delete(f"/assessments/{assessment.id}/findings/{finding_id}", headers=auth_headers)


def test_filter_findings_by_severity(client, auth_headers, assessment):
    r = client.post(f"/assessments/{assessment.id}/findings", headers=auth_headers, json={
        "control_id": "T-1", "title": "CritFinding", "description": "",
        "severity": "critical", "remediation_owner": "", "target_date": None, "notes": "",
    })
    finding_id = r.json()["id"]

    r = client.get(f"/assessments/{assessment.id}/findings?severity=critical",
                   headers=auth_headers)
    assert r.status_code == 200
    assert all(f["severity"] == "critical" for f in r.json())

    client.delete(f"/assessments/{assessment.id}/findings/{finding_id}", headers=auth_headers)


def test_filter_findings_by_status(client, auth_headers, assessment):
    r = client.post(f"/assessments/{assessment.id}/findings", headers=auth_headers, json={
        "control_id": "T-1", "title": "StatusFilter", "description": "",
        "severity": "low", "remediation_owner": "", "target_date": None, "notes": "",
    })
    finding_id = r.json()["id"]

    r = client.get(f"/assessments/{assessment.id}/findings?status=open", headers=auth_headers)
    assert r.status_code == 200
    assert all(f["status"] == "open" for f in r.json())

    client.delete(f"/assessments/{assessment.id}/findings/{finding_id}", headers=auth_headers)


def test_create_and_list_risk_acceptance(client, auth_headers, assessment):
    r = client.post(f"/assessments/{assessment.id}/risk-acceptances", headers=auth_headers, json={
        "control_id": "T-1",
        "justification": "Accepted due to cost constraints",
        "risk_rating": "medium",
        "residual_risk_notes": "Reviewed quarterly",
        "expires_at": None,
    })
    assert r.status_code == 201
    data = r.json()
    assert data["control_id"] == "T-1"
    assert data["risk_rating"] == "medium"
    assert data["justification"] == "Accepted due to cost constraints"
    assert data["approved_by_name"] == "testadmin"

    r = client.get(f"/assessments/{assessment.id}/risk-acceptances", headers=auth_headers)
    assert r.status_code == 200
    assert any(ra["control_id"] == "T-1" for ra in r.json())
