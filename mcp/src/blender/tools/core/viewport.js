// Viewport tools — blender_viewport_screenshot

import { sendToBlender } from "../../blender-bridge.js";

export const viewportTools = [
  {
    name: "blender_viewport_screenshot",
    description:
      "Capture a screenshot of the 3D viewport and save it to disk. " +
      "You MUST provide an absolute filepath with a .png extension. " +
      "The directory must already exist. " +
      "Example call: { \"filepath\": \"C:/tmp/viewport_capture.png\", \"width\": 1920, \"height\": 1080 }. " +
      "Returns: { success, filepath, width, height }",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description:
            "Absolute path for the output image file. Must end with .png. " +
            "The parent directory must already exist. " +
            "Example: \"C:/tmp/viewport.png\" or \"D:/screenshots/scene_01.png\".",
        },
        width: {
          type: "integer",
          description:
            "Width of the captured image in pixels. " +
            "Example: 1920. Defaults to current render width.",
        },
        height: {
          type: "integer",
          description:
            "Height of the captured image in pixels. " +
            "Example: 1080. Defaults to current render height.",
        },
      },
      required: ["filepath"],
    },
    handler: async (args) => {
      const result = await sendToBlender("viewport/screenshot", args);
      return JSON.stringify(result, null, 2);
    },
  },
  {
    name: "blender_graphics_capture",
    description:
      "Capture the current 3D viewport as an inline image. " +
      "Returns base64 PNG that Claude can see directly. " +
      "Use to visually inspect the scene during modeling. " +
      "Example call: { \"width\": 512, \"height\": 512 }. " +
      "Returns: inline image + metadata.",
    inputSchema: {
      type: "object",
      properties: {
        width: {
          type: "integer",
          description:
            "Image width in pixels (default: 512). Example: 1024.",
        },
        height: {
          type: "integer",
          description:
            "Image height in pixels (default: 512). Example: 768.",
        },
        use_camera: {
          type: "boolean",
          description:
            "Render from the active scene camera instead of the viewport angle. " +
            "IMPORTANT: Must be a JSON boolean. Defaults to false. " +
            "Example call: { \"width\": 512, \"height\": 512, \"use_camera\": true }.",
        },
      },
    },
    handler: async (args) => {
      const result = await sendToBlender("viewport/graphics-capture", args);
      const parsed = typeof result === "string" ? JSON.parse(result) : result;

      if (parsed.error) {
        return JSON.stringify(parsed, null, 2);
      }

      const imageData = parsed.data?.base64 || parsed.base64;
      if (!imageData || typeof imageData !== "string") {
        return JSON.stringify(
          { error: "Viewport capture returned no image data", ...parsed },
          null,
          2,
        );
      }

      // Build metadata without the base64 payload
      const metadata = { ...parsed };
      delete metadata.base64;
      if (metadata.data) delete metadata.data.base64;

      const b64 = imageData.replace(/^data:image\/\w+;base64,/, "");

      return [
        { type: "image", data: b64, mimeType: "image/png" },
        { type: "text", text: JSON.stringify(metadata, null, 2) },
      ];
    },
  },
];
