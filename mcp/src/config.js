// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// Configuration for the Mixar MCP server — all overridable via env.

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "::1", "localhost"]);

function resolveHost() {
  const host = process.env.MIXAR_MCP_HOST || "127.0.0.1";
  if (!LOOPBACK_HOSTS.has(host)) {
    // The bridge is a local-control surface; refuse to ship the token or any
    // script/BYOK payload to a non-loopback host.
    throw new Error(
      `MIXAR_MCP_HOST=${host} is not a loopback address; refusing to connect.`
    );
  }
  return host;
}

// The in-app bridge writes an auto-generated token to a stable, version-
// independent path (~/.mixar/mcp_bridge_token) on every platform. An explicit
// env var wins. Resolution is LAZY and re-reads the file until a token is
// found, so launch order stops mattering: if the MCP client starts before
// Mixar has generated the file, the next tool call picks it up automatically
// (no restart, no 401-for-the-whole-session).
const TOKEN_PATH = join(homedir(), ".mixar", "mcp_bridge_token");
let _cachedToken = "";
let _warnedNoToken = false;

function getBridgeToken() {
  if (process.env.MIXAR_MCP_TOKEN) return process.env.MIXAR_MCP_TOKEN.trim();
  if (_cachedToken) return _cachedToken; // cache only a non-empty result
  try {
    const token = readFileSync(TOKEN_PATH, "utf-8").trim();
    if (token) {
      _cachedToken = token;
      return token;
    }
  } catch {
    // file not present yet — fall through
  }
  if (!_warnedNoToken) {
    _warnedNoToken = true; // breadcrumb once, not on every retry
    console.error(
      `[Mixar MCP] No auth token yet (looked in ${TOKEN_PATH}). Requests will 401 ` +
        "until Mixar generates one; it is picked up automatically once present. " +
        "Or set MIXAR_MCP_TOKEN identically on both sides."
    );
  }
  return "";
}

/** Invalidate the cached token (called on a 401 so a rotated token is re-read). */
function resetBridgeToken() {
  _cachedToken = "";
}

export const CONFIG = {
  mixarHost: resolveHost(),
  mixarPort: parseInt(process.env.MIXAR_MCP_PORT || "9877", 10),
  // Script execution can legitimately take minutes; the bridge enforces its
  // own per-request ceiling (600s), so the HTTP timeout sits just above it.
  requestTimeoutMs: parseInt(process.env.MIXAR_MCP_TIMEOUT || "620000", 10),
  // Live getter — resolves lazily and order-independently (see getBridgeToken).
  get bridgeToken() {
    return getBridgeToken();
  },
  resetBridgeToken,
};
