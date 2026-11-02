"""Estimate accuracy, uncertainty-flag performance and verification effects."""

import datetime
import gzip
import hashlib
import json
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from category_c_reporting import export_category_c

ANALYSIS_DIR = Path(__file__).resolve().parent
DATA_DIR = ANALYSIS_DIR.parent / "02_data"
OUTPUT_DIR = ANALYSIS_DIR / "results/current"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BOOTSTRAP_REPLICATES = 10000
SEED = 20261007
manifest = json.loads((DATA_DIR / "manifest.json").read_text())
for primary_fields, h in manifest["files"].items():
    assert hashlib.sha256((DATA_DIR / primary_fields).read_bytes()).hexdigest() == h, (
        primary_fields
    )
assert (
    hashlib.sha256((ANALYSIS_DIR / "ANALYSIS_PLAN.md").read_bytes()).hexdigest()
    == manifest["analysis_plan_sha256"]
)
(OUTPUT_DIR / "execution_start.json").write_text(
    json.dumps(
        {
            "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "plan_sha256": manifest["analysis_plan_sha256"],
            "dataset_sha256": hashlib.sha256(
                (DATA_DIR / "dataset.json.gz").read_bytes()
            ).hexdigest(),
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "seed": SEED,
        },
        indent=2,
    )
    + "\n"
)
dataset = json.loads(gzip.decompress((DATA_DIR / "dataset.json.gz").read_bytes()))
field_records = pd.DataFrame(dataset["fields"])
rationale_records = pd.DataFrame(dataset["rationales"])
sessions = pd.DataFrame(dataset["sessions"])
export_category_c(dataset, OUTPUT_DIR)
visibility = dict(zip(sessions.session_id, sessions.uncertainty_visibility))
clusters = dict(
    zip(
        pd.DataFrame(dataset["clusters"]).study_id,
        pd.DataFrame(dataset["clusters"]).known_trial_cluster_id,
    )
)
field_records["task"] = np.where(field_records.kind == "data", "data", "rob")
field_records["explicit_flag_visibility"] = field_records.session_id.map(visibility)
rationale_fields = pd.DataFrame(
    [
        dict(
            study_id=x["study_id"],
            model=x["model"],
            session_id=x["session_id"],
            task="rob",
            domain="rob_rationale",
            field="rationale",
            robust_item=x["robust_item"],
            target_id=x["target_id"],
            primary_eligible=x["primary_eligible"],
            augmented_eligible=x["augmented_eligible"],
            reference_is_null=False,
            original_row_present=True,
            original_uncertainty_flagged=x["original_uncertainty_flagged"],
            original_uncertainty_type=x["original_uncertainty_type"],
            original_error=x["original_rationale_error"],
            reviewed_error=x["reviewed_rationale_error"],
            original_error_type=x["original_rationale_error_type"],
            reviewed_error_type=x["reviewed_rationale_error_type"],
            original_literal_equal=not x["original_rationale_error"],
            reviewed_literal_equal=not x["reviewed_rationale_error"],
            explicit_flag_visibility=visibility[x["session_id"]],
        )
        for x in dataset["rationales"]
    ]
)
fields = pd.concat([field_records, rationale_fields], ignore_index=True)
primary_domains = ["numeric", "metadata", "rob_judgment", "rob_rationale"]
primary_fields = fields[
    fields.primary_eligible & fields.domain.isin(primary_domains)
].copy()
primary_fields.to_csv(
    OUTPUT_DIR / "primary_scored_fields.csv.gz",
    index=False,
    compression={"method": "gzip", "mtime": 0},
)


