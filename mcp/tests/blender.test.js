// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// Tests for the vendored Blender tool surface + two-tier proxy. Runs with
// `node --test`. No network / running Mixar required — only static assembly.

import { test } from "node:test";
import assert from "node:assert/strict";

import { splitToolTiers } from "../src/blender/tool-tiers.js";
import { deriveAnnotations } from "../src/annotations.js";
import { sceneTools } from "../src/blender/tools/core/scene.js";
import { objectTools } from "../src/blender/tools/core/object.js";
import { nodeTools } from "../src/blender/tools/advanced/node.js";
import { physicsTools } from "../src/blender/tools/advanced/physics.js";

test("two-tier split separates core from advanced and adds meta proxies", () => {
  const all = [...sceneTools, ...objectTools, ...nodeTools, ...physicsTools];
  const { coreTools, metaTools, coreCount, advancedCount } = splitToolTiers(all);

  // scene_* and object_* are in the CORE_TOOLS set; node_*/physics_* are not.
  assert.ok(coreCount >= 3, `expected core tools, got ${coreCount}`);
  assert.ok(advancedCount >= 2, `expected advanced tools, got ${advancedCount}`);
  assert.equal(coreTools.length, coreCount);

  const metaNames = metaTools.map((t) => t.name);
  assert.deepEqual(new Set(metaNames), new Set(["blender_list_advanced_tools", "blender_advanced_tool"]));
});

test("advanced proxy lists and can target a tool by name", async () => {
  const all = [...sceneTools, ...nodeTools];
  const { metaTools } = splitToolTiers(all);
  const list = metaTools.find((t) => t.name === "blender_list_advanced_tools");
  const catalog = JSON.parse(await list.handler({}));
  assert.ok(catalog.totalAdvancedTools >= 1);
  assert.ok(catalog.categories.node, "node category present in advanced catalog");
});

test("annotations: reads are read-only, deletes destructive, proxy open-world", () => {
  assert.deepEqual(deriveAnnotations("blender_scene_info"), { readOnlyHint: true, idempotentHint: true });
  assert.deepEqual(deriveAnnotations("mixar_object_info"), { readOnlyHint: true, idempotentHint: true });
  assert.deepEqual(deriveAnnotations("blender_object_delete"), { destructiveHint: true });
  assert.deepEqual(deriveAnnotations("blender_collection_remove_object"), { destructiveHint: true });
  assert.deepEqual(deriveAnnotations("blender_object_set_parent"), { idempotentHint: true });
  assert.ok(deriveAnnotations("blender_advanced_tool").openWorldHint);
  assert.ok(deriveAnnotations("mixar_execute_script").openWorldHint);
  assert.ok(deriveAnnotations("mixar_generate").openWorldHint);
  // A plain create is neither read-only nor destructive → no annotation (MCP defaults).
  assert.equal(deriveAnnotations("blender_object_create"), undefined);
});

test("every exposed tool gets valid annotation shape or none", () => {
  const all = [...sceneTools, ...objectTools, ...nodeTools, ...physicsTools];
  const VALID = new Set(["readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"]);
  for (const t of all) {
    const ann = deriveAnnotations(t.name);
    if (ann === undefined) continue;
    for (const [k, v] of Object.entries(ann)) {
      assert.ok(VALID.has(k), `${t.name}: unexpected annotation ${k}`);
      assert.equal(typeof v, "boolean");
    }
    // A tool must never be both read-only and destructive.
    assert.ok(!(ann.readOnlyHint && ann.destructiveHint), `${t.name}: read-only AND destructive`);
  }
});

test("python-exec route gate rejects when disabled", async () => {
  const prev = process.env.MIXAR_MCP_ALLOW_PYTHON_EXEC;
  process.env.MIXAR_MCP_ALLOW_PYTHON_EXEC = "0";
  // Fresh import so config.js re-reads the env for this assertion.
  const { sendToBlender } = await import(`../src/blender/blender-bridge.js?g=${Date.now()}`);
  await assert.rejects(() => sendToBlender("python/exec", { code: "x=1" }), /disabled/);
  await assert.rejects(() => sendToBlender("python/exec-file", {}), /disabled/);
  if (prev === undefined) delete process.env.MIXAR_MCP_ALLOW_PYTHON_EXEC;
  else process.env.MIXAR_MCP_ALLOW_PYTHON_EXEC = prev;
});

test("vendored blender tools are namespaced and well-formed", () => {
  const all = [...sceneTools, ...objectTools, ...nodeTools, ...physicsTools];
  for (const t of all) {
    assert.ok(t.name.startsWith("blender_"), `${t.name} namespaced`);
    assert.equal(typeof t.description, "string");
    assert.equal(t.inputSchema.type, "object");
    assert.equal(typeof t.handler, "function");
  }
});
