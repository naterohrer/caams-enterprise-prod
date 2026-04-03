"""RFI (Request for Information) tracker endpoints."""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import require_contributor, require_viewer
from app.limiter import limiter
from app.database import get_db
from app.routers.audit_log import log_event

router = APIRouter(prefix="/assessments", tags=["rfi"])


def _get_assessment(assessment_id: int, db: Session) -> models.Assessment:
    a = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return a


@router.get("/{assessment_id}/rfis", response_model=List[schemas.RFIOut])
@limiter.limit("60/minute")
def list_rfis(
    request: Request,
    assessment_id: int,
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    q = db.query(models.RFI).filter(models.RFI.assessment_id == assessment_id)
    if status:
        q = q.filter(models.RFI.status == status)
    rfis = q.order_by(models.RFI.created_at.desc()).offset(offset).limit(limit).all()

    # Batch-load all responses in one query instead of one query per RFI.
    rfi_ids = [rfi.id for rfi in rfis]
    responses_by_rfi: dict = {}
    if rfi_ids:
        all_responses = (
            db.query(models.RFIResponse)
            .filter(models.RFIResponse.rfi_id.in_(rfi_ids))
            .order_by(models.RFIResponse.created_at)
            .all()
        )
        for r in all_responses:
            responses_by_rfi.setdefault(r.rfi_id, []).append(r)

    return [
        schemas.RFIOut(
            id=rfi.id, assessment_id=rfi.assessment_id, title=rfi.title,
            description=rfi.description, status=rfi.status, priority=rfi.priority,
            control_id=rfi.control_id, requested_by=rfi.requested_by,
            assigned_to=rfi.assigned_to, due_date=rfi.due_date,
            created_at=rfi.created_at, updated_at=rfi.updated_at, closed_at=rfi.closed_at,
            responses=[schemas.RFIResponseOut(
                id=r.id, rfi_id=r.rfi_id, responder_name=r.responder_name,
                response_text=r.response_text, created_at=r.created_at,
            ) for r in responses_by_rfi.get(rfi.id, [])],
        )
        for rfi in rfis
    ]


@router.post("/{assessment_id}/rfis", response_model=schemas.RFIOut, status_code=201)
def create_rfi(
    assessment_id: int,
    payload: schemas.RFICreate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    rfi = models.RFI(
        assessment_id=assessment_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        control_id=payload.control_id,
        requested_by=payload.requested_by or current_user.username,
        assigned_to=payload.assigned_to,
        due_date=payload.due_date,
    )
    db.add(rfi)
    db.commit()
    db.refresh(rfi)
    log_event(db, user=current_user, action="CREATE_RFI", resource_type="rfi",
              resource_id=str(rfi.id), details={"title": rfi.title, "priority": rfi.priority})
    return schemas.RFIOut(
        id=rfi.id, assessment_id=rfi.assessment_id, title=rfi.title,
        description=rfi.description, status=rfi.status, priority=rfi.priority,
        control_id=rfi.control_id, requested_by=rfi.requested_by,
        assigned_to=rfi.assigned_to, due_date=rfi.due_date,
        created_at=rfi.created_at, updated_at=rfi.updated_at, closed_at=rfi.closed_at,
        responses=[],
    )


@router.patch("/{assessment_id}/rfis/{rfi_id}", response_model=schemas.RFIOut)
def update_rfi(
    assessment_id: int,
    rfi_id: int,
    payload: schemas.RFIUpdate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    rfi = db.query(models.RFI).filter(
        models.RFI.id == rfi_id, models.RFI.assessment_id == assessment_id
    ).first()
    if not rfi:
        raise HTTPException(status_code=404, detail="RFI not found")

    if payload.title is not None:
        rfi.title = payload.title
    if payload.description is not None:
        rfi.description = payload.description
    if payload.status is not None:
        rfi.status = payload.status
        if payload.status == "closed" and not rfi.closed_at:
            rfi.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if payload.priority is not None:
        rfi.priority = payload.priority
    if payload.assigned_to is not None:
        rfi.assigned_to = payload.assigned_to
    if payload.due_date is not None:
        rfi.due_date = payload.due_date
    rfi.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(rfi)
    responses = (db.query(models.RFIResponse)
                 .filter(models.RFIResponse.rfi_id == rfi.id)
                 .order_by(models.RFIResponse.created_at)
                 .all())
    return schemas.RFIOut(
        id=rfi.id, assessment_id=rfi.assessment_id, title=rfi.title,
        description=rfi.description, status=rfi.status, priority=rfi.priority,
        control_id=rfi.control_id, requested_by=rfi.requested_by,
        assigned_to=rfi.assigned_to, due_date=rfi.due_date,
        created_at=rfi.created_at, updated_at=rfi.updated_at, closed_at=rfi.closed_at,
        responses=[schemas.RFIResponseOut(
            id=r.id, rfi_id=r.rfi_id, responder_name=r.responder_name,
            response_text=r.response_text, created_at=r.created_at,
        ) for r in responses],
    )


@router.post("/{assessment_id}/rfis/{rfi_id}/responses", response_model=schemas.RFIResponseOut, status_code=201)
def add_rfi_response(
    assessment_id: int,
    rfi_id: int,
    payload: schemas.RFIResponseCreate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    rfi = db.query(models.RFI).filter(
        models.RFI.id == rfi_id, models.RFI.assessment_id == assessment_id
    ).first()
    if not rfi:
        raise HTTPException(status_code=404, detail="RFI not found")
    if rfi.status == "closed":
        raise HTTPException(status_code=400, detail="Cannot add responses to a closed RFI")

    resp = models.RFIResponse(
        rfi_id=rfi_id,
        responder_name=payload.responder_name or current_user.username,
        response_text=payload.response_text,
    )
    db.add(resp)
    # Auto-update RFI status
    if rfi.status == "open":
        rfi.status = "responded"
        rfi.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        log_event(db, user=current_user, action="RFI_AUTO_RESPONDED",
                  resource_type="rfi", resource_id=str(rfi_id),
                  details={"assessment_id": assessment_id})
    db.commit()
    db.refresh(resp)
    return resp
