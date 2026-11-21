"""Database engine and forward-compatible SQLite schema upgrades."""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import event, inspect
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from app.config import get_settings


_LEGACY_ADDED_COLUMNS = {
    "host_config": {
        "agent_url": "TEXT",
        "agent_token_encrypted": "TEXT",
        "app_profiles": "TEXT",
        "agent_instance_id": "TEXT",
        "location_latitude": "REAL",
        "location_longitude": "REAL",
        "location_city": "TEXT",
        "location_region": "TEXT",
        "location_country": "TEXT",
        "location_country_code": "TEXT",
        "location_source": "TEXT",
        "location_confirmed": "BOOLEAN DEFAULT FALSE",
        "location_confidence": "TEXT",
        "public_ip_effective": "TEXT",
        "public_ip_source": "TEXT",
        "public_ip_override": "TEXT",
        "network_identity_evidence": "TEXT",
        "network_identity_checked_at": "TIMESTAMP",
        "enrollment_callback_ip": "TEXT",
        "enrollment_callback_mode": "TEXT",
        "traffic_billing_day": "INTEGER DEFAULT 1",
        "logo": "TEXT",
    },
    "image_update_cache": {
        "registry": "TEXT",
        "platform": "TEXT",
        "registry_index_digest": "TEXT",
        "registry_manifest_digest": "TEXT",
        "registry_config_digest": "TEXT",
        "identity_error": "TEXT",
        "http_status": "INTEGER",
        "matched_field": "TEXT",
        "retry_after": "INTEGER",
        "pending_current_digest": "TEXT",
        "pending_registry_digest": "TEXT",
        "pending_platform": "TEXT",
        "pending_matched_field": "TEXT",
        "pending_detected_at": "TIMESTAMP",
        "last_failure_http_status": "INTEGER",
        "last_failure_retry_after": "INTEGER",
    },
    "auto_update_run": {
        "request_id": "TEXT",
        "source": "TEXT NOT NULL DEFAULT 'auto'",
        "requested_by": "TEXT NOT NULL DEFAULT 'system'",
        "log_tail": "TEXT NOT NULL DEFAULT ''",
        "targets_json": "TEXT NOT NULL DEFAULT '{}'",
        "agent_job_id": "TEXT",
    },
    "enrollment_invite": {
        "agent_public_host": "TEXT DEFAULT ''",
        "location_payload": "TEXT",
        "callback_ip": "TEXT",
        "callback_mode": "TEXT",
    },
}


def _get_db_path(url: str) -> str:
    """Convert sqlite:///./path to absolute path, ensuring directory exists."""
    if url in {"sqlite://", "sqlite:///:memory:"}:
        return ":memory:"
    if url.startswith("sqlite:///"):
        rel = url[len("sqlite:///"):]
        path = Path(rel).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)
    return url


def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def _upgrade_schema(connection: Connection) -> None:
    inspector = inspect(connection)
    for table_name, additions in _LEGACY_ADDED_COLUMNS.items():
        if not inspector.has_table(table_name):
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        for name, ddl in additions.items():
            if name not in columns:
                connection.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}")


def create_engine_and_tables() -> Engine:
    from app import models  # noqa: F401 — register all table models

    settings = get_settings()
    database_url = make_url(settings.DATABASE_URL)
    dialect = database_url.get_backend_name()
    sqlite = dialect == "sqlite"
    if sqlite:
        db_path = _get_db_path(f"sqlite:///{database_url.database or ':memory:'}")
        database_url = database_url.set(database=db_path)
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if sqlite else {},
        poolclass=StaticPool if sqlite and db_path == ":memory:" else None,
        echo=settings.LOG_LEVEL == "debug",
    )
    if sqlite:
        event.listen(engine, "connect", _configure_sqlite_connection)
    try:
        with engine.connect() as connection:
            if sqlite:
                if db_path != ":memory:":
                    connection.exec_driver_sql("PRAGMA journal_mode=WAL").close()
                    connection.commit()
                # Acquire the lock before inspecting and start a real transaction for SQLite DDL.
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            if dialect in {"sqlite", "postgresql"}:
                _upgrade_schema(connection)
            SQLModel.metadata.create_all(connection)
            if dialect in {"sqlite", "postgresql"}:
                for index in SQLModel.metadata.tables["auto_update_run"].indexes:
                    index.create(connection, checkfirst=True)
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_host_config_agent_instance_id "
                    "ON host_config(agent_instance_id) WHERE agent_instance_id IS NOT NULL"
                )
            connection.commit()
    except Exception:
        engine.dispose()
        raise
    return engine


engine = create_engine_and_tables()


def get_session() -> Iterator[Session]:
    """Dependency: yield a database session."""
    with Session(engine) as session:
        yield session
