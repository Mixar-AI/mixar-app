// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// Unit tests for the Mixar MCP server tool layer. Runs with `node --test`.
// No network / no running Mixar required — the bridge module is stubbed.

import { test } from "node:test";
import assert from "node:assert/strict";

// Stub the bridge before importing tools so handlers use fakes.
import { asText } from "../src/bridge.js";

test("asText pretty-prints a bridge result", () => {
  const out = asText({ success: true, n: 1 });
  assert.equal(out, JSON.stringify({ success: true, n: 1 }, null, 2));
});

test("config rejects a non-loopback MIXAR_MCP_HOST", async () => {
  const prev = process.env.MIXAR_MCP_HOST;
  process.env.MIXAR_MCP_HOST = "10.0.0.5";
  await assert.rejects(
    () => import(`../src/config.js?bust=${Date.now()}`),
    /not a loopback address/
  );
  if (prev === undefined) delete process.env.MIXAR_MCP_HOST;
  else process.env.MIXAR_MCP_HOST = prev;
});

test("all tool modules export well-formed tool definitions", async () => {
  const modules = [
    "../src/tools/system.js",
    "../src/tools/execute.js",
    "../src/tools/scene.js",
    "../src/tools/history.js",
    "../src/tools/generation.js",
    "../src/tools/providers.js",
  ];
  let total = 0;
  for (const path of modules) {
    const mod = await import(path);
    const tools = Object.values(mod).find(Array.isArray);
    assert.ok(Array.isArray(tools), `${path} exports a tool array`);
    for (const tool of tools) {
      assert.equal(typeof tool.name, "string");
      assert.ok(tool.name.startsWith("mixar_"), `${tool.name} is namespaced`);
      assert.equal(typeof tool.description, "string");
      assert.ok(tool.description.length > 20, `${tool.name} has a real description`);
      assert.equal(tool.inputSchema.type, "object");
      assert.equal(typeof tool.handler, "function");
      total += 1;
    }
  }
  assert.ok(total >= 11, `expected >= 11 tools, got ${total}`);
});

test("tool names are unique across modules", async () => {
  const modules = [
    "../src/tools/system.js",
    "../src/tools/execute.js",
    "../src/tools/scene.js",
    "../src/tools/history.js",
    "../src/tools/generation.js",
    "../src/tools/providers.js",
  ];
  const seen = new Set();
  for (const path of modules) {
    const mod = await import(path);
    const tools = Object.values(mod).find(Array.isArray);
    for (const tool of tools) {
      assert.ok(!seen.has(tool.name), `duplicate tool name: ${tool.name}`);
      seen.add(tool.name);
    }
  }
});
