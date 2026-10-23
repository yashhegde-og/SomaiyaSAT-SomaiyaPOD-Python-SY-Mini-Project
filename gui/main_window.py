"""
gui/main_window.py - Primary ORBITAL Mission Control Application Shell
=====================================================================
Part of the ORBITAL Mission Telemetry System.

Replicates the Next.js / Tailwind Phase 7 Mission Control Workspace:
  - Header Status bar with live dual-clock (UTC + IST), satellite status,
    logged-in operator profile chip, role pill, and Bell-LaPadula clearance badge.
  - Floating Bottom Mission Dock matching MissionDock.tsx:
    [📡 Telemetry] [🌍 Stations] [🧠 AI Routing] [⚡ Power & RF] [🛠 Workbench] [🛡️ Security]
  - Responsive workspace frame with live PostgreSQL queries and RBAC button control.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import customtkinter as ctk

import db
import security
import theme
from gui.tab_ai_routing import AIRoutingAnalyticsTab
from gui.tab_mission_home import MissionHomeTab
from gui.tab_power_rf import PowerRFAnalyticsTab
from gui.tab_security import SecurityTab
from gui.tab_stations import StationsTab
from gui.tab_telemetry import TelemetryTab
from gui.tab_workbench import WorkbenchTab


class MainWorkspaceView(ctk.CTkFrame):
    """
    Main Mission Control Workspace Frame containing Header Bar,
    dynamic tab container, and the floating bottom mission dock.
    """

    def __init__(
        self,
        master: Any,
        user: security.UserSession,
        on_logout: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(master, fg_color=theme.COLOR_BG_DARK, corner_radius=0, **kwargs)

        self.user = user
        self.on_logout = on_logout
        self.current_tab: str = "home"
        self._clock_running = True
        self._clock_timer_id: Optional[str] = None

        # Build Main Shell Layout: Header (top), Dock (bottom), Workspace (fill center)
        self._create_header_bar()
        self._create_floating_mission_dock()
        self._create_workspace_container()

        # Start live synchronized clock
        self._update_live_clock()

        # Load initial tab
        self.switch_tab("home")

    # =========================================================================
    # 1. HEADER STATUS BAR (Matching HeaderStatus.tsx)
    # =========================================================================

    def _create_header_bar(self) -> None:
        """Constructs the mission header bar with dual clock and operator badge."""
        self.header = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_PANEL_BG,
            corner_radius=0,
            height=60,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        self.header.pack(fill="x", side="top")
        self.header.pack_propagate(False)

        # Left: App Brand & Mission Status
        left_box = ctk.CTkFrame(self.header, fg_color="transparent")
        left_box.pack(side="left", padx=20, fill="y")

        brand_lbl = ctk.CTkLabel(
            left_box,
            text="🛰️ ORBITAL",
            font=theme.FONT_TITLE,
            text_color=theme.COLOR_ACCENT_LAVENDER,
        )
        brand_lbl.pack(side="left", padx=(0, 10))

        # Orbit status pill
        orbit_pill = ctk.CTkFrame(left_box, fg_color="#10251C", corner_radius=10)
        orbit_pill.pack(side="left", padx=(0, 10), pady=16)
        orbit_lbl = ctk.CTkLabel(
            orbit_pill,
            text="● NOMINAL OPS  |  545 km LEO",
            font=(theme.FONT_FAMILY, 9, "bold"),
            text_color=theme.COLOR_STATUS_PASS,
        )
        orbit_lbl.pack(padx=10, pady=2)

        # Center: Live Mission Clocks (UTC + IST)
        center_box = ctk.CTkFrame(self.header, fg_color="transparent")
        center_box.pack(side="left", expand=True, fill="both")

        self.clock_lbl = ctk.CTkLabel(
            center_box,
            text="",
            font=theme.FONT_CODE_BOLD,
            text_color=theme.COLOR_TEXT_PRIMARY,
        )
        self.clock_lbl.pack(expand=True)

        # Right: User Chip & Security Clearance Badge
        right_box = ctk.CTkFrame(self.header, fg_color="transparent")
        right_box.pack(side="right", padx=20, fill="y")

        # User profile chip
        user_chip = ctk.CTkFrame(
            right_box,
            fg_color=theme.COLOR_INPUT_BG,
            corner_radius=8,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        user_chip.pack(side="left", padx=(0, 10), pady=12)

        user_name_lbl = ctk.CTkLabel(
            user_chip,
            text=f"👤 {self.user.full_name}",
            font=theme.FONT_SMALL,
            text_color=theme.COLOR_TEXT_PRIMARY,
        )
        user_name_lbl.pack(side="left", padx=(10, 6), pady=4)

        # Role badge
        role_badge = ctk.CTkFrame(user_chip, fg_color=theme.COLOR_PANEL_BORDER, corner_radius=6)
        role_badge.pack(side="left", padx=(0, 8), pady=4)
        role_lbl = ctk.CTkLabel(
            role_badge,
            text=self.user.role_name.upper(),
            font=(theme.FONT_FAMILY, 9, "bold"),
            text_color=theme.COLOR_TEXT_MUTED,
        )
        role_lbl.pack(padx=6, pady=1)

        # Clearance badge
        bg_col, fg_col = theme.get_classification_colors(self.user.clearance_level)
        clearance_pill = ctk.CTkFrame(right_box, fg_color=bg_col, corner_radius=8)
        clearance_pill.pack(side="left", padx=(0, 12), pady=12)

        clearance_lbl = ctk.CTkLabel(
            clearance_pill,
            text=f"CLEARANCE: {self.user.clearance_level.upper()}",
            font=(theme.FONT_FAMILY, 10, "bold"),
            text_color=fg_col,
        )
        clearance_lbl.pack(padx=10, pady=4)

        # Logout action button
        logout_btn = ctk.CTkButton(
            right_box,
            text="⎋ Exit",
            command=self._handle_logout,
            width=65,
            height=30,
            corner_radius=6,
            fg_color=theme.COLOR_PILL_RESTRICTED_BG,
            hover_color="#5F1D27",
            text_color=theme.COLOR_PILL_RESTRICTED_FG,
            font=theme.FONT_SMALL,
        )
        logout_btn.pack(side="left", pady=15)

    def _update_live_clock(self) -> None:
        """Updates dual UTC and Indian Standard Time (IST) clocks every second."""
        if not self._clock_running:
            return

        try:
            if not self.winfo_exists():
                return

            now_utc = datetime.now(timezone.utc)
            now_local = datetime.now()

            utc_str = now_utc.strftime("%H:%M:%S UTC")
            ist_str = now_local.strftime("%H:%M:%S IST")
            date_str = now_utc.strftime("%d %b %Y").upper()

            clock_text = f"🌐 {date_str}  •  {utc_str}  │  {ist_str}"
            self.clock_lbl.configure(text=clock_text)

            if self._clock_running:
                self._clock_timer_id = self.after(1000, self._update_live_clock)
        except Exception:
            self._clock_running = False

    def stop_clock(self) -> None:
        """Stops the clock update loop."""
        self._clock_running = False
        if self._clock_timer_id:
            try:
                self.after_cancel(self._clock_timer_id)
            except Exception:
                pass
            self._clock_timer_id = None

    def stop_all(self) -> None:
        """Stops clocks and any background tab loops/animations."""
        self.stop_clock()
        self._clear_workspace()

    # =========================================================================
    # 2. WORKSPACE CONTAINER & VIEWS
    # =========================================================================

    def _create_workspace_container(self) -> None:
        """Central dynamic container hosting the active module view."""
        self.workspace = ctk.CTkFrame(self, fg_color=theme.COLOR_BG_DARK, corner_radius=0)
        self.workspace.pack(fill="both", expand=True, padx=14, pady=(4, 6))

    def _clear_workspace(self) -> None:
        """Removes existing tab widgets when switching."""
        for child in self.workspace.winfo_children():
            if hasattr(child, "stop_animation"):
                try:
                    child.stop_animation()
                except Exception:
                    pass
            if hasattr(child, "stop_timers"):
                try:
                    child.stop_timers()
                except Exception:
                    pass
            child.destroy()

    def switch_tab(self, tab_key: str) -> None:
        """Activates and renders the requested module view."""
        self.current_tab = tab_key
        self._update_dock_buttons()
        self._clear_workspace()

        if tab_key == "home":
            self._render_home_tab()
        elif tab_key == "telemetry":
            self._render_telemetry_tab()
        elif tab_key == "stations":
            self._render_stations_tab()
        elif tab_key == "ai_routing":
            self._render_ai_routing_tab()
        elif tab_key == "power_rf":
            self._render_power_rf_tab()
        elif tab_key == "workbench":
            self._render_workbench_tab()
        elif tab_key == "security":
            self._render_security_tab()

    # -------------------------------------------------------------------------
    # TAB 0: MISSION HOME VIEW (Flight Deck & Ground Track Overview)
    # -------------------------------------------------------------------------

    def _render_home_tab(self) -> None:
        """Mounts Mission Home with 2D orbital tracks, live satellite propagation & KPIs."""
        self.home_tab = MissionHomeTab(
            self.workspace,
            user=self.user,
            on_navigate=self.switch_tab,
            on_filter_telemetry=self._filter_telemetry_by_station,
        )
        self.home_tab.pack(fill="both", expand=True)

    # -------------------------------------------------------------------------
    # TAB 1: TELEMETRY VIEW (CRUD + LIVE POSTGRESQL SYNC)
    # -------------------------------------------------------------------------

    def _render_telemetry_tab(self) -> None:
        """Mounts the full TelemetryTab with server-side pagination, filters & CRUD."""
        self.telemetry_tab = TelemetryTab(self.workspace, user=self.user)
        self.telemetry_tab.pack(fill="both", expand=True)

    # -------------------------------------------------------------------------
    # TAB 2: GROUND STATIONS VIEW
    # -------------------------------------------------------------------------

    def _render_stations_tab(self) -> None:
        """Mounts full Ground Stations module with pass countdowns & metrics."""
        self.stations_tab = StationsTab(
            self.workspace,
            user=self.user,
            on_filter_telemetry=self._filter_telemetry_by_station,
        )
        self.stations_tab.pack(fill="both", expand=True)

    def _filter_telemetry_by_station(self, station_code: str) -> None:
        """Switches to the Telemetry tab and applies the station filter."""
        self.switch_tab("telemetry")
        if hasattr(self, "telemetry_tab"):
            try:
                combo = getattr(self.telemetry_tab, "station_combo", None)
                if combo:
                    vals = combo.cget("values")
                    target = None
                    for v in vals:
                        if (
                            v.lower() == station_code.lower()
                            or station_code.lower() in v.lower()
                            or v.lower().startswith(station_code.lower())
                        ):
                            target = v
                            break
                    if target:
                        combo.set(target)
                    else:
                        combo.set(station_code)
                    self.telemetry_tab._on_filter_changed()
            except Exception as e:
                print(f"[!] Error filtering telemetry by station: {e}")

    # -------------------------------------------------------------------------
    # TAB 3: AI ROUTING VIEW (Inter-Satellite AI Engine + Scikit-Learn ML Model)
    # -------------------------------------------------------------------------

    def _render_ai_routing_tab(self) -> None:
        """Mounts AI routing analytics & interactive scikit-learn priority classifier."""
        self.ai_routing_tab = AIRoutingAnalyticsTab(self.workspace, user=self.user)
        self.ai_routing_tab.pack(fill="both", expand=True)

    # -------------------------------------------------------------------------
    # TAB 4: POWER & RF VIEW (EPS & RF Analytics + Dark Matplotlib + Saved Queries)
    # -------------------------------------------------------------------------

    def _render_power_rf_tab(self) -> None:
        """Mounts Power & RF Subsystem Dashboard with KPI cards & dark matplotlib charts."""
        self.power_rf_tab = PowerRFAnalyticsTab(self.workspace, user=self.user)
        self.power_rf_tab.pack(fill="both", expand=True)

    # -------------------------------------------------------------------------
    # TAB 5: WORKBENCH VIEW
    # -------------------------------------------------------------------------

    def _render_workbench_tab(self) -> None:
        """Mounts the full Safe SQL Workbench with AST validation & Dry-Run Preview."""
        self.workbench_tab = WorkbenchTab(self.workspace, user=self.user)
        self.workbench_tab.pack(fill="both", expand=True)

    # -------------------------------------------------------------------------
    # TAB 6: SECURITY VIEW
    # -------------------------------------------------------------------------

    def _render_security_tab(self) -> None:
        """Mounts the comprehensive Security, RBAC, Approval Queue & Audit Trail Console."""
        self.security_tab = SecurityTab(self.workspace, user=self.user)
        self.security_tab.pack(fill="both", expand=True)

    # =========================================================================
    # 3. FLOATING MISSION DOCK (Matching MissionDock.tsx)
    # =========================================================================

    def _create_floating_mission_dock(self) -> None:
        """Constructs floating dock navigation bar at the bottom."""
        self.dock_frame = ctk.CTkFrame(
            self,
            fg_color="#100E17",
            corner_radius=12,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
            height=50,
        )
        self.dock_frame.pack(side="bottom", fill="x", padx=14, pady=(2, 8))

        dock_inner = ctk.CTkFrame(self.dock_frame, fg_color="transparent")
        dock_inner.pack(padx=8, pady=5)

        self.nav_items = [
            ("home", "Mission Home", "🌐"),
            ("telemetry", "Telemetry", "📡"),
            ("stations", "Stations", "🌍"),
            ("ai_routing", "AI Routing", "🧠"),
            ("power_rf", "Power & RF", "⚡"),
            ("workbench", "Workbench", "🛠️"),
            ("security", "Security", "🛡️"),
        ]

        self.dock_buttons: Dict[str, ctk.CTkButton] = {}

        for key, label, icon in self.nav_items:
            btn = ctk.CTkButton(
                dock_inner,
                text=f"{icon}  {label}",
                command=lambda k=key: self.switch_tab(k),
                height=36,
                corner_radius=8,
                font=theme.FONT_BODY_BOLD,
                fg_color="transparent",
                hover_color="#201D2C",
                text_color=theme.COLOR_TEXT_PRIMARY,
            )
            btn.pack(side="left", padx=4)
            self.dock_buttons[key] = btn

    def _update_dock_buttons(self) -> None:
        """Updates button highlighting based on active tab."""
        for key, btn in self.dock_buttons.items():
            if key == self.current_tab:
                btn.configure(
                    fg_color=theme.COLOR_ACCENT_LAVENDER,
                    text_color=theme.COLOR_BG_DARK,
                    hover_color=theme.COLOR_ACCENT_HOVER,
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=theme.COLOR_TEXT_PRIMARY,
                    hover_color="#201D2C",
                )

    def _handle_logout(self) -> None:
        """Stops clock and notifies parent."""
        self.stop_clock()
        if self.on_logout:
            self.on_logout()


class MainWindow(ctk.CTk):
    """Standalone window wrapper around MainWorkspaceView."""

    def __init__(self, user: security.UserSession, on_logout: Optional[Callable[[], None]] = None):
        super().__init__()
        self.title(f"ORBITAL // Mission Control — {user.username} [{user.clearance_level}]")
        self.geometry("1260x820")
        self.minsize(1080, 720)
        self.configure(fg_color=theme.COLOR_BG_DARK)

        self.view = MainWorkspaceView(self, user=user, on_logout=on_logout)
        self.view.pack(fill="both", expand=True)
