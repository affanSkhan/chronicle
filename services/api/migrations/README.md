# Database migrations

Run these commands from the services/api directory with the project environment active:

    alembic upgrade head
    alembic current

Set DATABASE_URL for the target database before applying migrations. The initial migration uses SQLAlchemy model metadata as the bootstrap schema. Subsequent changes should use explicit Alembic revisions and be reviewed before production use.
