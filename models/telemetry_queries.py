"""
models/telemetry_queries.py - Parameterized Telemetry Data Access Object (DAO)
=============================================================================
Part of the ORBITAL Mission Telemetry System.

Responsibilities:
  1. Server-side pagination (LIMIT/OFFSET) with parameterized multi-filter search.
  2. Injection-safe column sorting via strict whitelist validation.
  3. Parameterized INSERT, UPDATE, and DELETE executions inside transactions.
  4. Automatic enforcement of Bell-LaPadula MAC and RBAC privileges.
  5. Detailed packet inspection retrieval (24 fields + DAC ownership).
  6. Filtered CSV export generation.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import db
import security

# Strict whitelist of valid sortable column names to prevent SQL injection
ALLOWED_SORT_COLUMNS = {
    "packet_id",
    "timestamp_utc",
    "ground_station",
    "satellite_id",
    "mission_phase",
    "orbit_number",
    "altitude_km",
    "orbital_velocity_kmps",
    "eclipse_status",
    "battery_voltage_v",
    "battery_soc_percent",
    "solar_current_ma",
    "onboard_temp_c",
    "comm_mode",
    "rssi_dbm",
    "snr_db",
    "data_rate_bps",
    "packet_size_bytes",
    "bit_error_rate",
    "crc_valid",
    "ai_routing_decision",
    "ai_confidence_score",
    "deployment_confirmed",
    "packet_priority",
    "classification",
    "owner_username",
}


def _build_filter_clause(
    filters: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[Any]]:
    """
    Constructs a strictly parameterized WHERE clause and parameter list
    from user filter selections.
    """
    conditions: List[str] = []
    params: List[Any] = []

    if not filters:
        return "", params

    # 1. Full-text / General search across multiple fields
    search = filters.get("search", "").strip()
    if search:
        search_pattern = f"%{search}%"
        conditions.append(
            """(
                packet_id::text ILIKE %s
                OR ground_station ILIKE %s
                OR satellite_id ILIKE %s
                OR comm_mode ILIKE %s
                OR ai_routing_decision ILIKE %s
                OR mission_phase ILIKE %s
            )"""
        )
        params.extend([search_pattern] * 6)

    # 2. Satellite filter
    sat = filters.get("satellite_id")
    if sat and sat != "All":
        conditions.append("satellite_id = %s")
        params.append(sat)

    # 3. Ground Station filter
    station = filters.get("ground_station")
    if station and station != "All":
        conditions.append("(ground_station = %s OR ground_station ILIKE %s)")
        params.extend([station, f"{station}%"])

    # 4. Comm Mode filter
    mode = filters.get("comm_mode")
    if mode and mode != "All":
        conditions.append("comm_mode = %s")
        params.append(mode)

    # 5. AI Routing Decision filter
    decision = filters.get("ai_routing_decision")
    if decision and decision != "All":
        conditions.append("ai_routing_decision = %s")
        params.append(decision)

    # 6. Packet Priority filter
    priority = filters.get("packet_priority")
    if priority and priority != "All":
        conditions.append("packet_priority = %s")
        params.append(priority)

    # 7. Classification filter
    classification = filters.get("classification")
    if classification and classification != "All":
        conditions.append("classification = %s")
        params.append(classification)

    # 8. Date Range filters
    start_date = filters.get("start_date")
    if start_date:
        conditions.append("timestamp_utc >= %s")
        params.append(start_date)

    end_date = filters.get("end_date")
    if end_date:
        conditions.append("timestamp_utc <= %s")
        params.append(end_date)

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where_sql, params


def fetch_telemetry_page(
    user_session: security.UserSession,
    page: int = 1,
    page_size: int = 50,
    sort_column: str = "timestamp_utc",
    sort_direction: str = "DESC",
    filters: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Retrieves a single server-side paginated window of telemetry records.
    Returns: (list_of_row_dicts, total_matching_records)
    """
    # Sanitize pagination parameters
    page = max(1, page)
    page_size = max(1, min(500, page_size))
    offset = (page - 1) * page_size

    # Validate sort parameters against whitelist
    if sort_column not in ALLOWED_SORT_COLUMNS:
        sort_column = "timestamp_utc"
    sort_dir = "ASC" if sort_direction.upper() == "ASC" else "DESC"

    where_clause, params = _build_filter_clause(filters)

    with db.get_db_cursor(commit=False, dict_cursor=True) as cur:
        # Enforce PostgreSQL Row-Level Security
        security.set_db_session_context(cur, user_session)

        # 1. Total matching row count under current session clearance and filters
        count_sql = f"SELECT COUNT(*) FROM telemetry_records {where_clause};"
        cur.execute(count_sql, params)
        total_records = cur.fetchone()[0]

        # 2. Paginated data query
        query_sql = f"""
            SELECT packet_id, timestamp_utc, ground_station, satellite_id,
                   mission_phase, orbit_number, altitude_km, orbital_velocity_kmps,
                   eclipse_status, battery_voltage_v, battery_soc_percent,
                   solar_current_ma, onboard_temp_c, comm_mode, rssi_dbm, snr_db,
                   data_rate_bps, packet_size_bytes, bit_error_rate, crc_valid,
                   ai_routing_decision, ai_confidence_score, deployment_confirmed,
                   packet_priority, classification, owner_username
            FROM telemetry_records
            {where_clause}
            ORDER BY {sort_column} {sort_dir}
            LIMIT %s OFFSET %s;
        """
        paginated_params = params + [page_size, offset]
        cur.execute(query_sql, paginated_params)
        rows = [dict(r) for r in cur.fetchall()]

    return rows, total_records


