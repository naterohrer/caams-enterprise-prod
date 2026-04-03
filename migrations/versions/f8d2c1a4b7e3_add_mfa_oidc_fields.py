"""add MFA and OIDC fields to users

Adds totp_secret, mfa_enabled, and oidc_sub columns to the users table
to support TOTP-based MFA and OIDC/SSO single sign-on.

Revision ID: f8d2c1a4b7e3
Revises: a3f9c1b2d4e5
Create Date: 2026-03-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f8d2c1a4b7e3'
down_revision: Union[str, None] = 'a3f9c1b2d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('totp_secret', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('mfa_enabled', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('oidc_sub', sa.String(length=256), nullable=True))
    op.create_index('ix_users_oidc_sub', 'users', ['oidc_sub'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_users_oidc_sub', table_name='users')
    op.drop_column('users', 'oidc_sub')
    op.drop_column('users', 'mfa_enabled')
    op.drop_column('users', 'totp_secret')
