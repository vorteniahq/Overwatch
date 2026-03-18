"""Dashboard GUI for viewing events and monitor status."""

import logging
import tkinter as tk
from tkinter import ttk
from datetime import datetime, timedelta

log = logging.getLogger("winmon.gui.dashboard")


class DashboardGUI:
    """Event viewer and status dashboard."""

    def __init__(self, engine):
        self.engine = engine
        self.root = None
        self._auto_refresh = True

    def run(self):
        """Show the dashboard window."""
        self.root = tk.Tk()
        self.root.title("Overwatch Dashboard")
        self.root.geometry("900x600")

        # Top: Status bar
        status_frame = ttk.LabelFrame(self.root, text="Status", padding=10)
        status_frame.pack(fill="x", padx=10, pady=(10, 5))

        self._status_label = ttk.Label(status_frame, text="Loading...")
        self._status_label.pack(side="left")

        ttk.Button(status_frame, text="Refresh",
                   command=self._refresh).pack(side="right", padx=5)
        ttk.Button(status_frame, text="Settings",
                   command=self._open_settings).pack(side="right", padx=5)

        # Middle: Event filter controls
        filter_frame = ttk.Frame(self.root, padding=5)
        filter_frame.pack(fill="x", padx=10)

        ttk.Label(filter_frame, text="Category:").pack(side="left", padx=5)
        self._cat_var = tk.StringVar(value="all")
        cat_combo = ttk.Combobox(filter_frame, textvariable=self._cat_var,
                                 values=["all", "login", "process", "usb",
                                         "rdp", "filesystem", "system"],
                                 width=15, state="readonly")
        cat_combo.pack(side="left", padx=5)
        cat_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh())

        ttk.Label(filter_frame, text="Severity:").pack(side="left", padx=5)
        self._sev_var = tk.StringVar(value="all")
        sev_combo = ttk.Combobox(filter_frame, textvariable=self._sev_var,
                                 values=["all", "info", "warning", "critical"],
                                 width=12, state="readonly")
        sev_combo.pack(side="left", padx=5)
        sev_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh())

        ttk.Label(filter_frame, text="Time:").pack(side="left", padx=5)
        self._time_var = tk.StringVar(value="today")
        time_combo = ttk.Combobox(filter_frame, textvariable=self._time_var,
                                  values=["1h", "today", "24h", "7d", "30d", "all"],
                                  width=10, state="readonly")
        time_combo.pack(side="left", padx=5)
        time_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh())

        # Event table
        table_frame = ttk.Frame(self.root)
        table_frame.pack(fill="both", expand=True, padx=10, pady=5)

        columns = ("time", "category", "severity", "summary")
        self._tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                  selectmode="browse")
        self._tree.heading("time", text="Time")
        self._tree.heading("category", text="Category")
        self._tree.heading("severity", text="Severity")
        self._tree.heading("summary", text="Summary")

        self._tree.column("time", width=160, minwidth=140)
        self._tree.column("category", width=100, minwidth=80)
        self._tree.column("severity", width=80, minwidth=60)
        self._tree.column("summary", width=500, minwidth=200)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical",
                                  command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)

        self._tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # Bottom: Details
        details_frame = ttk.LabelFrame(self.root, text="Details", padding=5)
        details_frame.pack(fill="x", padx=10, pady=(0, 10))

        self._details_text = tk.Text(details_frame, height=6, wrap="word",
                                     state="disabled")
        self._details_text.pack(fill="x")

        # Initial load
        self._refresh()
        self._schedule_refresh()
        self.root.mainloop()

    def _refresh(self):
        """Reload events from database."""
        try:
            # Update status
            status = self.engine.get_status()
            stats = status.get("stats", {})
            today_total = sum(stats.get("today", {}).values())
            hour_total = sum(stats.get("last_hour", {}).values())
            self._status_label.config(
                text=(f"Monitors: {status['monitors']} active | "
                      f"Events today: {today_total} | Last hour: {hour_total}")
            )

            # Build filters
            category = self._cat_var.get()
            severity = self._sev_var.get()
            time_filter = self._time_var.get()

            kwargs = {"limit": 500}
            if category != "all":
                kwargs["category"] = category
            if severity != "all":
                kwargs["severity"] = severity

            now = datetime.now()
            if time_filter == "1h":
                kwargs["since"] = (now - timedelta(hours=1)).isoformat()
            elif time_filter == "today":
                kwargs["since"] = now.replace(hour=0, minute=0, second=0).isoformat()
            elif time_filter == "24h":
                kwargs["since"] = (now - timedelta(days=1)).isoformat()
            elif time_filter == "7d":
                kwargs["since"] = (now - timedelta(days=7)).isoformat()
            elif time_filter == "30d":
                kwargs["since"] = (now - timedelta(days=30)).isoformat()

            events = self.engine.db.get_events(**kwargs)

            # Populate table
            self._tree.delete(*self._tree.get_children())
            self._event_details = {}

            for ev in events:
                ts = ev["timestamp"][:19].replace("T", " ")
                iid = self._tree.insert("", "end", values=(
                    ts, ev["category"], ev["severity"], ev["summary"]
                ))
                self._event_details[iid] = ev.get("details", "")

                # Color severity
                if ev["severity"] == "warning":
                    self._tree.tag_configure("warning", foreground="#CC7700")
                    self._tree.item(iid, tags=("warning",))
                elif ev["severity"] == "critical":
                    self._tree.tag_configure("critical", foreground="#CC0000")
                    self._tree.item(iid, tags=("critical",))

        except Exception as e:
            log.error("Dashboard refresh error: %s", e)

    def _schedule_refresh(self):
        """Auto-refresh every 10 seconds."""
        if self._auto_refresh and self.root:
            try:
                self._refresh()
                self.root.after(10000, self._schedule_refresh)
            except Exception:
                pass

    def _on_select(self, event):
        """Show details of selected event."""
        sel = self._tree.selection()
        if not sel:
            return
        details = self._event_details.get(sel[0], "No details available")
        self._details_text.config(state="normal")
        self._details_text.delete("1.0", "end")
        self._details_text.insert("1.0", details or "No details")
        self._details_text.config(state="disabled")

    def _open_settings(self):
        """Open the settings window."""
        import threading
        from winmon.gui.settings import SettingsGUI
        threading.Thread(
            target=lambda: SettingsGUI(self.engine.config).run(),
            daemon=True
        ).start()
