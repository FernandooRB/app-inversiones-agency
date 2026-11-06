"""Offline operator tool: consistent encrypted SQLite backup, verified before success."""

import argparse
import json
import os
import tomllib
from pathlib import Path

from case_workspace import CaseStore, Principal


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--admin-subject", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--bundle", action="store_true", help="Incluye seguimiento en un paquete cifrado.")
    parser.add_argument("--restore-to", type=Path, help="Directorio nuevo de restauración de un paquete.")
    arguments = parser.parse_args()
    config = tomllib.loads(arguments.config.read_text(encoding="utf-8"))
    identities = [
        item
        for item in config["access"]["identities"]
        if item["subject"] == arguments.admin_subject and item["role"] == "ADMIN"
    ]
    if len(identities) != 1:
        parser.error("Selecciona una identidad administrativa configurada sin ambigüedad.")
    workspace = config["workspace"]
    store = CaseStore(Path(workspace["database_path"]), workspace["encryption_key"].encode())
    identity = identities[0]
    principal = Principal(identity["issuer"], identity["subject"], identity["role"])
    if arguments.bundle:
        from operational_backup import create_backup_bundle, verify_backup_bundle

        if arguments.check_only or arguments.restore_to is not None:
            result = verify_backup_bundle(
                store, principal, arguments.destination, restore_to=arguments.restore_to
            )
        else:
            result = create_backup_bundle(
                store,
                principal,
                arguments.destination,
                technical_path=config.get("technical_watchlist", {}).get("database_path"),
            )
    else:
        result = (store.restore_check if arguments.check_only else store.backup)(
            principal, arguments.destination
        )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
