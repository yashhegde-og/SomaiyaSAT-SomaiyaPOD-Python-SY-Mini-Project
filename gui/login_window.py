"""
gui/login_window.py - Mission Control Login Screen with Live Starfield Canvas
============================================================================
Part of the ORBITAL Mission Telemetry System.

Matches the SomaiyaSat Mission Web Application aesthetic:
  - Deep space obsidian background (#08090D)
  - Animated Cosmic Starfield canvas with twinkling stars and diffraction spikes
  - Elevated glassmorphic card (#191722) with lavender accent border
  - bcrypt password authentication with real-time brute-force lockout countdown
  - Quick-demo role credentials selector for rapid viva/presentation testing
"""

from __future__ import annotations

import math
import os
import random
import tkinter as tk
from typing import Callable, List, Optional

import customtkinter as ctk
from PIL import Image

import security
import theme


class Star:
    """Represents an individual star in the cosmic starfield simulation."""

    def __init__(self, x_norm: float, y_norm: float, depth: int):
        self.x_norm = x_norm
        self.y_norm = y_norm
        self.depth = depth  # 1 = far, 2 = mid, 3 = near
        self.base_alpha = random.uniform(0.3, 0.9)
        self.twinkle_speed = random.uniform(0.04, 0.12)
        self.phase = random.uniform(0, math.pi * 2)

        # Depth-based visual traits
        if depth == 1:
            self.size = 1.0
            self.color = "#7350DB"  # Subtle far violet
            self.has_spikes = False
        elif depth == 2:
            self.size = random.choice([1.5, 2.0])
            self.color = random.choice(["#F3F0FA", "#D0BFFB", "#DEC28A"])  # Mid platinum / pale gold
            self.has_spikes = False
        else:
            self.size = random.choice([2.5, 3.5])
            self.color = random.choice(["#FFFFFF", "#D5B16D", "#A78BFA"])  # Near bright gold / lavender
            self.has_spikes = True


