"""Run the Overwatch dashboard headless against a seeded DEMO data dir.

Windows-only (the engine imports Windows monitors, though the demo config
disables them all, so nothing real is watched or logged). Serves the normal
dashboard at the port in the demo config (7374) with the seeded event feed.

    python scripts/demo_seed.py demo-data
    python scripts/demo_server.py demo-data

Used for marketing screenshots and demo videos: capture 127.0.0.1:7374
directly, or tunnel it (ssh -L 7374:127.0.0.1:7374 <this-machine>).
Ctrl+C to stop. Never point this at a real install's %APPDATA%.
"""

import sys
import time
from pathlib import Path

demo_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-data").resolve()
if not (demo_dir / "config.json").exists():
    sys.exit(f"No config.json in {demo_dir}; run demo_seed.py first.")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from winmon.config import Config  # noqa: E402
from winmon.engine import MonitorEngine  # noqa: E402

config = Config(config_path=demo_dir / "config.json")
# Bind the engine to the seeded database wherever this dir lives.
config.set("database", "path", str(demo_dir / "winmon_events.db"))

engine = MonitorEngine(config)
engine.start()
print(f"Demo dashboard up: http://127.0.0.1:{config.get('api', 'port')}  (Ctrl+C to stop)")
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    engine.stop()
