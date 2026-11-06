"""Fail-closed configuration and one-instance process supervision for staging."""

import os
import signal
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet


def validate_configuration(config, data_root):
    workspace, auth = config.get("workspace", {}), config.get("auth", {})
    if workspace.get("enabled") is not True:
        raise ValueError("Activa almacenamiento persistente antes de arrancar el entorno de prueba.")
    Fernet(workspace.get("encryption_key", "").encode())
    root = Path(data_root).resolve()
    paths = [Path(workspace.get("database_path", ""))]
    technical = config.get("technical_watchlist", {})
    if technical.get("backend", "sqlite") != "sqlite":
        raise ValueError(
            "Esta configuración de despliegue requiere seguimiento SQLite en el disco persistente."
        )
    paths.append(Path(technical.get("database_path", "")))
    if any(not path.is_absolute() or not path.resolve().is_relative_to(root) for path in paths):
        raise ValueError("Todos los registros deben ubicarse en el disco persistente configurado.")
    for key in ("client_id", "client_secret", "cookie_secret", "server_metadata_url", "redirect_uri"):
        value = auth.get(key, "")
        if not isinstance(value, str) or not value.strip() or "REPLACE" in value:
            raise ValueError("Faltan credenciales OIDC o el secreto de sesión.")
    redirect = urlparse(auth["redirect_uri"])
    metadata = urlparse(auth["server_metadata_url"])
    if (
        redirect.scheme != "https"
        or redirect.path != "/oauth2callback"
        or not redirect.hostname
        or metadata.scheme != "https"
        or not metadata.hostname
        or len(auth["cookie_secret"]) < 32
    ):
        raise ValueError(
            "OIDC necesita HTTPS, callback correcto y secreto de sesión de al menos 32 caracteres."
        )
    identities = config.get("access", {}).get("identities", [])
    from case_workspace import Principal

    if not identities or not any(item.get("role") == "ADMIN" for item in identities):
        raise ValueError("Configura al menos una identidad administrativa verificada.")
    for identity in identities:
        if "REPLACE" in str(identity):
            raise ValueError("Sustituye las identidades de ejemplo por identidades verificadas.")
        _ = Principal(identity["issuer"], identity["subject"], identity["role"]).actor
    root.mkdir(parents=True, exist_ok=True)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    probe = root / (".write_probe_" + str(os.getpid()))
    with probe.open("x") as handle:
        handle.write("ok")
    probe.unlink()
    return config


def supervise():
    os.umask(0o077)
    location = Path(os.environ.get("SIG_SECRETS_FILE", ".streamlit/secrets.toml"))
    secret_text = os.environ.pop("SIG_SECRETS_TOML", None)
    if secret_text is not None:
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_text(secret_text, encoding="utf-8")
        location.chmod(0o600)
    try:
        config = validate_configuration(
            tomllib.loads(location.read_text(encoding="utf-8")), os.environ.get("SIG_DATA_DIR", "/var/data")
        )
        # st.secrets reads the standard local file. Never bake it into an image.
        standard = Path(".streamlit/secrets.toml")
        if location.resolve() != standard.resolve():
            standard.parent.mkdir(parents=True, exist_ok=True)
            standard.write_bytes(location.read_bytes())
            standard.chmod(0o600)
    except (OSError, ValueError, KeyError, TypeError):
        print("startup status=CONFIGURATION_REQUIRED", file=sys.stderr)
        return 2
    port = int(os.environ.get("PORT", "8501"))
    if not 1 <= port <= 65535:
        return 2
    processes = []

    def stop(*_):
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    processes.append(
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "app_inversiones.py",
                "--server.address=0.0.0.0",
                f"--server.port={port}",
                "--server.headless=true",
            ]
        )
    )
    if config.get("operations", {}).get("enabled") is True:
        processes.append(subprocess.Popen([sys.executable, "-m", "scripts.operations_worker"]))
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
    finally:
        stop()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return next((process.returncode for process in processes if process.returncode), 0)


if __name__ == "__main__":
    raise SystemExit(supervise())
