"""Offline authenticated copies of existing portable ZIPs; no secrets in outputs."""

import base64
import os
from contextlib import contextmanager
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from operations_recovery import inspect_package
from operations_review import MAX_PACKAGE_BYTES
from portfolio_core import PortfolioError

MAX_ENCRYPTED_BYTES = 21_000_000
ERROR = "No se pudo completar la copia local: revisa clave, integridad, contexto y destino nuevo."


def _path(value):
    path = Path(value).absolute()
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (path, *path.parents)):
        raise PortfolioError(ERROR)
    return path


def _read(value, maximum):
    path = _path(value)
    if not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise PortfolioError(ERROR)
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if not 0 < len(raw) <= maximum:
        raise PortfolioError(ERROR)
    return raw


@contextmanager
def _locked(value):
    """Coordinate creates/deletes by this local tool, including other processes."""
    path = _path(value)
    lock = path.with_name(path.name + ".siglock")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(lock, flags, 0o600)
    try:
        yield path
    finally:
        os.close(descriptor)
        lock.unlink()


def _write(value, raw):
    with _locked(value) as path:
        # O_EXCL rejects existing files/hardlinks; never replace a live review or key.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise


def _canonical64(raw):
    decoded = base64.b64decode(raw, altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(decoded) != raw:
        raise ValueError
    return decoded


def _key_material(key_file):
    raw = _read(key_file, 44)
    if len(raw) != 44 or len(_canonical64(raw)) != 32:
        raise ValueError
    return raw


def _cipher(key_file):
    return Fernet(_key_material(key_file))


def generate_key(destination):
    try:
        _write(destination, Fernet.generate_key())
        return {"status": "COMPLETED", "operation": "keygen"}
    except (OSError, ValueError, TypeError):
        raise PortfolioError(ERROR) from None


def _open(source, key_file, scope):
    token = _read(source, MAX_ENCRYPTED_BYTES)
    _canonical64(token)
    raw = _cipher(key_file).decrypt(token)
    return raw, {**inspect_package(raw, **scope), "encrypted_sha256": sha256(token).hexdigest()}


def save_copy(source, destination, key_file, **scope):
    try:
        raw = _read(source, MAX_PACKAGE_BYTES)
        info = inspect_package(raw, **scope)
        token = _cipher(key_file).encrypt(raw)
        if len(token) > MAX_ENCRYPTED_BYTES:
            raise ValueError
        _write(destination, token)
        return {**info, "encrypted_sha256": sha256(token).hexdigest()}
    except (OSError, ValueError, TypeError, InvalidToken):
        raise PortfolioError(ERROR) from None


def verify_copy(source, key_file, **scope):
    try:
        return _open(source, key_file, scope)[1]
    except (OSError, ValueError, TypeError, InvalidToken):
        raise PortfolioError(ERROR) from None


def restore_copy(source, destination, key_file, **scope):
    try:
        raw, info = _open(source, key_file, scope)
        _write(destination, raw)
        return info
    except (OSError, ValueError, TypeError, InvalidToken):
        raise PortfolioError(ERROR) from None


def rotate_copy(source, destination, key_file, new_key_file, **scope):
    try:
        raw, info = _open(source, key_file, scope)
        new_key = _key_material(new_key_file)
        if compare_digest(_key_material(key_file), new_key):
            raise ValueError
        token = Fernet(new_key).encrypt(raw)
        _write(destination, token)
        return {**info, "encrypted_sha256": sha256(token).hexdigest()}
    except (OSError, ValueError, TypeError, InvalidToken):
        raise PortfolioError(ERROR) from None


def delete_copy(source, key_file, *, confirmation, **scope):
    try:
        with _locked(source) as path:
            info = verify_copy(path, key_file, **scope)
            if not isinstance(confirmation, str) or not compare_digest(
                confirmation, info["encrypted_sha256"]
            ):
                raise ValueError
            path.unlink()
        return {"status": "COMPLETED", "operation": "delete"}
    except (OSError, ValueError, TypeError):
        raise PortfolioError(ERROR) from None
