"""Immutable audit log — write via log_event(), read via /audit-log endpoints."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import require_admin, require_contributor
from app.database import get_db

_log = logging.getLogger("caams.audit_log")

router = APIRouter(prefix="/audit-log", tags=["audit-log"])


# ── Internal helper used by all routers ──────────────────────────────────────

def log_event(
    db: Session,
    *,
    user: Optional[models.User] = None,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    details: dict = None,
    ip_address: str = "",
    user_agent: str = "",
) -> None:
    """Append an immutable audit log entry. Never raises."""
    try:
        entry = models.AuditLogEntry(
            user_id=user.id if user else None,
            user_name=user.username if user else "system",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(entry)
        db.commit()
    except Exception as exc:
        db.rollback()
        _log.error("Failed to write audit log entry action=%s: %s", action, exc)


# ── Read endpoints ────────────────────────────────────────────────────────────

@router.get("", response_model=List[schemas.AuditLogOut])
def get_audit_log(
    resource_type: Optional[str] = Query(None),
    resource_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    user_name: Optional[str] = Query(None),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(models.AuditLogEntry).order_by(models.AuditLogEntry.timestamp.desc())
    if resource_type:
        q = q.filter(models.AuditLogEntry.resource_type == resource_type)
    if resource_id:
        q = q.filter(models.AuditLogEntry.resource_id == resource_id)
    if action:
        # Escape LIKE special characters before interpolating into the pattern
        # so a caller cannot widen the match with % or _ metacharacters.
        _esc = action.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        q = q.filter(models.AuditLogEntry.action.ilike(f"%{_esc}%", escape="\\"))
    if user_name:
        _esc = user_name.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        q = q.filter(models.AuditLogEntry.user_name.ilike(f"%{_esc}%", escape="\\"))
    return q.offset(offset).limit(limit).all()


@router.get("/assessment/{assessment_id}", response_model=List[schemas.AuditLogOut])
def get_assessment_audit_log(
    assessment_id: int,
    limit: int = Query(200, le=1000),
    _: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.AuditLogEntry)
        .filter(
            models.AuditLogEntry.resource_type == "assessment",
            models.AuditLogEntry.resource_id == str(assessment_id),
        )
        .order_by(models.AuditLogEntry.timestamp.desc())
        .limit(limit)
        .all()
    )