class Bootstrap:
    def __init__(self, family=False):
        self.family = family
        self.ids = sorted(set(clusters.values()) if family else clusters)
        self.index = {s: i for i, s in enumerate(self.ids)}
        self.w = (
            np.random.default_rng(SEED)
            .multinomial(
                len(self.ids),
                np.repeat(1 / len(self.ids), len(self.ids)),
                size=BOOTSTRAP_REPLICATES,
            )
            .astype(float)
        )

    def aggregate(self, study, num, den):
        nn = np.zeros(len(self.ids))
        dd = np.zeros(len(self.ids))
        idx = [self.index[clusters[s] if self.family else s] for s in study]
        np.add.at(nn, idx, np.asarray(num, float))
        np.add.at(dd, idx, np.asarray(den, float))
        return (nn, dd)

    def ratio(self, study, num, den):
        nn, dd = self.aggregate(study, num, den)
        a = self.w @ nn
        b = self.w @ dd
        draws = np.divide(a, b, out=np.full(BOOTSTRAP_REPLICATES, np.nan), where=b != 0)
        return (
            nn.sum() / dd.sum() if dd.sum() else np.nan,
            draws,
            float(nn.sum()),
            float(dd.sum()),
            int(np.count_nonzero(dd)),
        )


engines = {"report": Bootstrap(), "known_companion": Bootstrap(True)}
np.savez_compressed(
    OUTPUT_DIR / "bootstrap_weights.npz",
    report=engines["report"].w,
    known_companion=engines["known_companion"].w,
)


def interval(draws):
    valid = np.isfinite(draws)
    n = int(valid.sum())
    return (
        (*np.quantile(draws[valid], [0.025, 0.975]), n)
        if n >= 0.95 * BOOTSTRAP_REPLICATES
        else (np.nan, np.nan, n)
    )


def result(metric, estimate, draws, **meta):
    lo, hi, n = interval(draws)
    return dict(
        **meta,
        metric=metric,
        estimate=estimate,
        ci_low=lo,
        ci_high=hi,
        valid_replicates=n,
    )


def ratio_result(eng, dd, num, den, metric, **meta):
    est, boot, n, dn, nr = eng.ratio(dd.study_id, num, den)
    return (
        result(
            metric,
            est,
            boot,
            numerator=n,
            denominator=dn,
            n_reports_with_denominator=nr,
            **meta,
        ),
        boot,
    )


accuracy = []
contrasts = []


def accuracy_scope(dd, scope, clustering="report", macro=False):
    eng = engines[clustering]
    for version in ["original", "reviewed"]:
        pair = {}
        for model in ["gpt", "claude"]:
            x = dd[dd.model == model].copy()
            correct = 1 - x[version + "_error"].astype(float)
            if macro:
                tmp = (
                    pd.DataFrame({"study_id": x.study_id, "v": correct})
                    .groupby("study_id")
                    .v.mean()
                    .reset_index()
                )
                x = tmp
                correct = x.v
            row, boot = ratio_result(
                eng,
                x,
                correct,
                np.ones(len(x)),
                "accuracy",
                scope=scope,
                clustering=clustering,
                version=version,
                model=model,
                weighting="report_macro" if macro else "field",
            )
            accuracy.append(row)
            pair[model] = (row["estimate"], boot)
        contrasts.append(
            result(
                "gpt_minus_claude",
                pair["gpt"][0] - pair["claude"][0],
                pair["gpt"][1] - pair["claude"][1],
                scope=scope,
                clustering=clustering,
                version=version,
                weighting="report_macro" if macro else "field",
            )
        )


for task in ["data", "rob"]:
    base = primary_fields[primary_fields.task == task]
    accuracy_scope(base, task + "_primary")
    accuracy_scope(base[~base.reference_is_null], task + "_reference_nonblank")
    accuracy_scope(base, task + "_macro", macro=True)
    accuracy_scope(base, task + "_primary", "known_companion")
    aug = fields[
        fields.augmented_eligible
        & fields.domain.isin(primary_domains)
        & (fields.task == task)
    ]
    accuracy_scope(aug, task + "_supplement_augmented")
