"""
gui/tab_workbench.py - Safe SQL Workbench & Governance Lab
=========================================================
Part of the ORBITAL Mission Telemetry System.

Responsibilities:
  1. Interactive SQL editor with preset mission telemetry queries.
  2. Real-time AST safety feedback via sqlparse (blocking DROP, TRUNCATE, unqualified DELETE/UPDATE).
  3. Transactional Dry-Run Preview (guaranteed ROLLBACK with timing & row count).
  4. Live execution and commit for authorized users (Admin & Engineer).
  5. Dynamic ttk.Treeview data grid rendering variable query projections.
"""

from __future__ import annotations

import threading
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional

import customtkinter as ctk

import security
import theme
from models.governance_queries import (
    execute_dry_run_sql,
    execute_live_sql,
    validate_sql_safety,
)

PRESET_QUERIES = [
    (
        "Low Battery during Eclipse (< 50% SOC)",
        "SELECT packet_id, timestamp_utc, ground_station, satellite_id, battery_voltage_v, battery_soc_percent, eclipse_status\n"
        "FROM telemetry_records\n"
        "WHERE eclipse_status = 'Eclipse' AND battery_soc_percent < 50.0\n"
        "ORDER BY battery_soc_percent ASC\n"
        "LIMIT 50;",
    ),
    (
        "High Priority Packets with CRC Failures",
        "SELECT packet_id, timestamp_utc, ground_station, satellite_id, comm_mode, rssi_dbm, snr_db, crc_valid, packet_priority\n"
        "FROM telemetry_records\n"
        "WHERE crc_valid = 'Fail' AND packet_priority IN ('High', 'Critical')\n"
        "ORDER BY timestamp_utc DESC\n"
        "LIMIT 50;",
    ),
    (
        "AI Routing Confidence Summary by Comm Mode",
        "SELECT comm_mode, ai_routing_decision, COUNT(*) as packets, ROUND(AVG(ai_confidence_score), 3) as avg_conf\n"
        "FROM telemetry_records\n"
        "GROUP BY comm_mode, ai_routing_decision\n"
        "ORDER BY comm_mode, packets DESC;",
    ),
    (
        "SomaiyaSat Safe Mode Diagnostic Records",
        "SELECT packet_id, timestamp_utc, ground_station, onboard_temp_c, battery_voltage_v, comm_mode, packet_priority, classification\n"
        "FROM telemetry_records\n"
        "WHERE mission_phase = 'Safe Mode'\n"
        "ORDER BY timestamp_utc DESC\n"
        "LIMIT 50;",
    ),
]


