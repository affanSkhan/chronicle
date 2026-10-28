"""Persist original uploaded PDF bytes in the paper record.

Revision ID: 0008_persistent_pdf_content
Revises: 0007_run_cancel_retry
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_persistent_pdf_content"
down_revision = "0007_run_cancel_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "papers" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("papers")}
    if "file_content" not in columns:
        op.add_column("papers", sa.Column("file_content", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "papers" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("papers")}
    if "file_content" in columns:
        op.drop_column("papers", "file_content")
