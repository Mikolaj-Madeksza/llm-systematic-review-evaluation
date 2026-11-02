"""Check unit equivalence, omissions and source-specific scoring rules."""

import collections
import gzip
import json
from pathlib import Path

from value_equivalence import comparison, record_comparison, unit_equal

ROOT = Path(__file__).resolve().parents[1]
dataset = json.loads(gzip.decompress((ROOT / "02_data/dataset.json.gz").read_bytes()))
fields = dataset["fields"]
primary_fields = [r for r in fields if r["kind"] == "data" and r["primary_eligible"]]
for a, b in [
    ("nmol/L", "nmol/l"),
    ("mmol L−1", "mmol/L"),
    ("μU/mL", "uU/ml"),
    ("mL/min/m²", "ml/min/m2"),
]:
    assert unit_equal(a, b), (a, b)
for a, b in [("nmol/L", "mmol/L"), ("mg/dL", "mg/L"), ("mU/L", "MU/L"), ("L-1", "L1")]:
    assert not unit_equal(a, b), (a, b)
assert comparison("unit", "nmol/L", "mg/dL", accepted_values=["nmol/l", "mg/dL"])[0]
unit_errors = [
    r
    for r in fields
    if r["field"] == "unit"
    and r["original_row_present"]
    and (r["original_error"] == 1 or r["reviewed_error"] == 1)
]
assert all(
    json.loads(r["original_value_json"]) is None
    and json.loads(r["reviewed_value_json"]) is None
    for r in unit_errors
)
null_omissions = [
    r
    for r in primary_fields
    if not r["original_row_present"] and r["reference_is_null"]
]
assert all(
    r["original_error"] == 0 and r["reviewed_error"] == 0 for r in null_omissions
)
ni = [
    r
    for r in fields
    if r["study_id"] == "niroomand_2019"
    and r["field"] in ["n", "n_analyzed", "n_not_analyzed", "pct_not_analyzed"]
    and (r["adjudication_category"] == "C")
]
assert len(ni) == 60 and all(
    r["original_error"] is None
    and r["reviewed_error"] is None
    and (not r["primary_eligible"])
    for r in ni
)
most = [
    r
    for r in fields
    if r["study_id"] == "mostafai_2018" and (not r["prompt_scope_eligible"])
]
assert most and all(
    not r["primary_eligible"]
    and (not r["augmented_eligible"])
    and (r["original_error"] is None)
    and (r["reviewed_error"] is None)
    for r in most
)
refs = {r["target_id"]: r["reference_row_json"] for r in dataset["reference_rows"]}
alternatives = json.loads(
    (ROOT / "02_data/reference/row_representation_alternatives.json").read_text()
)
als = [(k, v) for k, v in alternatives.items() if k.startswith("al_mulhim_2015:data:")]
assert len(als) == 12
for tid, alt in als:
    ref = refs[tid]
    rep = alt["representations"][0]
    submitted = dict(ref, **rep["values"])
    for f in rep["values"]:
        assert record_comparison(f, submitted, ref, "al_mulhim_2015", alternatives=alt)[
            0
        ], (tid, f)
    if submitted["week"] == 12:
        submitted["week"] = 8
        assert not record_comparison(
            "week", submitted, ref, "al_mulhim_2015", alternatives=alt
        )[0]
assert (
    len(
        [
            r
            for r in dataset["reference_rows"]
            if r["target_id"].startswith("al_mulhim_2015:data:")
        ]
    )
    == 12
)
counts = {
    "eligible_fields_per_model": dict(
        collections.Counter(r["model"] for r in primary_fields)
    ),
    "original_errors": sum(r["original_error"] for r in primary_fields),
    "reviewed_errors": sum(r["reviewed_error"] for r in primary_fields),
    "corrected": sum(
        r["original_error"] == 1 and r["reviewed_error"] == 0 for r in primary_fields
    ),
    "introduced": sum(
        r["original_error"] == 0 and r["reviewed_error"] == 1 for r in primary_fields
    ),
    "presented_original_errors": sum(
        r["original_error"] for r in primary_fields if r["original_row_present"]
    ),
    "omitted_field_errors_by_model": {
        m: sum(
            r["original_error"]
            for r in primary_fields
            if not r["original_row_present"] and r["model"] == m
        )
        for m in ["gpt", "claude"]
    },
}
assert (
    counts["original_errors"] == 1022
    and counts["reviewed_errors"] == 1109
    and (counts["corrected"] == 36)
    and (counts["introduced"] == 123)
)
out = dict(status="passed", counts=counts)
(ROOT / "03_analysis/results/current/scoring_validation.json").write_text(
    json.dumps(out, indent=2) + "\n"
)
print("Scoring checks passed.")
