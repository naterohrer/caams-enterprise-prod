"""Seed the database with framework data and the tool catalog.
Run once after first install:  python seed.py
Safe to re-run — updates sub_controls on existing frameworks, skips the rest.
"""

import json
from pathlib import Path
from app.database import SessionLocal, engine
from app import models

DATA_DIR = Path(__file__).parent / "app" / "data"

FRAMEWORK_FILES = [
    "cis_v8.json",
    "nist_csf_v2.json",
    "soc2_2017.json",
    "pci_dss_v4.json",
    "hipaa_security.json",
]


def seed_framework(db, data: dict) -> None:
    existing = db.query(models.Framework).filter(
        models.Framework.name == data["name"],
        models.Framework.version == data["version"],
    ).first()
    if existing:
        # Update sub_controls on existing controls (backfill)
        updated = 0
        for c in data["controls"]:
            sub = c.get("sub_controls", [])
            if not sub:
                continue
            ctrl = db.query(models.Control).filter(
                models.Control.framework_id == existing.id,
                models.Control.control_id == c["control_id"],
            ).first()
            if ctrl and ctrl.sub_controls != sub:
                ctrl.sub_controls = sub
                updated += 1
        if updated:
            db.commit()
            print(f"  Updated sub_controls on {updated} controls in {data['name']} {data['version']}")
        else:
            print(f"  Skipping (already up-to-date): {data['name']} {data['version']}")
        return

    framework = models.Framework(
        name=data["name"],
        version=data["version"],
        description=data.get("description", ""),
    )
    db.add(framework)
    db.flush()

    for c in data["controls"]:
        db.add(
            models.Control(
                framework_id=framework.id,
                control_id=c["control_id"],
                title=c["title"],
                description=c["description"],
                required_tags=c["required_tags"],
                optional_tags=c["optional_tags"],
                evidence=c["evidence"],
                sub_controls=c.get("sub_controls", []),
            )
        )

    db.commit()
    print(f"  Seeded: {framework.name} {framework.version} ({len(data['controls'])} controls)")


def seed_tools(db, tools_data: list) -> None:
    added = 0
    for t in tools_data:
        existing = db.query(models.Tool).filter(models.Tool.name == t["name"]).first()
        if existing:
            continue
        tool = models.Tool(
            name=t["name"],
            category=t["category"],
            description=t.get("description", ""),
        )
        db.add(tool)
        db.flush()
        for tag in t.get("capabilities", []):
            db.add(models.ToolCapability(tool_id=tool.id, tag=tag))
        added += 1
    db.commit()
    print(f"  Seeded {added} new tools ({len(tools_data) - added} already existed)")


def seed_crosswalks(db) -> None:
    """Build automatic crosswalk entries based on shared required_tags between frameworks."""
    controls = db.query(models.Control).all()

    # Group by required_tags
    tag_to_controls: dict = {}
    for ctrl in controls:
        for tag in (ctrl.required_tags or []):
            tag_to_controls.setdefault(tag, []).append(ctrl)

    added = 0
    seen = set()
    for tag, ctrls in tag_to_controls.items():
        for i, src in enumerate(ctrls):
            for tgt in ctrls[i + 1:]:
                if src.framework_id == tgt.framework_id:
                    continue
                pair = (min(src.id, tgt.id), max(src.id, tgt.id))
                if pair in seen:
                    continue
                seen.add(pair)
                existing = db.query(models.FrameworkCrosswalk).filter(
                    models.FrameworkCrosswalk.source_control_id == pair[0],
                    models.FrameworkCrosswalk.target_control_id == pair[1],
                ).first()
                if existing:
                    continue
                db.add(models.FrameworkCrosswalk(
                    source_control_id=pair[0],
                    target_control_id=pair[1],
                    crosswalk_type="related",
                    notes=f"Shares tag: {tag}",
                ))
                added += 1

    db.commit()
    print(f"  Seeded {added} framework crosswalk entries")


def seed():
    models.Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print("Seeding frameworks…")
        for filename in FRAMEWORK_FILES:
            path = DATA_DIR / filename
            if not path.exists():
                print(f"  WARNING: {filename} not found, skipping")
                continue
            with open(path) as f:
                seed_framework(db, json.load(f))

        print("Seeding tool catalog…")
        tools_path = DATA_DIR / "tools_catalog.json"
        if tools_path.exists():
            with open(tools_path) as f:
                seed_tools(db, json.load(f))
        else:
            print("  WARNING: tools_catalog.json not found, skipping")

        print("Seeding framework crosswalks…")
        seed_crosswalks(db)

        # Ensure the site_settings singleton row exists (id=1).
        # This avoids a lazy-creation race on first admin access.
        models.SiteSettings.get_or_create(db)
        db.commit()

        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
