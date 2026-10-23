"""
bootstrap.py - Pure Python Database Bootstrapper & Auto-Provisioner
===================================================================
Part of the ORBITAL Mission Telemetry System.

Zero-config automated setup:
  1. Verifies if database 'orbital_py_project' exists. If not, creates it.
  2. Creates all 10 relational tables, constraints, and indexes natively in Python.
  3. Deploys PostgreSQL CDC triggers (fn_telemetry_change_audit).
  4. Deploys Bell-LaPadula MAC Row-Level Security (RLS) policies.
  5. Seeds master satellites, 14 ground stations, RBAC roles, and MAC matrix.
  6. Seeds 4 bcrypt-encrypted demo operator accounts.
  7. Bulk-loads the 52,000 telemetry records from CSV if table is empty.

Allows seamless execution on ANY device via `python main.py` with NO external SQL scripts.
"""

from __future__ import annotations

import io
import os
import sys
import time
from typing import List, Tuple

import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

import db
import security

# -----------------------------------------------------------------------------
# MASTER SEED DEFINITIONS
# -----------------------------------------------------------------------------

SATELLITES_SEED: List[Tuple[str, str, int, str, str, str, str]] = [
    (
        "SomaiyaSat",
        "SomaiyaSat PocketQube 1P",
        60234,
        "PocketQube",
        "Active",
        "2026-02-15",
        "Somaiya Vidyavihar amateur radio & AI data relay satellite (1P form factor)",
    ),
    (
        "SomaiyaPod",
        "SomaiyaPod PocketQube 2P Mothercraft",
        60235,
        "PocketQube",
        "Active",
        "2026-02-15",
        "Somaiya deployer pod & inter-satellite store-and-forward relay node (2P)",
    ),
]

GROUND_STATIONS_SEED: List[Tuple[str, str, str, str, float, float, float, str]] = [
    ("Mumbai-VU2SOMAIYA", "Somaiya Vidyavihar Ground Station", "VU2SOMAIYA", "India", 19.0728, 72.8998, 14.0, "Online"),
    ("Bengaluru-VU2BLR", "Bengaluru Amateur Satellite Station", "VU2BLR", "India", 12.9716, 77.5946, 920.0, "Online"),
    ("Delhi-VU2DEL", "Delhi Telemetry Tracking Station", "VU2DEL", "India", 28.6139, 77.2090, 216.0, "Online"),
    ("Chennai-VU2CHN", "Chennai Coastal Satellite Terminal", "VU2CHN", "India", 13.0827, 80.2707, 6.0, "Online"),
    ("Helsinki-OH2REORBIT", "Helsinki ReOrbit Tracking Facility", "OH2REORBIT", "Finland", 60.1699, 24.9384, 25.0, "Online"),
    ("Oulu-OH8SAT", "Oulu Sub-Arctic Station", "OH8SAT", "Finland", 65.0121, 25.4651, 15.0, "Online"),
    ("Zurich-HB9GND", "Zurich Alpine Node", "HB9GND", "Switzerland", 47.3769, 8.5417, 408.0, "Online"),
    ("Berlin-DL0CUBE", "Berlin CubeSat Gateway", "DL0CUBE", "Germany", 52.5200, 13.4050, 34.0, "Online"),
    ("Toronto-VE3POD", "Toronto Amateur Radio Tracking", "VE3POD", "Canada", 43.6532, -79.3832, 76.0, "Online"),
    ("California-W6PQC", "California PocketQube Center", "W6PQC", "USA", 37.7749, -122.4194, 16.0, "Online"),
    ("Melbourne-VK3SAT", "Melbourne Southern Hemisphere Node", "VK3SAT", "Australia", -37.8136, 144.9631, 31.0, "Online"),
    ("Sao Paulo-PY2AMSAT", "Sao Paulo AMSAT Gateway", "PY2AMSAT", "Brazil", -23.5505, -46.6333, 760.0, "Online"),
    ("Tokyo-JA1SPACE", "Tokyo Space Communication Hub", "JA1SPACE", "Japan", 35.6762, 139.6503, 40.0, "Online"),
    ("Cape Town-ZS1AMSAT", "Cape Town Southern Cross Station", "ZS1AMSAT", "South Africa", -33.9249, 18.4241, 25.0, "Online"),
]

