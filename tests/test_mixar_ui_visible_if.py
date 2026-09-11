# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Native strips honor catalog ``visible_if`` from the generated param group."""

from pathlib import Path
from types import SimpleNamespace
import json
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
ENGINE = (
    ROOT
    / "src/scripts/mixar/modules/common/generation_params/core/engine.py"
)
VISIBLE_IF_PY = (
    ROOT
    / "src/scripts/mixar/modules/common/generation_params/core/visible_if.py"
)
CONSTANTS = (
    ROOT
    / "src/scripts/mixar/modules/common/generation_params/constants.py"
)


def _schema():
    return {
        "mode": {
            "spec": {"type": "string"},
            "attr": "p_mode",
            "value_map": {"video": "video", "image": "image"},
        },
        "duration": {
            "spec": {"visible_if": {"mode": "video"}},
            "attr": "p_duration",
            "value_map": None,
        },
        "seed": {
            "spec": {"visible_if": {"quality": "high"}},
            "attr": "p_seed",
            "value_map": None,
        },
        "quality": {
            "spec": {"type": "string"},
            "attr": "p_quality",
            "value_map": {"high": "high", "low": "low"},
        },
        "ghost": {
            "spec": {"visible_if": {"missing_param": True}},
            "attr": "p_ghost",
            "value_map": None,
        },
    }


def test_python_visibility_matches_encoded_table():
    from mixar.modules.common.generation_params.core.engine import is_param_visible
    from mixar.modules.common.generation_params.core.visible_if import (
        encode_visible_if_table,
    )
    from mixar.modules.common.generation_params.constants import VISIBLE_IF_MISSING

    schema = _schema()
    table = json.loads(encode_visible_if_table(schema))
    assert table["p_duration"] == {"p_mode": "video"}
    assert table["p_seed"] == {"p_quality": "high"}
    assert table["p_ghost"] == {VISIBLE_IF_MISSING: ""}
    assert "p_mode" not in table

    group = SimpleNamespace(p_mode="video", p_duration=8, p_quality="low", p_seed=1)
    assert is_param_visible(schema, group, "duration")
    group.p_mode = "image"
    assert not is_param_visible(schema, group, "duration")
    assert not is_param_visible(schema, group, "ghost")
    assert is_param_visible(schema, group, "mode")


def test_engine_attaches_visible_if_metadata():
    from mixar.modules.common.generation_params.constants import VISIBLE_IF_ATTR

    engine = ENGINE.read_text(encoding="utf-8")
    constants = CONSTANTS.read_text(encoding="utf-8")
    header = (CPP / "agent_ui_visible_if.hh").read_text(encoding="utf-8")
    # Blender RNA refuses identifiers that start with '_'; `p_` would
    # show up as a native generation chip.
    assert VISIBLE_IF_ATTR == "mixar_visible_if"
    assert not VISIBLE_IF_ATTR.startswith("_")
    assert not VISIBLE_IF_ATTR.startswith("p_")
    assert f'VISIBLE_IF_ATTR = "{VISIBLE_IF_ATTR}"' in constants
    assert f'PANE_VISIBLE_IF_ATTR = "{VISIBLE_IF_ATTR}"' in header
    assert "annotations[VISIBLE_IF_ATTR]" in engine
    assert "encode_visible_if_table(schema)" in engine
    assert "VISIBLE_IF_MISSING" in VISIBLE_IF_PY.read_text(encoding="utf-8")


