// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// Mixar-adapted Blender bridge client.
//
// The vendored Blender MCP tools (tools/core, tools/advanced, tool-tiers)
// import { sendToBlender } from this module. In the standalone Blender MCP
// this posted directly to the addon's HTTP server; here we route through
// Mixar's shared, token-authenticated callBridge() so the whole tool surface
// reuses the same loopback transport, auth token, and hardening as the rest
// of the Mixar MCP server. Handlers land on the Mixar bridge's /api/* route,
// which dispatches to the vendored Python handler package on the main thread.

import { callBridge, getHealth } from "../bridge.js";
import { CONFIG } from "./config.js";

// Routes that run raw (non-sandboxed) Python. The server enforces this gate
// authoritatively; we reject early client-side too so the opt-out holds no
// matter which path (named tool or the advanced-tool proxy) built the route.
const PYTHON_EXEC_ROUTE = /^python\/exec(-file)?$/;

/**
 * Send a request to a Blender handler route (e.g. "scene/info", "object/create").
 * Mirrors the original blender-bridge.js contract: unwraps the { success, data }
 * envelope, throwing on { success: false } so tool handlers surface errors.
 *
 * @param {string} endpoint - handler route like "category/action"
 * @param {object} [params] - handler parameters
 * @returns {Promise<any>} the unwrapped handler data
 */
export async function sendToBlender(endpoint, params = {}) {
  if (!CONFIG.allowPythonExec && PYTHON_EXEC_ROUTE.test(endpoint)) {
    throw new Error(
      "Raw Python execution is disabled (MIXAR_MCP_ALLOW_PYTHON_EXEC=0). " +
        "Use the sandboxed mixar_execute_script instead."
    );
  }

  const data = await callBridge(`/api/${endpoint}`, params);

  if (data && data.success === false) {
    throw new Error(data.error || "Mixar/Blender handler returned an error");
  }

  let result = data && data.data !== undefined ? data.data : data;
  if (typeof result === "string") {
    try {
      result = JSON.parse(result);
    } catch {
      // Not JSON — return the string as-is.
    }
  }
  return result;
}

/** Health check — delegates to the Mixar bridge /health endpoint. */
export async function healthCheck() {
  try {
    return await getHealth();
  } catch (error) {
    return { status: "unreachable", error: error.message };
  }
}
