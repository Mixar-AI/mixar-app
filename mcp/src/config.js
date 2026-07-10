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
// independent path (~/.mixar/mcp_bridge_token) on every platform. Read it so
// the operator doesn't have to copy it by hand. An explicit env var wins.
function resolveToken() {
  if (process.env.MIXAR_MCP_TOKEN) return process.env.MIXAR_MCP_TOKEN.trim();
  const candidates = [join(homedir(), ".mixar", "mcp_bridge_token")];
  for (const path of candidates) {
    try {
      const token = readFileSync(path, "utf-8").trim();
      if (token) return token;
    } catch {
      // try next candidate
    }
  }
  // No token found and none set explicitly — every request will 401. Leave a
  // breadcrumb so the failure is diagnosable instead of a bare 401.
  console.error(
    `[Mixar MCP] No auth token found (looked in ${candidates.join(", ")}). ` +
      "Start Mixar with the bridge enabled so it generates one, or set " +
      "MIXAR_MCP_TOKEN identically on both sides."
  );
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
