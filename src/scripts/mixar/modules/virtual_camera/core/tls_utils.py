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

The pair is generated in a private (0700) temp folder beside the cache —
the key is created 0600 and never exists world-readable — then moved into
place key first. A cached pair is reused only while it loads and its SAN
still covers the address in the QR code; otherwise it is regenerated.
"""

from __future__ import annotations

import datetime
import ipaddress
import os
import shutil
import ssl
import subprocess
import tempfile

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
    """Return (cert_path, key_path), generating if needed. None = no TLS.

    A cached pair that cannot be loaded (a torn write, a mismatched key) or
    whose SAN misses ``hosts[0]`` (the LAN address changed) is replaced.
    """
    cert_path, key_path = cert_paths()
    if os.path.isfile(cert_path) and os.path.isfile(key_path):
        if _pair_loads(cert_path, key_path) and _san_covers(cert_path, hosts):
            return cert_path, key_path
    return regenerate(hosts)


def regenerate(hosts: list[str]) -> tuple[str, str] | None:
    """Discard the cached pair and generate a fresh one. None = no TLS."""
    cert_path, key_path = cert_paths()
    # The old pair stays until a new one is ready (os.replace overwrites):
    # if generation fails, a pair that only missed the current IP is still
    # better than no TLS.
    try:
        work = tempfile.mkdtemp(prefix=".vcam-tls-", dir=os.path.dirname(key_path))
    except OSError:
        return None
    try:
        tmp_cert = os.path.join(work, os.path.basename(cert_path))
        tmp_key = os.path.join(work, os.path.basename(key_path))
        if not (_generate_with_cryptography(tmp_cert, tmp_key, hosts)
                or _generate_with_openssl(tmp_cert, tmp_key, hosts)):
            return None
        # Key first: a crash between the two leaves no cert, so the next
        # start regenerates instead of pairing a new cert with an old key.
        os.replace(tmp_key, key_path)
        os.replace(tmp_cert, cert_path)
        return cert_path, key_path
    except OSError:
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _pair_loads(cert_path: str, key_path: str) -> bool:
    """Can a server context load this cert + key pair?"""
    try:
        from mixar.modules.common.network import server_ssl_context

        server_ssl_context().load_cert_chain(cert_path, key_path)
        return True
    except (ssl.SSLError, OSError, ValueError):
        return False
    except Exception:
        return False


def _san_covers(cert_path: str, hosts: list[str]) -> bool:
    """Does the cert's SAN name ``hosts[0]``? True when it cannot be checked
    (no ``cryptography``): a readable pair beats a needless regeneration."""
    if not hosts:
        return True
    try:
        from cryptography import x509
    except ImportError:
        return True
    try:
        with open(cert_path, "rb") as fh:
            cert = x509.load_pem_x509_certificate(fh.read())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except Exception:
        return False
    host = hosts[0]
    try:
        return ipaddress.ip_address(host) in san.get_values_for_type(x509.IPAddress)
    except ValueError:
        return host in san.get_values_for_type(x509.DNSName)


def _write_private(path: str, data: bytes) -> None:
    """Create ``path`` 0600 from the first byte (never umask-wide, then chmod)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def _generate_with_cryptography(cert_path: str, key_path: str,
                                hosts: list[str]) -> bool:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
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
        _write_private(
            key_path,
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )
        with open(cert_path, "wb") as fh:
            fh.write(cert.public_bytes(serialization.Encoding.PEM))
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
        # openssl creates the key itself; the private 0700 work folder is
        # what keeps it unreadable until this chmod.
        if result.returncode == 0 and os.path.isfile(cert_path):
            os.chmod(key_path, 0o600)
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


def _looks_like_ip(host: str) -> bool:
    parts = host.split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)
