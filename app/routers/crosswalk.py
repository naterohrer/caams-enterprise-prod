"""Framework crosswalk — map controls across multiple frameworks."""


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.auth import require_viewer
from app.database import get_db

router = APIRouter(prefix="/crosswalk", tags=["crosswalk"])


@router.get("")
def get_crosswalk(
    source_framework_id: int,
    target_framework_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Return crosswalk mapping between two frameworks."""
    src_fw = db.query(models.Framework).filter(models.Framework.id == source_framework_id).first()
    tgt_fw = db.query(models.Framework).filter(models.Framework.id == target_framework_id).first()
    if not src_fw or not tgt_fw:
        raise HTTPException(status_code=404, detail="Framework not found")

    src_controls = {c.id: c for c in src_fw.controls}
    tgt_controls = {c.id: c for c in tgt_fw.controls}

    mappings = (
        db.query(models.FrameworkCrosswalk)
        .filter(
            models.FrameworkCrosswalk.source_control_id.in_(src_controls.keys()),
            models.FrameworkCrosswalk.target_control_id.in_(tgt_controls.keys()),
        )
        .all()
    )

    result = []
    for m in mappings:
        sc = src_controls.get(m.source_control_id)
        tc = tgt_controls.get(m.target_control_id)
        if sc and tc:
            result.append({
                "id": m.id,
                "crosswalk_type": m.crosswalk_type,
                "notes": m.notes,
                "source": {
                    "control_id": sc.control_id,
                    "title": sc.title,
                    "framework": src_fw.name,
                },
                "target": {
                    "control_id": tc.control_id,
                    "title": tc.title,
                    "framework": tgt_fw.name,
                },
            })

    # Also identify tag-based overlap (automatic crosswalk via shared tags)
    tag_overlaps = []
    for sc in src_fw.controls:
        sc_tags = set(sc.required_tags or []) | set(sc.optional_tags or [])
        for tc in tgt_fw.controls:
            tc_tags = set(tc.required_tags or []) | set(tc.optional_tags or [])
            shared = sc_tags & tc_tags
            if shared:
                tag_overlaps.append({
                    "source_control_id": sc.control_id,
                    "source_title": sc.title,
                    "target_control_id": tc.control_id,
                    "target_title": tc.title,
                    "shared_tags": sorted(shared),
                    "overlap_strength": round(len(shared) / max(len(sc_tags), 1) * 100, 0),
                })

    tag_overlaps.sort(key=lambda x: -x["overlap_strength"])

    return {
        "source_framework": {"id": src_fw.id, "name": src_fw.name, "version": src_fw.version},
        "target_framework": {"id": tgt_fw.id, "name": tgt_fw.name, "version": tgt_fw.version},
        "explicit_mappings": result,
        "tag_overlaps": tag_overlaps[:100],  # top 100 by overlap strength
    }


@router.get("/multi-framework")
def multi_framework_coverage(
    assessment_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """
    Given an assessment, show which OTHER frameworks have controls whose required_tags
    are satisfied by the tools in this assessment.
    """
    a = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assessment not found")

    available_tags = set()
    for tool in a.tools:
        for cap in tool.capabilities:
            available_tags.add(cap.tag)

    all_frameworks = db.query(models.Framework).all()
    result = []
    for fw in all_frameworks:
        if fw.id == a.framework_id:
            continue
        total = len(fw.controls)
        if total == 0:
            continue
        covered = 0
        partial = 0
        not_covered = 0
        for ctrl in fw.controls:
            required = set(ctrl.required_tags)
            if not required:
                covered += 1
            elif required <= available_tags:
                covered += 1
            elif required & available_tags:
                partial += 1
            else:
                not_covered += 1
        score = round((covered + 0.5 * partial) / total * 100, 1)
        result.append({
            "framework_id": fw.id,
            "framework_name": fw.name,
            "framework_version": fw.version,
            "total_controls": total,
            "covered": covered,
            "partial": partial,
            "not_covered": not_covered,
            "score": score,
        })

    result.sort(key=lambda x: -x["score"])
    return {
        "assessment_id": a.id,
        "assessment_name": a.name,
        "primary_framework": a.framework.name if a.framework else "",
        "crosswalk": result,
    }
