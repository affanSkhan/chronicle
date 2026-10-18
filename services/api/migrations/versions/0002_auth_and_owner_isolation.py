"""Add authentication and account ownership fields.

Revision ID: 0002_auth_owner
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_auth_owner"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _ensure_users_table():
    if "users" not in _inspector().get_table_names():
        op.create_table(
            "users",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("email", sa.String(length=254), nullable=False),
            sa.Column("password_hash", sa.String(length=500), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("email", name="uq_users_email"),
        )
    indexes = {idx["name"] for idx in _inspector().get_indexes("users")}
    if "ix_users_email" not in indexes:
        op.create_index("ix_users_email", "users", ["email"], unique=False)


def _ensure_owner_column(table_name: str):
    inspector = _inspector()
    if "owner_user_id" not in {col["name"] for col in inspector.get_columns(table_name)}:
        op.add_column(table_name, sa.Column("owner_user_id", sa.String(length=36), nullable=True))
    foreign_keys = inspector.get_foreign_keys(table_name)
    has_owner_fk = any(
        fk.get("constrained_columns") == ["owner_user_id"] and fk.get("referred_table") == "users"
        for fk in foreign_keys
    )
    if not has_owner_fk:
        op.create_foreign_key(
            f"fk_{table_name}_owner_user_id_users",
            table_name,
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="CASCADE",
        )
    indexes = {idx["name"] for idx in _inspector().get_indexes(table_name)}
    index_name = f"ix_{table_name}_owner_user_id"
    if index_name not in indexes:
        op.create_index(index_name, table_name, ["owner_user_id"], unique=False)


def upgrade():
    _ensure_users_table()
    for table_name in ("research_projects", "research_runs", "papers"):
        if table_name in _inspector().get_table_names():
            _ensure_owner_column(table_name)

    inspector = _inspector()
    if "papers" in inspector.get_table_names():
        unique_constraints = {item.get("name") for item in inspector.get_unique_constraints("papers")}
        if "uq_papers_doi" in unique_constraints:
            op.drop_constraint("uq_papers_doi", "papers", type_="unique")
        unique_constraints = {item.get("name") for item in _inspector().get_unique_constraints("papers")}
        if "uq_papers_owner_doi" not in unique_constraints:
            op.create_unique_constraint("uq_papers_owner_doi", "papers", ["owner_user_id", "doi"])

        # Earlier scaffold versions accidentally made the file hash globally unique.
        # Shared hashes are valid across separate accounts; deduplication is user-scoped.
        for index in _inspector().get_indexes("papers"):
            if index.get("name") == "ix_papers_file_sha256" and index.get("unique"):
                op.drop_index("ix_papers_file_sha256", table_name="papers")
        indexes = {idx["name"] for idx in _inspector().get_indexes("papers")}
        if "ix_papers_file_sha256" not in indexes:
            op.create_index("ix_papers_file_sha256", "papers", ["file_sha256"], unique=False)


def downgrade():
    # Ownership is deliberately retained on downgrade so a rollback cannot
    # erase account boundaries or make newly created private data unscoped.
    pass
