"""
security.py - Authentication, RBAC, DAC & Bell-LaPadula MAC Security Engine
===========================================================================
Part of the ORBITAL Mission Telemetry System.

Responsibilities:
  1. Password hashing & salt generation via bcrypt.
  2. Authentication with 5-attempt brute-force lockout (15 minutes).
  3. RBAC (Role-Based Access Control) matrix and GUI permission checks.
  4. DAC (Discretionary Access Control) grant & revoke workflow with audit logs.
  5. MAC (Mandatory Access Control) Bell-LaPadula model enforcement.
  6. Database security context configuration (SET app.clearance / SET ROLE).
  7. Seeding standardized demo user accounts for presentation & viva.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import bcrypt

import db

# Security configuration constants
MAX_FAILED_ATTEMPTS: int = 5
LOCKOUT_DURATION_MINUTES: int = 15

# Bell-LaPadula clearance hierarchy
CLEARANCE_RANKS: Dict[str, int] = {
    "Public": 1,
    "Unclassified": 1,
    "Internal": 2,
    "Restricted": 3,
}


@dataclass
class UserSession:
    """
    Encapsulates authenticated mission operator session credentials,
    RBAC permissions, and Bell-LaPadula clearance classification.
    """
    user_id: int
    username: str
    full_name: str
    email: str
    role_name: str
    clearance_level: str
    permissions: Dict[str, bool]
    login_time: datetime

    def can(self, action: str) -> bool:
        """
        Check if user's role has permission for a specific GUI action.
        Actions: 'read', 'insert', 'update', 'delete', 'export', 'run_sql',
                 'manage_users', 'approve_changes'
        """
        key = f"can_{action}" if not action.startswith("can_") else action
        return self.permissions.get(key, False)

    def is_admin(self) -> bool:
        return self.role_name == "Admin"


# -----------------------------------------------------------------------------
# 1. BCRYPT PASSWORD ENCRYPTION
# -----------------------------------------------------------------------------

def hash_password(plain_password: str) -> str:
    """
    Hashes a plain-text password using bcrypt with automatic salt generation (work factor 12).
    """
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Securely checks if a plain password matches the bcrypt hash.
    Constant-time comparison prevents timing attacks.
    """
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


# -----------------------------------------------------------------------------
# 2. AUTHENTICATION & BRUTE-FORCE LOCKOUT (5 Attempts in 15 Minutes)
# -----------------------------------------------------------------------------

