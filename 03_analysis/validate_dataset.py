"""Check dataset identifiers, eligibility, scoring and reference hashes."""

import collections
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "02_data"
REFERENCE = "final_v12"
REFERENCE_DIR = DATA_DIR / "reference"


def read(p):
    return json.loads(p.read_text())


def main():
    d = json.loads(gzip.decompress((DATA_DIR / "dataset.json.gz").read_bytes()))
    f = d["fields"]
    m = d["row_mapping"]
    ss = d["sessions"]
    t = d["reference_rows"]
    assert len(m) == 6081 and len({x["source_id"] for x in m}) == 6081
    assert len(f) == len({x["field_id"] for x in f})
    assert (
        len(ss) == 384
        and len({x["session_id"] for x in ss}) == 384
        and all(x["time_s"] > 0 for x in ss)
    )
    assert len(t) == 3177 and len({x["target_id"] for x in t}) == 3177
    sm = {x["session_id"]: x for x in ss}
    tm = {x["target_id"]: x for x in t}
    mm = {x["source_id"]: x for x in m}
    seen = set()
    for x in m:
        assert len(x["target_ids"]) <= 1
        if x["target_ids"]:
            tid = x["target_ids"][0]
            key = (tid, x["model"])
            assert tid in tm and key not in seen
            seen.add(key)
        else:
            assert x["method"] in [
                "excluded_pooled_baseline",
                "excluded_nonrandomized_cohort",
            ]
    for x in f:
        assert x["session_id"] in sm and x["target_id"] in tm
        assert (
            x["study_id"]
            == sm[x["session_id"]]["study_id"]
            == tm[x["target_id"]]["study_id"]
        )
        assert x["model"] == sm[x["session_id"]]["model"]
        assert (
            x["reviewer"] == sm[x["session_id"]]["reviewer"]
            and x["uncertainty_visibility"]
            == sm[x["session_id"]]["uncertainty_visibility"]
        )
        if x["source_id"]:
            assert mm[x["source_id"]]["target_ids"] == [x["target_id"]]
        if not x["active_field"]:
            assert (
                not x["primary_eligible"]
                and x["original_error"] is None
                and (x["reviewed_error"] is None)
            )
        if x["eligibility_class"] in ("excluded_graph_only", "excluded_prompt_scope"):
            assert not x["primary_eligible"] and (not x["augmented_eligible"])
        if x["eligibility_class"] == "supplement_augmented_only":
            assert not x["primary_eligible"]
        if not x["original_row_present"]:
            assert not x["calibration_eligible"] and x["missed_uncertainty"] is None
        for k in ["original", "reviewed"]:
            assert x[k + "_error_type"] in [None, "E1", "E2"]
            if x[k + "_error"] == 0:
                assert x[k + "_error_type"] is None
        if x["calibration_eligible"]:
            assert x["missed_uncertainty"] == bool(
                x["original_error"] and (not x["original_uncertainty_flagged"])
            )
        assert "time_s" not in x
    paired = collections.defaultdict(list)
    for x in f:
        paired[x["target_id"], x["field"]].append(x)
    for rows in paired.values():
        assert len(rows) == 2 and {r["model"] for r in rows} == {"gpt", "claude"}
        assert (
            rows[0]["active_field"] == rows[1]["active_field"]
            and rows[0]["primary_eligible"] == rows[1]["primary_eligible"]
        )
    ci = [
        x
        for x in f
        if x["study_id"] == "moreira_lucas_2016"
        and x["outcome"] == "serum_25ohd"
        and (x["week"] == 24)
        and (x["field"] in ["ci_low", "ci_high"])
        and x["reference_is_null"]
    ]
    assert len(ci) == 4
    assert all(x["original_error_type"] == "E2" for x in ci if x["model"] == "claude")
    assert all(not x["original_row_present"] for x in ci if x["model"] == "gpt")
    n = [
        x
        for x in f
        if x["study_id"] == "trummer_2019"
        and x["outcome"] == "hba1c"
        and (x["outcome_variant"] == "paired_12_week_cohort")
        and (x["field"] == "n")
    ]
    assert len(n) == 8 and all(
        x["reference_is_null"] and (not x["primary_eligible"]) for x in n
    )
    for x in f:
        if x["source_id"] and x["domain"] in ["numeric", "metadata"]:
            original = mm[x["source_id"]]["original_record_json"]
            key = "numeric_u_type" if x["domain"] == "numeric" else "metadata_u_type"
            assert x["original_uncertainty_type"] == original.get(key)
    decisions = read(DATA_DIR / "rules/rationale_decisions.json")
    assert len(decisions) == 1152 and len(d["rationales"]) == 1152
    for row in d["rationales"]:
        assert row["semantic_status"] == "reviewed"
        assert row["semantic_decision_id"] in decisions
        for k in ["support", "step1_support", "step2_support"]:
            assert row["original_" + k] == row["reviewed_" + k]
        for version in ["original", "reviewed"]:
            assert row[version + "_rationale_error"] in [0, 1]
            assert row[version + "_item_composite_error"] == (
                int(
                    bool(
                        row[version + "_judgment_pair_error"]
                        or row[version + "_rationale_error"]
                    )
                )
                if row.get("reference_judgments_complete", True)
                else None
            )
        if row["eligibility_class"] == "supplement_augmented_only":
            assert not row["primary_eligible"]
    for x in f:
        if not x.get("reference_scorable", True):
            assert not x["primary_eligible"] and (not x["augmented_eligible"])
            assert x["original_error"] is None and x["reviewed_error"] is None
    design = read(DATA_DIR / "rules/design_check.json")
    assert all(r["full_rank"] and (not r["outcomes_used"]) for r in design.values())
    assert (ROOT / "03_analysis/ANALYSIS_PLAN.md").exists()
    result = {
        "status": "passed",
        "reference_version": REFERENCE,
        "source_rows": len(m),
        "sessions": len(ss),
        "reference_rows": len(t),
        "field_model_records": len(f),
        "rationales": len(d["rationales"]),
    }
    print("Dataset checks passed.")
    return result


if __name__ == "__main__":
    main()
