"""Lapisan akses database SQLite."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DATABASE_PATH


def utc_now() -> str:
    """Timestamp UTC berformat ISO-8601."""
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection():
    """Context manager koneksi SQLite dengan commit/rollback otomatis."""
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    # ON DELETE CASCADE pada tabel leads hanya berlaku jika FK diaktifkan per koneksi.
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    """Buat skema awal dan tandai job yang tertunda sebagai gagal saat restart."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                request_json TEXT NOT NULL,
                result_count INTEGER NOT NULL DEFAULT 0,
                apify_run_id TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                place_id TEXT,
                company_name TEXT NOT NULL DEFAULT '',
                data_json TEXT NOT NULL,
                raw_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_leads_job_id ON leads(job_id, id)"
        )
        connection.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                error = 'Server restart memutus job yang belum selesai.',
                updated_at = ?
            WHERE status IN ('queued', 'running')
            """,
            (utc_now(),),
        )