RBAC_ROLES_SEED: List[Tuple[str, str, bool, bool, bool, bool, bool, bool, bool, bool]] = [
    (
        "Admin",
        "Full administrative control: User management, approval queue, dry-run SQL workbench, full CRUD.",
        True, True, True, True, True, True, True, True,
    ),
    (
        "Engineer",
        "Mission Engineering: Read, insert, update, export CSV, and run dry-run SQL workbench.",
        True, True, True, False, True, True, False, False,
    ),
    (
        "Operator",
        "Ground Station Operator: Real-time telemetry monitoring, packet insertion, and CSV export.",
        True, True, False, False, True, False, False, False,
    ),
    (
        "Viewer",
        "Public / Read-only viewer: Can observe telemetry grids, station maps, and dashboard metrics.",
        True, False, False, False, False, False, False, False,
    ),
]

MAC_POLICIES_SEED: List[Tuple[str, str, bool, bool]] = [
    ("Public", "Public", True, True),
    ("Public", "Internal", False, True),
    ("Public", "Restricted", False, True),
    ("Internal", "Public", True, False),
    ("Internal", "Internal", True, True),
    ("Internal", "Restricted", False, True),
    ("Restricted", "Public", True, False),
    ("Restricted", "Internal", True, False),
    ("Restricted", "Restricted", True, True),
]

# -----------------------------------------------------------------------------
# DDL STRINGS EMBEDDED DIRECTLY IN PYTHON (NO EXTERNAL .SQL FILES)
# -----------------------------------------------------------------------------

