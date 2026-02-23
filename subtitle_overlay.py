import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from tools import debug_print, path_from_app_root, get_debug


class _SubtitleRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: Optional[str] = None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format: str, *args) -> None:  # pragma: no cover - suppressed entirely
        return


class SubtitleOverlayServer:
    """Serve subtitle assets and write JSON state for the browser overlay."""
    sub_styles = ["Inverted Pyramid", "Text Box"]

    def __init__(self, port: int = 4816) -> None:
        self.root_dir = Path(path_from_app_root("media", "subtitles"))
        self.port = port
        self.state_path = self.root_dir / "state.json"
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self._version = 0
        self._lock = threading.Lock()
        self._ensure_assets()
        self._start_server()
        self.clear_state()

    def _ensure_assets(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self.state_path.write_text("{}", encoding="utf-8")

    def _start_server(self) -> None:
        handler = partial(_SubtitleRequestHandler, directory=str(self.root_dir))
        try:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        except OSError as exc:
            debug_print("SubtitleOverlay", f"Failed to start overlay server on port {self.port}: {exc}")
            self.httpd = None
            return

        def _serve():
            if self.httpd is None:
                return
            debug_print(
                "SubtitleOverlay",
                f"Subtitle overlay available at http://127.0.0.1:{self.port}/index.html",
            )
            try:
                self.httpd.serve_forever()
            except Exception as exc:  # pragma: no cover - background thread logging
                debug_print("SubtitleOverlay", f"Server stopped: {exc}")

        self.server_thread = threading.Thread(target=_serve, name="SubtitleOverlayServer", daemon=True)
        self.server_thread.start()

    def update_state(self, payload: dict) -> None:
        data = payload or {}
        with self._lock:
            self._version += 1
            data.setdefault("lines", [])
            data["version"] = self._version
            data["updated_at"] = time.time()
            serialized = json.dumps(data, ensure_ascii=False)
            self.state_path.write_text(serialized, encoding="utf-8")

    def clear_state(self) -> None:
        self.update_state({"lines": []})

    def stop(self) -> None:
        if self.httpd:
            try:
                self.httpd.shutdown()
            except Exception:
                pass
            self.httpd = None
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=1)
            self.server_thread = None