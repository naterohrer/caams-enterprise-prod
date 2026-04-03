"""Framework and control read endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import require_viewer
from app.database import get_db

router = APIRouter(prefix="/frameworks", tags=["frameworks"])


@router.get("", response_model=List[schemas.FrameworkOut])
def list_frameworks(_: models.User = Depends(require_viewer), db: Session = Depends(get_db)):
    return db.query(models.Framework).order_by(models.Framework.name).all()


@router.get("/{framework_id}/controls", response_model=List[schemas.ControlOut])
def list_controls(
    framework_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    fw = db.query(models.Framework).filter(models.Framework.id == framework_id).first()
    if not fw:
        raise HTTPException(status_code=404, detail="Framework not found")
    return fw.controls
