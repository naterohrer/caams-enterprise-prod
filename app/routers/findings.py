"""Findings / issue tracker endpoints."""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import require_contributor, require_viewer
from app.limiter import limiter
from app.database import get_db
from app.routers.audit_log import log_event

router = APIRouter(prefix="/assessments", tags=["findings"])


def _get_assessment(assessment_id: int, db: Session) -> models.Assessment:
    a = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return a


@router.get("/{assessment_id}/findings", response_model=List[schemas.FindingOut])
@limiter.limit("60/minute")
def list_findings(
    request: Request,
    assessment_id: int,
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    control_id: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    q = db.query(models.Finding).filter(models.Finding.assessment_id == assessment_id)
    if status:
        q = q.filter(models.Finding.status == status)
    if severity:
        q = q.filter(models.Finding.severity == severity)
    if control_id:
        q = q.filter(models.Finding.control_id == control_id)
    return q.order_by(models.Finding.created_at.desc()).offset(offset).limit(limit).all()


@router.post("/{assessment_id}/findings", response_model=schemas.FindingOut, status_code=201)
def create_finding(
    assessment_id: int,
    payload: schemas.FindingCreate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    finding = models.Finding(
        assessment_id=assessment_id,
        control_id=payload.control_id,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        remediation_owner=payload.remediation_owner,
        target_date=payload.target_date,
        notes=payload.notes,
        created_by_id=current_user.id,
        created_by_name=current_user.username,
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    log_event(db, user=current_user, action="CREATE_FINDING", resource_type="finding",
              resource_id=str(finding.id),
              details={"assessment_id": assessment_id, "control_id": payload.control_id,
                       "severity": payload.severity})
    return finding


@router.get("/{assessment_id}/findings/{finding_id}", response_model=schemas.FindingOut)
def get_finding(
    assessment_id: int,
    finding_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    finding = db.query(models.Finding).filter(
        models.Finding.id == finding_id,
        models.Finding.assessment_id == assessment_id,
    ).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


@router.patch("/{assessment_id}/findings/{finding_id}", response_model=schemas.FindingOut)
def update_finding(
    assessment_id: int,
    finding_id: int,
    payload: schemas.FindingUpdate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    finding = db.query(models.Finding).filter(
        models.Finding.id == finding_id,
        models.Finding.assessment_id == assessment_id,
    ).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    if payload.title is not None:
        finding.title = payload.title
    if payload.description is not None:
        finding.description = payload.description
    if payload.severity is not None:
        finding.severity = payload.severity
    if payload.status is not None:
        finding.status = payload.status
        if payload.status in ("remediated", "closed", "accepted") and not finding.actual_close_date:
            finding.actual_close_date = datetime.now(timezone.utc).replace(tzinfo=None)
        elif payload.status in ("open", "in_progress"):
            finding.actual_close_date = None
    if payload.remediation_owner is not None:
        finding.remediation_owner = payload.remediation_owner
    if payload.target_date is not None:
        finding.target_date = payload.target_date
    if payload.actual_close_date is not None:
        finding.actual_close_date = payload.actual_close_date
    if payload.notes is not None:
        finding.notes = payload.notes

    finding.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(finding)
    log_event(db, user=current_user, action="UPDATE_FINDING", resource_type="finding",
              resource_id=str(finding_id))
    return finding


@router.delete("/{assessment_id}/findings/{finding_id}", status_code=204)
def delete_finding(
    assessment_id: int,
    finding_id: int,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    finding = db.query(models.Finding).filter(
        models.Finding.id == finding_id,
        models.Finding.assessment_id == assessment_id,
    ).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    db.delete(finding)
    db.commit()
    log_event(db, user=current_user, action="DELETE_FINDING", resource_type="finding",
              resource_id=str(finding_id))


# ── Risk Acceptances ──────────────────────────────────────────────────────────

@router.get("/{assessment_id}/risk-acceptances", response_model=List[schemas.RiskAcceptanceOut])
def list_risk_acceptances(
    assessment_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    return (
        db.query(models.RiskAcceptance)
        .filter(models.RiskAcceptance.assessment_id == assessment_id)
        .order_by(models.RiskAcceptance.created_at.desc())
        .all()
    )


@router.post("/{assessment_id}/risk-acceptances", response_model=schemas.RiskAcceptanceOut, status_code=201)
def create_risk_acceptance(
    assessment_id: int,
    payload: schemas.RiskAcceptanceCreate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    ra = models.RiskAcceptance(
        assessment_id=assessment_id,
        control_id=payload.control_id,
        justification=payload.justification,
        risk_rating=payload.risk_rating,
        residual_risk_notes=payload.residual_risk_notes,
        expires_at=payload.expires_at,
        approved_by_id=current_user.id,
        approved_by_name=current_user.username,
        approved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        created_by_id=current_user.id,
        created_by_name=current_user.username,
    )
    db.add(ra)
    db.commit()
    db.refresh(ra)
    log_event(db, user=current_user, action="CREATE_RISK_ACCEPTANCE", resource_type="risk_acceptance",
              resource_id=str(ra.id),
              details={"control_id": payload.control_id, "risk_rating": payload.risk_rating})
    return ra