for dom in [
    "numeric",
    "metadata",
    "rob_judgment",
    "rob_rationale",
    "rob_counts",
    "rob_outcome_scope",
]:
    accuracy_scope(fields[fields.primary_eligible & (fields.domain == dom)], dom)
composite = rationale_records.copy()
composite["original_error"] = rationale_records.original_item_composite_error
composite["reviewed_error"] = rationale_records.reviewed_item_composite_error
composite["explicit_flag_visibility"] = composite.session_id.map(visibility)
accuracy_scope(composite[composite.primary_eligible], "rob_item_composite")
for item in sorted(rationale_records.robust_item.unique()):
    accuracy_scope(
        composite[composite.primary_eligible & (composite.robust_item == item)],
        "rob_" + item + "_composite",
    )
pd.DataFrame(accuracy).to_csv(OUTPUT_DIR / "accuracy.csv", index=False)
pd.DataFrame(contrasts).to_csv(OUTPUT_DIR / "model_contrasts.csv", index=False)
units = []
for (sid, model, tid, dom), x in field_records[
    field_records.primary_eligible & (field_records.task == "data")
].groupby(["study_id", "model", "target_id", "domain"], sort=True):
    present = bool(x.original_row_present.iloc[0])
    required = bool((~x.reference_is_null).any())
    if not present and (not required):
        continue
    flags = x.original_uncertainty_flagged.unique()
    assert len(flags) == 1
    units.append(
        dict(
            unit_id=f"{tid}:{model}:{dom}",
            study_id=sid,
            model=model,
            task="data",
            domain=dom,
            source_id=x.source_id.iloc[0] if present else None,
            target_id=tid,
            emitted=present,
            synthetic_omission=not present,
            required=required,
            flagged=bool(flags[0]) if present else False,
            error=int(x.original_error.max()) if present else 1,
            flag_type=x.original_uncertainty_type.iloc[0] if present else None,
            member_fields=len(x),
        )
    )
for x in dataset["rationales"]:
    if x["primary_eligible"]:
        units.append(
            dict(
                unit_id=f"{x['target_id']}:{x['model']}:item",
                study_id=x["study_id"],
                model=x["model"],
                task="rob",
                domain="rob_item_composite",
                source_id=None,
                target_id=x["target_id"],
                emitted=True,
                synthetic_omission=False,
                required=True,
                flagged=x["original_uncertainty_flagged"],
                error=x["original_item_composite_error"],
                flag_type=x["original_uncertainty_type"],
                member_fields=1,
            )
        )
prediction_units = pd.DataFrame(units)
assert not prediction_units.unit_id.duplicated().any()
prediction_units.to_csv(
    OUTPUT_DIR / "uncertainty_prediction_units.csv.gz",
    index=False,
    compression={"method": "gzip", "mtime": 0},
)
triage = []
confusions = []


def triage_scope(x, scope, clustering="report", subtype=None):
    eng = engines[clustering]
    for model in ["gpt", "claude"]:
        z = x[x.model == model].copy()
        flag = (
            z.flagged.astype(bool)
            if subtype is None
            else z.flag_type.fillna("").str.contains(subtype)
        )
        err = z.error.astype(bool)
        ones = np.ones(len(z))
        tp = (flag & err).astype(int)
        fp = (flag & ~err).astype(int)
        tn = (~flag & ~err).astype(int)
        fn = (~flag & err).astype(int)
        meta = dict(
            scope=scope,
            clustering=clustering,
            model=model,
            flag_definition=subtype or "any_U1_U2",
        )
        confusions.append(
            dict(
                **meta,
                TP=int(tp.sum()),
                FP=int(fp.sum()),
                TN=int(tn.sum()),
                FN=int(fn.sum()),
                units=len(z),
                synthetic_omission_units=int(z.synthetic_omission.sum())
                if "synthetic_omission" in z
                else 0,
            )
        )
        definitions = {
            "sensitivity": (tp, tp + fn),
            "specificity": (tn, tn + fp),
            "ppv": (tp, tp + fp),
            "npv": (tn, tn + fn),
            "error_flagged": (tp, tp + fp),
            "error_unflagged": (fn, tn + fn),
            "flag_prevalence": (tp + fp, ones),
            "certain_but_wrong": (fn, ones),
            "overflagging": (fp, tp + fp),
            "flagged_correct_prevalence": (fp, ones),
        }
        rates = {}
        for metric, (num, den) in definitions.items():
            row, boot = ratio_result(eng, z, num, den, metric, **meta)
            triage.append(row)
            rates[metric] = (row["estimate"], boot)
        p1, b1 = rates["error_flagged"]
        p0, b0 = rates["error_unflagged"]
        triage.append(result("absolute_enrichment", p1 - p0, b1 - b0, **meta))
        with np.errstate(divide="ignore", invalid="ignore"):
            rr = np.divide(p1, p0)
            draws = b1 / b0
        triage.append(result("relative_enrichment", rr, draws, **meta))


for task in ["data", "rob"]:
    emitted = prediction_units[
        (prediction_units.task == task) & prediction_units.emitted
    ]
    alltarget = prediction_units[prediction_units.task == task]
    triage_scope(emitted, task + "_emitted_primary")
    triage_scope(alltarget, task + "_all_target_safety")
    triage_scope(emitted, task + "_emitted_primary", "known_companion")
    for typ in ["U1", "U2"]:
        triage_scope(emitted, task + "_subtype_exploratory", subtype=typ)
for dom in ["numeric", "metadata"]:
    triage_scope(
        prediction_units[(prediction_units.domain == dom) & prediction_units.emitted],
        dom + "_emitted_primary",
    )
    triage_scope(
        prediction_units[prediction_units.domain == dom], dom + "_all_target_safety"
    )
for doms, name in [
    (["numeric", "metadata"], "data_field_secondary"),
    (["rob_judgment"], "rob_judgment_field_secondary"),
    (["rob_counts"], "rob_count_field_secondary"),
]:
    x = field_records[
        field_records.primary_eligible
        & field_records.original_row_present
        & field_records.domain.isin(doms)
    ].copy()
    x = x.rename(
        columns={
            "original_uncertainty_flagged": "flagged",
            "original_error": "error",
            "original_uncertainty_type": "flag_type",
        }
    )
    triage_scope(x, name)
pd.DataFrame(triage).to_csv(
    OUTPUT_DIR / "uncertainty_flag_performance.csv", index=False
)
pd.DataFrame(confusions).to_csv(
    OUTPUT_DIR / "uncertainty_confusion_counts.csv", index=False
)
quality = []
qdiff = []


def quality_scope(x, scope, model="pooled", clustering="report"):
    eng = engines[clustering]
    if model != "pooled":
        x = x[x.model == model]
    metricpairs = {}
    for vis in ["visible", "hidden"]:
        z = x[x.explicit_flag_visibility == vis]
        oe = z.original_error.astype(int)
        re = z.reviewed_error.astype(int)
        for metric, num, den in [
            ("net_verification_change", re - oe, np.ones(len(z))),
            ("residual_error", re, np.ones(len(z))),
            ("original_errors_corrected", ((oe == 1) & (re == 0)).astype(int), oe),
            (
                "original_correct_made_wrong",
                ((oe == 0) & (re == 1)).astype(int),
                1 - oe,
            ),
        ]:
            row, boot = ratio_result(
                eng,
                z,
                num,
                den,
                metric,
                scope=scope,
                model=model,
                clustering=clustering,
                explicit_flag_visibility=vis,
            )
            quality.append(row)
            metricpairs[metric, vis] = (row["estimate"], boot)
    for metric in [
        "net_verification_change",
        "residual_error",
        "original_errors_corrected",
        "original_correct_made_wrong",
    ]:
        e1, b1 = metricpairs[metric, "visible"]
        e0, b0 = metricpairs[metric, "hidden"]
        qdiff.append(
            result(
                metric,
                e1 - e0,
                b1 - b0,
                scope=scope,
                model=model,
                clustering=clustering,
                contrast="explicit_flag_visible_minus_hidden",
            )
        )


