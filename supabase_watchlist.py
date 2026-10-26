"""Server-side Supabase storage for per-OIDC-identity technical watchlists."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from watchlist_store import WatchlistError, WatchlistStore, identity_key, normalize_watchlist


class SupabaseWatchlistStore:
    """Use the Data API only from the authorized Streamlit server process."""

    def __init__(
        self,
        url: str,
        secret_key: str,
        *,
        legacy_path: Path | None = None,
        client: httpx.Client | None = None,
    ):
        try:
            parsed = urlsplit(url) if isinstance(url, str) else None
            port = parsed.port if parsed is not None else None
        except ValueError:
            parsed, port = None, None
        if (
            parsed is None
            or parsed.scheme != "https"
            or not re.fullmatch(r"[a-z0-9-]+\.supabase\.co", parsed.hostname or "")
            or port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise WatchlistError("Configura la URL HTTPS de tu proyecto de Supabase.")
        if not isinstance(secret_key, str) or not secret_key.startswith("sb_secret_"):
            raise WatchlistError("Configura una clave secreta sb_secret_ de Supabase en Secrets.")
        if legacy_path is not None and not Path(legacy_path).is_absolute():
            raise WatchlistError("La ruta de la lista local anterior debe ser absoluta.")
        self.endpoint = f"{url.rstrip('/')}/rest/v1/technical_watchlists"
        self.secret_key = secret_key
        self.legacy_path = Path(legacy_path) if legacy_path is not None else None
        self.client = client

    def _request(self, method: str, **kwargs) -> httpx.Response:
        headers = {"apikey": self.secret_key, "Accept": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        if self.client is not None:
            return self.client.request(
                method, self.endpoint, headers=headers, timeout=10.0, follow_redirects=False, **kwargs
            )
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            return client.request(method, self.endpoint, headers=headers, **kwargs)

    def load(self, issuer: str, subject: str) -> list[str]:
        owner = identity_key(issuer, subject)
        try:
            response = self._request(
                "GET", params={"owner": f"eq.{owner}", "select": "symbols", "limit": "1"}
            )
            if response.status_code != 200:
                raise WatchlistError("No se pudo leer Seguimiento en Supabase; revisa la tabla y Secrets.")
            rows = response.json()
            if not isinstance(rows, list) or len(rows) > 1:
                raise WatchlistError("Supabase devolvió una lista con formato inválido.")
            if not rows:
                return self._import_local(issuer, subject)
            symbols = rows[0].get("symbols") if isinstance(rows[0], dict) else None
            if not isinstance(symbols, list) or not all(isinstance(value, str) for value in symbols):
                raise WatchlistError("La lista guardada en Supabase no tiene un formato válido.")
            return normalize_watchlist(symbols)
        except (httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, WatchlistError):
                raise
            raise WatchlistError("No se pudo leer Seguimiento en Supabase; revisa la conexión.") from None

    def _import_local(self, issuer: str, subject: str) -> list[str]:
        # A deployment may have already removed its local SQLite file. Import only
        # an existing row; a deliberately empty remote row never reimports old data.
        if self.legacy_path is None or not self.legacy_path.is_file():
            return []
        try:
            symbols = WatchlistStore(self.legacy_path).load(issuer, subject)
        except WatchlistError:
            return []
        if symbols:
            self.save(issuer, subject, symbols)
        return symbols

    def save(self, issuer: str, subject: str, symbols: Iterable[str]) -> list[str]:
        owner = identity_key(issuer, subject)
        normalized = normalize_watchlist(symbols)
        try:
            response = self._request(
                "POST",
                params={"on_conflict": "owner"},
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                json=[{
                    "owner": owner,
                    "symbols": normalized,
                    "updated_at": datetime.now(UTC).isoformat(),
                }],
            )
            if response.status_code not in (200, 201, 204):
                raise WatchlistError("No se pudo guardar Seguimiento en Supabase; revisa la tabla y Secrets.")
        except httpx.HTTPError:
            raise WatchlistError("No se pudo guardar Seguimiento en Supabase; revisa la conexión.") from None
        return normalized
