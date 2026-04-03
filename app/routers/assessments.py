"""Assessment CRUD, lifecycle, control metadata, coverage, and recommendations."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import require_admin, require_contributor, require_viewer
from app.database import get_db
from app.engine import mapper
from app.limiter import limiter
from app.logging_config import get_logger
from app.routers.audit_log import log_event

router = APIRouter(prefix="/assessments", tags=["assessments"])
log = get_logger("caams.assessments")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_assessment(assessment_id: int, db: Session) -> models.Assessment:
    a = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return a


def _notes_map(assessment_id: int, db: Session) -> dict:
    notes = db.query(models.ControlNote).filter(
        models.ControlNote.assessment_id == assessment_id
    ).all()
    return {n.control_id: n for n in notes}


def _ownership_map(assessment_id: int, db: Session) -> dict:
    owns = db.query(models.ControlOwnership).filter(
        models.ControlOwnership.assessment_id == assessment_id
    ).all()
    return {o.control_id: o for o in owns}


def _findings_map(assessment_id: int, db: Session) -> dict:
    findings = db.query(models.Finding).filter(
        models.Finding.assessment_id == assessment_id
    ).all()
    result = {}
    for f in findings:
        result.setdefault(f.control_id, []).append(f)
    return result


def _assessment_out(a: models.Assessment) -> schemas.AssessmentOut:
    created_by_name = ""
    if a.created_by:
        created_by_name = a.created_by.full_name or a.created_by.username
    return schemas.AssessmentOut(
        id=a.id,
        name=a.name,
        framework_id=a.framework_id,
        framework_name=a.framework.name if a.framework else "",
        created_at=a.created_at,
        updated_at=a.updated_at,
        status=a.status,
        scope_notes=a.scope_notes or "",
        is_recurring=a.is_recurring,
        recurrence_days=a.recurrence_days,
        next_review_date=a.next_review_date,
        created_by_id=a.created_by_id,
        created_by_name=created_by_name,
        tool_ids=[t.id for t in a.tools],
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.post("", response_model=schemas.AssessmentOut, status_code=201)
def create_assessment(
    payload: schemas.AssessmentCreate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    fw = db.query(models.Framework).filter(models.Framework.id == payload.framework_id).first()
    if not fw:
        raise HTTPException(status_code=404, detail="Framework not found")

    next_review = None
    if payload.is_recurring and payload.recurrence_days:
        next_review = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=payload.recurrence_days)

    a = models.Assessment(
        name=payload.name,
        framework_id=payload.framework_id,
        created_by_id=current_user.id,
        scope_notes=payload.scope_notes,
        is_recurring=payload.is_recurring,
        recurrence_days=payload.recurrence_days,
        next_review_date=next_review,
        status="draft",
    )
    db.add(a)
    db.flush()

    tools = db.query(models.Tool).filter(models.Tool.id.in_(payload.tool_ids)).all()
    a.tools = tools

    db.commit()
    db.refresh(a)
    log.info("ASSESSMENT created | id=%d | name=%s | framework=%s | by=%s",
             a.id, a.name, fw.name, current_user.username)
    log_event(db, user=current_user, action="CREATE_ASSESSMENT", resource_type="assessment",
              resource_id=str(a.id), details={"name": a.name, "framework": fw.name})
    return _assessment_out(a)


@router.get("", response_model=List[schemas.AssessmentOut])
@limiter.limit("60/minute")
def list_assessments(
    request: Request,
    status: Optional[str] = Query(None),
    framework_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    q = db.query(models.Assessment).order_by(models.Assessment.created_at.desc())
    if status:
        q = q.filter(models.Assessment.status == status)
    if framework_id:
        q = q.filter(models.Assessment.framework_id == framework_id)
    assessments = q.offset(offset).limit(limit).all()
    return [_assessment_out(a) for a in assessments]


@router.get("/history")
def list_history(_: models.User = Depends(require_viewer), db: Session = Depends(get_db)):
    """Return all assessments with pre-computed summary metrics."""
    from collections import defaultdict
    assessments = db.query(models.Assessment).order_by(models.Assessment.created_at.desc()).all()

    # Batch-load child rows — 3 queries total instead of 3×N
    ids = [a.id for a in assessments]
    if ids:
        _notes = db.query(models.ControlNote).filter(
            models.ControlNote.assessment_id.in_(ids)
        ).all()
        _owns = db.query(models.ControlOwnership).filter(
            models.ControlOwnership.assessment_id.in_(ids)
        ).all()
        _findings = db.query(models.Finding).filter(
            models.Finding.assessment_id.in_(ids)
        ).all()
    else:
        _notes = _owns = _findings = []

    notes_by = defaultdict(dict)
    for n in _notes:
        notes_by[n.assessment_id][n.control_id] = n

    owns_by = defaultdict(dict)
    for o in _owns:
        owns_by[o.assessment_id][o.control_id] = o

    findings_by: dict = defaultdict(lambda: defaultdict(list))
    open_by: dict = defaultdict(int)
    for f in _findings:
        findings_by[f.assessment_id][f.control_id].append(f)
        if f.status in ("open", "in_progress"):
            open_by[f.assessment_id] += 1

    result = []
    for a in assessments:
        controls = a.framework.controls if a.framework else []
        nm = notes_by[a.id]
        om = owns_by[a.id]
        fm = dict(findings_by[a.id])
        cov = mapper.compute_coverage(controls, a.tools, nm, om, fm)
        result.append({
            **_assessment_out(a).model_dump(),
            "score": cov["score"],
            "covered": cov["covered"],
            "partial": cov["partial"],
            "not_covered": cov["not_covered"],
            "not_applicable": cov["not_applicable"],
            "total_controls": cov["total_controls"],
            "tool_count": len(a.tools),
            "open_findings": open_by[a.id],
        })
    return result


@router.get("/{assessment_id}", response_model=schemas.AssessmentOut)
def get_assessment(
    assessment_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    return _assessment_out(_get_assessment(assessment_id, db))


@router.get("/{assessment_id}/tools")
def get_assessment_tools(
    assessment_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    a = _get_assessment(assessment_id, db)
    return [{"id": t.id, "name": t.name, "category": t.category,
             "capabilities": [c.tag for c in t.capabilities]} for t in a.tools]


@router.patch("/{assessment_id}/tools")
def update_assessment_tools(
    assessment_id: int,
    payload: schemas.AssessmentToolsUpdate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    a = _get_assessment(assessment_id, db)
    tools = db.query(models.Tool).filter(models.Tool.id.in_(payload.tool_ids)).all()
    a.tools = tools
    a.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    log_event(db, user=current_user, action="UPDATE_TOOLS", resource_type="assessment",
              resource_id=str(assessment_id))
    return {"tool_count": len(tools)}


@router.get("/{assessment_id}/results", response_model=schemas.AssessmentResults)
def get_results(
    assessment_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    a = _get_assessment(assessment_id, db)
    controls = a.framework.controls if a.framework else []
    nm = _notes_map(a.id, db)
    om = _ownership_map(a.id, db)
    fm = _findings_map(a.id, db)
    cov = mapper.compute_coverage(controls, a.tools, nm, om, fm)

    return schemas.AssessmentResults(
        assessment_id=a.id,
        assessment_name=a.name,
        framework_name=a.framework.name if a.framework else "",
        framework_version=a.framework.version if a.framework else "",
        status=a.status,
        total_controls=cov["total_controls"],
        covered=cov["covered"],
        partial=cov["partial"],
        not_covered=cov["not_covered"],
        not_applicable=cov["not_applicable"],
        score=cov["score"],
        controls=[schemas.ControlResult(**c) for c in cov["controls"]],
    )


@router.get("/{assessment_id}/recommendations")
def get_recommendations(
    assessment_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    a = _get_assessment(assessment_id, db)
    controls = a.framework.controls if a.framework else []
    all_tools = db.query(models.Tool).all()
    return mapper.compute_recommendations(controls, a.tools, all_tools)


@router.delete("/{assessment_id}", status_code=204)
def delete_assessment(
    assessment_id: int,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    a = _get_assessment(assessment_id, db)
    name = a.name
    db.delete(a)
    db.commit()
    log.warning("ASSESSMENT deleted | id=%d | name=%s | by=%s", assessment_id, name, current_user.username)
    log_event(db, user=current_user, action="DELETE_ASSESSMENT", resource_type="assessment",
              resource_id=str(assessment_id), details={"name": name})


@router.post("/{assessment_id}/clone", response_model=schemas.AssessmentOut, status_code=201)
def clone_assessment(
    assessment_id: int,
    payload: schemas.AssessmentClone,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    src = _get_assessment(assessment_id, db)
    new_name = payload.name or f"{src.name} (Copy)"
    clone = models.Assessment(
        name=new_name,
        framework_id=src.framework_id,
        created_by_id=current_user.id,
        scope_notes=src.scope_notes,
        is_recurring=src.is_recurring,
        recurrence_days=src.recurrence_days,
        status="draft",
    )
    db.add(clone)
    db.flush()
    clone.tools = list(src.tools)

    # Clone notes and ownership
    for note in src.control_notes:
        db.add(models.ControlNote(
            assessment_id=clone.id,
            control_id=note.control_id,
            notes=note.notes,
            evidence_url=note.evidence_url,
            override_status=note.override_status,
            override_justification=note.override_justification,
            override_expires=note.override_expires,
            assignee=note.assignee,
            due_date=note.due_date,
            is_applicable=note.is_applicable,
            exclusion_reason=note.exclusion_reason,
        ))
    for own in src.control_ownership:
        db.add(models.ControlOwnership(
            assessment_id=clone.id,
            control_id=own.control_id,
            owner=own.owner,
            team=own.team,
            evidence_owner=own.evidence_owner,
        ))

    db.commit()
    db.refresh(clone)
    log_event(db, user=current_user, action="CLONE_ASSESSMENT", resource_type="assessment",
              resource_id=str(clone.id), details={"source_id": assessment_id, "name": new_name})
    return _assessment_out(clone)


# ── Assessment Lifecycle ──────────────────────────────────────────────────────

VALID_TRANSITIONS = {
    "draft": ["submit_for_review", "archive"],
    "in_review": ["approve", "return", "archive"],
    "approved": ["archive"],
    "archived": [],
}

ACTION_STATUS_MAP = {
    "submit_for_review": "in_review",
    "approve": "approved",
    "return": "draft",
    "archive": "archived",
}


@router.post("/{assessment_id}/lifecycle", response_model=schemas.SignoffOut)
def assessment_lifecycle(
    assessment_id: int,
    payload: schemas.AssessmentStatusUpdate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    a = _get_assessment(assessment_id, db)

    # Non-admins may only manage assessments they created (CF-015)
    if current_user.role not in ("admin",) and a.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only manage lifecycle of assessments you created")

    # Approvals require admin
    if payload.action in ("approve",) and current_user.role not in ("admin",):
        raise HTTPException(status_code=403, detail="Only admins can approve assessments")

    allowed = VALID_TRANSITIONS.get(a.status, [])
    if payload.action not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot '{payload.action}' an assessment in '{a.status}' state. Allowed: {allowed}",
        )

    new_status = ACTION_STATUS_MAP[payload.action]
    a.status = new_status
    a.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    signoff = models.AssessmentSignoff(
        assessment_id=a.id,
        action=payload.action,
        user_id=current_user.id,
        user_name=current_user.username,
        comments=payload.comments,
    )
    db.add(signoff)
    db.commit()
    db.refresh(signoff)

    log.info("LIFECYCLE | assessment=%d | action=%s | by=%s", assessment_id, payload.action, current_user.username)
    log_event(db, user=current_user, action=f"LIFECYCLE_{payload.action.upper()}",
              resource_type="assessment", resource_id=str(assessment_id),
              details={"new_status": new_status, "comments": payload.comments})

    return schemas.SignoffOut(
        id=signoff.id, action=signoff.action, user_name=signoff.user_name,
        comments=signoff.comments, timestamp=signoff.timestamp,
    )


@router.get("/{assessment_id}/signoffs", response_model=List[schemas.SignoffOut])
def get_signoffs(
    assessment_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    signoffs = (
        db.query(models.AssessmentSignoff)
        .filter(models.AssessmentSignoff.assessment_id == assessment_id)
        .order_by(models.AssessmentSignoff.timestamp)
        .all()
    )
    return [
        schemas.SignoffOut(id=s.id, action=s.action, user_name=s.user_name,
                           comments=s.comments, timestamp=s.timestamp)
        for s in signoffs
    ]


# ── Control Notes / Override / Review ────────────────────────────────────────

@router.get("/{assessment_id}/controls/{control_id}/notes", response_model=schemas.ControlNoteOut)
def get_control_notes(
    assessment_id: int,
    control_id: str,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    note = db.query(models.ControlNote).filter(
        models.ControlNote.assessment_id == assessment_id,
        models.ControlNote.control_id == control_id,
    ).first()
    if not note:
        return schemas.ControlNoteOut(
            control_id=control_id, notes="", evidence_url="",
            override_status=None, override_justification="", override_expires=None,
            review_status="not_reviewed", review_notes="",
            reviewed_by_id=None, reviewed_at=None,
            assignee="", due_date=None, is_applicable=True, exclusion_reason="",
        )
    return note


@router.patch("/{assessment_id}/controls/{control_id}/notes", response_model=schemas.ControlNoteOut)
def upsert_control_notes(
    assessment_id: int,
    control_id: str,
    payload: schemas.ControlNoteUpdate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    note = db.query(models.ControlNote).filter(
        models.ControlNote.assessment_id == assessment_id,
        models.ControlNote.control_id == control_id,
    ).first()
    if not note:
        note = models.ControlNote(assessment_id=assessment_id, control_id=control_id)
        db.add(note)

    _VALID_OVERRIDE = {"covered", "partial", "not_covered", "not_applicable", ""}
    if payload.override_status is not None and payload.override_status not in _VALID_OVERRIDE:
        raise HTTPException(
            status_code=422,
            detail="override_status must be one of: covered, partial, not_covered, not_applicable",
        )

    if payload.notes is not None:
        note.notes = payload.notes
    if payload.evidence_url is not None:
        note.evidence_url = payload.evidence_url
    if payload.override_status is not None:
        note.override_status = payload.override_status or None
        if payload.override_status:
            log.warning("OVERRIDE | assessment=%d | control=%s | status=%s | by=%s",
                        assessment_id, control_id, payload.override_status, current_user.username)
            log_event(db, user=current_user, action="OVERRIDE", resource_type="assessment",
                      resource_id=str(assessment_id),
                      details={"control": control_id, "status": payload.override_status})
    if payload.override_justification is not None:
        note.override_justification = payload.override_justification
    if payload.override_expires is not None:
        note.override_expires = payload.override_expires
    if payload.assignee is not None:
        note.assignee = payload.assignee
    if payload.due_date is not None:
        note.due_date = payload.due_date
    if payload.is_applicable is not None:
        note.is_applicable = payload.is_applicable
    if payload.exclusion_reason is not None:
        note.exclusion_reason = payload.exclusion_reason

    db.commit()
    db.refresh(note)
    return note


@router.patch("/{assessment_id}/controls/{control_id}/review", response_model=schemas.ControlNoteOut)
def update_control_review(
    assessment_id: int,
    control_id: str,
    payload: schemas.ControlReviewUpdate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    note = db.query(models.ControlNote).filter(
        models.ControlNote.assessment_id == assessment_id,
        models.ControlNote.control_id == control_id,
    ).first()
    if not note:
        note = models.ControlNote(assessment_id=assessment_id, control_id=control_id)
        db.add(note)

    note.review_status = payload.review_status
    note.review_notes = payload.review_notes
    note.reviewed_by_id = current_user.id
    note.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(note)
    log_event(db, user=current_user, action="REVIEW_CONTROL", resource_type="assessment",
              resource_id=str(assessment_id),
              details={"control": control_id, "review_status": payload.review_status})
    return note


@router.patch("/{assessment_id}/controls/{control_id}/ownership", response_model=schemas.ControlOwnershipOut)
def upsert_ownership(
    assessment_id: int,
    control_id: str,
    payload: schemas.ControlOwnershipUpdate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    own = db.query(models.ControlOwnership).filter(
        models.ControlOwnership.assessment_id == assessment_id,
        models.ControlOwnership.control_id == control_id,
    ).first()
    if not own:
        own = models.ControlOwnership(assessment_id=assessment_id, control_id=control_id)
        db.add(own)
    if payload.owner is not None:
        own.owner = payload.owner
    if payload.team is not None:
        own.team = payload.team
    if payload.evidence_owner is not None:
        own.evidence_owner = payload.evidence_owner
    db.commit()
    db.refresh(own)
    return own
