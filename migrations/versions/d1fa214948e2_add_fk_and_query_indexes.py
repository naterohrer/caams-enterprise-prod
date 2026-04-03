"""add_fk_and_query_indexes

Adds indexes on all foreign key columns and frequently-filtered columns to
improve query performance at scale (assessments with many findings/evidence/rfis).

Revision ID: d1fa214948e2
Revises: 5c17e666712d
Create Date: 2026-02-28 09:09:52.937814

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd1fa214948e2'
down_revision: Union[str, None] = '5c17e666712d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── findings ─────────────────────────────────────────────────────────────
    op.create_index("ix_findings_assessment_id", "findings", ["assessment_id"])
    op.create_index("ix_findings_status", "findings", ["status"])
    op.create_index("ix_findings_severity", "findings", ["severity"])

    # ── evidence_files ────────────────────────────────────────────────────────
    op.create_index("ix_evidence_files_assessment_id", "evidence_files", ["assessment_id"])
    op.create_index("ix_evidence_files_control_id", "evidence_files", ["control_id"])

    # ── rfis ──────────────────────────────────────────────────────────────────
    op.create_index("ix_rfis_assessment_id", "rfis", ["assessment_id"])
    op.create_index("ix_rfis_status", "rfis", ["status"])

    # ── rfi_responses ─────────────────────────────────────────────────────────
    op.create_index("ix_rfi_responses_rfi_id", "rfi_responses", ["rfi_id"])

    # ── risk_acceptances ──────────────────────────────────────────────────────
    op.create_index("ix_risk_acceptances_assessment_id", "risk_acceptances", ["assessment_id"])

    # ── api_tokens ────────────────────────────────────────────────────────────
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])
    op.create_index("ix_api_tokens_is_active", "api_tokens", ["is_active"])

    # ── assessment_signoffs ───────────────────────────────────────────────────
    op.create_index("ix_assessment_signoffs_assessment_id", "assessment_signoffs", ["assessment_id"])

    # ── auditor_shares ────────────────────────────────────────────────────────
    op.create_index("ix_auditor_shares_assessment_id", "auditor_shares", ["assessment_id"])

    # ── auditor_comments ──────────────────────────────────────────────────────
    op.create_index("ix_auditor_comments_assessment_id", "auditor_comments", ["assessment_id"])

    # ── control_notes ─────────────────────────────────────────────────────────
    op.create_index("ix_control_notes_assessment_id", "control_notes", ["assessment_id"])

    # ── control_ownership ─────────────────────────────────────────────────────
    op.create_index("ix_control_ownership_assessment_id", "control_ownership", ["assessment_id"])

    # ── controls ──────────────────────────────────────────────────────────────
    op.create_index("ix_controls_framework_id_control_id", "controls", ["framework_id", "control_id"])

    # ── audit_log ─────────────────────────────────────────────────────────────
    op.create_index("ix_audit_log_resource_type", "audit_log", ["resource_type"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_user_name", "audit_log", ["user_name"])


def downgrade() -> None:
    op.drop_index("ix_findings_assessment_id", table_name="findings")
    op.drop_index("ix_findings_status", table_name="findings")
    op.drop_index("ix_findings_severity", table_name="findings")
    op.drop_index("ix_evidence_files_assessment_id", table_name="evidence_files")
    op.drop_index("ix_evidence_files_control_id", table_name="evidence_files")
    op.drop_index("ix_rfis_assessment_id", table_name="rfis")
    op.drop_index("ix_rfis_status", table_name="rfis")
    op.drop_index("ix_rfi_responses_rfi_id", table_name="rfi_responses")
    op.drop_index("ix_risk_acceptances_assessment_id", table_name="risk_acceptances")
    op.drop_index("ix_api_tokens_user_id", table_name="api_tokens")
    op.drop_index("ix_api_tokens_is_active", table_name="api_tokens")
    op.drop_index("ix_assessment_signoffs_assessment_id", table_name="assessment_signoffs")
    op.drop_index("ix_auditor_shares_assessment_id", table_name="auditor_shares")
    op.drop_index("ix_auditor_comments_assessment_id", table_name="auditor_comments")
    op.drop_index("ix_control_notes_assessment_id", table_name="control_notes")
    op.drop_index("ix_control_ownership_assessment_id", table_name="control_ownership")
    op.drop_index("ix_controls_framework_id_control_id", table_name="controls")
    op.drop_index("ix_audit_log_resource_type", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_user_name", table_name="audit_log")
