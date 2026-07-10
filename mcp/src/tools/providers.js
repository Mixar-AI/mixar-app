// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// Key-provider integration (BYOK): manage which LLM/generation provider keys
// the configured Mixar backend uses for the user's requests. With this MCP in
// place the *chat agent* consumes zero tokens (the MCP client is the brain);
// BYOK keeps GPU generation billed to the user's own provider account.

import { callBridge, asText } from "../bridge.js";

export const providerTools = [
  {
    name: "mixar_provider_keys",
    description:
      "Manage bring-your-own-key (BYOK) provider credentials on the user's Mixar account. " +
      "Actions: status (active state + masked key previews), models (available provider/model " +
      "catalog), set (store provider+model+api_key — validated by the backend before storing), " +
      "remove (delete all stored keys). Keys are write-only: only masked previews ever come back. " +
      "NOTE: `set` transmits the key to the configured Mixar backend over HTTPS, where it is " +
      "stored encrypted and used server-side for the user's generation requests.",
    inputSchema: {
      type: "object",
      properties: {
        action: {
          type: "string",
          enum: ["status", "models", "set", "remove"],
          description: "BYOK operation to perform",
        },
        provider: { type: "string", description: "Provider id (for set — see models action)" },
        model: { type: "string", description: "Model id (for set — see models action)" },
        api_key: { type: "string", description: "Provider API key (for set)" },
      },
      required: ["action"],
    },
    handler: async (args) => {
      switch (args.action) {
        case "status":
          return asText(await callBridge("/byok/status", {}));
        case "models":
          return asText(await callBridge("/byok/models", {}));
        case "set":
          return asText(
            await callBridge("/byok/set", {
              provider: args.provider,
              model: args.model,
              api_key: args.api_key,
            })
          );
        case "remove":
          return asText(await callBridge("/byok/remove", {}));
        default:
          throw new Error(`Unknown action: ${args.action}`);
      }
    },
  },
];
