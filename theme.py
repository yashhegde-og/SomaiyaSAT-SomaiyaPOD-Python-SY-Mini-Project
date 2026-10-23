"""
theme.py - ORBITAL Design System & UI Theme Configuration
============================================================
Central palette, typography, classification colors, and ttk/CustomTkinter
styling matching the SomaiyaSat mission web application.
"""

from __future__ import annotations

# =============================================================================
# COLOR PALETTE (Matched to SomaiyaSat Mission Web UI)
# =============================================================================

# Main backgrounds
COLOR_BG_DARK = "#08090D"           # Deep space black background
COLOR_PANEL_BG = "#191722"          # Dark violet-tinted panel / card background
COLOR_PANEL_BORDER = "#2B283A"      # Panel border accent
COLOR_INPUT_BG = "#12111A"          # Input / search entry background

# Accents and Highlights
COLOR_ACCENT_LAVENDER = "#A78BFA"   # Primary brand lavender
COLOR_ACCENT_HOVER = "#8B5CF6"      # Hover state for lavender buttons
COLOR_HIGHLIGHT_GOLD = "#D5B16D"    # Secondary brand gold
COLOR_GOLD_HOVER = "#C49E55"        # Hover state for gold buttons

# Text Hierarchy
COLOR_TEXT_PRIMARY = "#F3F0FA"      # Crisp near-white text
COLOR_TEXT_MUTED = "#B8B4C7"        # Subdued gray-lavender for subtitles / labels
COLOR_TEXT_DISABLED = "#5B566E"     # Disabled button / field text

# Status & Classification Pills
COLOR_PILL_PUBLIC_BG = "#3D3418"     # Subtle gold background
COLOR_PILL_PUBLIC_FG = "#D5B16D"     # Gold text

COLOR_PILL_INTERNAL_BG = "#2C2046"   # Subtle lavender background
COLOR_PILL_INTERNAL_FG = "#A78BFA"   # Lavender text

COLOR_PILL_RESTRICTED_BG = "#4A1820" # Subtle crimson background
COLOR_PILL_RESTRICTED_FG = "#F87171" # Red text

# Telemetry Status Accents
COLOR_STATUS_PASS = "#34D399"       # Emerald green
COLOR_STATUS_FAIL = "#EF4444"       # Danger red
COLOR_STATUS_WARN = "#FBBF24"       # Amber warning
COLOR_STATUS_INFO = "#38BDF8"       # Sky blue

# =============================================================================
# FONT DEFINITIONS (JetBrains Mono Typography System)
# =============================================================================

FONT_FAMILY = "JetBrains Mono"
FONT_MONO = "JetBrains Mono"

FONT_TITLE_LARGE = (FONT_FAMILY, 22, "bold")
FONT_TITLE = (FONT_FAMILY, 16, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 13, "bold")
FONT_BODY = (FONT_FAMILY, 12)
FONT_BODY_BOLD = (FONT_FAMILY, 12, "bold")
FONT_SMALL = (FONT_FAMILY, 10)
FONT_SMALL_BOLD = (FONT_FAMILY, 10, "bold")
FONT_CODE = (FONT_MONO, 11)
FONT_CODE_BOLD = (FONT_MONO, 11, "bold")

# =============================================================================
# GLOBAL TTK TREEVIEW & WIDGET THEME SETUP
# =============================================================================

def init_ttk_styles(root=None) -> None:
    """
    Configures ttk widget styles (Treeview, Headings, Scrollbars)
    globally to match the obsidian/plum dark space design system.
    Prevents unstyled/white screens across all tabs.
    """
    import tkinter.ttk as ttk
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    # Standard Treeview & Telemetry.Treeview table styling
    tree_configs = {
        "background": "#12111A",
        "foreground": COLOR_TEXT_PRIMARY,
        "fieldbackground": "#12111A",
        "rowheight": 32,
        "font": (FONT_MONO, 10),
        "borderwidth": 0,
        "lightcolor": "#12111A",
        "darkcolor": "#12111A",
    }
    style.configure("Treeview", **tree_configs)
    style.configure("Telemetry.Treeview", **tree_configs)

    tree_map = {
        "background": [("selected", "#2D2248"), ("active", "#1E1A2C")],
        "foreground": [("selected", "#FFFFFF"), ("active", COLOR_TEXT_PRIMARY)],
    }
    style.map("Treeview", **tree_map)
    style.map("Telemetry.Treeview", **tree_map)

    # Column Headings
    heading_configs = {
        "background": "#1D1A2B",
        "foreground": COLOR_HIGHLIGHT_GOLD,
        "relief": "flat",
        "font": (FONT_FAMILY, 10, "bold"),
        "padding": (8, 8),
        "borderwidth": 0,
    }
    style.configure("Treeview.Heading", **heading_configs)
    style.configure("Telemetry.Treeview.Heading", **heading_configs)

    heading_map = {
        "background": [("active", "#2A2440"), ("pressed", "#362F52")],
        "foreground": [("active", "#FFFFFF"), ("pressed", COLOR_HIGHLIGHT_GOLD)],
    }
    style.map("Treeview.Heading", **heading_map)
    style.map("Telemetry.Treeview.Heading", **heading_map)

    # Scrollbars
    style.configure(
        "Vertical.TScrollbar",
        background="#1D1A2B",
        troughcolor="#0E0D14",
        bordercolor="#2B283A",
        arrowcolor=COLOR_ACCENT_LAVENDER,
        relief="flat",
        width=12,
    )

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_classification_colors(classification: str) -> tuple[str, str]:
    """
    Returns (bg_color, fg_color) for a given classification level.
    """
    level = str(classification).strip().capitalize()
    if level == "Public":
        return COLOR_PILL_PUBLIC_BG, COLOR_PILL_PUBLIC_FG
    elif level == "Internal":
        return COLOR_PILL_INTERNAL_BG, COLOR_PILL_INTERNAL_FG
    elif level == "Restricted":
        return COLOR_PILL_RESTRICTED_BG, COLOR_PILL_RESTRICTED_FG
    return COLOR_PANEL_BG, COLOR_TEXT_MUTED


def get_priority_color(priority: str) -> str:
    """
    Returns foreground color for packet priority.
    """
    p = str(priority).strip().capitalize()
    if p == "Critical":
        return COLOR_STATUS_FAIL
    elif p == "High":
        return COLOR_STATUS_WARN
    elif p == "Medium":
        return COLOR_ACCENT_LAVENDER
    elif p == "Low":
        return COLOR_STATUS_PASS
    return COLOR_TEXT_PRIMARY
