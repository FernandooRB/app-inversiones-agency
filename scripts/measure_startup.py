"""Fresh-process AppTest timings; public source only, no account/provider calls.

Usage: python scripts/measure_startup.py BASELINE_ENTRY CANDIDATE_ENTRY OUTPUT_JSON
OS caches are not flushed; measurements are a lab comparison, not field CWV.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

WORKER = r"""
import json,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[2])
start=time.perf_counter()
from streamlit.testing.v1 import AppTest
app=AppTest.from_file(sys.argv[1],default_timeout=60).run()
initial=time.perf_counter()-start
assert not app.exception
start=time.perf_counter();app.run();interaction=time.perf_counter()-start
print(json.dumps({"initial_ms":round(initial*1000,2),"rerun_ms":round(interaction*1000,2),
"advanced_engine_loaded":"backtesting" in sys.modules,"exceptions":len(app.exception)}))
"""


def main():
    baseline, candidate, output = map(Path, sys.argv[1:])
    root = Path(__file__).resolve().parents[1]
    samples = []
    # Alternate ordering to reduce ordering bias. Each sample is a fresh interpreter.
    for label, entry in (
        ("baseline", baseline),
        ("candidate", candidate),
        ("candidate", candidate),
        ("baseline", baseline),
    ):
        result = subprocess.run(
            [sys.executable, "-c", WORKER, str(entry.resolve()), str(root)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
            env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
        )
        if result.returncode:
            raise RuntimeError("Startup measurement failed; inspect the controlled fixture.")
        sample = json.loads(result.stdout.splitlines()[-1])
        samples.append({"label": label, **sample})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "scope": "Local login gate; new processes, uncontrolled OS caches; not field CWV",
                "real_documents": False,
                "samples": samples,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(samples))


if __name__ == "__main__":
    main()
