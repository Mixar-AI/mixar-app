# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

# This test file constructs SPDX-formatted strings as test fixtures to
# exercise apply_spdx_headers.py. REUSE's linter would otherwise parse
# those literals as real SPDX directives. Ignore everything below.
#
# REUSE-IgnoreStart

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "open_source" / "apply_spdx_headers.py"
SPDX_LICENSE_TAG = "SPDX-License-" "Identifier:"
SPDX_COPYRIGHT_TAG = "SPDX-FileCopyright" "Text:"
MIXAR = "2026 Adeveda Enterprises Private Limited"


def run(cmd, cwd):
    return subprocess.run(
        cmd, cwd=cwd, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )


def test_inserts_header_with_separator_and_trailing_blank(tmp_path):
    target = tmp_path / "tool.py"
    target.write_text("#!/usr/bin/env python3\nprint('hello')\n")

    result = run([str(SCRIPT), "--root", str(tmp_path), "--write", "tool.py"], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert target.read_text() == (
        "#!/usr/bin/env python3\n"
        f"# {SPDX_COPYRIGHT_TAG} {MIXAR}\n"
        "#\n"
        f"# {SPDX_LICENSE_TAG} GPL-3.0-or-later\n"
        "\n"
        "print('hello')\n"
    )


def test_infers_license_from_siblings(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "existing.py").write_text(f"# {SPDX_LICENSE_TAG} GPL-2.0-or-later\n")
    target = package / "tool.py"
    target.write_text("print('hi')\n")

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write", "--infer-from-siblings", "package/tool.py"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert target.read_text().startswith(
        f"# {SPDX_COPYRIGHT_TAG} {MIXAR}\n"
        "#\n"
        f"# {SPDX_LICENSE_TAG} GPL-2.0-or-later\n"
        "\n"
    )


