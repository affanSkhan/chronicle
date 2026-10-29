"""Persist original uploaded PDF bytes in PostgreSQL when no private bucket is configured.

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
    if "paper_versions" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("paper_versions")}
    if "original_pdf_bytes" not in columns:
        op.add_column("paper_versions", sa.Column("original_pdf_bytes", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "paper_versions" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("paper_versions")}
    if "original_pdf_bytes" in columns:
        op.drop_column("paper_versions", "original_pdf_bytes")