SCHEMA_DDL = """
-- 1. SATELLITES TABLE
CREATE TABLE IF NOT EXISTS satellites (
    satellite_id            VARCHAR(50) PRIMARY KEY,
    satellite_name          VARCHAR(100) NOT NULL,
    norad_id                INTEGER UNIQUE,
    form_factor             VARCHAR(30) DEFAULT 'PocketQube',
    status                  VARCHAR(30) NOT NULL DEFAULT 'Active'
                            CHECK (status IN ('Active', 'Standby', 'Decommissioned', 'Decayed')),
    launch_date             DATE,
    description             TEXT
);

-- 2. GROUND STATIONS TABLE
CREATE TABLE IF NOT EXISTS ground_stations (
    station_code            VARCHAR(50) PRIMARY KEY,
    station_name            VARCHAR(100) NOT NULL,
    callsign                VARCHAR(30) NOT NULL,
    country                 VARCHAR(60) NOT NULL,
    latitude                NUMERIC(8, 4) NOT NULL CHECK (latitude BETWEEN -90.0 AND 90.0),
    longitude               NUMERIC(8, 4) NOT NULL CHECK (longitude BETWEEN -180.0 AND 180.0),
    elevation_m             NUMERIC(7, 2) NOT NULL DEFAULT 0.0 CHECK (elevation_m >= -500.0),
    status                  VARCHAR(30) NOT NULL DEFAULT 'Online'
                            CHECK (status IN ('Online', 'Degraded', 'Offline', 'Maintenance'))
);

-- 3. RBAC ROLES TABLE
CREATE TABLE IF NOT EXISTS rbac_roles (
    role_name               VARCHAR(30) PRIMARY KEY
                            CHECK (role_name IN ('Admin', 'Engineer', 'Operator', 'Viewer')),
    description             TEXT,
    can_read                BOOLEAN NOT NULL DEFAULT TRUE,
    can_insert              BOOLEAN NOT NULL DEFAULT FALSE,
    can_update              BOOLEAN NOT NULL DEFAULT FALSE,
    can_delete              BOOLEAN NOT NULL DEFAULT FALSE,
    can_export              BOOLEAN NOT NULL DEFAULT FALSE,
    can_run_sql             BOOLEAN NOT NULL DEFAULT FALSE,
    can_manage_users        BOOLEAN NOT NULL DEFAULT FALSE,
    can_approve_changes     BOOLEAN NOT NULL DEFAULT FALSE
);

-- 4. APP USERS TABLE
CREATE TABLE IF NOT EXISTS app_users (
    user_id                 SERIAL PRIMARY KEY,
    username                VARCHAR(50) UNIQUE NOT NULL,
    password_hash           VARCHAR(255) NOT NULL,
    full_name               VARCHAR(100) NOT NULL,
    email                   VARCHAR(120),
    role_name               VARCHAR(30) NOT NULL REFERENCES rbac_roles(role_name) ON UPDATE CASCADE,
    clearance_level         VARCHAR(20) NOT NULL DEFAULT 'Public'
                            CHECK (clearance_level IN ('Public', 'Internal', 'Restricted')),
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    failed_login_count      INTEGER NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    locked_until            TIMESTAMP WITHOUT TIME ZONE,
    last_login              TIMESTAMP WITHOUT TIME ZONE,
    created_at              TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 5. TELEMETRY RECORDS TABLE
CREATE TABLE IF NOT EXISTS telemetry_records (
    packet_id               BIGINT PRIMARY KEY,
    timestamp_utc           TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    ground_station          VARCHAR(50) NOT NULL REFERENCES ground_stations(station_code) ON UPDATE CASCADE,
    satellite_id            VARCHAR(50) NOT NULL REFERENCES satellites(satellite_id) ON UPDATE CASCADE,
    mission_phase           VARCHAR(30) NOT NULL
                            CHECK (mission_phase IN ('Nominal Ops', 'Safe Mode', 'Commissioning', 'Deployment')),
    orbit_number            INTEGER NOT NULL CHECK (orbit_number >= 0),
    altitude_km             NUMERIC(8, 3) NOT NULL CHECK (altitude_km > 0),
    orbital_velocity_kmps   NUMERIC(7, 3) NOT NULL CHECK (orbital_velocity_kmps > 0),
    eclipse_status          VARCHAR(20) NOT NULL
                            CHECK (eclipse_status IN ('Eclipse', 'Sunlit')),
    battery_voltage_v       NUMERIC(5, 3) NOT NULL CHECK (battery_voltage_v >= 0),
    battery_soc_percent     NUMERIC(5, 2) NOT NULL CHECK (battery_soc_percent BETWEEN 0.0 AND 100.0),
    solar_current_ma        NUMERIC(7, 2) NOT NULL CHECK (solar_current_ma >= 0.0),
    onboard_temp_c          NUMERIC(6, 2) NOT NULL,
    comm_mode               VARCHAR(40) NOT NULL
                            CHECK (comm_mode IN ('TT&C/Housekeeping', 'SSTV', 'M17', 'Codec2')),
    rssi_dbm                NUMERIC(6, 2) NOT NULL,
    snr_db                  NUMERIC(6, 2) NOT NULL,
    data_rate_bps           INTEGER NOT NULL CHECK (data_rate_bps > 0),
    packet_size_bytes       INTEGER NOT NULL CHECK (packet_size_bytes > 0),
    bit_error_rate          NUMERIC(8, 6) NOT NULL CHECK (bit_error_rate >= 0.0),
    crc_valid               VARCHAR(10) NOT NULL
                            CHECK (crc_valid IN ('Pass', 'Fail')),
    ai_routing_decision     VARCHAR(50) NOT NULL
                            CHECK (ai_routing_decision IN ('Direct-to-Ground', 'Relay-via-SomaiyaPod', 'Store-and-Forward')),
    ai_confidence_score     NUMERIC(5, 3) NOT NULL CHECK (ai_confidence_score BETWEEN 0.0 AND 1.0),
    deployment_confirmed    VARCHAR(10) NOT NULL
                            CHECK (deployment_confirmed IN ('Yes', 'No')),
    packet_priority         VARCHAR(20) NOT NULL
                            CHECK (packet_priority IN ('Low', 'Medium', 'High', 'Critical')),
    classification          VARCHAR(20) NOT NULL DEFAULT 'Public'
                            CHECK (classification IN ('Public', 'Internal', 'Restricted')),
    owner_username          VARCHAR(50) NOT NULL DEFAULT 'system',
    created_at              TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_telemetry_timestamp_utc ON telemetry_records (timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_telemetry_ground_station ON telemetry_records (ground_station);
CREATE INDEX IF NOT EXISTS idx_telemetry_comm_mode ON telemetry_records (comm_mode);
CREATE INDEX IF NOT EXISTS idx_telemetry_satellite_id ON telemetry_records (satellite_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_classification ON telemetry_records (classification);
CREATE INDEX IF NOT EXISTS idx_telemetry_packet_priority ON telemetry_records (packet_priority);

-- 6. DAC GRANTS TABLE
CREATE TABLE IF NOT EXISTS dac_grants (
    grant_id                SERIAL PRIMARY KEY,
    granter_username        VARCHAR(50) NOT NULL REFERENCES app_users(username) ON UPDATE CASCADE ON DELETE CASCADE,
    grantee_username        VARCHAR(50) NOT NULL REFERENCES app_users(username) ON UPDATE CASCADE ON DELETE CASCADE,
    target_type             VARCHAR(20) NOT NULL CHECK (target_type IN ('table', 'row')),
    target_packet_id        BIGINT REFERENCES telemetry_records(packet_id) ON DELETE CASCADE,
    permission              VARCHAR(20) NOT NULL CHECK (permission IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'ALL')),
    granted_at              TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at              TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT chk_dac_target CHECK (
        (target_type = 'row' AND target_packet_id IS NOT NULL) OR
        (target_type = 'table' AND target_packet_id IS NULL)
    )
);

-- 7. MAC POLICIES TABLE
CREATE TABLE IF NOT EXISTS mac_policies (
    policy_id               SERIAL PRIMARY KEY,
    subject_clearance       VARCHAR(20) NOT NULL CHECK (subject_clearance IN ('Public', 'Internal', 'Restricted')),
    object_classification   VARCHAR(20) NOT NULL CHECK (object_classification IN ('Public', 'Internal', 'Restricted')),
    can_read                BOOLEAN NOT NULL,
    can_write               BOOLEAN NOT NULL,
    CONSTRAINT uq_mac_policy UNIQUE (subject_clearance, object_classification)
);

-- 8. AUDIT EVENTS TABLE
CREATE TABLE IF NOT EXISTS audit_events (
    event_id                BIGSERIAL PRIMARY KEY,
    timestamp_utc           TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    username                VARCHAR(50) NOT NULL,
    action_type             VARCHAR(50) NOT NULL,
    target_table            VARCHAR(50),
    target_id               VARCHAR(50),
    status                  VARCHAR(20) NOT NULL DEFAULT 'SUCCESS'
                            CHECK (status IN ('SUCCESS', 'FAILED', 'DENIED')),
    details                 TEXT,
    client_ip               VARCHAR(50) DEFAULT '127.0.0.1'
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events (timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_audit_username ON audit_events (username);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events (action_type);

-- 9. CHANGE LOG TABLE
CREATE TABLE IF NOT EXISTS change_log (
    log_id                  BIGSERIAL PRIMARY KEY,
    changed_at              TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changed_by              VARCHAR(50) NOT NULL DEFAULT CURRENT_USER,
    action                  VARCHAR(10) NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
    table_name              VARCHAR(50) NOT NULL,
    record_id               BIGINT NOT NULL,
    old_values              JSONB,
    new_values              JSONB
);

CREATE INDEX IF NOT EXISTS idx_change_log_table_record ON change_log (table_name, record_id);
CREATE INDEX IF NOT EXISTS idx_change_log_changed_at ON change_log (changed_at);

-- 10. PENDING CHANGES TABLE
CREATE TABLE IF NOT EXISTS pending_changes (
    change_id               SERIAL PRIMARY KEY,
    requested_at            TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    requested_by            VARCHAR(50) NOT NULL REFERENCES app_users(username) ON UPDATE CASCADE,
    action_type             VARCHAR(20) NOT NULL CHECK (action_type IN ('DELETE', 'UPDATE', 'BULK_UPDATE')),
    target_table            VARCHAR(50) NOT NULL,
    target_record_id        BIGINT,
    proposed_payload        JSONB NOT NULL,
    status                  VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                            CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    reviewed_by             VARCHAR(50) REFERENCES app_users(username) ON UPDATE CASCADE,
    reviewed_at             TIMESTAMP WITHOUT TIME ZONE,
    review_comments         TEXT
);

CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_changes (status);
"""

