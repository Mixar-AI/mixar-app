// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// Compatibility config for the vendored Blender tool layer.
//
// The standalone Blender MCP had its own config.js; here the transport config
// lives in ../../../config.js (Mixar's) and is used by the blender-bridge
// shim. The only field the vendored tools themselves read is
// `allowPythonExec`, the gate for the raw Blender `python/exec` tool.
//
// The Mixar MCP is a full-control local surface (token-gated, loopback-only),
// so raw python exec is enabled by default — set MIXAR_MCP_ALLOW_PYTHON_EXEC=0
// to disable it and rely solely on the sandboxed mixar_execute_script.

const DISABLED = new Set(["0", "false", "no", "off"]);

export const CONFIG = {
  // Live getter: reflects MIXAR_MCP_ALLOW_PYTHON_EXEC at read time (the server
  // gate is authoritative; this mirrors it for early client-side rejection).
  get allowPythonExec() {
    return !DISABLED.has(
      (process.env.MIXAR_MCP_ALLOW_PYTHON_EXEC || "1").trim().toLowerCase()
    );
  },
};
