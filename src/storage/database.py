"""Database engine and session management."""
import os
from sqlmodel import SQLModel, Session, create_engine
from pathlib import Path
from typing import Generator

from resist.db.schema import STATEMENT_COLUMNS

# All corpus data lives in the datapool (D-008): RESIST_DATA_DIR, default ./datapool at the repo root
DATA_DIR = Path(os.environ.get("RESIST_DATA_DIR") or Path(__file__).parent.parent.parent / "datapool")
DATABASE_PATH = DATA_DIR / "db" / "resolutions.db"

_engine = None


def get_engine():
    """Get or create database engine."""
    global _engine
    if _engine is None:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{DATABASE_PATH}", echo=False)
        _add_statement_columns(_engine)
    return _engine


def _add_statement_columns(engine) -> None:
    """Additive statement columns for a database built before R1.21 / LR-F, appended in order
    (shortcut: raw DDL, no migration framework until R2b)."""
    with engine.begin() as c:
        cols = {r[1] for r in c.exec_driver_sql("pragma table_info(statement)")}
        for name, sql_type in (("page_number", "integer"),) + STATEMENT_COLUMNS:
            if cols and name not in cols:
                c.exec_driver_sql(f"alter table statement add column {name} {sql_type}")


def get_session() -> Generator[Session, None, None]:
    """Yield a database session."""
    engine = get_engine()
    with Session(engine) as session:
        yield session


def init_db():
    """Initialize database tables."""
    from src.models.resolution import Resolution, Statement, Citation, Sponsor, Keyword, Theme, ResolutionTheme
    from .fts import create_fts_tables, check_fts5_available

    engine = get_engine()

    # Check FTS5 availability
    if not check_fts5_available(engine):
        raise RuntimeError("SQLite FTS5 extension not available. Update SQLite.")

    # Create SQLModel tables
    SQLModel.metadata.create_all(engine)

    # Create FTS5 virtual table and triggers
    create_fts_tables(engine)

    return engine
