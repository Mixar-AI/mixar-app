# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Local stalled HTTP peer for the shutdown scenario; no remote requests."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

entered = threading.Event()
release = threading.Event()
completed = []


def install():
    import requests
    from mixar.modules.common.api.executor import AsyncRequest, get_executor

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            entered.set()
            if release.wait(90):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'ok')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}/shutdown-probe'
    get_executor().submit(
        AsyncRequest('shutdown-probe', lambda: requests.get(url, timeout=90)),
        lambda *args: completed.append(args),
    )
    return url
