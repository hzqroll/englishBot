"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-03 18:00:00
"""

from alembic import op
import sqlalchemy as sa

from src.infrastructure.db.base import Base
from src.infrastructure.db import models  # noqa: F401


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)