def authenticate_user(
    username: str,
    password: str,
    client_ip: str = "127.0.0.1",
) -> Tuple[bool, Optional[UserSession], str]:
    """
    Authenticates user against PostgreSQL 'app_users' table.
    Enforces a strict 5-attempt brute-force lockout lasting 15 minutes.
    Logs all successful, failed, and denied login attempts to 'audit_events'.
    """
    username = username.strip()
    if not username or not password:
        return False, None, "Username and password cannot be empty."

    with db.get_db_cursor(commit=True, dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT user_id, username, password_hash, full_name, email,
                   role_name, clearance_level, is_active, failed_login_count,
                   locked_until
            FROM app_users
            WHERE username = %s;
            """,
            (username,),
        )
        user_row = cur.fetchone()

        now = datetime.now()

        # Check: User existence
        if not user_row:
            _log_audit(cur, username, "LOGIN_FAILED", "app_users", None, "FAILED", "User does not exist.", client_ip)
            return False, None, "Invalid username or password."

        # Check: Account active state
        if not user_row["is_active"]:
            _log_audit(cur, username, "LOGIN_DENIED", "app_users", str(user_row["user_id"]), "DENIED", "Account is deactivated.", client_ip)
            return False, None, "Account is disabled. Contact your mission administrator."

        # Check: Lockout state
        locked_until = user_row["locked_until"]
        if locked_until and locked_until > now:
            remaining_seconds = int((locked_until - now).total_seconds())
            rem_min = remaining_seconds // 60
            rem_sec = remaining_seconds % 60
            msg = f"Account locked due to 5 failed attempts. Try again in {rem_min}m {rem_sec}s."
            _log_audit(cur, username, "LOGIN_LOCKED_ATTEMPT", "app_users", str(user_row["user_id"]), "DENIED", msg, client_ip)
            return False, None, msg

        # Verify bcrypt hash
        if verify_password(password, user_row["password_hash"]):
            # Reset failure count and unlock
            cur.execute(
                """
                UPDATE app_users
                SET failed_login_count = 0,
                    locked_until = NULL,
                    last_login = %s
                WHERE user_id = %s;
                """,
                (now, user_row["user_id"]),
            )

            # Retrieve role permissions
            cur.execute(
                """
                SELECT can_read, can_insert, can_update, can_delete,
                       can_export, can_run_sql, can_manage_users, can_approve_changes
                FROM rbac_roles
                WHERE role_name = %s;
                """,
                (user_row["role_name"],),
            )
            perm_row = cur.fetchone()
            permissions = dict(perm_row) if perm_row else {}

            session = UserSession(
                user_id=user_row["user_id"],
                username=user_row["username"],
                full_name=user_row["full_name"],
                email=user_row["email"] or "",
                role_name=user_row["role_name"],
                clearance_level=user_row["clearance_level"],
                permissions=permissions,
                login_time=now,
            )

            _log_audit(
                cur,
                username,
                "LOGIN_SUCCESS",
                "app_users",
                str(user_row["user_id"]),
                "SUCCESS",
                f"Authenticated as {user_row['role_name']} [{user_row['clearance_level']} clearance].",
                client_ip,
            )
            return True, session, "Authentication successful."

        else:
            # Increment failed attempts
            current_failures = (user_row["failed_login_count"] or 0) + 1
            if current_failures >= MAX_FAILED_ATTEMPTS:
                new_locked_until = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                cur.execute(
                    """
                    UPDATE app_users
                    SET failed_login_count = %s,
                        locked_until = %s
                    WHERE user_id = %s;
                    """,
                    (current_failures, new_locked_until, user_row["user_id"]),
                )
                msg = f"Account locked for {LOCKOUT_DURATION_MINUTES} minutes due to 5 consecutive failed login attempts."
                _log_audit(cur, username, "ACCOUNT_LOCKED", "app_users", str(user_row["user_id"]), "DENIED", msg, client_ip)
                return False, None, msg
            else:
                cur.execute(
                    """
                    UPDATE app_users
                    SET failed_login_count = %s
                    WHERE user_id = %s;
                    """,
                    (current_failures, user_row["user_id"]),
                )
                remaining = MAX_FAILED_ATTEMPTS - current_failures
                msg = f"Invalid password. {remaining} attempt(s) remaining before account lockout."
                _log_audit(cur, username, "LOGIN_FAILED", "app_users", str(user_row["user_id"]), "FAILED", msg, client_ip)
                return False, None, msg


def unlock_user_account(admin_user: UserSession, target_username: str) -> Tuple[bool, str]:
    """
    Allows an Admin to manually clear lockout status for a user.
    """
    if not admin_user.is_admin():
        return False, "Access Denied: Only administrators can unlock accounts."

    with db.get_db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE app_users
            SET failed_login_count = 0,
                locked_until = NULL
            WHERE username = %s;
            """,
            (target_username,),
        )
        if cur.rowcount == 0:
            return False, f"User '{target_username}' not found."

        _log_audit(
            cur,
            admin_user.username,
            "ADMIN_UNLOCK_USER",
            "app_users",
            target_username,
            "SUCCESS",
            f"Admin {admin_user.username} unlocked account {target_username}.",
        )
    return True, f"Account '{target_username}' has been successfully unlocked."


# -----------------------------------------------------------------------------
# 3. BELL-LAPADULA MANDATORY ACCESS CONTROL (MAC)
# -----------------------------------------------------------------------------

def can_read_mac(subject_clearance: str, object_classification: str) -> bool:
    """
    Bell-LaPadula Simple Security Property: 'No Read Up'
    A subject at clearance S can read object O iff Clearance(S) >= Classification(O).
    """
    s_rank = CLEARANCE_RANKS.get(subject_clearance, 1)
    o_rank = CLEARANCE_RANKS.get(object_classification, 1)
    return s_rank >= o_rank


