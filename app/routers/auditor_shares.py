"""Scoped auditor access — time-limited share links and comment threads."""

import hashlib
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user, require_contributor, require_viewer
from app.database import get_db
from app.engine import mapper
from app.routers.assessments import _findings_map, _notes_map, _ownership_map
from app.routers.audit_log import log_event

router = APIRouter(prefix="/assessments", tags=["auditor-shares"])


def _get_assessment(assessment_id: int, db: Session) -> models.Assessment:
    a = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return a


def _resolve_share(token: str, assessment_id: int, db: Session) -> models.AuditorShare:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    share = db.query(models.AuditorShare).filter(
        models.AuditorShare.token_hash == token_hash,
        models.AuditorShare.assessment_id == assessment_id,
        models.AuditorShare.is_active.is_(True),
    ).first()
    if not share:
        raise HTTPException(status_code=403, detail="Invalid or revoked share token")
    if share.expires_at and share.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(status_code=403, detail="Share token has expired")
    share.access_count += 1
    share.last_accessed = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return share


# ── Share management (internal users) ────────────────────────────────────────

@router.get("/{assessment_id}/auditor-shares", response_model=List[schemas.AuditorShareOut])
def list_shares(
    assessment_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    return (
        db.query(models.AuditorShare)
        .filter(models.AuditorShare.assessment_id == assessment_id)
        .order_by(models.AuditorShare.created_at.desc())
        .all()
    )


@router.post("/{assessment_id}/auditor-shares", response_model=schemas.AuditorShareCreated, status_code=201)
def create_share(
    assessment_id: int,
    payload: schemas.AuditorShareCreate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    raw = secrets.token_urlsafe(32)
    prefix = raw[:8]
    token_hash = hashlib.sha256(raw.encode()).hexdigest()

    share = models.AuditorShare(
        assessment_id=assessment_id,
        created_by_id=current_user.id,
        auditor_name=payload.auditor_name,
        auditor_email=payload.auditor_email,
        token_hash=token_hash,
        token_prefix=prefix,
        expires_at=payload.expires_at,
        allowed_controls=payload.allowed_controls,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    log_event(db, user=current_user, action="CREATE_AUDITOR_SHARE", resource_type="auditor_share",
              resource_id=str(share.id),
              details={"auditor_name": payload.auditor_name, "assessment_id": assessment_id})
    return schemas.AuditorShareCreated(
        id=share.id, assessment_id=share.assessment_id,
        auditor_name=share.auditor_name, auditor_email=share.auditor_email,
        token_prefix=share.token_prefix, created_at=share.created_at,
        expires_at=share.expires_at, is_active=share.is_active,
        access_count=share.access_count, last_accessed=share.last_accessed,
        token=raw,
    )


@router.delete("/{assessment_id}/auditor-shares/{share_id}", status_code=204)
def revoke_share(
    assessment_id: int,
    share_id: int,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    share = db.query(models.AuditorShare).filter(
        models.AuditorShare.id == share_id,
        models.AuditorShare.assessment_id == assessment_id,
    ).first()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    share.is_active = False
    db.commit()
    log_event(db, user=current_user, action="REVOKE_AUDITOR_SHARE", resource_type="auditor_share",
              resource_id=str(share_id))


# ── Public auditor view (accessed via share token) ────────────────────────────

@router.get("/{assessment_id}/auditor-view")
def auditor_view(
    assessment_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Read-only view of an assessment for external auditors (no auth required beyond token)."""
    share = _resolve_share(token, assessment_id, db)
    a = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assessment not found")

    controls = a.framework.controls if a.framework else []
    nm = _notes_map(assessment_id, db)
    om = _ownership_map(assessment_id, db)
    fm = _findings_map(assessment_id, db)
    cov = mapper.compute_coverage(controls, a.tools, nm, om, fm)

    ctrl_results = cov["controls"]
    if share.allowed_controls:
        ctrl_results = [c for c in ctrl_results if c["control_id"] in share.allowed_controls]

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Fetch evidence files for allowed controls — exclude expired files
    ev_query = db.query(models.EvidenceFile).filter(
        models.EvidenceFile.assessment_id == assessment_id,
        (models.EvidenceFile.expires_at.is_(None)) | (models.EvidenceFile.expires_at > now),
    )
    evidence_list = [
        {
            "id": e.id, "control_id": e.control_id, "original_filename": e.original_filename,
            "description": e.description, "uploaded_at": e.uploaded_at.isoformat(),
            "approval_status": e.approval_status, "file_size": e.file_size,
        }
        for e in ev_query.all()
        if not share.allowed_controls or e.control_id in share.allowed_controls
    ]

    # Findings (open only, no sensitive internal info)
    findings = db.query(models.Finding).filter(
        models.Finding.assessment_id == assessment_id,
        models.Finding.status.in_(["open", "in_progress"]),
    ).all()
    if share.allowed_controls:
        findings = [f for f in findings if f.control_id in share.allowed_controls]

    # Signoffs
    signoffs = (
        db.query(models.AssessmentSignoff)
        .filter(models.AssessmentSignoff.assessment_id == assessment_id)
        .order_by(models.AssessmentSignoff.timestamp)
        .all()
    )

    return {
        "assessment": {
            "id": a.id,
            "name": a.name,
            "framework": a.framework.name if a.framework else "",
            "framework_version": a.framework.version if a.framework else "",
            "status": a.status,
            "scope_notes": a.scope_notes,
        },
        "score": cov["score"],
        "covered": cov["covered"],
        "partial": cov["partial"],
        "not_covered": cov["not_covered"],
        "total_controls": cov["total_controls"],
        "controls": ctrl_results,
        "evidence_files": evidence_list,
        "open_findings": [
            {"id": f.id, "control_id": f.control_id, "title": f.title,
             "severity": f.severity, "status": f.status}
            for f in findings
        ],
        "signoffs": [
            {"action": s.action, "user_name": s.user_name,
             "comments": s.comments, "timestamp": s.timestamp.isoformat()}
            for s in signoffs
        ],
        "auditor_name": share.auditor_name,
        "share_expires_at": share.expires_at.isoformat() if share.expires_at else None,
    }


# ── Auditor Comments ──────────────────────────────────────────────────────────

@router.get("/{assessment_id}/comments", response_model=List[schemas.AuditorCommentOut])
def list_comments(
    assessment_id: int,
    control_id: Optional[str] = Query(None),
    current_user: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    q = db.query(models.AuditorComment).filter(
        models.AuditorComment.assessment_id == assessment_id
    )
    if control_id:
        q = q.filter(models.AuditorComment.control_id == control_id)
    # Non-admins/contributors don't see internal comments if they're auditor role
    comments = q.order_by(models.AuditorComment.created_at).all()
    if current_user.role == "auditor":
        comments = [c for c in comments if not c.is_internal]
    return comments


@router.post("/{assessment_id}/comments", response_model=schemas.AuditorCommentOut, status_code=201)
def add_comment(
    assessment_id: int,
    payload: schemas.AuditorCommentCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    if payload.is_internal and current_user.role not in ("admin", "contributor"):
        raise HTTPException(status_code=403, detail="Only admin or contributor users may post internal comments")
    is_internal = payload.is_internal
    comment = models.AuditorComment(
        assessment_id=assessment_id,
        control_id=payload.control_id,
        user_id=current_user.id,
        author_name=current_user.full_name or current_user.username,
        comment_text=payload.comment_text,
        is_internal=is_internal,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.post("/{assessment_id}/comments/external", response_model=schemas.AuditorCommentOut, status_code=201)
def add_external_comment(
    assessment_id: int,
    payload: schemas.AuditorCommentCreate,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """External auditor adds a comment via share token (no JWT required)."""
    share = _resolve_share(token, assessment_id, db)
    _get_assessment(assessment_id, db)

    comment = models.AuditorComment(
        assessment_id=assessment_id,
        control_id=payload.control_id,
        auditor_share_id=share.id,
        author_name=share.auditor_name,
        comment_text=payload.comment_text,
        is_internal=False,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment
