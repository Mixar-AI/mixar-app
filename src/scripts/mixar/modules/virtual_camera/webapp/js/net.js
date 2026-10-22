/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/* WebSocket link to the Mixar virtual-camera server.
 * Text frames carry JSON; binary frames carry JPEG/PNG viewport images. */
"use strict";

const Net = (() => {
  let ws = null;
  let handlers = { open: null, close: null, message: null, frame: null };
  let reconnectTimer = null;
  let closedByUs = false;
  let attempts = 0;

  /* Close codes the server sends when this pairing is over for good
   * (core/server.py, constants.py): 4000 replaced by another phone,
   * 4001 stale token, 4002 New Pairing Code, 4003 server stopped.
   * Reconnecting cannot help — only a fresh QR scan can. */
  const FINAL_CLOSE_MIN = 4000;
  const FINAL_CLOSE_MAX = 4003;
  const BACKOFF_BASE_MS = 1500;
  const BACKOFF_MAX_MS = 15000;

  function isFinalClose(code) {
    return code >= FINAL_CLOSE_MIN && code <= FINAL_CLOSE_MAX;
  }

  function backoffDelay() {
    /* Exponential backoff with jitter: 1.5 s doubling to 15 s, each delay
     * drawn from its upper half so many phones never retry in lockstep.
     * Everything that is not a final code (1006 from an iOS background
     * suspend, a Wi-Fi drop) stays retryable. */
    const ceiling = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** attempts);
    attempts += 1;
    return ceiling / 2 + Math.random() * (ceiling / 2);
  }

  function token() {
    return new URLSearchParams(location.search).get("t") || "";
  }

  function wsUrl() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}/ws?t=${encodeURIComponent(token())}`;
  }

  function discard(socket) {
    /* A socket a later connect() has replaced must not be heard from again:
     * its close fires AFTER the new one exists, and the old handler would
     * null `ws` out from under the live session and schedule a reconnect on
     * top of it. Detach first, then close — the close is what fires them. */
    socket.onopen = null;
    socket.onmessage = null;
    socket.onclose = null;
    socket.onerror = null;
    try { socket.close(); } catch { /* already closing or closed */ }
  }

  function connect() {
    closedByUs = false;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    if (ws) { discard(ws); ws = null; }

    const socket = new WebSocket(wsUrl());
    ws = socket;
    socket.binaryType = "arraybuffer";

    /* Every handler checks it is still the current socket: a reconnect
     * scheduled while this one was opening makes this one history. */
    socket.onopen = () => {
      if (ws !== socket) return;
      attempts = 0;
      send({ t: "hello", device: { ua: navigator.userAgent } });
      if (handlers.open) handlers.open();
    };
    socket.onmessage = (e) => {
      if (ws !== socket) return;
      if (e.data instanceof ArrayBuffer) {
        if (handlers.frame) handlers.frame(e.data);
        return;
      }
      let msg;
      try { msg = JSON.parse(e.data); } catch { return; }
      if (handlers.message) handlers.message(msg);
    };
    socket.onclose = (e) => {
      if (ws !== socket) return;
      ws = null;
      const code = e ? e.code : 0;
      const final = isFinalClose(code);
      if (handlers.close) handlers.close({ final, code });
      if (!closedByUs && !final) reconnectTimer = setTimeout(connect, backoffDelay());
    };
    socket.onerror = () => { /* onclose follows */ };
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
      return true;
    }
    return false;
  }

  return {
    connect,
    send,
    hasToken: () => token().length > 0,
    isOpen: () => ws !== null && ws.readyState === WebSocket.OPEN,
    on: (name, fn) => { handlers[name] = fn; },
    close: () => {
      closedByUs = true;
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
      if (ws) ws.close();
    },
  };
})();
