"""Persist private original uploaded PDF bytes in a separate PostgreSQL table.

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
    if "uploaded_pdf_blobs" in inspector.get_table_names():
        return
    op.create_table(
        "uploaded_pdf_blobs",
        sa.Column(
            "paper_version_id",
            sa.String(length=36),
            sa.ForeignKey("paper_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_uploaded_pdf_blobs_sha256", "uploaded_pdf_blobs", ["sha256"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "uploaded_pdf_blobs" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("uploaded_pdf_blobs")}
    if "ix_uploaded_pdf_blobs_sha256" in indexes:
        op.drop_index("ix_uploaded_pdf_blobs_sha256", table_name="uploaded_pdf_blobs")
    op.drop_table("uploaded_pdf_blobs")
