// Advanced Python execution tools — blender_python_exec, blender_python_exec_file

import { sendToBlender } from "../../blender-bridge.js";
import { CONFIG } from "../../config.js";

export const pythonExecTools = [
  {
    name: "blender_python_exec",
    description:
      "Execute arbitrary Python code inside Blender. " +
      "Stdout and stderr are captured and returned. " +
      "If the code is a single expression, its value is also returned as 'result'. " +
      "Use with care — this provides full access to the Blender Python API (bpy). " +
      "Example call: { \"code\": \"import bpy; print(bpy.data.objects.keys())\" }.",
    inputSchema: {
      type: "object",
      properties: {
        code: {
          type: "string",
          description: "Python code to execute inside Blender.",
        },
      },
      required: ["code"],
    },
    handler: async (args) => {
      if (!CONFIG.allowPythonExec) {
        return JSON.stringify({ error: "Python execution is disabled. Unset MIXAR_MCP_ALLOW_PYTHON_EXEC (or set it to 1) to enable." }, null, 2);
      }
      const result = await sendToBlender("python/exec", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_python_exec_file",
    description:
      "Execute a Python script file inside Blender. " +
      "Reads the file from the given path and runs it in the Blender Python environment. " +
      "Stdout, stderr, and the final expression result are captured and returned. " +
      "Example call: { \"filepath\": \"C:/Scripts/setup_scene.py\" }.",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description: "Absolute path to the Python (.py) script file to execute.",
        },
      },
      required: ["filepath"],
    },
    handler: async (args) => {
      if (!CONFIG.allowPythonExec) {
        return JSON.stringify({ error: "Python execution is disabled. Unset MIXAR_MCP_ALLOW_PYTHON_EXEC (or set it to 1) to enable." }, null, 2);
      }
      const result = await sendToBlender("python/exec-file", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
