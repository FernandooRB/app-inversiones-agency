"""Only fictitious documents and ephemeral keys; export restored inputs, never keys."""

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gbm_movement_review import read_movement_documents  # noqa: E402
from operations_review import build_operations_review  # noqa: E402
from scripts.gbm_review_fixture import fictional_statement  # noqa: E402


def make_fixture(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    ledger = (
        b"ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,"
        b"Referencia,MomentoFlujo,Interes\n"
        b"opening,2026-01-01,2026-01-01,OPEN_CASH,,MXN,0,0,100,0,0,,UNKNOWN,0\n"
        b"flow,2026-01-05,2026-01-05,DEPOSIT,,MXN,0,0,50,0,0,,EOD,0\n"
    )
    files = {"ledger": ledger, "nav": b"Fecha,NAV\n2026-01-01,100\n2026-01-10,150\n"}
    _, raw = build_operations_review(files, cutoff="2026-01-10", base="MXN")
    (folder / "recovery_review.zip").write_bytes(raw)
    draft = read_movement_documents([fictional_statement()])
    _, raw_draft = build_operations_review({}, cutoff="2026-01-30", base="MXN", draft=draft)
    (folder / "recovery_draft.zip").write_bytes(raw_draft)
    (folder / "recovery_invalid.zip").write_bytes(b"invalid fictional ZIP")

    def cli(*args):
        result = subprocess.run(
            [sys.executable, "-m", "scripts.local_review", *map(str, args)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, "Fictional CLI operation rejected"
        assert not result.stderr, "Unexpected CLI stderr"
        return json.loads(result.stdout)

    with TemporaryDirectory(prefix="synthetic-key-", dir=folder) as temporary:
        temporary = Path(temporary)
        key = temporary / "key.sigkey"
        copy = temporary / "copy.siglocal"
        recovered = temporary / "reopened.zip"
        cli("keygen", "--destination", key)
        cli("save", "--source", folder / "recovery_review.zip", "--key-file", key, "--destination", copy)
        verified = cli("verify", "--source", copy, "--key-file", key)
        cli("restore", "--source", copy, "--key-file", key, "--destination", recovered)
        assert recovered.read_bytes() == raw
        (folder / "recovery_restored.zip").write_bytes(recovered.read_bytes())
        cli(
            "delete",
            "--source",
            copy,
            "--key-file",
            key,
            "--confirmation-sha256",
            verified["encrypted_sha256"],
        )
        assert not copy.exists()
    (folder / "recovery_local_verification.json").write_text(
        json.dumps(
            {
                "fictional_only": True,
                "new_process_restore_exact_bytes": True,
                "sha256": sha256(raw).hexdigest(),
                "ephemeral_keys_removed": True,
                "explicit_delete_only_selected_copy": True,
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    make_fixture(sys.argv[1])
