# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Additional CA certificates and the launcher-default fix (core/trust.py).

Two contracts an enterprise install depends on:

* Blender's launcher exports ``SSL_CERT_FILE=<bundled certifi>`` before
  Python starts. That value must NOT be mistaken for an operator override,
  or the OS trust store is never consulted.
* A root CA dropped into the certs folder (PEM or DER, any of the usual
  extensions) is trusted *in addition to* whatever roots apply, in every
  trust mode, by every ``ssl.SSLContext`` created afterwards.

``truststore`` is replaced by a recording stub in most tests, so the patch
is exercised against CPython's real ``ssl.SSLContext``; one test injects the
real truststore to prove its wrapper picks the certificates up too. The patch
is unwound after each test so the process's ``ssl`` module is left untouched.
"""

import base64
import os
import ssl
import sys
import types

import pytest

from mixar.modules.common.network import collect_extra_ca_certs, install_trust_store
from mixar.modules.common.network.constants import (
    CA_BUNDLE_ENV_VARS,
    TRUST_MODE_BUNDLE,
    TRUST_MODE_OS,
)
from mixar.modules.common.network.core import trust as trust_mod

# Self-signed "Mixar Test Root CA", valid for 100 years; a fixture only.
TEST_ROOT_PEM = """-----BEGIN CERTIFICATE-----
MIIDSTCCAjGgAwIBAgIUHjTDe93ObidsiukSwBXzyFCCjDMwDQYJKoZIhvcNAQEL
BQAwMzEbMBkGA1UEAwwSTWl4YXIgVGVzdCBSb290IENBMRQwEgYDVQQKDAtNaXhh
ciBUZXN0czAgFw0yNjA5MDgxMzAwNDBaGA8yMTI2MDgxNTEzMDA0MFowMzEbMBkG
A1UEAwwSTWl4YXIgVGVzdCBSb290IENBMRQwEgYDVQQKDAtNaXhhciBUZXN0czCC
ASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAOcUTG8rprf1eILsC1PUnWvr
XCvhOajZvKCYVF44dpXRbxYkUF/UJ70LwE9MHO+QbiiOxtJIiAUeyoPS8Nv9xlPr
dWRO8pjHivjnFnAYDyXEs4Lh76/ZJouSdIERTUkVzrIxS1l8HcAG/Vsdm45OmGHM
FJpNOcqEs29WvuWhv4WBViYQ39BPq7o1y9KFu7pVL9TIeLFGDAShwnrkf6r6857B
uT/Xc4SAvOxeqoeHdR4iEkwyNc/tFjG6y1UgzRoRIEvAfub5jShPD+Docc2JA6Jd
K1YyzlJxAQ5+Wg/+cRo1ASS6Md2lDeR4i+se6Kid/Ui4771xpmcdL/3zrU13YG8C
AwEAAaNTMFEwHQYDVR0OBBYEFARXn1X1p/BB4SXt30BiRztaRPzTMB8GA1UdIwQY
MBaAFARXn1X1p/BB4SXt30BiRztaRPzTMA8GA1UdEwEB/wQFMAMBAf8wDQYJKoZI
hvcNAQELBQADggEBAFz0wv22YjCbFjBBIM/nBgT28/+Ca2mWJ5rZr8LPGwC4r/4l
OCdfy4sex1/T2bSiVa3DdSWUSKiztOiNqfEILsj4xk3OSbVm81ZhtqoA0+P7NX4G
+66NNmC15cXCJo/9pjlZpfAGfxi+q2kaPUCTkKhTDAv/fl/XUIhVHfWyGdYBxy2k
+imrawrzkjb2AsDT5f+xevY1zhCH18iEwbtEPqOtNgCWOel6mknRJ3si9vmCrNT4
0IdqfkFJDZH9F2GlH2QERIO9eFwbVDsLv5ERYuQi6LFG+ZvPyFld1eMTd4veFmPj
sCxQKB5QETjr4fu2Q/nPy3p1ckXiffav6CXi46I=
-----END CERTIFICATE-----
"""
TEST_ROOT_DER = base64.b64decode("".join(TEST_ROOT_PEM.strip().splitlines()[1:-1]))
TEST_ROOT_SUBJECT = ((("commonName", "Mixar Test Root CA"),), (("organizationName", "Mixar Tests"),))


@pytest.fixture
def isolated_trust(monkeypatch):
    """Recording truststore stub, no drop-folder discovery, wrapper unwound after."""
    calls = []
    module = types.ModuleType("truststore")
    module.inject_into_ssl = lambda: calls.append("inject")
    monkeypatch.setitem(sys.modules, "truststore", module)
    monkeypatch.setattr(trust_mod, "_report", None)
    monkeypatch.setattr(trust_mod.sys, "platform", "darwin")
    monkeypatch.setattr(trust_mod, "default_certs_search_dirs", lambda environ=None: ())
    original_class, original_new = ssl.SSLContext, ssl.SSLContext.__new__
    yield calls
    trust_mod._uninstall_extra_certs()
    assert ssl.SSLContext is original_class
    assert ssl.SSLContext.__new__ is original_new


def _subjects(context):
    return [cert["subject"] for cert in context.get_ca_certs()]


# --- Launcher default must not masquerade as an operator override -----------


def test_launcher_certifi_ssl_cert_file_is_not_an_override(isolated_trust, monkeypatch, tmp_path):
    bundled = tmp_path / "python" / "site-packages" / "certifi" / "cacert.pem"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("x")
    monkeypatch.setattr(trust_mod, "_certifi_path", lambda: str(bundled))
    env = {"SSL_CERT_FILE": str(bundled)}
    report = install_trust_store(None, env, force=True)
    assert report.mode == TRUST_MODE_OS
    assert isolated_trust == ["inject"]
    assert "REQUESTS_CA_BUNDLE" not in env


def test_ssl_cert_file_inside_the_interpreter_prefix_is_ignored(isolated_trust, monkeypatch, tmp_path):
    prefix = tmp_path / "blender-python"
    inside = prefix / "lib" / "cert.pem"
    inside.parent.mkdir(parents=True)
    inside.write_text("x")
    monkeypatch.setattr(trust_mod.sys, "prefix", str(prefix))
    monkeypatch.setattr(trust_mod.sys, "base_prefix", str(prefix))
    monkeypatch.setattr(trust_mod.sys, "exec_prefix", str(prefix))
    monkeypatch.setattr(trust_mod, "_certifi_path", lambda: "")
    report = install_trust_store(None, {"SSL_CERT_FILE": str(inside)}, force=True)
    assert report.mode == TRUST_MODE_OS


def test_operator_ssl_cert_file_outside_the_interpreter_is_still_honored(isolated_trust, monkeypatch, tmp_path):
    monkeypatch.setattr(trust_mod, "_certifi_path", lambda: str(tmp_path / "elsewhere.pem"))
    bundle = tmp_path / "it.pem"
    bundle.write_text("x")
    env = {"SSL_CERT_FILE": str(bundle)}
    report = install_trust_store(None, env, force=True)
    assert report.mode == TRUST_MODE_BUNDLE
    assert report.source == "env:SSL_CERT_FILE"
    assert isolated_trust == []


# --- Collecting extra certificates -------------------------------------------


def test_drop_folder_accepts_pem_and_der_under_any_extension(isolated_trust, tmp_path):
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "root.crt").write_text(TEST_ROOT_PEM)
    (certs / "root-der.cer").write_bytes(TEST_ROOT_DER)
    (certs / "README.txt").write_text("not a certificate")
    (certs / ".DS_Store").write_bytes(b"\x00")
    extra = collect_extra_ca_certs(None, {}, search_dirs=[str(certs)])
    assert extra.count == 1  # same certificate twice => deduplicated
    assert extra.files == (str(certs / "root-der.cer"),)  # first file wins, sorted order
    assert extra.errors == ()
    assert extra.pem.startswith("-----BEGIN CERTIFICATE-----")


def test_env_and_config_sources_accept_files_and_folders(isolated_trust, tmp_path):
    single = tmp_path / "corp.pem"
    single.write_text(TEST_ROOT_PEM)
    folder = tmp_path / "more"
    folder.mkdir()
    (folder / "same.crt").write_bytes(TEST_ROOT_DER)
    env = {"MIXAR_EXTRA_CA_CERTS": str(single)}
    config = lambda: {"network": {"extra_ca_certs": [str(folder)]}}
    extra = collect_extra_ca_certs(config, env, search_dirs=())
    assert extra.count == 1
    assert extra.files == (str(single),)


def test_config_string_is_split_on_pathsep(isolated_trust, tmp_path):
    a = tmp_path / "a.pem"
    b = tmp_path / "b.pem"
    a.write_text(TEST_ROOT_PEM)
    b.write_text(TEST_ROOT_PEM)
    config = lambda: {"network": {"extra_ca_certs": os.pathsep.join([str(a), str(b)])}}
    extra = collect_extra_ca_certs(config, {}, search_dirs=())
    assert extra.files == (str(a),)  # b holds the same certificate
    assert extra.count == 1


def test_unparsable_file_is_reported_and_skipped(isolated_trust, tmp_path):
    good = tmp_path / "good.pem"
    good.write_text(TEST_ROOT_PEM)
    bad = tmp_path / "bad.crt"
    bad.write_bytes(b"this is not a certificate")
    extra = collect_extra_ca_certs(None, {"MIXAR_EXTRA_CA_CERTS": os.pathsep.join([str(bad), str(good)])}, search_dirs=())
    assert extra.count == 1
    assert extra.files == (str(good),)
    assert len(extra.errors) == 1 and str(bad) in extra.errors[0]


def test_missing_explicit_path_is_an_error_not_a_crash(isolated_trust, tmp_path):
    extra = collect_extra_ca_certs(None, {"MIXAR_EXTRA_CA_CERTS": str(tmp_path / "nope.pem")}, search_dirs=())
    assert extra.count == 0
    assert "does not exist" in extra.errors[0]


def test_absent_drop_folders_are_silently_fine(isolated_trust, tmp_path):
    extra = collect_extra_ca_certs(None, {}, search_dirs=[str(tmp_path / "missing")])
    assert extra == trust_mod.ExtraCerts()


# --- Installing them into every new SSLContext --------------------------------


def test_extra_certs_reach_every_new_context_in_os_mode(isolated_trust, tmp_path):
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "corp-root.crt").write_text(TEST_ROOT_PEM)
    report = install_trust_store(None, {}, force=True, search_dirs=[str(certs)])
    assert report.mode == TRUST_MODE_OS
    assert report.extra_cert_count == 1
    assert report.extra_cert_files == (str(certs / "corp-root.crt"),)
    assert report.extra_cert_errors == ()

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    assert isinstance(context, ssl.SSLContext)
    assert TEST_ROOT_SUBJECT in _subjects(context)
    # The standard factory goes through the same class.
    assert TEST_ROOT_SUBJECT in _subjects(ssl.create_default_context())


def test_extra_certs_are_additive_in_custom_bundle_mode(isolated_trust, tmp_path):
    bundle = tmp_path / "corp-bundle.pem"
    bundle.write_text(TEST_ROOT_PEM)
    extra_dir = tmp_path / "certs"
    extra_dir.mkdir()
    (extra_dir / "second.der").write_bytes(TEST_ROOT_DER)
    env = {"MIXAR_CA_BUNDLE": str(bundle)}
    report = install_trust_store(None, env, force=True, search_dirs=[str(extra_dir)])
    assert report.mode == TRUST_MODE_BUNDLE
    assert report.extra_cert_count == 1
    for name in CA_BUNDLE_ENV_VARS:
        assert env[name] == str(bundle)  # the bundle export is untouched
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(bundle))  # what requests/urllib3 do next
    assert TEST_ROOT_SUBJECT in _subjects(context)


def test_reinstall_swaps_certificates_without_stacking_patches(isolated_trust, tmp_path):
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "corp-root.pem").write_text(TEST_ROOT_PEM)
    original_new = ssl.SSLContext.__new__
    install_trust_store(None, {}, force=True, search_dirs=[str(certs)])
    patched_new = ssl.SSLContext.__new__
    assert patched_new is not original_new
    install_trust_store(None, {}, force=True, search_dirs=[str(certs)])
    assert ssl.SSLContext.__new__ is patched_new
    assert trust_mod._original_new is original_new
    # Dropping every certificate restores the pristine constructor.
    empty = tmp_path / "empty"
    empty.mkdir()
    report = install_trust_store(None, {}, force=True, search_dirs=[str(empty)])
    assert report.extra_cert_count == 0
    assert ssl.SSLContext.__new__ is original_new
    assert TEST_ROOT_SUBJECT not in _subjects(ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))


def test_no_extra_certs_leaves_ssl_context_untouched(isolated_trust, tmp_path):
    original_new = ssl.SSLContext.__new__
    report = install_trust_store(None, {}, force=True, search_dirs=[str(tmp_path)])
    assert report.extra_cert_count == 0
    assert ssl.SSLContext.__new__ is original_new


def test_stdlib_property_setters_still_work_on_patched_contexts(isolated_trust, tmp_path):
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "corp-root.pem").write_text(TEST_ROOT_PEM)
    install_trust_store(None, {}, force=True, search_dirs=[str(certs)])
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.verify_mode = ssl.CERT_REQUIRED  # rebinding ssl.SSLContext would recurse here
    context.check_hostname = True
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    assert context.verify_mode is ssl.CERT_REQUIRED


def test_real_truststore_context_carries_the_extra_certificates(monkeypatch, tmp_path):
    monkeypatch.delitem(sys.modules, "truststore", raising=False)
    truststore = pytest.importorskip("truststore")
    monkeypatch.setattr(trust_mod, "_report", None)
    monkeypatch.setattr(trust_mod.sys, "platform", "darwin")
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "corp-root.crt").write_bytes(TEST_ROOT_DER)
    original_class = ssl.SSLContext
    try:
        report = install_trust_store(None, {}, force=True, search_dirs=[str(certs)])
        assert report.mode == TRUST_MODE_OS
        assert ssl.SSLContext is truststore.SSLContext
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        # truststore verifies with the OS and passes ``_ctx.get_ca_certs()`` —
        # its inner real context — as additional anchors; that is what we fill.
        assert TEST_ROOT_SUBJECT in _subjects(context._ctx)
        context.verify_mode = ssl.CERT_REQUIRED
    finally:
        trust_mod._uninstall_extra_certs()
        truststore.extract_from_ssl()
        ssl.SSLContext = original_class


def test_urllib3_contexts_carry_the_extra_certificates(isolated_trust, tmp_path):
    urllib3_ssl = pytest.importorskip("urllib3.util.ssl_")
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "corp-root.pem").write_text(TEST_ROOT_PEM)
    install_trust_store(None, {}, force=True, search_dirs=[str(certs)])
    context = urllib3_ssl.create_urllib3_context()
    assert TEST_ROOT_SUBJECT in _subjects(context)


def test_requests_preloaded_context_is_refreshed(isolated_trust, tmp_path, monkeypatch):
    adapters = pytest.importorskip("requests.adapters")
    # requests 2.32.0-2.32.3 (what the app bundles) keep one context at import;
    # emulate it on any version so the refresh path is always exercised.
    stale = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    monkeypatch.setattr(adapters, "_preloaded_ssl_context", stale, raising=False)
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "corp-root.pem").write_text(TEST_ROOT_PEM)
    install_trust_store(None, {}, force=True, search_dirs=[str(certs)])
    fresh = adapters._preloaded_ssl_context
    assert fresh is not stale
    assert TEST_ROOT_SUBJECT in _subjects(fresh)
    assert fresh.verify_mode is ssl.CERT_REQUIRED


def test_diagnostics_expose_extra_cert_count(isolated_trust, tmp_path, monkeypatch):
    from mixar.modules.common.network.core import setup as setup_mod

    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "corp-root.pem").write_text(TEST_ROOT_PEM)
    (certs / "broken.crt").write_bytes(b"junk")
    monkeypatch.setattr(setup_mod, "_report", None)
    install_trust_store(None, {}, force=True, search_dirs=[str(certs)])
    diagnostics = setup_mod.network_diagnostics()
    assert diagnostics["extra_ca_certs"] == 1
    assert "broken.crt" in diagnostics["extra_ca_errors"]


# --- Drop-folder locations -----------------------------------------------------


def test_machine_certs_dirs_per_platform():
    assert trust_mod.machine_certs_dirs("darwin") == ("/Library/Application Support/Mixar/certs",)
    assert trust_mod.machine_certs_dirs("linux") == ("/etc/mixar/certs",)
    assert trust_mod.machine_certs_dirs("win32", {"ProgramData": r"C:\ProgramData"}) == (
        os.path.join(r"C:\ProgramData", "Mixar", "certs"),
    )
    assert trust_mod.machine_certs_dirs("win32", {}) == ()


def test_user_certs_dir_sits_next_to_the_config_overlay(monkeypatch):
    import bpy

    monkeypatch.setattr(bpy.utils, "user_resource", lambda kind, path="", create=False: f"/cfg/{path}")
    assert trust_mod.user_certs_dir() == os.path.join("/cfg/mixar", "certs")


def test_user_certs_dir_is_empty_outside_blender(monkeypatch):
    import bpy

    monkeypatch.setattr(bpy.utils, "user_resource", lambda *a, **k: object())
    assert trust_mod.user_certs_dir() == ""


def test_tls_hint_points_at_the_drop_folder(monkeypatch):
    from mixar.modules.common.network import classify_network_error
    from mixar.modules.common.network.core import errors as errors_mod

    monkeypatch.setattr(errors_mod, "_certs_dir_label", lambda: "/cfg/mixar/certs")
    failure = classify_network_error(
        ssl.SSLCertVerificationError("certificate verify failed"), url="https://api.mixar.app/x", environ={}
    )
    assert "/cfg/mixar/certs" in failure.hint
    assert "MIXAR_EXTRA_CA_CERTS" in failure.hint
    assert "MIXAR_CA_BUNDLE" in failure.hint
