"""Add scheduled source monitoring settings and check history.

Revision ID: 0005_source_monitoring
Revises: 0004_study_source_passage
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_source_monitoring"
down_revision = "0004_study_source_passage"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "papers" in tables:
        columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("papers")}
        if "monitoring_enabled" not in columns:
            op.add_column("papers", sa.Column("monitoring_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "monitor_interval_minutes" not in columns:
            op.add_column("papers", sa.Column("monitor_interval_minutes", sa.Integer(), nullable=False, server_default="1440"))
        if "last_status_check_at" not in columns:
            op.add_column("papers", sa.Column("last_status_check_at", sa.DateTime(timezone=True), nullable=True))
        if "next_status_check_at" not in columns:
            op.add_column("papers", sa.Column("next_status_check_at", sa.DateTime(timezone=True), nullable=True))
        indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("papers")}
        for name, column in (
            ("ix_papers_monitoring_enabled", "monitoring_enabled"),
            ("ix_papers_next_status_check_at", "next_status_check_at"),
        ):
            if name not in indexes:
                op.create_index(name, "papers", [column], unique=False)

    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "source_status_checks" not in tables:
        op.create_table(
            "source_status_checks",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("paper_id", sa.String(length=36), nullable=False),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("trigger_type", sa.String(length=24), nullable=False, server_default="manual"),
            sa.Column("outcome", sa.String(length=24), nullable=False, server_default="ok"),
            sa.Column("provider_states", sa.JSON(), nullable=False),
            sa.Column("signals", sa.JSON(), nullable=False),
            sa.Column("result_hash", sa.String(length=64), nullable=False),
            sa.Column("previous_result_hash", sa.String(length=64), nullable=True),
            sa.Column("change_detected", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("source_status_checks")}
    for name, column in (
        ("ix_source_status_checks_paper_id", "paper_id"),
        ("ix_source_status_checks_checked_at", "checked_at"),
    ):
        if name not in indexes:
            op.create_index(name, "source_status_checks", [column], unique=False)


def downgrade():
    # Preserve monitoring history if application code is rolled back.
    pass
