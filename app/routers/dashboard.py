"""Executive dashboard — org-wide compliance posture across all assessments."""

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.auth import require_viewer
from app.database import get_db
from app.engine import mapper

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """
    Returns org-wide metrics:
    - Per-framework compliance summary (latest approved assessment per framework)
    - Overall score across all active assessments
    - Open findings breakdown by severity
    - RFI summary
    - Overdue controls count
    - Assessments due for renewal soon
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # All non-archived assessments
    assessments = (
        db.query(models.Assessment)
        .filter(models.Assessment.status != "archived")
        .order_by(models.Assessment.created_at.desc())
        .all()
    )

    framework_scores = {}
    total_score_sum = 0.0
    total_score_count = 0
    overdue_controls = 0
    all_findings = []
    all_rfis = []
    assessments_due_soon = []
    lifecycle_counts = defaultdict(int)

    # Batch-load all child rows in 4 queries instead of 4×N queries
    assessment_ids = [a.id for a in assessments]
    if assessment_ids:
        _notes_all = db.query(models.ControlNote).filter(
            models.ControlNote.assessment_id.in_(assessment_ids)
        ).all()
        _owns_all = db.query(models.ControlOwnership).filter(
            models.ControlOwnership.assessment_id.in_(assessment_ids)
        ).all()
        _findings_all = db.query(models.Finding).filter(
            models.Finding.assessment_id.in_(assessment_ids)
        ).all()
        _rfis_all = db.query(models.RFI).filter(
            models.RFI.assessment_id.in_(assessment_ids)
        ).all()
    else:
        _notes_all = _owns_all = _findings_all = _rfis_all = []

    # Index by assessment_id for O(1) lookup inside the loop
    _notes_by_aid: dict = defaultdict(dict)
    for n in _notes_all:
        _notes_by_aid[n.assessment_id][n.control_id] = n

    _owns_by_aid: dict = defaultdict(dict)
    for o in _owns_all:
        _owns_by_aid[o.assessment_id][o.control_id] = o

    _findings_by_aid: dict = defaultdict(lambda: defaultdict(list))
    for f in _findings_all:
        _findings_by_aid[f.assessment_id][f.control_id].append(f)
        all_findings.append(f)

    _rfis_by_aid: dict = defaultdict(list)
    for r in _rfis_all:
        _rfis_by_aid[r.assessment_id].append(r)
        all_rfis.append(r)

    for a in assessments:
        lifecycle_counts[a.status] += 1

        controls = a.framework.controls if a.framework else []
        nm = _notes_by_aid[a.id]
        om = _owns_by_aid[a.id]
        fm = dict(_findings_by_aid[a.id])

        cov = mapper.compute_coverage(controls, a.tools, nm, om, fm)

        fw_name = a.framework.name if a.framework else "Unknown"
        # Keep only the best-scoring assessment per framework (preferring approved)
        existing = framework_scores.get(fw_name)
        if existing is None:
            replace = True
        elif a.status == "approved" and existing["status"] != "approved":
            replace = True
        elif a.status != "approved" and existing["status"] == "approved":
            replace = False
        else:
            replace = cov["score"] > existing["score"]
        if replace:
            framework_scores[fw_name] = {
                "framework_name": fw_name,
                "assessment_id": a.id,
                "assessment_name": a.name,
                "status": a.status,
                "score": cov["score"],
                "covered": cov["covered"],
                "partial": cov["partial"],
                "not_covered": cov["not_covered"],
                "total_controls": cov["total_controls"],
                "tool_count": len(a.tools),
            }

        total_score_sum += cov["score"]
        total_score_count += 1

        # Count overdue controls
        for ctrl_result in cov["controls"]:
            if ctrl_result["is_overdue"]:
                overdue_controls += 1

        # Assessments due for renewal in next 30 days
        if a.next_review_date:
            days_until = (a.next_review_date - now).days
            if 0 <= days_until <= 30:
                assessments_due_soon.append({
                    "assessment_id": a.id,
                    "assessment_name": a.name,
                    "next_review_date": a.next_review_date.isoformat(),
                    "days_until": days_until,
                })

    # Findings breakdown
    findings_by_severity = defaultdict(int)
    findings_by_status = defaultdict(int)
    for f in all_findings:
        findings_by_severity[f.severity] += 1
        findings_by_status[f.status] += 1

    open_findings = sum(
        1 for f in all_findings if f.status in ("open", "in_progress")
    )

    # RFI summary
    rfi_by_status = defaultdict(int)
    for r in all_rfis:
        rfi_by_status[r.status] += 1

    overall_score = round(total_score_sum / total_score_count, 1) if total_score_count else 0.0

    return {
        "overall_score": overall_score,
        "assessment_count": len(assessments),
        "lifecycle_counts": dict(lifecycle_counts),
        "framework_scores": list(framework_scores.values()),
        "findings_by_severity": dict(findings_by_severity),
        "findings_by_status": dict(findings_by_status),
        "open_findings": open_findings,
        "overdue_controls": overdue_controls,
        "rfi_by_status": dict(rfi_by_status),
        "assessments_due_soon": sorted(assessments_due_soon, key=lambda x: x["days_until"]),
    }
