"""Authentication and user management endpoints."""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import (
    create_access_token, create_mfa_token, create_refresh_token, decode_token,
    get_current_user, hash_password, require_admin,
    require_viewer, verify_password,
)
from app.email import build_invite_url, send_invite_email
from app.jwt_utils import JWTError
from app.database import get_db
from app.limiter import limiter
from app.logging_config import get_logger
from app.routers.audit_log import log_event

# How long invite tokens are valid.  Configurable via CAAMS_INVITE_TOKEN_HOURS.
_INVITE_TOKEN_HOURS = int(os.environ.get("CAAMS_INVITE_TOKEN_HOURS", "72"))

# Sentinel stored in hashed_password while an invite is pending acceptance.
_INVITE_PENDING = "invite-pending"

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("caams.auth")


@router.get("/setup-needed")
def setup_needed(db: Session = Depends(get_db)):
    count = db.query(models.User).count()
    return {"needed": count == 0}


@router.post("/setup", response_model=schemas.TokenResponse)
@limiter.limit("5/hour")
def setup(request: Request, payload: schemas.SetupRequest, db: Session = Depends(get_db)):
    if db.query(models.User).count() > 0:
        raise HTTPException(status_code=403, detail="Setup already completed")
    user = models.User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("SETUP | admin account created | username=%s", user.username)
    tv = user.token_version or 0
    token = create_access_token({"sub": user.username, "role": user.role, "tv": tv})
    refresh = create_refresh_token({"sub": user.username, "role": user.role, "tv": tv})
    return schemas.TokenResponse(access_token=token, refresh_token=refresh, role=user.role)


