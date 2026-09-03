# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HUNYUAN_OPS = ROOT / "src/scripts/mixar/modules/hunyuan/ui/operators/hunyuan_ops.py"


def read_ops() -> str:
    return HUNYUAN_OPS.read_text(encoding="utf-8")


def test_agent_retopology_operator_accepts_model_param():
    src = read_ops()

    assert "# Retopology (TOPOLOGY) direct-invocation params" in src
    assert 'model: StringProperty(default="tripo")' in src


def test_agent_retopology_direct_passes_model_to_queue():
    src = read_ops()

    assert 'model = (self.model or "tripo").strip().lower()' in src
    assert 'if model not in {"tripo", "hunyuan"}:' in src
    assert '"model": model,' in src
