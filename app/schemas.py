"""Pydantic v2 request/response schemas."""

from __future__ import annotations
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator


# ── Auth ─────────────────────────────────────────────────────────────────────

class SetupRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=12, max_length=128, title="Password")


class TokenResponse(BaseModel):
    # Normal auth (None when mfa_required=True)
    access_token: Optional[str] = None
    refresh_token: str = ""
    token_type: str = "bearer"
    role: Optional[str] = None
    # MFA step (set when password is valid but TOTP is required)
    mfa_required: bool = False
    mfa_token: Optional[str] = None


class MFAVerifyLogin(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=8)


class MFASetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class MFAConfirm(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class MFADisable(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class RefreshRequest(BaseModel):
    refresh_token: str


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=12, max_length=128, title="Password")
    role: str = Field(default="viewer")
    full_name: str = Field(default="", max_length=120)
    email: str = Field(default="", max_length=120)

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in ("admin", "contributor", "viewer", "auditor"):
            raise ValueError("role must be admin, contributor, viewer, or auditor")
        return v


# ── Invite flow ───────────────────────────────────────────────────────────────

class InviteCreate(BaseModel):
    """Admin payload for POST /auth/users/invite — no password required."""
    username: str = Field(min_length=1, max_length=64)
    role: str = Field(default="viewer")
    full_name: str = Field(default="", max_length=120)
    email: str = Field(default="", max_length=120)

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in ("admin", "contributor", "viewer", "auditor"):
            raise ValueError("role must be admin, contributor, viewer, or auditor")
        return v


class InviteResponse(BaseModel):
    """Returned to the admin after creating an invite."""
    user_id: int
    username: str
    invite_token: str   # raw token — embed in the accept-invite URL
    invite_url: str     # full URL if CAAMS_APP_BASE_URL is set, else ""
    email_sent: bool    # True if SMTP delivered the email automatically
    expires_hours: int  # how many hours until the token expires


class InviteAccept(BaseModel):
    """New user payload for POST /auth/invite/accept."""
    token: str
    password: str = Field(min_length=12, max_length=128, title="Password")


class UserUpdate(BaseModel):
    role: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=12, max_length=128, title="Password")
    is_active: Optional[bool] = None
    full_name: Optional[str] = Field(default=None, max_length=120)
    email: Optional[str] = Field(default=None, max_length=120)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime
    full_name: str
    email: str
    mfa_enabled: bool = False
    model_config = {"from_attributes": True}


class UserDirectoryEntry(BaseModel):
    username: str
    full_name: str
    model_config = {"from_attributes": True}


# ── API Tokens ────────────────────────────────────────────────────────────────

class APITokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    expires_at: Optional[datetime] = None
    scopes: List[str] = Field(default_factory=list)


class APITokenOut(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: datetime
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    is_active: bool
    scopes: List[str]
    user_id: int
    model_config = {"from_attributes": True}


class APITokenCreated(APITokenOut):
    """Returned once at creation — includes the plaintext token."""
    token: str


# ── Frameworks ────────────────────────────────────────────────────────────────

class FrameworkOut(BaseModel):
    id: int
    name: str
    version: str
    description: str
    control_count: int = 0
    model_config = {"from_attributes": True}


class ControlOut(BaseModel):
    id: int
    framework_id: int
    control_id: str
    title: str
    description: str
    required_tags: List[str]
    optional_tags: List[str]
    evidence: List[str]
    sub_controls: List[Any]
    model_config = {"from_attributes": True}


# ── Tools ─────────────────────────────────────────────────────────────────────

class ToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=500)
    capabilities: List[str] = Field(default_factory=list)


class ToolOut(BaseModel):
    id: int
    name: str
    category: str
    description: str
    capabilities: List[str] = []
    model_config = {"from_attributes": True}


# ── Assessments ───────────────────────────────────────────────────────────────

class AssessmentToolsUpdate(BaseModel):
    tool_ids: List[int] = Field(default_factory=list)


class AssessmentClone(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)


class AssessmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    framework_id: int
    tool_ids: List[int] = Field(default_factory=list)
    scope_notes: str = Field(default="", max_length=2000)
    is_recurring: bool = False
    recurrence_days: Optional[int] = None


class AssessmentOut(BaseModel):
    id: int
    name: str
    framework_id: int
    framework_name: str = ""
    created_at: datetime
    updated_at: datetime
    status: str
    scope_notes: str
    is_recurring: bool
    recurrence_days: Optional[int]
    next_review_date: Optional[datetime]
    created_by_id: Optional[int]
    created_by_name: str = ""
    tool_ids: List[int] = []
    model_config = {"from_attributes": True}