for task in ["data", "rob"]:
    x = primary_fields[primary_fields.task == task]
    for model in ["pooled", "gpt", "claude"]:
        quality_scope(x, task + "_primary", model)
    quality_scope(x, task + "_primary", "pooled", "known_companion")
quality_scope(
    primary_fields[primary_fields.domain == "rob_judgment"], "rob_judgment_secondary"
)
quality_scope(composite[composite.primary_eligible], "rob_item_composite_secondary")
pd.DataFrame(quality).to_csv(OUTPUT_DIR / "verification_quality.csv", index=False)
pd.DataFrame(qdiff).to_csv(OUTPUT_DIR / "visibility_quality_contrasts.csv", index=False)
patterns = []
for (task, dom, model), x in fields[fields.primary_eligible].groupby(
    ["task", "domain", "model"]
):
    for version in ["original", "reviewed"]:
        for et in ["E1", "E2"]:
            e = x[version + "_error_type"].eq(et)
            patterns.append(
                dict(
                    task=task,
                    domain=dom,
                    model=model,
                    version=version,
                    error_type=et,
                    count=int(e.sum()),
                    denominator=len(x),
                    unflagged_count=int((e & ~x.original_uncertainty_flagged).sum()),
                )
            )
pd.DataFrame(patterns).to_csv(OUTPUT_DIR / "error_patterns.csv", index=False)
nulls = []
for (task, dom, model), x in field_records[
    field_records.primary_eligible & field_records.reference_is_null
].groupby(["task", "domain", "model"]):
    for version in ["original", "reviewed"]:
        nulls.append(
            dict(
                task=task,
                domain=dom,
                model=model,
                version=version,
                active_reference_blank_fields=len(x),
                nonblank_assertion_errors=int(
                    (
                        x[version + "_error"].eq(1)
                        & x[version + "_value_json"].map(
                            lambda v: json.loads(v) is not None
                        )
                    ).sum()
                ),
                omitted_row_blank_fields=int((~x.original_row_present).sum()),
            )
        )
pd.DataFrame(nulls).to_csv(OUTPUT_DIR / "reference_blank_audit.csv", index=False)
pd.DataFrame(dataset["extras"]).groupby(
    ["study_id", "model", "kind", "method"]
).size().reset_index(name="unnecessary_records").to_csv(
    OUTPUT_DIR / "extra_record_audit.csv", index=False
)
assert (
    len(prediction_units[(prediction_units.task == "data") & prediction_units.emitted])
    == field_records[
        field_records.primary_eligible
        & (field_records.task == "data")
        & field_records.original_row_present
    ]
    .groupby(["source_id", "domain"])
    .ngroups
)
assert all(
    prediction_units.loc[prediction_units.synthetic_omission, "error"] == 1
) and (not prediction_units.loc[prediction_units.synthetic_omission, "flagged"].any())
assert int(
    prediction_units[
        (prediction_units.task == "data") & prediction_units.emitted
    ].member_fields.sum()
) == len(
    field_records[
        field_records.primary_eligible
        & (field_records.task == "data")
        & field_records.original_row_present
    ]
)
assert len(prediction_units[prediction_units.task == "rob"]) == int(
    rationale_records.primary_eligible.sum()
)
(OUTPUT_DIR / "python_environment.json").write_text(
    json.dumps(
        {
            "python": sys.version,
            "platform": platform.platform(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        indent=2,
    )
    + "\n"
)
print(
    "Accuracy, uncertainty-flag performance, omission sensitivity and randomized verification-quality contrasts completed."
)
