# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The message extractor sees exactly the strings Blender looks up."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "i18n"))

import extract_cpp  # noqa: E402
import extract_python  # noqa: E402

PY_SOURCE = '''
class MIXAR_OT_bake(bpy.types.Operator):
    """Bake the layer.

        Second line
    """
    bl_idname = "mixar.bake"
    bl_label = "Bake Layer"
    mode: EnumProperty(name="Mode", items=[("A", "Alpha", "First"), ("B", "Beta", "", "NONE", 1)])

    def draw(self, context):
        self.layout.label(text="Hello")
        self.layout.label(text=obj.name, translate=False)
        self.layout.label(text="Not me", translate=False)
        self.layout.operator("x.y", text="Stop" if running else "Start")
        self.layout.label(text=f"Dynamic {x}")
        self.report({"ERROR"}, "Failed")
        iface_("{count} items").format(count=3)
        n_("Marked")
        tip_("In mesh", "Mesh")

class MIXAR_PT_panel(bpy.types.Panel):
    bl_label = "Panel"
    bl_description = "Explicit"
    bl_category = "Mixar"
    """Docstring ignored: bl_description wins."""
'''

CPP_SOURCE = r'''
static const EnumPropertyItem items[] = {
  {0, "NONE", ICON_NONE, "None", "No thing"},
  {1, "SOME", 0, N_("Some"), nullptr},
  {0, nullptr, 0, nullptr, nullptr},
};
static const char *prompts[] = {"GENERATE", "model_3d", "image", "video",};
void MIXAR_OT_foo(wmOperatorType *ot) {
  ot->name = "Do Foo";
  ot->description = "Does foo " "really well";
  RNA_def_boolean(ot->srna, "flag", false, "Flag", "A flag");
  RNA_def_int(ot->srna, "count", 1, 0, 10, "Count", "How many", 0, 10);
  RNA_def_string(ot->srna, "path", "default", 0, "Path", "File path");
  RNA_def_boolean(func, "api_param", false, "", "Python API doc, not UI");
}
void draw() {
  BLF_draw(0, IFACE_("Hello world"), 5);
  BKE_reportf(op->reports, RPT_ERROR, "Failed %s", x);
  BKE_report(op->reports, RPT_INFO, ok ? "Done" : "Nothing to do");
  const char *s = CTX_IFACE_("Mesh", "Face");  // IFACE_("comment")
  const char c = '"';
  label(IFACE_("Say \"hi\"\n"));
}
'''


def _messages(found):
    return {(m.msgctxt, m.msgid) for m in found}


def test_python_extraction():
    found = _messages(extract_python.extract_source(PY_SOURCE, "x.py"))
    assert found == {
        (None, "Bake Layer"), (None, "Bake the layer.\n\nSecond line\n"),
        (None, "Mode"), (None, "Alpha"), (None, "First"), (None, "Beta"),
        (None, "Hello"), (None, "Stop"), (None, "Start"), (None, "Failed"),
        (None, "{count} items"), (None, "Marked"), ("Mesh", "In mesh"),
        (None, "Panel"), (None, "Explicit"), (None, "Mixar"),
    }


def test_docstring_matches_python_313_cleaning():
    assert extract_python.clean_docstring("Line.\n\n        More\n    ") == "Line.\n\nMore\n"
    assert extract_python.clean_docstring("  One line") == "One line"


def test_cpp_extraction():
    found = _messages(extract_cpp.extract_source(CPP_SOURCE, "x.cc"))
    assert found == {
        (None, "None"), (None, "No thing"), (None, "Some"),
        (None, "Do Foo"), (None, "Does foo really well"),
        (None, "Flag"), (None, "A flag"), (None, "Count"), (None, "How many"),
        (None, "Path"), (None, "File path"),
        (None, "Hello world"), (None, "Failed %s"), (None, "Done"), (None, "Nothing to do"),
        ("Mesh", "Face"), (None, 'Say "hi"\n'),
    }


def test_operator_translation_context_is_kept():
    source = '''void OT(wmOperatorType *ot) { ot->name = "Grab";
      ot->translation_context = BLT_I18NCONTEXT_ID_MESH; }
      void OT2(wmOperatorType *ot) { ot->name = "Plain"; }'''
    found = extract_cpp.extract_source(source, "x.cc", {"BLT_I18NCONTEXT_ID_MESH": "Mesh"})
    assert _messages(found) == {("Mesh", "Grab"), (None, "Plain")}


def test_rtl_catalog_text_is_stored_visual_like_blenders():
    import pytest
    rtl = pytest.importorskip("rtl")
    try:
        visual = rtl.log2vis("שלום {name}\nשורה 2")
    except RuntimeError:
        pytest.skip("fribidi not installed")
    # Reversed line by line, placeholders intact and in reading position.
    assert visual == "{name} םולש\n2 הרוש"
    arabic = rtl.log2vis("ملف {count}")
    assert "{count}" in arabic and rtl.is_visual(arabic)


def test_rtl_protects_whole_replacement_fields():
    import pytest
    rtl = pytest.importorskip("rtl")
    # Format specs of any shape stay one unit, so reordering cannot flip them.
    for field in ("{faces:,}", "{x:>8}", "{count:.1f}", "{0}", "{}", "%.2f", "{{"):
        assert rtl.LRE + field + rtl.PDF in rtl.protect_format_seq("a " + field + " b")
