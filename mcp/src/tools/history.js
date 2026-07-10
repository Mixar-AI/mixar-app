// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// Operation history: Mixar's local per-scene log of every agent script and
// curated manual edit (operations.jsonl — no backend involved).

import { callBridge, asText } from "../bridge.js";

export const historyTools = [
  {
    name: "mixar_operation_history",
    description:
      "Read Mixar's local operation history for the active scene — every past agent script " +
      "execution and curated manual user edit. Tools: operation_history_summary, " +
      "list_operations (limit/source/category/since_seq), get_operation (seq or op_id — " +
      "includes the archived script), operations_for_object (object_name).",
    inputSchema: {
      type: "object",
      properties: {
        tool: {
          type: "string",
          enum: [
            "operation_history_summary",
            "list_operations",
            "get_operation",
            "operations_for_object",
          ],
          description: "History query to run",
        },
        params: {
          type: "object",
          description:
            "Tool parameters: list_operations {limit, source, category, since_seq, include_queries}; " +
            "get_operation {seq | op_id}; operations_for_object {object_name}",
        },
      },
      required: ["tool"],
    },
    handler: async (args) =>
      asText(
        await callBridge("/tool", {
          domain: "operation_history",
          name: args.tool,
          params: args.params || {},
        })
      ),
  },
];
