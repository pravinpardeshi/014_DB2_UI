from __future__ import annotations
import logging
from typing import TYPE_CHECKING
from config import Settings

if TYPE_CHECKING:
    import pyodbc

logger = logging.getLogger(__name__)

try:
    import pyodbc as _pyodbc

    ODBC_AVAILABLE = True
except ImportError:
    _pyodbc = None  # type: ignore[assignment]
    ODBC_AVAILABLE = False
    logger.warning("pyodbc not available – running in demo mode (no ODBC driver)")


class Database:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._connection = None

    def connect(self):
        if not ODBC_AVAILABLE:
            raise ConnectionError("pyodbc/ODBC driver not installed")
        if self._connection is None:
            logger.info(
                "Connecting to Mainframe via ODBC: %s:%s/%s",
                self._settings.odbc_host,
                self._settings.odbc_port,
                self._settings.odbc_database,
            )
            self._connection = _pyodbc.connect(self._settings.connection_string)
        return self._connection

    def close(self) -> None:
        if self._connection:
            self._connection.close()
            self._connection = None
            logger.info("ODBC connection closed")

    def execute(self, query: str, params: tuple = ()):
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor

    def fetch_all(self, query: str, params: tuple = ()) -> list[dict]:
        cursor = self.execute(query, params)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def fetch_one(self, query: str, params: tuple = ()) -> dict | None:
        cursor = self.execute(query, params)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        row = cursor.fetchone()
        if row:
            return dict(zip(columns, row))
        return None

    def fetch_one_value(self, query: str, params: tuple = ()):
        cursor = self.execute(query, params)
        row = cursor.fetchone()
        return row[0] if row else None


db: Database | None = None


def get_database() -> Database:
    global db
    if db is None:
        raise RuntimeError("Database not initialized")
    return db


def init_database(settings: Settings) -> Database:
    global db
    db = Database(settings)
    return db
