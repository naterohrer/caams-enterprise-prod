"""Evidence file upload, management, and approval endpoints."""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import require_contributor, require_viewer
from app.database import get_db
from app.limiter import limiter
from app.routers.audit_log import log_event

router = APIRouter(prefix="/assessments", tags=["evidence"])

UPLOADS_DIR = Path(__file__).parent.parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

# Import the operator-configurable limit from main so there is a single source
# of truth.  Imported lazily to avoid a circular import at module load time.
def _get_max_upload_bytes() -> int:
    from app.main import MAX_UPLOAD_BYTES  # noqa: PLC0415
    return MAX_UPLOAD_BYTES

# Maps every allowed MIME type to a canonical on-disk extension.
# The set of keys is the allowlist; the on-disk filename uses the value (not the
# user-supplied extension) so that static serving of /uploads cannot
# inadvertently serve an executable content type.
_MIME_TO_EXT: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
}


def _validate_file(content: bytes, declared_mime: str) -> str:
    """Validate content type against allowlist and reject obviously wrong magic bytes.

    Returns the normalised MIME type to store, or raises HTTPException.
    """
    mime = (declared_mime or "").split(";")[0].strip().lower()
    if not mime:
        mime = "application/octet-stream"
    if mime not in _MIME_TO_EXT:
        raise HTTPException(
            status_code=415,
            detail=f"File type '{mime}' is not permitted. "
                   "Allowed: PDF, Word, Excel, PowerPoint, plain text, CSV, PNG, JPEG, GIF, WebP, ZIP.",
        )
    # Reject files whose magic bytes clearly contradict a PDF declaration
    if mime == "application/pdf" and not content.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="File content does not match declared PDF type.")
    # Reject executable magic bytes regardless of declared type
    for exe_magic in (b"MZ", b"\x7fELF", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa"):
        if content.startswith(exe_magic):
            raise HTTPException(status_code=415, detail="Executable file types are not permitted.")
    return mime


def _get_assessment(assessment_id: int, db: Session) -> models.Assessment:
    a = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return a


@router.get("/{assessment_id}/evidence", response_model=List[schemas.EvidenceFileOut])
@limiter.limit("60/minute")
def list_evidence(
    request: Request,
    assessment_id: int,
    control_id: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    q = db.query(models.EvidenceFile).filter(
        models.EvidenceFile.assessment_id == assessment_id,
        (models.EvidenceFile.expires_at.is_(None)) | (models.EvidenceFile.expires_at > now),
    )
    if control_id:
        q = q.filter(models.EvidenceFile.control_id == control_id)
    return q.order_by(models.EvidenceFile.uploaded_at.desc()).offset(offset).limit(limit).all()


@router.post("/{assessment_id}/evidence", response_model=schemas.EvidenceFileOut, status_code=201)
@limiter.limit("20/minute")
async def upload_evidence(
    request: Request,
    assessment_id: int,
    control_id: str = Form(...),
    description: str = Form(default=""),
    expires_at: str = Form(default=None),
    file: UploadFile = File(...),
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    _get_assessment(assessment_id, db)

    max_bytes = _get_max_upload_bytes()
    mb_label = max_bytes // (1024 * 1024)

    # Pre-flight size check via Content-Length to avoid reading huge payloads into RAM
    cl = request.headers.get("content-length")
    if cl:
        try:
            if int(cl) > max_bytes:
                raise HTTPException(status_code=413, detail=f"File too large (max {mb_label} MB)")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header")

    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large (max {mb_label} MB)")

    safe_mime = _validate_file(content, file.content_type)

    # Use the canonical extension derived from the validated MIME type so that
    # on-disk filenames never carry an attacker-controlled extension.
    ext = _MIME_TO_EXT.get(safe_mime, ".bin")
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOADS_DIR / stored_name
    dest.write_bytes(content)

    expires = None
    if expires_at:
        try:
            expires = datetime.fromisoformat(expires_at)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Invalid expires_at format. Expected ISO 8601 (e.g. 2026-12-31T00:00:00)",
            )

    ev = models.EvidenceFile(
        assessment_id=assessment_id,
        control_id=control_id,
        stored_filename=stored_name,
        original_filename=file.filename,
        file_size=len(content),
        content_type=safe_mime,
        description=description,
        uploaded_by_id=current_user.id,
        uploaded_by_name=current_user.username,
        expires_at=expires,
        approval_status="pending",
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    log_event(db, user=current_user, action="UPLOAD_EVIDENCE", resource_type="evidence_file",
              resource_id=str(ev.id),
              details={"assessment_id": assessment_id, "control_id": control_id,
                       "filename": file.filename})
    return ev


@router.get("/{assessment_id}/evidence/{file_id}/download")
def download_evidence(
    assessment_id: int,
    file_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    ev = db.query(models.EvidenceFile).filter(
        models.EvidenceFile.id == file_id,
        models.EvidenceFile.assessment_id == assessment_id,
    ).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence file not found")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if ev.expires_at is not None and ev.expires_at <= now:
        raise HTTPException(status_code=410, detail="Evidence file has expired")
    file_path = UPLOADS_DIR / ev.stored_filename
    # Guard against path traversal — ensure the resolved path stays within UPLOADS_DIR
    if not str(file_path.resolve()).startswith(str(UPLOADS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(
        path=file_path,
        filename=ev.original_filename,
        media_type=ev.content_type,
    )


@router.patch("/{assessment_id}/evidence/{file_id}/approval", response_model=schemas.EvidenceFileOut)
def approve_evidence(
    assessment_id: int,
    file_id: int,
    payload: schemas.EvidenceApprovalUpdate,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    ev = db.query(models.EvidenceFile).filter(
        models.EvidenceFile.id == file_id,
        models.EvidenceFile.assessment_id == assessment_id,
    ).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence file not found")

    if payload.action == "approve":
        ev.approval_status = "approved"
        ev.approved_by_id = current_user.id
        ev.approved_by_name = current_user.username
        ev.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        ev.rejection_reason = ""
    else:
        ev.approval_status = "rejected"
        ev.rejection_reason = payload.rejection_reason
        # Clear any previous approval metadata so rejected files don't show stale data
        ev.approved_by_id = None
        ev.approved_by_name = ""
        ev.approved_at = None

    db.commit()
    db.refresh(ev)
    log_event(db, user=current_user, action=f"EVIDENCE_{payload.action.upper()}",
              resource_type="evidence_file", resource_id=str(file_id))
    return ev


@router.delete("/{assessment_id}/evidence/{file_id}", status_code=204)
def delete_evidence(
    assessment_id: int,
    file_id: int,
    current_user: models.User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    ev = db.query(models.EvidenceFile).filter(
        models.EvidenceFile.id == file_id,
        models.EvidenceFile.assessment_id == assessment_id,
    ).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence file not found")

    file_path = UPLOADS_DIR / ev.stored_filename
    try:
        file_path.unlink()
    except FileNotFoundError:
        pass  # already removed or never written; proceed with DB delete

    db.delete(ev)
    db.commit()
    log_event(db, user=current_user, action="DELETE_EVIDENCE", resource_type="evidence_file",
              resource_id=str(file_id))
