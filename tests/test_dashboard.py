"""Integration tests for the executive dashboard endpoint."""



def test_dashboard_empty(client, auth_headers):
    """Dashboard returns valid structure even when no assessments exist."""
    resp = client.get("/dashboard", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "overall_score" in body
    assert "assessment_count" in body
    assert "framework_scores" in body
    assert "findings_by_severity" in body
    assert "open_findings" in body
    assert "overdue_controls" in body
    assert "rfi_by_status" in body
    assert "assessments_due_soon" in body


def test_dashboard_unauthenticated(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 401


def test_dashboard_with_assessment(client, auth_headers, assessment):
    """Dashboard reflects a real assessment score."""
    resp = client.get("/dashboard", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["assessment_count"] >= 1
    # overall_score should be a number
    assert isinstance(body["overall_score"], (int, float))


def test_dashboard_lifecycle_counts(client, auth_headers, assessment):
    resp = client.get("/dashboard", headers=auth_headers)
    body = resp.json()
    lc = body["lifecycle_counts"]
    # The fixture assessment is in 'draft' status
    assert lc.get("draft", 0) >= 1


def test_dashboard_framework_scores_present(client, auth_headers, assessment):
    resp = client.get("/dashboard", headers=auth_headers)
    body = resp.json()
    scores = body["framework_scores"]
    assert isinstance(scores, list)
    assert len(scores) >= 1
    fw_names = [s["framework_name"] for s in scores]
    assert "TestFW" in fw_names
