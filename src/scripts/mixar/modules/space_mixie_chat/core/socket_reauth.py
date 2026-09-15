# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Rotate socket credentials off the reader and Blender's main thread."""

import base64
import json
import threading
import time


def expires_soon(token):
    # Unverified claims are only a scheduling hint. The server verifies the JWT.
    try:
        encoded = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        return float(claims['exp']) <= time.time() + 120
    except (AttributeError, IndexError, KeyError, ValueError, TypeError):
        return True


def start_reauth(client, token):
    stopped = threading.Event()
    socket = client._ws

    def refresh():
        previous = token
        while not stopped.wait(30):
            if client._ws is not socket or not client.is_connected:
                return
            current = client._token_getter() if client._token_getter else previous
            if expires_soon(current):
                renewed, retryable = client._try_refresh_token()
                if not renewed:
                    if not retryable:
                        socket.close()
                        return
                    continue
                current = renewed
            if current == previous:
                continue
            done, result = threading.Event(), []
            def received(value):
                result.append(value)
                done.set()
            try:
                client.send_request('system.reauth', {'token': current}, received)
                if not done.wait(35) or not result[0].get('authenticated'):
                    socket.close()
                    return
                previous = current
            except Exception:
                socket.close()
                return

    threading.Thread(target=refresh, name='MixarSocketAuth', daemon=True).start()
    return stopped