TRIGGERS_DDL = """
-- Automated Change Data Capture (CDC) Trigger Function
CREATE OR REPLACE FUNCTION fn_telemetry_change_audit()
RETURNS TRIGGER AS $$
DECLARE
    v_user VARCHAR(50);
    v_action VARCHAR(10);
    v_record_id BIGINT;
    v_old JSONB := NULL;
    v_new JSONB := NULL;
BEGIN
    v_user := COALESCE(NULLIF(current_setting('app.username', true), ''), CURRENT_USER);

    IF (TG_OP = 'INSERT') THEN
        v_action := 'INSERT';
        v_record_id := NEW.packet_id;
        v_new := to_jsonb(NEW);
    ELSIF (TG_OP = 'UPDATE') THEN
        v_action := 'UPDATE';
        v_record_id := NEW.packet_id;
        v_old := to_jsonb(OLD);
        v_new := to_jsonb(NEW);
    ELSIF (TG_OP = 'DELETE') THEN
        v_action := 'DELETE';
        v_record_id := OLD.packet_id;
        v_old := to_jsonb(OLD);
    END IF;

    INSERT INTO change_log (
        changed_at, changed_by, action, table_name, record_id, old_values, new_values
    )
    VALUES (
        CURRENT_TIMESTAMP, v_user, v_action, 'telemetry_records', v_record_id, v_old, v_new
    );

    IF (TG_OP = 'DELETE') THEN
        RETURN OLD;
    ELSE
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS trg_telemetry_audit ON telemetry_records;

CREATE TRIGGER trg_telemetry_audit
AFTER INSERT OR UPDATE OR DELETE ON telemetry_records
FOR EACH ROW EXECUTE FUNCTION fn_telemetry_change_audit();
"""

