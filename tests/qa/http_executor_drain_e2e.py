# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check waiting HTTP teardown in a running isolated QA app; no credits.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Requires this branch's
executor in the app. Uses real loopback HTTP success/error responses, then
opens and dismisses the File menu and captures the responsive viewport.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


DRAIN = '''
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests
from mixar.modules.common.api.executor import AsyncRequest, get_executor, stop_executor

executor = get_executor()
assert executor.pending_count() == 0, 'Run in an idle isolated app'
executor.stop()
executor.start(pool_size=1)
entered, release = threading.Event(), threading.Event()
values = []

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/running':
            entered.set()
            if not release.wait(5):
                return
        self.send_response(503 if self.path == '/error' else 200)
        self.end_headers()
        self.wfile.write(self.path.encode())

    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()

def request(path):
    with requests.get(f'http://127.0.0.1:{server.server_port}/{path}', timeout=5) as response:
        response.raise_for_status()
        return response.text

def complete(identity, value, error):
    values.append([identity, value, type(error).__name__ if error else None])

def release_after_stop_begins():
    deadline = time.monotonic() + 5
    while executor.is_running and time.monotonic() < deadline:
        time.sleep(.01)
    release.set()

releaser = threading.Thread(target=release_after_stop_begins, daemon=True)
try:
    executor.submit(AsyncRequest('running', lambda: request('running')), complete)
    assert entered.wait(3), 'Running HTTP request never reached the peer'
    executor.submit(AsyncRequest('queued', lambda: request('queued')), complete)
    executor.submit(AsyncRequest('error', lambda: request('error')), complete)
    assert executor.pending_count() == 3 and values == []
    releaser.start()
    stop_executor(wait=True)
    assert values == [['running', '/running', None], ['queued', '/queued', None],
                      ['error', None, 'HTTPError']], values
    assert executor.pending_count() == 0 and not executor.is_running
    result = {'completions': values, 'pending_count': executor.pending_count()}
finally:
    release.set()
    executor.stop(wait=True)
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=2)
    if releaser.ident is not None:
        releaser.join(timeout=2)
    executor.start()
'''


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/http-executor-drain'))
    out.mkdir(parents=True, exist_ok=True)
    qa.step('wait_for_idle_executor', qa.wait,
            "__import__('mixar.modules.common.api.executor', fromlist=['get_executor'])"
            '.get_executor().pending_count() == 0', timeout=30)
    result = qa.step('drain_running_queued_and_failed_http', qa.eval, DRAIN)
    qa.step('open_file_menu_after_drain', qa.click, text='File', but_type='Pulldown')
    assert qa.find(op='WM_OT_quit_blender')['total'] == 1
    qa.step('dismiss_file_menu', qa.press, 'ESC')
    assert qa.find(op='WM_OT_quit_blender')['total'] == 0
    qa.step('capture_responsive_app', qa.snap, str(out / 'after-drain.png'))
    return result


if __name__ == '__main__':
    run_scenario('http_executor_drain', run)
