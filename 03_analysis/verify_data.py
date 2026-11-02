"""Verify source inputs and rebuild the analytical data."""

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from validate_dataset import main as validate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "02_data"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload(path):
    content = path.read_bytes()
    return gzip.decompress(content) if path.suffix == ".gz" else content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((DATA / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        assert sha(DATA / name) == digest, name
    assert (
        sha(ROOT / "03_analysis/ANALYSIS_PLAN.md") == manifest["analysis_plan_sha256"]
    )
    expected = manifest.get("generated_files")
    if expected is None:
        names = manifest["analytical_files"] + [
            "rules/prompt_scope.json",
            "rules/prompt_scope.csv",
            "rules/design_check.json",
        ]
        expected = {
            name: hashlib.sha256(payload(DATA / name)).hexdigest() for name in names
        }

    if args.rebuild:
        with tempfile.TemporaryDirectory(prefix="slr-rebuild-") as tmp:
            env = dict(os.environ, SLR_DATA_OUTPUT=tmp)
            for script in [
                "build_prompt_scope.py",
                "build_dataset.py",
                "check_design.py",
            ]:
                subprocess.run(
                    [sys.executable, str(ROOT / "03_analysis" / script)],
                    env=env,
                    check=True,
                )
            for name, digest in expected.items():
                assert (
                    hashlib.sha256(payload(Path(tmp) / name)).hexdigest() == digest
                ), name
            if "generated_files" in manifest:
                assert not set(expected).intersection(manifest["files"])
                for name in expected:
                    (DATA / name).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(Path(tmp) / name, DATA / name)

    for name, digest in expected.items():
        if not (DATA / name).exists():
            raise SystemExit(
                "Analytical data are absent. Run verify_data.py --rebuild."
            )
        assert hashlib.sha256(payload(DATA / name)).hexdigest() == digest, name
    validate()
    print(
        "Input verification passed."
        + (" Data rebuild matched." if args.rebuild else "")
    )


if __name__ == "__main__":
    main()
