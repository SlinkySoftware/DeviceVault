"""The monitoring relay's TLS certificate: self-signed, generated on first start, kept in the state volume.

Like the SSH host key and ``identity.json`` this is self-generated state, not
configuration. Zabbix cannot pin a certificate (its HTTP agent items verify
against a CA or not at all), so the fingerprint is reported in heartbeats and
shown on the Workers page for anyone who wants to check it by hand. Deleting
the files gives the receiver a new certificate on its next start.
"""

import hashlib
import os
import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from devicevault_protocol.identity import state_dir

CERTIFICATE_FILENAME = 'relay_tls.crt'
KEY_FILENAME = 'relay_tls.key'
VALIDITY = timedelta(days=3650)


@dataclass(frozen=True)
class Certificate:
    certificate_path: Path
    key_path: Path
    fingerprint: str

    def ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.certificate_path, self.key_path)
        return context


def fingerprint(der: bytes) -> str:
    """SHA-256 of the certificate, as ``openssl x509 -fingerprint -sha256`` and browsers show it."""
    digest = hashlib.sha256(der).hexdigest().upper()
    return ':'.join(digest[i : i + 2] for i in range(0, len(digest), 2))


def load_or_create(directory: Path | None = None, *, hostname: str | None = None) -> Certificate:
    directory = directory or state_dir()
    certificate_path, key_path = directory / CERTIFICATE_FILENAME, directory / KEY_FILENAME
    if certificate_path.exists() and key_path.exists():
        certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    else:
        certificate = _create(certificate_path, key_path, hostname or socket.gethostname())
    der = certificate.public_bytes(serialization.Encoding.DER)
    return Certificate(certificate_path=certificate_path, key_path=key_path, fingerprint=fingerprint(der))


def _create(certificate_path: Path, key_path: Path, hostname: str) -> x509.Certificate:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname[:64] or 'devicevault-receiver')])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + VALIDITY)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname or 'devicevault-receiver')]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    _write(
        key_path,
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        0o600,
    )
    _write(certificate_path, certificate.public_bytes(serialization.Encoding.PEM), 0o644)
    return certificate


def _write(path: Path, content: bytes, mode: int) -> None:
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(content)
    os.replace(tmp, path)
