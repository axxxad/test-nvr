from sqlalchemy import inspect, text

from app.database import engine


def _add_column_if_missing(table: str, column: str, ddl: str) -> None:
    with engine.connect() as conn:
        columns = {col["name"] for col in inspect(engine).get_columns(table)}
        if column not in columns:
            conn.execute(text(ddl))
            conn.commit()


def migrate_schema() -> None:
    """Add columns introduced after initial deploy (SQLite has no auto-migrate)."""
    _add_column_if_missing(
        "cameras",
        "recording_enabled",
        "ALTER TABLE cameras ADD COLUMN recording_enabled BOOLEAN NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(
        "cameras",
        "retention_days",
        "ALTER TABLE cameras ADD COLUMN retention_days INTEGER NOT NULL DEFAULT 2",
    )