def test_dry_run_does_not_modify(tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text("# Title\n")

    result = run([str(SCRIPT), "--root", str(tmp_path), "README.md"], cwd=tmp_path)

    assert result.returncode == 1
    assert "would update: README.md" in result.stdout
    assert doc.read_text() == "# Title\n"


def test_html_style_for_markdown(tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text("# Title\n")

    result = run([str(SCRIPT), "--root", str(tmp_path), "--write", "README.md"], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert doc.read_text() == (
        f"<!-- {SPDX_COPYRIGHT_TAG} {MIXAR} -->\n"
        f"<!-- {SPDX_LICENSE_TAG} GPL-3.0-or-later -->\n"
        "\n"
        "# Title\n"
    )


def test_paths_from_file(tmp_path):
    path_list = tmp_path / "paths.txt"
    script = tmp_path / "script.sh"
    script.write_text("echo hi\n")
    path_list.write_text("script.sh\n")

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write", "--paths-from", str(path_list)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert script.read_text().startswith(
        f"# {SPDX_COPYRIGHT_TAG} {MIXAR}\n"
        "#\n"
        f"# {SPDX_LICENSE_TAG} GPL-3.0-or-later\n"
        "\n"
    )


def test_skips_files_that_already_have_spdx_by_default(tmp_path):
    target = tmp_path / "module.py"
    initial = (
        f"# {SPDX_COPYRIGHT_TAG} 2010 Some Other Holder\n"
        "#\n"
        f"# {SPDX_LICENSE_TAG} GPL-2.0-or-later\n"
        "\n"
        "x = 1\n"
    )
    target.write_text(initial)

    result = run([str(SCRIPT), "--root", str(tmp_path), "--write", "module.py"], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert target.read_text() == initial


def test_reformat_normalizes_cramped_header_without_touching_content(tmp_path):
    target = tmp_path / "module.py"
    target.write_text(
        f"# {SPDX_COPYRIGHT_TAG} 2010 Upstream Author\n"
        f"# {SPDX_LICENSE_TAG} GPL-2.0-or-later\n"
        "x = 1\n"
    )

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write", "--reformat", "module.py"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert target.read_text() == (
        f"# {SPDX_COPYRIGHT_TAG} 2010 Upstream Author\n"
        "#\n"
        f"# {SPDX_LICENSE_TAG} GPL-2.0-or-later\n"
        "\n"
        "x = 1\n"
    )


def test_reformat_is_idempotent(tmp_path):
    target = tmp_path / "module.py"
    canonical = (
        f"# {SPDX_COPYRIGHT_TAG} 2010 Upstream Author\n"
        "#\n"
        f"# {SPDX_LICENSE_TAG} GPL-2.0-or-later\n"
        "\n"
        "x = 1\n"
    )
    target.write_text(canonical)

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write", "--reformat", "module.py"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert target.read_text() == canonical
    assert "already-canonical" in result.stdout


def test_add_copyright_appends_below_existing(tmp_path):
    target = tmp_path / "module.py"
    target.write_text(
        f"# {SPDX_COPYRIGHT_TAG} 2010 Upstream Author\n"
        "#\n"
        f"# {SPDX_LICENSE_TAG} GPL-2.0-or-later\n"
        "\n"
        "x = 1\n"
    )

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write",
         "--add-copyright", MIXAR, "module.py"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert target.read_text() == (
        f"# {SPDX_COPYRIGHT_TAG} 2010 Upstream Author\n"
        f"# {SPDX_COPYRIGHT_TAG} {MIXAR}\n"
        "#\n"
        f"# {SPDX_LICENSE_TAG} GPL-2.0-or-later\n"
        "\n"
        "x = 1\n"
    )


def test_add_copyright_is_noop_if_already_present(tmp_path):
    target = tmp_path / "module.py"
    initial = (
        f"# {SPDX_COPYRIGHT_TAG} 2010 Upstream Author\n"
        f"# {SPDX_COPYRIGHT_TAG} {MIXAR}\n"
        "#\n"
        f"# {SPDX_LICENSE_TAG} GPL-2.0-or-later\n"
        "\n"
        "x = 1\n"
    )
    target.write_text(initial)

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write",
         "--add-copyright", MIXAR, "module.py"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert target.read_text() == initial


def test_add_copyright_preserves_upstream_license(tmp_path):
    target = tmp_path / "module.py"
    target.write_text(
        f"# {SPDX_COPYRIGHT_TAG} 2010 Upstream Author\n"
        "#\n"
        f"# {SPDX_LICENSE_TAG} GPL-2.0-or-later\n"
        "\n"
        "x = 1\n"
    )

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write",
         "--license", "MIT", "--add-copyright", MIXAR, "module.py"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    text = target.read_text()
    assert text.count(SPDX_LICENSE_TAG) == 1
    assert "GPL-2.0-or-later" in text
    assert "MIT" not in text


def test_cblock_with_block_comment_is_reformatted_not_duplicated(tmp_path):
    target = tmp_path / "file.cc"
    target.write_text(
        "/* SPDX-FileCopyrightText: 2001-2002 NaN Holding BV. All rights reserved.\n"
        " *\n"
        " * SPDX-License-Identifier: GPL-2.0-or-later */\n"
        "\n"
        "#include <iostream>\n"
    )

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write",
         "--reformat", "--add-copyright", MIXAR, "file.cc"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    text = target.read_text()
    assert text.count(SPDX_COPYRIGHT_TAG) == 2
    assert text.count(SPDX_LICENSE_TAG) == 1
    assert text == (
        "/* SPDX-FileCopyrightText: 2001-2002 NaN Holding BV. All rights reserved.\n"
        f" * {SPDX_COPYRIGHT_TAG} {MIXAR}\n"
        " *\n"
        " * SPDX-License-Identifier: GPL-2.0-or-later */\n"
        "\n"
        "#include <iostream>\n"
    )


def test_slash_style_existing_block_is_preserved(tmp_path):
    target = tmp_path / "file.cc"
    target.write_text(
        f"// {SPDX_COPYRIGHT_TAG} 2024 Some Author\n"
        f"// {SPDX_LICENSE_TAG} GPL-2.0-or-later\n"
        "int main() {}\n"
    )

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write", "--reformat",
         "--add-copyright", MIXAR, "file.cc"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert target.read_text() == (
        f"// {SPDX_COPYRIGHT_TAG} 2024 Some Author\n"
        f"// {SPDX_COPYRIGHT_TAG} {MIXAR}\n"
        "//\n"
        f"// {SPDX_LICENSE_TAG} GPL-2.0-or-later\n"
        "\n"
        "int main() {}\n"
    )


def test_migrate_license_flips_matching_id(tmp_path):
    target = tmp_path / "module.py"
    initial = (
        f"# {SPDX_COPYRIGHT_TAG} {MIXAR}\n"
        "#\n"
        f"# {SPDX_LICENSE_TAG} GPL-3.0-only\n"
        "\n"
        "x = 1\n"
    )
    target.write_text(initial)

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write",
         "--migrate-license", "GPL-3.0-only", "GPL-3.0-or-later", "module.py"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert target.read_text() == initial.replace("GPL-3.0-only", "GPL-3.0-or-later")


def test_migrate_license_skips_non_matching_id(tmp_path):
    target = tmp_path / "module.py"
    initial = (
        f"# {SPDX_COPYRIGHT_TAG} {MIXAR}\n"
        "#\n"
        f"# {SPDX_LICENSE_TAG} GPL-2.0-or-later\n"
        "\n"
        "x = 1\n"
    )
    target.write_text(initial)

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write",
         "--migrate-license", "GPL-3.0-only", "GPL-3.0-or-later", "module.py"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert target.read_text() == initial  # untouched


def test_migrate_license_skips_file_without_spdx(tmp_path):
    target = tmp_path / "script.sh"
    initial = "#!/usr/bin/env bash\necho hi\n"
    target.write_text(initial)

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write",
         "--migrate-license", "GPL-3.0-only", "GPL-3.0-or-later", "script.sh"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert target.read_text() == initial  # untouched (no existing license to match)


def test_mixar_policy_modified_blender_inherits_upstream_license(tmp_path):
    """Files with an upstream/ counterpart get upstream's license; Mixar
    copyright appended below upstream's existing copyright."""
    (tmp_path / "upstream/source/blender/editors/space_view3d").mkdir(parents=True)
    (tmp_path / "src/source/blender/editors/space_view3d").mkdir(parents=True)

    (tmp_path / "upstream/source/blender/editors/space_view3d/view3d.cc").write_text(
        "/* SPDX-FileCopyrightText: 2007 Blender Foundation\n"
        " *\n"
        " * SPDX-License-Identifier: GPL-2.0-or-later */\n"
        "int main() {}\n"
    )
    target = tmp_path / "src/source/blender/editors/space_view3d/view3d.cc"
    target.write_text(
        "/* SPDX-FileCopyrightText: 2007 Blender Foundation\n"
        " *\n"
        " * SPDX-License-Identifier: GPL-3.0-or-later */\n"
        "int mixar_modified() {}\n"
    )

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write",
         "--mixar-policy", "src/source/blender/editors/space_view3d/view3d.cc"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    text = target.read_text()
    assert "SPDX-License-Identifier: GPL-2.0-or-later" in text
    assert "SPDX-License-Identifier: GPL-3.0-or-later" not in text
    assert "Blender Foundation" in text
    assert MIXAR in text


def test_mixar_policy_mixar_new_files_get_gpl3(tmp_path):
    """Files without an upstream/ counterpart get GPL-3.0-or-later."""
    (tmp_path / "src/source/blender/editors/space_mixie").mkdir(parents=True)
    target = tmp_path / "src/source/blender/editors/space_mixie/space_mixie.cc"
    target.write_text(
        "/* SPDX-FileCopyrightText: 2026 Mixar Authors\n"
        " *\n"
        " * SPDX-License-Identifier: GPL-2.0-or-later */\n"
        "void mixie() {}\n"
    )

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write",
         "--mixar-policy", "src/source/blender/editors/space_mixie/space_mixie.cc"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    text = target.read_text()
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in text
    assert "SPDX-License-Identifier: GPL-2.0-or-later" not in text
    assert MIXAR in text
    assert "Mixar Authors" in text  # original copyright preserved


def test_mixar_policy_brand_asset_gets_licenseref(tmp_path):
    """Files in MIXAR_BRAND_ASSETS get LicenseRef-Mixar-Brand."""
    target_path = "src/release/datafiles/icons_svg/mixar_icon.svg"
    (tmp_path / target_path).parent.mkdir(parents=True)
    target = tmp_path / target_path
    target.write_text(
        "<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->\n"
        "<!-- SPDX-License-Identifier: GPL-2.0-or-later -->\n"
        "<svg></svg>\n"
    )

    result = run(
        [str(SCRIPT), "--root", str(tmp_path), "--write",
         "--mixar-policy", target_path],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    text = target.read_text()
    assert "SPDX-License-Identifier: LicenseRef-Mixar-Brand" in text
    assert "SPDX-License-Identifier: GPL-2.0-or-later" not in text

# REUSE-IgnoreEnd
