"""SQLAlchemy ORM models for CAAMS Enterprise unified audit platform."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey,
    Integer, JSON, String, Table, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime (timezone-stripped for SQLite compat)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

# ── Many-to-many: Assessment ↔ Tool ─────────────────────────────────────────

assessment_tool = Table(
    "assessment_tool",
    Base.metadata,
    Column("assessment_id", Integer, ForeignKey("assessments.id", ondelete="CASCADE"), primary_key=True),
    Column("tool_id", Integer, ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True),
)


# ── Framework / Control ──────────────────────────────────────────────────────

class Framework(Base):
    __tablename__ = "frameworks"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    version = Column(String(40), nullable=False)
    description = Column(Text, default="")
    controls = relationship("Control", back_populates="framework", cascade="all, delete-orphan")

    @property
    def control_count(self) -> int:
        return len(self.controls)


class Control(Base):
    __tablename__ = "controls"
    id = Column(Integer, primary_key=True)
    framework_id = Column(Integer, ForeignKey("frameworks.id", ondelete="CASCADE"), nullable=False)
    control_id = Column(String(40), nullable=False)   # e.g. "CIS-1", "CC6.1"
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    required_tags = Column(JSON, default=lambda: [])
    optional_tags = Column(JSON, default=lambda: [])
    evidence = Column(JSON, default=lambda: [])       # list[str] — evidence items
    sub_controls = Column(JSON, default=lambda: [])
    framework = relationship("Framework", back_populates="controls")


# ── Tools ────────────────────────────────────────────────────────────────────

class Tool(Base):
    __tablename__ = "tools"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, unique=True)
    category = Column(String(80), nullable=False, default="")
    description = Column(Text, default="")
    capabilities = relationship("ToolCapability", back_populates="tool", cascade="all, delete-orphan")


class ToolCapability(Base):
    __tablename__ = "tool_capabilities"
    id = Column(Integer, primary_key=True)
    tool_id = Column(Integer, ForeignKey("tools.id", ondelete="CASCADE"), nullable=False)
    tag = Column(String(80), nullable=False)
    tool = relationship("Tool", back_populates="capabilities")


# ── Users & API Tokens ───────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), nullable=False, unique=True)
    hashed_password = Column(String(128), nullable=False)
    # roles: admin | contributor | viewer | auditor
    role = Column(String(20), nullable=False, default="viewer")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    full_name = Column(String(120), default="")
    email = Column(String(120), default="")
    # MFA (TOTP)
    totp_secret = Column(String(64), nullable=True)
    mfa_enabled = Column(Boolean, default=False)
    # SSO / OIDC — stable subject identifier from the IdP
    oidc_sub = Column(String(256), nullable=True)
    # Token revocation — increment to invalidate all existing JWTs for this user
    token_version = Column(Integer, default=0, nullable=False, server_default="0")


class InviteToken(Base):
    """Single-use, time-limited invite token for new user onboarding.

    When an admin creates a user via POST /auth/users/invite the user record is
    created with hashed_password="invite-pending" and one of these rows is
    inserted.  The raw token is returned to the admin (and optionally emailed)
    so the new user can call POST /auth/invite/accept to set their own password.
    """
    __tablename__ = "invite_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    token_prefix = Column(String(12), nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)  # None = not yet accepted

    user = relationship("User", foreign_keys=[user_id])
    created_by = relationship("User", foreign_keys=[created_by_id])


class APIToken(Base):
    __tablename__ = "api_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(80), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    prefix = Column(String(12), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    scopes = Column(JSON, default=lambda: [])  # e.g. ["read", "write"]
    user = relationship("User")


# ── Assessments ──────────────────────────────────────────────────────────────

class Assessment(Base):
    __tablename__ = "assessments"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    framework_id = Column(Integer, ForeignKey("frameworks.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # lifecycle: draft | in_review | approved | archived
    status = Column(String(20), nullable=False, default="draft")
    scope_notes = Column(Text, default="")
    # recurring assessment config
    is_recurring = Column(Boolean, default=False)
    recurrence_days = Column(Integer, nullable=True)
    next_review_date = Column(DateTime, nullable=True)

    framework = relationship("Framework")
    created_by = relationship("User", foreign_keys=[created_by_id])
    tools = relationship("Tool", secondary=assessment_tool)
    signoffs = relationship("AssessmentSignoff", back_populates="assessment", cascade="all, delete-orphan")
    control_notes = relationship("ControlNote", back_populates="assessment", cascade="all, delete-orphan")
    control_ownership = relationship("ControlOwnership", back_populates="assessment", cascade="all, delete-orphan")
    evidence_files = relationship("EvidenceFile", back_populates="assessment", cascade="all, delete-orphan")
    findings = relationship("Finding", back_populates="assessment", cascade="all, delete-orphan")
    risk_acceptances = relationship("RiskAcceptance", back_populates="assessment", cascade="all, delete-orphan")
    auditor_shares = relationship("AuditorShare", back_populates="assessment", cascade="all, delete-orphan")
    rfis = relationship("RFI", back_populates="assessment", cascade="all, delete-orphan")
    auditor_comments = relationship("AuditorComment", back_populates="assessment", cascade="all, delete-orphan")


class AssessmentSignoff(Base):
    __tablename__ = "assessment_signoffs"
    id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    # actions: submitted_for_review | approved | returned | archived
    action = Column(String(30), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_name = Column(String(80), default="")
    comments = Column(Text, default="")
    timestamp = Column(DateTime, default=_utcnow)
    assessment = relationship("Assessment", back_populates="signoffs")
    user = relationship("User")


# ── Per-control metadata ─────────────────────────────────────────────────────

class ControlNote(Base):
    __tablename__ = "control_notes"
    __table_args__ = (UniqueConstraint("assessment_id", "control_id"),)
    id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    control_id = Column(String(40), nullable=False)

    # Audit notes
    notes = Column(Text, default="")
    evidence_url = Column(String(2048), default="")

    # Manual override
    override_status = Column(String(20), nullable=True)         # covered|partial|not_covered
    override_justification = Column(Text, default="")
    override_expires = Column(DateTime, nullable=True)

    # Review workflow
    # statuses: not_reviewed | in_review | approved | rejected
    review_status = Column(String(20), default="not_reviewed")
    review_notes = Column(Text, default="")
    reviewed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    # Assignment & due dates
    assignee = Column(String(120), default="")
    due_date = Column(DateTime, nullable=True)

    # SOA / applicability
    is_applicable = Column(Boolean, default=True)
    exclusion_reason = Column(Text, default="")

    assessment = relationship("Assessment", back_populates="control_notes")
    reviewed_by = relationship("User")


class ControlOwnership(Base):
    __tablename__ = "control_ownership"
    __table_args__ = (UniqueConstraint("assessment_id", "control_id"),)
    id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    control_id = Column(String(40), nullable=False)
    owner = Column(String(120), default="")
    team = Column(String(120), default="")
    evidence_owner = Column(String(120), default="")
    assessment = relationship("Assessment", back_populates="control_ownership")


# ── Evidence files ───────────────────────────────────────────────────────────

class EvidenceFile(Base):
    __tablename__ = "evidence_files"
    id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    control_id = Column(String(40), nullable=False)
    stored_filename = Column(String(255), nullable=False)   # UUID-based filename on disk
    original_filename = Column(String(255), nullable=False)
    file_size = Column(Integer, default=0)
    content_type = Column(String(120), default="application/octet-stream")
    description = Column(Text, default="")
    uploaded_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_by_name = Column(String(80), default="")
    uploaded_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime, nullable=True)
    # approval: pending | approved | rejected
    approval_status = Column(String(20), default="pending")
    approved_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_name = Column(String(80), default="")
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, default="")

    assessment = relationship("Assessment", back_populates="evidence_files")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])


# ── Findings / Issue Tracker ─────────────────────────────────────────────────

class Finding(Base):
    __tablename__ = "findings"
    id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    control_id = Column(String(40), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    # severity: critical | high | medium | low | informational
    severity = Column(String(20), default="medium")
    # status: open | in_progress | remediated | accepted | closed
    status = Column(String(20), default="open")
    remediation_owner = Column(String(120), default="")
    target_date = Column(DateTime, nullable=True)
    actual_close_date = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_name = Column(String(80), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    notes = Column(Text, default="")

    assessment = relationship("Assessment", back_populates="findings")
    created_by = relationship("User")


# ── Risk Acceptances ─────────────────────────────────────────────────────────

class RiskAcceptance(Base):
    __tablename__ = "risk_acceptances"
    id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    control_id = Column(String(40), nullable=False)
    justification = Column(Text, nullable=False)
    # risk_rating: critical | high | medium | low
    risk_rating = Column(String(20), default="medium")
    residual_risk_notes = Column(Text, default="")
    approved_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_name = Column(String(80), default="")
    approved_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_name = Column(String(80), default="")
    created_at = Column(DateTime, default=_utcnow)

    assessment = relationship("Assessment", back_populates="risk_acceptances")
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    created_by = relationship("User", foreign_keys=[created_by_id])


# ── Immutable Audit Log ──────────────────────────────────────────────────────

class AuditLogEntry(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=_utcnow, index=True)
    user_id = Column(Integer, nullable=True)
    user_name = Column(String(80), default="")
    # action: LOGIN | LOGOUT | CREATE | UPDATE | DELETE | OVERRIDE | SIGNOFF | etc.
    action = Column(String(60), nullable=False)
    resource_type = Column(String(60), default="")
    resource_id = Column(String(40), default="")
    details = Column(JSON, default=lambda: {})
    ip_address = Column(String(45), default="")
    user_agent = Column(String(255), default="")


# ── External Auditor Shares ──────────────────────────────────────────────────

class AuditorShare(Base):
    __tablename__ = "auditor_shares"
    id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    auditor_name = Column(String(120), default="")
    auditor_email = Column(String(200), default="")
    token_hash = Column(String(64), nullable=False, unique=True)
    token_prefix = Column(String(12), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    access_count = Column(Integer, default=0)
    last_accessed = Column(DateTime, nullable=True)
    # If set, only these control IDs are visible
    allowed_controls = Column(JSON, nullable=True)

    assessment = relationship("Assessment", back_populates="auditor_shares")
    created_by = relationship("User")


# ── Auditor Comments (read-only threads) ─────────────────────────────────────

class AuditorComment(Base):
    __tablename__ = "auditor_comments"
    id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    control_id = Column(String(40), nullable=False)
    # either an auditor share or an internal user
    auditor_share_id = Column(Integer, ForeignKey("auditor_shares.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name = Column(String(120), default="External Auditor")
    comment_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    # is_internal=True means visible only to internal team
    is_internal = Column(Boolean, default=False)

    assessment = relationship("Assessment", back_populates="auditor_comments")
    auditor_share = relationship("AuditorShare")
    user = relationship("User")


# ── RFI (Request for Information) ───────────────────────────────────────────

class RFI(Base):
    __tablename__ = "rfis"
    id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    # status: open | responded | closed
    status = Column(String(20), default="open")
    # priority: high | medium | low
    priority = Column(String(20), default="medium")
    # optional control linkage
    control_id = Column(String(40), default="")
    requested_by = Column(String(120), default="")
    assigned_to = Column(String(120), default="")
    due_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    closed_at = Column(DateTime, nullable=True)

    assessment = relationship("Assessment", back_populates="rfis")
    responses = relationship("RFIResponse", back_populates="rfi", cascade="all, delete-orphan")


class RFIResponse(Base):
    __tablename__ = "rfi_responses"
    id = Column(Integer, primary_key=True)
    rfi_id = Column(Integer, ForeignKey("rfis.id", ondelete="CASCADE"), nullable=False)
    responder_name = Column(String(120), default="")
    response_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    attachment_path = Column(String(255), default="")

    rfi = relationship("RFI", back_populates="responses")


# ── Site Settings (singleton) ────────────────────────────────────────────────

class SiteSettings(Base):
    """Singleton table for application-level settings.

    Always has exactly one row (id=1).  Use SiteSettings.get_or_create(db) to
    read or initialise it.  DB values take precedence over environment variables
    so admins can configure settings via the web UI without editing env files.
    """
    __tablename__ = "site_settings"
    id = Column(Integer, primary_key=True)
    # SMTP — if smtp_host is set these override env vars
    smtp_host = Column(String(255), default="")
    smtp_port = Column(Integer, default=587)
    smtp_user = Column(String(255), default="")
    smtp_password = Column(String(255), default="")  # plaintext; protect at DB level
    smtp_from = Column(String(255), default="")
    smtp_use_tls = Column(Boolean, default=True)
    # OIDC — if oidc_issuer is set these override CAAMS_OIDC_* env vars
    oidc_issuer = Column(String(512), default="")
    oidc_client_id = Column(String(255), default="")
    oidc_client_secret = Column(String(512), default="")  # encrypted at rest
    oidc_default_role = Column(String(50), default="viewer")

    @classmethod
    def get_or_create(cls, db):
        row = db.query(cls).filter(cls.id == 1).first()
        if row is None:
            row = cls(id=1)
            db.add(row)
            db.flush()
        return row


# ── Framework Crosswalk ──────────────────────────────────────────────────────

class FrameworkCrosswalk(Base):
    __tablename__ = "framework_crosswalks"
    id = Column(Integer, primary_key=True)
    source_control_id = Column(Integer, ForeignKey("controls.id", ondelete="CASCADE"), nullable=False)
    target_control_id = Column(Integer, ForeignKey("controls.id", ondelete="CASCADE"), nullable=False)
    # crosswalk_type: equivalent | related | partial
    crosswalk_type = Column(String(20), default="related")
    notes = Column(Text, default="")
    __table_args__ = (UniqueConstraint("source_control_id", "target_control_id"),)

    source_control = relationship("Control", foreign_keys=[source_control_id])
    target_control = relationship("Control", foreign_keys=[target_control_id])
