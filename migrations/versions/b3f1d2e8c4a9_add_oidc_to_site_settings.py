"""add OIDC fields to site_settings

Extends the site_settings singleton table with four OIDC/SSO columns so
admins can configure OpenID Connect via the web UI without editing
environment files or restarting the service.  DB values take precedence
over the CAAMS_OIDC_* environment variables at runtime.

Revision ID: b3f1d2e8c4a9
Revises: e4b7f2a3c9d1
Create Date: 2026-04-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3f1d2e8c4a9'
down_revision: Union[str, None] = 'e4b7f2a3c9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('site_settings', sa.Column('oidc_issuer',        sa.String(512), nullable=True, server_default=''))
    op.add_column('site_settings', sa.Column('oidc_client_id',     sa.String(255), nullable=True, server_default=''))
    op.add_column('site_settings', sa.Column('oidc_client_secret', sa.String(512), nullable=True, server_default=''))
    op.add_column('site_settings', sa.Column('oidc_default_role',  sa.String(50),  nullable=True, server_default='viewer'))


def downgrade() -> None:
    op.drop_column('site_settings', 'oidc_default_role')
    op.drop_column('site_settings', 'oidc_client_secret')
    op.drop_column('site_settings', 'oidc_client_id')
    op.drop_column('site_settings', 'oidc_issuer')
