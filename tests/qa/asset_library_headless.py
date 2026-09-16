# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run with --background --factory-startup after the GUI QA scenario.

Use the same MIXAR_USER_RESOURCES. Factory preferences must not disable the
GUI catalog; headless agents must resolve the same exact biome identities.
"""
import json
import os
from pathlib import Path
import bpy
from mixar.modules.asset_search.core.catalog import service

assert bpy.app.background
result = service.search('pine', ['QA Biomes'], scatterable=True)
assert len(result['results']) == 2 and all(h['available'] for h in result['results']), result
report = dict(success=True, asset_ids=[h['asset_id'] for h in result['results']],
              source_id=result['source_id'], libraries=[lib['name'] for lib in result['libraries']])
out = Path(os.environ.get('ASSET_QA_OUT', '/tmp/mixar-assets-qa'))
(out / 'headless-report.json').write_text(json.dumps(report, indent=2))
print('__ASSET_QA__' + json.dumps(report))
