"""
models/analytics_queries.py - Telemetry Analytics, Saved Queries & ML Model
==========================================================================
Part of the ORBITAL Mission Telemetry System.

Responsibilities:
  1. Aggregated KPI Metrics (Total packets, CRC Pass %, Avg BER, Battery SOC %, Deployment %).
  2. Aggregated Datasets for Matplotlib Charts:
     - Packets per Ground Station
     - Comm Mode Usage
     - Battery SOC in Eclipse vs Sunlit
     - RSSI vs SNR Link Budget Scatter
     - AI Routing Decisions & Confidence Distribution
  3. Saved Telemetry Mission Queries (Low battery in eclipse, Failed CRC high priority, Thermal extremes).
  4. Scikit-Learn Packet Priority Classifier (predicts priority from link & power telemetry).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

import db
import security


# =============================================================================
# 1. KPI METRICS AGGREGATOR
# =============================================================================

def fetch_kpi_metrics(user_session: security.UserSession) -> Dict[str, Any]:
    """
    Computes high-level mission KPI cards filtered through Bell-LaPadula MAC.
    """
    with db.get_db_cursor(commit=False, dict_cursor=True) as cur:
        security.set_db_session_context(cur, user_session)

        cur.execute(
            """
            SELECT 
                COUNT(*) AS total_packets,
                ROUND(AVG(CASE WHEN crc_valid = 'Pass' THEN 100.0 ELSE 0.0 END), 2) AS crc_pass_rate,
                AVG(bit_error_rate) AS avg_ber,
                ROUND(AVG(battery_soc_percent), 2) AS avg_battery_soc,
                ROUND(AVG(battery_voltage_v), 2) AS avg_voltage,
                ROUND(AVG(CASE WHEN deployment_confirmed = 'Yes' THEN 100.0 ELSE 0.0 END), 1) AS deployment_rate,
                COUNT(DISTINCT ground_station) AS active_stations,
                COUNT(DISTINCT orbit_number) AS total_orbits
            FROM telemetry_records;
            """
        )
        row = cur.fetchone() or {}

        # Format BER nicely (e.g., 2.34e-4)
        ber_val = float(row.get("avg_ber") or 0.0)
        formatted_ber = f"{ber_val:.3e}" if ber_val > 0 else "0.000"

        return {
            "total_packets": int(row.get("total_packets") or 0),
            "crc_pass_rate": float(row.get("crc_pass_rate") or 0.0),
            "avg_ber": formatted_ber,
            "avg_battery_soc": float(row.get("avg_battery_soc") or 0.0),
            "avg_voltage": float(row.get("avg_voltage") or 0.0),
            "deployment_rate": float(row.get("deployment_rate") or 0.0),
            "active_stations": int(row.get("active_stations") or 0),
            "total_orbits": int(row.get("total_orbits") or 0),
        }


# =============================================================================
# 2. CHART DATA QUERIES (MATPLOTLIB EMBEDDING)
# =============================================================================

def fetch_station_distribution(user_session: security.UserSession, limit: int = 14) -> pd.DataFrame:
    """Returns packet counts grouped by receiving ground station."""
    with db.get_db_cursor(commit=False) as cur:
        security.set_db_session_context(cur, user_session)
        cur.execute(
            """
            SELECT ground_station, COUNT(*) AS packet_count
            FROM telemetry_records
            GROUP BY ground_station
            ORDER BY packet_count DESC
            LIMIT %s;
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=["ground_station", "packet_count"])


def fetch_comm_mode_distribution(user_session: security.UserSession) -> pd.DataFrame:
    """Returns packet counts and percentages grouped by RF comm mode."""
    with db.get_db_cursor(commit=False) as cur:
        security.set_db_session_context(cur, user_session)
        cur.execute(
            """
            SELECT comm_mode, COUNT(*) AS packet_count
            FROM telemetry_records
            GROUP BY comm_mode
            ORDER BY packet_count DESC;
            """
        )
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=["comm_mode", "packet_count"])