@router.post("/login", response_model=schemas.TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form.username).first()
    ip = request.client.host if request.client else "unknown"
    if user and user.hashed_password == _INVITE_PENDING:
        raise HTTPException(
            status_code=403,
            detail="Account not yet activated — please accept your invitation first",
        )
    if not user or not verify_password(form.password, user.hashed_password):
        log.warning("LOGIN failed | username=%s | ip=%s", form.username, ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    # MFA gate: if MFA is enabled, return a short-lived mfa_pending token instead
    if user.mfa_enabled:
        log.info("LOGIN mfa-required | user=%s | ip=%s", user.username, ip)
        return schemas.TokenResponse(mfa_required=True, mfa_token=create_mfa_token(user.id))
    log.info("LOGIN success | user=%s | role=%s | ip=%s", user.username, user.role, ip)
    log_event(db, user=user, action="LOGIN", resource_type="user",
              resource_id=str(user.id), ip_address=ip)
    tv = user.token_version or 0
    token = create_access_token({"sub": user.username, "role": user.role, "tv": tv})
    refresh = create_refresh_token({"sub": user.username, "role": user.role, "tv": tv})
    return schemas.TokenResponse(access_token=token, refresh_token=refresh, role=user.role)


@router.post("/refresh", response_model=schemas.TokenResponse)
@limiter.limit("10/minute")
def refresh(request: Request, payload: schemas.RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new access + refresh token pair."""
    try:
        data = decode_token(payload.refresh_token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    if data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    username = data.get("sub")
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    # Verify the refresh token's version still matches — catches revoked sessions
    if data.get("tv", 0) != (user.token_version or 0):
        raise HTTPException(status_code=401, detail="Session revoked — please log in again")
    tv = user.token_version or 0
    new_access = create_access_token({"sub": user.username, "role": user.role, "tv": tv})
    new_refresh = create_refresh_token({"sub": user.username, "role": user.role, "tv": tv})
    return schemas.TokenResponse(access_token=new_access, refresh_token=new_refresh, role=user.role)


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.get("/directory", response_model=list[schemas.UserDirectoryEntry])
def user_directory(_: models.User = Depends(require_viewer), db: Session = Depends(get_db)):
    """Lightweight user list for dropdown population — any authenticated user."""
    return (
        db.query(models.User)
        .filter(models.User.is_active)
        .order_by(models.User.full_name, models.User.username)
        .all()
    )


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(_: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(models.User).order_by(models.User.id).all()


@router.post("/users", response_model=schemas.UserOut, status_code=201)
def create_user(
    payload: schemas.UserCreate,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if db.query(models.User).filter(models.User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already exists")
    user = models.User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        full_name=payload.full_name,
        email=payload.email,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("USER created | username=%s | role=%s | by=%s", user.username, user.role, current_user.username)
    log_event(db, user=current_user, action="CREATE_USER", resource_type="user",
              resource_id=str(user.id), details={"username": user.username, "role": user.role})
    return user


@router.post("/users/invite", response_model=schemas.InviteResponse, status_code=201)
@limiter.limit("20/hour")
def invite_user(
    request: Request,
    payload: schemas.InviteCreate,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a new user account and return a single-use invite token.

    The invited user must call POST /auth/invite/accept with the token to set
    their own password and activate the account.  If SMTP is configured the
    invite email is sent automatically; the token is always returned so the
    admin can share it manually as well.
    """
    if db.query(models.User).filter(models.User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already exists")

    user = models.User(
        username=payload.username,
        hashed_password=_INVITE_PENDING,
        role=payload.role,
        full_name=payload.full_name,
        email=payload.email,
        is_active=False,  # activated when invite is accepted
    )
    db.add(user)
    db.flush()  # get user.id without committing

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=_INVITE_TOKEN_HOURS)

    invite = models.InviteToken(
        user_id=user.id,
        token_hash=token_hash,
        token_prefix=raw_token[:8],
        created_by_id=current_user.id,
        expires_at=expires_at,
    )
    db.add(invite)
    db.commit()
    db.refresh(user)

    invite_url = build_invite_url(raw_token)
    email_sent = False
    if payload.email:
        email_sent = send_invite_email(payload.email, payload.full_name, invite_url or raw_token, db=db)

    log.info(
        "INVITE created | username=%s | role=%s | by=%s | email_sent=%s",
        user.username, user.role, current_user.username, email_sent,
    )
    log_event(
        db, user=current_user, action="INVITE_USER", resource_type="user",
        resource_id=str(user.id),
        details={"username": user.username, "role": user.role, "email_sent": email_sent},
    )

    return schemas.InviteResponse(
        user_id=user.id,
        username=user.username,
        invite_token=raw_token,
        invite_url=invite_url,
        email_sent=email_sent,
        expires_hours=_INVITE_TOKEN_HOURS,
    )


@router.post("/invite/accept", response_model=schemas.TokenResponse)
@limiter.limit("10/hour")
def accept_invite(
    request: Request,
    payload: schemas.InviteAccept,
    db: Session = Depends(get_db),
):
    """Activate an invited account by setting a password.

    Validates the invite token (not expired, not already used), sets the
    user's password, marks the account active, and returns a JWT pair so the
    user is immediately logged in.
    """
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    invite = (
        db.query(models.InviteToken)
        .filter(models.InviteToken.token_hash == token_hash)
        .first()
    )

    # Deliberately vague error to avoid leaking whether a token exists
    _invalid = HTTPException(status_code=400, detail="Invalid or expired invite token")

    if not invite:
        raise _invalid
    if invite.used_at is not None:
        raise _invalid
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if invite.expires_at < now:
        raise _invalid

    user = db.query(models.User).filter(models.User.id == invite.user_id).first()
    if not user:
        raise _invalid

    user.hashed_password = hash_password(payload.password)
    user.is_active = True
    invite.used_at = now
    db.commit()
    db.refresh(user)

    log.info("INVITE accepted | username=%s", user.username)
    log_event(
        db, user=user, action="INVITE_ACCEPTED", resource_type="user",
        resource_id=str(user.id), ip_address=request.client.host if request.client else "",
    )

    tv = user.token_version or 0
    token = create_access_token({"sub": user.username, "role": user.role, "tv": tv})
    refresh = create_refresh_token({"sub": user.username, "role": user.role, "tv": tv})
    return schemas.TokenResponse(access_token=token, refresh_token=refresh, role=user.role)


@router.patch("/users/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    invalidate_sessions = False
    if payload.role is not None:
        if payload.role not in ("admin", "contributor", "viewer", "auditor"):
            raise HTTPException(status_code=422, detail="Invalid role")
        user.role = payload.role
    if payload.password is not None:
        user.hashed_password = hash_password(payload.password)
        invalidate_sessions = True
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if not payload.is_active:
            invalidate_sessions = True
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.email is not None:
        user.email = payload.email
    if invalidate_sessions:
        user.token_version = (user.token_version or 0) + 1
    db.commit()
    db.refresh(user)
    log_event(db, user=current_user, action="UPDATE_USER", resource_type="user",
              resource_id=str(user.id))
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    db.delete(user)
    db.commit()
    log_event(db, user=current_user, action="DELETE_USER", resource_type="user",
              resource_id=str(user_id), details={"username": user.username})


@router.get("/notifications/my")
def get_my_notifications(
    current_user: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return open RFIs, findings, and controls assigned to the current user."""
    username = current_user.username

    rfis = (
        db.query(models.RFI, models.Assessment.name)
        .join(models.Assessment, models.RFI.assessment_id == models.Assessment.id)
        .filter(models.RFI.assigned_to == username, models.RFI.status != "closed")
        .order_by(models.RFI.due_date.asc().nullslast())
        .all()
    )

    findings = (
        db.query(models.Finding, models.Assessment.name)
        .join(models.Assessment, models.Finding.assessment_id == models.Assessment.id)
        .filter(
            models.Finding.remediation_owner == username,
            models.Finding.status.notin_(["closed", "remediated", "accepted"]),
        )
        .order_by(models.Finding.target_date.asc().nullslast())
        .all()
    )

    controls = (
        db.query(models.ControlNote, models.Assessment.name)
        .join(models.Assessment, models.ControlNote.assessment_id == models.Assessment.id)
        .filter(models.ControlNote.assignee == username)
        .order_by(models.ControlNote.due_date.asc().nullslast())
        .all()
    )

    return {
        "rfis": [
            {
                "id": r.id,
                "title": r.title,
                "assessment_id": r.assessment_id,
                "assessment_name": name,
                "priority": r.priority,
                "due_date": r.due_date.isoformat() if r.due_date else None,
                "status": r.status,
            }
            for r, name in rfis
        ],
        "findings": [
            {
                "id": f.id,
                "title": f.title,
                "assessment_id": f.assessment_id,
                "assessment_name": name,
                "severity": f.severity,
                "status": f.status,
                "target_date": f.target_date.isoformat() if f.target_date else None,
            }
            for f, name in findings
        ],
        "controls": [
            {
                "control_id": c.control_id,
                "assessment_id": c.assessment_id,
                "assessment_name": name,
                "due_date": c.due_date.isoformat() if c.due_date else None,
                "review_status": c.review_status,
            }
            for c, name in controls
        ],
        "total": len(rfis) + len(findings) + len(controls),
    }
