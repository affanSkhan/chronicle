"""Add cooperative cancellation/retry metadata and widen run status.

Revision ID: 0007_run_cancel_retry
Revises: 0006_project_archive
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_run_cancel_retry"
down_revision = "0006_project_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "research_runs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("research_runs")}

    # Existing PostgreSQL deployments had VARCHAR(24), which cannot store the
    # existing completed_with_limitations state. Widen it before writing states.
    if "status" in columns:
        status_col = next(column for column in inspector.get_columns("research_runs") if column["name"] == "status")
        if getattr(status_col["type"], "length", None) and status_col["type"].length < 40:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("research_runs") as batch:
                    batch.alter_column(
                        "status",
                        existing_type=sa.String(length=status_col["type"].length),
                        type_=sa.String(length=40),
                        existing_nullable=False,
                    )
            else:
                op.alter_column(
                    "research_runs",
                    "status",
                    existing_type=sa.String(length=status_col["type"].length),
                    type_=sa.String(length=40),
                    existing_nullable=False,
                )

    for name, column in (
        ("cancel_requested_at", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True)),
        ("cancelled_at", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)),
        ("retry_of_run_id", sa.Column("retry_of_run_id", sa.String(length=36), nullable=True)),
    ):
        if name not in columns:
            op.add_column("research_runs", column)

    inspector = sa.inspect(op.get_bind())
    existing_indexes = {index["name"] for index in inspector.get_indexes("research_runs")}
    if "ix_research_runs_retry_of_run_id" not in existing_indexes:
        op.create_index("ix_research_runs_retry_of_run_id", "research_runs", ["retry_of_run_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "research_runs" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("research_runs")}
    existing_indexes = {index["name"] for index in inspector.get_indexes("research_runs")}
    if "ix_research_runs_retry_of_run_id" in existing_indexes:
        op.drop_index("ix_research_runs_retry_of_run_id", table_name="research_runs")
    for name in ("retry_of_run_id", "cancelled_at", "cancel_requested_at"):
        if name in existing_columns:
            op.drop_column("research_runs", name)
    # Status width deliberately remains expanded: downgrading could truncate live state values.