SECURITY_RLS_DDL = """
CREATE OR REPLACE FUNCTION get_clearance_rank(lvl text) RETURNS integer AS $$
BEGIN
    CASE LOWER(COALESCE(lvl, 'public'))
        WHEN 'public' THEN RETURN 1;
        WHEN 'unclassified' THEN RETURN 1;
        WHEN 'internal' THEN RETURN 2;
        WHEN 'restricted' THEN RETURN 3;
        ELSE RETURN 1;
    END CASE;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

ALTER TABLE telemetry_records ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rls_telemetry_select ON telemetry_records;
DROP POLICY IF EXISTS rls_telemetry_insert ON telemetry_records;
DROP POLICY IF EXISTS rls_telemetry_update ON telemetry_records;
DROP POLICY IF EXISTS rls_telemetry_delete ON telemetry_records;

CREATE POLICY rls_telemetry_select ON telemetry_records
FOR SELECT
USING (
    current_setting('app.role', true) = 'Admin'
    OR current_setting('app.username', true) = 'system'
    OR current_setting('app.clearance', true) IS NULL
    OR get_clearance_rank(current_setting('app.clearance', true)) >= get_clearance_rank(classification)
    OR EXISTS (
        SELECT 1 FROM dac_grants
        WHERE grantee_username = current_setting('app.username', true)
          AND target_packet_id = telemetry_records.packet_id
          AND permission IN ('SELECT', 'ALL')
          AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
    )
);

CREATE POLICY rls_telemetry_insert ON telemetry_records
FOR INSERT
WITH CHECK (
    current_setting('app.role', true) = 'Admin'
    OR current_setting('app.username', true) = 'system'
    OR current_setting('app.clearance', true) IS NULL
    OR get_clearance_rank(current_setting('app.clearance', true)) <= get_clearance_rank(classification)
);

CREATE POLICY rls_telemetry_update ON telemetry_records
FOR UPDATE
USING (
    current_setting('app.role', true) = 'Admin'
    OR current_setting('app.username', true) = 'system'
    OR (
        get_clearance_rank(current_setting('app.clearance', true)) >= get_clearance_rank(classification)
        AND (
            owner_username = current_setting('app.username', true)
            OR EXISTS (
                SELECT 1 FROM dac_grants
                WHERE grantee_username = current_setting('app.username', true)
                  AND target_packet_id = telemetry_records.packet_id
                  AND permission IN ('UPDATE', 'ALL')
                  AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            )
        )
    )
);

CREATE POLICY rls_telemetry_delete ON telemetry_records
FOR DELETE
USING (
    current_setting('app.role', true) = 'Admin'
    OR current_setting('app.username', true) = 'system'
    OR (
        current_setting('app.role', true) IN ('Engineer', 'Operator')
        AND owner_username = current_setting('app.username', true)
    )
);
"""


def classify_telemetry_packet(row: pd.Series) -> str:
    """Security Classification based on priority and flight phase."""
    priority = row["packet_priority"]
    phase = row["mission_phase"]
    mode = row["comm_mode"]

    if priority == "Critical" or phase in ("Safe Mode", "Commissioning"):
        return "Restricted"
    elif priority == "High" or mode in ("TT&C/Housekeeping", "M17"):
        return "Internal"
    else:
        return "Public"


