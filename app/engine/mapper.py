"""Coverage computation engine.

Given a list of tool capability tags and a list of Controls, computes whether
each control is covered, partially covered, or not covered.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app import models


def _active_tags(tool: models.Tool) -> set[str]:
    return {c.tag for c in tool.capabilities}


def compute_coverage(
    controls: List[models.Control],
    selected_tools: List[models.Tool],
    notes_map: Dict[str, models.ControlNote],
    ownership_map: Dict[str, models.ControlOwnership],
    findings_map: Dict[str, List[models.Finding]],
) -> dict:
    """Return a dict with aggregate metrics and a per-control results list."""

    available_tags: set[str] = set()
    tool_tag_map: Dict[str, List[str]] = {}
    for tool in selected_tools:
        tags = _active_tags(tool)
        available_tags |= tags
        for tag in tags:
            tool_tag_map.setdefault(tag, []).append(tool.name)

    results = []
    covered_count = partial_count = not_covered_count = na_count = 0

    for ctrl in controls:
        note = notes_map.get(ctrl.control_id)
        own = ownership_map.get(ctrl.control_id)
        ctrl_findings = findings_map.get(ctrl.control_id, [])

        # SOA — not applicable controls are excluded from scoring
        is_applicable = True if note is None else note.is_applicable

        if not is_applicable:
            na_count += 1
            results.append(_build_result(
                ctrl=ctrl, note=note, own=own,
                status="not_applicable", is_override=False,
                covered_by=[], missing_tags=list(ctrl.required_tags or []),
                matched_tags=[], ctrl_findings=ctrl_findings,
            ))
            continue

        # Check manual override
        override_status = None
        is_override = False
        if note and note.override_status:
            expires = note.override_expires
            if expires is None or expires > datetime.now(timezone.utc).replace(tzinfo=None):
                override_status = note.override_status
                is_override = True

        if override_status:
            status = override_status  # covered | partial | not_covered
        else:
            required = set(ctrl.required_tags or [])
            matched = required & available_tags
            if not required:
                status = "covered"
            elif matched == required:
                status = "covered"
            elif matched:
                status = "partial"
            else:
                status = "not_covered"

        if status == "covered":
            covered_count += 1
        elif status == "partial":
            partial_count += 1
        else:
            not_covered_count += 1

        required_set = set(ctrl.required_tags or [])
        matched_tags = list(required_set & available_tags)
        missing_tags = list(required_set - available_tags)
        covered_by = sorted({
            tool_name
            for tag in matched_tags
            for tool_name in tool_tag_map.get(tag, [])
        })

        results.append(_build_result(
            ctrl=ctrl, note=note, own=own,
            status=status, is_override=is_override,
            covered_by=covered_by, missing_tags=missing_tags,
            matched_tags=matched_tags, ctrl_findings=ctrl_findings,
        ))

    applicable_total = covered_count + partial_count + not_covered_count
    score = 0.0
    if applicable_total > 0:
        score = round((covered_count + 0.5 * partial_count) / applicable_total * 100, 1)

    return {
        "total_controls": len(controls),
        "covered": covered_count,
        "partial": partial_count,
        "not_covered": not_covered_count,
        "not_applicable": na_count,
        "score": score,
        "controls": results,
    }


def _build_result(
    *,
    ctrl: models.Control,
    note: Optional[models.ControlNote],
    own: Optional[models.ControlOwnership],
    status: str,
    is_override: bool,
    covered_by: List[str],
    missing_tags: List[str],
    matched_tags: List[str],
    ctrl_findings: List[models.Finding],
) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    due_date = note.due_date if note else None
    is_overdue = bool(due_date and due_date < now and status not in ("covered", "not_applicable"))

    open_findings = [f for f in ctrl_findings if f.status in ("open", "in_progress")]

    return {
        "control_id": ctrl.control_id,
        "title": ctrl.title,
        "description": ctrl.description,
        "status": status,
        "is_override": is_override,
        "override_justification": (note.override_justification or "") if note else "",
        "override_expires": note.override_expires if note else None,
        "covered_by": covered_by,
        "missing_tags": missing_tags,
        "matched_tags": matched_tags,
        "evidence_items": ctrl.evidence or [],
        "sub_controls": ctrl.sub_controls or [],
        "notes": (note.notes or "") if note else "",
        "evidence_url": (note.evidence_url or "") if note else "",
        "owner": (own.owner or "") if own else "",
        "team": (own.team or "") if own else "",
        "evidence_owner": (own.evidence_owner or "") if own else "",
        "review_status": (note.review_status or "not_reviewed") if note else "not_reviewed",
        "review_notes": (note.review_notes or "") if note else "",
        "assignee": (note.assignee or "") if note else "",
        "due_date": due_date,
        "is_overdue": is_overdue,
        "is_applicable": (note.is_applicable if note else True),
        "exclusion_reason": (note.exclusion_reason or "") if note else "",
        "finding_count": len(ctrl_findings),
        "open_finding_count": len(open_findings),
    }


def compute_recommendations(
    controls: List[models.Control],
    selected_tools: List[models.Tool],
    all_tools: List[models.Tool],
) -> List[dict]:
    """Return tools not yet in scope, ranked by gap-closing impact."""
    selected_ids = {t.id for t in selected_tools}
    available_tags: set[str] = set()
    for tool in selected_tools:
        available_tags |= _active_tags(tool)

    # Identify all missing required tags
    missing_required: set[str] = set()
    for ctrl in controls:
        missing_required |= set(ctrl.required_tags or []) - available_tags

    if not missing_required:
        return []

    recs = []
    for tool in all_tools:
        if tool.id in selected_ids:
            continue
        tool_tags = _active_tags(tool)
        gaps_closed = tool_tags & missing_required
        if gaps_closed:
            # Count controls that would move from not_covered/partial to better
            controls_helped = sum(
                1 for ctrl in controls
                if (set(ctrl.required_tags or []) - available_tags) & gaps_closed
            )
            recs.append({
                "tool_id": tool.id,
                "tool_name": tool.name,
                "category": tool.category,
                "gaps_closed": sorted(gaps_closed),
                "controls_helped": controls_helped,
            })

    recs.sort(key=lambda r: (-r["controls_helped"], r["tool_name"]))
    return recs
