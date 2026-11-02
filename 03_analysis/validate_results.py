"""Recompute primary estimates and intervals from the analysis inputs."""

import collections
import csv
import gzip
import json
import math
import subprocess
from pathlib import Path

import numpy as np

ANALYSIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ANALYSIS_DIR / "results/current"
dataset = json.loads(
    gzip.decompress((ANALYSIS_DIR.parent / "02_data/dataset.json.gz").read_bytes())
)


def read(name):
    return list(csv.DictReader((OUTPUT_DIR / name).open()))


def equal(a, b):
    assert math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-12), (a, b)


vis = {x["session_id"]: x["uncertainty_visibility"] for x in dataset["sessions"]}
rows = []
for x in dataset["fields"]:
    if x["primary_eligible"] and x["domain"] in ["numeric", "metadata", "rob_judgment"]:
        rows.append(
            (
                x["study_id"],
                x["model"],
                "data" if x["kind"] == "data" else "rob",
                vis[x["session_id"]],
                x["original_error"],
                x["reviewed_error"],
            )
        )
for x in dataset["rationales"]:
    if x["primary_eligible"]:
        rows.append(
            (
                x["study_id"],
                x["model"],
                "rob",
                vis[x["session_id"]],
                x["original_rationale_error"],
                x["reviewed_rationale_error"],
            )
        )
for res in read("accuracy.csv"):
    if (
        res["scope"] not in ["data_primary", "rob_primary"]
        or res["clustering"] != "report"
    ):
        continue
    task = res["scope"].split("_")[0]
    col = 4 if res["version"] == "original" else 5
    x = [r for r in rows if r[1] == res["model"] and r[2] == task]
    correct = sum(r[col] == 0 for r in x)
    equal(correct, res["numerator"])
    equal(len(x), res["denominator"])
    equal(correct / len(x), res["estimate"])
unitmembers = collections.defaultdict(list)
for x in dataset["fields"]:
    if x["primary_eligible"] and x["kind"] == "data":
        unitmembers[x["study_id"], x["model"], x["target_id"], x["domain"]].append(x)
units = []
for key, rr in unitmembers.items():
    present = rr[0]["original_row_present"]
    required = any(json.loads(x["reference_value_json"]) is not None for x in rr)
    if not present and (not required):
        continue
    flag = bool(rr[0]["original_uncertainty_type"]) if present else False
    error = any(x["original_error"] == 1 for x in rr) if present else True
    units.append((key[0], key[1], "data", present, flag, error))
for x in dataset["rationales"]:
    if x["primary_eligible"]:
        units.append(
            (
                x["study_id"],
                x["model"],
                "rob",
                True,
                bool(x["original_uncertainty_type"]),
                bool(
                    x["original_judgment_pair_error"] or x["original_rationale_error"]
                ),
            )
        )
for res in read("uncertainty_confusion_counts.csv"):
    if (
        res["scope"]
        not in [
            "data_emitted_primary",
            "rob_emitted_primary",
            "data_all_target_safety",
            "rob_all_target_safety",
        ]
        or res["clustering"] != "report"
    ):
        continue
    task = res["scope"].split("_")[0]
    safety = "safety" in res["scope"]
    ct = collections.Counter()
    for sid, model, tk, present, flag, error in units:
        if model != res["model"] or tk != task or (not (safety or present)):
            continue
        ct["TP" if flag and error else "FP" if flag else "FN" if error else "TN"] += 1
    for label in ["TP", "FP", "TN", "FN"]:
        equal(ct[label], res[label])
for res in read("verification_quality.csv"):
    if (
        res["scope"] not in ["data_primary", "rob_primary"]
        or res["model"] != "pooled"
        or res["clustering"] != "report"
    ):
        continue
    task = res["scope"].split("_")[0]
    x = [r for r in rows if r[2] == task and r[3] == res["explicit_flag_visibility"]]
    if res["metric"] == "net_verification_change":
        num = sum(r[5] - r[4] for r in x)
        den = len(x)
    elif res["metric"] == "residual_error":
        num = sum(r[5] for r in x)
        den = len(x)
    elif res["metric"] == "original_errors_corrected":
        num = sum(r[4] == 1 and r[5] == 0 for r in x)
        den = sum(r[4] for r in x)
    else:
        num = sum(r[4] == 0 and r[5] == 1 for r in x)
        den = sum(r[4] == 0 for r in x)
    equal(num, res["numerator"])
    equal(den, res["denominator"])
    equal(num / den, res["estimate"])
w = np.load(OUTPUT_DIR / "bootstrap_weights.npz")["report"]
ids = sorted({r[0] for r in rows})
for task in ["data", "rob"]:
    draws = {}
    for model in ["gpt", "claude"]:
        counts = np.array(
            [
                [
                    sum(
                        r[4] == 0
                        for r in rows
                        if r[0] == sid and r[1] == model and (r[2] == task)
                    ),
                    sum(
                        1
                        for r in rows
                        if r[0] == sid and r[1] == model and (r[2] == task)
                    ),
                ]
                for sid in ids
            ]
        )
        numerator = w @ counts[:, 0]
        denominator = w @ counts[:, 1]
        draws[model] = numerator / denominator
    ci = np.quantile(draws["gpt"] - draws["claude"], [0.025, 0.975])
    res = next(
        x
        for x in read("model_contrasts.csv")
        if x["scope"] == task + "_primary"
        and x["clustering"] == "report"
        and (x["version"] == "original")
    )
    equal(ci[0], res["ci_low"])
    equal(ci[1], res["ci_high"])
