"""Tool catalog endpoints."""

import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import require_admin, require_viewer
from app.database import get_db

router = APIRouter(prefix="/tools", tags=["tools"])


def _tool_out(tool: models.Tool) -> schemas.ToolOut:
    return schemas.ToolOut(
        id=tool.id,
        name=tool.name,
        category=tool.category,
        description=tool.description,
        capabilities=[c.tag for c in tool.capabilities],
    )


@router.get("", response_model=List[schemas.ToolOut])
def list_tools(_: models.User = Depends(require_viewer), db: Session = Depends(get_db)):
    tools = db.query(models.Tool).order_by(models.Tool.name).all()
    return [_tool_out(t) for t in tools]


@router.post("", response_model=schemas.ToolOut, status_code=201)
def create_tool(
    payload: schemas.ToolCreate,
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if db.query(models.Tool).filter(models.Tool.name == payload.name).first():
        raise HTTPException(status_code=409, detail="Tool already exists")
    tool = models.Tool(name=payload.name, category=payload.category, description=payload.description)
    db.add(tool)
    db.flush()
    for tag in payload.capabilities:
        db.add(models.ToolCapability(tool_id=tool.id, tag=tag))
    db.commit()
    db.refresh(tool)
    return _tool_out(tool)


@router.delete("/{tool_id}", status_code=204)
def delete_tool(
    tool_id: int,
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    tool = db.query(models.Tool).filter(models.Tool.id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    db.delete(tool)
    db.commit()


@router.get("/template/download")
def download_template(_: models.User = Depends(require_viewer)):
    from fastapi.responses import JSONResponse
    template = [
        {"name": "Example Tool", "category": "EDR", "description": "", "capabilities": ["endpoint-protection", "EDR"]}
    ]
    return JSONResponse(content=template)


@router.post("/upload", status_code=201)
def upload_tools(
    file: UploadFile,
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.main import MAX_UPLOAD_BYTES  # noqa: PLC0415
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        mb_label = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"File too large (max {mb_label} MB)")
    try:
        data = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON file")
    if not isinstance(data, list):
        raise HTTPException(status_code=422, detail="Expected a JSON array")

    added = 0
    skipped = 0
    for item in data:
        if not isinstance(item, dict) or "name" not in item:
            continue
        if db.query(models.Tool).filter(models.Tool.name == item["name"]).first():
            skipped += 1
            continue
        tool = models.Tool(
            name=item["name"],
            category=item.get("category", ""),
            description=item.get("description", ""),
        )
        db.add(tool)
        db.flush()
        for tag in item.get("capabilities", []):
            db.add(models.ToolCapability(tool_id=tool.id, tag=str(tag)))
        added += 1
    db.commit()
    return {"added": added, "skipped": skipped}
