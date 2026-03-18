"""GUI settings panel for configuring Overwatch monitoring rules."""

import logging
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

log = logging.getLogger("winmon.gui.settings")


class SettingsGUI:
    """Tkinter-based configuration GUI for Overwatch."""

    def __init__(self, config):
        self.config = config
        self.root = None

    def run(self):
        """Create and show the settings window."""
        self.root = tk.Tk()
        self.root.title("Overwatch Settings")
        self.root.geometry("650x580")
        self.root.resizable(True, True)

        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # Tab: General
        self._build_general_tab(notebook)
        # Tab: Telegram
        self._build_telegram_tab(notebook)
        # Tab: Silent Hours
        self._build_silent_tab(notebook)
        # Tab: Monitors
        self._build_monitors_tab(notebook)
        # Tab: Process Watchlist
        self._build_watchlist_tab(notebook)
        # Tab: File Watch Paths
        self._build_filepaths_tab(notebook)
        # Tab: Database
        self._build_database_tab(notebook)

        # Bottom buttons
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.root.destroy).pack(side="right")

        self.root.mainloop()

    def _has_startup_shortcut(self):
        """Check if startup shortcut exists."""
        startup_dir = os.path.join(
            os.environ.get("APPDATA", ""), "Microsoft", "Windows",
            "Start Menu", "Programs", "Startup"
        )
        return os.path.exists(os.path.join(startup_dir, "Overwatch.lnk"))

    def _build_general_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=15)
        notebook.add(frame, text="General")

        import socket
        ttk.Label(frame, text="Machine Name:").grid(row=0, column=0, sticky="w", pady=5)
        self._machine_name = ttk.Entry(frame, width=30)
        self._machine_name.insert(0, self.config.get("general", "machine_name") or "")
        self._machine_name.grid(row=0, column=1, pady=5, padx=5, sticky="w")

        hostname = socket.gethostname()
        ttk.Label(frame, text=f"Leave blank to use hostname ({hostname})",
                  foreground="gray").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 15))

        self._autostart = tk.BooleanVar(value=self._has_startup_shortcut())
        ttk.Checkbutton(frame, text="Start Overwatch with Windows",
                        variable=self._autostart).grid(
                        row=2, column=0, columnspan=2, sticky="w", pady=5)

        ttk.Label(frame, text=(
            "Creates a shortcut in your Startup folder so\n"
            "Overwatch runs automatically when you log in."
        ), foreground="gray").grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 15))

    def _build_telegram_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=15)
        notebook.add(frame, text="Telegram")

        ttk.Label(frame, text="Bot Token:").grid(row=0, column=0, sticky="w", pady=5)
        self._tg_token = ttk.Entry(frame, width=50)
        self._tg_token.insert(0, self.config.get("telegram", "bot_token") or "")
        self._tg_token.grid(row=0, column=1, pady=5, padx=5)

        ttk.Label(frame, text="Chat ID:").grid(row=1, column=0, sticky="w", pady=5)
        self._tg_chat = ttk.Entry(frame, width=50)
        self._tg_chat.insert(0, self.config.get("telegram", "chat_id") or "")
        self._tg_chat.grid(row=1, column=1, pady=5, padx=5)

        self._tg_enabled = tk.BooleanVar(value=self.config.get("telegram", "enabled"))
        ttk.Checkbutton(frame, text="Enable Telegram Notifications",
                        variable=self._tg_enabled).grid(row=2, column=0,
                        columnspan=2, sticky="w", pady=5)

        ttk.Button(frame, text="Send Test Message",
                   command=self._test_telegram).grid(row=3, column=0,
                   columnspan=2, pady=15)

        ttk.Label(frame, text=(
            "To set up a Telegram bot:\n"
            "1. Message @BotFather on Telegram\n"
            "2. Send /newbot and follow the prompts\n"
            "3. Copy the bot token here\n"
            "4. Start a chat with your bot\n"
            "5. Send a message, then visit:\n"
            "   https://api.telegram.org/bot<TOKEN>/getUpdates\n"
            "6. Find your chat_id in the response"
        ), justify="left", foreground="gray").grid(row=4, column=0,
            columnspan=2, sticky="w", pady=10)

    @staticmethod
    def _to_12h(hour24):
        """Convert 24h hour int to (hour12, ampm) tuple."""
        ampm = "AM" if hour24 < 12 else "PM"
        h = hour24 % 12
        if h == 0:
            h = 12
        return h, ampm

    @staticmethod
    def _to_24h(hour12, ampm):
        """Convert 12h hour + AM/PM string to 24h int."""
        h = int(hour12) % 12
        if ampm == "PM":
            h += 12
        return h

    def _build_silent_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=15)
        notebook.add(frame, text="Silent Hours")

        self._silent_enabled = tk.BooleanVar(
            value=self.config.get("silent_hours", "enabled"))
        ttk.Checkbutton(frame, text="Enable Silent Hours",
                        variable=self._silent_enabled).grid(
                        row=0, column=0, columnspan=5, sticky="w", pady=5)

        # --- Start Time ---
        start_h24 = self.config.get("silent_hours", "start_hour") or 7
        start_m = self.config.get("silent_hours", "start_minute") or 0
        start_h12, start_ampm = self._to_12h(start_h24)

        ttk.Label(frame, text="Start Time:").grid(row=1, column=0, sticky="w", pady=5)
        self._silent_start_h = ttk.Spinbox(frame, from_=1, to=12, width=4, wrap=True)
        self._silent_start_h.set(start_h12)
        self._silent_start_h.grid(row=1, column=1, pady=5, padx=(5, 0))
        ttk.Label(frame, text=":").grid(row=1, column=2, padx=1)
        self._silent_start_m = ttk.Spinbox(frame, from_=0, to=59, width=4, wrap=True,
                                            format="%02.0f")
        self._silent_start_m.set(f"{start_m:02d}")
        self._silent_start_m.grid(row=1, column=3, pady=5, padx=(0, 5))
        self._silent_start_ampm = ttk.Combobox(frame, values=["AM", "PM"], width=4,
                                                state="readonly")
        self._silent_start_ampm.set(start_ampm)
        self._silent_start_ampm.grid(row=1, column=4, pady=5)

        # --- End Time ---
        end_h24 = self.config.get("silent_hours", "end_hour") or 17
        end_m = self.config.get("silent_hours", "end_minute") or 0
        end_h12, end_ampm = self._to_12h(end_h24)

        ttk.Label(frame, text="End Time:").grid(row=2, column=0, sticky="w", pady=5)
        self._silent_end_h = ttk.Spinbox(frame, from_=1, to=12, width=4, wrap=True)
        self._silent_end_h.set(end_h12)
        self._silent_end_h.grid(row=2, column=1, pady=5, padx=(5, 0))
        ttk.Label(frame, text=":").grid(row=2, column=2, padx=1)
        self._silent_end_m = ttk.Spinbox(frame, from_=0, to=59, width=4, wrap=True,
                                          format="%02.0f")
        self._silent_end_m.set(f"{end_m:02d}")
        self._silent_end_m.grid(row=2, column=3, pady=5, padx=(0, 5))
        self._silent_end_ampm = ttk.Combobox(frame, values=["AM", "PM"], width=4,
                                              state="readonly")
        self._silent_end_ampm.set(end_ampm)
        self._silent_end_ampm.grid(row=2, column=4, pady=5)

        # --- Days ---
        ttk.Label(frame, text="Active Days:").grid(row=3, column=0, sticky="w", pady=10)
        days_frame = ttk.Frame(frame)
        days_frame.grid(row=3, column=1, columnspan=4, sticky="w")

        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        active_days = self.config.get("silent_hours", "days") or [0, 1, 2, 3, 4]
        self._silent_days = []
        for i, name in enumerate(day_names):
            var = tk.BooleanVar(value=(i in active_days))
            self._silent_days.append(var)
            ttk.Checkbutton(days_frame, text=name, variable=var).pack(side="left", padx=3)

        ttk.Label(frame, text=(
            "During silent hours, events are still logged to the database\n"
            "but Telegram alerts are suppressed."
        ), foreground="gray").grid(row=4, column=0, columnspan=5, sticky="w", pady=15)

    def _build_monitors_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=15)
        notebook.add(frame, text="Monitors")

        self._mon_vars = {}
        self._alert_vars = {}
        monitors = self.config.get("monitors") or {}

        row = 0
        ttk.Label(frame, text="Monitor", font=("", 10, "bold")).grid(
            row=row, column=0, sticky="w", padx=5)
        ttk.Label(frame, text="Enabled", font=("", 10, "bold")).grid(
            row=row, column=1, padx=5)
        ttk.Label(frame, text="Alert", font=("", 10, "bold")).grid(
            row=row, column=2, padx=5)
        ttk.Label(frame, text="Description", font=("", 10, "bold")).grid(
            row=row, column=3, sticky="w", padx=5)
        row += 1

        ttk.Separator(frame, orient="horizontal").grid(
            row=row, column=0, columnspan=4, sticky="ew", pady=5)
        row += 1

        for key, mon in monitors.items():
            if not isinstance(mon, dict):
                continue
            desc = mon.get("description", key)

            enabled_var = tk.BooleanVar(value=mon.get("enabled", True))
            alert_var = tk.BooleanVar(value=mon.get("alert", True))
            self._mon_vars[key] = enabled_var
            self._alert_vars[key] = alert_var

            ttk.Label(frame, text=key.title()).grid(row=row, column=0, sticky="w", padx=5, pady=3)
            ttk.Checkbutton(frame, variable=enabled_var).grid(row=row, column=1, pady=3)
            ttk.Checkbutton(frame, variable=alert_var).grid(row=row, column=2, pady=3)
            ttk.Label(frame, text=desc, foreground="gray").grid(
                row=row, column=3, sticky="w", padx=5, pady=3)
            row += 1

    def _build_watchlist_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=15)
        notebook.add(frame, text="Process Watchlist")

        ttk.Label(frame, text="Alert on these processes (one per line):").pack(
            anchor="w", pady=(0, 5))

        self._watchlist_text = tk.Text(frame, height=15, width=50)
        watchlist = self.config.get("monitors", "process", "watchlist") or []
        self._watchlist_text.insert("1.0", "\n".join(watchlist))
        self._watchlist_text.pack(fill="both", expand=True)

    def _build_filepaths_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=15)
        notebook.add(frame, text="File Paths")

        ttk.Label(frame, text="Watch these directories (one per line):").pack(
            anchor="w", pady=(0, 5))
        self._paths_text = tk.Text(frame, height=8, width=50)
        paths = self.config.get("monitors", "filesystem", "watch_paths") or []
        self._paths_text.insert("1.0", "\n".join(paths))
        self._paths_text.pack(fill="both", expand=True, pady=(0, 10))

        ttk.Button(frame, text="Add Folder...", command=self._add_folder).pack(
            anchor="w", pady=5)

        ttk.Label(frame, text="Alert on these file extensions (one per line):").pack(
            anchor="w", pady=(10, 5))
        self._exts_text = tk.Text(frame, height=6, width=50)
        exts = self.config.get("monitors", "filesystem", "extensions_watchlist") or []
        self._exts_text.insert("1.0", "\n".join(exts))
        self._exts_text.pack(fill="both", expand=True)

    def _build_database_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=15)
        notebook.add(frame, text="Database")

        ttk.Label(frame, text="Database Path:").grid(row=0, column=0, sticky="w", pady=5)
        self._db_path = ttk.Entry(frame, width=40)
        self._db_path.insert(0, self.config.get("database", "path") or "winmon_events.db")
        self._db_path.grid(row=0, column=1, pady=5, padx=5)

        ttk.Label(frame, text="Max Events:").grid(row=1, column=0, sticky="w", pady=5)
        self._max_events = ttk.Entry(frame, width=15)
        self._max_events.insert(0, str(self.config.get("database", "max_events") or 100000))
        self._max_events.grid(row=1, column=1, sticky="w", pady=5, padx=5)

        ttk.Label(frame, text="Cleanup After (days):").grid(row=2, column=0, sticky="w", pady=5)
        self._cleanup_days = ttk.Entry(frame, width=15)
        self._cleanup_days.insert(0, str(self.config.get("database", "cleanup_days") or 30))
        self._cleanup_days.grid(row=2, column=1, sticky="w", pady=5, padx=5)

    def _add_folder(self):
        """Open folder chooser and add to paths."""
        folder = filedialog.askdirectory()
        if folder:
            self._paths_text.insert("end", "\n" + folder)

    def _test_telegram(self):
        """Send a test Telegram notification."""
        import urllib.request
        import urllib.error
        import json

        token = self._tg_token.get().strip()
        chat_id = self._tg_chat.get().strip()

        if not token or not chat_id:
            messagebox.showwarning("Missing Config",
                                   "Please enter both Bot Token and Chat ID.")
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({
            "chat_id": chat_id,
            "text": "\u2705 Overwatch test message - notifications are working!",
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                if result.get("ok"):
                    messagebox.showinfo("Success", "Test message sent!")
                else:
                    messagebox.showerror("Error", f"API error: {result}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to send: {e}")

    def _save(self):
        """Save all settings to config."""
        # General
        self.config.set("general", "machine_name", self._machine_name.get().strip())
        self._apply_autostart(self._autostart.get())

        # Telegram
        self.config.set("telegram", "bot_token", self._tg_token.get().strip())
        self.config.set("telegram", "chat_id", self._tg_chat.get().strip())
        self.config.set("telegram", "enabled", self._tg_enabled.get())

        # Silent hours — convert 12h back to 24h for storage
        self.config.set("silent_hours", "enabled", self._silent_enabled.get())
        self.config.set("silent_hours", "start_hour",
                        self._to_24h(self._silent_start_h.get(), self._silent_start_ampm.get()))
        self.config.set("silent_hours", "start_minute", int(self._silent_start_m.get()))
        self.config.set("silent_hours", "end_hour",
                        self._to_24h(self._silent_end_h.get(), self._silent_end_ampm.get()))
        self.config.set("silent_hours", "end_minute", int(self._silent_end_m.get()))
        days = [i for i, var in enumerate(self._silent_days) if var.get()]
        self.config.set("silent_hours", "days", days)

        # Monitors
        for key, var in self._mon_vars.items():
            self.config.set("monitors", key, "enabled", var.get())
        for key, var in self._alert_vars.items():
            self.config.set("monitors", key, "alert", var.get())

        # Process watchlist
        watchlist = [line.strip() for line in
                     self._watchlist_text.get("1.0", "end").splitlines()
                     if line.strip()]
        self.config.set("monitors", "process", "watchlist", watchlist)

        # File paths
        paths = [line.strip() for line in
                 self._paths_text.get("1.0", "end").splitlines()
                 if line.strip()]
        self.config.set("monitors", "filesystem", "watch_paths", paths)

        exts = [line.strip() for line in
                self._exts_text.get("1.0", "end").splitlines()
                if line.strip()]
        self.config.set("monitors", "filesystem", "extensions_watchlist", exts)

        # Database
        self.config.set("database", "path", self._db_path.get().strip())
        try:
            self.config.set("database", "max_events", int(self._max_events.get()))
        except ValueError:
            pass
        try:
            self.config.set("database", "cleanup_days", int(self._cleanup_days.get()))
        except ValueError:
            pass

        self.config.save()
        messagebox.showinfo("Saved", "Settings saved successfully!")
        self.root.destroy()

    def _apply_autostart(self, enabled):
        """Create or remove Windows startup shortcut."""
        startup_dir = os.path.join(
            os.environ.get("APPDATA", ""), "Microsoft", "Windows",
            "Start Menu", "Programs", "Startup"
        )
        shortcut_path = os.path.join(startup_dir, "Overwatch.lnk")

        if enabled:
            try:
                import subprocess
                # Find Overwatch.bat relative to this file
                base_dir = os.path.normpath(os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir
                ))
                bat_path = os.path.join(base_dir, "Overwatch.bat")
                # Use PowerShell to create shortcut
                ps_cmd = (
                    f'$ws = New-Object -ComObject WScript.Shell; '
                    f'$s = $ws.CreateShortcut("{shortcut_path}"); '
                    f'$s.TargetPath = "{bat_path}"; '
                    f'$s.WorkingDirectory = "{base_dir}"; '
                    f'$s.WindowStyle = 7; '
                    f'$s.Save()'
                )
                subprocess.run(["powershell", "-Command", ps_cmd],
                             capture_output=True, timeout=10)
            except Exception as e:
                log.error("Failed to create startup shortcut: %s", e)
        else:
            try:
                if os.path.exists(shortcut_path):
                    os.remove(shortcut_path)
            except Exception as e:
                log.error("Failed to remove startup shortcut: %s", e)