def can_write_mac(subject_clearance: str, object_classification: str) -> bool:
    """
    Bell-LaPadula *-Property (Star Property): 'No Write Down'
    A subject at clearance S can write/insert object O iff Clearance(S) <= Classification(O).
    Prevents higher-clearance users from leaking sensitive data into public classifications.
    """
    s_rank = CLEARANCE_RANKS.get(subject_clearance, 1)
    o_rank = CLEARANCE_RANKS.get(object_classification, 1)
    return s_rank <= o_rank


def set_db_session_context(cur: Any, user: UserSession) -> None:
    """
    Configures PostgreSQL connection parameters to enforce Row-Level Security:
      - SET ROLE orbital_reader / orbital_writer / orbital_admin
      - SET app.username = username
      - SET app.role = role_name
      - SET app.clearance = clearance_level
    """
    # 1. Switch to least-privileged PostgreSQL system role
    if user.role_name == "Admin":
        pg_role = "orbital_admin"
    elif user.can("insert") or user.can("update") or user.can("delete"):
        pg_role = "orbital_writer"
    else:
        pg_role = "orbital_reader"

    # Use parameter substitution for application session variables
    cur.execute(f"SET ROLE {pg_role};")
    cur.execute(
        """
        SELECT set_config('app.username', %s, false),
               set_config('app.role', %s, false),
               set_config('app.clearance', %s, false);
        """,
        (user.username, user.role_name, user.clearance_level),
    )


# -----------------------------------------------------------------------------
# 4. DISCRETIONARY ACCESS CONTROL (DAC)
# -----------------------------------------------------------------------------

