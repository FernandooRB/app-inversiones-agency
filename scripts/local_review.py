"""Offline encrypted review copies. Never pass a key itself as an argument."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import local_review_storage as storage  # noqa: E402
from operations_recovery import inspect_package  # noqa: E402
from portfolio_core import PortfolioError  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    keygen = commands.add_parser("keygen")
    keygen.add_argument("--destination", required=True, type=Path)
    for name in ("inspect", "save", "verify", "restore", "rotate", "delete"):
        sub = commands.add_parser(name)
        sub.add_argument("--source", required=True, type=Path)
        sub.add_argument("--case-id")
        sub.add_argument("--account-id")
        sub.add_argument("--allowed-account", action="append")
        if name != "inspect":
            sub.add_argument("--key-file", required=True, type=Path)
        if name in {"save", "restore", "rotate"}:
            sub.add_argument("--destination", required=True, type=Path)
        if name == "rotate":
            sub.add_argument("--new-key-file", required=True, type=Path)
        if name == "delete":
            sub.add_argument("--confirmation-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "keygen":
            result = storage.generate_key(args.destination)
        else:
            scope = dict(
                case_id=args.case_id, account_id=args.account_id, allowed_accounts=args.allowed_account
            )
            if args.command == "inspect":
                result = inspect_package(storage._read(args.source, storage.MAX_PACKAGE_BYTES), **scope)
            elif args.command in {"save", "restore"}:
                function = storage.save_copy if args.command == "save" else storage.restore_copy
                result = function(args.source, args.destination, args.key_file, **scope)
            elif args.command == "verify":
                result = storage.verify_copy(args.source, args.key_file, **scope)
            elif args.command == "rotate":
                result = storage.rotate_copy(
                    args.source, args.destination, args.key_file, args.new_key_file, **scope
                )
            else:
                result = storage.delete_copy(
                    args.source, args.key_file, confirmation=args.confirmation_sha256, **scope
                )
        print(json.dumps({"status": "COMPLETED", "operation": args.command, **result}))
        return 0
    except (PortfolioError, OSError, ValueError, TypeError):
        print(json.dumps({"status": "OPERATION_REJECTED", "operation": args.command}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
