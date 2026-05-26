"""Embedded FastAPI server — replaces the Tkinter dashboard/settings GUIs.

Runs uvicorn in a background thread inside the same process as the engine,
so DB, config, and notifier are shared in-memory. Bridges DB events (sync,
fired from monitor threads) to WebSocket clients (async, on the uvicorn loop)
via run_coroutine_threadsafe.
"""

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, Body, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

from winmon.intel.attack_map import ATTACK_TECHNIQUES, technique_url
from winmon.system import sync_autostart, is_autostart_enabled

log = logging.getLogger("winmon.api")

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_PORT = 7373


class APIServer:
    """Embedded HTTP/WebSocket server for the Overwatch dashboard."""

    def __init__(self, engine, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        self._engine = engine
        self._host = host
        self._port = port
        self._app = FastAPI(title="Overwatch", docs_url="/api/docs", redoc_url=None)
        self._client_queues: set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None
        self._setup_routes()

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}/"

    def start(self):
        """Spin up uvicorn in a daemon thread."""
        # Register live-event bridge with the DB
        self._engine.db.add_listener(self._on_db_event)

        config = uvicorn.Config(
            self._app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False,
            ws_ping_interval=20,
            ws_ping_timeout=20,
        )
        self._server = uvicorn.Server(config)

        ready = threading.Event()

        def run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            # uvicorn's serve() signals via server.started after binding
            ready.set()
            self._loop.run_until_complete(self._server.serve())

        self._thread = threading.Thread(target=run, name="overwatch-api", daemon=True)
        self._thread.start()
        ready.wait(timeout=5)
        log.info("Dashboard available at %s", self.url)

    def stop(self):
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)
        log.info("API server stopped")

    # ---- DB → WebSocket bridge --------------------------------------------

    def _on_db_event(self, event: dict):
        """Called on a monitor thread after every DB insert. Cheap + non-blocking."""
        if not self._loop or not self._client_queues:
            return
        try:
            self._loop.call_soon_threadsafe(self._fan_out, event)
        except RuntimeError:
            pass  # loop already closed

    def _fan_out(self, event: dict):
        for q in list(self._client_queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    # ---- Routes -----------------------------------------------------------

    def _setup_routes(self):
        app = self._app
        engine = self._engine

        # ---- Pages (no-cache + cache-busted asset URLs) ----
        # Inject a version string into every script/stylesheet reference so
        # the browser is forced to refetch when assets change.
        _NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}
        import time as _time

        def _serve_page(filename: str):
            from fastapi.responses import HTMLResponse
            path = STATIC_DIR / filename
            html = path.read_text(encoding="utf-8")
            # Use file mtime as version — changes whenever any asset changes
            assets = [STATIC_DIR / "app.js", STATIC_DIR / "app.css",
                      STATIC_DIR / "settings.js", STATIC_DIR / "settings.css"]
            ver = max(int(a.stat().st_mtime) for a in assets if a.exists())
            html = html.replace('/static/app.js"', f'/static/app.js?v={ver}"')
            html = html.replace('/static/app.css"', f'/static/app.css?v={ver}"')
            html = html.replace('/static/settings.js"', f'/static/settings.js?v={ver}"')
            html = html.replace('/static/settings.css"', f'/static/settings.css?v={ver}"')
            return HTMLResponse(html, headers=_NO_CACHE)

        @app.get("/")
        async def index():
            return _serve_page("index.html")

        @app.get("/settings")
        async def settings_page():
            return _serve_page("settings.html")

        # Custom no-cache static handler — prevents WebView2 from serving stale JS/CSS.
        @app.get("/static/{path:path}")
        async def serve_static(path: str):
            full = STATIC_DIR / path
            if not full.is_file() or not str(full.resolve()).startswith(str(STATIC_DIR.resolve())):
                raise HTTPException(404)
            return FileResponse(
                full,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )

        # ---- Status / system ----
        @app.get("/api/status")
        async def get_status():
            s = engine.get_status()
            s["away_mode"] = bool(engine.config.get("general", "away_mode"))
            return s

        @app.post("/api/system/pause")
        async def pause():
            engine.pause()
            return {"running": False, "paused": True}

        @app.post("/api/system/resume")
        async def resume():
            engine.resume()
            return {"running": True, "paused": False}

        @app.post("/api/system/restart")
        async def restart():
            engine.restart()
            return {"restarted": True}

        @app.post("/api/system/away")
        async def set_away_mode(payload: dict = Body(...)):
            """Toggle Away Mode. Body: {enabled: bool}"""
            enabled = bool(payload.get("enabled", False))
            engine.config.set("general", "away_mode", enabled)
            # Surface the state change in the event feed + Telegram
            engine.db.log_event(
                "system",
                f"Away Mode {'ON' if enabled else 'OFF'}",
                "Any login, unlock, USB plug-in, or remote connection "
                "will now be reported as critical." if enabled else
                "Normal monitoring resumed.",
                severity="warning" if enabled else "info",
                source="engine",
                alerted=enabled,
                friendly_summary=(
                    "Away Mode is on - you will be alerted to anything that touches this computer."
                    if enabled else "Away Mode is off."
                ),
            )
            if enabled and engine.config.get("telegram", "enabled"):
                engine.notifier.send_alert(
                    "system", "Away Mode is now active",
                    "Overwatch will alert you to any access to this computer.",
                    "warning",
                )
            return {"away_mode": enabled}

        # ---- Events ----
        @app.get("/api/events")
        async def list_events(
            category: Optional[str] = None,
            severity: Optional[str] = None,
            since: Optional[str] = None,
            limit: int = Query(100, ge=1, le=1000),
            offset: int = Query(0, ge=0),
            unacknowledged_only: bool = False,
        ):
            return {
                "events": engine.db.get_events(
                    category=category, severity=severity, since=since,
                    limit=limit, offset=offset,
                    unacknowledged_only=unacknowledged_only,
                ),
            }

        @app.post("/api/events/{event_id}/acknowledge")
        async def acknowledge_event(event_id: int):
            engine.db.acknowledge_event(event_id)
            return {"acknowledged": True}

        @app.post("/api/events/acknowledge-all")
        async def acknowledge_all(category: Optional[str] = None):
            engine.db.acknowledge_all(category=category)
            return {"acknowledged_all": True}

        # ---- Monitors ----
        @app.get("/api/monitors")
        async def list_monitors():
            return {
                "monitors": [
                    {
                        "name": type(m).__name__,
                        "category": getattr(m, "CATEGORY", "unknown"),
                        "enabled": engine.config.get(
                            "monitors", getattr(m, "CATEGORY", ""), "enabled"
                        ),
                        "alert": engine.config.get(
                            "monitors", getattr(m, "CATEGORY", ""), "alert"
                        ),
                    }
                    for m in engine._monitors
                ],
            }

        # ---- Config ----
        @app.get("/api/config")
        async def get_config():
            cfg = engine.config.get_all()
            # Redact secrets in the read endpoint
            if cfg.get("telegram", {}).get("bot_token"):
                cfg["telegram"]["bot_token_set"] = True
                cfg["telegram"]["bot_token"] = ""
            return cfg

        @app.put("/api/config")
        async def update_config(updates: dict = Body(...)):
            """Merge `updates` into config and persist. Pass nested dicts."""
            had_autostart_key = (
                "general" in updates and "autostart" in updates["general"]
            )
            _deep_merge(engine.config._data, updates)
            engine.config.save()

            # If autostart changed, reconcile the Startup-folder shortcut.
            autostart_state = is_autostart_enabled()
            if had_autostart_key:
                desired = bool(engine.config.get("general", "autostart"))
                sync_autostart(desired)
                autostart_state = is_autostart_enabled()

            return {"saved": True, "autostart_enabled": autostart_state}

        # ---- Alerts ----
        @app.post("/api/alerts/test")
        async def send_test_alert():
            engine.notifier.send_test()
            return {"queued": True}

        # ---- MITRE ATT&CK catalog (id -> {name, description, url}) ----
        @app.get("/api/attack")
        async def attack_catalog():
            return {
                tid: {"name": name, "description": desc, "url": technique_url(tid)}
                for tid, (name, desc) in ATTACK_TECHNIQUES.items()
            }

        # ---- WebSocket live stream ----
        @app.websocket("/api/stream")
        async def stream(ws: WebSocket):
            await ws.accept()
            queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
            self._client_queues.add(queue)
            try:
                # send a hello so the client knows we're connected
                await ws.send_text(json.dumps({"type": "hello"}))
                while True:
                    event = await queue.get()
                    await ws.send_text(json.dumps({"type": "event", "event": event}))
            except WebSocketDisconnect:
                pass
            except Exception:
                log.exception("WebSocket error")
            finally:
                self._client_queues.discard(queue)


def _deep_merge(dst: dict, src: dict):
    """Recursively merge src into dst, in place."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
