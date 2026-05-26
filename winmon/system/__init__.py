"""Windows-specific OS integrations (autostart, services, registry helpers)."""
from winmon.system.autostart import (
    is_autostart_enabled,
    sync_autostart,
    STARTUP_SHORTCUT_PATH,
)

__all__ = ["is_autostart_enabled", "sync_autostart", "STARTUP_SHORTCUT_PATH"]