class AssessmentStatusUpdate(BaseModel):
    action: str   # submit_for_review | approve | return | archive
    comments: str = Field(default="", max_length=2000)


class SignoffOut(BaseModel):
    id: int
    action: str
    user_name: str
    comments: str
    timestamp: datetime
    model_config = {"from_attributes": True}


# ── Control Notes / Override ──────────────────────────────────────────────────

class ControlNoteUpdate(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=10000)
    evidence_url: Optional[str] = Field(default=None, max_length=2048)
    override_status: Optional[str] = None
    override_justification: Optional[str] = Field(default=None, max_length=2000)
    override_expires: Optional[datetime] = None
    assignee: Optional[str] = Field(default=None, max_length=120)
    due_date: Optional[datetime] = None
    is_applicable: Optional[bool] = None
    exclusion_reason: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("override_status")
    @classmethod
    def valid_override(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("covered", "partial", "not_covered", "not_applicable", ""):
            raise ValueError("override_status must be covered, partial, not_covered, not_applicable, or empty")
        return v


class ControlReviewUpdate(BaseModel):
    review_status: str
    review_notes: str = ""

    @field_validator("review_status")
    @classmethod
    def valid_review_status(cls, v: str) -> str:
        if v not in ("not_reviewed", "in_review", "approved", "rejected"):
            raise ValueError("Invalid review_status")
        return v


class ControlOwnershipUpdate(BaseModel):
    owner: Optional[str] = Field(default=None, max_length=120)
    team: Optional[str] = Field(default=None, max_length=120)
    evidence_owner: Optional[str] = Field(default=None, max_length=120)


class ControlNoteOut(BaseModel):
    id: Optional[int] = None
    assessment_id: Optional[int] = None
    control_id: str
    notes: str
    evidence_url: str
    override_status: Optional[str]
    override_justification: str
    override_expires: Optional[datetime]
    review_status: str
    review_notes: str
    reviewed_by_id: Optional[int]
    reviewed_at: Optional[datetime]
    assignee: str
    due_date: Optional[datetime]
    is_applicable: bool
    exclusion_reason: str
    model_config = {"from_attributes": True}


class ControlOwnershipOut(BaseModel):
    id: Optional[int] = None
    assessment_id: Optional[int] = None
    control_id: str
    owner: str
    team: str
    evidence_owner: str
    model_config = {"from_attributes": True}


# ── Evidence Files ────────────────────────────────────────────────────────────

class EvidenceFileOut(BaseModel):
    id: int
    assessment_id: int
    control_id: str
    original_filename: str
    file_size: int
    content_type: str
    description: str
    uploaded_by_name: str
    uploaded_at: datetime
    expires_at: Optional[datetime]
    approval_status: str
    approved_by_name: str
    approved_at: Optional[datetime]
    rejection_reason: str
    model_config = {"from_attributes": True}


class EvidenceApprovalUpdate(BaseModel):
    action: str   # approve | reject
    rejection_reason: str = ""

    @field_validator("action")
    @classmethod
    def valid_action(cls, v: str) -> str:
        if v not in ("approve", "reject"):
            raise ValueError("action must be approve or reject")
        return v


# ── Findings ──────────────────────────────────────────────────────────────────

class FindingCreate(BaseModel):
    control_id: str = Field(default="", max_length=40)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=10000)
    severity: str = Field(default="medium")
    remediation_owner: str = Field(default="", max_length=120)
    target_date: Optional[datetime] = None
    notes: str = Field(default="", max_length=5000)

    @field_validator("severity")
    @classmethod
    def valid_severity(cls, v: str) -> str:
        if v not in ("critical", "high", "medium", "low", "informational"):
            raise ValueError("Invalid severity")
        return v


class FindingUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=10000)
    severity: Optional[str] = None
    status: Optional[str] = None
    remediation_owner: Optional[str] = Field(default=None, max_length=120)
    target_date: Optional[datetime] = None
    actual_close_date: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("severity")
    @classmethod
    def valid_severity(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("critical", "high", "medium", "low", "informational"):
            raise ValueError("Invalid severity")
        return v

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("open", "in_progress", "remediated", "accepted", "closed"):
            raise ValueError("Invalid status")
        return v


class FindingOut(BaseModel):
    id: int
    assessment_id: int
    control_id: str
    title: str
    description: str
    severity: str
    status: str
    remediation_owner: str
    target_date: Optional[datetime]
    actual_close_date: Optional[datetime]
    created_by_id: Optional[int] = None
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    notes: str
    model_config = {"from_attributes": True}


# ── Risk Acceptances ──────────────────────────────────────────────────────────

class RiskAcceptanceCreate(BaseModel):
    control_id: str = Field(min_length=1, max_length=40)
    justification: str = Field(min_length=10, max_length=5000)
    risk_rating: str = Field(default="medium")
    residual_risk_notes: str = Field(default="", max_length=2000)
    expires_at: Optional[datetime] = None

    @field_validator("risk_rating")
    @classmethod
    def valid_rating(cls, v: str) -> str:
        if v not in ("critical", "high", "medium", "low"):
            raise ValueError("Invalid risk_rating")
        return v


class RiskAcceptanceOut(BaseModel):
    id: int
    assessment_id: int
    control_id: str
    justification: str
    risk_rating: str
    residual_risk_notes: str
    approved_by_name: str
    approved_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_by_name: str
    created_at: datetime
    model_config = {"from_attributes": True}


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    id: int
    timestamp: datetime
    user_id: Optional[int] = None
    user_name: str
    action: str
    resource_type: str
    resource_id: str
    details: dict
    ip_address: str
    model_config = {"from_attributes": True}


# ── Auditor Shares ────────────────────────────────────────────────────────────

class AuditorShareCreate(BaseModel):
    auditor_name: str = Field(min_length=1, max_length=120)
    auditor_email: str = Field(default="", max_length=200)
    expires_at: Optional[datetime] = None
    allowed_controls: Optional[List[str]] = None


class AuditorShareOut(BaseModel):
    id: int
    assessment_id: int
    auditor_name: str
    auditor_email: str
    token_prefix: str
    created_at: datetime
    expires_at: Optional[datetime]
    is_active: bool
    access_count: int
    last_accessed: Optional[datetime]
    model_config = {"from_attributes": True}


class AuditorShareCreated(AuditorShareOut):
    token: str


# ── Auditor Comments ──────────────────────────────────────────────────────────

class AuditorCommentCreate(BaseModel):
    control_id: str = Field(min_length=1, max_length=40)
    comment_text: str = Field(min_length=1, max_length=5000)
    is_internal: bool = False


class AuditorCommentOut(BaseModel):
    id: int
    assessment_id: int
    control_id: str
    author_name: str
    comment_text: str
    created_at: datetime
    is_internal: bool
    model_config = {"from_attributes": True}


# ── RFI ───────────────────────────────────────────────────────────────────────

class RFICreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    priority: str = Field(default="medium")
    control_id: str = Field(default="", max_length=40)
    requested_by: str = Field(default="", max_length=120)
    assigned_to: str = Field(default="", max_length=120)
    due_date: Optional[datetime] = None

    @field_validator("priority")
    @classmethod
    def valid_priority(cls, v: str) -> str:
        if v not in ("critical", "high", "medium", "low"):
            raise ValueError("Invalid priority")
        return v


class RFIUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = Field(default=None, max_length=120)
    due_date: Optional[datetime] = None

    @field_validator("priority")
    @classmethod
    def valid_priority(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("critical", "high", "medium", "low"):
            raise ValueError("Invalid priority")
        return v

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("open", "responded", "closed"):
            raise ValueError("Invalid status")
        return v


class RFIResponseCreate(BaseModel):
    responder_name: str = Field(default="", max_length=120)
    response_text: str = Field(min_length=1, max_length=10000)


class RFIResponseOut(BaseModel):
    id: int
    rfi_id: int
    responder_name: str
    response_text: str
    created_at: datetime
    model_config = {"from_attributes": True}


class RFIOut(BaseModel):
    id: int
    assessment_id: int
    title: str
    description: str
    status: str
    priority: str
    control_id: str
    requested_by: str
    assigned_to: str
    due_date: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime]
    responses: List[RFIResponseOut] = []
    model_config = {"from_attributes": True}


# ── Coverage result (computed, not stored) ────────────────────────────────────

class ControlResult(BaseModel):
    control_id: str
    title: str
    description: str
    status: str      # covered | partial | not_covered (or overridden)
    is_override: bool
    override_justification: str
    override_expires: Optional[datetime]
    covered_by: List[str]
    missing_tags: List[str]
    matched_tags: List[str]
    evidence_items: List[str]
    sub_controls: List[Any]
    notes: str
    evidence_url: str
    owner: str
    team: str
    evidence_owner: str
    review_status: str
    review_notes: str
    assignee: str
    due_date: Optional[datetime]
    is_overdue: bool
    is_applicable: bool
    exclusion_reason: str
    finding_count: int
    open_finding_count: int


class AssessmentResults(BaseModel):
    assessment_id: int
    assessment_name: str
    framework_name: str
    framework_version: str
    status: str
    total_controls: int
    covered: int
    partial: int
    not_covered: int
    not_applicable: int
    score: float
    controls: List[ControlResult]
