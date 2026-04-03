"""add site_settings table for DB-persisted configuration

Adds a singleton site_settings table (always one row, id=1) that allows
admins to configure SMTP and other settings via the web UI without editing
environment files or restarting the service.  DB values take precedence
over environment variables at runtime.

Revision ID: e4b7f2a3c9d1
Revises: c2e9d8f3a1b4
Create Date: 2026-03-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4b7f2a3c9d1'
down_revision: Union[str, None] = 'c2e9d8f3a1b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'site_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('smtp_host', sa.String(255), nullable=True, server_default=''),
        sa.Column('smtp_port', sa.Integer(), nullable=True, server_default='587'),
        sa.Column('smtp_user', sa.String(255), nullable=True, server_default=''),
        sa.Column('smtp_password', sa.String(255), nullable=True, server_default=''),
        sa.Column('smtp_from', sa.String(255), nullable=True, server_default=''),
        sa.Column('smtp_use_tls', sa.Boolean(), nullable=True, server_default='true'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('site_settings')
