"""Persist report conclusions and their claim/passage provenance edges.

Revision ID: 0009_conclusion_evidence
Revises: 0008_persistent_pdf_content
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_conclusion_evidence"
down_revision = "0008_persistent_pdf_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "research_runs" not in tables or "report_versions" not in tables:
        return

    if "conclusions" not in tables:
        op.create_table(
            "conclusions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("report_version_id", sa.String(length=36), sa.ForeignKey("report_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("statement", sa.Text(), nullable=False),
            sa.Column("relation_type", sa.String(length=40), nullable=False, server_default="qualifies"),
            sa.Column("reviewer_status", sa.String(length=40), nullable=False, server_default="needs_review"),
            sa.Column("provenance_basis", sa.String(length=40), nullable=False, server_default="model_inferred"),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("uncertainty_notes", sa.Text(), nullable=True),
            sa.Column("metadata_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("report_version_id", "statement", name="uq_conclusion_report_statement"),
        )
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("conclusions")}
    for index_name, column_name in (
        ("ix_conclusions_run_id", "run_id"),
        ("ix_conclusions_report_version_id", "report_version_id"),
        ("ix_conclusions_reviewer_status", "reviewer_status"),
    ):
        if index_name not in indexes:
            op.create_index(index_name, "conclusions", [column_name], unique=False)

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "conclusion_evidence_relations" not in tables:
        op.create_table(
            "conclusion_evidence_relations",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("conclusion_id", sa.String(length=36), sa.ForeignKey("conclusions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("claim_id", sa.String(length=36), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=True),
            sa.Column("passage_id", sa.String(length=36), sa.ForeignKey("passages.id", ondelete="CASCADE"), nullable=True),
            sa.Column("relation_type", sa.String(length=40), nullable=False, server_default="supports"),
            sa.Column("provenance_basis", sa.String(length=40), nullable=False, server_default="model_inferred"),
            sa.Column("reviewer_status", sa.String(length=40), nullable=False, server_default="needs_review"),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("claim_id IS NOT NULL OR passage_id IS NOT NULL", name="ck_conclusion_edge_has_source"),
            sa.UniqueConstraint("conclusion_id", "claim_id", "passage_id", "relation_type", name="uq_conclusion_evidence_edge"),
        )
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("conclusion_evidence_relations")}
    for index_name, column_name in (
        ("ix_conclusion_evidence_relations_conclusion_id", "conclusion_id"),
        ("ix_conclusion_evidence_relations_claim_id", "claim_id"),
        ("ix_conclusion_evidence_relations_passage_id", "passage_id"),
    ):
        if index_name not in indexes:
            op.create_index(index_name, "conclusion_evidence_relations", [column_name], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "conclusion_evidence_relations" in tables:
        for index_name in (
            "ix_conclusion_evidence_relations_passage_id",
            "ix_conclusion_evidence_relations_claim_id",
            "ix_conclusion_evidence_relations_conclusion_id",
        ):
            if index_name in {index["name"] for index in sa.inspect(bind).get_indexes("conclusion_evidence_relations")}:
                op.drop_index(index_name, table_name="conclusion_evidence_relations")
        op.drop_table("conclusion_evidence_relations")
    if "conclusions" in set(sa.inspect(bind).get_table_names()):
        for index_name in (
            "ix_conclusions_reviewer_status",
            "ix_conclusions_report_version_id",
            "ix_conclusions_run_id",
        ):
            if index_name in {index["name"] for index in sa.inspect(bind).get_indexes("conclusions")}:
                op.drop_index(index_name, table_name="conclusions")
        op.drop_table("conclusions")
