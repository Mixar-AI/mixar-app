# SPDX-FileCopyrightText: 2026 Mixar AI
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for matgen_client.py: mocks requests, no Blender dependency."""

import queue
import sys
import unittest
from unittest.mock import MagicMock, patch


class TestMatgenClient(unittest.TestCase):

    def _import_client(self):
        """Import after patching bpy so it loads without Blender."""
        sys.modules.setdefault('bpy', MagicMock())
        for key in list(sys.modules.keys()):
            if 'matgen_client' in key:
                del sys.modules[key]
        from src.scripts.mixar.modules.paint.procedural_materials import matgen_client as mc
        return mc

    def test_fetch_catalog_success_puts_materials_in_queue(self):
        mc = self._import_client()
        result_queue = queue.Queue()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "materials": [
                    {
                        "material_id": "wood_oak",
                        "name": "Oak",
                        "category": "wood",
                        "thumbnail_url": None,
                    }
                ],
            },
        }

        with patch(
            'src.scripts.mixar.modules.paint.procedural_materials.matgen_client.requests.get',
            return_value=mock_response,
        ) as mock_get:
            mc.fetch_catalog_async("fake-token", "http://localhost:8000", result_queue)

        result = result_queue.get_nowait()
        self.assertTrue(result["ok"])
        self.assertEqual(result["materials"][0]["material_id"], "wood_oak")
        mock_get.assert_called_once()
        self.assertTrue(mock_get.call_args.args[0].endswith("/api/v1/mat-gen/catalog"))

    def test_fetch_script_success_puts_script_in_queue(self):
        mc = self._import_client()
        result_queue = queue.Queue()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "script": "import bpy\ndef create_material(): pass",
                "name": "Oak",
            },
        }

        with patch(
            'src.scripts.mixar.modules.paint.procedural_materials.matgen_client.requests.get',
            return_value=mock_response,
        ) as mock_get:
            mc.fetch_script_async(
                "wood_oak",
                "fake-token",
                "http://localhost:8000",
                result_queue,
            )

        result = result_queue.get_nowait()
        self.assertTrue(result["ok"])
        self.assertIn("import bpy", result["script"])
        self.assertEqual(result["name"], "Oak")
        self.assertTrue(mock_get.call_args.args[0].endswith("/api/v1/mat-gen/script/wood_oak"))

    def test_fetch_script_error_puts_error_in_queue(self):
        mc = self._import_client()
        result_queue = queue.Queue()

        with patch(
            'src.scripts.mixar.modules.paint.procedural_materials.matgen_client.requests.get',
            side_effect=Exception("Connection refused"),
        ):
            mc.fetch_script_async(
                "wood_oak",
                "fake-token",
                "http://localhost:8000",
                result_queue,
            )

        result = result_queue.get_nowait()
        self.assertFalse(result["ok"])
        self.assertIn("Connection refused", result["error"])
