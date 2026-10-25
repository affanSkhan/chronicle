"""Add soft-archive lifecycle state to research workspaces.

Revision ID: 0006_project_archive
Revises: 0005_source_monitoring
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_project_archive"
down_revision = "0005_source_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "research_projects" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("research_projects")}
    if "archived_at" not in columns:
        op.add_column("research_projects", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "research_projects" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("research_projects")}
    if "archived_at" in columns:
        op.drop_column("research_projects", "archived_at")
