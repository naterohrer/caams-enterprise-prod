"""XLSX importer endpoints (CIS Controls, NIST CSF)."""

from fastapi import APIRouter, Depends, File, Request, UploadFile, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin
from app import models
from app.database import get_db
from app.importers.cis_xlsx import import_cis_xlsx
from app.importers.nist_csf_xlsx import import_nist_csf_xlsx
from app.limiter import limiter
from app.logging_config import get_logger

router = APIRouter(prefix="/import", tags=["import"])
log = get_logger("caams.importers")


@router.post("/cis-xlsx")
@limiter.limit("5/minute")
async def import_cis(
    request: Request,
    file: UploadFile = File(...),
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=422, detail="Expected an XLSX file")
    from app.main import MAX_UPLOAD_BYTES  # noqa: PLC0415
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        mb_label = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"File too large (max {mb_label} MB)")
    try:
        result = import_cis_xlsx(content, db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        log.error("CIS XLSX import failed: %s", e, exc_info=True)
        raise HTTPException(status_code=422, detail="Failed to parse XLSX file. "
                            "Ensure it follows the CIS Controls spreadsheet format.")
    return result


@router.post("/nist-csf-xlsx")
@limiter.limit("5/minute")
async def import_nist_csf(
    request: Request,
    file: UploadFile = File(...),
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=422, detail="Expected an XLSX file")
    from app.main import MAX_UPLOAD_BYTES  # noqa: PLC0415
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        mb_label = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"File too large (max {mb_label} MB)")
    try:
        result = import_nist_csf_xlsx(content, db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        log.error("NIST CSF XLSX import failed: %s", e, exc_info=True)
        raise HTTPException(status_code=422, detail="Failed to parse XLSX file. "
                            "Ensure it is the official NIST CSF 2.0 workbook.")
    return result
