"""Build scored fields and sessions from model outputs and adjudicated references."""

import collections
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
from zipfile import ZipFile

from adjudication_categories import build_c_assessments, category, joint_constraints
from load_assessments import load_assessments
from reference_policy import matches_context
from value_equivalence import (
    comparison,
    record_comparison,
    whole_rationale,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "02_data"
if not os.environ.get("SLR_DATA_OUTPUT"):
    raise SystemExit(
        "Set SLR_DATA_OUTPUT to a separate output directory, or run 03_analysis/verify_data.py --rebuild."
    )
OUT = Path(os.environ["SLR_DATA_OUTPUT"]).resolve()
if OUT == DATA_DIR.resolve():
    raise SystemExit(
        "The current data folder is locked; rebuild into a separate directory."
    )
OUT.mkdir(parents=True, exist_ok=True)
REFERENCE_DIR = DATA_DIR / "reference"


def read(p):
    return json.loads((ROOT / p).read_text())


def match(r, c):
    return all((r.get(k) == v for k, v in c.items()))


def hashid(*v):
    return hashlib.sha256(
        json.dumps(v, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:20]


reference_standard = json.loads((REFERENCE_DIR / "reference_standard.json").read_text())
study_decisions = json.loads((REFERENCE_DIR / "study_decisions.json").read_text())
linked_assessments = load_assessments(DATA_DIR)
FIELD_STATUS = (
    json.loads((REFERENCE_DIR / "field_status.json").read_text())
    if (REFERENCE_DIR / "field_status.json").exists()
    else {}
)
ROW_ALTERNATIVES = (
    json.loads((REFERENCE_DIR / "row_representation_alternatives.json").read_text())
    if (REFERENCE_DIR / "row_representation_alternatives.json").exists()
    else {}
)


def context(o, s):
    c = {
        k: o.get(k)
        for k in ["outcome", "vitd", "dose_IU_day_equivalent", "cointervention", "week"]
    }
    for k, aliases in s.get("context_aliases", {}).items():
        if k in c:
            c[k] = aliases.get(str(c[k]), c[k])
    for x in s.get("context_overrides", []):
        if match(c, x["match"]):
            c.update(x["set"])
    c["week"] = s.get("week_aliases", {}).get(str(c["week"]), c["week"])
    if c["outcome"] in s.get("outcome_variant_defaults", {}):
        c["outcome_variant"] = s["outcome_variant_defaults"][c["outcome"]]
    return c


def target_id(sid, kind, i):
    return f"{sid}:{kind}:{i + 1:03d}"


def source_id(kind, o):
    return f"{kind}:{o['source_model']}:{o['_row']}"


def mappings():
    result = []
    overrides = (
        read("02_data/rules/row_mapping_overrides.json")
        if (DATA_DIR / "rules/row_mapping_overrides.json").exists()
        else {}
    )
    for kind, rr in linked_assessments.items():
        for x in rr:
            o = x["original"]
            sid = o["study_id"]
            s = study_decisions[sid]
            reference_rows = reference_standard[sid][kind]
            method = ""
            cand = []
            if kind == "items":
                cand = [
                    i
                    for i, r in enumerate(reference_rows)
                    if r["robust_item"] == o["robust_item"]
                ]
                method = "item_identity"
            elif kind == "groups":
                if o["scope"] == "overall":
                    cand = [
                        i
                        for i, r in enumerate(reference_rows)
                        if r["scope"] == "overall"
                    ]
                    method = "overall"
                elif o["source_model"] == s["groups_base"]:
                    cand = [
                        i
                        for i, r in enumerate(reference_rows)
                        if r["scope"] == o["scope"]
                        and r["group_index"] == o["group_index"]
                    ]
                    method = "adjudicated_base_group"
                else:
                    cand = [
                        i
                        for i, r in enumerate(reference_rows)
                        if r["scope"] == o["scope"] and r["label"] == o["label"]
                    ]
                    method = "exact_arm_label"
            else:
                c = context(o, s)
                if any(match(c, m) for m in s.get("excluded_contexts", [])):
                    method = "excluded_pooled_baseline"
                else:
                    if o["source_model"] == s["data_base"]:
                        cand = [
                            i
                            for i, r in enumerate(reference_rows)
                            if r.get("record_origin") != "source_addition"
                            and match(o, r["source_identity"])
                        ]
                        method = "adjudicated_base_identity"
                    if len(cand) != 1:
                        cand = [
                            i
                            for i, r in enumerate(reference_rows)
                            if matches_context(r, c, s)
                        ]
                        method = "adjudicated_context"
            manual = overrides.get(source_id(kind, o))
            if manual:
                cand = [
                    i
                    for i in range(len(reference_rows))
                    if target_id(sid, kind, i) == manual["target_id"]
                ]
                method = (
                    "reviewed_coordinate_mapping"
                    if cand
                    else "excluded_nonrandomized_cohort"
                )
            result.append(
                {
                    "source_id": source_id(kind, o),
                    "study_id": sid,
                    "kind": kind,
                    "model": o["source_model"],
                    "source_row": o["_row"],
                    "method": method,
                    "target_ids": [target_id(sid, kind, i) for i in cand],
                }
            )
    return result


NUM = [
    "mean",
    "sd",
    "median",
    "iqr_low",
    "iqr_high",
    "se",
    "ci_low",
    "ci_high",
    "min",
    "max",
]
META = [
    "outcome",
    "vitd",
    "dose_IU_day_equivalent",
    "cointervention",
    "week",
    "value_type",
    "unit",
    "n",
    "analysis_population",
    "reported_statistic",
]
GROUP = ["n_randomized", "n_analyzed", "n_not_analyzed", "pct_not_analyzed"]


def dumpcsv(name, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (OUT / name).open("w", newline="", encoding="utf-8-sig") as out:
        w = csv.DictWriter(out, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    k: json.dumps(v, ensure_ascii=False)
                    if isinstance(v, (dict, list))
                    else v
                    for k, v in r.items()
                }
            )


def encoded(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def source_text_values():
    result = {}
    issues = []
    byfile = collections.defaultdict(list)
    for x in linked_assessments["data"]:
        byfile[x["original"]["source_file"]].append(x["original"])
    archive = DATA_DIR / "inputs/model_outputs.zip"
    raw_files = {}
    if archive.exists():
        with ZipFile(archive) as z:
            raw_files = {
                name: z.read(name).decode("utf-8-sig") for name in z.namelist()
            }
    for f, rows in byfile.items():
        try:
            name = str(Path(f).relative_to("inputs"))
            text = (
                raw_files[name]
                if raw_files
                else (DATA_DIR / "inputs/model_outputs" / name).read_text(
                    encoding="utf-8-sig"
                )
            )
            start = text.find("{")
            obj = json.JSONDecoder().raw_decode(text[start:])[0]
            raw = obj["rows"]
            assert len(raw) == len(rows)
            for o, r in zip(sorted(rows, key=lambda x: x["_row"]), raw):
                assert o["outcome"] == r["outcome"]
                result[source_id("data", o)] = {**r, **r.get("values", {})}
        except Exception as e:
            issues.append({"file": f, "issue": str(e)})
    return (result, issues)


def main():
    scope_path = OUT / "rules/prompt_scope.json"
    if not scope_path.exists():
        scope_path = DATA_DIR / "rules/prompt_scope.json"
    scope = json.loads(scope_path.read_text())
    assert (
        hashlib.sha256((DATA_DIR / scope["reference"]).read_bytes()).hexdigest()
        == scope["sha256"]
    )
    maps = mappings()
    rules = read("02_data/rules/eligibility_rules.json")
    raw, rawissues = source_text_values()
    assert not rawissues, rawissues
    linked = {
        source_id(k, x["original"]): x
        for k, rr in linked_assessments.items()
        for x in rr
    }
    timing = list(
        csv.DictReader((DATA_DIR / "inputs/timing.csv").open(encoding="utf-8-sig"))
    )
    sessions = {}
    burden = collections.Counter()
    kindburden = collections.Counter()
    fieldburden = collections.Counter()
    for k, rr in linked_assessments.items():
        for x in rr:
            key = (
                x["original"]["study_id"],
                "data" if k == "data" else "rob",
                x["original"]["source_model"],
            )
            burden[key] += 1
            kindburden[key, k] += 1
            presented = (
                META + NUM + ["metadata_source", "numeric_source"]
                if k == "data"
                else [
                    "outcomes_assessed",
                    "step1",
                    "step2",
                    "support",
                    "step1_support",
                    "step2_support",
                ]
                if k == "items"
                else ["label"] + GROUP
            )
            fieldburden[key] += sum(x["original"].get(f) is not None for f in presented)
    for t in timing:
        key = (t["study_id"], t["task"], t["source_model"])
        assert key not in sessions
        sessions[key] = {
            "session_id": ":".join(key),
            "study_id": key[0],
            "task": key[1],
            "model": key[2],
            "reviewer": t["reviewer"],
            "assigned_reviewer": t["assigned_reviewer"],
            "uncertainty_visibility": t["uncertainty_status"],
            "review_order": int(t["review_order"]),
            "time_s": float(t["time_s"]),
            "original_row_burden": burden[key],
            "data_row_burden": kindburden[key, "data"],
            "rob_item_row_burden": kindburden[key, "items"],
            "rob_group_row_burden": kindburden[key, "groups"],
            "original_nonblank_field_burden_excluding_uncertainty": fieldburden[key],
            "timing_file": t["file"],
            "timing_sheet": t["sheet"],
            "timing_row": int(t["row"]),
        }
    targets = {}
    registry = []
    bytarget = collections.defaultdict(dict)
    for sid, d in sorted(reference_standard.items()):
        for kind in ["data", "items", "groups"]:
            for i, r in enumerate(d[kind]):
                tid = target_id(sid, kind, i)
                rule = rules.get(
                    tid,
                    {
                        "eligibility_class": "main_report",
                        "reason": "Locked report-specific reference; no graph-only or supplement-only restriction identified.",
                    },
                )
                if kind == "data" and (not scope["targets"][tid]["eligible"]):
                    decision = scope["targets"][tid]
                    rule = {
                        "eligibility_class": "excluded_prompt_scope",
                        "reason": decision["reason"] + " " + decision["workbook_cell"],
                    }
                targets[tid] = (sid, kind, r, rule)
                registry.append(
                    {
                        "target_id": tid,
                        "study_id": sid,
                        "kind": kind,
                        "eligibility_class": rule["eligibility_class"],
                        "eligibility_reason": rule["reason"],
                        "reference_row_json": r,
                        "evidence_attachment": d["attachment"],
                        "source_locator": r.get("numeric_source", r.get("pdf_locator")),
                        "adjudication_note": study_decisions[sid]["data_note"]
                        if kind == "data"
                        else study_decisions[sid].get("rob_note", r.get("support", "")),
                    }
                )
    for m in maps:
        assert len(m["target_ids"]) <= 1, m
        if m["target_ids"]:
            t = m["target_ids"][0]
            assert m["model"] not in bytarget[t], (t, m)
            bytarget[t][m["model"]] = linked[m["source_id"]]
        else:
            assert m["method"] in [
                "excluded_pooled_baseline",
                "excluded_nonrandomized_cohort",
            ], m
        o = linked[m["source_id"]]["original"]
        v = linked[m["source_id"]]["reviewed"]
        m.update(
            original_file=o["_file"],
            original_sheet=o["_sheet"],
            reviewed_file=v["_file"],
            reviewed_sheet=v["_sheet"],
            reviewed_row=v["_row"],
            original_record_json=o,
            reviewed_record_json=v,
        )
    decisions = read("02_data/rules/rationale_decisions.json")
    assert len(decisions) == 1152
    fields = []
    texts = []
    serialization = []
    for tid, (sid, kind, ref, rule) in targets.items():
        pair = bytarget[tid]
        columns = (
            META + NUM
            if kind == "data"
            else ["step1", "step2", "outcomes_assessed"]
            if kind == "items"
            else GROUP
        )
        for field in columns:
            vals = [ref.get(field)] + [
                z[version].get(field)
                for z in pair.values()
                for version in ["original", "reviewed"]
            ]
            status = FIELD_STATUS.get(
                tid + "|" + field,
                {"status": "selected_value", "scorable": True, "reason": ""},
            )
            active = (
                any(v is not None for v in vals)
                and status["scorable"]
                and (rule["eligibility_class"] != "excluded_prompt_scope")
            )
            for model in ["gpt", "claude"]:
                x = pair.get(model)
                o = x["original"] if x else {}
                v = x["reviewed"] if x else {}
                task = "data" if kind == "data" else "rob"
                sess = sessions[sid, task, model]
                domain = (
                    "numeric"
                    if kind == "data" and field in NUM
                    else "metadata"
                    if kind == "data"
                    else "rob_judgment"
                    if kind == "items"
                    else "rob_counts"
                )
                flagfield = (
                    "numeric_u_type"
                    if domain == "numeric"
                    else "metadata_u_type"
                    if domain == "metadata"
                    else "u_type"
                )
                flag_source = o
                if kind == "groups":
                    flag_source = next(
                        q["original"]
                        for q in linked_assessments["items"]
                        if q["original"]["study_id"] == sid
                        and q["original"]["source_model"] == model
                        and (q["original"]["robust_item"] == "item6")
                    )
                original_value = o.get(field)
                rawvalue = (
                    raw.get(source_id(kind, o), {}).get(field)
                    if x and kind == "data"
                    else original_value
                )
                drift = bool(x and kind == "data" and (rawvalue != original_value))
                if drift:
                    serialization.append(
                        {
                            "source_id": source_id(kind, o),
                            "field": field,
                            "raw_text_value": rawvalue,
                            "workbook_value": original_value,
                        }
                    )
                flags = flag_source.get(flagfield)
                primary = active and rule["eligibility_class"] == "main_report"
                augmented = active and rule["eligibility_class"] in (
                    "main_report",
                    "supplement_augmented_only",
                )
                row = {
                    "field_id": hashid(tid, model, field),
                    "target_id": tid,
                    "study_id": sid,
                    "session_id": sess["session_id"],
                    "model": model,
                    "kind": kind,
                    "domain": domain,
                    "field": field,
                    "outcome": ref.get("outcome"),
                    "outcome_variant": ref.get("outcome_variant"),
                    "arm_id": ref.get("arm_id"),
                    "week": ref.get("week"),
                    "robust_item": ref.get("robust_item"),
                    "group_index": ref.get("group_index"),
                    "original_row_present": bool(x),
                    "reviewed_row_present": bool(x),
                    "source_id": source_id(kind, o) if x else None,
                    "reference_value_json": encoded(ref.get(field)),
                    "original_value_json": encoded(rawvalue),
                    "workbook_value_json": encoded(original_value),
                    "raw_text_value_json": encoded(rawvalue),
                    "reviewed_value_json": encoded(v.get(field)),
                    "serialization_difference": drift,
                    "active_field": active,
                    "primary_eligible": primary,
                    "augmented_eligible": augmented,
                    "eligibility_class": rule["eligibility_class"],
                    "eligibility_reason": rule["reason"],
                    "original_uncertainty_type": flags,
                    "original_uncertainty_comment": flag_source.get(
                        flagfield.replace("type", "comment")
                    ),
                    "original_uncertainty_flagged": bool(flags),
                    "uncertainty_observable": bool(x),
                    "reference_uncertainty_type": ref.get(flagfield),
                    "reference_additional_uncertainty": ref.get(
                        "metadata_additional_u_types"
                    )
                    if domain == "metadata"
                    else None,
                    "reviewer": sess["reviewer"],
                    "uncertainty_visibility": sess["uncertainty_visibility"],
                    "review_order": sess["review_order"],
                    "reference_is_null": ref.get(field) is None,
                    "source_locator": ref.get("numeric_source", ref.get("pdf_locator")),
                }
                row.update(
                    prompt_scope_eligible=rule["eligibility_class"]
                    != "excluded_prompt_scope",
                    reference_status=status["status"],
                    reference_status_reason=status["reason"],
                    reference_scorable=status["scorable"],
                )
                row["adjudication_category"], row["adjudication_category_reason"] = (
                    category(kind, field, status, sid)
                )
                for label, value in [
                    ("original", rawvalue),
                    ("reviewed", v.get(field)),
                ]:
                    submitted = {**(o if label == "original" else v), field: value}
                    equal, comparison_rule = (
                        record_comparison(
                            field,
                            submitted,
                            ref,
                            sid,
                            status,
                            ROW_ALTERNATIVES.get(tid),
                        )
                        if x
                        else (True, "no_reported_value_to_omit")
                        if ref.get(field) is None
                        else (False, "omitted_row")
                    )
                    error = not equal
                    required = {
                        "mean_sd": ["mean", "sd"],
                        "mean_se": ["mean", "se"],
                        "mean_ci": ["mean", "ci_low", "ci_high"],
                        "median_iqr": ["median", "iqr_low", "iqr_high"],
                        "median_minmax": ["median", "min", "max"],
                    }.get(ref.get("reported_statistic"), [])
                    extra_stat = (
                        kind == "data"
                        and field in NUM
                        and (ref.get(field) is None)
                        and (field not in required)
                    )
                    code = (
                        None
                        if not error
                        else "E1"
                        if value is None or extra_stat
                        else "E2"
                    )
                    row[label + "_literal_equal"] = value == ref.get(field)
                    row[label + "_comparison_rule"] = comparison_rule
                    row[label + "_error"] = int(error) if active else None
                    row[label + "_error_type"] = code if active else None
                    row[label + "_comparison"] = (
                        "all_blank_not_scored"
                        if not active
                        else "omitted_eligible_value"
                        if error and value is None
                        else "unnecessary_statistic"
                        if error and extra_stat
                        else "unsupported_nonblank"
                        if error and ref.get(field) is None
                        else "value_mismatch"
                        if error
                        else "match"
                        if comparison_rule == "literal_match"
                        else comparison_rule
                    )
                    if rule["eligibility_class"] == "excluded_prompt_scope":
                        row[label + "_comparison"] = (
                            "outside_requested_extraction_scope"
                        )
                    if not status["scorable"]:
                        row[label + "_comparison"] = (
                            "category_C_unverifiable_not_binary_scored"
                        )
                if kind == "items" and field == "outcomes_assessed":
                    row["domain"] = "rob_outcome_scope"
                    if ref["robust_item"] != "item1":
                        row.update(
                            primary_eligible=False,
                            augmented_eligible=False,
                            eligibility_reason="Repeated study-level outcome scope; retained on item1 only in denominators.",
                        )
                row["calibration_eligible"] = row["primary_eligible"] and bool(x)
                row["missed_uncertainty"] = (
                    bool(row["original_error"] and (not flags))
                    if row["calibration_eligible"]
                    else None
                )
                row["certain_but_wrong"] = row["missed_uncertainty"]
                row["uncertain_but_correct"] = (
                    bool(flags and row["original_error"] == 0)
                    if row["calibration_eligible"]
                    else None
                )
                fields.append(row)
        if kind == "items":
            for model in ["gpt", "claude"]:
                x = pair[model]
                o = x["original"]
                v = x["reviewed"]
                texts.append(
                    {
                        "target_id": tid,
                        "study_id": sid,
                        "model": model,
                        "robust_item": ref["robust_item"],
                        "session_id": sessions[sid, "rob", model]["session_id"],
                        "original_support": o.get("support"),
                        "original_step1_support": o.get("step1_support"),
                        "original_step2_support": o.get("step2_support"),
                        "reviewed_support": v.get("support"),
                        "reviewed_step1_support": v.get("step1_support"),
                        "reviewed_step2_support": v.get("step2_support"),
                        "reference_support": ref.get("support"),
                        "reference_step1_support": ref.get("step1_support"),
                        "reference_step2_support": ref.get("step2_support"),
                        "original_uncertainty_type": o.get("u_type"),
                        "source_locator": ref["pdf_locator"],
                        "original_step1": o.get("step1"),
                        "original_step2": o.get("step2"),
                        "reviewed_step1": v.get("step1"),
                        "reviewed_step2": v.get("step2"),
                        "reference_step1": ref.get("step1"),
                        "reference_step2": ref.get("step2"),
                        "semantic_status": "not_scored",
                        "original_rationale_error": None,
                        "original_rationale_error_type": None,
                        "reviewed_rationale_error": None,
                        "reviewed_rationale_error_type": None,
                        "reason": "",
                    }
                )
    for row in texts:
        key = f"{row['study_id']}:{row['model']}:{row['robust_item']}"
        decision = decisions[key]
        raw = {
            k: row["original_" + k]
            for k in ["support", "step1_support", "step2_support"]
        }
        assert raw == {k: row["reviewed_" + k] for k in raw}
        assert (
            hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
            == decision["text_sha256"]
        )
        assert decision["status"] == "reviewed"
        for k in [
            "original_rationale_error",
            "original_rationale_error_type",
            "reviewed_rationale_error",
            "reviewed_rationale_error_type",
            "reason",
            "adjudicator",
            "date",
            "text_sha256",
            "reviewed_text_unchanged",
        ]:
            row[k] = decision[k]
        row["semantic_status"] = "reviewed"
        row["semantic_decision_id"] = key
        row["rationale_category_C_component"] = (
            decision.get("adjudication_category") == "C_component"
        )
        row["rationale_zero_error_interpretation"] = decision.get(
            "zero_error_interpretation",
            "No demonstrated semantic rationale error under the source-reviewed rule.",
        )
        for version in ["original", "reviewed", "reference"]:
            row[version + "_whole_rationale"] = whole_rationale(row, version + "_")
        assert row["reference_whole_rationale"], "Missing reference rationale"
        rule = targets[row["target_id"]][3]
        row["eligibility_class"] = rule["eligibility_class"]
        row["eligibility_reason"] = rule["reason"]
        complete = all(
            FIELD_STATUS.get(row["target_id"] + "|" + f, {}).get("scorable", True)
            for f in ["step1", "step2"]
        )
        row["reference_judgments_complete"] = complete
        row["primary_eligible"] = (
            complete and rule["eligibility_class"] == "main_report"
        )
        row["augmented_eligible"] = complete and rule["eligibility_class"] in (
            "main_report",
            "supplement_augmented_only",
        )
        row["original_uncertainty_flagged"] = bool(row["original_uncertainty_type"])
        row["calibration_eligible"] = row["primary_eligible"]
        for version in ["original", "reviewed"]:
            wrong = any(
                not comparison(
                    f,
                    row[version + "_" + f],
                    row["reference_" + f],
                    row["study_id"],
                    FIELD_STATUS.get(row["target_id"] + "|" + f, {}).get(
                        "accepted_values"
                    ),
                )[0]
                for f in ["step1", "step2"]
            )
            row[version + "_judgment_pair_error"] = int(wrong) if complete else None
            row[version + "_item_composite_error"] = (
                int(wrong or row[version + "_rationale_error"]) if complete else None
            )
        row["certain_but_wrong"] = (
            bool(
                row["original_item_composite_error"]
                and (not row["original_uncertainty_flagged"])
            )
            if row["primary_eligible"]
            else None
        )
    extras = [
        {
            **m,
            "eligibility_class": m["method"],
            "original_error_type": "E1",
            "reviewed_error_type": "E1",
            "primary_eligible": False,
            "reason": "Unnecessary pooled/nonrandomized record; completeness audit only, outside the canonical field denominator.",
        }
        for m in maps
        if not m["target_ids"]
    ]
    clusters = [
        {
            "study_id": sid,
            "report_cluster_id": sid,
            "known_trial_cluster_id": "mousa_2017_naderpoor_2018"
            if sid in ["mousa_2017", "naderpoor_2018"]
            else sid,
            "trial_linkage_status": "confirmed_companion_pair"
            if sid in ["mousa_2017", "naderpoor_2018"]
            else "no_cross_report_link_established",
            "evidence": "; ".join(reference_standard[sid]["qualifications"]),
        }
        for sid in sorted(reference_standard)
    ]
    category_c = build_c_assessments(fields, registry, maps, reference_standard)
    item6_rationales = {
        (t["study_id"], t["model"]): t for t in texts if t["robust_item"] == "item6"
    }
    for record in category_c:
        rationale = (
            item6_rationales[record["study_id"], record["model"]]
            if record["kind"] != "data"
            else None
        )
        for version in ["original", "reviewed"]:
            record[version + "_associated_rationale_error"] = (
                rationale[version + "_rationale_error"] if rationale else None
            )
        record["associated_rationale_reason"] = (
            rationale["reason"] if rationale else None
        )
    constraint_issues = joint_constraints(maps, reference_standard)
    dumpcsv("category_c_assessments.csv", category_c)
    (OUT / "category_c_joint_constraints.json").write_text(
        json.dumps(constraint_issues, indent=2) + "\n"
    )
    dumpcsv("field_comparisons.csv", fields)
    dumpcsv("sessions.csv", list(sessions.values()))
    dumpcsv("row_mapping.csv", maps)
    dumpcsv("reference_rows.csv", registry)
    dumpcsv("extra_source_rows.csv", extras)
    dumpcsv("rationale_assessment.csv", texts)
    dumpcsv("study_clusters.csv", clusters)
    dumpcsv("serialization_differences.csv", serialization)
    payload = json.dumps(
        {
            "fields": fields,
            "sessions": list(sessions.values()),
            "row_mapping": maps,
            "reference_rows": registry,
            "extras": extras,
            "rationales": texts,
            "clusters": clusters,
            "category_c_assessments": category_c,
            "category_c_joint_constraints": constraint_issues,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    (OUT / "dataset.json.gz").write_bytes(gzip.compress(payload, mtime=0))
    for name in [
        "field_comparisons.csv",
        "row_mapping.csv",
        "reference_rows.csv",
        "rationale_assessment.csv",
    ]:
        q = OUT / name
        (OUT / (name + ".gz")).write_bytes(gzip.compress(q.read_bytes(), mtime=0))
        q.unlink()
    print("Dataset built.")


if __name__ == "__main__":
    main()
