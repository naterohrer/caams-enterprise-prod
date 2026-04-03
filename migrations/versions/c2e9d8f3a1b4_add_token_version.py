"""add token_version to users for JWT revocation

Adds a token_version integer column to users. Incrementing this value
immediately invalidates all existing JWTs for that user, enabling instant
session revocation on password change, deactivation, or admin MFA reset.

Revision ID: c2e9d8f3a1b4
Revises: f8d2c1a4b7e3
Create Date: 2026-03-01 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c2e9d8f3a1b4'
down_revision: Union[str, None] = 'f8d2c1a4b7e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('users', 'token_version')
