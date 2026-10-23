"""
gui/tab_telemetry.py - Primary Telemetry Grid with Server-Side Pagination & CRUD
================================================================================
Part of the ORBITAL Mission Telemetry System.

Responsibilities:
  1. Server-side paginated grid (LIMIT/OFFSET) with ttk.Treeview dark styling.
  2. Multi-column parameterized filters (Search, Station, Sat, Mode, AI, Priority).
  3. Interactive column header sorting (▲/▼) with whitelist injection defense.
  4. Live database synchronization after every INSERT/UPDATE/DELETE transaction.
  5. Add/Edit dialogs with input validation and Bell-LaPadula write checks.
  6. Packet Inspector popup displaying all 24 telemetry attributes + JSON view.
  7. Filtered CSV export capability.
  8. RBAC and MAC dynamic button and row protection.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

import customtkinter as ctk

import db
import security
import theme
from models.telemetry_queries import (
    delete_telemetry_packet,
    export_telemetry_to_csv,
    fetch_packet_by_id,
    fetch_telemetry_page,
    get_filter_dropdown_options,
    insert_telemetry_packet,
    update_telemetry_packet,
)


class TelemetryTab(ctk.CTkFrame):
    """
    Main Telemetry Module View hosting the filter controls, paginated
    telemetry grid, server-side pagination bar, and CRUD operations.
    """

    def __init__(self, master: Any, user: security.UserSession, **kwargs):
        super().__init__(master, fg_color=theme.COLOR_BG_DARK, corner_radius=0, **kwargs)

        self.user = user

        # State Variables
        self.current_page: int = 1
        self.page_size: int = 50
        self.total_records: int = 0
        self.total_pages: int = 1
        self.sort_column: str = "timestamp_utc"
        self.sort_direction: str = "DESC"
        self.is_loading: bool = False

        # Preload filter options from DB
        try:
            self.filter_options = get_filter_dropdown_options()
        except Exception:
            self.filter_options = {
                "satellites": ["All", "SomaiyaSat", "SomaiyaPod"],
                "stations": ["All"],
                "comm_modes": ["All", "TT&C/Housekeeping", "SSTV", "M17", "Codec2"],
                "ai_decisions": ["All", "Direct-to-Ground", "Relay-via-SomaiyaPod", "Store-and-Forward"],
                "priorities": ["All", "Critical", "High", "Medium", "Low"],
                "classifications": ["All", "Restricted", "Internal", "Public"],
            }

        # Build UI
        self._init_ttk_styles()
        self._create_filter_toolbar()
        self._create_action_bar()
        self._create_treeview_grid()
        self._create_pagination_bar()

        # Load initial page
        self.reload_grid()

    # =========================================================================
    # 1. TREEVIEW STYLING (Dark Space Theme)
    # =========================================================================

    def _init_ttk_styles(self) -> None:
        """Configures ttk.Treeview theme to match Obsidian / Plum palette."""
        theme.init_ttk_styles(self)

    # =========================================================================
    # 2. FILTER TOOLBAR
    # =========================================================================

    def _create_filter_toolbar(self) -> None:
        """Constructs multi-field filter panel."""
        self.filter_card = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_PANEL_BG,
            corner_radius=10,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        self.filter_card.pack(fill="x", padx=10, pady=(10, 6))

        inner = ctk.CTkFrame(self.filter_card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)

        # Row 1: Search + Dropdowns
        r1 = ctk.CTkFrame(inner, fg_color="transparent")
        r1.pack(fill="x", pady=(0, 6))

        # Search Box
        ctk.CTkLabel(r1, text="🔍 Search:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(side="left", padx=(0, 4))
        self.search_entry = ctk.CTkEntry(
            r1,
            placeholder_text="Filter ID, Station, Mode, Phase...",
            width=220,
            height=28,
            font=theme.FONT_SMALL,
            fg_color=theme.COLOR_INPUT_BG,
            border_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
        )
        self.search_entry.pack(side="left", padx=(0, 12))
        self.search_entry.bind("<Return>", lambda e: self._on_filter_changed())

        # Satellite Dropdown
        ctk.CTkLabel(r1, text="Satellite:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(side="left", padx=(0, 4))
        self.sat_combo = ctk.CTkComboBox(
            r1,
            values=self.filter_options["satellites"],
            command=lambda v: self._on_filter_changed(),
            width=130,
            height=28,
            font=theme.FONT_SMALL,
            fg_color=theme.COLOR_INPUT_BG,
            border_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
            dropdown_fg_color=theme.COLOR_PANEL_BG,
        )
        self.sat_combo.set("All")
        self.sat_combo.pack(side="left", padx=(0, 12))

        # Station Dropdown
        ctk.CTkLabel(r1, text="Station:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(side="left", padx=(0, 4))
        self.station_combo = ctk.CTkComboBox(
            r1,
            values=self.filter_options["stations"],
            command=lambda v: self._on_filter_changed(),
            width=180,
            height=28,
            font=theme.FONT_SMALL,
            fg_color=theme.COLOR_INPUT_BG,
            border_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
            dropdown_fg_color=theme.COLOR_PANEL_BG,
        )
        self.station_combo.set("All")
        self.station_combo.pack(side="left", padx=(0, 12))

        # Comm Mode Dropdown
        ctk.CTkLabel(r1, text="Mode:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(side="left", padx=(0, 4))
        self.mode_combo = ctk.CTkComboBox(
            r1,
            values=self.filter_options["comm_modes"],
            command=lambda v: self._on_filter_changed(),
            width=140,
            height=28,
            font=theme.FONT_SMALL,
            fg_color=theme.COLOR_INPUT_BG,
            border_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
            dropdown_fg_color=theme.COLOR_PANEL_BG,
        )
        self.mode_combo.set("All")
        self.mode_combo.pack(side="left", padx=(0, 12))

        # AI Routing Decision
        ctk.CTkLabel(r1, text="AI Decision:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(side="left", padx=(0, 4))
        self.ai_combo = ctk.CTkComboBox(
            r1,
            values=self.filter_options["ai_decisions"],
            command=lambda v: self._on_filter_changed(),
            width=160,
            height=28,
            font=theme.FONT_SMALL,
            fg_color=theme.COLOR_INPUT_BG,
            border_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
            dropdown_fg_color=theme.COLOR_PANEL_BG,
        )
        self.ai_combo.set("All")
        self.ai_combo.pack(side="left", padx=(0, 12))

        # Priority Dropdown
        ctk.CTkLabel(r1, text="Priority:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(side="left", padx=(0, 4))
        self.priority_combo = ctk.CTkComboBox(
            r1,
            values=self.filter_options["priorities"],
            command=lambda v: self._on_filter_changed(),
            width=110,
            height=28,
            font=theme.FONT_SMALL,
            fg_color=theme.COLOR_INPUT_BG,
            border_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
            dropdown_fg_color=theme.COLOR_PANEL_BG,
        )
        self.priority_combo.set("All")
        self.priority_combo.pack(side="left", padx=(0, 12))

        # Clear Filters Button
        reset_btn = ctk.CTkButton(
            r1,
            text="↺ Reset",
            command=self._clear_all_filters,
            width=70,
            height=28,
            font=theme.FONT_SMALL,
            fg_color=theme.COLOR_INPUT_BG,
            hover_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_MUTED,
        )
        reset_btn.pack(side="right")

    def _get_active_filters(self) -> Dict[str, Any]:
        """Collects current filter form values."""
        return {
            "search": self.search_entry.get().strip(),
            "satellite_id": self.sat_combo.get(),
            "ground_station": self.station_combo.get(),
            "comm_mode": self.mode_combo.get(),
            "ai_routing_decision": self.ai_combo.get(),
            "packet_priority": self.priority_combo.get(),
        }

    def _on_filter_changed(self) -> None:
        """Resets to page 1 and reloads data when filters change."""
        self.current_page = 1
        self.reload_grid()

    def _clear_all_filters(self) -> None:
        """Clears all filter fields and reloads."""
        self.search_entry.delete(0, "end")
        self.sat_combo.set("All")
        self.station_combo.set("All")
        self.mode_combo.set("All")
        self.ai_combo.set("All")
        self.priority_combo.set("All")
        self.current_page = 1
        self.reload_grid()

    # =========================================================================
    # 3. ACTION TOOLBAR (Respects RBAC)
    # =========================================================================

    def _create_action_bar(self) -> None:
        """Constructs action buttons: Add, Edit, Delete, Inspect, Export, Refresh."""
        self.action_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.action_bar.pack(fill="x", padx=12, pady=(0, 6))

        # Add Button (Enabled if user.can('insert'))
        self.add_btn = ctk.CTkButton(
            self.action_bar,
            text="+ New Packet",
            command=self._open_add_dialog,
            state="normal" if self.user.can("insert") else "disabled",
            fg_color=theme.COLOR_ACCENT_LAVENDER if self.user.can("insert") else theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_BG_DARK if self.user.can("insert") else theme.COLOR_TEXT_DISABLED,
            hover_color=theme.COLOR_ACCENT_HOVER,
            font=theme.FONT_SMALL,
            width=110,
            height=30,
            corner_radius=6,
        )
        self.add_btn.pack(side="left", padx=(0, 6))

        # Edit Button (Enabled if user.can('update'))
        self.edit_btn = ctk.CTkButton(
            self.action_bar,
            text="✎ Edit",
            command=self._open_edit_dialog,
            state="normal" if self.user.can("update") else "disabled",
            fg_color=theme.COLOR_HIGHLIGHT_GOLD if self.user.can("update") else theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_BG_DARK if self.user.can("update") else theme.COLOR_TEXT_DISABLED,
            hover_color=theme.COLOR_GOLD_HOVER,
            font=theme.FONT_SMALL,
            width=90,
            height=30,
            corner_radius=6,
        )
        self.edit_btn.pack(side="left", padx=(0, 6))

        # Delete Button (Enabled if user.can('delete'))
        self.del_btn = ctk.CTkButton(
            self.action_bar,
            text="🗑 Delete",
            command=self._handle_delete_action,
            state="normal" if self.user.can("delete") else "disabled",
            fg_color=theme.COLOR_STATUS_FAIL if self.user.can("delete") else theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY if self.user.can("delete") else theme.COLOR_TEXT_DISABLED,
            hover_color="#8B1E2B",
            font=theme.FONT_SMALL,
            width=95,
            height=30,
            corner_radius=6,
        )
        self.del_btn.pack(side="left", padx=(0, 6))

        # Inspect Button (Always enabled)
        self.inspect_btn = ctk.CTkButton(
            self.action_bar,
            text="👁 Inspect",
            command=self._open_inspect_dialog,
            fg_color="#201D2C",
            hover_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
            font=theme.FONT_SMALL,
            width=100,
            height=30,
            corner_radius=6,
        )
        self.inspect_btn.pack(side="left", padx=(0, 6))

        # Export CSV Button (Enabled if user.can('export'))
        self.export_btn = ctk.CTkButton(
            self.action_bar,
            text="⤓ Export CSV",
            command=self._handle_export_csv,
            state="normal" if self.user.can("export") else "disabled",
            fg_color="#201D2C" if self.user.can("export") else theme.COLOR_PANEL_BORDER,
            hover_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY if self.user.can("export") else theme.COLOR_TEXT_DISABLED,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
            font=theme.FONT_SMALL,
            width=110,
            height=30,
            corner_radius=6,
        )
        self.export_btn.pack(side="left", padx=(0, 6))

        # Refresh Button
        self.refresh_btn = ctk.CTkButton(
            self.action_bar,
            text="🔄 Refresh",
            command=self.reload_grid,
            fg_color="transparent",
            hover_color="#201D2C",
            text_color=theme.COLOR_TEXT_MUTED,
            font=theme.FONT_SMALL,
            width=80,
            height=30,
            corner_radius=6,
        )
        self.refresh_btn.pack(side="right")

        # Loading / Status spinner indicator
        self.status_lbl = ctk.CTkLabel(
            self.action_bar,
            text="",
            font=theme.FONT_SMALL,
            text_color=theme.COLOR_HIGHLIGHT_GOLD,
        )
        self.status_lbl.pack(side="right", padx=12)

    # =========================================================================
    # 4. TELEMETRY TREEVIEW GRID
    # =========================================================================

    def _create_treeview_grid(self) -> None:
        """Constructs the Treeview table with scrollbars and column headers."""
        grid_container = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_PANEL_BG,
            corner_radius=10,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        grid_container.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # Table Column Definitions: (id, label, width, anchor)
        self.columns_def = [
            ("packet_id", "#ID", 65, "center"),
            ("timestamp_utc", "Timestamp (UTC)", 140, "center"),
            ("satellite_id", "Satellite", 95, "w"),
            ("ground_station", "Ground Station", 150, "w"),
            ("comm_mode", "Comm Mode", 120, "w"),
            ("orbit_number", "Orbit #", 65, "center"),
            ("battery_soc_percent", "SOC %", 65, "e"),
            ("onboard_temp_c", "Temp °C", 70, "e"),
            ("rssi_dbm", "RSSI (dBm)", 85, "e"),
            ("crc_valid", "CRC", 65, "center"),
            ("ai_routing_decision", "AI Routing", 140, "w"),
            ("packet_priority", "Priority", 80, "center"),
            ("classification", "Classification", 100, "center"),
        ]

        col_ids = [c[0] for c in self.columns_def]
        self.tree = ttk.Treeview(
            grid_container,
            columns=col_ids,
            show="headings",
            style="Telemetry.Treeview",
            selectmode="browse",
        )

        for col_id, label, width, anchor in self.columns_def:
            arrow = ""
            if col_id == self.sort_column:
                arrow = " ▲" if self.sort_direction == "ASC" else " ▼"
            self.tree.heading(
                col_id,
                text=f"{label}{arrow}",
                anchor=anchor,
                command=lambda c=col_id: self._on_column_header_click(c),
            )
            self.tree.column(col_id, width=width, minwidth=40, anchor=anchor)

        # Scrollbars
        vsb = ttk.Scrollbar(grid_container, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(grid_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew", padx=(2, 0), pady=(2, 0))
        vsb.grid(row=0, column=1, sticky="ns", pady=(2, 0), padx=(0, 2))
        hsb.grid(row=1, column=0, sticky="ew", padx=(2, 0), pady=(0, 2))

        grid_container.rowconfigure(0, weight=1)
        grid_container.columnconfigure(0, weight=1)

        # Double-click to inspect
        self.tree.bind("<Double-1>", lambda e: self._open_inspect_dialog())

        # Row Tags for Colored Classification and Status Styling
        self.tree.tag_configure("odd_row", background="#12111A")
        self.tree.tag_configure("even_row", background="#181622")
        self.tree.tag_configure("class_public", foreground=theme.COLOR_PILL_PUBLIC_FG)
        self.tree.tag_configure("class_internal", foreground=theme.COLOR_PILL_INTERNAL_FG)
        self.tree.tag_configure("class_restricted", foreground=theme.COLOR_PILL_RESTRICTED_FG)
        self.tree.tag_configure("priority_critical", foreground=theme.COLOR_STATUS_FAIL)

    def _on_column_header_click(self, col_id: str) -> None:
        """Toggles sort direction or switches sort column."""
        if self.sort_column == col_id:
            self.sort_direction = "DESC" if self.sort_direction == "ASC" else "ASC"
        else:
            self.sort_column = col_id
            self.sort_direction = "DESC"

        # Update column header arrow labels
        for cid, label, width, anchor in self.columns_def:
            arrow = ""
            if cid == self.sort_column:
                arrow = " ▲" if self.sort_direction == "ASC" else " ▼"
            self.tree.heading(cid, text=f"{label}{arrow}")

        self.current_page = 1
        self.reload_grid()

    # =========================================================================
    # 5. SERVER-SIDE PAGINATION BAR
    # =========================================================================

    def _create_pagination_bar(self) -> None:
        """Constructs pagination controls with row counts and page jumpers."""
        self.pag_card = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_PANEL_BG,
            corner_radius=10,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
            height=46,
        )
        self.pag_card.pack(fill="x", padx=10, pady=(0, 10))
        self.pag_card.pack_propagate(False)

        inner = ctk.CTkFrame(self.pag_card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=14)

        # Left: Record Counts Status
        self.count_lbl = ctk.CTkLabel(
            inner,
            text="Loading records...",
            font=theme.FONT_SMALL,
            text_color=theme.COLOR_TEXT_MUTED,
        )
        self.count_lbl.pack(side="left")

        # Center/Right: Navigation buttons
        nav_box = ctk.CTkFrame(inner, fg_color="transparent")
        nav_box.pack(side="right")

        # Page Size selector
        ctk.CTkLabel(nav_box, text="Rows per page:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(side="left", padx=(0, 4))
        self.page_size_combo = ctk.CTkComboBox(
            nav_box,
            values=["25", "50", "100", "200"],
            command=self._on_page_size_changed,
            width=70,
            height=26,
            font=theme.FONT_SMALL,
            fg_color=theme.COLOR_INPUT_BG,
            border_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
        )
        self.page_size_combo.set(str(self.page_size))
        self.page_size_combo.pack(side="left", padx=(0, 16))

        # First Page
        self.btn_first = ctk.CTkButton(
            nav_box, text="« First", width=55, height=26, font=theme.FONT_SMALL,
            command=lambda: self._go_to_page(1), fg_color="#201D2C", text_color=theme.COLOR_TEXT_PRIMARY
        )
        self.btn_first.pack(side="left", padx=2)

        # Prev Page
        self.btn_prev = ctk.CTkButton(
            nav_box, text="‹ Prev", width=55, height=26, font=theme.FONT_SMALL,
            command=lambda: self._go_to_page(self.current_page - 1), fg_color="#201D2C", text_color=theme.COLOR_TEXT_PRIMARY
        )
        self.btn_prev.pack(side="left", padx=2)

        # Page Indicator
        self.page_lbl = ctk.CTkLabel(
            nav_box,
            text="Page 1 of 1",
            font=theme.FONT_CODE_BOLD,
            text_color=theme.COLOR_HIGHLIGHT_GOLD,
            width=110,
        )
        self.page_lbl.pack(side="left", padx=6)

        # Next Page
        self.btn_next = ctk.CTkButton(
            nav_box, text="Next ›", width=55, height=26, font=theme.FONT_SMALL,
            command=lambda: self._go_to_page(self.current_page + 1), fg_color="#201D2C", text_color=theme.COLOR_TEXT_PRIMARY
        )
        self.btn_next.pack(side="left", padx=2)

        # Last Page
        self.btn_last = ctk.CTkButton(
            nav_box, text="Last »", width=55, height=26, font=theme.FONT_SMALL,
            command=lambda: self._go_to_page(self.total_pages), fg_color="#201D2C", text_color=theme.COLOR_TEXT_PRIMARY
        )
        self.btn_last.pack(side="left", padx=2)

    def _on_page_size_changed(self, choice: str) -> None:
        """Handles change in rows-per-page dropdown."""
        try:
            self.page_size = int(choice)
            self.current_page = 1
            self.reload_grid()
        except ValueError:
            pass

    def _go_to_page(self, page_num: int) -> None:
        """Navigates to a specific page number."""
        page_num = max(1, min(self.total_pages, page_num))
        if page_num != self.current_page:
            self.current_page = page_num
            self.reload_grid()

    # =========================================================================
    # 6. ASYNCHRONOUS DATA FETCHING & GRID RELOAD
    # =========================================================================

    def reload_grid(self) -> None:
        """
        Fetches the current page of records from PostgreSQL and updates the grid.
        Executes with responsive cursor state and immediate UI synchronization.
        """
        self.status_lbl.configure(text="Fetching from DB...")
        self.update_idletasks()

        filters = self._get_active_filters()
        try:
            rows, total_cnt = fetch_telemetry_page(
                user_session=self.user,
                page=self.current_page,
                page_size=self.page_size,
                sort_column=self.sort_column,
                sort_direction=self.sort_direction,
                filters=filters,
            )
            self._apply_grid_data(rows, total_cnt)
        except Exception as exc:
            self._on_fetch_error(str(exc))

    def _apply_grid_data(self, rows: List[Dict[str, Any]], total_records: int) -> None:
        """Populates the Treeview table with freshly loaded database rows."""
        self.is_loading = False
        self.status_lbl.configure(text="")
        self.total_records = total_records
        self.total_pages = max(1, (total_records + self.page_size - 1) // self.page_size)

        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Insert new rows with alternate striping and classification tag styling
        for idx, r in enumerate(rows):
            stripe_tag = "even_row" if idx % 2 == 0 else "odd_row"
            class_tag = f"class_{str(r['classification']).lower()}"
            priority_tag = "priority_critical" if r["packet_priority"] == "Critical" else ""

            row_tags = (stripe_tag, class_tag, priority_tag)

            values = (
                r["packet_id"],
                r["timestamp_utc"],
                r["satellite_id"],
                r["ground_station"],
                r["comm_mode"],
                r["orbit_number"],
                f"{r['battery_soc_percent']:.1f}%",
                f"{r['onboard_temp_c']:.1f}",
                f"{r['rssi_dbm']:.1f}",
                r["crc_valid"],
                r["ai_routing_decision"],
                r["packet_priority"],
                r["classification"],
            )

            self.tree.insert("", "end", iid=str(r["packet_id"]), values=values, tags=row_tags)

        # Update Pagination display labels
        start_idx = ((self.current_page - 1) * self.page_size) + 1 if total_records > 0 else 0
        end_idx = min(self.current_page * self.page_size, total_records)
        self.count_lbl.configure(
            text=f"Showing {start_idx:,} – {end_idx:,} of {total_records:,} packets  •  Bell-LaPadula MAC Active"
        )
        self.page_lbl.configure(text=f"Page {self.current_page} of {self.total_pages}")

        # Update button state
        self.btn_first.configure(state="normal" if self.current_page > 1 else "disabled")
        self.btn_prev.configure(state="normal" if self.current_page > 1 else "disabled")
        self.btn_next.configure(state="normal" if self.current_page < self.total_pages else "disabled")
        self.btn_last.configure(state="normal" if self.current_page < self.total_pages else "disabled")

    def _on_fetch_error(self, err_msg: str) -> None:
        """Handles query execution errors gracefully."""
        self.is_loading = False
        self.status_lbl.configure(text="Query Error")
        messagebox.showerror("Database Query Error", f"Failed to retrieve telemetry records:\n\n{err_msg}")

    # =========================================================================
    # 7. CRUD DIALOGS & ACTIONS
    # =========================================================================

    def _get_selected_packet_id(self) -> Optional[int]:
        """Returns the integer packet_id of the currently selected tree row."""
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Selection Required", "Please select a telemetry packet from the table first.")
            return None
        return int(sel[0])

    def _open_add_dialog(self) -> None:
        """Opens dialog to insert a new packet."""
        PacketFormDialog(
            parent=self.winfo_toplevel(),
            user_session=self.user,
            mode="add",
            filter_options=self.filter_options,
            on_success=self.reload_grid,
        )

    def _open_edit_dialog(self) -> None:
        """Opens dialog to edit the selected packet."""
        pkt_id = self._get_selected_packet_id()
        if pkt_id is None:
            return

        # Fetch current record
        pkt_data = fetch_packet_by_id(self.user, pkt_id)
        if not pkt_data:
            messagebox.showerror("Access Error", f"Unable to fetch packet #{pkt_id} under your security clearance.")
            return

        PacketFormDialog(
            parent=self.winfo_toplevel(),
            user_session=self.user,
            mode="edit",
            initial_data=pkt_data,
            filter_options=self.filter_options,
            on_success=self.reload_grid,
        )

    def _handle_delete_action(self) -> None:
        """Executes deletion or queues approval request."""
        pkt_id = self._get_selected_packet_id()
        if pkt_id is None:
            return

        if self.user.is_admin():
            confirm = messagebox.askyesno(
                "Confirm Deletion",
                f"Permanently DELETE packet #{pkt_id} from PostgreSQL?\n\nThis action will be logged in the immutable audit log.",
            )
        else:
            confirm = messagebox.askyesno(
                "Submit Deletion Request",
                f"Your role ({self.user.role_name}) requires Admin approval to delete telemetry.\n\n"
                f"Submit deletion request for packet #{pkt_id} to the Admin Approval Queue?",
            )

        if not confirm:
            return

        ok, msg = delete_telemetry_packet(self.user, pkt_id)
        if ok:
            messagebox.showinfo("Operation Successful", msg)
            self.reload_grid()
        else:
            messagebox.showerror("Operation Failed", msg)

    def _open_inspect_dialog(self) -> None:
        """Opens detailed 24-parameter inspector modal."""
        pkt_id = self._get_selected_packet_id()
        if pkt_id is None:
            return

        pkt_data = fetch_packet_by_id(self.user, pkt_id)
        if not pkt_data:
            messagebox.showerror("Access Error", f"Packet #{pkt_id} not accessible.")
            return

        PacketInspectorDialog(
            parent=self.winfo_toplevel(),
            user_session=self.user,
            packet_data=pkt_data,
            on_dac_grant_success=self.reload_grid,
        )

    def _handle_export_csv(self) -> None:
        """Exports currently filtered telemetry dataset to CSV asynchronously."""
        filters = self._get_active_filters()
        filepath = filedialog.asksaveasfilename(
            parent=self,
            title="Export Telemetry to CSV",
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            initialfile=f"somaiyasat_telemetry_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        if not filepath:
            return

        self.status_lbl.configure(text="Exporting CSV...")

        def export_task() -> None:
            ok, msg, count = export_telemetry_to_csv(self.user, filters, filepath)
            def on_done():
                self.status_lbl.configure(text="")
                if ok:
                    messagebox.showinfo("Export Complete", f"{msg}\nFile: {filepath}")
                else:
                    messagebox.showerror("Export Failed", msg)
            self.after(0, on_done)

        threading.Thread(target=export_task, daemon=True).start()


# =============================================================================
# 8. PACKET ADD / EDIT FORM DIALOG
# =============================================================================

class PacketFormDialog(ctk.CTkToplevel):
    """
    Modal form dialog supporting both INSERT and UPDATE operations.
    Enforces validation bounds and Bell-LaPadula *-Property constraints.
    """

    def __init__(
        self,
        parent: Any,
        user_session: security.UserSession,
        mode: str = "add",
        initial_data: Optional[Dict[str, Any]] = None,
        filter_options: Optional[Dict[str, Any]] = None,
        on_success: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)
        self.user = user_session
        self.mode = mode
        self.initial_data = initial_data or {}
        self.filter_options = filter_options or {}
        self.on_success = on_success

        title_text = "New Telemetry Packet" if mode == "add" else f"Edit Packet #{self.initial_data.get('packet_id')}"
        self.title(f"ORBITAL // {title_text}")
        self.geometry("780x640")
        self.minsize(740, 580)
        self.configure(fg_color=theme.COLOR_BG_DARK)

        self.grab_set()  # Make modal

        self._create_form_widgets()

        # Center dialog
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _create_form_widgets(self) -> None:
        """Builds multi-section scrollable parameter form."""
        header = ctk.CTkFrame(self, fg_color=theme.COLOR_PANEL_BG, corner_radius=0, height=50)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        title_lbl = ctk.CTkLabel(
            header,
            text=f"{'➕ Create Telemetry Packet' if self.mode == 'add' else '✎ Edit Telemetry Packet'}",
            font=theme.FONT_TITLE,
            text_color=theme.COLOR_ACCENT_LAVENDER,
        )
        title_lbl.pack(side="left", padx=20)

        # Form scroll area
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=12)

        # Section 1: Craft & Orbital Dynamics
        self._add_section_header(scroll, "1. SATELLITE & ORBIT DYNAMICS")
        f1 = self._add_grid_box(scroll)

        self.sat_var = self._add_dropdown(f1, 0, 0, "Satellite ID:", ["SomaiyaSat", "SomaiyaPod"], self.initial_data.get("satellite_id", "SomaiyaSat"))
        self.station_var = self._add_dropdown(f1, 0, 1, "Ground Station:", [s for s in self.filter_options.get("stations", []) if s != "All"], self.initial_data.get("ground_station", "Mumbai-VU2SOMAIYA"))
        self.phase_var = self._add_dropdown(f1, 1, 0, "Mission Phase:", ["Nominal Ops", "Safe Mode", "Commissioning", "Deployment"], self.initial_data.get("mission_phase", "Nominal Ops"))
        self.eclipse_var = self._add_dropdown(f1, 1, 1, "Eclipse Status:", ["Sunlit", "Eclipse"], self.initial_data.get("eclipse_status", "Sunlit"))

        self.orbit_entry = self._add_text_field(f1, 2, 0, "Orbit Number:", str(self.initial_data.get("orbit_number", "12")))
        self.alt_entry = self._add_text_field(f1, 2, 1, "Altitude (km):", str(self.initial_data.get("altitude_km", "545.20")))
        self.vel_entry = self._add_text_field(f1, 3, 0, "Velocity (km/s):", str(self.initial_data.get("orbital_velocity_kmps", "7.614")))
        self.temp_entry = self._add_text_field(f1, 3, 1, "Onboard Temp (°C):", str(self.initial_data.get("onboard_temp_c", "18.5")))

        # Section 2: Power Subsystem (EPS)
        self._add_section_header(scroll, "2. ELECTRICAL POWER SUBSYSTEM (EPS)")
        f2 = self._add_grid_box(scroll)

        self.volt_entry = self._add_text_field(f2, 0, 0, "Battery Voltage (V):", str(self.initial_data.get("battery_voltage_v", "4.05")))
        self.soc_entry = self._add_text_field(f2, 0, 1, "State of Charge (%):", str(self.initial_data.get("battery_soc_percent", "88.5")))
        self.solar_entry = self._add_text_field(f2, 1, 0, "Solar Current (mA):", str(self.initial_data.get("solar_current_ma", "420.0")))

        # Section 3: Radio Frequency & Payload Link
        self._add_section_header(scroll, "3. RF LINK & AMATEUR PAYLOAD")
        f3 = self._add_grid_box(scroll)

        self.mode_var = self._add_dropdown(f3, 0, 0, "Comm Mode:", ["TT&C/Housekeeping", "M17", "SSTV", "Codec2"], self.initial_data.get("comm_mode", "TT&C/Housekeeping"))
        self.crc_var = self._add_dropdown(f3, 0, 1, "CRC Status:", ["Pass", "Fail"], self.initial_data.get("crc_valid", "Pass"))
        self.rssi_entry = self._add_text_field(f3, 1, 0, "RSSI (dBm):", str(self.initial_data.get("rssi_dbm", "-98.5")))
        self.snr_entry = self._add_text_field(f3, 1, 1, "SNR (dB):", str(self.initial_data.get("snr_db", "14.2")))
        self.rate_entry = self._add_text_field(f3, 2, 0, "Data Rate (bps):", str(self.initial_data.get("data_rate_bps", "9600")))
        self.size_entry = self._add_text_field(f3, 2, 1, "Packet Size (bytes):", str(self.initial_data.get("packet_size_bytes", "256")))
        self.ber_entry = self._add_text_field(f3, 3, 0, "Bit Error Rate (BER):", str(self.initial_data.get("bit_error_rate", "0.0012")))

        # Section 4: AI Routing & Security Classification
        self._add_section_header(scroll, "4. AI ROUTING & DATA GOVERNANCE")
        f4 = self._add_grid_box(scroll)

        self.ai_var = self._add_dropdown(f4, 0, 0, "AI Routing Decision:", ["Direct-to-Ground", "Relay-via-SomaiyaPod", "Store-and-Forward"], self.initial_data.get("ai_routing_decision", "Direct-to-Ground"))
        self.ai_conf_entry = self._add_text_field(f4, 0, 1, "AI Confidence (0.0-1.0):", str(self.initial_data.get("ai_confidence_score", "0.850")))
        self.priority_var = self._add_dropdown(f4, 1, 0, "Packet Priority:", ["Low", "Medium", "High", "Critical"], self.initial_data.get("packet_priority", "Medium"))
        self.deploy_var = self._add_dropdown(f4, 1, 1, "Deployment Confirmed:", ["Yes", "No"], self.initial_data.get("deployment_confirmed", "Yes"))

        # Classification dropdown (Enforces Bell-LaPadula write constraint)
        self.class_var = self._add_dropdown(f4, 2, 0, "Classification:", ["Public", "Internal", "Restricted"], self.initial_data.get("classification", "Public"))

        # Footer Actions
        footer = ctk.CTkFrame(self, fg_color=theme.COLOR_PANEL_BG, corner_radius=0, height=56)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        save_btn = ctk.CTkButton(
            footer,
            text="💾 Commit to PostgreSQL",
            command=self._handle_save,
            fg_color=theme.COLOR_ACCENT_LAVENDER,
            hover_color=theme.COLOR_ACCENT_HOVER,
            text_color=theme.COLOR_BG_DARK,
            font=theme.FONT_BODY_BOLD,
            width=180,
            height=36,
        )
        save_btn.pack(side="right", padx=20, pady=10)

        cancel_btn = ctk.CTkButton(
            footer,
            text="Cancel",
            command=self.destroy,
            fg_color=theme.COLOR_INPUT_BG,
            hover_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_MUTED,
            width=90,
            height=36,
        )
        cancel_btn.pack(side="right", padx=(0, 8), pady=10)

    def _add_section_header(self, parent: Any, text: str) -> None:
        ctk.CTkLabel(parent, text=text, font=theme.FONT_SUBTITLE, text_color=theme.COLOR_HIGHLIGHT_GOLD).pack(anchor="w", pady=(10, 4))

    def _add_grid_box(self, parent: Any) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color=theme.COLOR_INPUT_BG, corner_radius=8, border_width=1, border_color=theme.COLOR_PANEL_BORDER)
        f.pack(fill="x", pady=(0, 10))
        f.columnconfigure((0, 1), weight=1)
        return f

    def _add_dropdown(self, parent: Any, row: int, col: int, label: str, values: List[str], current: str) -> ctk.StringVar:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid(row=row, column=col, padx=10, pady=6, sticky="ew")
        ctk.CTkLabel(wrap, text=label, font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
        var = ctk.StringVar(value=current if current in values else (values[0] if values else ""))
        combo = ctk.CTkComboBox(wrap, values=values, variable=var, fg_color=theme.COLOR_PANEL_BG, border_color=theme.COLOR_PANEL_BORDER, text_color=theme.COLOR_TEXT_PRIMARY)
        combo.pack(fill="x")
        return var

    def _add_text_field(self, parent: Any, row: int, col: int, label: str, current: str) -> ctk.CTkEntry:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid(row=row, column=col, padx=10, pady=6, sticky="ew")
        ctk.CTkLabel(wrap, text=label, font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
        entry = ctk.CTkEntry(wrap, fg_color=theme.COLOR_PANEL_BG, border_color=theme.COLOR_PANEL_BORDER, text_color=theme.COLOR_TEXT_PRIMARY)
        entry.insert(0, current)
        entry.pack(fill="x")
        return entry

    def _handle_save(self) -> None:
        """Validates input data and calls DAO insert or update."""
        try:
            data = {
                "satellite_id": self.sat_var.get(),
                "ground_station": self.station_var.get(),
                "mission_phase": self.phase_var.get(),
                "eclipse_status": self.eclipse_var.get(),
                "orbit_number": int(self.orbit_entry.get().strip()),
                "altitude_km": float(self.alt_entry.get().strip()),
                "orbital_velocity_kmps": float(self.vel_entry.get().strip()),
                "onboard_temp_c": float(self.temp_entry.get().strip()),
                "battery_voltage_v": float(self.volt_entry.get().strip()),
                "battery_soc_percent": float(self.soc_entry.get().strip()),
                "solar_current_ma": float(self.solar_entry.get().strip()),
                "comm_mode": self.mode_var.get(),
                "crc_valid": self.crc_var.get(),
                "rssi_dbm": float(self.rssi_entry.get().strip()),
                "snr_db": float(self.snr_entry.get().strip()),
                "data_rate_bps": int(self.rate_entry.get().strip()),
                "packet_size_bytes": int(self.size_entry.get().strip()),
                "bit_error_rate": float(self.ber_entry.get().strip()),
                "ai_routing_decision": self.ai_var.get(),
                "ai_confidence_score": float(self.ai_conf_entry.get().strip()),
                "packet_priority": self.priority_var.get(),
                "deployment_confirmed": self.deploy_var.get(),
                "classification": self.class_var.get(),
            }
        except ValueError as e:
            messagebox.showerror("Validation Error", f"Please check all numeric values:\n\n{e}")
            return

        # Physical limits and boundary validation
        if data["battery_soc_percent"] < 0.0 or data["battery_soc_percent"] > 100.0:
            messagebox.showerror("Validation Error", "Battery State of Charge (SOC) must be between 0.0% and 100.0%.")
            self.soc_entry.focus()
            return
        if data["battery_voltage_v"] < 2.0 or data["battery_voltage_v"] > 5.0:
            messagebox.showerror("Validation Error", "Battery Voltage must be within operational range (2.0V - 5.0V).")
            self.volt_entry.focus()
            return
        if data["solar_current_ma"] < 0.0:
            messagebox.showerror("Validation Error", "Solar Current cannot be negative.")
            self.solar_entry.focus()
            return
        if data["ai_confidence_score"] < 0.0 or data["ai_confidence_score"] > 1.0:
            messagebox.showerror("Validation Error", "AI Confidence Score must be between 0.0 and 1.0.")
            self.ai_conf_entry.focus()
            return
        if data["bit_error_rate"] < 0.0 or data["bit_error_rate"] > 1.0:
            messagebox.showerror("Validation Error", "Bit Error Rate must be between 0.0 and 1.0.")
            self.ber_entry.focus()
            return

        # Perform Insert or Update
        if self.mode == "add":
            ok, msg, new_id = insert_telemetry_packet(self.user, data)
        else:
            pkt_id = self.initial_data["packet_id"]
            ok, msg = update_telemetry_packet(self.user, pkt_id, data)

        if ok:
            messagebox.showinfo("Success", msg)
            if self.on_success:
                self.on_success()
            self.destroy()
        else:
            messagebox.showerror("Operation Failed", msg)


# =============================================================================
# 9. PACKET INSPECTOR POPUP DIALOG
# =============================================================================

class PacketInspectorDialog(ctk.CTkToplevel):
    """
    Detailed packet inspector showing all 24 attributes, JSON payload,
    and Discretionary Access Control (DAC) grant action.
    """

    def __init__(
        self,
        parent: Any,
        user_session: security.UserSession,
        packet_data: Dict[str, Any],
        on_dac_grant_success: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)
        self.user = user_session
        self.data = packet_data
        self.on_dac_grant_success = on_dac_grant_success

        pkt_id = packet_data.get("packet_id")
        self.title(f"ORBITAL // Telemetry Inspector — Packet #{pkt_id}")
        self.geometry("720x620")
        self.minsize(680, 560)
        self.configure(fg_color=theme.COLOR_BG_DARK)

        self.grab_set()

        self._build_ui()

        # Center dialog
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self) -> None:
        # Header
        top = ctk.CTkFrame(self, fg_color=theme.COLOR_PANEL_BG, corner_radius=0, height=56)
        top.pack(fill="x")
        top.pack_propagate(False)

        pkt_id = self.data.get("packet_id")
        ctk.CTkLabel(
            top,
            text=f"🛰️ Telemetry Packet #{pkt_id}  [{self.data.get('satellite_id')}]",
            font=theme.FONT_TITLE,
            text_color=theme.COLOR_TEXT_PRIMARY,
        ).pack(side="left", padx=20)

        # Classification badge
        bg_col, fg_col = theme.get_classification_colors(self.data.get("classification", "Public"))
        pill = ctk.CTkFrame(top, fg_color=bg_col, corner_radius=8)
        pill.pack(side="right", padx=20)
        ctk.CTkLabel(pill, text=self.data.get("classification", "").upper(), font=(theme.FONT_FAMILY, 9, "bold"), text_color=fg_col).pack(padx=10, pady=3)

        # Tabs: Structured Specs vs Raw JSON
        tabview = ctk.CTkTabview(self, fg_color=theme.COLOR_PANEL_BG)
        tabview.pack(fill="both", expand=True, padx=16, pady=10)

        t_specs = tabview.add("Technical Parameters")
        t_json = tabview.add("Raw JSON Payload")

        # Specifications Layout
        scroll = ctk.CTkScrollableFrame(t_specs, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=6, pady=6)

        specs_groups = [
            ("FLIGHT DYNAMICS", [
                ("Timestamp (UTC)", str(self.data.get("timestamp_utc"))),
                ("Mission Phase", str(self.data.get("mission_phase"))),
                ("Orbit Number", str(self.data.get("orbit_number"))),
                ("Altitude", f"{self.data.get('altitude_km')} km"),
                ("Orbital Velocity", f"{self.data.get('orbital_velocity_kmps')} km/s"),
                ("Eclipse Status", str(self.data.get("eclipse_status"))),
            ]),
            ("ELECTRICAL POWER & THERMAL (EPS)", [
                ("Battery Voltage", f"{self.data.get('battery_voltage_v')} V"),
                ("State of Charge", f"{self.data.get('battery_soc_percent')} %"),
                ("Solar Current", f"{self.data.get('solar_current_ma')} mA"),
                ("Onboard Temp", f"{self.data.get('onboard_temp_c')} °C"),
            ]),
            ("COMMUNICATIONS & RF LINK", [
                ("Ground Station", str(self.data.get("ground_station"))),
                ("Comm Mode", str(self.data.get("comm_mode"))),
                ("RSSI", f"{self.data.get('rssi_dbm')} dBm"),
                ("SNR", f"{self.data.get('snr_db')} dB"),
                ("Data Rate", f"{self.data.get('data_rate_bps')} bps"),
                ("Packet Size", f"{self.data.get('packet_size_bytes')} bytes"),
                ("Bit Error Rate", str(self.data.get("bit_error_rate"))),
                ("CRC Check", str(self.data.get("crc_valid"))),
            ]),
            ("AI ROUTING & GOVERNANCE", [
                ("AI Decision", str(self.data.get("ai_routing_decision"))),
                ("AI Confidence", f"{float(self.data.get('ai_confidence_score', 0))*100:.1f} %"),
                ("Deployment Confirmed", str(self.data.get("deployment_confirmed"))),
                ("Packet Priority", str(self.data.get("packet_priority"))),
                ("Record Owner", str(self.data.get("owner_username"))),
            ]),
        ]

        for g_title, g_items in specs_groups:
            ctk.CTkLabel(scroll, text=g_title, font=theme.FONT_SMALL, text_color=theme.COLOR_HIGHLIGHT_GOLD).pack(anchor="w", pady=(10, 2))
            box = ctk.CTkFrame(scroll, fg_color=theme.COLOR_INPUT_BG, corner_radius=8, border_width=1, border_color=theme.COLOR_PANEL_BORDER)
            box.pack(fill="x", pady=(0, 6))

            for k, v in g_items:
                row = ctk.CTkFrame(box, fg_color="transparent")
                row.pack(fill="x", padx=12, pady=3)
                ctk.CTkLabel(row, text=k, font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED, width=170, anchor="w").pack(side="left")
                ctk.CTkLabel(row, text=v, font=theme.FONT_CODE_BOLD, text_color=theme.COLOR_TEXT_PRIMARY, anchor="w").pack(side="left")

        # JSON Tab
        json_box = ctk.CTkTextbox(t_json, fg_color=theme.COLOR_INPUT_BG, text_color=theme.COLOR_TEXT_PRIMARY, font=theme.FONT_CODE)
        json_box.pack(fill="both", expand=True, padx=6, pady=6)
        clean_dict = {k: (str(v) if isinstance(v, datetime) else v) for k, v in self.data.items()}
        json_box.insert("1.0", json.dumps(clean_dict, indent=2))

        # Bottom Bar with DAC Grant button
        bottom = ctk.CTkFrame(self, fg_color=theme.COLOR_PANEL_BG, corner_radius=0, height=50)
        bottom.pack(fill="x", side="bottom")
        bottom.pack_propagate(False)

        # DAC Grant Button (Available to Admin or Record Owner)
        is_owner = self.data.get("owner_username") == self.user.username
        if self.user.is_admin() or is_owner:
            dac_btn = ctk.CTkButton(
                bottom,
                text="🔑 Issue DAC Grant",
                command=self._open_dac_grant_dialog,
                fg_color=theme.COLOR_HIGHLIGHT_GOLD,
                hover_color=theme.COLOR_GOLD_HOVER,
                text_color=theme.COLOR_BG_DARK,
                font=theme.FONT_SMALL,
                height=30,
            )
            dac_btn.pack(side="left", padx=16, pady=10)

        close_btn = ctk.CTkButton(
            bottom,
            text="Close",
            command=self.destroy,
            width=80,
            height=30,
            font=theme.FONT_SMALL,
            fg_color=theme.COLOR_INPUT_BG,
            hover_color=theme.COLOR_PANEL_BORDER,
        )
        close_btn.pack(side="right", padx=16, pady=10)

    def _open_dac_grant_dialog(self) -> None:
        """Opens prompt to grant discretionary read access to another user."""
        dialog = ctk.CTkInputDialog(
            text=f"Enter the username to grant SELECT access to packet #{self.data.get('packet_id')}:",
            title="Issue Discretionary Access (DAC) Grant",
        )
        grantee = dialog.get_input()
        if not grantee:
            return

        ok, msg = security.grant_dac_permission(
            granter=self.user,
            grantee_username=grantee.strip(),
            target_type="row",
            permission="SELECT",
            packet_id=self.data.get("packet_id"),
        )
        if ok:
            messagebox.showinfo("DAC Grant Issued", msg)
            if self.on_dac_grant_success:
                self.on_dac_grant_success()
        else:
            messagebox.showerror("DAC Grant Failed", msg)
