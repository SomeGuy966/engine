"""The app: a tiny web server that only listens on this Mac (127.0.0.1) and
serves one page. Nothing is uploaded anywhere - "upload" just copies the image
into Engine/uploads/ so the engine can read it.

Started by Engine.app. Quits by itself ~15 minutes after its tab is closed,
or right away with the "Quit" button.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .backends import Cancelled
from .cards import CardError, load_cards
from .core import Engine, open_image
from .paths import IMAGE_SUFFIXES, OUTPUT_DIR, UPLOADS_DIR, WEB_DIR, ensure_dirs

DEFAULT_PORT = 7861
IDLE_QUIT_SECONDS = 15 * 60       # no page open and nothing running -> quit
IDLE_UNLOAD_SECONDS = 5 * 60      # free model memory after this long unused
MAX_UPLOAD_BYTES = 300 * 1024 * 1024

TOKEN = secrets.token_urlsafe(24)  # blocks other websites from poking this server
ENGINE = Engine()
STATE = {"last_seen": time.time(), "job": None, "allowed": set()}
JOB_LOCK = threading.Lock()


def _log(*args) -> None:
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def _allow(path: Path) -> str:
    p = str(path.resolve())
    STATE["allowed"].add(p)
    return p


def _is_allowed(p: str) -> bool:
    rp = Path(p).resolve()
    return (
        str(rp) in STATE["allowed"]
        or rp.is_relative_to(OUTPUT_DIR.resolve())
        or rp.is_relative_to(UPLOADS_DIR.resolve())
    )


def _image_info(path: Path) -> dict:
    img = open_image(path)
    return {"path": _allow(path), "name": path.name, "width": img.width, "height": img.height}


def _run_job(job: dict) -> None:
    def report(frac, msg):
        if frac is not None:
            job["progress"] = frac
        if msg:
            job["log"].append(msg)
            del job["log"][:-300]
            job["message"] = msg

    try:
        models = job["models"]
        if len(models) == 1:
            result = ENGINE.enhance(job["path"], model=models[0], scale=job["scale"], report=report)
            job["result"] = result.to_dict()
            job["results"] = [job["result"]]
            _allow(Path(result.output_path))
            _log(f"done: {result.output_path} ({result.seconds}s)")
        else:
            multi = ENGINE.enhance_many(job["path"], models, scale=job["scale"], report=report)
            job.update(multi.to_dict())
            for r in multi.results:
                _allow(Path(r.output_path))
            if multi.comparison_path:
                _allow(Path(multi.comparison_path))
            if not multi.results:
                raise RuntimeError("Every model failed:\n" + "\n".join(
                    f"{e['model_name']}: {e['error']}" for e in multi.errors))
            _log(f"done: {len(multi.results)} models, comparison {multi.comparison_path} ({multi.seconds}s)")
        job["state"] = "done"
    except Cancelled:
        job["state"] = "cancelled"
        job["message"] = "Cancelled"
    except Exception as e:  # report every failure to the page
        job["state"] = "error"
        job["error"] = str(e)
        _log("error:", traceback.format_exc())
    finally:
        job["finished"] = time.time()


class Handler(BaseHTTPRequestHandler):
    server_version = f"Engine/{__version__}"

    def log_message(self, fmt, *args):  # keep the log quiet
        pass

    # -- helpers ----------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _error(self, msg: str, code: int = 400) -> None:
        self._json({"error": msg}, code)

    def _body_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _token_ok(self, query: dict) -> bool:
        given = self.headers.get("X-Engine-Token") or (query.get("token") or [""])[0]
        return secrets.compare_digest(given, TOKEN)

    # -- routes -----------------------------------------------------------
    def do_GET(self):
        if not self._host_ok():
            return self._error("forbidden", 403)
        url = urlparse(self.path)
        q = parse_qs(url.query)
        STATE["last_seen"] = time.time()

        if url.path in ("/", "/index.html"):
            html = (WEB_DIR / "index.html").read_text().replace("__ENGINE_TOKEN__", TOKEN)
            return self._send(200, html.encode(), "text/html; charset=utf-8", {
                "Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; "
                                           "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                                           "connect-src 'self'"})
        if url.path == "/api/ping":
            return self._json({"app": "engine", "version": __version__})
        if not self._token_ok(q):
            return self._error("forbidden", 403)

        if url.path == "/api/models":
            cards, problems = load_cards()
            return self._json({"models": [c.to_public() for c in cards], "problems": problems})
        if url.path == "/api/job":
            job = STATE["job"]
            if not job:
                return self._json({"state": "idle"})
            since = int((q.get("since") or ["0"])[0])
            out = {k: v for k, v in job.items() if k != "log"}
            out["log"] = job["log"][since:] if since <= len(job["log"]) else []
            out["log_len"] = len(job["log"])
            return self._json(out)
        if url.path == "/api/image":
            p = unquote((q.get("path") or [""])[0])
            if not p or not _is_allowed(p) or not Path(p).is_file():
                return self._error("not found", 404)
            ext = Path(p).suffix.lower()
            ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                     ".gif": "image/gif", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff"}
            return self._send(200, Path(p).read_bytes(), ctype.get(ext, "application/octet-stream"))
        return self._error("not found", 404)

    def do_POST(self):
        if not self._host_ok():
            return self._error("forbidden", 403)
        url = urlparse(self.path)
        STATE["last_seen"] = time.time()
        if not self._token_ok(parse_qs(url.query)):
            return self._error("forbidden", 403)
        try:
            return self._post(url.path)
        except (CardError, FileNotFoundError, ValueError) as e:
            return self._error(str(e))
        except Exception as e:
            _log("error:", traceback.format_exc())
            return self._error(f"Unexpected error: {e}", 500)

    def _post(self, route: str):
        if route == "/api/upload":
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_UPLOAD_BYTES:
                return self._error("Image is empty or too large")
            name = unquote(self.headers.get("X-Filename") or "pasted.png")
            name = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(name).name).strip() or "image.png"
            if Path(name).suffix.lower() not in IMAGE_SUFFIXES:
                name += ".png"
            UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            dest = UPLOADS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_{name}"
            dest.write_bytes(self.rfile.read(n))
            try:
                return self._json(_image_info(dest))
            except Exception:
                dest.unlink(missing_ok=True)
                raise ValueError("That file couldn't be opened as an image")

        if route == "/api/inspect":
            raw = (self._body_json().get("path") or "").strip().strip("'\"")
            if not raw:
                return self._error("Type or paste a file path")
            return self._json(_image_info(Path(raw).expanduser()))

        if route == "/api/run":
            body = self._body_json()
            with JOB_LOCK:
                job = STATE["job"]
                if job and job["state"] == "running":
                    return self._error("Already enhancing an image", 409)
                path = body.get("path") or ""
                if not _is_allowed(path):
                    return self._error("Choose an image first")
                models = body.get("models") or ([body["model"]] if body.get("model") else [])
                if not models:
                    return self._error("Pick at least one model")
                job = {
                    "id": secrets.token_hex(4), "state": "running", "path": path,
                    "models": [str(m) for m in models], "scale": body.get("scale"),
                    "progress": 0.0, "message": "Starting", "log": [], "result": None,
                    "results": [], "comparison_path": None, "errors": [],
                    "error": None, "started": time.time(), "finished": None,
                }
                STATE["job"] = job
                threading.Thread(target=_run_job, args=(job,), daemon=True).start()
            _log(f"run: models={','.join(job['models'])} scale={job['scale']} {Path(path).name}")
            return self._json({"id": job["id"]})

        if route == "/api/cancel":
            ENGINE.cancel()
            return self._json({"ok": True})

        if route in ("/api/reveal", "/api/open"):
            p = self._body_json().get("path") or ""
            if not _is_allowed(p) or not Path(p).exists():
                return self._error("not found", 404)
            subprocess.run(["open", "-R", p] if route == "/api/reveal" else ["open", p], check=False)
            return self._json({"ok": True})

        if route == "/api/open-output":
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(OUTPUT_DIR)], check=False)
            return self._json({"ok": True})

        if route == "/api/quit":
            self._json({"ok": True})
            threading.Thread(target=_shutdown, args=("quit button",), daemon=True).start()
            return None

        return self._error("not found", 404)


SERVER: ThreadingHTTPServer | None = None


def _shutdown(reason: str) -> None:
    _log(f"shutting down ({reason})")
    ENGINE.cancel()
    time.sleep(0.3)
    if SERVER:
        SERVER.shutdown()


def _watchdog() -> None:
    while True:
        time.sleep(20)
        job = STATE["job"]
        running = bool(job and job["state"] == "running")
        now = time.time()
        if not running:
            ENGINE.unload_if_idle(IDLE_UNLOAD_SECONDS)
        if not running and now - STATE["last_seen"] > IDLE_QUIT_SECONDS:
            _shutdown("idle - no Engine tab open")
            return


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def main() -> int:
    global SERVER
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--open", action="store_true", help="open the page in your browser")
    args = ap.parse_args()

    ensure_dirs()
    port = args.port
    while not _port_free(port):
        port += 1
        if port > args.port + 20:
            print("No free port found", file=sys.stderr)
            return 1
    SERVER = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    SERVER.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    _log(f"Engine {__version__} running at {url} (pid {os.getpid()})")
    threading.Thread(target=_watchdog, daemon=True).start()
    if args.open:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        SERVER.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ENGINE.unload()
        SERVER.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
