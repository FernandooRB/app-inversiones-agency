"""One-instance worker for administrator-approved local feeds; no external messages."""

import os
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from case_workspace import CaseStore, Principal
from operations_jobs import scheduler_tick


def main():
    location = Path(os.environ.get("SIG_SECRETS_FILE", ".streamlit/secrets.toml"))
    while True:
        # Reload policy each tick so revocation does not wait for a process restart.
        try:
            config = tomllib.loads(location.read_text(encoding="utf-8"))
            operations = config.get("operations", {})
            if operations.get("enabled") is True and config.get("workspace", {}).get("enabled") is True:
                workspace = config["workspace"]
                store = CaseStore(Path(workspace["database_path"]), workspace["encryption_key"].encode())
                principals = [
                    Principal(item["issuer"], item["subject"], item["role"])
                    for item in config.get("access", {}).get("identities", [])
                ]
                scheduler_tick(store, principals, operations.get("sources", {}))
                if operations.get("backup_enabled") is True:
                    from operational_backup import create_backup_bundle

                    admins = [principal for principal in principals if principal.role == "ADMIN"]
                    folder = store.path.parent / "backups"
                    folder.mkdir(exist_ok=True)
                    destination = folder / f"workspace_{datetime.now(UTC).date()}.sigbackup"
                    if admins and not destination.exists():
                        create_backup_bundle(
                            store,
                            admins[0],
                            destination,
                            technical_path=config.get("technical_watchlist", {}).get("database_path"),
                        )
        except (OSError, ValueError, KeyError):
            # No private path, credentials, documents or provider exception text in logs.
            print("operations_worker status=CONFIGURATION_REQUIRED", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
