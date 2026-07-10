// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// HTTP client for the in-app MCP bridge (mixar.modules.mcp_bridge).

import { CONFIG } from "./config.js";

const BASE_URL = `http://${CONFIG.mixarHost}:${CONFIG.mixarPort}`;

/**
 * POST a JSON body to a bridge endpoint and return the parsed JSON result.
 * Bridge responses always carry a top-level `success` flag; failures are
 * thrown as Errors so tool handlers surface them uniformly.
 */
export async function callBridge(path, body = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CONFIG.requestTimeoutMs);
  const headers = { "Content-Type": "application/json" };
  if (CONFIG.bridgeToken) headers["X-Mixar-MCP-Token"] = CONFIG.bridgeToken;

  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error(
        `Bridge request to ${path} timed out after ${CONFIG.requestTimeoutMs}ms`
      );
    }
    throw new Error(
      `Cannot reach Mixar at ${BASE_URL} — is Mixar running with the MCP bridge enabled? (${err.message})`
    );
  } finally {
    clearTimeout(timer);
  }

  const text = await response.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(`Bridge returned non-JSON (HTTP ${response.status}): ${text.slice(0, 300)}`);
  }
  return data;
}

/** GET /health — connectivity check. */
export async function getHealth() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(`${BASE_URL}/health`, { signal: controller.signal });
    return await response.json();
  } catch (err) {
    throw new Error(
      `Cannot reach Mixar at ${BASE_URL} — is Mixar running with the MCP bridge enabled? (${err.message})`
    );
  } finally {
    clearTimeout(timer);
  }
}

/** Format a bridge result as an MCP text payload. */
export function asText(result) {
  return JSON.stringify(result, null, 2);
}
