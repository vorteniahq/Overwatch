"""Configuration management for Overwatch."""

import json
import os
import threading
from pathlib import Path

DEFAULT_CONFIG = {
    "telegram": {
        "bot_token": "",
        "chat_id": "",
        "enabled": True
    },
    "silent_hours": {
        "enabled": True,
        "start_hour": 7,
        "start_minute": 0,
        "end_hour": 17,
        "end_minute": 0,
        "days": [0, 1, 2, 3, 4]  # Mon-Fri (0=Monday)
    },
    "monitors": {
        "session": {
            "enabled": True,
            "alert": True,
            "description": "Workstation lock and unlock events"
        },
        "login": {
            "enabled": True,
            "alert": True,
            "description": "User login/logout events"
        },
        "process": {
            "enabled": True,
            "alert": True,
            "description": "New process creation",
            "watchlist": [
                "powershell.exe", "cmd.exe", "wscript.exe", "cscript.exe",
                "mshta.exe", "regsvr32.exe", "rundll32.exe", "certutil.exe",
                "bitsadmin.exe", "msiexec.exe", "psexec.exe", "mimikatz.exe",
                "net.exe", "net1.exe", "whoami.exe", "taskkill.exe"
            ]
        },
        "usb": {
            "enabled": True,
            "alert": True,
            "description": "USB device insertion/removal"
        },
        "rdp": {
            "enabled": True,
            "alert": True,
            "description": "RDP and TeamViewer connections"
        },
        "network": {
            "enabled": True,
            "alert": True,
            "description": "Wi-Fi, IP, and network connection changes",
            "watch_outbound": False
        },
        "power": {
            "enabled": True,
            "alert": True,
            "description": "Laptop power and battery (auto-idle on desktops)"
        },
        "filesystem": {
            "enabled": True,
            "alert": True,
            "description": "File system changes in watched paths",
            # Default to the user folders a snoop would actually look in.
            # %USERPROFILE% is expanded at runtime by the filesystem monitor.
            "watch_paths": [
                "%USERPROFILE%\\Documents",
                "%USERPROFILE%\\Desktop",
                "%USERPROFILE%\\Downloads",
                "%USERPROFILE%\\Pictures"
            ],
            "extensions_watchlist": [
                ".exe", ".dll", ".bat", ".cmd", ".ps1", ".vbs",
                ".js", ".wsf", ".scr", ".msi", ".reg"
            ]
        }
    },
    "database": {
        "path": "winmon_events.db",
        "max_events": 100000,
        "cleanup_days": 30
    },
    "general": {
        "machine_name": "",
        "display_mode": "basic",
        "log_level": "INFO",
        "start_minimized": True,
        "autostart": False,
        # When True, any login / unlock / USB / remote-access event escalates to
        # critical severity and forces a Telegram ping. Toggle from the dashboard.
        "away_mode": False,
    },
    "api": {
        "host": "127.0.0.1",
        "port": 7373
    }
}


class Config:
    """Thread-safe configuration manager with file persistence."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, config_path=None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path=None):
        if self._initialized:
            return
        self._initialized = True
        self._file_lock = threading.RLock()

        if config_path:
            self._path = Path(config_path)
        else:
            app_data = os.environ.get("APPDATA", os.path.expanduser("~"))
            self._path = Path(app_data) / "Overwatch" / "config.json"

        self._data = {}
        self.load()

    @property
    def path(self):
        return self._path

    def load(self):
        """Load config from file, creating defaults if missing."""
        with self._file_lock:
            if self._path.exists():
                try:
                    with open(self._path, "r") as f:
                        self._data = json.load(f)
                    self._merge_defaults(self._data, DEFAULT_CONFIG)
                except (json.JSONDecodeError, IOError):
                    self._data = json.loads(json.dumps(DEFAULT_CONFIG))
            else:
                self._data = json.loads(json.dumps(DEFAULT_CONFIG))
                self.save()

    def save(self):
        """Persist config to disk."""
        with self._file_lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w") as f:
                json.dump(self._data, f, indent=2)

    def get(self, *keys, default=None):
        """Get a nested config value. Usage: config.get('telegram', 'bot_token')"""
        obj = self._data
        for key in keys:
            if isinstance(obj, dict) and key in obj:
                obj = obj[key]
            else:
                return default
        return obj

    def set(self, *args):
        """Set a nested config value. Last arg is value. Usage: config.set('telegram', 'bot_token', 'xxx')"""
        if len(args) < 2:
            raise ValueError("Need at least key and value")
        keys = args[:-1]
        value = args[-1]
        obj = self._data
        for key in keys[:-1]:
            if key not in obj or not isinstance(obj[key], dict):
                obj[key] = {}
            obj = obj[key]
        obj[keys[-1]] = value
        self.save()

    def get_all(self):
        """Return a deep copy of entire config."""
        return json.loads(json.dumps(self._data))

    def _merge_defaults(self, current, defaults):
        """Recursively merge defaults into current config."""
        for key, value in defaults.items():
            if key not in current:
                current[key] = json.loads(json.dumps(value))
            elif isinstance(value, dict) and isinstance(current.get(key), dict):
                self._merge_defaults(current[key], value)

    @classmethod
    def reset_instance(cls):
        """Reset singleton (for testing)."""
        cls._instance = None
