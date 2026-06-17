"""SQLite database engine with WAL mode, single-connection for single-worker."""

from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

from app.config import get_settings


def _get_db_path(url: str) -> str:
    """Convert sqlite:///./path to absolute path, ensuring directory exists."""
    if url.startswith("sqlite:///"):
        rel = url[len("sqlite:///"):]
        p = Path(rel).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)
    return url


def create_engine_and_tables():
    settings = get_settings()
    db_path = _get_db_path(settings.DATABASE_URL)

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={
            "check_same_thread": False,
            # Enable WAL mode for better concurrent read/write in single-worker
        },
        echo=settings.LOG_LEVEL == "debug",
    )

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
        except Exception as exc:
            # Table might not exist yet; create_all will handle it
            pass
            
        conn.commit()

    # Import models so SQLModel.metadata knows about them before create_all
    from app.models import HostConfig, AuditLog, ImageUpdateCache, Setting  # noqa: F401

    SQLModel.metadata.create_all(engine)
    return engine


engine = create_engine_and_tables()


def get_session() -> Session:
    """Dependency: yield a database session."""
    with Session(engine) as session:
        yield session
