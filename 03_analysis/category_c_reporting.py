"""Summarize unverifiable fields and uncertainty disclosures."""

import csv
import json
from collections import Counter, defaultdict


def prediction_units(records):
    grouped = defaultdict(list)
    for r in records:
        if r["eligibility_class"] == "main_report":
            grouped[r["uncertainty_unit_id"]].append(r)
    result = []
    for uid, rows in sorted(grouped.items()):
        flags = {
            r.get("relevant_flag_review", r["uncertainty_flag_assessment"])
            for r in rows
        }
        disclosure = (
            "appropriate_topic_flag"
            if flags == {"appropriate_topic_flag"}
            else "no_emitted_row"
            if flags == {"no_emitted_row"}
            else "missed_uncertainty_flag"
            if flags == {"missed_uncertainty_flag"}
            else "incomplete_or_unrelated_disclosure"
        )
        result.append(
            dict(
                uncertainty_unit_id=uid,
                study_id=rows[0]["study_id"],
                model=rows[0]["model"],
                domain=rows[0]["uncertainty_decision_domain"],
                category_c_fields=len(rows),
                uncertainty_flag_assessment=disclosure,
                original_has_demonstrable_field_error=any(
                    r["original_demonstrable_error"] == 1 for r in rows
                ),
                reviewed_has_demonstrable_field_error=any(
                    r["reviewed_demonstrable_error"] == 1 for r in rows
                ),
                original_associated_rationale_error=any(
                    r.get("original_associated_rationale_error") == 1 for r in rows
                ),
                reviewed_associated_rationale_error=any(
                    r.get("reviewed_associated_rationale_error") == 1 for r in rows
                ),
                original_has_unverified_estimate=any(
                    r["original_plausibility"] == "plausible_unverified" for r in rows
                ),
            )
        )
    return result


def export_category_c(dataset, output):

    def csvwrite(name, rows):
        with (output / name).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["no_records"])
            w.writeheader()
            w.writerows(rows)

    records = [dict(r) for r in dataset["category_c_assessments"]]
    fields = {(r["target_id"], r["model"], r["field"]): r for r in dataset["fields"]}
    for r in records:
        r["response_class"] = r["original_plausibility"]
        r["relevant_flag_review"] = r["uncertainty_flag_assessment"]
        r["descriptive_review_reason"] = (
            "Source constraints and disclosure of the actual unresolved issue."
        )
        sid, model = (r["study_id"], r["model"])
        if sid == "salekzamani_2016" and model == "gpt":
            lo = json.loads(
                fields[r["target_id"], model, "ci_low"]["original_value_json"]
            )
            hi = json.loads(
                fields[r["target_id"], model, "ci_high"]["original_value_json"]
            )
            assert lo > hi
            r["response_class"] = "constraint_violation"
            r["descriptive_review_reason"] = (
                "Source-literal reversed interval bounds are internally inconsistent; the true value remains unverifiable."
            )
        if (
            sid == "wallace_2019"
            and model == "claude"
            and (r["field"] == "analysis_population")
            and (r["relevant_flag_review"] == "appropriate_topic_flag")
        ):
            r["relevant_flag_review"] = "flag_does_not_address_this_uncertainty"
            r["descriptive_review_reason"] = (
                "The comment discusses counts and dropouts but does not disclose the unresolved analysis population."
            )
        if (
            sid == "lemieux_2019" and model == "claude" or sid == "tuomainen_2015"
        ) and r["uncertainty_decision_domain"] == "rob_item6":
            r["relevant_flag_review"] = "flag_does_not_address_this_uncertainty"
            r["descriptive_review_reason"] = (
                "The comment does not disclose the unresolved outcome-specific analysis denominator."
            )
    units = prediction_units(records)
    csvwrite("category_C_field_assessments.csv", records)
    csvwrite("category_C_uncertainty_decision_units.csv", units)
    counts = Counter(
        (r["model"], r["domain"], r["uncertainty_flag_assessment"]) for r in units
    )
    csvwrite(
        "category_C_uncertainty_handling.csv",
        [
            dict(model=m, domain=d, disclosure=s, units=n)
            for (m, d, s), n in sorted(counts.items())
        ],
    )
    (output / "category_C_joint_constraint_violations.json").write_text(
        json.dumps(dataset["category_c_joint_constraints"], indent=2) + "\n"
    )
    (output / "category_C_reporting_note.txt").write_text(
        "Category C is excluded from binary accuracy. Constraint violations and uncertainty disclosures are summarized separately, once per original uncertainty decision. A joint violation does not identify which individual value is wrong.\n"
    )
