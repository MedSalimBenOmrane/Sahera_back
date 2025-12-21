"""Alter reponse.contenu to Text

Revision ID: c3f2a9e4b1d7
Revises: 7c2b8d9c1f0f
Create Date: 2026-01-10 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3f2a9e4b1d7"
down_revision = "7c2b8d9c1f0f"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "reponse",
        "contenu",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        "reponse",
        "contenu",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