def test_strips_evaluate_visible_if_before_placing_chips():
    params = (CPP / "agent_ui_tab3d_params.cc").read_text(encoding="utf-8")
    media = (CPP / "agent_ui_tabmedia_util.cc").read_text(encoding="utf-8")
    splat = (CPP / "agent_ui_tabsplat.cc").read_text(encoding="utf-8")
    cmake = (CPP / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "pane_schema_param_visible(group_ptr, identifier)" in params
    assert "pane_schema_param_visible(group, ident)" in media
    assert "pane_schema_param_visible(&state.params, \"p_mode\")" in splat
    assert "pane_schema_param_visible(&state.params, \"p_lod\")" in splat
    assert "agent_ui_visible_if.cc" in cmake
    hidden = media[media.index("pane_schema_param_visible(group, ident)") :]
    assert hidden.index("continue") < hidden.index("(*r_total)++")


def test_cpp_parser_matches_python_table(tmp_path):
    from mixar.modules.common.generation_params.core.visible_if import (
        encode_visible_if_table,
    )

    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    payload = encode_visible_if_table(_schema())
    source = tmp_path / "visible_if.cc"
    source.write_text(
        """
#include "agent_ui_visible_if.hh"
#include <cassert>
#include <string>
#include <unordered_map>
using namespace blender;
static std::optional<std::string> lookup(
    const std::unordered_map<std::string, std::string> &values, std::string_view other)
{
  const auto it = values.find(std::string(other));
  if (it == values.end()) {
    return std::nullopt;
  }
  return it->second;
}
int main() {
  MixarVisibleIfTable table;
  assert(pane_visible_if_parse(R"JSON("""
        + payload
        + """)JSON", table));
  const std::unordered_map<std::string, std::string> video{
      {"p_mode", "video"}, {"p_quality", "low"}};
  const std::unordered_map<std::string, std::string> image{
      {"p_mode", "image"}, {"p_quality", "high"}};
  auto from_video = [&](std::string_view other) { return lookup(video, other); };
  auto from_image = [&](std::string_view other) { return lookup(image, other); };
  assert(pane_visible_if_matches(table, "p_duration", from_video));
  assert(!pane_visible_if_matches(table, "p_duration", from_image));
  assert(pane_visible_if_matches(table, "p_seed", from_image));
  assert(!pane_visible_if_matches(table, "p_ghost", from_video));
  MixarVisibleIfTable numeric;
  assert(pane_visible_if_parse(R"({"p_x":{"p_n":"1.0"}})", numeric));
  const std::unordered_map<std::string, std::string> one{{"p_n", "1"}};
  auto from_one = [&](std::string_view other) { return lookup(one, other); };
  assert(pane_visible_if_matches(table, "p_mode", from_video));
  assert(!pane_visible_if_matches(numeric, "p_x", from_one));
  MixarVisibleIfTable empty;
  assert(pane_visible_if_parse("{}", empty));
  assert(empty.by_attr.empty());
  MixarVisibleIfTable bad;
  assert(!pane_visible_if_parse("not-json", bad));
}
"""
    )
    binary = tmp_path / "visible_if"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-I",
            str(CPP),
            str(source),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True)


def test_native_visibility_matches_python_edge_values(tmp_path):
    """Use the Python visibility predicate as oracle for the production C++ reader."""
    import struct
    from mixar.modules.common.generation_params.core.engine import is_param_visible
    from mixar.modules.common.generation_params.core.visible_if import encode_visible_if_table

    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    rounded = struct.unpack("f", struct.pack("f", 1.234567))[0]
    cases = [
        ("string", "01", "1", None),
        ("string", "1", "1.0", {"1": "1"}),
        ("string", "9007199254740992", "9007199254740993", None),
        ("string", "🎨", "🎨", {"🎨": "🎨"}),
        ("string", "材質\b\f", "材質\b\f", None),
        ("boolean", True, True, None),
        ("integer", 1, 1.0, None),
        ("number", 1.0, 1, None),
        ("number", 1.0, 1.0, None),
        ("number", 1.0, "01", None),
        ("number", -0.0, 0.0, None),
        ("number", rounded, rounded, None),
        ("number", rounded, 1.234567, None),
        ("float", 1e20, 1e20, None),
        ("number", "01", "1", {"01": "01"}),
    ]
    checks = []
    for ptype, current, expected, value_map in cases:
        native_float = ptype in {"float", "number"} and value_map is None
        if native_float:
            current = struct.unpack("f", struct.pack("f", current))[0]
        schema = {
            "guard": {"spec": {"type": ptype}, "attr": "p_guard", "value_map": value_map},
            "dependent": {"spec": {"visible_if": {"guard": expected}}, "attr": "p_dependent"},
        }
        verdict = is_param_visible(schema, SimpleNamespace(p_guard=current), "dependent")
        payload = encode_visible_if_table(schema)
        current_expr = (
            f"visible_if_detail::float_string(float({current!r}))"
            if native_float else f'R"VALUE({current})VALUE"'
        )
        checks.append(f'''{{
            MixarVisibleIfTable table;
            assert(pane_visible_if_parse(R"JSON({payload})JSON", table));
            auto read = [](std::string_view name) -> std::optional<std::string> {{
                if (name != "p_guard") return std::nullopt;
                return {current_expr};
            }};
            assert(pane_visible_if_matches(table, "p_dependent", read) == {str(verdict).lower()});
        }}''')
    source = tmp_path / "edge_values.cc"
    source.write_text('''#include "agent_ui_visible_if.hh"
#include <cassert>
using namespace blender;
struct CommaDecimal : std::numpunct<char> {
  char do_decimal_point() const override { return ','; }
};
int main() {
  std::locale::global(std::locale(std::locale::classic(), new CommaDecimal));
''' + "\n".join(checks) + "\n}", encoding="utf-8")
    binary = tmp_path / "edge_values"
    subprocess.run([compiler, "-std=c++17", "-I", str(CPP), str(source), "-o", str(binary)],
                   check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)
