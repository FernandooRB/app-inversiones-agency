from cryptography.fernet import Fernet

from scripts.workspace_operations import main


def test_operator_cli_checks_backup_restoration_and_hides_secrets(monkeypatch, tmp_path, capsys):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SIG_CASE_STORE_KEY", key)
    database = tmp_path / "operator.db"
    args = ["--database", str(database)]
    assert main([*args, "initialize"]) == 0
    assert main([*args, "check"]) == 0
    backup = tmp_path / "backup.db"
    restored = tmp_path / "restored.db"
    assert main([*args, "backup", "--destination", str(backup)]) == 0
    assert main([*args, "restore", "--source", str(backup), "--destination", str(restored)]) == 0
    assert main([*args, "initialize"]) == 2
    output = capsys.readouterr().out
    assert key not in output and str(tmp_path) not in output
    monkeypatch.delenv("SIG_CASE_STORE_KEY")
    assert main([*args, "check"]) == 2
