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

// The in-app bridge writes an auto-generated token here when MIXAR_MCP_TOKEN
// is not explicitly set. Read it so the operator doesn't have to copy it by
// hand. An explicit env var always wins.
function resolveToken() {
  if (process.env.MIXAR_MCP_TOKEN) return process.env.MIXAR_MCP_TOKEN.trim();
  const candidates = [];
  // Blender user config dir (Windows / macOS / Linux best-effort).
  if (process.env.APPDATA) {
    candidates.push(join(process.env.APPDATA, "Blender Foundation", "Blender"));
  }
  candidates.push(join(homedir(), ".mixar", "mcp_bridge_token"));
  for (const path of candidates) {
    try {
      return readFileSync(path, "utf-8").trim();
    } catch {
      // try next
    }
  }
  return "";
}

export const CONFIG = {
  mixarHost: resolveHost(),
  mixarPort: parseInt(process.env.MIXAR_MCP_PORT || "9877", 10),
  // Script execution can legitimately take minutes; the bridge enforces its
  // own per-request ceiling (600s), so the HTTP timeout sits just above it.
  requestTimeoutMs: parseInt(process.env.MIXAR_MCP_TIMEOUT || "620000", 10),
  bridgeToken: resolveToken(),
};
