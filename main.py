"""
main.py - ORBITAL Mission Telemetry System Primary Application Entry Point
======================================================================
SomaiyaSat & SomaiyaPod PocketQube Telemetry Management System

Runs the application lifecycle inside a single unified CustomTkinter root window:
  1. Verifies database connectivity.
  2. Presents the Cosmic Starfield Login View.
  3. Seamlessly mounts the full Mission Control Dashboard (Header Bar,
     Workspace, Floating Dock) upon bcrypt authentication.
  4. Returns cleanly to login upon operator logout.
"""

from __future__ import annotations

import sys
from typing import Optional

import customtkinter as ctk

import db
import security
import theme
from gui.login_window import LoginView
from gui.main_window import MainWorkspaceView


class OrbitalApp(ctk.CTk):
    """
    Primary application window orchestrating the lifecycle between
    the Cosmic Starfield Login Screen and the Mission Control Dashboard.
    """

    def __init__(self):
        super().__init__()

        self.current_session: Optional[security.UserSession] = None
        self.login_view: Optional[LoginView] = None
        self.workspace_view: Optional[MainWorkspaceView] = None

        # Base Application Window Setup
        self.configure(fg_color=theme.COLOR_BG_DARK)
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)

        # Initialize global TTK theme styles (deep space obsidian, no white screens)
        theme.init_ttk_styles(self)

        # Show Login View initially
        self.show_login_screen()

    def show_login_screen(self) -> None:
        """Presents the animated cosmic starfield login screen."""
        if self.workspace_view:
            self.workspace_view.stop_clock()
            self.workspace_view.destroy()
            self.workspace_view = None

        self.title("ORBITAL // SomaiyaSat Mission Telemetry Access Control")
        self.geometry("980x680")
        self.minsize(860, 600)

        # Center on screen
        self.update_idletasks()
        w = 980
        h = 680
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

        self.login_view = LoginView(self, on_login_success=self.on_login_success)
        self.login_view.pack(fill="both", expand=True)

    def on_login_success(self, session: security.UserSession) -> None:
        """Handles successful authentication and mounts the main mission workspace."""
        self.current_session = session

        # Destroy login view safely
        if self.login_view:
            self.login_view.stop_animation()
            self.login_view.destroy()
            self.login_view = None

        # Resize and transition to Main Mission Control layout
        self.title(f"ORBITAL // SomaiyaSat Mission Control — {session.full_name} [{session.clearance_level}]")
        self.geometry("1260x820")
        self.minsize(1080, 720)

        # Center on screen
        self.update_idletasks()
        w = 1260
        h = 820
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

        # Mount Main Workspace View
        self.workspace_view = MainWorkspaceView(
            self,
            user=self.current_session,
            on_logout=self.on_logout,
        )
        self.workspace_view.pack(fill="both", expand=True)

    def on_logout(self) -> None:
        """Handles operator logout and returns to login screen."""
        self.current_session = None
        self.show_login_screen()

    def _on_app_close(self) -> None:
        """Handles graceful application teardown."""
        if self.login_view:
            self.login_view.stop_animation()
        if self.workspace_view:
            self.workspace_view.stop_all()
        self.destroy()


def main() -> None:
    # 1. Automatic database & schema self-provisioning (no manual SQL setup required)
    try:
        db.ensure_database_and_schema_ready()
    except Exception as exc:
        print(f"[!] Warning during database bootstrap: {exc}")

    # 2. Quick sanity check on DB connection
    ok, msg = db.test_connection()
    if not ok:
        print(f"[!] Database connection failed: {msg}")
        print("    Please ensure PostgreSQL is running and your .env credentials are correct.")
        sys.exit(1)

    # 3. Launch unified application
    app = OrbitalApp()
    app.mainloop()


if __name__ == "__main__":
    main()
