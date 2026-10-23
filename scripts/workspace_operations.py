"""Trusted local operator commands; output contains statuses and counts only.

The operator has the storage key and therefore full database access. This is not
an OIDC endpoint; never expose it as an HTTP service or pass its key on the command line.
"""

import argparse
import getpass
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from case_workspace import CaseStore, Principal, WorkspaceError  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--key-env", default="SIG_CASE_STORE_KEY")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("initialize")
    commands.add_parser("check")
    backup = commands.add_parser("backup")
    backup.add_argument("--destination", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--source", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    for command in ("archive", "unarchive", "purge"):
        sub = commands.add_parser(command)
        sub.add_argument("--case-id", required=True)
        if command == "purge":
            sub.add_argument("--confirm-alias", required=True)
    args = parser.parse_args(argv)
    try:
        value = os.environ.get(args.key_env, "")
        if not value:
            raise WorkspaceError("Falta clave de operador.")
        store = CaseStore(args.database, value.encode())
        principal = Principal("local-operator", getpass.getuser(), "ADMIN")
        result = {}
        if args.command == "initialize":
            store.initialize(principal)
        elif args.command == "check":
            result = store.restore_check(principal, store.path)
        elif args.command == "backup":
            result = store.backup(principal, args.destination)
        elif args.command == "restore":
            result = store.restore_new(principal, args.source, args.destination)
        elif args.command in {"archive", "unarchive"}:
            state = store.read(principal, args.case_id)
            store.update(principal, args.case_id, state["revision"], "archived", args.command == "archive")
        elif args.command == "purge":
            store.purge(principal, args.case_id, args.confirm_alias)
        print(json.dumps({"status": "COMPLETED", "operation": args.command, **result}))
        return 0
    except (WorkspaceError, OSError, ValueError, TypeError, sqlite3.Error):
        print(json.dumps({"status": "OPERATION_REJECTED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
