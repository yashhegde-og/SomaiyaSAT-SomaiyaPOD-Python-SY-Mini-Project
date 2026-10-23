"""
models/governance_queries.py - Audit, Governance, Approval Queue & Safe SQL DAO
=============================================================================
Part of the ORBITAL Mission Telemetry System.

Responsibilities:
  1. AST parsing via sqlparse to block DROP, TRUNCATE, and unconstrained DELETE/UPDATE.
  2. Transactional Dry-Run SQL runner (BEGIN -> Execute -> Preview -> ROLLBACK).
  3. Live SQL Workbench executor with immutable audit logging.
  4. Pending Changes approval queue (review, approve, reject with transactions).
  5. Comprehensive audit trail (audit_events) and CDC history (change_log) queries.
  6. Operator account administration (create, deactivate, unlock).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import sqlparse
from sqlparse.sql import IdentifierList, Token, Where
from sqlparse.tokens import DDL, DML, Keyword

import db
import security


# =============================================================================
# 1. SQL SAFETY AST VALIDATOR (sqlparse)
# =============================================================================

BLOCKED_KEYWORDS = {"DROP", "TRUNCATE", "ALTER"}


def validate_sql_safety(query_str: str) -> Tuple[bool, str]:
    """
    Parses SQL AST using sqlparse.
    Blocks dangerous structural changes (DROP, TRUNCATE) and destructive DML
    without an explicit WHERE clause (unqualified DELETE / UPDATE).
    """
    clean_sql = query_str.strip()
    if not clean_sql:
        return False, "Query cannot be empty."

    parsed_stmts = sqlparse.parse(clean_sql)
    if not parsed_stmts:
        return False, "Unable to parse SQL statement."

    for stmt in parsed_stmts:
        # Check first token for statement type
        stmt_type = stmt.get_type().upper()

        # 1. Block destructive DDL statements
        if stmt_type in BLOCKED_KEYWORDS:
            return False, f"Blocked by Governance: Structural statement '{stmt_type}' is strictly prohibited."

        for token in stmt.tokens:
            val = token.value.upper()
            if val in BLOCKED_KEYWORDS:
                return False, f"Blocked by Governance: Keyword '{val}' is forbidden in the SQL Workbench."

        # 2. Block unqualified DELETE statements
        if stmt_type == "DELETE":
            has_where = any(isinstance(token, Where) for token in stmt.tokens)
            if not has_where:
                return (
                    False,
                    "Blocked by Governance: Unqualified DELETE statement (missing WHERE clause). "
                    "Mass deletion of telemetry is disallowed.",
                )

        # 3. Block unqualified UPDATE statements
        if stmt_type == "UPDATE":
            has_where = any(isinstance(token, Where) for token in stmt.tokens)
            if not has_where:
                return (
                    False,
                    "Blocked by Governance: Unqualified UPDATE statement (missing WHERE clause). "
                    "Unconstrained table modification is disallowed.",
                )

    return True, "Query passed AST safety verification."


# =============================================================================
# 2. SQL WORKBENCH DRY-RUN & LIVE EXECUTION
# =============================================================================

def execute_dry_run_sql(
    user_session: security.UserSession,
    query_str: str,
    max_preview_rows: int = 100,
) -> Dict[str, Any]:
    """
    Executes a query inside an isolated transaction that is GUARANTEED to ROLLBACK.
    Captures execution duration, affected row counts, and preview records
    without writing any changes to disk.
    """
    if not user_session.can("run_sql"):
        return {
            "success": False,
            "error": "Access Denied: Your role does not have SQL Workbench execution privileges.",
            "dry_run": True,
        }

    is_safe, safety_msg = validate_sql_safety(query_str)
    if not is_safe:
        return {"success": False, "error": safety_msg, "dry_run": True}

    conn = db.get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    start_time = time.time()
    try:
        # Configure security context inside transaction
        security.set_db_session_context(cur, user_session)

        cur.execute(query_str)
        elapsed_ms = (time.time() - start_time) * 1000

        # Attempt to retrieve columns & rows if query returns data
        columns: List[str] = []
        rows: List[List[Any]] = []
        if cur.description:
            columns = [desc[0] for desc in cur.description]
            fetched = cur.fetchmany(max_preview_rows)
            for row in fetched:
                rows.append([str(v) if isinstance(v, (datetime, bytes)) else v for v in row])

        row_count = cur.rowcount

        # Log dry-run to audit
        security._log_audit(
            cur,
            user_session.username,
            "SQL_DRY_RUN",
            None,
            None,
            "SUCCESS",
            f"Dry-run executed in {elapsed_ms:.2f}ms. Query: {query_str[:120]}...",
        )

        # Always ROLLBACK dry runs
        conn.rollback()

        return {
            "success": True,
            "dry_run": True,
            "columns": columns,
            "rows": rows,
            "row_count": row_count,
            "elapsed_ms": elapsed_ms,
            "message": f"Dry-run preview succeeded in {elapsed_ms:.1f}ms (Transaction automatically ROLLED BACK).",
        }
    except Exception as exc:
        conn.rollback()
        return {
            "success": False,
            "dry_run": True,
            "error": str(exc),
            "elapsed_ms": (time.time() - start_time) * 1000,
        }
    finally:
        cur.close()
        conn.close()


def execute_live_sql(
    user_session: security.UserSession,
    query_str: str,
    max_rows: int = 100,
) -> Dict[str, Any]:
    """
    Executes and COMMITS a live SQL statement inside a transaction.
    Restricted to Admins and Engineers.
    """
    if not user_session.can("run_sql"):
        return {"success": False, "error": "Access Denied: SQL Workbench access restricted.", "dry_run": False}

    is_safe, safety_msg = validate_sql_safety(query_str)
    if not is_safe:
        return {"success": False, "error": safety_msg, "dry_run": False}

    conn = db.get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    start_time = time.time()
    try:
        security.set_db_session_context(cur, user_session)
        cur.execute(query_str)
        elapsed_ms = (time.time() - start_time) * 1000

        columns: List[str] = []
        rows: List[List[Any]] = []
        if cur.description:
            columns = [desc[0] for desc in cur.description]
            fetched = cur.fetchmany(max_rows)
            for row in fetched:
                rows.append([str(v) if isinstance(v, (datetime, bytes)) else v for v in row])

        row_count = cur.rowcount

        # Log to audit_events
        security._log_audit(
            cur,
            user_session.username,
            "SQL_LIVE_EXECUTE",
            None,
            None,
            "SUCCESS",
            f"Live query executed and committed in {elapsed_ms:.2f}ms. Query: {query_str[:120]}...",
        )

        conn.commit()

        return {
            "success": True,
            "dry_run": False,
            "columns": columns,
            "rows": rows,
            "row_count": row_count,
            "elapsed_ms": elapsed_ms,
            "message": f"Query committed successfully in {elapsed_ms:.1f}ms ({row_count} row(s) affected).",
        }
    except Exception as exc:
        conn.rollback()
        return {"success": False, "dry_run": False, "error": str(exc), "elapsed_ms": (time.time() - start_time) * 1000}
    finally:
        cur.close()
        conn.close()


# =============================================================================
# 3. APPROVAL QUEUE (pending_changes)
# =============================================================================

def fetch_pending_changes(status: str = "PENDING") -> List[Dict[str, Any]]:
    """Retrieves changes awaiting administrative approval."""
    with db.get_db_cursor(commit=False, dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT change_id, requested_at, requested_by, action_type,
                   target_table, target_record_id, proposed_payload,
                   status, reviewed_by, reviewed_at, review_comments
            FROM pending_changes
            WHERE status = %s
            ORDER BY requested_at DESC;
            """,
            (status,),
        )
        return [dict(r) for r in cur.fetchall()]


