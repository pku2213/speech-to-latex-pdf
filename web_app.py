#!/usr/bin/env python3
"""Local browser interface for audio2pdf.

The server binds to 127.0.0.1 only. The page calls the shared pipeline in a
background thread and polls an in-memory status record, so long recordings do
not freeze the interface.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent
SRC_DIR = PROJECT_DIR / "src"
WEB_INDEX = PROJECT_DIR / "web" / "index.html"
sys.path.insert(0, str(SRC_DIR))

from pipeline import ConfigError, PipelineError, check_setup, run_pipeline


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
RUNS: dict[str, dict[str, Any]] = {}
RUN_LOCK = threading.Lock()


def find_free_port(start_port: int = DEFAULT_PORT) -> int:
    """Return the first available localhost port in a small predictable range."""
    for port in range(start_port, start_port + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return port
    raise RuntimeError("No free local port found.")


def run_powershell_dialog(kind: str) -> str:
    """Open a native Windows picker and return an UTF-8 path or an empty string."""
    if kind == "file":
        command = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'Choose audio or video'
$dialog.Filter = 'Audio and video|*.mp3;*.wav;*.m4a;*.aac;*.flac;*.ogg;*.mp4;*.mov;*.mkv;*.avi;*.wmv|All files|*.*'
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($dialog.FileName) }
"""
    elif kind == "config":
        command = rf"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'Choose config YAML'
$dialog.InitialDirectory = '{str(PROJECT_DIR).replace("'", "''")}'
$dialog.Filter = 'YAML|*.yaml;*.yml|All files|*.*'
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{ [Console]::Out.Write($dialog.FileName) }}
"""
    elif kind == "folder":
        command = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Choose output folder'
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($dialog.SelectedPath) }
"""
    else:
        raise ValueError(f"Unknown dialog kind: {kind}")

    completed = subprocess.run(
        ["powershell", "-NoProfile", "-STA", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode != 0:
        raise RuntimeError(stderr.strip() or "Dialog failed.")
    return stdout.strip()


def run_worker(run_id: str, payload: dict[str, Any]) -> None:
    """Execute one pipeline run and expose progress to the polling endpoint."""
    def progress(message: str) -> None:
        with RUN_LOCK:
            run = RUNS.get(run_id)
            if run is not None:
                run["logs"].append(str(message))

    try:
        result = run_pipeline(
            input_file=payload["input_file"],
            title=payload.get("title") or None,
            config_path=payload.get("config_path") or PROJECT_DIR / "config.yaml",
            output_dir=payload.get("output_dir") or PROJECT_DIR / "output",
            progress_callback=progress,
        )
        with RUN_LOCK:
            RUNS[run_id]["state"] = "done"
            RUNS[run_id]["result"] = {
                "pdf_path": str(result.pdf_path),
                "work_dir": str(result.work_dir),
                "log_path": str(result.log_path),
                "output_dir": str(result.pdf_path.parent),
                "timestamped_transcript_path": str(result.timestamped_transcript_path or ""),
            }
    except (ConfigError, PipelineError, RuntimeError, OSError) as exc:
        with RUN_LOCK:
            RUNS[run_id]["state"] = "error"
            RUNS[run_id]["error"] = str(exc)
            RUNS[run_id]["logs"].append(f"ERROR: {exc}")
    except Exception as exc:  # Last-resort boundary for the desktop UI.
        with RUN_LOCK:
            RUNS[run_id]["state"] = "error"
            RUNS[run_id]["error"] = f"Unexpected error: {exc}"
            RUNS[run_id]["logs"].append(f"ERROR: Unexpected error: {exc}")


class Handler(BaseHTTPRequestHandler):
    """Serve the single-page UI and a minimal local JSON API."""

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _common_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._common_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self) -> None:
        if not WEB_INDEX.exists():
            self._send_json({"ok": False, "error": f"UI file not found: {WEB_INDEX}"}, 500)
            return
        html = WEB_INDEX.read_text(encoding="utf-8")
        html = html.replace("__PROJECT_DIR__", str(PROJECT_DIR).replace("\\", "\\\\"))
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._common_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self._send_html()
            return
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        try:
            if parsed.path == "/api/browse-file":
                self._send_json({"ok": True, "path": run_powershell_dialog("file")})
            elif parsed.path == "/api/browse-config":
                self._send_json({"ok": True, "path": run_powershell_dialog("config")})
            elif parsed.path == "/api/browse-folder":
                self._send_json({"ok": True, "path": run_powershell_dialog("folder")})
            elif parsed.path == "/api/status":
                query = urllib.parse.parse_qs(parsed.query)
                run_id = (query.get("run_id") or [""])[0]
                with RUN_LOCK:
                    run = RUNS.get(run_id)
                    if not run:
                        self._send_json({"ok": False, "error": "Run not found."}, 404)
                        return
                    self._send_json({"ok": True, **run})
            elif parsed.path == "/api/health":
                self._send_json({"ok": True, "project_dir": str(PROJECT_DIR)})
            else:
                self._send_json({"ok": False, "error": "Not found."}, 404)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 500)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/api/check":
                messages = check_setup(
                    payload.get("config_path") or PROJECT_DIR / "config.yaml",
                    require_api_keys=bool(payload.get("require_api_keys", True)),
                )
                self._send_json({"ok": True, "messages": messages})
            elif self.path == "/api/run":
                input_file = str(payload.get("input_file") or "").strip()
                if not input_file:
                    self._send_json({"ok": False, "error": "Missing input file."}, 400)
                    return
                run_id = uuid.uuid4().hex
                with RUN_LOCK:
                    RUNS[run_id] = {
                        "state": "running",
                        "logs": [],
                        "result": None,
                        "error": "",
                        "created_at": int(time.time()),
                    }
                thread = threading.Thread(
                    target=run_worker,
                    args=(run_id, payload),
                    daemon=True,
                    name=f"audio2pdf-{run_id[:8]}",
                )
                thread.start()
                self._send_json({"ok": True, "run_id": run_id})
            elif self.path == "/api/open":
                path = Path(str(payload.get("path") or "")).expanduser()
                if not path.exists():
                    self._send_json({"ok": False, "error": f"Path not found: {path}"}, 404)
                    return
                os.startfile(path)  # type: ignore[attr-defined]
                self._send_json({"ok": True})
            else:
                self._send_json({"ok": False, "error": "Not found."}, 404)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 500)


def main() -> None:
    port = find_free_port()
    server = ThreadingHTTPServer((HOST, port), Handler)
    url = f"http://{HOST}:{port}/"
    print(f"audio2pdf page: {url}")
    print("Close this window to stop the local page server.")
    if os.environ.get("AUDIO2PDF_NO_BROWSER") != "1":
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
