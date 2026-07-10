// Centralized runtime parameter validation for MCP tool handlers.
//
// validateParams(tool, args) inspects the tool's inputSchema and checks:
//   1. All fields listed in inputSchema.required are present and non-null.
//   2. Each present field whose type is declared in inputSchema.properties
//      has the correct JS typeof / Array.isArray type.
//   3. Enum constraints (propSchema.enum) are enforced.
//   4. Array minItems / maxItems bounds are enforced.
//
// Returns { valid: true } on success, or { valid: false, error: "<message>" }
// so callers can short-circuit before forwarding args to sendToBlender().
//
// Type mapping (JSON Schema → JS):
//   "string"  → typeof === "string"
//   "number"  → typeof === "number"
//   "integer" → typeof === "number" && Number.isInteger
//   "boolean" → typeof === "boolean"
//   "array"   → Array.isArray
//   "object"  → typeof === "object" && !Array.isArray && !== null
//
// For composite types (anyOf, oneOf), we validate that the value matches
// at least one of the declared sub-schema types.

const JSON_SCHEMA_TYPE_CHECKS = {
  string: (v) => typeof v === "string",
  number: (v) => typeof v === "number",
  integer: (v) => typeof v === "number" && Number.isInteger(v),
  boolean: (v) => typeof v === "boolean",
  array: (v) => Array.isArray(v),
  object: (v) => typeof v === "object" && !Array.isArray(v) && v !== null,
};

/**
 * Validate args against a tool's inputSchema.
 *
 * @param {{ name: string, inputSchema?: object }} tool
 * @param {object} args
 * @returns {{ valid: boolean, error?: string }}
 */
export function validateParams(tool, args) {
  const schema = tool.inputSchema;

  // No schema defined — nothing to validate.
  if (!schema || typeof schema !== "object") {
    return { valid: true };
  }

  const required = Array.isArray(schema.required) ? schema.required : [];
  const properties = schema.properties && typeof schema.properties === "object"
    ? schema.properties
    : {};

  // 1. Required-field presence check.
  for (const field of required) {
    if (args[field] === undefined || args[field] === null) {
      return {
        valid: false,
        error: `Missing required parameter "${field}" for tool "${tool.name}".`,
      };
    }
  }

  // 2. Type check for all present fields that have a declared scalar type.
  for (const [field, value] of Object.entries(args)) {
    if (value === undefined || value === null) continue;

    const propSchema = properties[field];
    if (!propSchema || typeof propSchema !== "object") continue;

    const declaredType = propSchema.type;

    if (declaredType && typeof declaredType === "string") {
      // Simple scalar type check.
      const check = JSON_SCHEMA_TYPE_CHECKS[declaredType];
      if (check && !check(value)) {
        const actual = Array.isArray(value) ? "array" : typeof value;
        return {
          valid: false,
          error:
            `Parameter "${field}" for tool "${tool.name}" must be of type ` +
            `"${declaredType}" but received "${actual}".`,
        };
      }

      // 3. Enum constraint check.
      if (Array.isArray(propSchema.enum) && propSchema.enum.length > 0) {
        if (!propSchema.enum.includes(value)) {
          return {
            valid: false,
            error:
              `Parameter "${field}" for tool "${tool.name}" must be one of ` +
              `[${propSchema.enum.map((v) => `"${v}"`).join(", ")}] ` +
              `but received "${value}".`,
          };
        }
      }

      // 4. Array minItems / maxItems check.
      if (declaredType === "array" && Array.isArray(value)) {
        if (
          typeof propSchema.minItems === "number" &&
          value.length < propSchema.minItems
        ) {
          return {
            valid: false,
            error:
              `Parameter "${field}" for tool "${tool.name}" must have at least ` +
              `${propSchema.minItems} item(s) but received ${value.length}.`,
          };
        }
        if (
          typeof propSchema.maxItems === "number" &&
          value.length > propSchema.maxItems
        ) {
          return {
            valid: false,
            error:
              `Parameter "${field}" for tool "${tool.name}" must have at most ` +
              `${propSchema.maxItems} item(s) but received ${value.length}.`,
          };
        }
      }
    } else {
      // Handle oneOf / anyOf union types — validate value matches at least one.
      // Note: the MCP transport may stringify values, so we allow strings through
      // when a numeric or array type is expected (Python coerce_value handles conversion).
      const variants = propSchema.oneOf || propSchema.anyOf;
      if (Array.isArray(variants) && variants.length > 0) {
        const allowedTypes = variants
          .map((v) => v && v.type)
          .filter(Boolean);
        const actual = Array.isArray(value) ? "array" : typeof value;

        // Allow strings through if coercion is possible downstream
        const coercible = actual === "string" && (
          allowedTypes.includes("number") ||
          allowedTypes.includes("integer") ||
          allowedTypes.includes("array") ||
          allowedTypes.includes("boolean")
        );

        if (!coercible) {
          const matchesAny = variants.some((variant) => {
            const vType = variant && variant.type;
            if (!vType || typeof vType !== "string") return true;
            const vCheck = JSON_SCHEMA_TYPE_CHECKS[vType];
            return vCheck ? vCheck(value) : true;
          });
          if (!matchesAny) {
            return {
              valid: false,
              error:
                `Parameter "${field}" for tool "${tool.name}" must be one of ` +
                `[${allowedTypes.join(", ")}] but received "${actual}".`,
            };
          }
        }
      }
    }
  }

  return { valid: true };
}