for task in ["data", "rob"]:
    for metric in [
        "net_verification_change",
        "residual_error",
        "original_errors_corrected",
        "original_correct_made_wrong",
    ]:
        draws = {}
        for visibility in ["visible", "hidden"]:
            counts = []
            for sid in ids:
                x = [
                    r
                    for r in rows
                    if r[0] == sid and r[2] == task and (r[3] == visibility)
                ]
                if metric == "net_verification_change":
                    num = sum(r[5] - r[4] for r in x)
                    den = len(x)
                elif metric == "residual_error":
                    num = sum(r[5] for r in x)
                    den = len(x)
                elif metric == "original_errors_corrected":
                    num = sum(r[4] == 1 and r[5] == 0 for r in x)
                    den = sum(r[4] for r in x)
                else:
                    num = sum(r[4] == 0 and r[5] == 1 for r in x)
                    den = sum(r[4] == 0 for r in x)
                counts.append([num, den])
            counts = np.array(counts)
            draws[visibility] = w @ counts[:, 0] / (w @ counts[:, 1])
        ci = np.quantile(draws["visible"] - draws["hidden"], [0.025, 0.975])
        res = next(
            x
            for x in read("visibility_quality_contrasts.csv")
            if x["scope"] == task + "_primary"
            and x["model"] == "pooled"
            and (x["clustering"] == "report")
            and (x["metric"] == metric)
        )
        equal(ci[0], res["ci_low"])
        equal(ci[1], res["ci_high"])
for task in ["data", "rob"]:
    for model in ["gpt", "claude"]:
        counts = []
        for sid in ids:
            x = [
                r
                for r in units
                if r[0] == sid and r[1] == model and (r[2] == task) and r[3]
            ]
            counts.append(
                [
                    sum(r[4] and r[5] for r in x),
                    sum(r[4] for r in x),
                    sum(not r[4] and r[5] for r in x),
                    sum(not r[4] for r in x),
                ]
            )
        counts = np.array(counts)
        boot = w @ counts
        ci = np.quantile(
            boot[:, 0] / boot[:, 1] / (boot[:, 2] / boot[:, 3]), [0.025, 0.975]
        )
        res = next(
            x
            for x in read("uncertainty_flag_performance.csv")
            if x["scope"] == task + "_emitted_primary"
            and x["model"] == model
            and (x["clustering"] == "report")
            and (x["metric"] == "relative_enrichment")
        )
        equal(ci[0], res["ci_low"])
        equal(ci[1], res["ci_high"])
sessions = dataset["sessions"]
timing = read("timing_effects.csv")
for task in ["data", "rob"]:
    ss = [s for s in sessions if s["task"] == task]
    X = []
    y = []
    for s in ss:
        z = [
            int(s["model"] == "gpt"),
            int(s["reviewer"] == "MK"),
            int(s["uncertainty_visibility"] == "visible"),
            s["review_order"],
        ]
        if task == "data":
            z.append(math.log(s["original_row_burden"]))
        X.append(z)
        y.append(math.log(s["time_s"]))
    X = np.array(X, float)
    y = np.array(y)
    for sid in {s["study_id"] for s in ss}:
        ix = [i for i, s in enumerate(ss) if s["study_id"] == sid]
        X[ix] -= X[ix].mean(axis=0)
        y[ix] -= y[ix].mean()
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    res = next(
        r for r in timing if r["task"] == task and r["specification"] == "primary"
    )
    equal(math.exp(b[2]), res["estimate"])
fontchecks = {}
for filename in ["figure_1_summary.pdf", "figure_S1_omission_sensitivity.pdf"]:
    p = OUTPUT_DIR / "figures" / filename
    assert p.is_file() and p.stat().st_size > 0, f"Missing figure: {filename}"
    output = subprocess.check_output(["pdffonts", str(p)], text=True)
    fonts = output.splitlines()[2:]
    assert fonts and all(
        "Arial" in line and line.split()[-5] == "yes" for line in fonts
    ), output
    fontchecks[p.name] = output
(OUTPUT_DIR / "pdf_font_checks.json").write_text(
    json.dumps(fontchecks, indent=2) + "\n"
)
introduced = []
for x in dataset["fields"]:
    if (
        x["primary_eligible"]
        and x["kind"] == "data"
        and (x["original_error"] == 0)
        and (x["reviewed_error"] == 1)
    ):
        same = json.loads(x["workbook_value_json"]) == json.loads(
            x["reviewed_value_json"]
        )
        if same:
            assert (
                x["original_comparison_rule"]
                == "equivalent_source_published_row_representation"
            ), x
            assert x["reviewed_comparison_rule"] == "substantive_value_difference", x
            related = [
                y
                for y in dataset["fields"]
                if y["target_id"] == x["target_id"] and y["model"] == x["model"]
            ]
            assert any(
                y["workbook_value_json"] != y["reviewed_value_json"] for y in related
            ), x
        introduced.append(
            {
                k: x[k]
                for k in [
                    "study_id",
                    "model",
                    "source_id",
                    "field",
                    "workbook_value_json",
                    "reviewed_value_json",
                    "reference_value_json",
                    "reviewer",
                    "uncertainty_visibility",
                ]
            }
        )
with (OUTPUT_DIR / "introduced_extraction_errors_audit.csv").open(
    "w", newline=""
) as fh:
    writer = csv.DictWriter(fh, fieldnames=list(introduced[0]))
    writer.writeheader()
    writer.writerows(introduced)
checks = dict(
    status="passed",
    primary_estimates=True,
    primary_intervals=True,
    timing_estimates=True,
    pdf_fonts=True,
)
(OUTPUT_DIR / "independent_validation.json").write_text(
    json.dumps(checks, indent=2) + "\n"
)
print(json.dumps(checks))