class LoginView(ctk.CTkFrame):
    """
    Modular Login View containing the animated Starfield Canvas
    and the Glassmorphic Credentials Card. Can be hosted in a standalone
    window or swapped inside a root application frame.
    """

    def __init__(
        self,
        master: Any,
        on_login_success: Optional[Callable[[security.UserSession], None]] = None,
        **kwargs,
    ):
        super().__init__(master, fg_color=theme.COLOR_BG_DARK, corner_radius=0, **kwargs)

        self.on_login_success = on_login_success
        self.authenticated_session: Optional[security.UserSession] = None

        # Starfield particle collection
        self.stars: List[Star] = []
        self._init_starfield(count=160)
        self._animation_running = True
        self._after_id: Optional[str] = None

        # Build UI Elements
        self._create_starfield_canvas()
        self._create_login_card()

        # Start animation loop
        self._animate_starfield()

    def _init_starfield(self, count: int) -> None:
        """Initializes distributed star coordinates across depth planes."""
        self.stars.clear()
        for _ in range(count):
            depth = random.choices([1, 2, 3], weights=[0.60, 0.30, 0.10])[0]
            self.stars.append(Star(random.random(), random.random(), depth))

    def _create_starfield_canvas(self) -> None:
        """Constructs full-frame background canvas for space rendering."""
        self.canvas = tk.Canvas(
            self,
            bg=theme.COLOR_BG_DARK,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

    def _draw_nebula_glow(self, width: int, height: int) -> None:
        """Renders subtle ambient cosmic glow clusters behind the card."""
        self.canvas.create_oval(
            -100, height // 3 - 150, width // 2, height // 3 + 300,
            fill="#120D22", outline="", width=0
        )
        self.canvas.create_oval(
            width // 2, height // 2, width + 150, height + 150,
            fill="#14110A", outline="", width=0
        )

    def _animate_starfield(self) -> None:
        """Animates star twinkling and diffraction spikes at ~30 FPS."""
        if not self._animation_running:
            return

        try:
            if not self.winfo_exists():
                return

            self.canvas.delete("all")
            width = max(self.winfo_width(), 100)
            height = max(self.winfo_height(), 100)

            # Draw background nebulae
            self._draw_nebula_glow(width, height)

            # Draw and twinkle stars
            for star in self.stars:
                star.phase += star.twinkle_speed
                alpha = star.base_alpha + 0.35 * math.sin(star.phase)
                alpha = max(0.15, min(1.0, alpha))

                cx = star.x_norm * width
                cy = star.y_norm * height
                r = star.size

                self.canvas.create_oval(
                    cx - r, cy - r, cx + r, cy + r,
                    fill=star.color, outline=""
                )

                if star.has_spikes and alpha > 0.6:
                    spike_len = r * 3.5
                    self.canvas.create_line(
                        cx - spike_len, cy, cx + spike_len, cy,
                        fill=star.color, width=1
                    )
                    self.canvas.create_line(
                        cx, cy - spike_len, cx, cy + spike_len,
                        fill=star.color, width=1
                    )

            if self._animation_running:
                self._after_id = self.after(35, self._animate_starfield)
        except Exception:
            self._animation_running = False

    def stop_animation(self) -> None:
        """Halts the animation loop and cancels pending timer events."""
        self._animation_running = False
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _create_login_card(self) -> None:
        """Constructs the centered floating glassmorphic authentication card."""
        self.card = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_PANEL_BG,
            corner_radius=16,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
            width=460,
        )
        self.card.place(relx=0.5, rely=0.5, anchor="center")

        inner = ctk.CTkFrame(self.card, fg_color="transparent")
        inner.pack(padx=36, pady=32, fill="both", expand=True)

        # 1. Mission Header Badge (Clean Centered Text)
        header_frame = ctk.CTkFrame(inner, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 16))

        title_lbl = ctk.CTkLabel(
            header_frame,
            text="ORBITAL",
            font=theme.FONT_TITLE_LARGE,
            text_color=theme.COLOR_ACCENT_LAVENDER,
            anchor="center",
            justify="center",
        )
        title_lbl.pack(fill="x", anchor="center")

        sub_lbl = ctk.CTkLabel(
            header_frame,
            text="SomaiyaSat & SomaiyaPod PocketQube Mission Control",
            font=theme.FONT_SMALL,
            text_color=theme.COLOR_TEXT_MUTED,
            anchor="center",
            justify="center",
        )
        sub_lbl.pack(fill="x", anchor="center", pady=(4, 0))

        sep = ctk.CTkFrame(inner, fg_color=theme.COLOR_PANEL_BORDER, height=1)
        sep.pack(fill="x", pady=(14, 18))

        # 2. Input Fields
        u_lbl = ctk.CTkLabel(
            inner,
            text="OPERATOR USERNAME",
            font=theme.FONT_CODE_BOLD,
            text_color=theme.COLOR_TEXT_MUTED,
        )
        u_lbl.pack(anchor="w", pady=(0, 4))

        self.user_entry = ctk.CTkEntry(
            inner,
            placeholder_text="Enter assigned username (e.g., admin_user)",
            fg_color=theme.COLOR_INPUT_BG,
            border_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
            placeholder_text_color=theme.COLOR_TEXT_DISABLED,
            height=38,
            corner_radius=8,
            font=theme.FONT_BODY,
        )
        self.user_entry.pack(fill="x", pady=(0, 14))
        self.user_entry.bind("<Return>", lambda e: self.pass_entry.focus())

        p_frame = ctk.CTkFrame(inner, fg_color="transparent")
        p_frame.pack(fill="x", pady=(0, 4))

        p_lbl = ctk.CTkLabel(
            p_frame,
            text="SECURITY PASSPHRASE",
            font=theme.FONT_CODE_BOLD,
            text_color=theme.COLOR_TEXT_MUTED,
        )
        p_lbl.pack(side="left")

        # Integrated Password Tile with Embedded Eye Icon
        self.pass_tile = ctk.CTkFrame(
            inner,
            fg_color=theme.COLOR_INPUT_BG,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
            corner_radius=8,
            height=38,
        )
        self.pass_tile.pack(fill="x", pady=(0, 10))

        self.pass_entry = ctk.CTkEntry(
            self.pass_tile,
            placeholder_text="Enter account password",
            show="*",
            fg_color="transparent",
            border_width=0,
            text_color=theme.COLOR_TEXT_PRIMARY,
            placeholder_text_color=theme.COLOR_TEXT_DISABLED,
            height=36,
            font=theme.FONT_BODY,
        )
        self.pass_entry.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.pass_entry.bind("<Return>", lambda e: self._handle_login())

        self._show_pass = False
        self.eye_btn = ctk.CTkButton(
            self.pass_tile,
            text="👁",
            width=36,
            height=32,
            fg_color="transparent",
            hover_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_MUTED,
            font=(theme.FONT_FAMILY, 14),
            command=self._toggle_password_visibility,
        )
        self.eye_btn.pack(side="right", padx=(0, 4))
        self.pass_entry.bind("<Return>", lambda e: self._handle_login())

        # 3. Dynamic Feedback Label
        self.msg_lbl = ctk.CTkLabel(
            inner,
            text="",
            font=theme.FONT_SMALL,
            text_color=theme.COLOR_STATUS_FAIL,
            wraplength=380,
            justify="center",
        )
        self.msg_lbl.pack(fill="x", pady=(2, 10))

        # 4. Authenticate Button
        self.login_btn = ctk.CTkButton(
            inner,
            text="AUTHENTICATE & CONNECT",
            command=self._handle_login,
            height=42,
            corner_radius=8,
            fg_color=theme.COLOR_ACCENT_LAVENDER,
            hover_color=theme.COLOR_ACCENT_HOVER,
            text_color=theme.COLOR_BG_DARK,
            font=theme.FONT_BODY_BOLD,
        )
        self.login_btn.pack(fill="x", pady=(0, 16))

        # 5. Quick Demo Roles Toolbar
        demo_box = ctk.CTkFrame(
            inner,
            fg_color=theme.COLOR_INPUT_BG,
            corner_radius=10,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        demo_box.pack(fill="x", pady=(4, 0))

        demo_title = ctk.CTkLabel(
            demo_box,
            text="QUICK DEMO ROLES (CLICK TO AUTO-FILL)",
            font=(theme.FONT_FAMILY, 9, "bold"),
            text_color=theme.COLOR_HIGHLIGHT_GOLD,
        )
        demo_title.pack(pady=(6, 4))

        roles_btn_frame = ctk.CTkFrame(demo_box, fg_color="transparent")
        roles_btn_frame.pack(pady=(0, 6), padx=6, fill="x")

        demo_configs = [
            ("Admin (Restricted)", "admin_user", "Admin@2026!", theme.COLOR_PILL_RESTRICTED_BG, theme.COLOR_PILL_RESTRICTED_FG),
            ("Engineer (Internal)", "flight_engineer", "Engineer@2026!", theme.COLOR_PILL_INTERNAL_BG, theme.COLOR_PILL_INTERNAL_FG),
            ("Operator (Internal)", "station_operator", "Operator@2026!", theme.COLOR_PILL_INTERNAL_BG, theme.COLOR_PILL_INTERNAL_FG),
            ("Viewer (Public)", "public_viewer", "Viewer@2026!", theme.COLOR_PILL_PUBLIC_BG, theme.COLOR_PILL_PUBLIC_FG),
        ]

        roles_btn_frame.columnconfigure((0, 1), weight=1)
        for idx, (label, u, p, bg, fg) in enumerate(demo_configs):
            btn = ctk.CTkButton(
                roles_btn_frame,
                text=label,
                command=lambda user=u, pwd=p: self._fill_demo(user, pwd),
                font=(theme.FONT_FAMILY, 10),
                height=26,
                corner_radius=6,
                fg_color=bg,
                text_color=fg,
                hover_color=theme.COLOR_PANEL_BORDER,
            )
            r = idx // 2
            c = idx % 2
            btn.grid(row=r, column=c, padx=3, pady=3, sticky="ew")

        # Pre-fill Admin by default for convenience
        self._fill_demo("admin_user", "Admin@2026!")

    def _toggle_password_visibility(self) -> None:
        """Toggles password visibility with eye indicator."""
        self._show_pass = not getattr(self, "_show_pass", False)
        if self._show_pass:
            self.pass_entry.configure(show="")
            self.eye_btn.configure(text="🔒", text_color=theme.COLOR_HIGHLIGHT_GOLD)
        else:
            self.pass_entry.configure(show="*")
            self.eye_btn.configure(text="👁", text_color=theme.COLOR_TEXT_MUTED)

    def _fill_demo(self, username: str, password: str) -> None:
        """Helper to pre-fill test credentials into entry fields."""
        self.user_entry.delete(0, "end")
        self.user_entry.insert(0, username)
        self.pass_entry.delete(0, "end")
        self.pass_entry.insert(0, password)
        self.msg_lbl.configure(text="", text_color=theme.COLOR_STATUS_FAIL)

    def _handle_login(self) -> None:
        """Executes bcrypt authentication and triggers success callback."""
        u = self.user_entry.get().strip()
        p = self.pass_entry.get()

        if not u or not p:
            self.msg_lbl.configure(text="Please provide both username and password.", text_color=theme.COLOR_STATUS_WARN)
            return

        self.login_btn.configure(state="disabled", text="VERIFYING WITH BCRYPT...")
        self.update_idletasks()

        ok, session, message = security.authenticate_user(u, p)
        self.login_btn.configure(state="normal", text="AUTHENTICATE & CONNECT")

        if ok and session:
            self.authenticated_session = session
            self.msg_lbl.configure(
                text=f"Authentication Granted: {session.full_name} [{session.clearance_level}]",
                text_color=theme.COLOR_STATUS_PASS,
            )
            self.stop_animation()

            if self.on_login_success:
                self.on_login_success(session)
        else:
            self.msg_lbl.configure(text=message, text_color=theme.COLOR_STATUS_FAIL)


class LoginWindow(ctk.CTk):
    """Standalone window wrapper around LoginView."""

    def __init__(self, on_login_success: Optional[Callable[[security.UserSession], None]] = None):
        super().__init__()
        self.title("ORBITAL // SomaiyaSat Mission Telemetry Access Control")
        self.geometry("980x680")
        self.minsize(860, 600)
        self.configure(fg_color=theme.COLOR_BG_DARK)

        self.login_view = LoginView(self, on_login_success=on_login_success)
        self.login_view.pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        self.login_view.stop_animation()
        self.destroy()


def show_login_dialog() -> Optional[security.UserSession]:
    """Convenience function for standalone execution."""
    session_result: List[Optional[security.UserSession]] = [None]

    def on_success(sess: security.UserSession) -> None:
        session_result[0] = sess
        win.destroy()

    win = LoginWindow(on_login_success=on_success)
    win.mainloop()
    return session_result[0]


if __name__ == "__main__":
    user = show_login_dialog()
    if user:
        print(f"[+] Login successful: {user.username} ({user.role_name} | Clearance: {user.clearance_level})")