def grant_dac_permission(
    granter: UserSession,
    grantee_username: str,
    target_type: str,
    permission: str,
    packet_id: Optional[int] = None,
    duration_hours: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    Record owners or Admins can grant discretionary access to other users.
    target_type: 'row' (requires packet_id) or 'table'
    permission: 'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'ALL'
    """
    if target_type == "row" and packet_id is None:
        return False, "Target packet_id required for row-level DAC grant."

    target_type = target_type.lower()
    permission = permission.upper()

    with db.get_db_cursor(commit=True, dict_cursor=True) as cur:
        # Check grantee exists
        cur.execute("SELECT user_id FROM app_users WHERE username = %s;", (grantee_username,))
        if not cur.fetchone():
            return False, f"Target user '{grantee_username}' does not exist."

        # If row-level, verify granter owns the record or is Admin
        if target_type == "row" and not granter.is_admin():
            cur.execute("SELECT owner_username FROM telemetry_records WHERE packet_id = %s;", (packet_id,))
            row = cur.fetchone()
            if not row or row["owner_username"] != granter.username:
                return False, "Access Denied: Only the record owner or an Admin can grant access to this packet."

        expires_at = datetime.now() + timedelta(hours=duration_hours) if duration_hours else None

        cur.execute(
            """
            INSERT INTO dac_grants (
                granter_username, grantee_username, target_type,
                target_packet_id, permission, expires_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING grant_id;
            """,
            (
                granter.username,
                grantee_username,
                target_type,
                packet_id,
                permission,
                expires_at,
            ),
        )
        grant_id = cur.fetchone()["grant_id"]

        _log_audit(
            cur,
            granter.username,
            "DAC_GRANT",
            "dac_grants",
            str(grant_id),
            "SUCCESS",
            f"Granted {permission} on {target_type} (packet_id: {packet_id}) to {grantee_username}.",
        )

    return True, f"DAC grant #{grant_id} successfully issued to '{grantee_username}'."


def revoke_dac_permission(revoker: UserSession, grant_id: int) -> Tuple[bool, str]:
    """
    Revokes an active DAC grant. Can be performed by granter or Admin.
    """
    with db.get_db_cursor(commit=True, dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT grant_id, granter_username, grantee_username, target_packet_id, permission
            FROM dac_grants
            WHERE grant_id = %s;
            """,
            (grant_id,),
        )
        grant = cur.fetchone()
        if not grant:
            return False, f"DAC grant #{grant_id} not found."

        if not revoker.is_admin() and grant["granter_username"] != revoker.username:
            return False, "Access Denied: Only the original granter or an Admin can revoke this grant."

        cur.execute("DELETE FROM dac_grants WHERE grant_id = %s;", (grant_id,))

        _log_audit(
            cur,
            revoker.username,
            "DAC_REVOKE",
            "dac_grants",
            str(grant_id),
            "SUCCESS",
            f"Revoked {grant['permission']} on packet {grant['target_packet_id']} from {grant['grantee_username']}.",
        )

    return True, f"DAC grant #{grant_id} revoked successfully."


def list_active_dac_grants() -> List[Dict[str, Any]]:
    """
    Returns list of all active DAC grants with granter and grantee details.
    """
    with db.get_db_cursor(commit=False, dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT grant_id, granter_username, grantee_username, target_type,
                   target_packet_id, permission, granted_at, expires_at
            FROM dac_grants
            WHERE expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP
            ORDER BY granted_at DESC;
            """
        )
        return [dict(r) for r in cur.fetchall()]


# -----------------------------------------------------------------------------
# 5. AUDIT EVENT LOGGING HELPER
# -----------------------------------------------------------------------------

def _log_audit(
    cur: Any,
    username: str,
    action_type: str,
    target_table: Optional[str],
    target_id: Optional[str],
    status: str,
    details: str,
    client_ip: str = "127.0.0.1",
) -> None:
    """
    Internal parameterized audit logger writing to PostgreSQL 'audit_events'.
    """
    cur.execute(
        """
        INSERT INTO audit_events (
            username, action_type, target_table, target_id,
            status, details, client_ip
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s);
        """,
        (username, action_type, target_table, target_id, status, details, client_ip),
    )


# -----------------------------------------------------------------------------
# 6. SEED DEMO USERS (One per Role & Clearance Level)
# -----------------------------------------------------------------------------

DEMO_USERS_SPEC = [
    {
        "username": "admin_user",
        "password": "Admin@2026!",
        "full_name": "Dr. Ramesh Somaiya (Flight Director)",
        "email": "flight.director@somaiyasat.edu",
        "role_name": "Admin",
        "clearance_level": "Restricted",
    },
    {
        "username": "flight_engineer",
        "password": "Engineer@2026!",
        "full_name": "Aarav Sharma (Payload Lead)",
        "email": "aarav.sharma@somaiyasat.edu",
        "role_name": "Engineer",
        "clearance_level": "Internal",
    },
    {
        "username": "station_operator",
        "password": "Operator@2026!",
        "full_name": "Pooja Nair (Station Operator)",
        "email": "pooja.nair@somaiyasat.edu",
        "role_name": "Operator",
        "clearance_level": "Internal",
    },
    {
        "username": "public_viewer",
        "password": "Viewer@2026!",
        "full_name": "Somaiya AMSAT Guest (Public)",
        "email": "amsat.guest@somaiya.edu",
        "role_name": "Viewer",
        "clearance_level": "Public",
    },
]


def seed_demo_users() -> None:
    """
    Encrypts passwords with bcrypt and inserts/updates demo user accounts in PostgreSQL.
    """
    print("[*] Seeding demo user accounts with bcrypt password hashes...")
    with db.get_db_cursor(commit=True) as cur:
        for u in DEMO_USERS_SPEC:
            hashed = hash_password(u["password"])
            cur.execute(
                """
                INSERT INTO app_users (
                    username, password_hash, full_name, email,
                    role_name, clearance_level, is_active, failed_login_count, locked_until
                )
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, 0, NULL)
                ON CONFLICT (username) DO UPDATE SET
                    password_hash = EXCLUDED.password_hash,
                    full_name = EXCLUDED.full_name,
                    email = EXCLUDED.email,
                    role_name = EXCLUDED.role_name,
                    clearance_level = EXCLUDED.clearance_level,
                    is_active = TRUE,
                    failed_login_count = 0,
                    locked_until = NULL;
                """,
                (
                    u["username"],
                    hashed,
                    u["full_name"],
                    u["email"],
                    u["role_name"],
                    u["clearance_level"],
                ),
            )
            print(f"  [+] Demo user '{u['username']}' ({u['role_name']} | {u['clearance_level']}) seeded.")

    print("[+] All demo users successfully registered.")
