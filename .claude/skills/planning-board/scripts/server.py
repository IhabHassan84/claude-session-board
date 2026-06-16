#!/usr/bin/env python3
"""Local planning-board server. Stdlib only, bound to 127.0.0.1.

Serves the read-only viewer (web/index.html), the board JSON files, and an SSE
endpoint (/events) that pushes a message whenever any board file changes, so the
browser re-renders live without any commit.

Multiple Claude Code sessions on one machine each serve a different project, so
this server AUTO-SELECTS A FREE PORT (starting from PLANNING_BOARD_PORT, default
7842, scanning upward) and records the chosen port in <boards>/.runtime.json so
the CLI can print a matching URL. If a server is already serving this project's
boards, this process exits quietly.
"""
import http.server
import json
import os
import socket
import socketserver
import time

PORT_BASE = int(os.environ.get("PLANNING_BOARD_PORT", "7842"))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
WEB_DIR = os.path.join(SKILL_DIR, "web")

BOARDS_DIR = os.environ.get("PLANNING_BOARD_DIR") or os.path.join(
    os.getcwd(), ".claude", "boards"
)
ATTACH_DIR = os.path.join(BOARDS_DIR, "attachments")
RUNTIME_PATH = os.path.join(BOARDS_DIR, ".runtime.json")

MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
}


def snapshot():
    snap = {}
    if os.path.isdir(BOARDS_DIR):
        for fn in os.listdir(BOARDS_DIR):
            if fn.endswith(".json"):
                try:
                    snap[fn] = os.path.getmtime(os.path.join(BOARDS_DIR, fn))
                except OSError:
                    pass
    return snap


def port_alive(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def already_serving():
    if not os.path.exists(RUNTIME_PATH):
        return False
    try:
        with open(RUNTIME_PATH) as f:
            rt = json.load(f)
        return isinstance(rt.get("port"), int) and port_alive(rt["port"])
    except Exception:
        return False


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(404, b"viewer not found", "text/plain")
            return

        if path.startswith("/boards/"):
            fn = os.path.basename(path)
            fp = os.path.join(BOARDS_DIR, fn)
            if fn.endswith(".json") and os.path.exists(fp):
                with open(fp, "rb") as f:
                    self._send(200, f.read(), "application/json")
            else:
                self._send(404, b"{}", "application/json")
            return

        if path.startswith("/attachments/"):
            fn = os.path.basename(path)
            fp = os.path.join(ATTACH_DIR, fn)
            if os.path.exists(fp) and os.path.isfile(fp):
                ext = os.path.splitext(fn)[1].lower()
                with open(fp, "rb") as f:
                    self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))
            else:
                self._send(404, b"not found", "text/plain")
            return

        if path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last = snapshot()
            try:
                self.wfile.write(b"data: connected\n\n")
                self.wfile.flush()
                while True:
                    time.sleep(1)
                    cur = snapshot()
                    if cur != last:
                        last = cur
                        self.wfile.write(b"data: changed\n\n")
                    else:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            return

        self._send(404, b"not found", "text/plain")


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def bind_free_port():
    for port in range(PORT_BASE, PORT_BASE + 100):
        try:
            return ThreadingServer(("127.0.0.1", port), Handler), port
        except OSError:
            continue
    srv = ThreadingServer(("127.0.0.1", 0), Handler)  # OS-assigned fallback
    return srv, srv.server_address[1]


def main():
    if already_serving():
        return
    os.makedirs(BOARDS_DIR, exist_ok=True)
    srv, port = bind_free_port()
    with open(RUNTIME_PATH, "w") as f:
        json.dump({"port": port, "pid": os.getpid(), "boards_dir": BOARDS_DIR}, f)
    print(f"planning-board server on http://127.0.0.1:{port} (boards: {BOARDS_DIR})")
    try:
        srv.serve_forever()
    finally:
        try:
            os.remove(RUNTIME_PATH)
        except OSError:
            pass


if __name__ == "__main__":
    main()
# end
