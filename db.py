"""
db.py - PostgreSQL Database Connection & Execution Manager
==========================================================
Part of the ORBITAL Mission Telemetry System.
Handles connection pooling, context management, schema initialization,
and parameterized SQL query execution.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator, List, Optional, Tuple

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as PgConnection
from psycopg2.extensions import cursor as PgCursor
from psycopg2.extras import DictCursor

# Load environment variables from .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Register NumPy adapters so psycopg2 seamlessly adapts NumPy scalars from pandas
try:
    import numpy as np
    from psycopg2.extensions import AsIs, register_adapter
    register_adapter(np.int64, lambda v: AsIs(int(v)))
    register_adapter(np.int32, lambda v: AsIs(int(v)))
    register_adapter(np.float64, lambda v: AsIs(float(v)))
    register_adapter(np.float32, lambda v: AsIs(float(v)))
    register_adapter(np.bool_, lambda v: AsIs(bool(v)))
except ImportError:
    pass



def get_db_config(override_dbname: Optional[str] = None) -> dict[str, Any]:
    """
    Retrieve database configuration parameters from environment variables
    with standard PostgreSQL default fallbacks.
    """
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": override_dbname or os.getenv("DB_NAME", "orbital_py_project"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", "sqlopgng"),
        "connect_timeout": int(os.getenv("DB_TIMEOUT", "5")),
    }


def get_connection(override_dbname: Optional[str] = None) -> PgConnection:
    """
    Establish and return a new PostgreSQL connection using configured credentials.
    Raises psycopg2.OperationalError if the connection fails.
    """
    cfg = get_db_config(override_dbname=override_dbname)
    return psycopg2.connect(**cfg)


@contextmanager
def get_db_cursor(
    commit: bool = False,
    dict_cursor: bool = False,
    override_dbname: Optional[str] = None,
) -> Generator[PgCursor, None, None]:
    """
    Context manager for safe database cursor execution.
    Automatically commits on normal completion if `commit=True`,
    rolls back on unhandled exceptions, and safely closes the cursor & connection.
    """
    conn = get_connection(override_dbname=override_dbname)
    cursor_factory = DictCursor if dict_cursor else None
    cur = conn.cursor(cursor_factory=cursor_factory)
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def test_connection(override_dbname: Optional[str] = None) -> Tuple[bool, str]:
    """
    Test connectivity to the PostgreSQL instance.
    Returns (True, "Connected: <version>") on success,
    or (False, "<error_message>") on failure.
    """
    try:
        with get_db_cursor(commit=False, override_dbname=override_dbname) as cur:
            cur.execute("SELECT version();")
            ver = cur.fetchone()[0]
            return True, f"Connected: {ver}"
    except Exception as exc:
        return False, str(exc)


def create_database_if_not_exists(target_db: Optional[str] = None) -> bool:
    """
    Connect to the maintenance 'postgres' database and verify if the target
    database exists. If not, create it.
    """
    cfg = get_db_config()
    target = target_db or cfg["dbname"]

    # Connect to maintenance database with autocommit to execute CREATE DATABASE
    conn = psycopg2.connect(
        host=cfg["host"],
        port=cfg["port"],
        dbname="postgres",
        user=cfg["user"],
        password=cfg["password"],
        connect_timeout=cfg["connect_timeout"],
    )
    conn.autocommit = True
    cur = conn.cursor()

    try:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (target,))
        exists = cur.fetchone() is not None

        if not exists:
            # Use psycopg2.sql identifier to safely format database name
            cur.execute(
                sql.SQL("CREATE DATABASE {} ENCODING 'UTF8';").format(
                    sql.Identifier(target)
                )
            )
            created = True
        else:
            created = False
        return created
    finally:
        cur.close()
        conn.close()


def ensure_database_and_schema_ready() -> None:
    """
    Auto-provisions the database, tables, triggers, and seed records
    directly in pure Python without requiring external .sql scripts.
    """
    import bootstrap
    bootstrap.ensure_database_and_schema_ready()


def execute_schema_file(schema_path: str = "schema.sql") -> None:
    """
    Read and execute the schema DDL script to create all required tables,
    indexes, and constraints inside a single transaction.
    """
    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"Schema file not found at: {schema_path}")

    with open(schema_path, "r", encoding="utf-8") as f:
        ddl_script = f.read()

    with get_db_cursor(commit=True) as cur:
        cur.execute(ddl_script)


def execute_parameterized_query(
    query: str,
    params: Optional[Tuple[Any, ...] | List[Any] | dict[str, Any]] = None,
    fetch: Optional[str] = None,
    commit: bool = False,
    dict_cursor: bool = False,
) -> Any:
    """
    Execute a strictly parameterized SQL statement to eliminate SQL injection.
    fetch options:
      - 'one': returns cur.fetchone()
      - 'all': returns cur.fetchall()
      - None: returns cur.rowcount
    """
    with get_db_cursor(commit=commit, dict_cursor=dict_cursor) as cur:
        cur.execute(query, params)
        if fetch == "one":
            return cur.fetchone()
        elif fetch == "all":
            return cur.fetchall()
        return cur.rowcount
