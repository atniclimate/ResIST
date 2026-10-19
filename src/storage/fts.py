"""FTS5 full-text search setup and queries."""
from sqlalchemy import text


def check_fts5_available(engine) -> bool:
    """Verify FTS5 extension is available."""
    try:
        with engine.connect() as conn:
            # Try creating a test FTS5 table to verify availability
            conn.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_test USING fts5(test)"))
            conn.execute(text("DROP TABLE IF EXISTS _fts5_test"))
            conn.commit()
        return True
    except Exception:
        return False


def create_fts_tables(engine):
    """Create FTS5 virtual table for resolution full-text search."""
    with engine.connect() as conn:
        # External content FTS5 table referencing resolution table
        # Uses porter tokenizer for stemming, unicode61 for proper Unicode handling
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS resolution_fts USING fts5(
                resolution_number,
                title,
                full_text,
                content='resolution',
                content_rowid='id',
                tokenize='porter unicode61'
            )
        """))

        # Trigger: sync FTS on INSERT
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS resolution_ai AFTER INSERT ON resolution BEGIN
                INSERT INTO resolution_fts(rowid, resolution_number, title, full_text)
                VALUES (new.id, new.resolution_number, new.title, new.full_text);
            END
        """))

        # Trigger: sync FTS on DELETE
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS resolution_ad AFTER DELETE ON resolution BEGIN
                INSERT INTO resolution_fts(resolution_fts, rowid, resolution_number, title, full_text)
                VALUES ('delete', old.id, old.resolution_number, old.title, old.full_text);
            END
        """))

        # Trigger: sync FTS on UPDATE
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS resolution_au AFTER UPDATE ON resolution BEGIN
                INSERT INTO resolution_fts(resolution_fts, rowid, resolution_number, title, full_text)
                VALUES ('delete', old.id, old.resolution_number, old.title, old.full_text);
                INSERT INTO resolution_fts(rowid, resolution_number, title, full_text)
                VALUES (new.id, new.resolution_number, new.title, new.full_text);
            END
        """))

        conn.commit()
