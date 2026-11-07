# SPDX-FileCopyrightText: 2026 Mixar AI
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for matgen_persistence.py — pure filesystem, no Blender dependency."""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock


class TestMatgenPersistence(unittest.TestCase):

    def setUp(self):
        # Stub bpy before import
        sys.modules.setdefault('bpy', MagicMock())
        # Remove cached module to force fresh import
        for key in list(sys.modules.keys()):
            if 'matgen_persistence' in key:
                del sys.modules[key]
        from src.scripts.mixar.modules.paint.procedural_materials import matgen_persistence as mp
        self.mp = mp

    def test_safe_filename_truncates_and_adds_hash(self):
        name = self.mp._make_safe_filename("worn copper with green patina and lots of extra words that are very long")
        # Must end with _XXXX.py (4-char hash + .py)
        self.assertTrue(name.endswith(".py"))
        parts = name.rsplit("_", 1)
        self.assertEqual(len(parts[1].replace(".py", "")), 4)
        # Must be under 60 chars total
        self.assertLessEqual(len(name), 60)

    def test_safe_filename_basic(self):
        name = self.mp._make_safe_filename("worn copper")
        self.assertTrue(name.endswith(".py"))
        self.assertIn("worn_copper", name)

    def test_save_writes_script_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            mat = self.mp.save_generated_material(
                script="import bpy\ndef create_material(): pass",
                query="worn copper",
                archetype="metal",
                matgen_dir=tmp,
                catalog_path=os.path.join(tmp, "matgen_catalog.json"),
            )
            # mat.script_path is relative like "matgen/worn_copper_XXXX.py"
            # The actual file is at tmp/<filename>
            filename = os.path.basename(mat.script_path)
            script_path = os.path.join(tmp, filename)
            self.assertTrue(os.path.exists(script_path))
            with open(script_path) as f:
                self.assertIn("import bpy", f.read())

    def test_save_creates_catalog_if_missing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = os.path.join(tmp, "matgen_catalog.json")
            self.assertFalse(os.path.exists(catalog_path))

            mat = self.mp.save_generated_material(
                script="import bpy\ndef create_material(): pass",
                query="test material",
                archetype="stone",
                matgen_dir=tmp,
                catalog_path=catalog_path,
            )

            self.assertTrue(os.path.exists(catalog_path))
            with open(catalog_path) as f:
                data = json.load(f)
            self.assertEqual(len(data["materials"]), 1)
            self.assertEqual(data["materials"][0]["material_id"], mat.material_id)
            self.assertEqual(data["materials"][0]["category"], "ai_generated")
            self.assertEqual(data["materials"][0]["query"], "test material")

    def test_save_appends_to_existing_catalog(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = os.path.join(tmp, "matgen_catalog.json")
            # Pre-populate with one entry
            with open(catalog_path, "w") as f:
                json.dump({"materials": [
                    {"name": "Old Material", "category": "ai_generated",
                     "material_path": "matgen/old.py", "thumbnail_path": None}
                ]}, f)

            self.mp.save_generated_material(
                script="import bpy\ndef create_material(): pass",
                query="new material",
                archetype="metal",
                matgen_dir=tmp,
                catalog_path=catalog_path,
            )

            with open(catalog_path) as f:
                data = json.load(f)
            self.assertEqual(len(data["materials"]), 2)

    def test_corrupted_catalog_is_reset(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = os.path.join(tmp, "matgen_catalog.json")
            with open(catalog_path, "w") as f:
                f.write("NOT VALID JSON }{")

            # Should not raise; should reset and write fresh catalog
            self.mp.save_generated_material(
                script="import bpy\ndef create_material(): pass",
                query="test",
                archetype="metal",
                matgen_dir=tmp,
                catalog_path=catalog_path,
            )
            with open(catalog_path) as f:
                data = json.load(f)  # Must be valid JSON now
            self.assertEqual(len(data["materials"]), 1)

    def test_duplicate_query_does_not_create_duplicate_catalog_entry(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = os.path.join(tmp, "matgen_catalog.json")
            kwargs = dict(
                script="import bpy\ndef create_material(): pass",
                query="worn copper",
                archetype="metal",
                matgen_dir=tmp,
                catalog_path=catalog_path,
            )
            self.mp.save_generated_material(**kwargs)
            self.mp.save_generated_material(**kwargs)  # same query again

            with open(catalog_path) as f:
                data = json.load(f)
            self.assertEqual(len(data["materials"]), 1, "Duplicate query must not create two catalog entries")

    def test_returned_material_info_has_correct_fields(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            mat = self.mp.save_generated_material(
                script="import bpy\ndef create_material(): pass",
                query="rusty iron",
                archetype="metal",
                matgen_dir=tmp,
                catalog_path=os.path.join(tmp, "matgen_catalog.json"),
            )
            self.assertTrue(hasattr(mat, 'material_id'))
            self.assertTrue(hasattr(mat, 'name'))
            self.assertTrue(hasattr(mat, 'category'))
            self.assertTrue(hasattr(mat, 'script_path'))
            self.assertTrue(hasattr(mat, 'thumbnail_path'))
            self.assertTrue(hasattr(mat, 'node_group_name'))
            self.assertEqual(mat.category, "ai_generated")
            self.assertIsNone(mat.thumbnail_path)
            self.assertIn("rusty_iron", mat.material_id)
