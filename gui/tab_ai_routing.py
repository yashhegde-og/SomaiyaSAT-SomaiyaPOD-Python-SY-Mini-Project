"""
gui/tab_ai_routing.py - AI Inter-Satellite Routing & Scikit-Learn ML Simulator
==============================================================================
Part of the ORBITAL Mission Telemetry System.

Responsibilities:
  1. AI Autonomous Routing Decision Engine Analysis:
     - Direct-to-Ground, Relay-via-SomaiyaPod, and Store-and-Forward metrics.
     - Matplotlib embedded dark chart for decision volume and average confidence.
  2. Scikit-Learn Machine Learning Priority Classifier:
     - Trains a RandomForestClassifier directly on PostgreSQL telemetry.
     - Computes validation accuracy and feature importance rankings.
     - Interactive live simulator for operators to input link/power telemetry
       and predict packet_priority with probability breakdown.
"""

from __future__ import annotations

import threading
from tkinter import messagebox
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


class AIRoutingAnalyticsTab(ctk.CTkFrame):
    """
    AI Routing & Machine Learning Analytics Tab featuring embedded
    dark charts and an interactive scikit-learn packet priority simulator.
    """

    def __init__(self, master: Any, user: security.UserSession, **kwargs):
        super().__init__(master, fg_color=theme.COLOR_BG_DARK, corner_radius=0, **kwargs)
        self.user = user
        self.ml_predictor = analytics_queries.get_priority_predictor()

        # Scrollable container
        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=theme.COLOR_PANEL_BG,
            corner_radius=12,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        self.scroll.pack(fill="both", expand=True, padx=8, pady=8)

        self._create_header_and_kpis()
        self._create_main_content_split()

        # Load AI metrics and auto-train model asynchronously
        self.after(100, self._load_data_and_train_model)

    # =========================================================================
    # 1. HEADER & DECISION SUMMARY CARDS
    # =========================================================================

    def _create_header_and_kpis(self) -> None:
        """Top bar and 3 decision summary cards."""
        top_bar = ctk.CTkFrame(self.scroll, fg_color="transparent")
        top_bar.pack(fill="x", padx=16, pady=(14, 10))

        title = ctk.CTkLabel(
            top_bar,
            text="🧠 Autonomous Inter-Satellite AI Data Routing & Predictive ML",
            font=theme.FONT_TITLE,
            text_color=theme.COLOR_TEXT_PRIMARY,
        )
        title.pack(side="left")

        # Decision Summary Cards Container
        self.cards_frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.cards_frame.pack(fill="x", padx=16, pady=(0, 14))
        self.cards_frame.columnconfigure((0, 1, 2), weight=1)

        self.decision_cards: Dict[str, Tuple[ctk.CTkLabel, ctk.CTkLabel]] = {}
        specs = [
            ("Direct-to-Ground", "📡 DIRECT-TO-GROUND", "Loading...", theme.COLOR_ACCENT_LAVENDER),
            ("Relay-via-SomaiyaPod", "🛰️ RELAY VIA SOMAIYAPOD", "Loading...", theme.COLOR_HIGHLIGHT_GOLD),
            ("Store-and-Forward", "💾 STORE-AND-FORWARD", "Loading...", theme.COLOR_STATUS_PASS),
        ]

        for idx, (key, label_text, init_val, color) in enumerate(specs):
            card = ctk.CTkFrame(
                self.cards_frame,
                fg_color=theme.COLOR_INPUT_BG,
                corner_radius=10,
                border_width=1,
                border_color=theme.COLOR_PANEL_BORDER,
            )
            card.grid(row=0, column=idx, padx=6, pady=4, sticky="nsew")

            t_lbl = ctk.CTkLabel(card, text=label_text, font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED)
            t_lbl.pack(anchor="w", padx=14, pady=(10, 2))

            v_lbl = ctk.CTkLabel(card, text=init_val, font=theme.FONT_TITLE, text_color=color)
            v_lbl.pack(anchor="w", padx=14, pady=(0, 10))

            self.decision_cards[key] = (t_lbl, v_lbl)

    # =========================================================================
    # 2. MAIN CONTENT SPLIT (LEFT: CHARTS, RIGHT: ML SIMULATOR)
    # =========================================================================

    def _create_main_content_split(self) -> None:
        """Left side: Matplotlib charts. Right side: Interactive ML Simulator."""
        split_frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        split_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        split_frame.columnconfigure(0, weight=6)
        split_frame.columnconfigure(1, weight=5)

        # Left: Matplotlib Charts Box
        self.charts_box = ctk.CTkFrame(
            split_frame,
            fg_color=theme.COLOR_INPUT_BG,
            corner_radius=10,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        self.charts_box.grid(row=0, column=0, padx=(0, 8), sticky="nsew")

        ctk.CTkLabel(
            self.charts_box,
            text="📊 AI Routing Decisions & ML Feature Importance",
            font=theme.FONT_SUBTITLE,
            text_color=theme.COLOR_ACCENT_LAVENDER,
        ).pack(anchor="w", padx=14, pady=(12, 6))

        self.charts_canvas_container = ctk.CTkFrame(self.charts_box, fg_color="transparent")
        self.charts_canvas_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Right: ML Simulator Box
        sim_box = ctk.CTkFrame(
            split_frame,
            fg_color=theme.COLOR_INPUT_BG,
            corner_radius=10,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        sim_box.grid(row=0, column=1, padx=(8, 0), sticky="nsew")

        self._build_ml_simulator_ui(sim_box)

    # =========================================================================
    # 3. INTERACTIVE SCIKIT-LEARN SIMULATOR UI
    # =========================================================================

    def _build_ml_simulator_ui(self, container: ctk.CTkFrame) -> None:
        """Builds telemetry input controls for live scikit-learn priority prediction."""
        title_row = ctk.CTkFrame(container, fg_color="transparent")
        title_row.pack(fill="x", padx=14, pady=(12, 4))

        ctk.CTkLabel(
            title_row,
            text="🤖 Live Priority Prediction Engine",
            font=theme.FONT_SUBTITLE,
            text_color=theme.COLOR_HIGHLIGHT_GOLD,
        ).pack(side="left")

        self.model_status_badge = ctk.CTkLabel(
            title_row,
            text="● Training...",
            font=theme.FONT_SMALL_BOLD,
            text_color=theme.COLOR_HIGHLIGHT_GOLD,
        )
        self.model_status_badge.pack(side="right")

        # Feature Inputs Grid
        inputs_frame = ctk.CTkFrame(container, fg_color="transparent")
        inputs_frame.pack(fill="x", padx=14, pady=8)
        inputs_frame.columnconfigure((0, 1), weight=1)

        self.feature_inputs: Dict[str, ctk.CTkEntry] = {}

        # Telemetry fields with physical boundaries
        self.feature_limits = {
            "battery_soc_percent": (0.0, 100.0, "Battery State of Charge must be between 0.0% and 100.0%"),
            "battery_voltage_v": (2.5, 4.5, "Battery Voltage must be between 2.5 V and 4.5 V"),
            "solar_current_ma": (0.0, 2500.0, "Solar Panel Current must be between 0.0 mA and 2,500.0 mA"),
            "onboard_temp_c": (-45.0, 85.0, "Onboard Temperature must be between -45.0 °C and 85.0 °C"),
            "rssi_dbm": (-140.0, 0.0, "RSSI must be between -140.0 dBm and 0.0 dBm"),
            "snr_db": (-25.0, 45.0, "SNR must be between -25.0 dB and 45.0 dB"),
            "data_rate_bps": (100.0, 1000000.0, "Data Rate must be between 100 bps and 1,000,000 bps"),
            "packet_size_bytes": (16.0, 4096.0, "Packet Size must be between 16 and 4,096 bytes"),
            "bit_error_rate": (0.0, 1.0, "Bit Error Rate (BER) must be between 0.0 and 1.0"),
            "ai_confidence_score": (0.0, 1.0, "AI Confidence Score must be between 0.0 and 1.0"),
        }

        fields = [
            ("battery_soc_percent", "Battery SOC (%): [0 - 100%]", "78.0"),
            ("battery_voltage_v", "Battery Voltage (V): [2.5 - 4.5 V]", "3.85"),
            ("solar_current_ma", "Solar Current (mA): [0 - 2500 mA]", "320.0"),
            ("onboard_temp_c", "Onboard Temp (°C): [-45 - 85 °C]", "21.5"),
            ("rssi_dbm", "RSSI (dBm): [-140 - 0 dBm]", "-92.0"),
            ("snr_db", "SNR (dB): [-25 - 45 dB]", "14.0"),
            ("data_rate_bps", "Data Rate (bps): [100 - 1M bps]", "9600"),
            ("packet_size_bytes", "Packet Size (bytes): [16 - 4096]", "128"),
            ("bit_error_rate", "Bit Error Rate (BER): [0.0 - 1.0]", "0.00015"),
            ("ai_confidence_score", "AI Confidence Score: [0.0 - 1.0]", "0.85"),
        ]

        for idx, (fkey, flabel, fdefault) in enumerate(fields):
            r = idx // 2
            c = idx % 2

            cell = ctk.CTkFrame(inputs_frame, fg_color="transparent")
            cell.grid(row=r, column=c, padx=6, pady=4, sticky="ew")

            ctk.CTkLabel(cell, text=flabel, font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
            entry = ctk.CTkEntry(
                cell,
                height=28,
                font=theme.FONT_BODY,
                fg_color=theme.COLOR_PANEL_BG,
                border_color=theme.COLOR_PANEL_BORDER,
                text_color=theme.COLOR_TEXT_PRIMARY,
            )
            entry.insert(0, fdefault)
            entry.pack(fill="x", pady=(2, 0))
            self.feature_inputs[fkey] = entry

        # Action Buttons
        btn_row = ctk.CTkFrame(container, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(10, 8))

        predict_btn = ctk.CTkButton(
            btn_row,
            text="⚡ Run Priority Prediction",
            command=self._handle_predict,
            height=34,
            font=theme.FONT_BODY_BOLD,
            fg_color=theme.COLOR_ACCENT_LAVENDER,
            hover_color=theme.COLOR_ACCENT_HOVER,
            text_color=theme.COLOR_BG_DARK,
        )
        predict_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        retrain_btn = ctk.CTkButton(
            btn_row,
            text="🔄 Retrain ML",
            command=self._retrain_model_async,
            width=100,
            height=34,
            font=theme.FONT_SMALL_BOLD,
            fg_color=theme.COLOR_PANEL_BG,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
            hover_color="#2B283A",
            text_color=theme.COLOR_TEXT_PRIMARY,
        )
        retrain_btn.pack(side="right")

        # Prediction Output Card
        self.pred_card = ctk.CTkFrame(
            container,
            fg_color=theme.COLOR_PANEL_BG,
            corner_radius=8,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        self.pred_card.pack(fill="x", padx=14, pady=(4, 14))

        ctk.CTkLabel(
            self.pred_card,
            text="PREDICTED PACKET PRIORITY",
            font=theme.FONT_SMALL,
            text_color=theme.COLOR_TEXT_MUTED,
        ).pack(anchor="w", padx=14, pady=(10, 2))

        self.pred_result_lbl = ctk.CTkLabel(
            self.pred_card,
            text="Awaiting Inference...",
            font=theme.FONT_TITLE_LARGE,
            text_color=theme.COLOR_TEXT_PRIMARY,
        )
        self.pred_result_lbl.pack(anchor="w", padx=14, pady=(0, 6))

        self.pred_probs_lbl = ctk.CTkLabel(
            self.pred_card,
            text="",
            font=theme.FONT_SMALL,
            text_color=theme.COLOR_TEXT_MUTED,
            justify="left",
        )
        self.pred_probs_lbl.pack(anchor="w", padx=14, pady=(0, 10))

    def _handle_predict(self) -> None:
        """Parses user input telemetry values and executes ML inference."""
        if not self.ml_predictor.is_trained:
            messagebox.showwarning("Model Not Ready", "The Scikit-Learn model is still training. Please wait a moment.")
            return

        try:
            feats: Dict[str, float] = {}
            for k, entry in self.feature_inputs.items():
                raw_txt = entry.get().strip()
                if not raw_txt:
                    messagebox.showerror("Validation Error", f"Field '{k}' cannot be empty.")
                    entry.focus()
                    return

                val = float(raw_txt)

                # Strict Physical Boundary & Range Check
                if k in self.feature_limits:
                    min_v, max_v, err_msg = self.feature_limits[k]
                    if val < min_v or val > max_v:
                        messagebox.showerror(
                            "Out of Bounds Error",
                            f"Input value '{val}' is outside permitted mission limits.\n\n{err_msg} (Entered: {val}).",
                        )
                        entry.focus()
                        return

                feats[k] = val

            pred_class, probs = self.ml_predictor.predict(feats)

            # Color badge by class
            class_colors = {
                "Critical": theme.COLOR_STATUS_FAIL,
                "High": theme.COLOR_ACCENT_LAVENDER,
                "Medium": theme.COLOR_HIGHLIGHT_GOLD,
                "Low": theme.COLOR_TEXT_MUTED,
            }

            self.pred_result_lbl.configure(
                text=f"● {pred_class.upper()} PRIORITY",
                text_color=class_colors.get(pred_class, theme.COLOR_TEXT_PRIMARY),
            )

            # Format probabilities
            prob_strs = [f"{cls}: {p*100:.1f}%" for cls, p in sorted(probs.items(), key=lambda x: x[1], reverse=True)]
            self.pred_probs_lbl.configure(text="Confidence:  " + "   |   ".join(prob_strs))

        except ValueError as err:
            messagebox.showerror("Input Error", f"Invalid numeric value in telemetry fields: {err}")
        except Exception as exc:
            messagebox.showerror("Prediction Error", f"Error during model inference: {exc}")

    # =========================================================================
    # 4. BACKGROUND LOADER & MODEL TRAINING
    # =========================================================================

    def _load_data_and_train_model(self) -> None:
        """Fetches routing distribution and trains RandomForestClassifier."""
        def worker():
            try:
                # 1. Fetch AI distribution
                df_routing = analytics_queries.fetch_ai_routing_distribution(self.user)

                # 2. Train ML model
                acc = self.ml_predictor.train_on_database(self.user, sample_size=12000)

                self.after(0, lambda: self._update_cards(df_routing))
                self.after(0, lambda: self._update_model_status(acc))
                self.after(0, lambda: self._render_charts(df_routing, self.ml_predictor.feature_importances))
            except Exception as exc:
                print(f"[!] AI Routing error: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _retrain_model_async(self) -> None:
        """Triggers manual retraining of the scikit-learn model."""
        self.model_status_badge.configure(text="● Retraining...", text_color=theme.COLOR_HIGHLIGHT_GOLD)

        def worker():
            try:
                acc = self.ml_predictor.train_on_database(self.user, sample_size=15000)
                self.after(0, lambda: self._update_model_status(acc))
                df_routing = analytics_queries.fetch_ai_routing_distribution(self.user)
                self.after(0, lambda: self._render_charts(df_routing, self.ml_predictor.feature_importances))
                self.after(0, lambda: messagebox.showinfo("Retraining Complete", f"RandomForest model retrained.\nAccuracy: {acc*100:.2f}%"))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Retraining Failed", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _update_cards(self, df: pd.DataFrame) -> None:
        """Updates decision summary cards."""
        for _, row in df.iterrows():
            dec = row["decision"]
            cnt = int(row["count"])
            conf = float(row["avg_confidence"])
            if dec in self.decision_cards:
                self.decision_cards[dec][1].configure(text=f"{cnt:,} pkts ({conf:.1f}% conf)")

    def _update_model_status(self, acc: float) -> None:
        """Displays model accuracy badge."""
        self.model_status_badge.configure(
            text=f"● RandomForest Model (Accuracy: {acc*100:.1f}%)",
            text_color=theme.COLOR_STATUS_PASS,
        )

    def _render_charts(self, df_routing: pd.DataFrame, feat_importances: Dict[str, float]) -> None:
        """Renders 2 dark matplotlib charts: Decision volume & Feature importances."""
        for child in self.charts_canvas_container.winfo_children():
            child.destroy()

        plt.close("all")

        bg_color = "#100E17"
        text_color = "#F3F0FA"
        muted_color = "#B8B4C7"
        grid_color = "#2B283A"

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(6.5, 6.2), facecolor=bg_color)
        fig.subplots_adjust(hspace=0.45, left=0.25, right=0.95, top=0.92, bottom=0.10)

        # ---------------------------------------------------------------------
        # Chart 1: AI Routing Decisions Volume & Confidence
        # ---------------------------------------------------------------------
        ax1.set_facecolor(bg_color)
        ax1.grid(True, linestyle="--", alpha=0.3, color=grid_color, axis="x")

        if not df_routing.empty:
            labels = [d.replace("-", " ") for d in df_routing["decision"]]
            palette = ["#A78BFA", "#D5B16D", "#38BDF8"]
            ax1.barh(labels, df_routing["count"], color=palette[:len(df_routing)], alpha=0.85, height=0.55)

        ax1.set_title("Autonomous AI Routing Decisions", color=text_color, fontsize=10, fontweight="bold")
        ax1.set_xlabel("Packets Routed", color=muted_color, fontsize=8.5)
        ax1.tick_params(colors=muted_color, labelsize=8)
        for spine in ax1.spines.values():
            spine.set_color(grid_color)

        # ---------------------------------------------------------------------
        # Chart 2: Scikit-Learn Feature Importance Ranking
        # ---------------------------------------------------------------------
        ax2.set_facecolor(bg_color)
        ax2.grid(True, linestyle="--", alpha=0.3, color=grid_color, axis="x")

        if feat_importances:
            sorted_feats = sorted(feat_importances.items(), key=lambda x: x[1])
            f_names = [f[0].replace("_", " ") for f in sorted_feats]
            f_vals = [f[1] for f in sorted_feats]

            ax2.barh(f_names, f_vals, color="#10B981", alpha=0.8, height=0.6)

        ax2.set_title("ML Feature Importance (Priority Predictor)", color=text_color, fontsize=10, fontweight="bold")
        ax2.set_xlabel("Relative Importance Weight", color=muted_color, fontsize=8.5)
        ax2.tick_params(colors=muted_color, labelsize=8)
        for spine in ax2.spines.values():
            spine.set_color(grid_color)

        # Embed into CTk frame
        canvas = FigureCanvasTkAgg(fig, master=self.charts_canvas_container)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