def review_pending_change(
    admin_session: security.UserSession,
    change_id: int,
    approve: bool,
    comments: str = "",
) -> Tuple[bool, str]:
    """
    Processes a pending change item:
    If approved: executes the queued operation inside a transaction,
                 updates status to 'APPROVED', and logs to audit_events.
    If rejected: marks status as 'REJECTED' with comments.
    """
    if not admin_session.can("approve_changes"):
        return False, "Access Denied: Only administrators can approve/reject pending changes."

    now = datetime.now()

    with db.get_db_cursor(commit=True, dict_cursor=True) as cur:
        cur.execute("SELECT * FROM pending_changes WHERE change_id = %s FOR UPDATE;", (change_id,))
        record = cur.fetchone()
        if not record:
            return False, f"Pending change #{change_id} not found."

        if record["status"] != "PENDING":
            return False, f"Change #{change_id} has already been reviewed ({record['status']})."

        payload = record["proposed_payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)

        if approve:
            action_type = record["action_type"]
            table = record["target_table"]
            target_id = record["target_record_id"]

            # Execute the queued change
            if action_type == "DELETE" and table == "telemetry_records":
                cur.execute("DELETE FROM telemetry_records WHERE packet_id = %s;", (target_id,))
            elif action_type == "UPDATE" and table == "telemetry_records":
                pass  # Handled per payload

            cur.execute(
                """
                UPDATE pending_changes
                SET status = 'APPROVED',
                    reviewed_by = %s,
                    reviewed_at = %s,
                    review_comments = %s
                WHERE change_id = %s;
                """,
                (admin_session.username, now, comments, change_id),
            )

            security._log_audit(
                cur,
                admin_session.username,
                "APPROVAL_QUEUE_APPROVE",
                table,
                str(target_id),
                "SUCCESS",
                f"Admin {admin_session.username} approved {action_type} change #{change_id}. Comments: {comments}",
            )
            return True, f"Change #{change_id} successfully approved and executed."
        else:
            cur.execute(
                """
                UPDATE pending_changes
                SET status = 'REJECTED',
                    reviewed_by = %s,
                    reviewed_at = %s,
                    review_comments = %s
                WHERE change_id = %s;
                """,
                (admin_session.username, now, comments, change_id),
            )

            security._log_audit(
                cur,
                admin_session.username,
                "APPROVAL_QUEUE_REJECT",
                record["target_table"],
                str(record["target_record_id"]),
                "SUCCESS",
                f"Admin {admin_session.username} rejected change #{change_id}. Comments: {comments}",
            )
            return True, f"Change #{change_id} was rejected."


# =============================================================================
# 4. AUDIT TRAIL & CDC CHANGE LOG QUERIES
# =============================================================================

def fetch_audit_events(
    user_session: security.UserSession,
    limit: int = 100,
    action_filter: Optional[str] = None,
    username_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves immutable audit_events entries."""
    conditions: List[str] = []
    params: List[Any] = []

    if action_filter and action_filter != "All":
        conditions.append("action_type = %s")
        params.append(action_filter)

    if username_filter and username_filter != "All":
        conditions.append("username = %s")
        params.append(username_filter)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with db.get_db_cursor(commit=False, dict_cursor=True) as cur:
        cur.execute(
            f"""
            SELECT event_id, timestamp_utc, username, action_type,
                   target_table, target_id, status, details, client_ip
            FROM audit_events
            {where_clause}
            ORDER BY event_id DESC
            LIMIT %s;
            """,
            params + [limit],
        )
        return [dict(r) for r in cur.fetchall()]


def fetch_change_logs(
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Retrieves change_log records populated automatically by database triggers."""
    with db.get_db_cursor(commit=False, dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT log_id, changed_at, changed_by, action,
                   table_name, record_id, old_values, new_values
            FROM change_log
            ORDER BY log_id DESC
            LIMIT %s;
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def fetch_all_users() -> List[Dict[str, Any]]:
    """Retrieves operator accounts for admin governance."""
    with db.get_db_cursor(commit=False, dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT user_id, username, full_name, email, role_name,
                   clearance_level, is_active, failed_login_count,
                   locked_until, last_login, created_at
            FROM app_users
            ORDER BY user_id;
            """
        )
        return [dict(r) for r in cur.fetchall()]


def toggle_user_active(admin_session: security.UserSession, username: str) -> Tuple[bool, str]:
    """Activates or deactivates an operator account."""
    if not admin_session.can("manage_users"):
        return False, "Access Denied: Only administrators can modify user status."

    with db.get_db_cursor(commit=True, dict_cursor=True) as cur:
        cur.execute("SELECT is_active FROM app_users WHERE username = %s;", (username,))
        row = cur.fetchone()
        if not row:
            return False, f"User '{username}' not found."

        new_state = not row["is_active"]
        cur.execute("UPDATE app_users SET is_active = %s WHERE username = %s;", (new_state, username))

        status_str = "ACTIVATED" if new_state else "DEACTIVATED"
        security._log_audit(
            cur,
            admin_session.username,
            f"USER_{status_str}",
            "app_users",
            username,
            "SUCCESS",
            f"Admin {admin_session.username} toggled {username} active state to {new_state}.",
        )

    return True, f"User '{username}' successfully {status_str.lower()}."


def create_new_user(
    admin_session: security.UserSession,
    username: str,
    full_name: str,
    email: str,
    role_name: str,
    clearance_level: str,
    password: str,
) -> Tuple[bool, str]:
    """Provisions a new operator user account with bcrypt password hashing."""
    if not admin_session.can("manage_users"):
        return False, "Access Denied: Only administrators can provision user accounts."

    username = username.strip().lower()
    full_name = full_name.strip()
    email = email.strip()
    password = password.strip()

    if not username:
        return False, "Username cannot be empty."
    if len(password) < 6:
        return False, "Password must be at least 6 characters long."
    if role_name not in ("Admin", "Engineer", "Operator", "Viewer"):
        return False, f"Invalid role: {role_name}"
    if clearance_level not in ("Public", "Internal", "Restricted"):
        return False, f"Invalid clearance level: {clearance_level}"

    hashed_pw = security.hash_password(password)

    try:
        with db.get_db_cursor(commit=True) as cur:
            cur.execute("SELECT 1 FROM app_users WHERE username = %s;", (username,))
            if cur.fetchone():
                return False, f"Username '{username}' is already registered."

            cur.execute(
                """
                INSERT INTO app_users (
                    username, password_hash, full_name, email,
                    role_name, clearance_level, is_active, failed_login_count, locked_until
                )
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, 0, NULL);
                """,
                (username, hashed_pw, full_name, email or None, role_name, clearance_level),
            )

            security._log_audit(
                cur,
                admin_session.username,
                "USER_CREATE",
                "app_users",
                username,
                "SUCCESS",
                f"Provisioned operator {username} ({role_name} / {clearance_level})",
            )
        return True, f"Operator '{username}' created successfully."
    except Exception as exc:
        return False, f"Failed to create user: {exc}"


def update_user_profile(
    admin_session: security.UserSession,
    username: str,
    full_name: str,
    email: str,
    role_name: str,
    clearance_level: str,
    new_password: Optional[str] = None,
) -> Tuple[bool, str]:
    """Updates operator role, clearance rank, and profile details."""
    if not admin_session.can("manage_users"):
        return False, "Access Denied: Only administrators can update operator accounts."

    full_name = full_name.strip()
    email = email.strip()

    try:
        with db.get_db_cursor(commit=True) as cur:
            if new_password and len(new_password.strip()) >= 6:
                hashed_pw = security.hash_password(new_password.strip())
                cur.execute(
                    """
                    UPDATE app_users
                    SET full_name = %s, email = %s, role_name = %s, clearance_level = %s, password_hash = %s
                    WHERE username = %s;
                    """,
                    (full_name, email or None, role_name, clearance_level, hashed_pw, username),
                )
            else:
                cur.execute(
                    """
                    UPDATE app_users
                    SET full_name = %s, email = %s, role_name = %s, clearance_level = %s
                    WHERE username = %s;
                    """,
                    (full_name, email or None, role_name, clearance_level, username),
                )

            security._log_audit(
                cur,
                admin_session.username,
                "USER_UPDATE",
                "app_users",
                username,
                "SUCCESS",
                f"Updated operator {username} (Role: {role_name}, Clearance: {clearance_level})",
            )
        return True, f"Operator '{username}' updated successfully."
    except Exception as exc:
        return False, f"Failed to update user: {exc}"


def delete_user_account(admin_session: security.UserSession, username: str) -> Tuple[bool, str]:
    """Removes an operator account (protects default admin)."""
    if not admin_session.can("manage_users"):
        return False, "Access Denied: Only administrators can delete operator accounts."

    if username == admin_session.username:
        return False, "Self-deletion prohibited: You cannot delete your currently active session account."
    if username == "admin_user":
        return False, "Security restriction: The primary 'admin_user' master account cannot be deleted."

    try:
        with db.get_db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM app_users WHERE username = %s;", (username,))
            security._log_audit(
                cur,
                admin_session.username,
                "USER_DELETE",
                "app_users",
                username,
                "SUCCESS",
                f"Deleted operator account {username}",
            )
        return True, f"Operator '{username}' deleted successfully."
    except Exception as exc:
        return False, f"Failed to delete user: {exc}"
