"""add mail config fields to admin

Revision ID: 7c2b8d9c1f0f
Revises: b6d0482d595f
Create Date: 2025-12-16 16:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7c2b8d9c1f0f'
down_revision = 'b6d0482d595f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('admin', sa.Column('mail_sender_email', sa.String(length=255), nullable=True))
    op.add_column('admin', sa.Column('mail_sender_name', sa.String(length=255), nullable=True))
    op.add_column('admin', sa.Column('smtp_host', sa.String(length=255), nullable=True))
    op.add_column('admin', sa.Column('smtp_port', sa.Integer(), nullable=True))
    op.add_column('admin', sa.Column('smtp_use_tls', sa.Boolean(), nullable=True))
    op.add_column('admin', sa.Column('smtp_username', sa.String(length=255), nullable=True))
    op.add_column('admin', sa.Column('smtp_password', sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column('admin', 'smtp_password')
    op.drop_column('admin', 'smtp_username')
    op.drop_column('admin', 'smtp_use_tls')
    op.drop_column('admin', 'smtp_port')
    op.drop_column('admin', 'smtp_host')
    op.drop_column('admin', 'mail_sender_name')
    op.drop_column('admin', 'mail_sender_email')
