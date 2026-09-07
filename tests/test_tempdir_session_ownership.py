# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exercise the native purge decision with fake filesystem calls.

The fallback case cannot safely be induced against the real system temp
directory. Compile the production function with a recording delete stub.
"""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_purge_deletes_only_an_owned_existing_session_directory(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("native temp-directory regression requires a C++ compiler")
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/source/blender/blenkernel/intern/appdir.cc").read_text(
        encoding="utf-8"
    )
    start = source.index("void BKE_tempdir_session_purge()\n{")
    function = source[start:source.index("\n}\n", start) + 2]
    probe = tmp_path / "purge.cc"
    probe.write_text("""
        #include <cassert>
        struct {
          char temp_dirname_session[8] = "base";
          bool temp_dirname_session_can_be_deleted = false;
        } g_app;
        bool exists = true;
        int deletions = 0;
        bool BLI_is_dir(const char *) { return exists; }
        void BLI_delete(const char *, bool, bool) { ++deletions; }
        """ + function + """
        int main() {
          BKE_tempdir_session_purge();
          assert(deletions == 0); // Existing base fallback is not ours.
          g_app.temp_dirname_session_can_be_deleted = true;
          BKE_tempdir_session_purge();
          assert(deletions == 1); // Our private session gets cleaned up.
          exists = false;
          BKE_tempdir_session_purge();
          assert(deletions == 1);
          exists = true;
          g_app.temp_dirname_session[0] = '\\0';
          BKE_tempdir_session_purge();
          assert(deletions == 1);
        }
        """, encoding="utf-8")
    executable = tmp_path / "purge"
    subprocess.run([compiler, "-std=c++17", str(probe), "-o", str(executable)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)
