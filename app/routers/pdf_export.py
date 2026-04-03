"""PDF export — assessment report and evidence package (ZIP)."""

import csv
import io
import pathlib
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from sqlalchemy.orm import Session

from app import models
from app.auth import require_viewer
from app.database import get_db
from app.engine import mapper
from app.limiter import limiter
from app.routers.assessments import _findings_map, _notes_map, _ownership_map
from app.routers.evidence import UPLOADS_DIR

router = APIRouter(prefix="/assessments", tags=["pdf-export"])

STATUS_COLORS = {
    "covered": colors.HexColor("#00B050"),
    "partial": colors.HexColor("#FF9900"),
    "not_covered": colors.HexColor("#FF0000"),
    "not_applicable": colors.HexColor("#808080"),
}


@router.get("/{assessment_id}/export/pdf")
@limiter.limit("5/minute")
def export_pdf(
    request: Request,
    assessment_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    a = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assessment not found")

    controls = a.framework.controls if a.framework else []
    nm = _notes_map(assessment_id, db)
    om = _ownership_map(assessment_id, db)
    fm = _findings_map(assessment_id, db)
    cov = mapper.compute_coverage(controls, a.tools, nm, om, fm)
    findings = db.query(models.Finding).filter(
        models.Finding.assessment_id == assessment_id
    ).all()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm,
                            leftMargin=2*cm, rightMargin=2*cm)
    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    body_style = styles["BodyText"]

    story = []

    # Cover page
    story.append(Spacer(1, 3*cm))
    story.append(Paragraph("CAAMS Enterprise Compliance Assessment Report", h1))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1F3864")))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(f"<b>Assessment:</b> {a.name}", body_style))
    fw_name = a.framework.name if a.framework else "N/A"
    fw_ver = a.framework.version if a.framework else ""
    story.append(Paragraph(f"<b>Framework:</b> {fw_name} {fw_ver}", body_style))
    story.append(Paragraph(f"<b>Status:</b> {a.status.title()}", body_style))
    story.append(Paragraph(
        f"<b>Generated:</b> {datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M UTC')}", body_style))
    story.append(Spacer(1, 1*cm))

    # Executive Summary
    story.append(Paragraph("Executive Summary", h2))
    summary_data = [
        ["Metric", "Value"],
        ["Overall Score", f"{cov['score']}%"],
        ["Covered Controls", str(cov["covered"])],
        ["Partial Controls", str(cov["partial"])],
        ["Not Covered Controls", str(cov["not_covered"])],
        ["Not Applicable", str(cov["not_applicable"])],
        ["Total Controls", str(cov["total_controls"])],
        ["Tools in Scope", str(len(a.tools))],
        ["Open Findings", str(sum(1 for f in findings if f.status in ("open", "in_progress")))],
    ]
    summary_table = Table(summary_data, colWidths=[8*cm, 8*cm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF2FF")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
    ]))
    story.append(summary_table)
    story.append(PageBreak())

    # Tools in scope
    story.append(Paragraph("Tools in Scope", h2))
    if a.tools:
        tool_data = [["Tool Name", "Category", "Capabilities"]]
        for t in a.tools:
            tool_data.append([t.name, t.category, ", ".join(c.tag for c in t.capabilities[:5])])
        tool_table = Table(tool_data, colWidths=[5*cm, 4*cm, 8*cm])
        tool_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF2FF")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(tool_table)
    story.append(PageBreak())

    # Coverage detail
    story.append(Paragraph("Control Coverage Detail", h2))
    ctrl_data = [["Control ID", "Title", "Status", "Owner", "Review"]]
    for c in cov["controls"]:
        status_label = c["status"].replace("_", " ").title()
        if c["is_override"]:
            status_label += " ✎"
        ctrl_data.append([
            c["control_id"],
            c["title"][:60] + ("…" if len(c["title"]) > 60 else ""),
            status_label,
            c["owner"][:25],
            c["review_status"],
        ])
    ctrl_table = Table(ctrl_data, colWidths=[2.5*cm, 7*cm, 3*cm, 3*cm, 2.5*cm])
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF2FF")]),
    ]
    for i, c in enumerate(cov["controls"], 1):
        col = STATUS_COLORS.get(c["status"], colors.grey)
        style_cmds.append(("BACKGROUND", (2, i), (2, i), col))
        style_cmds.append(("TEXTCOLOR", (2, i), (2, i), colors.white))
    ctrl_table.setStyle(TableStyle(style_cmds))
    story.append(ctrl_table)

    # Findings
    if findings:
        story.append(PageBreak())
        story.append(Paragraph("Findings & Issues", h2))
        f_data = [["ID", "Control", "Title", "Severity", "Status", "Target Date"]]
        for f in findings:
            td = f.target_date.strftime("%Y-%m-%d") if f.target_date else ""
            f_data.append([str(f.id), f.control_id, f.title[:50], f.severity, f.status, td])
        f_table = Table(f_data, colWidths=[1*cm, 2*cm, 7*cm, 2.5*cm, 2.5*cm, 3*cm])
        f_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF2FF")]),
        ]))
        story.append(f_table)

    doc.build(story)
    buf.seek(0)
    filename = f"CaamsEnterprise_{a.name.replace(' ', '_')}_{datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{assessment_id}/export/evidence-package")