def fetch_battery_eclipse_data(user_session: security.UserSession) -> Tuple[np.ndarray, np.ndarray]:
    """
    Returns battery SOC values split by Eclipse vs Sunlit for boxplot / density analysis.
    """
    with db.get_db_cursor(commit=False) as cur:
        security.set_db_session_context(cur, user_session)
        cur.execute(
            """
            SELECT battery_soc_percent
            FROM telemetry_records
            WHERE eclipse_status = 'Eclipse'
            ORDER BY packet_id DESC
            LIMIT 4000;
            """
        )
        eclipse_vals = np.array([r[0] for r in cur.fetchall()], dtype=float)

        cur.execute(
            """
            SELECT battery_soc_percent
            FROM telemetry_records
            WHERE eclipse_status = 'Sunlit'
            ORDER BY packet_id DESC
            LIMIT 4000;
            """
        )
        sunlit_vals = np.array([r[0] for r in cur.fetchall()], dtype=float)

        return eclipse_vals, sunlit_vals


def fetch_rf_link_scatter_data(user_session: security.UserSession, limit: int = 1200) -> pd.DataFrame:
    """
    Returns sampled RF metrics (RSSI vs SNR) tagged with comm mode and priority.
    """
    with db.get_db_cursor(commit=False) as cur:
        security.set_db_session_context(cur, user_session)
        cur.execute(
            """
            SELECT rssi_dbm, snr_db, comm_mode, packet_priority, crc_valid
            FROM telemetry_records
            ORDER BY packet_id DESC
            LIMIT %s;
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=["rssi_dbm", "snr_db", "comm_mode", "packet_priority", "crc_valid"])


def fetch_ai_routing_distribution(user_session: security.UserSession) -> pd.DataFrame:
    """
    Returns autonomous AI routing decisions, packet counts, and mean confidence scores.
    """
    with db.get_db_cursor(commit=False) as cur:
        security.set_db_session_context(cur, user_session)
        cur.execute(
            """
            SELECT 
                ai_routing_decision,
                COUNT(*) AS packet_count,
                ROUND(AVG(ai_confidence_score) * 100, 2) AS avg_confidence_pct
            FROM telemetry_records
            GROUP BY ai_routing_decision
            ORDER BY packet_count DESC;
            """
        )
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=["decision", "count", "avg_confidence"])


# =============================================================================
# 3. SAVED MISSION QUERIES
# =============================================================================

SAVED_MISSION_QUERIES: Dict[str, Dict[str, str]] = {
    "LOW_BATTERY_ECLIPSE": {
        "title": "⚡ Low Battery During Eclipse (< 35% SOC)",
        "description": "Packets received during orbital eclipse showing dangerous battery discharge.",
        "sql": """
            SELECT packet_id, timestamp_utc, satellite_id, ground_station,
                   battery_voltage_v, battery_soc_percent, onboard_temp_c, packet_priority
            FROM telemetry_records
            WHERE eclipse_status = 'Eclipse' AND battery_soc_percent < 35.0
            ORDER BY battery_soc_percent ASC
            LIMIT 100;
        """,
    },
    "HIGH_PRIORITY_FAILED_CRC": {
        "title": "🚨 High/Critical Packets with Failed CRC",
        "description": "Critical downlink packets corrupted during atmospheric transit (RF link degredation).",
        "sql": """
            SELECT packet_id, timestamp_utc, ground_station, comm_mode,
                   rssi_dbm, snr_db, bit_error_rate, crc_valid, packet_priority
            FROM telemetry_records
            WHERE packet_priority IN ('High', 'Critical') AND crc_valid = 'Fail'
            ORDER BY packet_id DESC
            LIMIT 100;
        """,
    },
    "THERMAL_EXTREMES": {
        "title": "🌡️ Thermal Extremes (< -5°C or > 40°C)",
        "description": "Satellite bus temperature violations outside nominal operational thermal window.",
        "sql": """
            SELECT packet_id, timestamp_utc, satellite_id, eclipse_status,
                   onboard_temp_c, solar_current_ma, battery_voltage_v, comm_mode
            FROM telemetry_records
            WHERE onboard_temp_c < -5.0 OR onboard_temp_c > 40.0
            ORDER BY onboard_temp_c DESC
            LIMIT 100;
        """,
    },
    "HIGH_BER_ANOMALY": {
        "title": "📡 High Bit Error Rate (BER > 10⁻³)",
        "description": "Downlink packets experiencing severe channel noise or interference.",
        "sql": """
            SELECT packet_id, timestamp_utc, ground_station, comm_mode,
                   bit_error_rate, data_rate_bps, rssi_dbm, snr_db
            FROM telemetry_records
            WHERE bit_error_rate > 0.001
            ORDER BY bit_error_rate DESC
            LIMIT 100;
        """,
    },
    "POD_RELAY_LOW_CONFIDENCE": {
        "title": "🛰️ SomaiyaPod Relay with Low AI Confidence (< 75%)",
        "description": "Inter-satellite routing packets where AI routing confidence fell below nominal safety margin.",
        "sql": """
            SELECT packet_id, timestamp_utc, satellite_id, comm_mode,
                   ai_routing_decision, ai_confidence_score, packet_priority
            FROM telemetry_records
            WHERE ai_routing_decision = 'Relay-via-SomaiyaPod' AND ai_confidence_score < 0.75
            ORDER BY ai_confidence_score ASC
            LIMIT 100;
        """,
    },
}


def execute_saved_query(
    user_session: security.UserSession,
    query_key: str,
) -> Tuple[List[str], List[List[Any]]]:
    """
    Executes a predefined saved telemetry analysis query.
    Returns column names and table rows.
    """
    spec = SAVED_MISSION_QUERIES.get(query_key)
    if not spec:
        raise ValueError(f"Unknown saved query key: {query_key}")

    sql = spec["sql"]
    with db.get_db_cursor(commit=False) as cur:
        security.set_db_session_context(cur, user_session)
        cur.execute(sql)
        cols = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchall()
        return cols, rows


# =============================================================================
# 4. SCIKIT-LEARN AI PRIORITY PREDICTOR
# =============================================================================

class PriorityPredictorML:
    """
    Lightweight Scikit-Learn Classifier predicting packet_priority
    ('Low', 'Medium', 'High', 'Critical') based on Link, Power & Bus telemetry.
    """

    FEATURE_NAMES = [
        "battery_voltage_v",
        "battery_soc_percent",
        "solar_current_ma",
        "onboard_temp_c",
        "rssi_dbm",
        "snr_db",
        "data_rate_bps",
        "packet_size_bytes",
        "bit_error_rate",
        "ai_confidence_score",
    ]

    def __init__(self):
        self.model = RandomForestClassifier(
            n_estimators=80,
            random_state=42,
            n_jobs=-1,
        )
        self.is_trained = False
        self.accuracy: float = 0.0
        self.feature_importances: Dict[str, float] = {}

    def train_on_database(self, user_session: security.UserSession, sample_size: int = 12000) -> float:
        """
        Loads training data directly from PostgreSQL and trains the RandomForestClassifier.
        """
        with db.get_db_cursor(commit=False) as cur:
            security.set_db_session_context(cur, user_session)
            cols = ", ".join(self.FEATURE_NAMES)
            cur.execute(
                f"""
                SELECT {cols}, packet_priority
                FROM telemetry_records
                LIMIT %s;
                """,
                (sample_size,),
            )
            rows = cur.fetchall()

        if not rows:
            raise ValueError("Insufficient telemetry records in database to train model.")

        df = pd.DataFrame(rows, columns=self.FEATURE_NAMES + ["packet_priority"])
        X = df[self.FEATURE_NAMES].values
        y = df["packet_priority"].values

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        self.model.fit(X_train, y_train)
        y_pred = self.model.predict(X_test)
        self.accuracy = float(accuracy_score(y_test, y_pred))
        self.is_trained = True

        # Calculate feature importances
        for feat, imp in zip(self.FEATURE_NAMES, self.model.feature_importances_):
            self.feature_importances[feat] = float(imp)

        return self.accuracy

    def predict(self, feature_values: Dict[str, float]) -> Tuple[str, Dict[str, float]]:
        """
        Runs live inference for a set of telemetry inputs.
        Returns predicted priority class and probability distribution.
        """
        if not self.is_trained:
            raise RuntimeError("Model has not been trained yet. Call train_on_database() first.")

        vec = np.array([[feature_values[f] for f in self.FEATURE_NAMES]])
        pred_class = self.model.predict(vec)[0]
        probs = self.model.predict_proba(vec)[0]
        prob_dict = {cls: float(p) for cls, p in zip(self.model.classes_, probs)}

        return str(pred_class), prob_dict


# Global predictor singleton
_PREDICTOR_INSTANCE: Optional[PriorityPredictorML] = None


def get_priority_predictor() -> PriorityPredictorML:
    """Returns singleton instance of the Scikit-Learn Priority Predictor."""
    global _PREDICTOR_INSTANCE
    if _PREDICTOR_INSTANCE is None:
        _PREDICTOR_INSTANCE = PriorityPredictorML()
    return _PREDICTOR_INSTANCE
