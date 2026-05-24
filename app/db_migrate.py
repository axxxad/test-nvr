from sqlalchemy import inspect, text

from app.database import engine


def _add_column_if_missing(table: str, column: str, ddl: str) -> bool:
    with engine.connect() as conn:
        columns = {col["name"] for col in inspect(engine).get_columns(table)}
        if column not in columns:
            conn.execute(text(ddl))
            conn.commit()
            return True
    return False


def _backfill_camera_sort_order() -> None:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id FROM cameras ORDER BY id")).fetchall()
        for index, (camera_id,) in enumerate(rows):
            conn.execute(
                text("UPDATE cameras SET sort_order = :order WHERE id = :id"),
                {"order": index, "id": camera_id},
            )
        conn.commit()


def _drop_segments_table_if_present() -> None:
    with engine.connect() as conn:
        tables = set(inspect(engine).get_table_names())
        if "segments" in tables:
            conn.execute(text("DROP TABLE segments"))
            conn.commit()


def migrate_schema() -> None:
    """Add columns introduced after initial deploy (SQLite has no auto-migrate)."""
    _drop_segments_table_if_present()
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
    _add_column_if_missing(
        "cameras",
        "record_audio",
        "ALTER TABLE cameras ADD COLUMN record_audio BOOLEAN NOT NULL DEFAULT 0",
    )
    if _add_column_if_missing(
        "cameras",
        "sort_order",
        "ALTER TABLE cameras ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0",
    ):
        _backfill_camera_sort_order()
