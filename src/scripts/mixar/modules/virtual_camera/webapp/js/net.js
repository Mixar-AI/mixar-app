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

  function connect() {
    closedByUs = false;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    ws = new WebSocket(wsUrl());
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      send({ t: "hello", device: { ua: navigator.userAgent } });
      if (handlers.open) handlers.open();
    };
    ws.onmessage = (e) => {
      if (e.data instanceof ArrayBuffer) {
        if (handlers.frame) handlers.frame(e.data);
        return;
      }
      let msg;
      try { msg = JSON.parse(e.data); } catch { return; }
      if (handlers.message) handlers.message(msg);
    };
    ws.onclose = () => {
      ws = null;
      if (handlers.close) handlers.close();
      if (!closedByUs) reconnectTimer = setTimeout(connect, 1500);
    };
    ws.onerror = () => { /* onclose follows */ };
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
    close: () => { closedByUs = true; if (ws) ws.close(); },
  };
})();
