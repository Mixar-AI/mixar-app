// Advanced render extended tools — engine settings, cycles, eevee, compositing

import { sendToBlender } from "../../blender-bridge.js";

export const renderExtendedTools = [
  {
    name: "blender_render_engine_set",
    description:
      "Set the active render engine for the current scene. " +
      "BLENDER_EEVEE_NEXT is the fast real-time engine for Blender 4.x (EEVEE Next). " +
      "BLENDER_EEVEE is the EEVEE engine name for Blender 3.x and 5.x+. " +
      "CYCLES is a physically-based path-tracing engine that produces photorealistic results at the cost of render time. " +
      "BLENDER_WORKBENCH is a minimal viewport-quality engine useful for quick geometry checks or technical illustration. " +
      "Returns the engine identifier that was applied to the scene. " +
      "Example call: { \"engine\": \"CYCLES\" }.",
    inputSchema: {
      type: "object",
      properties: {
        engine: {
          type: "string",
          enum: ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES", "BLENDER_WORKBENCH"],
          description:
            "The render engine to activate. Must be UPPERCASE. " +
            "BLENDER_EEVEE_NEXT — fast rasterisation engine (Blender 4.x). " +
            "BLENDER_EEVEE — EEVEE engine for Blender 3.x and 5.x+. " +
            "CYCLES — photorealistic path tracer. " +
            "BLENDER_WORKBENCH — lightweight viewport renderer.",
        },
      },
      required: ["engine"],
    },
    handler: async (args) => {
      const result = await sendToBlender("render/engine-set", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_render_execute",
    description:
      "Trigger a render of the current scene and optionally write the output to disk. " +
      "When animation is true every frame in the scene's frame range (or the overridden frame_start/frame_end) " +
      "is rendered and saved — WARNING: this can be VERY SLOW for long animations or high-quality settings. " +
      "When animation is false (the default) only the current frame is rendered. " +
      "filepath overrides the output path configured in the scene render settings. " +
      "frame_start and frame_end override the scene's frame range when rendering an animation sequence. " +
      "Returns the filepath, whether animation mode was used, and the frame range that was rendered.",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description:
            "Optional output filepath or directory for the rendered image(s). " +
            "Overrides the scene's existing render output path. " +
            "For animations, include a frame token such as '/tmp/render####.png'.",
        },
        animation: {
          type: "boolean",
          description:
            "If true, render the full animation sequence and write every frame to disk. " +
            "WARNING: can be extremely slow for long sequences. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Defaults to false (single-frame still render).",
        },
        frame_start: {
          type: "integer",
          description:
            "Override the scene's start frame for animation rendering. Ignored when animation is false.",
        },
        frame_end: {
          type: "integer",
          description:
            "Override the scene's end frame for animation rendering. Ignored when animation is false.",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("render/execute", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_render_cycles_settings",
    description:
      "Configure Cycles render engine settings for the current scene. " +
      "samples controls the number of render samples per pixel; higher values reduce noise but increase render time. " +
      "denoise enables or disables the built-in denoiser (Intel Open Image Denoise or OptiX), which can significantly " +
      "speed up renders at lower sample counts. " +
      "device selects whether Cycles renders on the CPU or the GPU (GPU requires a compatible graphics card and enabled in Blender preferences). " +
      "bounces sets the maximum total light bounce count, controlling global illumination depth. " +
      "All parameters are optional; only provided values are updated. " +
      "Returns the resulting Cycles settings applied to the scene.",
    inputSchema: {
      type: "object",
      properties: {
        samples: {
          type: "integer",
          maximum: 10000,
          description:
            "Number of render samples per pixel. Higher = better quality, slower render. " +
            "Typical range: 32 (fast preview) to 4096 (high quality).",
        },
        denoise: {
          type: "boolean",
          description:
            "Enable or disable the Cycles denoiser. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "When true, the render is post-processed by a denoising filter (OIDN or OptiX). " +
            "Allows usable results at much lower sample counts.",
        },
        device: {
          type: "string",
          enum: ["CPU", "GPU"],
          description:
            "Compute device for Cycles rendering. Must be UPPERCASE. " +
            "CPU — use the processor (always available, slower). " +
            "GPU — use the graphics card (requires compatible GPU enabled in Blender preferences).",
        },
        bounces: {
          type: "integer",
          description:
            "Maximum total number of light bounces (global max_bounces). " +
            "Controls depth of indirect lighting and caustics. " +
            "Typical range: 4 (fast) to 128 (full GI).",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("render/cycles-settings", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_render_eevee_settings",
    description:
      "Configure EEVEE render engine settings for the current scene. " +
      "samples sets the number of temporal anti-aliasing render samples (taa_render_samples). " +
      "ao enables or disables ambient occlusion (GTAO) for contact shadows on curved surfaces. " +
      "bloom enables the screen-space bloom/glow effect (Blender 3.x only; removed in EEVEE Next / Blender 4.x). " +
      "ssr enables screen-space reflections in Blender 3.x; in Blender 4.x this maps to the raytracing toggle. " +
      "shadow_quality maps to the shadow cube map size, affecting point/spot light shadow resolution. " +
      "All parameters are optional; only provided values are updated. " +
      "Returns the settings applied and any compatibility warnings for Blender 4.x.",
    inputSchema: {
      type: "object",
      properties: {
        samples: {
          type: "integer",
          maximum: 10000,
          description:
            "Number of temporal AA render samples (taa_render_samples). " +
            "Higher values reduce flickering. Typical range: 16–256.",
        },
        ao: {
          type: "boolean",
          description:
            "Enable or disable ambient occlusion (Ground Truth Ambient Occlusion). " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Adds contact shadows that improve depth perception.",
        },
        bloom: {
          type: "boolean",
          description:
            "Enable or disable bloom/glow post-processing effect. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "NOTE: Bloom was removed in EEVEE Next (Blender 4.x). " +
            "A warning is returned if set on an incompatible version.",
        },
        ssr: {
          type: "boolean",
          description:
            "Enable or disable screen-space reflections (Blender 3.x) or raytracing (Blender 4.x). " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Adds reflections based on visible screen content.",
        },
        shadow_quality: {
          type: "string",
          description:
            "Shadow cube map resolution for point/spot lights. " +
            "Accepted values: '64', '128', '256', '512', '1024', '2048', '4096'. " +
            "Higher values produce sharper shadows at greater VRAM cost.",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("render/eevee-settings", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_render_output_settings",
    description:
      "Configure the scene's render output settings: resolution, file format, colour depth, and output path. " +
      "resolution_x and resolution_y set the render dimensions in pixels. " +
      "format sets the image container; common choices are PNG (lossless), JPEG (lossy), OPEN_EXR (HDR/multi-layer), " +
      "TIFF (lossless 16-bit), and BMP (uncompressed). " +
      "color_depth selects the bit depth per channel: '8' for standard 8-bit, '16' for 16-bit, '32' for 32-bit float (EXR only). " +
      "filepath sets the base output path; for animation renders include frame tokens such as '####'. " +
      "Returns the render dimensions, format, colour depth, and filepath that were applied.",
    inputSchema: {
      type: "object",
      properties: {
        resolution_x: {
          type: "integer",
          maximum: 8192,
          description: "Render width in pixels (e.g. 1920 for Full HD).",
        },
        resolution_y: {
          type: "integer",
          maximum: 8192,
          description: "Render height in pixels (e.g. 1080 for Full HD).",
        },
        format: {
          type: "string",
          description:
            "Output image file format. " +
            "Supported values: PNG, JPEG, OPEN_EXR, OPEN_EXR_MULTILAYER, TIFF, BMP, FFMPEG.",
        },
        color_depth: {
          type: "string",
          description:
            "Bit depth per channel for the output image. " +
            "Accepted values: '8' (standard), '16' (16-bit), '32' (32-bit float, EXR only).",
        },
        filepath: {
          type: "string",
          description:
            "Base output filepath for rendered images. " +
            "Use frame hash tokens (e.g. '/tmp/frame####.png') for animation sequences.",
        },
      },
      required: ["resolution_x", "resolution_y", "format", "filepath"],
    },
    handler: async (args) => {
      const result = await sendToBlender("render/output-settings", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_render_color_management",
    description:
      "Configure the scene's colour management settings, which control how rendered linear-light values " +
      "are transformed for display. " +
      "view_transform selects the display transform applied to the render: " +
      "STANDARD is a linear passthrough, FILMIC applies the Filmic look with film-like tone mapping, " +
      "AGXBASE uses AgX (available in Blender 4.x+) for a modern photographic look, " +
      "RAW disables colour management entirely. " +
      "look applies an artistic grading preset on top of the view transform (e.g. 'High Contrast', 'None'). " +
      "exposure adjusts the scene's overall brightness in EV stops (0.0 = neutral). " +
      "gamma applies a power-curve correction to the display output (1.0 = neutral). " +
      "All parameters are optional; only provided values are updated. " +
      "Returns the colour management settings that were applied.",
    inputSchema: {
      type: "object",
      properties: {
        view_transform: {
          type: "string",
          enum: ["STANDARD", "FILMIC", "AGXBASE", "RAW"],
          description:
            "Display view transform to apply. Must be UPPERCASE. " +
            "STANDARD — linear passthrough. " +
            "FILMIC — film-like tone mapping (default in Blender 3.x). " +
            "AGXBASE — AgX photographic mapping (Blender 4.x+). " +
            "RAW — bypass colour management.",
        },
        look: {
          type: "string",
          description:
            "Artistic look preset applied on top of the view transform. " +
            "Examples: 'None', 'Low Contrast', 'Medium Contrast', 'High Contrast'. " +
            "Available looks depend on the active view transform.",
        },
        exposure: {
          type: "number",
          description:
            "Scene exposure in EV stops. Positive values brighten, negative values darken. " +
            "Range: typically -10.0 to +10.0. Neutral value is 0.0.",
        },
        gamma: {
          type: "number",
          description:
            "Display gamma correction applied after the view transform. " +
            "Neutral value is 1.0. Values above 1.0 brighten mid-tones; below 1.0 darken them.",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("render/color-management", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_render_compositing_setup",
    description:
      "Enable the compositor node tree on the current scene and add one or more compositor nodes to it. " +
      "Calling this tool automatically sets scene.use_nodes = true so the compositor is active on render. " +
      "Each entry in the nodes array describes a node to create: " +
      "type is a friendly name mapped to the Blender node class (e.g. GLARE → CompositorNodeGlare). " +
      "name is an optional label to assign to the node so it can be found later. " +
      "inputs is an optional object of RNA attribute key/value pairs to apply directly to the node " +
      "(e.g. { 'glare_type': 'GHOSTS', 'threshold': 0.8 }). " +
      "Supported type values: GLARE, COLOR_BALANCE, BLUR, DENOISE, LENS_DISTORTION, VIGNETTE, MIX, BRIGHTNESS_CONTRAST. " +
      "You may also pass any raw Blender compositor node class name directly as type. " +
      "Returns the list of nodes that were created with their assigned names and bl_idname types.",
    inputSchema: {
      type: "object",
      properties: {
        nodes: {
          type: "array",
          description:
            "Array of compositor node configuration objects to add to the scene node tree. " +
            "IMPORTANT: Must be a JSON array of objects, NOT a string. " +
            "Example: [{ \"type\": \"GLARE\", \"name\": \"MyGlare\", \"inputs\": { \"glare_type\": \"GHOSTS\", \"threshold\": 0.8 } }].",
          items: {
            type: "object",
            properties: {
              type: {
                type: "string",
                description:
                  "Friendly node type name or raw Blender bl_idname. " +
                  "Friendly names: GLARE, COLOR_BALANCE, BLUR, DENOISE, LENS_DISTORTION, " +
                  "VIGNETTE, MIX, BRIGHTNESS_CONTRAST. " +
                  "Raw example: 'CompositorNodeGlare'.",
              },
              name: {
                type: "string",
                description: "Optional label to assign to the created node.",
              },
              inputs: {
                type: "object",
                description:
                  "Optional key/value map of RNA properties to set on the node after creation. " +
                  "Keys must match valid Python attribute names on the node (e.g. 'glare_type', 'threshold', 'size').",
              },
            },
            required: ["type"],
          },
        },
      },
      required: ["nodes"],
    },
    handler: async (args) => {
      const result = await sendToBlender("render/compositing-setup", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_render_stamp_settings",
    description:
      "Configure the render stamp (metadata burn-in) settings for the current scene. " +
      "The render stamp overlays text information such as the date, time, frame number, scene name, " +
      "camera name, filename, and render time onto rendered images. " +
      "params is a flat key/value object whose keys map directly to RNA properties on bpy.context.scene.render. " +
      "Common keys: use_stamp (bool, master on/off toggle), use_stamp_date (bool), use_stamp_time (bool), " +
      "use_stamp_render_time (bool), use_stamp_frame (bool), use_stamp_scene (bool), " +
      "use_stamp_camera (bool), use_stamp_filename (bool), " +
      "stamp_font_size (int, pixel size of stamp text, e.g. 12), stamp_note_text (str, custom note string). " +
      "Unknown or unsupported keys are silently ignored. " +
      "Returns the keys that were successfully applied.",
    inputSchema: {
      type: "object",
      properties: {
        params: {
          type: "object",
          description:
            "Key/value pairs of render stamp RNA properties to set. " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Common keys: use_stamp (bool), use_stamp_date (bool), use_stamp_time (bool), use_stamp_render_time (bool), " +
            "use_stamp_frame (bool), use_stamp_scene (bool), use_stamp_camera (bool), use_stamp_filename (bool), " +
            "stamp_font_size (int), stamp_note_text (string). " +
            "Example: { \"use_stamp\": true, \"use_stamp_frame\": true, \"stamp_font_size\": 14 }.",
        },
      },
      required: ["params"],
    },
    handler: async (args) => {
      const result = await sendToBlender("render/stamp-settings", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
