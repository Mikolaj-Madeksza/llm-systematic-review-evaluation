"""Rebuild the analytical data and run the complete analysis."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ANALYSIS = ROOT / "03_analysis"


def main():
    if not __debug__:
        raise SystemExit("Run without -O; input and result checks must remain enabled.")
    (ANALYSIS / "results/current").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    library = ROOT / "renv/library"
    if library.is_dir():
        env.setdefault("LLM_SLR_R_LIBRARY", str(library))
    commands = [
        [sys.executable, "verify_data.py", "--rebuild"],
        [sys.executable, "randomization.py"],
        [sys.executable, "validate_scoring_policy.py"],
        [sys.executable, "run_analysis.py"],
        ["Rscript", "run_timing.R"],
        [sys.executable, "prepare_publication_results.py"],
        ["Rscript", "adjusted_net_change.R"],
        ["Rscript", "make_figures.R"],
        [sys.executable, "validate_results.py"],
    ]
    for interpreter, script, *args in commands:
        print(f"Running {script}", flush=True)
        subprocess.run(
            [interpreter, str(ANALYSIS / script), *args], cwd=ROOT, env=env, check=True
        )
    print("Analysis complete. Results: 03_analysis/results/current/")


if __name__ == "__main__":
    main()
