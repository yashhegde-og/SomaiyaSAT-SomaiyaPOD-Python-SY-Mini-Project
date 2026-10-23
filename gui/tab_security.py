"""
gui/tab_security.py - Security, RBAC, Approval Queue & Audit Trail Console
=========================================================================
Part of the ORBITAL Mission Telemetry System.

Responsibilities:
  1. User administration (operator account list, lockout unlock, active toggle).
  2. Approval Queue (pending_changes review, approve, reject with transactions).
  3. Active Discretionary Access Control (DAC) grants and revocation.
  4. Immutable Audit Trail (audit_events) stream with action filters.
  5. Trigger-generated CDC Change Log (change_log) with old/new JSON diffs.
"""

from __future__ import annotations

import json
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional

import customtkinter as ctk

import security
import theme
from models.governance_queries import (
    create_new_user,
    delete_user_account,
    fetch_all_users,
    fetch_audit_events,
    fetch_change_logs,
    fetch_pending_changes,
    review_pending_change,
    toggle_user_active,
    update_user_profile,
)


class SecurityTab(ctk.CTkFrame):
    """Admin Security, Governance & Audit Management Console."""

    def __init__(self, master: Any, user: security.UserSession, **kwargs):
        super().__init__(master, fg_color=theme.COLOR_BG_DARK, corner_radius=0, **kwargs)

        self.user = user

        # Ensure TTK dark theme (clam, #12111A) is loaded so Treeviews never render white
        theme.init_ttk_styles(self)

        # Build UI layout
        self._create_header()
        self._create_tabview()

    def _create_header(self) -> None:
        """Top header bar with role and clearance indicator."""
        card = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_PANEL_BG,
            corner_radius=10,
            border_width=1,
            border_color=theme.COLOR_PANEL_BORDER,
        )
        card.pack(fill="x", padx=10, pady=(10, 6))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=10)

        ctk.CTkLabel(
            inner,
            text="🛡️ Mission Security & Governance Center",
            font=theme.FONT_TITLE,
            text_color=theme.COLOR_TEXT_PRIMARY,
        ).pack(side="left")

        # Admin Badge
        bg_c, fg_c = theme.get_classification_colors(self.user.clearance_level)
        pill = ctk.CTkFrame(inner, fg_color=bg_c, corner_radius=8)
        pill.pack(side="right")
        ctk.CTkLabel(
            pill,
            text=f"{self.user.role_name.upper()} • CLEARANCE: {self.user.clearance_level.upper()}",
            font=(theme.FONT_FAMILY, 9, "bold"),
            text_color=fg_c,
        ).pack(padx=10, pady=3)

    def _create_tabview(self) -> None:
        """Constructs multi-pane governance notebook."""
        self.tabview = ctk.CTkTabview(
            self,
            fg_color=theme.COLOR_PANEL_BG,
            segmented_button_fg_color="#12111A",
            segmented_button_selected_color=theme.COLOR_ACCENT_HOVER,
            segmented_button_selected_hover_color=theme.COLOR_ACCENT_HOVER,
            segmented_button_unselected_color="#191722",
            segmented_button_unselected_hover_color="#28243C",
            text_color=theme.COLOR_TEXT_PRIMARY,
        )
        self.tabview.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Define Tabs
        t_users = self.tabview.add("Operator Accounts")
        t_queue = self.tabview.add("Approval Queue")
        t_dac = self.tabview.add("DAC Grants")
        t_audit = self.tabview.add("Audit Trail")
        t_cdc = self.tabview.add("CDC Change Log")

        self._build_users_subtab(t_users)
        self._build_queue_subtab(t_queue)
        self._build_dac_subtab(t_dac)
        self._build_audit_subtab(t_audit)
        self._build_cdc_subtab(t_cdc)

    # -------------------------------------------------------------------------
    # SUBTAB 1: OPERATOR ACCOUNTS & LOCKOUT MANAGEMENT
    # -------------------------------------------------------------------------

    def _build_users_subtab(self, parent: Any) -> None:
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", padx=10, pady=8)

        # 1. Provision Operator
        ctk.CTkButton(
            toolbar,
            text="➕ Provision Operator",
            command=self._open_add_user_dialog,
            state="normal" if self.user.is_admin() else "disabled",
            fg_color=theme.COLOR_ACCENT_LAVENDER if self.user.is_admin() else theme.COLOR_PANEL_BORDER,
            hover_color=theme.COLOR_ACCENT_HOVER,
            text_color=theme.COLOR_BG_DARK if self.user.is_admin() else theme.COLOR_TEXT_DISABLED,
            font=theme.FONT_SMALL_BOLD,
            width=140,
            height=28,
        ).pack(side="left", padx=(0, 6))

        # 2. Edit Operator
        ctk.CTkButton(
            toolbar,
            text="✏️ Edit Role / Clearance",
            command=self._open_edit_user_dialog,
            state="normal" if self.user.is_admin() else "disabled",
            fg_color="#201D2C",
            hover_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
            font=theme.FONT_SMALL,
            width=145,
            height=28,
        ).pack(side="left", padx=(0, 6))

        # 3. Toggle Active State
        ctk.CTkButton(
            toolbar,
            text="Toggle Active State",
            command=self._toggle_selected_user,
            state="normal" if self.user.is_admin() else "disabled",
            fg_color="#201D2C",
            hover_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
            font=theme.FONT_SMALL,
            width=130,
            height=28,
        ).pack(side="left", padx=(0, 6))

        # 4. Delete Operator
        ctk.CTkButton(
            toolbar,
            text="🗑️ Delete",
            command=self._delete_selected_user,
            state="normal" if self.user.is_admin() else "disabled",
            fg_color="#3D1820" if self.user.is_admin() else theme.COLOR_PANEL_BORDER,
            hover_color="#5D2028",
            text_color="#F87171" if self.user.is_admin() else theme.COLOR_TEXT_DISABLED,
            font=theme.FONT_SMALL,
            width=80,
            height=28,
        ).pack(side="left", padx=(0, 6))

        # 5. Refresh
        ctk.CTkButton(
            toolbar,
            text="🔄 Refresh",
            command=self._load_users,
            fg_color="transparent",
            text_color=theme.COLOR_TEXT_MUTED,
            font=theme.FONT_SMALL,
            width=80,
            height=28,
        ).pack(side="right")

        # Treeview (Clean operator table without lockout/failure columns)
        cols = ["user_id", "username", "full_name", "email", "role_name", "clearance_level", "is_active"]
        self.tree_users = ttk.Treeview(parent, columns=cols, show="headings", style="Telemetry.Treeview", selectmode="browse")

        headers = ["ID", "Username", "Full Name", "Email", "Role", "Clearance", "Active"]
        for cid, h in zip(cols, headers):
            self.tree_users.heading(cid, text=h)
            self.tree_users.column(cid, width=120, anchor="center")

        self.tree_users.column("full_name", width=220, anchor="w")
        self.tree_users.column("email", width=240, anchor="w")
        self.tree_users.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._load_users()

    def _load_users(self) -> None:
        for item in self.tree_users.get_children():
            self.tree_users.delete(item)
        try:
            self._users_cache = {u["username"]: u for u in fetch_all_users()}
            for u in self._users_cache.values():
                vals = (
                    u["user_id"],
                    u["username"],
                    u["full_name"],
                    u.get("email") or "—",
                    u["role_name"],
                    u["clearance_level"],
                    "Yes" if u["is_active"] else "No",
                )
                self.tree_users.insert("", "end", iid=u["username"], values=vals)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load user accounts: {e}")

    def _open_add_user_dialog(self) -> None:
        """Opens a sleek popup dialog for administrators to provision a new user account."""
        if not self.user.is_admin():
            messagebox.showerror("Access Denied", "Only administrators can provision new users.")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("ORBITAL // Provision Mission Operator")
        dialog.geometry("480x560")
        dialog.resizable(False, False)
        dialog.configure(fg_color=theme.COLOR_PANEL_BG)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        # Center dialog
        dialog.update_idletasks()
        w, h = 480, 560
        x = (dialog.winfo_screenwidth() // 2) - (w // 2)
        y = (dialog.winfo_screenheight() // 2) - (h // 2)
        dialog.geometry(f"{w}x{h}+{x}+{y}")

        title_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        title_frame.pack(fill="x", padx=24, pady=(20, 10))

        ctk.CTkLabel(
            title_frame,
            text="👤 Provision New Mission Operator",
            font=theme.FONT_TITLE,
            text_color=theme.COLOR_TEXT_PRIMARY,
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_frame,
            text="Creates a new account with bcrypt hashing and Bell-LaPadula clearance assignment.",
            font=theme.FONT_SMALL,
            text_color=theme.COLOR_TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        form = ctk.CTkFrame(dialog, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=24, pady=10)

        # 1. Username
        ctk.CTkLabel(form, text="Username (system identifier):", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
        e_user = ctk.CTkEntry(form, height=32, font=theme.FONT_BODY, placeholder_text="e.g. rohit_sharma")
        e_user.pack(fill="x", pady=(2, 8))

        # 2. Full Name
        ctk.CTkLabel(form, text="Full Name & Callout:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
        e_name = ctk.CTkEntry(form, height=32, font=theme.FONT_BODY, placeholder_text="e.g. Rohit Sharma (Flight Dynamics)")
        e_name.pack(fill="x", pady=(2, 8))

        # 3. Email
        ctk.CTkLabel(form, text="Email Address:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
        e_email = ctk.CTkEntry(form, height=32, font=theme.FONT_BODY, placeholder_text="rohit@somaiyasat.edu")
        e_email.pack(fill="x", pady=(2, 8))

        # Row: Role & Clearance
        rc_row = ctk.CTkFrame(form, fg_color="transparent")
        rc_row.pack(fill="x", pady=(2, 8))
        rc_row.columnconfigure((0, 1), weight=1)

        c1 = ctk.CTkFrame(rc_row, fg_color="transparent")
        c1.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkLabel(c1, text="RBAC Role:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
        role_opt = ctk.CTkOptionMenu(c1, values=["Engineer", "Operator", "Viewer", "Admin"], height=32)
        role_opt.set("Engineer")
        role_opt.pack(fill="x", pady=(2, 0))

        c2 = ctk.CTkFrame(rc_row, fg_color="transparent")
        c2.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ctk.CTkLabel(c2, text="Clearance Rank:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
        clearance_opt = ctk.CTkOptionMenu(c2, values=["Internal", "Public", "Restricted"], height=32)
        clearance_opt.set("Internal")
        clearance_opt.pack(fill="x", pady=(2, 0))

        # 4. Password
        ctk.CTkLabel(form, text="Initial Password (min 6 chars):", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
        e_pass = ctk.CTkEntry(form, height=32, font=theme.FONT_BODY, show="•")
        e_pass.insert(0, "Orbital@Ops#2026")
        e_pass.pack(fill="x", pady=(2, 14))

        # Action Buttons
        btn_box = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_box.pack(fill="x", padx=24, pady=(0, 20))

        def on_submit():
            u = e_user.get().strip()
            n = e_name.get().strip()
            em = e_email.get().strip()
            r = role_opt.get()
            cl = clearance_opt.get()
            pw = e_pass.get().strip()

            if not u or not n:
                messagebox.showerror("Validation Error", "Username and Full Name are required.", parent=dialog)
                return
            if len(pw) < 6:
                messagebox.showerror("Validation Error", "Password must be at least 6 characters.", parent=dialog)
                return

            ok, msg = create_new_user(self.user, u, n, em, r, cl, pw)
            if ok:
                messagebox.showinfo("Success", msg, parent=dialog)
                dialog.destroy()
                self._load_users()
            else:
                messagebox.showerror("Error", msg, parent=dialog)

        ctk.CTkButton(
            btn_box,
            text="Cancel",
            command=dialog.destroy,
            fg_color="#201D2C",
            hover_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_MUTED,
            height=36,
            width=100,
        ).pack(side="left")

        ctk.CTkButton(
            btn_box,
            text="Create Operator Account",
            command=on_submit,
            fg_color=theme.COLOR_ACCENT_LAVENDER,
            hover_color=theme.COLOR_ACCENT_HOVER,
            text_color=theme.COLOR_BG_DARK,
            font=theme.FONT_BODY_BOLD,
            height=36,
        ).pack(side="right", fill="x", expand=True, padx=(10, 0))

    def _open_edit_user_dialog(self) -> None:
        """Opens a modal to edit an operator's role, clearance, and details."""
        sel = self.tree_users.selection()
        if not sel:
            messagebox.showinfo("Selection", "Please select an operator account to edit.")
            return

        username = sel[0]
        u = getattr(self, "_users_cache", {}).get(username)
        if not u:
            messagebox.showerror("Error", f"Could not find details for '{username}'.")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"ORBITAL // Edit Operator — {username}")
        dialog.geometry("480x520")
        dialog.resizable(False, False)
        dialog.configure(fg_color=theme.COLOR_PANEL_BG)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        # Center dialog
        dialog.update_idletasks()
        w, h = 480, 520
        x = (dialog.winfo_screenwidth() // 2) - (w // 2)
        y = (dialog.winfo_screenheight() // 2) - (h // 2)
        dialog.geometry(f"{w}x{h}+{x}+{y}")

        title_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        title_frame.pack(fill="x", padx=24, pady=(20, 10))

        ctk.CTkLabel(
            title_frame,
            text=f"✏️ Modify Operator: {username}",
            font=theme.FONT_TITLE,
            text_color=theme.COLOR_HIGHLIGHT_GOLD,
        ).pack(anchor="w")

        form = ctk.CTkFrame(dialog, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=24, pady=10)

        ctk.CTkLabel(form, text="Full Name:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
        e_name = ctk.CTkEntry(form, height=32, font=theme.FONT_BODY)
        e_name.insert(0, u.get("full_name") or "")
        e_name.pack(fill="x", pady=(2, 8))

        ctk.CTkLabel(form, text="Email Address:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
        e_email = ctk.CTkEntry(form, height=32, font=theme.FONT_BODY)
        e_email.insert(0, u.get("email") or "")
        e_email.pack(fill="x", pady=(2, 8))

        rc_row = ctk.CTkFrame(form, fg_color="transparent")
        rc_row.pack(fill="x", pady=(2, 8))
        rc_row.columnconfigure((0, 1), weight=1)

        c1 = ctk.CTkFrame(rc_row, fg_color="transparent")
        c1.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkLabel(c1, text="RBAC Role:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
        role_opt = ctk.CTkOptionMenu(c1, values=["Admin", "Engineer", "Operator", "Viewer"], height=32)
        role_opt.set(u.get("role_name", "Viewer"))
        role_opt.pack(fill="x", pady=(2, 0))

        c2 = ctk.CTkFrame(rc_row, fg_color="transparent")
        c2.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ctk.CTkLabel(c2, text="Clearance Rank:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
        clearance_opt = ctk.CTkOptionMenu(c2, values=["Public", "Internal", "Restricted"], height=32)
        clearance_opt.set(u.get("clearance_level", "Public"))
        clearance_opt.pack(fill="x", pady=(2, 0))

        ctk.CTkLabel(form, text="Reset Password (leave blank to keep current):", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(anchor="w")
        e_pass = ctk.CTkEntry(form, height=32, font=theme.FONT_BODY, show="•", placeholder_text="Optional new password...")
        e_pass.pack(fill="x", pady=(2, 14))

        btn_box = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_box.pack(fill="x", padx=24, pady=(0, 20))

        def on_update():
            n = e_name.get().strip()
            em = e_email.get().strip()
            r = role_opt.get()
            cl = clearance_opt.get()
            pw = e_pass.get().strip()

            if not n:
                messagebox.showerror("Validation Error", "Full Name cannot be empty.", parent=dialog)
                return
            if pw and len(pw) < 6:
                messagebox.showerror("Validation Error", "New password must be at least 6 characters.", parent=dialog)
                return

            ok, msg = update_user_profile(self.user, username, n, em, r, cl, pw if pw else None)
            if ok:
                messagebox.showinfo("Success", msg, parent=dialog)
                dialog.destroy()
                self._load_users()
            else:
                messagebox.showerror("Error", msg, parent=dialog)

        ctk.CTkButton(
            btn_box,
            text="Cancel",
            command=dialog.destroy,
            fg_color="#201D2C",
            hover_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_MUTED,
            height=36,
            width=100,
        ).pack(side="left")

        ctk.CTkButton(
            btn_box,
            text="Save Changes",
            command=on_update,
            fg_color=theme.COLOR_HIGHLIGHT_GOLD,
            hover_color=theme.COLOR_GOLD_HOVER,
            text_color=theme.COLOR_BG_DARK,
            font=theme.FONT_BODY_BOLD,
            height=36,
        ).pack(side="right", fill="x", expand=True, padx=(10, 0))

    def _delete_selected_user(self) -> None:
        """Deletes selected user account after confirmation."""
        sel = self.tree_users.selection()
        if not sel:
            messagebox.showinfo("Selection", "Please select an operator to delete.")
            return

        username = sel[0]
        if not messagebox.askyesno("Confirm Deletion", f"Permanently delete operator account '{username}'?"):
            return

        ok, msg = delete_user_account(self.user, username)
        if ok:
            messagebox.showinfo("Deleted", msg)
            self._load_users()
        else:
            messagebox.showerror("Error", msg)

    def _toggle_selected_user(self) -> None:
        sel = self.tree_users.selection()
        if not sel:
            messagebox.showinfo("Selection", "Please select a user.")
            return
        username = sel[0]
        ok, msg = toggle_user_active(self.user, username)
        if ok:
            messagebox.showinfo("Success", msg)
            self._load_users()
        else:
            messagebox.showerror("Error", msg)

    # -------------------------------------------------------------------------
    # SUBTAB 2: APPROVAL QUEUE (pending_changes)
    # -------------------------------------------------------------------------

    def _build_queue_subtab(self, parent: Any) -> None:
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", padx=10, pady=8)

        ctk.CTkButton(
            toolbar,
            text="✓ Approve Change",
            command=lambda: self._review_queue_item(True),
            state="normal" if self.user.can("approve_changes") else "disabled",
            fg_color=theme.COLOR_STATUS_PASS if self.user.can("approve_changes") else theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_BG_DARK if self.user.can("approve_changes") else theme.COLOR_TEXT_DISABLED,
            font=theme.FONT_SMALL,
            width=130,
            height=28,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            toolbar,
            text="✗ Reject Change",
            command=lambda: self._review_queue_item(False),
            state="normal" if self.user.can("approve_changes") else "disabled",
            fg_color=theme.COLOR_STATUS_FAIL if self.user.can("approve_changes") else theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY if self.user.can("approve_changes") else theme.COLOR_TEXT_DISABLED,
            font=theme.FONT_SMALL,
            width=120,
            height=28,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            toolbar,
            text="🔄 Refresh",
            command=self._load_queue,
            fg_color="transparent",
            text_color=theme.COLOR_TEXT_MUTED,
            font=theme.FONT_SMALL,
            width=80,
            height=28,
        ).pack(side="right")

        cols = ["change_id", "requested_at", "requested_by", "action_type", "target_table", "target_record_id", "status"]
        self.tree_queue = ttk.Treeview(parent, columns=cols, show="headings", style="Telemetry.Treeview", selectmode="browse")

        headers = ["#ID", "Requested Time", "Requester", "Action", "Target Table", "Target Record", "Status"]
        for cid, h in zip(cols, headers):
            self.tree_queue.heading(cid, text=h)
            self.tree_queue.column(cid, width=110, anchor="center")

        self.tree_queue.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._load_queue()

    def _load_queue(self) -> None:
        for item in self.tree_queue.get_children():
            self.tree_queue.delete(item)
        try:
            items = fetch_pending_changes("PENDING")
            for it in items:
                vals = (
                    it["change_id"],
                    str(it["requested_at"])[:19],
                    it["requested_by"],
                    it["action_type"],
                    it["target_table"],
                    f"#{it['target_record_id']}",
                    it["status"],
                )
                self.tree_queue.insert("", "end", iid=str(it["change_id"]), values=vals)
        except Exception:
            pass

    def _review_queue_item(self, approve: bool) -> None:
        sel = self.tree_queue.selection()
        if not sel:
            messagebox.showinfo("Selection", "Please select a pending change request from the queue.")
            return

        cid = int(sel[0])
        action = "APPROVE" if approve else "REJECT"
        dialog = ctk.CTkInputDialog(
            text=f"Enter review comments for {action} change #{cid}:",
            title=f"{action.title()} Pending Change",
        )
        comments = dialog.get_input() or ""

        ok, msg = review_pending_change(self.user, cid, approve, comments)
        if ok:
            messagebox.showinfo("Processed", msg)
            self._load_queue()
        else:
            messagebox.showerror("Error", msg)

    # -------------------------------------------------------------------------
    # SUBTAB 3: DISCRETIONARY ACCESS GRANTS (dac_grants)
    # -------------------------------------------------------------------------

    def _build_dac_subtab(self, parent: Any) -> None:
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", padx=10, pady=8)

        ctk.CTkButton(
            toolbar,
            text="Revoke Grant",
            command=self._revoke_selected_dac,
            state="normal" if self.user.is_admin() else "disabled",
            fg_color=theme.COLOR_STATUS_FAIL if self.user.is_admin() else theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY if self.user.is_admin() else theme.COLOR_TEXT_DISABLED,
            font=theme.FONT_SMALL,
            width=120,
            height=28,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            toolbar,
            text="🔄 Refresh",
            command=self._load_dac,
            fg_color="transparent",
            text_color=theme.COLOR_TEXT_MUTED,
            font=theme.FONT_SMALL,
            width=80,
            height=28,
        ).pack(side="right")

        cols = ["grant_id", "granter_username", "grantee_username", "target_type", "target_packet_id", "permission", "granted_at"]
        self.tree_dac = ttk.Treeview(parent, columns=cols, show="headings", style="Telemetry.Treeview", selectmode="browse")

        headers = ["Grant ID", "Granter", "Grantee", "Target Type", "Packet ID", "Permission", "Granted At"]
        for cid, h in zip(cols, headers):
            self.tree_dac.heading(cid, text=h)
            self.tree_dac.column(cid, width=110, anchor="center")

        self.tree_dac.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._load_dac()

    def _load_dac(self) -> None:
        for item in self.tree_dac.get_children():
            self.tree_dac.delete(item)
        try:
            grants = security.list_active_dac_grants()
            for g in grants:
                vals = (
                    g["grant_id"],
                    g["granter_username"],
                    g["grantee_username"],
                    g["target_type"],
                    f"#{g['target_packet_id']}" if g["target_packet_id"] else "—",
                    g["permission"],
                    str(g["granted_at"])[:19],
                )
                self.tree_dac.insert("", "end", iid=str(g["grant_id"]), values=vals)
        except Exception:
            pass

    def _revoke_selected_dac(self) -> None:
        sel = self.tree_dac.selection()
        if not sel:
            messagebox.showinfo("Selection", "Select a grant to revoke.")
            return
        gid = int(sel[0])
        ok, msg = security.revoke_dac_permission(self.user, gid)
        if ok:
            messagebox.showinfo("Success", msg)
            self._load_dac()
        else:
            messagebox.showerror("Error", msg)

    # -------------------------------------------------------------------------
    # SUBTAB 4: IMMUTABLE AUDIT TRAIL (audit_events)
    # -------------------------------------------------------------------------

    def _build_audit_subtab(self, parent: Any) -> None:
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", padx=10, pady=8)

        ctk.CTkLabel(toolbar, text="Filter Action:", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_MUTED).pack(side="left", padx=(0, 4))
        self.audit_action_combo = ctk.CTkComboBox(
            toolbar,
            values=["All", "LOGIN_SUCCESS", "LOGIN_FAILED", "ACCOUNT_LOCKED", "INSERT_PACKET", "UPDATE_PACKET", "DELETE_PACKET", "SQL_DRY_RUN", "DAC_GRANT"],
            command=lambda v: self._load_audit(),
            width=180,
            height=28,
            font=theme.FONT_SMALL,
            fg_color=theme.COLOR_INPUT_BG,
            border_color=theme.COLOR_PANEL_BORDER,
            text_color=theme.COLOR_TEXT_PRIMARY,
        )
        self.audit_action_combo.set("All")
        self.audit_action_combo.pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            toolbar,
            text="🔄 Refresh",
            command=self._load_audit,
            fg_color="transparent",
            text_color=theme.COLOR_TEXT_MUTED,
            font=theme.FONT_SMALL,
            width=80,
            height=28,
        ).pack(side="right")

        cols = ["event_id", "timestamp_utc", "username", "action_type", "target_table", "status", "details"]
        self.tree_audit = ttk.Treeview(parent, columns=cols, show="headings", style="Telemetry.Treeview", selectmode="browse")

        headers = ["#ID", "Timestamp (UTC)", "Operator", "Action", "Target", "Status", "Details"]
        for cid, h in zip(cols, headers):
            self.tree_audit.heading(cid, text=h)
            self.tree_audit.column(cid, width=100, anchor="center")

        self.tree_audit.column("details", width=340, anchor="w")
        self.tree_audit.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._load_audit()

    def _load_audit(self) -> None:
        for item in self.tree_audit.get_children():
            self.tree_audit.delete(item)
        action_f = self.audit_action_combo.get()
        try:
            events = fetch_audit_events(self.user, limit=100, action_filter=action_f)
            for e in events:
                vals = (
                    e["event_id"],
                    str(e["timestamp_utc"])[:19],
                    e["username"],
                    e["action_type"],
                    e["target_table"] or "—",
                    e["status"],
                    e["details"],
                )
                self.tree_audit.insert("", "end", iid=str(e["event_id"]), values=vals)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # SUBTAB 5: CDC CHANGE LOG (change_log)
    # -------------------------------------------------------------------------

    def _build_cdc_subtab(self, parent: Any) -> None:
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", padx=10, pady=8)

        ctk.CTkLabel(
            toolbar,
            text="Trigger-populated Change Data Capture (CDC) table tracking row modifications",
            font=theme.FONT_SMALL,
            text_color=theme.COLOR_HIGHLIGHT_GOLD,
        ).pack(side="left")

        ctk.CTkButton(
            toolbar,
            text="🔄 Refresh",
            command=self._load_cdc,
            fg_color="transparent",
            text_color=theme.COLOR_TEXT_MUTED,
            font=theme.FONT_SMALL,
            width=80,
            height=28,
        ).pack(side="right")

        cols = ["log_id", "changed_at", "changed_by", "action", "table_name", "record_id", "diff"]
        self.tree_cdc = ttk.Treeview(parent, columns=cols, show="headings", style="Telemetry.Treeview", selectmode="browse")

        headers = ["#Log ID", "Changed At", "Operator", "Action", "Table", "Record ID", "New Values / Diff"]
        for cid, h in zip(cols, headers):
            self.tree_cdc.heading(cid, text=h)
            self.tree_cdc.column(cid, width=100, anchor="center")

        self.tree_cdc.column("diff", width=380, anchor="w")
        self.tree_cdc.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._load_cdc()

    def _load_cdc(self) -> None:
        for item in self.tree_cdc.get_children():
            self.tree_cdc.delete(item)
        try:
            logs = fetch_change_logs(limit=100)
            for l in logs:
                diff_summary = ""
                if l["new_values"]:
                    diff_summary = str(l["new_values"])[:80] + "..."
                elif l["old_values"]:
                    diff_summary = f"Deleted: {str(l['old_values'])[:60]}..."

                vals = (
                    l["log_id"],
                    str(l["changed_at"])[:19],
                    l["changed_by"],
                    l["action"],
                    l["table_name"],
                    f"#{l['record_id']}",
                    diff_summary,
                )
                self.tree_cdc.insert("", "end", iid=str(l["log_id"]), values=vals)
        except Exception:
            pass