def fetch_packet_by_id(
    user_session: security.UserSession,
    packet_id: int,
) -> Optional[Dict[str, Any]]:
    """
    Fetches the full 24-column record for a single packet by its packet_id.
    Returns None if not found or blocked by Row-Level Security.
    """
    with db.get_db_cursor(commit=False, dict_cursor=True) as cur:
        security.set_db_session_context(cur, user_session)
        cur.execute(
            """
            SELECT * FROM telemetry_records
            WHERE packet_id = %s;
            """,
            (packet_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def insert_telemetry_packet(
    user_session: security.UserSession,
    data: Dict[str, Any],
) -> Tuple[bool, str, Optional[int]]:
    """
    Inserts a new telemetry record inside a transaction.
    Enforces RBAC ('can_insert') and Bell-LaPadula *-Property (No Write Down).
    """
    if not user_session.can("insert"):
        return False, "Access Denied: Your role does not have permission to insert telemetry packets.", None

    classification = data.get("classification", "Public")
    if not security.can_write_mac(user_session.clearance_level, classification):
        return (
            False,
            f"Bell-LaPadula *-Property Violation (No Write Down): "
            f"An operator with '{user_session.clearance_level}' clearance cannot insert into '{classification}'.",
            None,
        )

    with db.get_db_cursor(commit=True, dict_cursor=True) as cur:
        security.set_db_session_context(cur, user_session)

        # Generate next packet_id if not explicitly provided
        packet_id = data.get("packet_id")
        if not packet_id:
            cur.execute("SELECT COALESCE(MAX(packet_id), 0) + 1 FROM telemetry_records;")
            packet_id = cur.fetchone()[0]

        timestamp = data.get("timestamp_utc") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        insert_sql = """
            INSERT INTO telemetry_records (
                packet_id, timestamp_utc, ground_station, satellite_id, mission_phase,
                orbit_number, altitude_km, orbital_velocity_kmps, eclipse_status,
                battery_voltage_v, battery_soc_percent, solar_current_ma, onboard_temp_c,
                comm_mode, rssi_dbm, snr_db, data_rate_bps, packet_size_bytes,
                bit_error_rate, crc_valid, ai_routing_decision, ai_confidence_score,
                deployment_confirmed, packet_priority, classification, owner_username
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s
            );
        """
        params = (
            packet_id,
            timestamp,
            data["ground_station"],
            data["satellite_id"],
            data["mission_phase"],
            int(data["orbit_number"]),
            float(data["altitude_km"]),
            float(data["orbital_velocity_kmps"]),
            data["eclipse_status"],
            float(data["battery_voltage_v"]),
            float(data["battery_soc_percent"]),
            float(data["solar_current_ma"]),
            float(data["onboard_temp_c"]),
            data["comm_mode"],
            float(data["rssi_dbm"]),
            float(data["snr_db"]),
            int(data["data_rate_bps"]),
            int(data["packet_size_bytes"]),
            float(data["bit_error_rate"]),
            data["crc_valid"],
            data["ai_routing_decision"],
            float(data["ai_confidence_score"]),
            data["deployment_confirmed"],
            data["packet_priority"],
            classification,
            user_session.username,
        )

        cur.execute(insert_sql, params)

        # Log to audit_events
        security._log_audit(
            cur,
            user_session.username,
            "INSERT_PACKET",
            "telemetry_records",
            str(packet_id),
            "SUCCESS",
            f"Operator {user_session.username} created packet #{packet_id} [{classification}].",
        )

    return True, f"Packet #{packet_id} successfully created and committed.", packet_id


def update_telemetry_packet(
    user_session: security.UserSession,
    packet_id: int,
    data: Dict[str, Any],
) -> Tuple[bool, str]:
    """
    Updates an existing telemetry record inside a transaction.
    Enforces RBAC ('can_update'), Bell-LaPadula MAC, and DAC ownership checks.
    """
    if not user_session.can("update"):
        return False, "Access Denied: Your role does not have permission to update telemetry packets."

    with db.get_db_cursor(commit=True, dict_cursor=True) as cur:
        security.set_db_session_context(cur, user_session)

        # Check existing row
        cur.execute("SELECT * FROM telemetry_records WHERE packet_id = %s;", (packet_id,))
        existing = cur.fetchone()
        if not existing:
            return False, f"Packet #{packet_id} not found or not accessible under your security clearance."

        new_classification = data.get("classification", existing["classification"])
        if not security.can_write_mac(user_session.clearance_level, new_classification):
            return (
                False,
                f"Bell-LaPadula Violation: Cannot classify record as '{new_classification}' "
                f"from '{user_session.clearance_level}' clearance.",
            )

        update_sql = """
            UPDATE telemetry_records SET
                ground_station = %s,
                satellite_id = %s,
                mission_phase = %s,
                orbit_number = %s,
                altitude_km = %s,
                orbital_velocity_kmps = %s,
                eclipse_status = %s,
                battery_voltage_v = %s,
                battery_soc_percent = %s,
                solar_current_ma = %s,
                onboard_temp_c = %s,
                comm_mode = %s,
                rssi_dbm = %s,
                snr_db = %s,
                data_rate_bps = %s,
                packet_size_bytes = %s,
                bit_error_rate = %s,
                crc_valid = %s,
                ai_routing_decision = %s,
                ai_confidence_score = %s,
                deployment_confirmed = %s,
                packet_priority = %s,
                classification = %s
            WHERE packet_id = %s;
        """
        params = (
            data["ground_station"],
            data["satellite_id"],
            data["mission_phase"],
            int(data["orbit_number"]),
            float(data["altitude_km"]),
            float(data["orbital_velocity_kmps"]),
            data["eclipse_status"],
            float(data["battery_voltage_v"]),
            float(data["battery_soc_percent"]),
            float(data["solar_current_ma"]),
            float(data["onboard_temp_c"]),
            data["comm_mode"],
            float(data["rssi_dbm"]),
            float(data["snr_db"]),
            int(data["data_rate_bps"]),
            int(data["packet_size_bytes"]),
            float(data["bit_error_rate"]),
            data["crc_valid"],
            data["ai_routing_decision"],
            float(data["ai_confidence_score"]),
            data["deployment_confirmed"],
            data["packet_priority"],
            new_classification,
            packet_id,
        )

        cur.execute(update_sql, params)

        # Log change to change_log
        old_clean = {k: (str(v) if isinstance(v, datetime) else v) for k, v in dict(existing).items()}
        new_clean = {k: str(v) for k, v in data.items()}
        cur.execute(
            """
            INSERT INTO change_log (changed_by, action, table_name, record_id, old_values, new_values)
            VALUES (%s, 'UPDATE', 'telemetry_records', %s, %s, %s);
            """,
            (user_session.username, packet_id, json.dumps(old_clean, default=str), json.dumps(new_clean, default=str)),
        )

        # Log audit event
        security._log_audit(
            cur,
            user_session.username,
            "UPDATE_PACKET",
            "telemetry_records",
            str(packet_id),
            "SUCCESS",
            f"Operator {user_session.username} updated telemetry packet #{packet_id}.",
        )

    return True, f"Packet #{packet_id} updated and committed successfully."


def delete_telemetry_packet(
    user_session: security.UserSession,
    packet_id: int,
) -> Tuple[bool, str]:
    """
    Deletes a telemetry record inside a transaction.
    If user is Admin, deletes immediately.
    If user is non-admin (Engineer/Operator), queues deletion request to pending_changes.
    If user is Viewer, rejects with permission denied.
    """
    if user_session.role_name == "Viewer" or not (user_session.can("delete") or user_session.can("insert") or user_session.can("update")):
        return False, "Access Denied: Viewers do not have permission to delete or request deletion of telemetry."

    with db.get_db_cursor(commit=True, dict_cursor=True) as cur:
        security.set_db_session_context(cur, user_session)

        # Check existing row
        cur.execute("SELECT packet_id, classification FROM telemetry_records WHERE packet_id = %s;", (packet_id,))
        row = cur.fetchone()
        if not row:
            return False, f"Packet #{packet_id} not found or inaccessible."

        if user_session.is_admin():
            cur.execute("DELETE FROM telemetry_records WHERE packet_id = %s;", (packet_id,))

            cur.execute(
                """
                INSERT INTO change_log (changed_by, action, table_name, record_id, old_values)
                VALUES (%s, 'DELETE', 'telemetry_records', %s, %s);
                """,
                (user_session.username, packet_id, json.dumps({"packet_id": packet_id})),
            )

            security._log_audit(
                cur,
                user_session.username,
                "DELETE_PACKET",
                "telemetry_records",
                str(packet_id),
                "SUCCESS",
                f"Admin {user_session.username} permanently deleted packet #{packet_id}.",
            )
            return True, f"Packet #{packet_id} permanently deleted from database."
        else:
            # Queue to pending_changes for Admin approval
            cur.execute(
                """
                INSERT INTO pending_changes (
                    requested_by, action_type, target_table,
                    target_record_id, proposed_payload, status
                )
                VALUES (%s, 'DELETE', 'telemetry_records', %s, %s, 'PENDING')
                RETURNING change_id;
                """,
                (user_session.username, packet_id, json.dumps({"action": "DELETE", "packet_id": packet_id})),
            )
            change_id = cur.fetchone()["change_id"]

            security._log_audit(
                cur,
                user_session.username,
                "QUEUE_DELETE_REQUEST",
                "pending_changes",
                str(change_id),
                "SUCCESS",
                f"Operator {user_session.username} queued delete request #{change_id} for packet #{packet_id}.",
            )
            return True, f"Deletion request #{change_id} for packet #{packet_id} queued for Administrative approval."


def export_telemetry_to_csv(
    user_session: security.UserSession,
    filters: Optional[Dict[str, Any]],
    output_filepath: str,
    max_rows: int = 52000,
) -> Tuple[bool, str, int]:
    """
    Exports currently filtered telemetry records to a CSV file.
    Respects user's RBAC export permission and MAC clearance.
    """
    if not user_session.can("export"):
        return False, "Access Denied: Your role does not possess CSV export privileges.", 0

    where_clause, params = _build_filter_clause(filters)

    with db.get_db_cursor(commit=False, dict_cursor=True) as cur:
        security.set_db_session_context(cur, user_session)

        sql = f"""
            SELECT packet_id, timestamp_utc, ground_station, satellite_id,
                   mission_phase, orbit_number, altitude_km, orbital_velocity_kmps,
                   eclipse_status, battery_voltage_v, battery_soc_percent,
                   solar_current_ma, onboard_temp_c, comm_mode, rssi_dbm, snr_db,
                   data_rate_bps, packet_size_bytes, bit_error_rate, crc_valid,
                   ai_routing_decision, ai_confidence_score, deployment_confirmed,
                   packet_priority, classification
            FROM telemetry_records
            {where_clause}
            ORDER BY timestamp_utc DESC
            LIMIT %s;
        """
        cur.execute(sql, params + [max_rows])
        rows = cur.fetchall()

        if not rows:
            return False, "No records match current filter criteria to export.", 0

        fieldnames = list(rows[0].keys())
        with open(output_filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow(dict(r))

        with db.get_db_cursor(commit=True) as log_cur:
            security._log_audit(
                log_cur,
                user_session.username,
                "EXPORT_CSV",
                "telemetry_records",
                None,
                "SUCCESS",
                f"Exported {len(rows):,} filtered records to '{output_filepath}'.",
            )

    return True, f"Successfully exported {len(rows):,} records to CSV.", len(rows)


def get_filter_dropdown_options() -> Dict[str, List[str]]:
    """
    Fetches distinct values for all telemetry filter dropdowns.
    """
    options: Dict[str, List[str]] = {}
    with db.get_db_cursor() as cur:
        # Satellites
        cur.execute("SELECT satellite_id FROM satellites ORDER BY satellite_id;")
        options["satellites"] = ["All"] + [r[0] for r in cur.fetchall()]

        # Ground Stations
        cur.execute("SELECT station_code FROM ground_stations ORDER BY station_code;")
        options["stations"] = ["All"] + [r[0] for r in cur.fetchall()]

        # Comm Modes
        cur.execute("SELECT DISTINCT comm_mode FROM telemetry_records ORDER BY comm_mode;")
        options["comm_modes"] = ["All"] + [r[0] for r in cur.fetchall()]

        # AI Routing Decisions
        cur.execute("SELECT DISTINCT ai_routing_decision FROM telemetry_records ORDER BY ai_routing_decision;")
        options["ai_decisions"] = ["All"] + [r[0] for r in cur.fetchall()]

        # Priorities
        options["priorities"] = ["All", "Critical", "High", "Medium", "Low"]

        # Classifications
        options["classifications"] = ["All", "Restricted", "Internal", "Public"]

    return options


def fetch_ground_station_metrics() -> List[Dict[str, Any]]:
    """
    Returns ground stations combined with aggregated telemetry statistics:
    total packets, mean SNR, and CRC pass rate.
    """
    with db.get_db_cursor(commit=False, dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT 
                g.station_code, g.station_name, g.callsign, g.country,
                g.latitude, g.longitude, g.elevation_m, g.status,
                COALESCE(s.packet_count, 0) AS total_packets,
                COALESCE(s.mean_snr, 0.0) AS mean_snr,
                COALESCE(s.crc_pass_pct, 100.0) AS crc_pass_rate
            FROM ground_stations g
            LEFT JOIN (
                SELECT 
                    ground_station,
                    COUNT(*) AS packet_count,
                    ROUND(AVG(snr_db), 2) AS mean_snr,
                    ROUND(AVG(CASE WHEN crc_valid = 'Pass' THEN 100.0 ELSE 0.0 END), 1) AS crc_pass_pct
                FROM telemetry_records
                GROUP BY ground_station
            ) s ON g.station_code = s.ground_station
            ORDER BY total_packets DESC, g.station_name;
            """
        )
        return [dict(r) for r in cur.fetchall()]
