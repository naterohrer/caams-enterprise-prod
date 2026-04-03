"""add invite_tokens table

Adds the invite_tokens table used by the POST /auth/users/invite and
POST /auth/invite/accept endpoints introduced in the invite-flow feature.

Revision ID: a3f9c1b2d4e5
Revises: d1fa214948e2
Create Date: 2026-02-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f9c1b2d4e5'
down_revision: Union[str, None] = 'd1fa214948e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'invite_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('token_prefix', sa.String(length=12), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_invite_tokens_user_id', 'invite_tokens', ['user_id'])
    op.create_index('ix_invite_tokens_used_at', 'invite_tokens', ['used_at'])


def downgrade() -> None:
    op.drop_index('ix_invite_tokens_used_at', table_name='invite_tokens')
    op.drop_index('ix_invite_tokens_user_id', table_name='invite_tokens')
    op.drop_table('invite_tokens')
