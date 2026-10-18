"""Add review and evidence-state audit events.

Revision ID: 0003_audit_events
Revises: 0002_auth_owner
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_audit_events"
down_revision = "0002_auth_owner"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "audit_events" not in tables:
        op.create_table(
            "audit_events",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("actor_user_id", sa.String(length=36), nullable=True),
            sa.Column("run_id", sa.String(length=36), nullable=True),
            sa.Column("target_entity_type", sa.String(length=80), nullable=False),
            sa.Column("target_entity_id", sa.String(length=100), nullable=False),
            sa.Column("action", sa.String(length=120), nullable=False),
            sa.Column("previous_value", sa.JSON(), nullable=True),
            sa.Column("new_value", sa.JSON(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("resolution_status", sa.String(length=40), nullable=False, server_default="recorded"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"], ondelete="CASCADE"),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("audit_events")}
    for column in ("actor_user_id", "run_id", "target_entity_type", "target_entity_id", "action", "created_at"):
        name = f"ix_audit_events_{column}"
        if name not in indexes:
            op.create_index(name, "audit_events", [column], unique=False)


def downgrade():
    # Keep the audit trail when rolling back application code.
    pass
