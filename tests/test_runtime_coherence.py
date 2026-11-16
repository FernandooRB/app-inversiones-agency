"""Exercise an actual long-lived interpreter, including same-size source replacement."""

import os
import subprocess
import sys
from pathlib import Path


def test_live_source_update_is_detected_before_mixing_loaded_modules(tmp_path):
    root = Path(__file__).resolve().parents[1]
    module = tmp_path / "synthetic_runtime_module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import os, sys
from pathlib import Path
sys.path.insert(0, {str(root)!r})
from runtime_coherence import install_local_tracking, loaded_module_changes
root=Path({str(tmp_path)!r})
sys.path.insert(0,str(root))
install_local_tracking(root)
import synthetic_runtime_module
assert synthetic_runtime_module.VALUE == 1
assert loaded_module_changes(root) == []
path=root/'synthetic_runtime_module.py'
stamp=path.stat()
path.write_text('VALUE = 2\\n',encoding='utf-8')
os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
assert loaded_module_changes(root) == ['synthetic_runtime_module']
assert synthetic_runtime_module.VALUE == 1
""",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import sys
from pathlib import Path
sys.path.insert(0,{str(root)!r})
from runtime_coherence import install_local_tracking, loaded_module_changes
root=Path({str(tmp_path)!r});sys.path.insert(0,str(root))
install_local_tracking(root)
import synthetic_runtime_module
assert synthetic_runtime_module.VALUE == 2
assert loaded_module_changes(root) == []
""",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_previously_untracked_local_import_requires_restart(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "synthetic_legacy_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import sys
from pathlib import Path
sys.path[:0]=[{str(tmp_path)!r},{str(root)!r}]
import synthetic_legacy_module
from runtime_coherence import install_local_tracking, loaded_module_changes
root=Path({str(tmp_path)!r})
install_local_tracking(root)
assert loaded_module_changes(root) == ['synthetic_legacy_module']
""",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_script_entrypoint_is_not_an_untracked_import(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = tmp_path / "app.py"
    script.write_text(
        f"""
import sys
from pathlib import Path
sys.path.insert(0,{str(root)!r})
from runtime_coherence import install_local_tracking, loaded_module_changes
root=Path(__file__).resolve().parent
install_local_tracking(root)
assert loaded_module_changes(root) == [], loaded_module_changes(root)
""",
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_login_does_not_load_advanced_financial_engines():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import sys
from streamlit.testing.v1 import AppTest
app=AppTest.from_file({str(root / "app_inversiones.py")!r},default_timeout=40).run()
assert not app.exception
assert 'backtesting' not in sys.modules
assert 'multi_cut' not in sys.modules
assert 'reporting' not in sys.modules
""",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=root,
    )
    assert result.returncode == 0, result.stderr[-3000:]
