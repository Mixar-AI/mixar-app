// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// System tools: bridge connectivity and status.

import { getHealth, asText } from "../bridge.js";

export const systemTools = [
  {
    name: "mixar_health",
    description:
      "Check that Mixar is running and the MCP bridge is reachable. Returns the app version " +
      "and whether the bridge requires a shared token. Call this first when other tools fail.",
    inputSchema: { type: "object", properties: {} },
    handler: async () => asText(await getHealth()),
  },
];
