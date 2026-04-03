"""API token management (machine-to-machine access)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import generate_api_token, require_admin
from app.database import get_db
from app.routers.audit_log import log_event

router = APIRouter(prefix="/api-tokens", tags=["api-tokens"])


@router.get("", response_model=List[schemas.APITokenOut])
def list_tokens(
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return db.query(models.APIToken).order_by(models.APIToken.created_at.desc()).all()


@router.post("", response_model=schemas.APITokenCreated, status_code=201)
def create_token(
    payload: schemas.APITokenCreate,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    raw, prefix, hashed = generate_api_token()
    tok = models.APIToken(
        user_id=current_user.id,
        name=payload.name,
        token_hash=hashed,
        prefix=prefix,
        expires_at=payload.expires_at,
        scopes=payload.scopes,
    )
    db.add(tok)
    db.commit()
    db.refresh(tok)
    log_event(db, user=current_user, action="CREATE_API_TOKEN", resource_type="api_token",
              resource_id=str(tok.id), details={"name": payload.name})
    return schemas.APITokenCreated(
        id=tok.id, name=tok.name, prefix=tok.prefix, token=raw,
        created_at=tok.created_at, expires_at=tok.expires_at,
        last_used_at=tok.last_used_at, is_active=tok.is_active,
        scopes=tok.scopes, user_id=tok.user_id,
    )


@router.delete("/{token_id}", status_code=204)
def revoke_token(
    token_id: int,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    tok = db.query(models.APIToken).filter(models.APIToken.id == token_id).first()
    if not tok:
        raise HTTPException(status_code=404, detail="Token not found")
    tok.is_active = False
    db.commit()
    log_event(db, user=current_user, action="REVOKE_API_TOKEN", resource_type="api_token",
              resource_id=str(token_id))
