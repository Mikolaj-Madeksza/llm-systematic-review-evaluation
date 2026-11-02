"""Check predictor matrix rank and assignment balance."""

import collections
import csv
import json
import math
import os
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parents[1] / "02_data"
OUTPUT = Path(os.environ.get("SLR_DATA_OUTPUT", str(DATA_DIR)))
(OUTPUT / "rules").mkdir(parents=True, exist_ok=True)
session_file = OUTPUT / "sessions.csv"
if not session_file.exists():
    session_file = DATA_DIR / "sessions.csv"
rows = list(csv.DictReader(session_file.open(encoding="utf-8-sig")))
result = {}
for task in ["data", "rob"]:
    rr = [r for r in rows if r["task"] == task]
    ids = sorted({r["study_id"] for r in rr})
    terms = (
        ["intercept"]
        + ["report:" + s for s in ids[1:]]
        + ["gpt", "reviewer_MK", "visible", "review_order_centered"]
    )
    ordermean = sum(float(r["review_order"]) for r in rr) / len(rr)
    burdenmean = sum(math.log(float(r["original_row_burden"])) for r in rr) / len(rr)
    X = []
    for r in rr:
        row = (
            [1]
            + [int(r["study_id"] == sid) for sid in ids[1:]]
            + [
                int(r["model"] == "gpt"),
                int(r["reviewer"] == "MK"),
                int(r["uncertainty_visibility"] == "visible"),
                float(r["review_order"]) - ordermean,
            ]
        )
        if task == "data":
            row.append(math.log(float(r["original_row_burden"])) - burdenmean)
        X.append(row)
    if task == "data":
        terms.append("log_original_rows_centered")
    a = np.array(X)
    rank = int(np.linalg.matrix_rank(a))
    assert rank == a.shape[1]
    balance = collections.Counter(
        (r["model"], r["reviewer"], r["uncertainty_visibility"]) for r in rr
    )
    assert set(balance.values()) == {24}
    result[task] = {
        "sessions": len(rr),
        "design_columns": a.shape[1],
        "rank": rank,
        "full_rank": True,
        "terms": terms,
        "cell_counts": {":".join(k): v for k, v in sorted(balance.items())},
        "outcomes_used": False,
        "burden_rule": "Adjusted for original row burden"
        if task == "data"
        else "Row burden omitted because it is absorbed by report effects",
    }
(OUTPUT / "rules/design_check.json").write_text(json.dumps(result, indent=2) + "\n")
print("Predictor matrices full rank; balanced assignment; no outcomes used.")
