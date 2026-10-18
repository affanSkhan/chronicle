"""Attach extracted study context to a source passage.

Revision ID: 0004_study_source_passage
Revises: 0003_audit_events
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_study_source_passage"
down_revision = "0003_audit_events"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "studies" not in tables:
        return
    columns = {item["name"] for item in inspector.get_columns("studies")}
    if "source_passage_id" not in columns:
        op.add_column("studies", sa.Column("source_passage_id", sa.String(length=36), nullable=True))
    foreign_keys = sa.inspect(op.get_bind()).get_foreign_keys("studies")
    has_fk = any(
        item.get("constrained_columns") == ["source_passage_id"] and item.get("referred_table") == "passages"
        for item in foreign_keys
    )
    if not has_fk:
        op.create_foreign_key(
            "fk_studies_source_passage_id_passages",
            "studies",
            "passages",
            ["source_passage_id"],
            ["id"],
            ondelete="SET NULL",
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("studies")}
    if "ix_studies_source_passage_id" not in indexes:
        op.create_index("ix_studies_source_passage_id", "studies", ["source_passage_id"], unique=False)


def downgrade():
    # Retain scientific provenance records during code rollback.
    pass