@limiter.limit("5/minute")
def export_evidence_package(
    request: Request,
    assessment_id: int,
    _: models.User = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """
    ZIP package containing:
    - The PDF assessment report
    - All approved/pending evidence files
    - A manifest CSV
    """
    a = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assessment not found")

    evidence_files = db.query(models.EvidenceFile).filter(
        models.EvidenceFile.assessment_id == assessment_id
    ).all()

    # Generate PDF in-memory (re-use the PDF export logic)
    controls = a.framework.controls if a.framework else []
    nm = _notes_map(assessment_id, db)
    om = _ownership_map(assessment_id, db)
    fm = _findings_map(assessment_id, db)
    cov = mapper.compute_coverage(controls, a.tools, nm, om, fm)

    # Build a simple PDF buffer
    pdf_buf = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buf, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("CAAMS Enterprise Evidence Package", styles["Heading1"]),
        Paragraph(f"Assessment: {a.name}", styles["BodyText"]),
        Paragraph(f"Framework: {a.framework.name if a.framework else 'N/A'}", styles["BodyText"]),
        Paragraph(f"Score: {cov['score']}%", styles["BodyText"]),
        Paragraph(f"Generated: {datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M UTC')}", styles["BodyText"]),
        Spacer(1, 0.5*cm),
        Paragraph(f"Evidence files included: {len(evidence_files)}", styles["BodyText"]),
    ]
    doc.build(story)
    pdf_buf.seek(0)

    # Build ZIP
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add PDF report
        zf.writestr(f"report_{a.name.replace(' ', '_')}.pdf", pdf_buf.read())

        # Add manifest — use csv.writer to handle commas/quotes/injection safely
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf)
        writer.writerow(
            ["filename", "control_id", "description", "uploaded_by",
             "uploaded_at", "approval_status", "expires_at"]
        )
        for ev in evidence_files:
            exp = ev.expires_at.strftime("%Y-%m-%d") if ev.expires_at else ""
            writer.writerow([
                ev.original_filename, ev.control_id, ev.description,
                ev.uploaded_by_name, ev.uploaded_at.strftime("%Y-%m-%d"),
                ev.approval_status, exp,
            ])
        zf.writestr("manifest.csv", csv_buf.getvalue())

        # Add evidence files
        for ev in evidence_files:
            disk_path = UPLOADS_DIR / ev.stored_filename
            if disk_path.exists():
                # Use only the basename to prevent path traversal inside the ZIP
                safe_name = pathlib.Path(ev.original_filename).name or ev.stored_filename
                zip_path = f"evidence/{ev.control_id}/{safe_name}"
                zf.write(disk_path, zip_path)

    zip_buf.seek(0)
    filename = f"evidence_package_{a.name.replace(' ', '_')}_{datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y%m%d')}.zip"
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
