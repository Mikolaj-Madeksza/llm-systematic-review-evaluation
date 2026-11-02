"""Classify reference fields and assess unverifiable values."""

import json
import re
from collections import defaultdict


def category(kind, field, status, sid=None):
    if not status.get("scorable", True):
        return (
            "C",
            "Source cannot establish a unique defensible value; retained without binary correctness.",
        )
    if kind == "items" and field in ("step1", "step2"):
        if field == "step2" and status.get("mechanically_calculable", False):
            return (
                "A",
                "Known counts and the predefined item-6 threshold determine the judgment.",
            )
        return (
            "B",
            "Source-reviewed ROBUST-RCT judgment under the predefined item rules.",
        )
    if status.get("adjudication_category") == "B":
        return ("B", status["reason"])
    return (
        "A",
        "Reference verifiable under the extraction rules; approved equivalent representations remain accepted.",
    )


def assess(value, field, ref, study, all_refs):
    """Classify missing values, constraint violations and unverified estimates."""
    if value is None:
        return (
            "not_estimated",
            None,
            "No numerical/category claim was made for this unverifiable field.",
        )
    count = field in ("n", "n_randomized", "n_analyzed", "n_not_analyzed")
    numeric = count or field in ("pct_not_analyzed", "sd", "se")
    if numeric and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        return ("constraint_violation", 1, "Expected a numeric value.")
    if numeric and (
        value < 0
        or (count and value != int(value))
        or (field == "pct_not_analyzed" and value > 100)
    ):
        return (
            "constraint_violation",
            1,
            "Violates the nonnegative count/dispersion or 0-100 percentage constraint.",
        )
    groups = all_refs[study]["groups"]
    overall = next((g for g in groups if g["scope"] == "overall"), {})
    if (
        count
        and overall.get("n_randomized") is not None
        and (value > overall["n_randomized"])
    ):
        return (
            "known_evidence_contradiction",
            1,
            "Count exceeds the known overall randomized sample.",
        )
    if (
        field == "n_analyzed"
        and ref.get("n_randomized") is not None
        and (value > ref["n_randomized"])
    ):
        return (
            "known_evidence_contradiction",
            1,
            "Analyzed count exceeds the known randomized count.",
        )
    if (
        field == "n_randomized"
        and ref.get("n_analyzed") is not None
        and (value < ref["n_analyzed"])
    ):
        return (
            "known_evidence_contradiction",
            1,
            "Randomized count is smaller than the known analyzed count.",
        )
    if study == "carrillo_2013" and ref.get("group_index") == 2:
        if (
            field == "n_randomized"
            and value < 14
            or (field == "n_not_analyzed" and value < 1)
            or (field == "pct_not_analyzed" and value == 0)
        ):
            return (
                "known_evidence_contradiction",
                1,
                "Thirteen placebo completers plus at least one explicitly identified placebo dropout.",
            )
    if study == "lemieux_2019" and ref.get("scope") in ("group", "overall"):
        lower = (
            93 if ref["scope"] == "overall" else 47 if ref["group_index"] == 1 else 46
        )
        randomized = ref.get("n_randomized")
        if (
            field == "n_analyzed"
            and value < lower
            or (
                randomized is not None
                and field == "n_not_analyzed"
                and (value > randomized - lower)
            )
            or (
                randomized is not None
                and field == "pct_not_analyzed"
                and (value > 100 * (randomized - lower) / randomized + 0.11)
            )
        ):
            return (
                "known_evidence_contradiction",
                1,
                "All-available-data mixed-model analysis includes baseline observations: at least 47/46 per arm (93 overall).",
            )
    if (
        field == "reported_statistic"
        and study == "foroughi_2016"
        and (value not in ("mean_sd", "mean_se"))
    ):
        return (
            "known_evidence_contradiction",
            1,
            "The reported dispersion ambiguity is SD versus SE for mean change.",
        )
    if field == "step2" and value not in (
        "Definitely Low",
        "Probably Low",
        "Probably High",
        "Definitely High",
    ):
        return ("constraint_violation", 1, "Not a permitted ROBUST-RCT item-6 rating.")
    return (
        "plausible_unverified",
        None,
        "Not disproven by the source constraints; this is not a finding of correctness.",
    )


def acknowledgement(flag, comment, field):
    if not flag:
        return "missed_uncertainty_flag"
    text = comment or ""
    pattern = (
        "\\b(?:SD|SE|CI|statistic|dispersion|interval|bounds?|sign)\\b"
        if field in ("reported_statistic", "sd", "se", "ci_low", "ci_high")
        else "\\b(?:n|Ns|denominator|denominators|sample|participants?|group sizes|attrition|dropouts?|missingness|completion|completed|retention|flow|per-arm|per-group|population|ITT|PP|per.protocol|intention.to.treat)\\b"
    )
    return (
        "appropriate_topic_flag"
        if re.search(pattern, text, re.I)
        else "flag_does_not_address_this_uncertainty"
    )


