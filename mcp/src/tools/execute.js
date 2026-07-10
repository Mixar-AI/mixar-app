// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// The full-control tool: sandboxed bpy script execution — the exact engine
// the hosted Mixie agent drives, minus the hosted agent.

import { callBridgeChecked, asText } from "../bridge.js";

export const executeTools = [
  {
    name: "mixar_execute_script",
    description: [
      "Execute a Python script inside Mixar (Blender 5.0 fork) with FULL control over the scene,",
      "using the same sandboxed executor Mixar's hosted AI agent uses.",
      "Sandbox rules: pre-injected modules are bpy, bmesh, mathutils, numpy, json, math, re, random,",
      "colorsys, datetime, collections, time, bpy_extras, imbuf. `os` and `pathlib` are NOT available;",
      "open/tempfile/base64/urllib are restricted wrappers. eval/exec/compile are blocked, and",
      "dunder-introspection escapes (__subclasses__, __globals__, ...) are rejected by AST validation.",
      "Inputs: pass structured inputs via `params` — they appear in the script as the `__PARAMS__` dict.",
      "Outputs: assign a JSON-serializable dict to a variable named `__RESULT__`; its keys are returned",
      "flattened in the response (do NOT print it). stdout is returned as `output`.",
      "The response also lists created/modified/deleted objects. An undo step is pushed by default.",
    ].join(" "),
    inputSchema: {
      type: "object",
      properties: {
        script: {
          type: "string",
          description: "Python source to execute in the Mixar sandbox",
        },
        params: {
          type: "object",
          description: "Optional inputs exposed to the script as __PARAMS__ (dict)",
        },
        push_undo: {
          type: "boolean",
          description: "Push an undo step before executing (default true)",
        },
        timeout: {
          type: "number",
          description: "Seconds to wait for completion (default 60, max 600)",
        },
      },
      required: ["script"],
    },
    handler: async (args) => asText(await callBridgeChecked("/execute", args)),
  },
];
