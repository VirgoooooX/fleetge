"""Database engine with SQLite WAL mode and SQLAlchemy URL support."""

from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

from app.config import get_settings


def _get_db_path(url: str) -> str:
    """Convert sqlite:///./path to absolute path, ensuring directory exists."""
    if url in {"sqlite://", "sqlite:///:memory:"}:
        return ":memory:"
    if url.startswith("sqlite:///"):
        rel = url[len("sqlite:///"):]
        p = Path(rel).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)
    return url


def create_engine_and_tables():
    settings = get_settings()
    database_url = settings.DATABASE_URL
    is_sqlite = database_url.startswith("sqlite:")
    if is_sqlite:
        db_path = _get_db_path(database_url)
        database_url = "sqlite:///:memory:" if db_path == ":memory:" else f"sqlite:///{db_path}"

    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if is_sqlite else {},
        echo=settings.LOG_LEVEL == "debug",
    )

    # Import models before create_all so each supported dialect sees every table.
    from app.models import (  # noqa: F401
        AuditLog,
        StackAutoUpdate,
        AutoUpdateRun,
        EnrollmentInvite,
        HostConfig,
        HostBillingAlertState,
        HostSubscription,
        HostTrafficBucket,
        HostTrafficCursor,
        HostTrafficDaily,
        ImageUpdateCache,
        Setting,
    )

    if not is_sqlite:
        SQLModel.metadata.create_all(engine)
        return engine

    # Enable WAL mode — use exec_driver_sql for raw PRAGMA statements
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        
        # Proactively migrate SQLite schema for new agent fields
        try:
            cursor = conn.exec_driver_sql("PRAGMA table_info(host_config)")
            columns = [row[1] for row in cursor.fetchall()]
            if columns:  # table exists
                if "agent_url" not in columns:
                    conn.exec_driver_sql("ALTER TABLE host_config ADD COLUMN agent_url TEXT")
                if "agent_token_encrypted" not in columns:
                    conn.exec_driver_sql("ALTER TABLE host_config ADD COLUMN agent_token_encrypted TEXT")
                if "app_profiles" not in columns:
                    conn.exec_driver_sql("ALTER TABLE host_config ADD COLUMN app_profiles TEXT")
                host_config_columns = {
                    "agent_instance_id": "TEXT",
                    "location_latitude": "REAL",
                    "location_longitude": "REAL",
                    "location_city": "TEXT",
                    "location_region": "TEXT",
                    "location_country": "TEXT",
                    "location_country_code": "TEXT",
                    "location_source": "TEXT",
                    "location_confirmed": "BOOLEAN DEFAULT 0",
                    "location_confidence": "TEXT",
                    "public_ip_effective": "TEXT",
                    "public_ip_source": "TEXT",
                    "public_ip_override": "TEXT",
                    "network_identity_evidence": "TEXT",
                    "network_identity_checked_at": "TIMESTAMP",
                    "enrollment_callback_ip": "TEXT",
                    "enrollment_callback_mode": "TEXT",
                    "traffic_billing_day": "INTEGER DEFAULT 1",
                }
                for column_name, column_ddl in host_config_columns.items():
                    if column_name not in columns:
                        conn.exec_driver_sql(
                            f"ALTER TABLE host_config ADD COLUMN {column_name} {column_ddl}"
                        )
                conn.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_host_config_agent_instance_id "
                    "ON host_config(agent_instance_id) WHERE agent_instance_id IS NOT NULL"
                )
        except Exception:
            # Table might not exist yet; create_all will handle it
            pass

        try:
            cursor = conn.exec_driver_sql("PRAGMA table_info(image_update_cache)")
            columns = [row[1] for row in cursor.fetchall()]
            if columns:
                image_update_cache_columns = {
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
                }
                for column_name, column_ddl in image_update_cache_columns.items():
                    if column_name not in columns:
                        conn.exec_driver_sql(
                            f"ALTER TABLE image_update_cache ADD COLUMN {column_name} {column_ddl}"
                        )
        except Exception:
            # Table might not exist yet; create_all will handle it
            pass
             
        conn.commit()

    SQLModel.metadata.create_all(engine)
    with engine.connect() as conn:
        run_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(auto_update_run)").fetchall()
        }
        if run_columns:
            run_migrations = {
                "request_id": "TEXT",
                "source": "TEXT NOT NULL DEFAULT 'auto'",
                "requested_by": "TEXT NOT NULL DEFAULT 'system'",
                "log_tail": "TEXT NOT NULL DEFAULT ''",
                "targets_json": "TEXT NOT NULL DEFAULT '{}'",
                "agent_job_id": "TEXT",
            }
            for column_name, column_ddl in run_migrations.items():
                if column_name not in run_columns:
                    conn.exec_driver_sql(
                        f"ALTER TABLE auto_update_run ADD COLUMN {column_name} {column_ddl}"
                    )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_auto_update_run_request_id "
                "ON auto_update_run(request_id)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_auto_update_run_source "
                "ON auto_update_run(source)"
            )
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_auto_update_run_host_request_stack "
                "ON auto_update_run(host_id, request_id, stack_name)"
            )
        cache_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(image_update_cache)").fetchall()
        }
        for column_name in ("registry_index_digest", "registry_manifest_digest", "registry_config_digest", "identity_error"):
            if cache_columns and column_name not in cache_columns:
                conn.exec_driver_sql(f"ALTER TABLE image_update_cache ADD COLUMN {column_name} TEXT")
        conn.commit()
    with engine.connect() as conn:
        invite_columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(enrollment_invite)").fetchall()]
        if invite_columns:
            if "agent_public_host" not in invite_columns:
                conn.exec_driver_sql("ALTER TABLE enrollment_invite ADD COLUMN agent_public_host TEXT DEFAULT ''")
            if "location_payload" not in invite_columns:
                conn.exec_driver_sql("ALTER TABLE enrollment_invite ADD COLUMN location_payload TEXT")
            if "callback_ip" not in invite_columns:
                conn.exec_driver_sql("ALTER TABLE enrollment_invite ADD COLUMN callback_ip TEXT")
            if "callback_mode" not in invite_columns:
                conn.exec_driver_sql("ALTER TABLE enrollment_invite ADD COLUMN callback_mode TEXT")
            conn.commit()
    with engine.connect() as conn:
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_host_config_agent_instance_id "
            "ON host_config(agent_instance_id) WHERE agent_instance_id IS NOT NULL"
        )
        conn.commit()
    return engine


engine = create_engine_and_tables()


def get_session() -> Session:
    """Dependency: yield a database session."""
    with Session(engine) as session:
        yield session
