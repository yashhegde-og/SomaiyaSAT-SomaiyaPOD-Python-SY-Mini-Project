"""
gui/tab_power_rf.py - Electrical Power Subsystem (EPS) & RF Link Analytics
==========================================================================
Part of the ORBITAL Mission Telemetry System.

Responsibilities:
  1. Top Mission KPI Summary Cards:
     - Total Packets
     - CRC Pass Rate %
     - Average Bit Error Rate (BER)
     - Average Battery State of Charge (SOC %)
     - Deployment Confirmed Rate %
  2. Four Embedded Dark-Themed Matplotlib Charts:
     - Chart 1: Battery SOC in Eclipse vs Sunlit (Distribution Comparison)
     - Chart 2: RF Link Budget Scatter (RSSI vs SNR by Comm Mode)
     - Chart 3: Top Receiving Ground Stations (Bar Chart)
     - Chart 4: RF Comm Mode Usage Breakdown (Donut Chart)
  3. Interactive Saved Telemetry Anomaly Queries Console:
     - Predefined mission queries executed inside parameterized queries
     - Live result display in a dark ttk.Treeview with CSV export
"""

from __future__ import annotations

import csv
import threading
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

import customtkinter as ctk
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import security
import theme
from models import analytics_queries


class PowerRFAnalyticsTab(ctk.CTkFrame):
    """
    Comprehensive Power & RF Subsystem Dashboard with dark-themed
    embedded Matplotlib analytics and saved anomaly queries.
    """

    def __init__(self, master: Any, user: security.UserSession, **kwargs):
        super().__init__(master, fg_color=theme.COLOR_BG_DARK, corner_radius=0, **kwargs)
        self.user = user

        # Scrollable container hosting KPIs, Charts & Saved Queries
        self.scroll_container = ctk.CTkScrollableFrame(
            self,
            fg_color=theme.COLOR_PANEL_BG,
            corner_radius=12,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        self.scroll_container.pack(fill="both", expand=True, padx=8, pady=8)

        self._create_header_and_kpis()
        self._create_charts_section()
        self._create_saved_queries_section()

        # Load initial metrics and charts in background thread
        self.after(100, self._load_data_async)

    # =========================================================================
    # 1. KPI CARDS SECTION
    # =========================================================================

    def _create_header_and_kpis(self) -> None:
        """Header title and 5 prominent mission telemetry KPI cards."""
        top_bar = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        top_bar.pack(fill="x", padx=16, pady=(14, 10))

        title = ctk.CTkLabel(
            top_bar,
            text="⚡ Electrical Power (EPS) & RF Link Budget Analytics",
            font=theme.FONT_TITLE,
            text_color=theme.COLOR_TEXT_PRIMARY,
        )
        title.pack(side="left")

        refresh_btn = ctk.CTkButton(
            top_bar,
            text="🔄 Refresh Metrics",
            command=self._load_data_async,
            width=130,
            height=30,
            font=theme.FONT_SMALL_BOLD,
            fg_color=theme.COLOR_INPUT_BG,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
            hover_color=theme.COLOR_ACCENT_LAVENDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
        )
        refresh_btn.pack(side="right")

        # KPI Cards Container
        self.kpi_frame = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        self.kpi_frame.pack(fill="x", padx=16, pady=(0, 14))
        self.kpi_frame.columnconfigure((0, 1, 2, 3, 4), weight=1)

        self.kpi_cards: Dict[str, Tuple[ctk.CTkLabel, ctk.CTkLabel]] = {}
        specs = [
            ("total_packets", "TOTAL PACKETS", "📡", "Loading...", theme.COLOR_TEXT_PRIMARY),
            ("crc_pass_rate", "CRC PASS RATE", "🛡️", "Loading...", theme.COLOR_STATUS_PASS),
            ("avg_ber", "AVG BIT ERROR (BER)", "📊", "Loading...", theme.COLOR_HIGHLIGHT_GOLD),
            ("avg_battery_soc", "AVG BATTERY SOC", "🔋", "Loading...", theme.COLOR_ACCENT_LAVENDER),
            ("deployment_rate", "DEPLOY CONFIRMED", "🛰️", "Loading...", theme.COLOR_STATUS_PASS),
        ]

        for idx, (key, title_text, icon, initial_val, val_color) in enumerate(specs):
            card = ctk.CTkFrame(
                self.kpi_frame,
                fg_color=theme.COLOR_INPUT_BG,
                corner_radius=10,
                border_width=1,
                border_color=theme.COLOR_PANEL_BORDER,
            )
            card.grid(row=0, column=idx, padx=5, pady=4, sticky="nsew")

            t_lbl = ctk.CTkLabel(
                card,
                text=f"{icon}  {title_text}",
                font=theme.FONT_SMALL,
                text_color=theme.COLOR_TEXT_MUTED,
            )
            t_lbl.pack(anchor="w", padx=12, pady=(10, 2))

            v_lbl = ctk.CTkLabel(
                card,
                text=initial_val,
                font=theme.FONT_TITLE_LARGE,
                text_color=val_color,
            )
            v_lbl.pack(anchor="w", padx=12, pady=(0, 10))

            self.kpi_cards[key] = (t_lbl, v_lbl)

    def _update_kpi_ui(self, metrics: Dict[str, Any]) -> None:
        """Updates KPI card labels on main thread."""
        self.kpi_cards["total_packets"][1].configure(text=f"{metrics.get('total_packets', 0):,}")
        self.kpi_cards["crc_pass_rate"][1].configure(text=f"{metrics.get('crc_pass_rate', 0.0):.1f}%")
        self.kpi_cards["avg_ber"][1].configure(text=str(metrics.get("avg_ber", "0.000")))
        self.kpi_cards["avg_battery_soc"][1].configure(text=f"{metrics.get('avg_battery_soc', 0.0):.1f}%")
        self.kpi_cards["deployment_rate"][1].configure(text=f"{metrics.get('deployment_rate', 0.0):.1f}%")

    # =========================================================================
    # 2. CHARTS SECTION (MATPLOTLIB EMBEDDED)
    # =========================================================================

    def _create_charts_section(self) -> None:
        """Creates container for 4 dark-themed Matplotlib figures."""
        section_box = ctk.CTkFrame(
            self.scroll_container,
            fg_color=theme.COLOR_INPUT_BG,
            corner_radius=10,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        section_box.pack(fill="x", padx=16, pady=10)

        ctk.CTkLabel(
            section_box,
            text="📈 Subsystem Telemetry Visualizations (Dark-Themed Matplotlib Canvas)",
            font=theme.FONT_SUBTITLE,
            text_color=theme.COLOR_ACCENT_LAVENDER,
        ).pack(anchor="w", padx=16, pady=(12, 6))

        # Canvas frame for matplotlib figure
        self.charts_canvas_frame = ctk.CTkFrame(section_box, fg_color="transparent")
        self.charts_canvas_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _render_matplotlib_figures(
        self,
        station_df: pd.DataFrame,
        comm_df: pd.DataFrame,
        eclipse_vals: np.ndarray,
        sunlit_vals: np.ndarray,
        rf_df: pd.DataFrame,
    ) -> None:
        """
        Builds a 2x2 grid of Matplotlib charts styled with Obsidian & Lavender dark palette.
        Runs on main thread after data query finishes.
        """
        for child in self.charts_canvas_frame.winfo_children():
            child.destroy()

        plt.close("all")

        # Dark theme styling configuration
        bg_color = "#100E17"
        text_color = "#F3F0FA"
        muted_color = "#B8B4C7"
        grid_color = "#2B283A"

        fig, axs = plt.subplots(2, 2, figsize=(11.5, 7.8), facecolor=bg_color)
        fig.subplots_adjust(hspace=0.38, wspace=0.28, left=0.08, right=0.96, top=0.93, bottom=0.09)

        # ---------------------------------------------------------------------
        # Chart 1: Battery SOC in Eclipse vs Sunlit (Density / Boxplot)
        # ---------------------------------------------------------------------
        ax1 = axs[0, 0]
        ax1.set_facecolor(bg_color)
        ax1.grid(True, linestyle="--", alpha=0.3, color=grid_color)

        data_to_plot = [eclipse_vals, sunlit_vals] if len(eclipse_vals) and len(sunlit_vals) else [[50], [80]]
        bplot = ax1.boxplot(
            data_to_plot,
            patch_artist=True,
            tick_labels=["Eclipse", "Sunlit"],
            widths=0.45,
            medianprops=dict(color="#D5B16D", linewidth=2.0),
            whiskerprops=dict(color=muted_color),
            capprops=dict(color=muted_color),
            flierprops=dict(marker="o", color=muted_color, markersize=3, alpha=0.3),
        )

        colors = ["#7C3AED", "#10B981"]
        for patch, col in zip(bplot["boxes"], colors):
            patch.set_facecolor(col)
            patch.set_alpha(0.65)
            patch.set_edgecolor("#A78BFA")

        ax1.set_title("Battery SOC %: Eclipse vs Sunlit Pass", color=text_color, fontsize=10, fontweight="bold")
        ax1.set_ylabel("State of Charge (%)", color=muted_color, fontsize=9)
        ax1.tick_params(colors=muted_color, labelsize=8)
        for spine in ax1.spines.values():
            spine.set_color(grid_color)

        # ---------------------------------------------------------------------
        # Chart 2: RF Link Budget Scatter (RSSI vs SNR)
        # ---------------------------------------------------------------------
        ax2 = axs[0, 1]
        ax2.set_facecolor(bg_color)
        ax2.grid(True, linestyle="--", alpha=0.3, color=grid_color)

        mode_colors = {
            "M17": "#A78BFA",
            "Codec2": "#D5B16D",
            "SSTV": "#38BDF8",
            "TT&C/Housekeeping": "#10B981",
        }

        if not rf_df.empty:
            for mode, grp in rf_df.groupby("comm_mode"):
                ax2.scatter(
                    grp["rssi_dbm"],
                    grp["snr_db"],
                    s=14,
                    alpha=0.6,
                    label=str(mode),
                    color=mode_colors.get(str(mode), "#E2E8F0"),
                    edgecolors="none",
                )

        ax2.set_title("RF Link Budget (RSSI vs SNR)", color=text_color, fontsize=10, fontweight="bold")
        ax2.set_xlabel("RSSI (dBm)", color=muted_color, fontsize=9)
        ax2.set_ylabel("SNR (dB)", color=muted_color, fontsize=9)
        ax2.tick_params(colors=muted_color, labelsize=8)
        legend = ax2.legend(facecolor="#191722", edgecolor=grid_color, fontsize=7.5, labelcolor=text_color)
        legend.get_frame().set_alpha(0.8)
        for spine in ax2.spines.values():
            spine.set_color(grid_color)

        # ---------------------------------------------------------------------
        # Chart 3: Top Receiving Ground Stations
        # ---------------------------------------------------------------------
        ax3 = axs[1, 0]
        ax3.set_facecolor(bg_color)
        ax3.grid(True, linestyle="--", alpha=0.3, color=grid_color, axis="x")

        if not station_df.empty:
            top_st = station_df.head(8).iloc[::-1]
            # Simplify station labels for display
            clean_names = [s.split("-")[0] for s in top_st["ground_station"]]
            bars = ax3.barh(clean_names, top_st["packet_count"], color="#A78BFA", alpha=0.75, height=0.65)
            # Highlight Mumbai station
            for idx, name in enumerate(top_st["ground_station"]):
                if "Mumbai" in name:
                    bars[idx].set_color("#D5B16D")
                    bars[idx].set_alpha(0.9)

        ax3.set_title("Packets by Ground Station (Top 8)", color=text_color, fontsize=10, fontweight="bold")
        ax3.set_xlabel("Packets Received", color=muted_color, fontsize=9)
        ax3.tick_params(colors=muted_color, labelsize=8)
        for spine in ax3.spines.values():
            spine.set_color(grid_color)

        # ---------------------------------------------------------------------
        # Chart 4: Comm Mode Usage Breakdown (Donut)
        # ---------------------------------------------------------------------
        ax4 = axs[1, 1]
        ax4.set_facecolor(bg_color)

        if not comm_df.empty:
            palette = ["#A78BFA", "#D5B16D", "#38BDF8", "#10B981"]
            wedges, texts, autotexts = ax4.pie(
                comm_df["packet_count"],
                labels=comm_df["comm_mode"],
                autopct="%1.1f%%",
                startangle=140,
                colors=palette[: len(comm_df)],
                wedgeprops=dict(width=0.45, edgecolor=bg_color, linewidth=2),
                textprops=dict(color=muted_color, fontsize=7.5),
            )
            for autotext in autotexts:
                autotext.set_color("#FFFFFF")
                autotext.set_fontsize(7.5)
                autotext.set_weight("bold")

        ax4.set_title("RF Comm Mode Distribution", color=text_color, fontsize=10, fontweight="bold")

        # Embed into CustomTkinter via FigureCanvasTkAgg
        canvas = FigureCanvasTkAgg(fig, master=self.charts_canvas_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    # =========================================================================
    # 3. SAVED MISSION ANOMALY QUERIES
    # =========================================================================

    def _create_saved_queries_section(self) -> None:
        """Interactive console to run predefined telemetry anomaly queries."""
        container = ctk.CTkFrame(
            self.scroll_container,
            fg_color=theme.COLOR_INPUT_BG,
            corner_radius=10,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        container.pack(fill="x", padx=16, pady=(10, 20))

        title_row = ctk.CTkFrame(container, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(
            title_row,
            text="🔍 Saved Telemetry Mission Anomaly Queries (PostgreSQL Parameterized)",
            font=theme.FONT_SUBTITLE,
            text_color=theme.COLOR_HIGHLIGHT_GOLD,
        ).pack(side="left")

        # Query Selector & Controls
        ctrl_row = ctk.CTkFrame(container, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=16, pady=(0, 10))

        self.query_keys = list(analytics_queries.SAVED_MISSION_QUERIES.keys())
        query_titles = [analytics_queries.SAVED_MISSION_QUERIES[k]["title"] for k in self.query_keys]

        self.query_var = ctk.StringVar(value=query_titles[0])
        self.query_dropdown = ctk.CTkOptionMenu(
            ctrl_row,
            variable=self.query_var,
            values=query_titles,
            width=420,
            height=32,
            font=theme.FONT_SMALL,
            fg_color=theme.COLOR_PANEL_BG,
            button_color=theme.COLOR_ACCENT_LAVENDER,
            button_hover_color=theme.COLOR_ACCENT_HOVER,
            text_color=theme.COLOR_TEXT_PRIMARY,
            dropdown_fg_color=theme.COLOR_PANEL_BG,
            dropdown_text_color=theme.COLOR_TEXT_PRIMARY,
        )
        self.query_dropdown.pack(side="left", padx=(0, 10))

        run_btn = ctk.CTkButton(
            ctrl_row,
            text="▶ Execute Saved Query",
            command=self._execute_selected_query,
            width=160,
            height=32,
            font=theme.FONT_SMALL_BOLD,
            fg_color=theme.COLOR_ACCENT_LAVENDER,
            hover_color=theme.COLOR_ACCENT_HOVER,
            text_color=theme.COLOR_BG_DARK,
        )
        run_btn.pack(side="left", padx=(0, 10))

        export_btn = ctk.CTkButton(
            ctrl_row,
            text="📥 Export to CSV",
            command=self._export_query_results,
            width=120,
            height=32,
            font=theme.FONT_SMALL_BOLD,
            fg_color=theme.COLOR_PANEL_BG,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
            hover_color="#2B283A",
            text_color=theme.COLOR_TEXT_PRIMARY,
        )
        export_btn.pack(side="left")

        self.query_status_lbl = ctk.CTkLabel(
            ctrl_row,
            text="",
            font=theme.FONT_SMALL,
            text_color=theme.COLOR_TEXT_MUTED,
        )
        self.query_status_lbl.pack(side="right", padx=10)

        # Results Treeview Table
        tree_frame = ctk.CTkFrame(container, fg_color=theme.COLOR_PANEL_BG, corner_radius=8)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.last_query_columns: List[str] = []
        self.last_query_rows: List[List[Any]] = []

        self.query_tree = ttk.Treeview(tree_frame, selectmode="browse", height=8)
        scroll_y = ttk.Scrollbar(tree_frame, orient="vertical", command=self.query_tree.yview)
        scroll_x = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.query_tree.xview)
        self.query_tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        self.query_tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

    def _execute_selected_query(self) -> None:
        """Executes selected predefined query and displays results."""
        selected_title = self.query_var.get()
        target_key = None
        for k, v in analytics_queries.SAVED_MISSION_QUERIES.items():
            if v["title"] == selected_title:
                target_key = k
                break

        if not target_key:
            return

        self.query_status_lbl.configure(text="Executing query in PostgreSQL...", text_color=theme.COLOR_ACCENT_LAVENDER)

        def worker():
            try:
                cols, rows = analytics_queries.execute_saved_query(self.user, target_key)
                self.after(0, lambda: self._populate_query_tree(cols, rows))
            except Exception as exc:
                self.after(0, lambda: self.query_status_lbl.configure(text=f"Error: {exc}", text_color=theme.COLOR_STATUS_FAIL))

        threading.Thread(target=worker, daemon=True).start()

    def _populate_query_tree(self, cols: List[str], rows: List[List[Any]]) -> None:
        """Updates Treeview columns and items."""
        self.last_query_columns = cols
        self.last_query_rows = rows

        self.query_tree.delete(*self.query_tree.get_children())
        self.query_tree["columns"] = cols
        self.query_tree["show"] = "headings"

        for col in cols:
            self.query_tree.heading(col, text=col)
            self.query_tree.column(col, width=120, anchor="center")

        for r in rows:
            clean_row = [str(val) for val in r]
            self.query_tree.insert("", "end", values=clean_row)

        self.query_status_lbl.configure(
            text=f"Found {len(rows)} matching anomaly records.",
            text_color=theme.COLOR_STATUS_PASS,
        )

    def _export_query_results(self) -> None:
        """Exports currently loaded query records to a local CSV file."""
        if not self.last_query_rows:
            messagebox.showinfo("Export CSV", "No query results to export. Run a query first.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile="mission_anomaly_export.csv",
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(self.last_query_columns)
                writer.writerows(self.last_query_rows)
            messagebox.showinfo("Export Successful", f"Exported {len(self.last_query_rows)} records to:\n{file_path}")
        except Exception as exc:
            messagebox.showerror("Export Failed", f"Unable to write CSV: {exc}")

    # =========================================================================
    # 4. BACKGROUND DATA LOADER
    # =========================================================================

    def _load_data_async(self) -> None:
        """Fetches KPIs and chart datasets in a background thread to keep GUI responsive."""
        def worker():
            try:
                kpis = analytics_queries.fetch_kpi_metrics(self.user)
                station_df = analytics_queries.fetch_station_distribution(self.user)
                comm_df = analytics_queries.fetch_comm_mode_distribution(self.user)
                eclipse_vals, sunlit_vals = analytics_queries.fetch_battery_eclipse_data(self.user)
                rf_df = analytics_queries.fetch_rf_link_scatter_data(self.user)

                self.after(0, lambda: self._update_kpi_ui(kpis))
                self.after(
                    0,
                    lambda: self._render_matplotlib_figures(
                        station_df, comm_df, eclipse_vals, sunlit_vals, rf_df
                    ),
                )
            except Exception as exc:
                print(f"[!] Analytics load error: {exc}")

        threading.Thread(target=worker, daemon=True).start()