def build_c_assessments(fields, refs, mappings, reference_standard):
    by_id = {r["target_id"]: r["reference_row_json"] for r in refs}
    mapped = {(m["target_ids"][0], m["model"]): m for m in mappings if m["target_ids"]}
    item6 = {
        (m["study_id"], m["model"]): m
        for m in mappings
        if m["kind"] == "items" and m["original_record_json"]["robust_item"] == "item6"
    }
    output = []
    for r in fields:
        if r["eligibility_class"] == "excluded_prompt_scope":
            continue
        if r["adjudication_category"] != "C":
            continue
        m = mapped.get((r["target_id"], r["model"]))
        raw = m["original_record_json"] if m else {}
        flag, comment = (
            r["original_uncertainty_type"],
            r["original_uncertainty_comment"],
        )
        flag_id = r["source_id"] or r["target_id"]
        flag_domain = r["domain"]
        if r["kind"] != "data":
            flag_id = item6[r["study_id"], r["model"]]["source_id"]
            flag_domain = "rob_item6"
        elif r["study_id"] in ("foroughi_2016", "ghani_2022") and r["field"] in (
            "sd",
            "se",
            "ci_low",
            "ci_high",
        ):
            flag, comment = (raw.get("metadata_u_type"), raw.get("metadata_u_comment"))
            flag_domain = "metadata"
        record = {
            k: r[k]
            for k in (
                "field_id",
                "target_id",
                "study_id",
                "model",
                "kind",
                "field",
                "domain",
                "eligibility_class",
                "original_value_json",
                "reviewed_value_json",
                "reference_status_reason",
            )
        }
        record.update(
            adjudication_category="C",
            primary_accuracy_eligible=False,
            uncertainty_unit_id=":".join(
                (r["study_id"], r["model"], flag_id, flag_domain)
            ),
            uncertainty_decision_domain=flag_domain,
            uncertainty_type=flag,
            uncertainty_comment=comment,
            uncertainty_flag_assessment=acknowledgement(flag, comment, r["field"])
            if m
            else "no_emitted_row",
            flag_assessment_definition="Topic-relevant structured disclosure; does not validate the inferred value or its rationale.",
        )
        for version in ("original", "reviewed"):
            state, error, reason = assess(
                json.loads(r[version + "_value_json"]),
                r["field"],
                by_id[r["target_id"]],
                r["study_id"],
                reference_standard,
            )
            record.update(
                {
                    version + "_plausibility": state,
                    version + "_demonstrable_error": error,
                    version + "_demonstrable_error_type": "E2" if error else None,
                    version + "_assessment_reason": reason,
                }
            )
        output.append(record)
    return output


def joint_constraints(mappings, reference_standard):
    """Known totals constrain sets of unknown arm values, not each member."""
    grouped = defaultdict(list)
    issues = []
    for m in mappings:
        if not m["target_ids"]:
            continue
        sid, kind, i = m["target_ids"][0].split(":")
        ref = reference_standard[sid][kind][int(i) - 1]
        if kind == "groups" and ref["scope"] == "group":
            grouped[sid, m["model"], "groups"].append((m, ref))
        elif kind == "data" and sid in ("angellotti_2018", "tuomainen_2015"):
            grouped[
                sid,
                m["model"],
                ref.get("outcome"),
                ref.get("outcome_variant"),
                ref.get("week"),
                ref.get("value_type"),
            ].append((m, ref))
    for key, rows in grouped.items():
        sid, model = key[:2]
        if key[2] == "groups":
            overall = next(
                (
                    g
                    for g in reference_standard[sid]["groups"]
                    if g["scope"] == "overall"
                ),
                {},
            )
            checks = [
                (f, overall.get(f))
                for f in ("n_randomized", "n_analyzed", "n_not_analyzed")
            ]
        else:
            refs = [r for _, r in rows]
            arm_keys = [
                (
                    r.get("arm_id"),
                    r.get("vitd"),
                    r.get("dose_IU_day_equivalent"),
                    r.get("cointervention"),
                )
                for r in refs
            ]
            if len(rows) < 2 or len(set(arm_keys)) != len(rows):
                continue
            total = None
            if sid == "tuomainen_2015" and any(r.get("n") is None for r in refs):
                total = 65
            if (
                sid == "angellotti_2018"
                and refs[0].get("outcome")
                in ("hba1c", "ins_secretion_rate", "issi_2", "matsuda")
                and any(r.get("n") is None for r in refs)
            ):
                total = (
                    117
                    if refs[0].get("week") == 16
                    else 114
                    if refs[0].get("week") == 36
                    else 118
                )
            checks = [("n", total)]
        for field, total in checks:
            if total is None or not any((r.get(field) is None for _, r in rows)):
                continue
            for version in ("original", "reviewed"):
                values = [m[version + "_record_json"].get(field) for m, _ in rows]
                if (
                    all(isinstance(v, (int, float)) for v in values)
                    and sum(values) != total
                ):
                    issues.append(
                        dict(
                            study_id=sid,
                            model=model,
                            version=version,
                            field=field,
                            target_ids=[m["target_ids"][0] for m, _ in rows],
                            values=values,
                            known_total=total,
                            submitted_total=sum(values),
                            error_type="E2",
                            scope="joint_arithmetic_constraint",
                            reason="Submitted arm values do not sum to the known total. At least one is wrong; the evidence does not identify which. Do not replicate this error onto every C field.",
                        )
                    )
    return issues