def ensure_database_and_schema_ready() -> None:
    """
    Main self-bootstrapping entry point.
    Guarantees database, tables, triggers, policies, and initial data exist.
    """
    cfg = db.get_db_config()
    target_db = cfg["dbname"]

    # 1. Ensure target database exists
    print(f"[*] Checking PostgreSQL database '{target_db}'...")
    try:
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
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (target_db,))
        exists = cur.fetchone() is not None
        if not exists:
            cur.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8';").format(sql.Identifier(target_db)))
            print(f"[+] Successfully created database '{target_db}'.")
        cur.close()
        conn.close()
    except Exception as exc:
        print(f"[i] Direct connection note: {exc}")

    # 2. Check if tables already exist in target database
    with db.get_db_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'telemetry_records'
            );
            """
        )
        tables_exist = cur.fetchone()[0]

    if not tables_exist:
        print("[*] Fresh installation detected. Setting up relational schema in Python...")
        with db.get_db_cursor(commit=True) as cur:
            cur.execute(SCHEMA_DDL)
            cur.execute(TRIGGERS_DDL)
            cur.execute(SECURITY_RLS_DDL)

            # Seed master reference tables
            cur.executemany(
                """
                INSERT INTO satellites (satellite_id, satellite_name, norad_id, form_factor, status, launch_date, description)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (satellite_id) DO NOTHING;
                """,
                SATELLITES_SEED,
            )

            cur.executemany(
                """
                INSERT INTO ground_stations (station_code, station_name, callsign, country, latitude, longitude, elevation_m, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (station_code) DO NOTHING;
                """,
                GROUND_STATIONS_SEED,
            )

            cur.executemany(
                """
                INSERT INTO rbac_roles (role_name, description, can_read, can_insert, can_update, can_delete, can_export, can_run_sql, can_manage_users, can_approve_changes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (role_name) DO NOTHING;
                """,
                RBAC_ROLES_SEED,
            )

            cur.executemany(
                """
                INSERT INTO mac_policies (subject_clearance, object_classification, can_read, can_write)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (subject_clearance, object_classification) DO NOTHING;
                """,
                MAC_POLICIES_SEED,
            )
        print("[+] Schema and reference data provisioned.")

        # Seed demo user accounts
        security.seed_demo_users()

    # 3. Check if telemetry records table is populated
    with db.get_db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) FROM telemetry_records;")
        row_count = cur.fetchone()[0]

    csv_file = "somaiyasat_somaiyapod_telemetry_dataset_52k.csv"
    if row_count == 0 and os.path.exists(csv_file):
        print(f"[*] Telemetry records table empty. Ingesting '{csv_file}'...")
        df = pd.read_csv(csv_file)
        df["packet_id"] = df["packet_id"].astype("int64")
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"]).dt.strftime("%Y-%m-%d %H:%M:%S")
        df["classification"] = df.apply(classify_telemetry_packet, axis=1)
        df["owner_username"] = "system"

        columns = [
            "packet_id", "timestamp_utc", "ground_station", "satellite_id", "mission_phase",
            "orbit_number", "altitude_km", "orbital_velocity_kmps", "eclipse_status",
            "battery_voltage_v", "battery_soc_percent", "solar_current_ma", "onboard_temp_c",
            "comm_mode", "rssi_dbm", "snr_db", "data_rate_bps", "packet_size_bytes",
            "bit_error_rate", "crc_valid", "ai_routing_decision", "ai_confidence_score",
            "deployment_confirmed", "packet_priority", "classification", "owner_username",
        ]

        buffer = io.StringIO()
        df[columns].to_csv(buffer, index=False, header=False, sep="\t", na_rep="\\N")
        buffer.seek(0)
        copy_sql = f"COPY telemetry_records ({', '.join(columns)}) FROM STDIN WITH (FORMAT text, NULL '\\N');"

        with db.get_db_cursor(commit=True) as cur:
            try:
                cur.copy_expert(copy_sql, buffer)
            except Exception:
                buffer.seek(0)
                data_tuples = df[columns].values.tolist()
                insert_sql = f"INSERT INTO telemetry_records ({', '.join(columns)}) VALUES %s ON CONFLICT (packet_id) DO NOTHING;"
                execute_values(cur, insert_sql, data_tuples, page_size=5000)

        print(f"[+] Loaded {len(df):,} telemetry packets into PostgreSQL.")
    else:
        print(f"[+] Database '{target_db}' is ready with {row_count:,} telemetry records.")
