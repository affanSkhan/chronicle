from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_upgrade_existing_0005_database_preserves_run_data_and_adds_lifecycle_fields(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "chronicle-migration-test.sqlite3"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0005_source_monitoring')"))
        connection.execute(text("CREATE TABLE paper_versions (id VARCHAR(36) PRIMARY KEY)"))
        connection.execute(text(
            "CREATE TABLE research_projects ("
            "id VARCHAR(36) PRIMARY KEY, owner_user_id VARCHAR(36), title VARCHAR(240) NOT NULL, "
            "research_question TEXT NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
        connection.execute(text(
            "CREATE TABLE research_runs ("
            "id VARCHAR(36) PRIMARY KEY, owner_user_id VARCHAR(36), project_id VARCHAR(36), "
            "question TEXT NOT NULL, mode VARCHAR(24) NOT NULL, status VARCHAR(24) NOT NULL, "
            "max_sources INTEGER NOT NULL, demo BOOLEAN NOT NULL, error_message TEXT, "
            "configuration JSON NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO research_projects (id, title, research_question, created_at, updated_at) "
            "VALUES ('project-1', 'Existing workspace', 'How should existing data be preserved?', "
            "'2026-01-01', '2026-01-01')"
        ))
        connection.execute(text(
            "INSERT INTO research_runs (id, question, mode, status, max_sources, demo, configuration, created_at, updated_at) "
            "VALUES ('run-1', 'How should old run state be preserved?', 'deep', 'completed', 4, 0, '{}', "
            "'2026-01-01', '2026-01-01')"
        ))

    api_dir = Path(__file__).resolve().parents[1]
    config = Config(str(api_dir / "alembic.ini"))
    config.set_main_option("script_location", str(api_dir / "migrations"))
    command.upgrade(config, "head")

    inspector = inspect(engine)
    project_columns = {column["name"] for column in inspector.get_columns("research_projects")}
    run_columns = {column["name"] for column in inspector.get_columns("research_runs")}
    run_status = next(column["type"] for column in inspector.get_columns("research_runs") if column["name"] == "status")
    assert "archived_at" in project_columns
    assert {"cancel_requested_at", "cancelled_at", "retry_of_run_id"} <= run_columns
    assert run_status.length == 40
    assert "ix_research_runs_retry_of_run_id" in {index["name"] for index in inspector.get_indexes("research_runs")}
    assert "original_pdf_bytes" in {column["name"] for column in inspector.get_columns("paper_versions")}

    with engine.connect() as connection:
        assert connection.execute(text("SELECT title FROM research_projects WHERE id='project-1'")).scalar_one() == "Existing workspace"
        row = connection.execute(text("SELECT question, status FROM research_runs WHERE id='run-1'")).one()
        assert row.question == "How should old run state be preserved?"
        assert row.status == "completed"
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0008_persistent_pdf_content"