class WorkbenchTab(ctk.CTkFrame):
    """Safe SQL Workbench UI with dry-run verification and AST safety checks."""

    def __init__(self, master: Any, user: security.UserSession, **kwargs):
        super().__init__(master, fg_color=theme.COLOR_BG_DARK, corner_radius=0, **kwargs)

        self.user = user

        # Ensure TTK dark theme is initialized
        theme.init_ttk_styles(self)

        # Build UI layout
        self._create_header_and_presets()
        self._create_editor_card()
        self._create_results_grid()

    def _create_header_and_presets(self) -> None:
        """Top bar with title, preset dropdown, and AST verification badge."""
        top_card = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_PANEL_BG,
            corner_radius=10,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        top_card.pack(fill="x", padx=10, pady=(10, 6))

        inner = ctk.CTkFrame(top_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=10)

        # Title
        ctk.CTkLabel(
            inner,
            text="🛠️ Safe SQL Workbench & Governance Lab",
            font=theme.FONT_TITLE,
            text_color=theme.COLOR_TEXT_PRIMARY,
        ).pack(side="left")

        # Presets Dropdown
        ctk.CTkLabel(inner, text="Preset Queries:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(side="left", padx=(20, 6))
        self.preset_combo = ctk.CTkComboBox(
            inner,
            values=[p[0] for p in PRESET_QUERIES],
            command=self._on_preset_selected,
            width=280,
            height=28,
            font=theme.FONT_SMALL,
            fg_color=theme.COLOR_INPUT_BG,
            border_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
            dropdown_fg_color=theme.COLOR_PANEL_BG,
        )
        self.preset_combo.set("Select a preset query...")
        self.preset_combo.pack(side="left", padx=(0, 10))

    def _on_preset_selected(self, choice: str) -> None:
        """Loads selected preset SQL query into editor."""
        for title, sql in PRESET_QUERIES:
            if title == choice:
                self.sql_editor.delete("1.0", "end")
                self.sql_editor.insert("1.0", sql)
                self._check_ast_safety()
                break

    def _create_editor_card(self) -> None:
        """SQL Query editor with AST safety indicator and action buttons."""
        card = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_PANEL_BG,
            corner_radius=10,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        card.pack(fill="x", padx=10, pady=(0, 6))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        # Editor
        self.sql_editor = ctk.CTkTextbox(
            inner,
            height=110,
            fg_color=theme.COLOR_INPUT_BG,
            border_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
            font=theme.FONT_CODE,
        )
        self.sql_editor.pack(fill="x", pady=(0, 8))
        self.sql_editor.insert("1.0", PRESET_QUERIES[0][1])
        self.sql_editor.bind("<KeyRelease>", lambda e: self._check_ast_safety())

        # Action Buttons & Status Row
        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x")

        # Dry Run Button
        self.dry_run_btn = ctk.CTkButton(
            btn_row,
            text="🧪 Dry-Run Preview (BEGIN...ROLLBACK)",
            command=self._handle_dry_run,
            fg_color=theme.COLOR_HIGHLIGHT_GOLD,
            hover_color=theme.COLOR_GOLD_HOVER,
            text_color=theme.COLOR_BG_DARK,
            font=theme.FONT_BODY_BOLD,
            height=32,
            corner_radius=6,
        )
        self.dry_run_btn.pack(side="left", padx=(0, 8))

        # Live Execute Button (Admin only)
        self.live_btn = ctk.CTkButton(
            btn_row,
            text="▶ Execute & Commit",
            command=self._handle_live_execute,
            state="normal" if self.user.is_admin() else "disabled",
            fg_color=theme.COLOR_STATUS_FAIL if self.user.is_admin() else theme.COLOR_PANEL_BORDER,
            hover_color="#8B1E2B",
            text_color=theme.COLOR_TEXT_PRIMARY if self.user.is_admin() else theme.COLOR_TEXT_DISABLED,
            font=theme.FONT_BODY_BOLD,
            height=32,
            corner_radius=6,
        )
        self.live_btn.pack(side="left", padx=(0, 12))

        # AST Safety Status Label
        self.safety_lbl = ctk.CTkLabel(
            btn_row,
            text="✓ AST Verification: Query Safe",
            font=theme.FONT_SMALL,
            text_color=theme.COLOR_STATUS_PASS,
        )
        self.safety_lbl.pack(side="left")

        # Results status summary
        self.results_status_lbl = ctk.CTkLabel(
            btn_row,
            text="",
            font=theme.FONT_CODE_BOLD,
            text_color=theme.COLOR_HIGHLIGHT_GOLD,
        )
        self.results_status_lbl.pack(side="right")

    def _check_ast_safety(self) -> None:
        """Evaluates AST of current editor text and updates status."""
        query = self.sql_editor.get("1.0", "end").strip()
        is_safe, msg = validate_sql_safety(query)
        if is_safe:
            self.safety_lbl.configure(text=f"✓ AST: {msg}", text_color=theme.COLOR_STATUS_PASS)
            self.dry_run_btn.configure(state="normal")
            if self.user.is_admin():
                self.live_btn.configure(state="normal")
        else:
            self.safety_lbl.configure(text=f"⛔ {msg}", text_color=theme.COLOR_STATUS_FAIL)
            self.dry_run_btn.configure(state="disabled")
            self.live_btn.configure(state="disabled")

    def _create_results_grid(self) -> None:
        """Constructs dynamic Treeview for query result projections."""
        self.grid_card = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_PANEL_BG,
            corner_radius=10,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        self.grid_card.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.tree = ttk.Treeview(self.grid_card, show="headings", style="Telemetry.Treeview")
        vsb = ttk.Scrollbar(self.grid_card, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self.grid_card, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew", padx=(2, 0), pady=(2, 0))
        vsb.grid(row=0, column=1, sticky="ns", padx=(0, 2), pady=(2, 0))
        hsb.grid(row=1, column=0, sticky="ew", padx=(2, 0), pady=(0, 2))

        self.grid_card.rowconfigure(0, weight=1)
        self.grid_card.columnconfigure(0, weight=1)

    def _handle_dry_run(self) -> None:
        """Executes transactional dry-run with automatic ROLLBACK."""
        query = self.sql_editor.get("1.0", "end").strip()
        self.results_status_lbl.configure(text="Executing dry-run...")
        self.update_idletasks()

        res = execute_dry_run_sql(self.user, query)
        self._display_results(res)

    def _handle_live_execute(self) -> None:
        """Executes and commits live SQL query."""
        query = self.sql_editor.get("1.0", "end").strip()
        if not messagebox.askyesno(
            "Confirm Live Execution",
            "Are you sure you want to EXECUTE & COMMIT this statement?\n\nThis will permanently modify the database.",
        ):
            return

        self.results_status_lbl.configure(text="Executing live commit...")
        self.update_idletasks()

        res = execute_live_sql(self.user, query)
        self._display_results(res)

    def _display_results(self, res: Dict[str, Any]) -> None:
        """Renders query result columns and rows into the Treeview."""
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not res.get("success"):
            messagebox.showerror("Execution Error", res.get("error", "Unknown error"))
            self.results_status_lbl.configure(text="Execution Failed")
            return

        columns = res.get("columns", [])
        rows = res.get("rows", [])
        elapsed = res.get("elapsed_ms", 0)
        row_cnt = res.get("row_count", 0)
        is_dry = res.get("dry_run", False)

        tag_str = "[DRY-RUN ROLLBACK]" if is_dry else "[COMMITTED]"
        self.results_status_lbl.configure(
            text=f"{tag_str} {len(rows)} row(s) returned ({elapsed:.1f}ms)",
            text_color=theme.COLOR_HIGHLIGHT_GOLD if is_dry else theme.COLOR_STATUS_PASS,
        )

        if not columns:
            self.tree.configure(columns=["status"])
            self.tree.heading("status", text="Result")
            self.tree.column("status", width=400, anchor="w")
            self.tree.insert("", "end", values=[f"Query executed successfully. Affected rows: {row_cnt}"])
            return

        # Setup dynamic columns
        self.tree.configure(columns=columns)
        for col in columns:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=120, minwidth=60, anchor="w")

        # Insert rows
        for idx, r in enumerate(rows):
            stripe = "even_row" if idx % 2 == 0 else "odd_row"
            self.tree.insert("", "end", values=r, tags=(stripe,))
