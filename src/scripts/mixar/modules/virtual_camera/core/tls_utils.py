# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Self-signed TLS certificate for the virtual-camera server.

iOS gates DeviceOrientation behind a secure context, so the phone must reach
us over HTTPS. A per-machine self-signed cert is generated once and cached;
the phone accepts it a single time in Safari. Generation prefers the
`cryptography` package and falls back to the system `openssl` binary; when
neither is available the server runs plain HTTP and the app degrades to
joystick-only control (sensors unavailable without TLS).
"""

from __future__ import annotations

import datetime
import os
import subprocess

CERT_BASENAME = "mixar_virtual_camera"
CERT_DAYS = 3650


def _cache_dir() -> str:
    try:
        import bpy

        base = bpy.utils.user_resource("CONFIG", path="mixar", create=True)
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".mixar")
        os.makedirs(base, exist_ok=True)
    return base


def cert_paths() -> tuple[str, str]:
    base = _cache_dir()
    return (
        os.path.join(base, CERT_BASENAME + ".crt"),
        os.path.join(base, CERT_BASENAME + ".key"),
    )


def ensure_certificate(hosts: list[str]) -> tuple[str, str] | None:
    """Return (cert_path, key_path), generating if missing. None = no TLS."""
    cert_path, key_path = cert_paths()
    if os.path.isfile(cert_path) and os.path.isfile(key_path):
        return cert_path, key_path

    if _generate_with_cryptography(cert_path, key_path, hosts):
        return cert_path, key_path
    if _generate_with_openssl(cert_path, key_path, hosts):
        return cert_path, key_path
    return None


def _generate_with_cryptography(cert_path: str, key_path: str,
                                hosts: list[str]) -> bool:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        import ipaddress
    except ImportError:
        return False

    try:
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "Mixar Virtual Camera")]
        )
        sans: list[x509.GeneralName] = [x509.DNSName("localhost")]
        for host in hosts:
            try:
                sans.append(x509.IPAddress(ipaddress.ip_address(host)))
            except ValueError:
                sans.append(x509.DNSName(host))
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=CERT_DAYS))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .sign(key, hashes.SHA256())
        )
        with open(key_path, "wb") as fh:
            fh.write(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
        with open(cert_path, "wb") as fh:
            fh.write(cert.public_bytes(serialization.Encoding.PEM))
        os.chmod(key_path, 0o600)
        return True
    except Exception:
        return False


def _generate_with_openssl(cert_path: str, key_path: str,
                           hosts: list[str]) -> bool:
    san = ",".join(
        ["DNS:localhost"]
        + [f"IP:{h}" if _looks_like_ip(h) else f"DNS:{h}" for h in hosts]
    )
    cmd = [
        "openssl", "req", "-x509", "-newkey", "ec",
        "-pkeyopt", "ec_paramgen_curve:prime256v1",
        "-keyout", key_path, "-out", cert_path,
        "-days", str(CERT_DAYS), "-nodes",
        "-subj", "/CN=Mixar Virtual Camera",
        "-addext", f"subjectAltName={san}",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=30, check=False
        )
        if result.returncode == 0 and os.path.isfile(cert_path):
            os.chmod(key_path, 0o600)
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


def _looks_like_ip(host: str) -> bool:
    parts = host.split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)
