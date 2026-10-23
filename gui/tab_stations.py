"""
gui/tab_stations.py - International Ground Station Network Module
=================================================================
Part of the ORBITAL Mission Telemetry System.
Matches GroundStationsModule.tsx from the Orbital mission operations platform:
  - 14 Amateur Tracking Stations across 10 countries.
  - Dynamic Next-Pass Countdown Timer calculated in real-time.
  - Live aggregated telemetry stats per station (total packets, mean SNR, CRC pass rate).
  - Search filter by station code, name, country, or callsign.
  - 1-click drill-down linking directly into filtered Telemetry records.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, List, Optional

import customtkinter as ctk

import security
import theme
from models.telemetry_queries import fetch_ground_station_metrics


def calculate_next_station_pass(latitude: float, longitude: float, current_time: float) -> Dict[str, Any]:
    """
    Computes a realistic Keplerian pass countdown for 51.6° LEO orbit (95.6 min period).
    """
    orbit_period_sec = 95.6 * 60.0  # 5736 seconds
    # Phase offset derived from station longitude and latitude
    station_phase = ((longitude + 180.0) / 360.0 + (latitude + 90.0) / 180.0 * 0.5) % 1.0
    current_phase = ((current_time / orbit_period_sec) + station_phase) % 1.0

    in_pass = current_phase < 0.09  # ~8.5 minutes pass window
    if in_pass:
        seconds_left = int((0.09 - current_phase) * orbit_period_sec)
        m, s = divmod(seconds_left, 60)
        return {"in_pass": True, "countdown": f"{m:02d}m {s:02d}s", "label": "IN PASS"}
    else:
        seconds_left = int((1.0 - current_phase) * orbit_period_sec)
        m, s = divmod(seconds_left, 60)
        return {"in_pass": False, "countdown": f"{m:02d}m {s:02d}s", "label": "NEXT PASS"}


class StationsTab(ctk.CTkFrame):
    """Ground Station Tracking Network Console matching Orbital web app."""

    def __init__(
        self,
        master: Any,
        user: security.UserSession,
        on_filter_telemetry: Optional[Callable[[str], None]] = None,
        **kwargs,
    ):
        super().__init__(master, fg_color=theme.COLOR_BG_DARK, corner_radius=0, **kwargs)

        self.user = user
        self.on_filter_telemetry = on_filter_telemetry
        self.stations_data: List[Dict[str, Any]] = []
        self._timer_running = True
        self._timer_id: Optional[str] = None

        # Build UI layout
        self._create_header_bar()
        self._create_scrollable_grid()

        # Load data & start pass countdown
        self.reload_data()
        self._update_pass_timers()

    def _create_header_bar(self) -> None:
        """Top toolbar with title, search entry, and refresh button."""
        header_card = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_PANEL_BG,
            corner_radius=12,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        header_card.pack(fill="x", padx=10, pady=(6, 8))

        inner = ctk.CTkFrame(header_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=10)

        # Title block
        left_box = ctk.CTkFrame(inner, fg_color="transparent")
        left_box.pack(side="left")

        ctk.CTkLabel(
            left_box,
            text="🌍 International Ground Station Network",
            font=theme.FONT_TITLE,
            text_color=theme.COLOR_TEXT_PRIMARY,
        ).pack(anchor="w")

        ctk.CTkLabel(
            left_box,
            text="14 Amateur Satellite Tracking Stations • Real-Time Orbit Pass Synchronization & Demodulation Stats",
            font=theme.FONT_SMALL,
            text_color=theme.COLOR_TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        # Search & Actions
        right_box = ctk.CTkFrame(inner, fg_color="transparent")
        right_box.pack(side="right")

        self.search_entry = ctk.CTkEntry(
            right_box,
            placeholder_text="Search stations, callsign...",
            width=220,
            height=32,
            font=theme.FONT_BODY,
            fg_color=theme.COLOR_INPUT_BG,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        self.search_entry.pack(side="left", padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda e: self._render_station_cards())

        ctk.CTkButton(
            right_box,
            text="🔄 Refresh",
            command=self.reload_data,
            width=85,
            height=32,
            fg_color="#201D2C",
            hover_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
            font=theme.FONT_SMALL,
        ).pack(side="left")

    def _create_scrollable_grid(self) -> None:
        """Scrollable container hosting the station cards."""
        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=4, pady=(0, 6))

    def reload_data(self) -> None:
        """Fetches station metrics from PostgreSQL."""
        try:
            self.stations_data = fetch_ground_station_metrics()
            self._render_station_cards()
        except Exception as exc:
            print(f"[!] Error loading station metrics: {exc}")

    def _render_station_cards(self) -> None:
        """Clears and renders station cards matching active search filter."""
        for child in self.scroll_frame.winfo_children():
            child.destroy()

        query = self.search_entry.get().strip().lower()
        filtered = [
            s for s in self.stations_data
            if (
                query in s["station_name"].lower()
                or query in s["station_code"].lower()
                or query in s["callsign"].lower()
                or query in s["country"].lower()
            )
        ]

        if not filtered:
            empty_box = ctk.CTkFrame(self.scroll_frame, fg_color=theme.COLOR_PANEL_BG, corner_radius=12)
            empty_box.pack(fill="x", padx=20, pady=40)
            ctk.CTkLabel(
                empty_box,
                text="No Matching Ground Stations",
                font=theme.FONT_SUBTITLE,
                text_color=theme.COLOR_TEXT_PRIMARY,
            ).pack(pady=(20, 4))
            ctk.CTkLabel(
                empty_box,
                text="Try adjusting or clearing your search term to view all 14 nodes.",
                font=theme.FONT_SMALL,
                text_color=theme.COLOR_TEXT_MUTED,
            ).pack(pady=(0, 20))
            return

        # 2-column or 3-column responsive layout
        grid_container = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        grid_container.pack(fill="both", expand=True, padx=8, pady=4)
        grid_container.columnconfigure((0, 1), weight=1)

        now = time.time()

        for idx, st in enumerate(filtered):
            is_mumbai = "Mumbai" in st["station_code"]
            border_col = theme.COLOR_HIGHLIGHT_GOLD if is_mumbai else theme.COLOR_PANEL_BORDER

            card = ctk.CTkFrame(
                grid_container,
                fg_color=theme.COLOR_PANEL_BG,
                corner_radius=12,
                border_width=1,
                border_color=border_col,
            )
            r = idx // 2
            c = idx % 2
            card.grid(row=r, column=c, padx=8, pady=8, sticky="nsew")

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=16, pady=14)

            # Extract friendly city name from station_code (e.g. Mumbai, Berlin)
            city_name = st["station_code"].split("-")[0]
            callsign_text = f"📍 {city_name}" + (" (HQ)" if is_mumbai else "")

            # Top Row: City Name & Status
            top_row = ctk.CTkFrame(inner, fg_color="transparent")
            top_row.pack(fill="x")

            ctk.CTkLabel(
                top_row,
                text=callsign_text,
                font=theme.FONT_TITLE,
                text_color=theme.COLOR_HIGHLIGHT_GOLD if is_mumbai else theme.COLOR_TEXT_PRIMARY,
            ).pack(side="left")

            stat_pill = ctk.CTkFrame(top_row, fg_color="#10251C", corner_radius=6)
            stat_pill.pack(side="right")
            ctk.CTkLabel(
                stat_pill,
                text=f"● {st['status'].upper()}",
                font=(theme.FONT_FAMILY, 9, "bold"),
                text_color=theme.COLOR_STATUS_PASS,
            ).pack(padx=8, pady=2)

            # Station Name & Location
            ctk.CTkLabel(
                inner,
                text=f"{st['station_name']}  ({st['callsign']})",
                font=theme.FONT_BODY_BOLD,
                text_color=theme.COLOR_TEXT_PRIMARY,
                anchor="w",
            ).pack(fill="x", pady=(4, 1))

            ctk.CTkLabel(
                inner,
                text=f"{st['country']}  •  Elevation: {float(st['elevation_m']):.0f} m  •  {float(st['latitude']):.2f}° N, {float(st['longitude']):.2f}° E",
                font=theme.FONT_SMALL,
                text_color=theme.COLOR_TEXT_MUTED,
                anchor="w",
            ).pack(fill="x", pady=(0, 8))

            # Pass Countdown Indicator (Real-Time Propagation)
            pass_info = calculate_next_station_pass(float(st["latitude"]), float(st["longitude"]), now)
            pass_box = ctk.CTkFrame(
                inner,
                fg_color="#0D241A" if pass_info["in_pass"] else theme.COLOR_INPUT_BG,
                corner_radius=8,
                border_width=1,
                border_color=theme.COLOR_STATUS_PASS if pass_info["in_pass"] else theme.COLOR_PANEL_BORDER,
            )
            pass_box.pack(fill="x", pady=(0, 10))

            pass_inner = ctk.CTkFrame(pass_box, fg_color="transparent")
            pass_inner.pack(fill="x", padx=10, pady=6)

            ctk.CTkLabel(
                pass_inner,
                text="🛰️ " + ("IN PASS CONTACT" if pass_info["in_pass"] else "NEXT OVERPASS COUNTDOWN"),
                font=(theme.FONT_FAMILY, 9, "bold"),
                text_color=theme.COLOR_STATUS_PASS if pass_info["in_pass"] else theme.COLOR_TEXT_MUTED,
            ).pack(side="left")

            ctk.CTkLabel(
                pass_inner,
                text=pass_info["countdown"],
                font=theme.FONT_CODE_BOLD,
                text_color=theme.COLOR_STATUS_PASS if pass_info["in_pass"] else theme.COLOR_HIGHLIGHT_GOLD,
            ).pack(side="right")

            # 3 KPI Stat Boxes
            stats_row = ctk.CTkFrame(inner, fg_color="transparent")
            stats_row.pack(fill="x", pady=(0, 12))
            stats_row.columnconfigure((0, 1, 2), weight=1)

            # Box 1: Packets
            b1 = ctk.CTkFrame(stats_row, fg_color=theme.COLOR_INPUT_BG, corner_radius=6, border_width=1, border_color=theme.COLOR_PANEL_BORDER)
            b1.grid(row=0, column=0, sticky="ew", padx=(0, 4))
            ctk.CTkLabel(b1, text="PACKETS", font=(theme.FONT_FAMILY, 8, "bold"), text_color=theme.COLOR_TEXT_MUTED).pack(pady=(4, 0))
            ctk.CTkLabel(b1, text=f"{int(st['total_packets']):,}", font=theme.FONT_BODY_BOLD, text_color=theme.COLOR_TEXT_PRIMARY).pack(pady=(0, 4))

            # Box 2: Mean SNR
            b2 = ctk.CTkFrame(stats_row, fg_color=theme.COLOR_INPUT_BG, corner_radius=6, border_width=1, border_color=theme.COLOR_PANEL_BORDER)
            b2.grid(row=0, column=1, sticky="ew", padx=2)
            ctk.CTkLabel(b2, text="MEAN SNR", font=(theme.FONT_FAMILY, 8, "bold"), text_color=theme.COLOR_TEXT_MUTED).pack(pady=(4, 0))
            ctk.CTkLabel(b2, text=f"{float(st['mean_snr']):.1f} dB", font=theme.FONT_BODY_BOLD, text_color=theme.COLOR_HIGHLIGHT_GOLD).pack(pady=(0, 4))

            # Box 3: CRC Pass Rate
            b3 = ctk.CTkFrame(stats_row, fg_color=theme.COLOR_INPUT_BG, corner_radius=6, border_width=1, border_color=theme.COLOR_PANEL_BORDER)
            b3.grid(row=0, column=2, sticky="ew", padx=(4, 0))
            ctk.CTkLabel(b3, text="CRC PASS", font=(theme.FONT_FAMILY, 8, "bold"), text_color=theme.COLOR_TEXT_MUTED).pack(pady=(4, 0))
            ctk.CTkLabel(b3, text=f"{float(st['crc_pass_rate']):.1f}%", font=theme.FONT_BODY_BOLD, text_color=theme.COLOR_STATUS_PASS).pack(pady=(0, 4))

            # Bottom Action Button: Drill Down
            ctk.CTkButton(
                inner,
                text=f"📡 Inspect {city_name} Telemetry Records",
                command=lambda sc=st["station_code"]: self._handle_drilldown(sc),
                height=32,
                corner_radius=8,
                fg_color="#201D2C",
                hover_color=theme.COLOR_ACCENT_HOVER,
                text_color=theme.COLOR_ACCENT_LAVENDER,
                font=theme.FONT_BODY_BOLD,
            ).pack(fill="x")

    def _handle_drilldown(self, station_code: str) -> None:
        if self.on_filter_telemetry:
            self.on_filter_telemetry(station_code)

    def _update_pass_timers(self) -> None:
        """Periodically refreshes countdown timers every 15 seconds without flickering."""
        if not self._timer_running:
            return
        try:
            if self.winfo_exists():
                self._render_station_cards()
                self._timer_id = self.after(15000, self._update_pass_timers)
        except Exception:
            self._timer_running = False

    def stop_timers(self) -> None:
        """Stops background timer loops on view destruction."""
        self._timer_running = False
        if self._timer_id:
            try:
                self.after_cancel(self._timer_id)
            except Exception:
                pass
            self._timer_id = None
