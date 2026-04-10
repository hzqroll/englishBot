"""rename qq columns to feishu naming

Revision ID: 0002_rename_qq_columns
Revises: 0001_initial
Create Date: 2026-04-10
"""

from alembic import op


revision = "0002_rename_qq_columns"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("qq_user_id", new_column_name="open_id")
    with op.batch_alter_table("groups") as batch_op:
        batch_op.alter_column("qq_group_id", new_column_name="chat_id")


def downgrade() -> None:
    with op.batch_alter_table("groups") as batch_op:
        batch_op.alter_column("chat_id", new_column_name="qq_group_id")
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("open_id", new_column_name="qq_user_id")
