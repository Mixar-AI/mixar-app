// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// AI generation via Mixar's unified job queue — image gen, 3D gen, retopology,
// UV unwrap, texture gen, scene gen. Jobs run on the configured backend using
// the user's own Mixar session (and BYOK keys when active).

import { callBridgeChecked, asText } from "../bridge.js";

export const generationTools = [
  {
    name: "mixar_generation_catalog",
    description:
      "Browse the generation catalog (capabilities → services → models with parameter schemas). " +
      "Call with no args for the capability list, with `capability` for its services, or with " +
      "`service` for its models + default model. Requires the user to be logged into Mixar.",
    inputSchema: {
      type: "object",
      properties: {
        capability: { type: "string", description: "Capability key (e.g. image_gen, model_gen, retopology)" },
        service: { type: "string", description: "Service key (e.g. image_gen, model_3d, retopology)" },
      },
    },
    handler: async (args) => asText(await callBridgeChecked("/generation/catalog", args)),
  },
  {
    name: "mixar_generate",
    description:
      "Submit an AI generation job to Mixar's unified queue (POST /job-queue/jobs). " +
      "`service` + `model` come from mixar_generation_catalog; `payload` carries the job inputs — " +
      "typically {prompt, params:{...}} for images, or top-level base64 file inputs " +
      "(image_bytes_b64, file_bytes_b64, input_name) plus params for 3D/retopo/UV jobs. " +
      "Returns a job_id — poll with mixar_generation_job_status. Uses the user's Mixar account " +
      "(credits or BYOK); requires login.",
    inputSchema: {
      type: "object",
      properties: {
        service: { type: "string", description: "Service key from the catalog" },
        model: { type: "string", description: "Model slug from the catalog" },
        payload: { type: "object", description: "Job payload (inputs + params sub-dict)" },
      },
      required: ["service", "model", "payload"],
    },
    handler: async (args) => asText(await callBridgeChecked("/generation/enqueue", args)),
  },
  {
    name: "mixar_generation_job_status",
    description:
      "Poll a generation job. Statuses: PENDING → SUBMITTED → POLLING → DONE/FAILED/CANCELLED. " +
      "When DONE, `result` carries output URLs (e.g. result_files [{type,url}] for GLB jobs, " +
      "image URLs for image jobs). Import results into the scene with mixar_execute_script.",
    inputSchema: {
      type: "object",
      properties: {
        job_id: { type: "string", description: "Job id returned by mixar_generate" },
      },
      required: ["job_id"],
    },
    handler: async (args) => asText(await callBridgeChecked("/generation/status", args)),
  },
  {
    name: "mixar_generation_job_cancel",
    description: "Cancel a queued or running generation job.",
    inputSchema: {
      type: "object",
      properties: {
        job_id: { type: "string", description: "Job id to cancel" },
      },
      required: ["job_id"],
    },
    handler: async (args) => asText(await callBridgeChecked("/generation/cancel", args)),
  },
];
