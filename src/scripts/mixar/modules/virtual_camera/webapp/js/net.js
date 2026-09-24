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
    socket.onclose = () => {
      if (ws !== socket) return;
      ws = null;
      if (handlers.close) handlers.close();
      if (!closedByUs) reconnectTimer = setTimeout(connect, 1500);
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
