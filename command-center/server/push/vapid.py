"""VAPID keypair management.

Loads an existing EC P-256 private key (PEM) or generates one on first use,
persisting it to ``config.PUSH_KEYS_PATH``. Exposes:
  - application_server_key():  base64url uncompressed point for the browser's
                               PushManager.subscribe({ applicationServerKey })
  - private_pem():             PEM string passed to pywebpush as vapid_private_key
"""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

import config

_priv: ec.EllipticCurvePrivateKey | None = None


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _load_or_create() -> ec.EllipticCurvePrivateKey:
    global _priv
    if _priv is not None:
        return _priv
    path = config.PUSH_KEYS_PATH
    if path.exists():
        _priv = serialization.load_pem_private_key(path.read_bytes(), password=None)
        return _priv
    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pem)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    _priv = priv
    return _priv


def private_pem() -> str:
    priv = _load_or_create()
    return priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


def private_key_b64() -> str:
    """Raw base64url-encoded EC private scalar (32 bytes) — the form
    pywebpush/py_vapid consume directly.

    Do NOT hand pywebpush a full PKCS8 PEM *string*: py_vapid mis-parses it and
    raises 'Could not deserialize key data', so every push fails locally before
    it ever reaches the push service (Apple/Mozilla/FCM). See sender.send_one.
    """
    d = _load_or_create().private_numbers().private_value
    return _b64url(d.to_bytes(32, "big"))


def application_server_key() -> str:
    """Public key as base64url-encoded uncompressed EC point (65 bytes, 0x04…)."""
    pub = _load_or_create().public_key()
    raw = pub.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return _b64url(raw)
