import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// reference-data lives at mcp/reference-data; this file is at
// mcp/src/blender/reference/loader.js → up three to reach mcp/.
const DATA_DIR = path.join(__dirname, "../../../reference-data");

let dimensions = [];
let materials = [];
let recipes = [];
let loaded = false;

export function loadReferenceData() {
  if (loaded) return;
  dimensions = loadDir("dimensions");
  materials = loadDir("materials");
  recipes = loadRecipeDir("recipes");
  loaded = true;
  console.error(
    `[Reference] Loaded ${dimensions.length} dimensions, ${materials.length} materials, ${recipes.length} recipes`
  );
}

function loadDir(subdir) {
  const dir = path.join(DATA_DIR, subdir);
  if (!fs.existsSync(dir)) return [];
  const items = [];
  for (const file of fs.readdirSync(dir)) {
    if (!file.endsWith(".json") || file.startsWith(".")) continue;
    try {
      const data = JSON.parse(fs.readFileSync(path.join(dir, file), "utf-8"));
      if (data.items) {
        items.push(...data.items.map((i) => ({ ...i, _category: data.category })));
      }
    } catch (e) {
      console.error(`[Reference] Failed to parse ${file}: ${e.message}`);
    }
  }
  return items;
}

function loadRecipeDir(subdir) {
  const dir = path.join(DATA_DIR, subdir);
  if (!fs.existsSync(dir)) return [];
  const items = [];
  for (const file of fs.readdirSync(dir)) {
    if (!file.endsWith(".json") || file.startsWith(".")) continue;
    try {
      const data = JSON.parse(fs.readFileSync(path.join(dir, file), "utf-8"));
      if (data.recipes) {
        items.push(...data.recipes.map((r) => ({ ...r, _category: data.category })));
      }
    } catch (e) {
      console.error(`[Reference] Failed to parse ${file}: ${e.message}`);
    }
  }
  return items;
}

// Fuzzy search: exact name → startsWith → includes (case-insensitive)
function fuzzySearch(items, query, category) {
  let pool = items;
  if (category) pool = pool.filter((i) => i._category === category.toLowerCase());
  const q = query.toLowerCase();

  // Exact match
  let result = pool.filter((i) => i.name === q);
  if (result.length) return result;

  // startsWith
  result = pool.filter(
    (i) =>
      i.name.startsWith(q) ||
      (i.display_name && i.display_name.toLowerCase().startsWith(q))
  );
  if (result.length) return result;

  // includes
  result = pool.filter(
    (i) =>
      i.name.includes(q) ||
      (i.display_name && i.display_name.toLowerCase().includes(q)) ||
      (i.tags && i.tags.some((t) => t.includes(q)))
  );
  if (result.length) return result;

  // No match — return empty array
  return [];
}

export function findDimension(query, category) {
  const results = fuzzySearch(dimensions, query, category);
  return {
    results,
    query,
    count: results.length,
    ...(results.length === 0 && { suggestions: listCategories("dimensions") }),
  };
}

export function findMaterial(query, category) {
  const results = fuzzySearch(materials, query, category);
  return {
    results,
    query,
    count: results.length,
    ...(results.length === 0 && { suggestions: listCategories("materials") }),
  };
}

export function findRecipe(query, category) {
  const results = fuzzySearch(recipes, query, category);
  return {
    results,
    query,
    count: results.length,
    ...(results.length === 0 && { suggestions: listCategories("recipes") }),
  };
}

export function listCategories(type) {
  const map = { dimensions, materials, recipes };
  const items = map[type] || [];
  return [...new Set(items.map((i) => i._category))];
}
