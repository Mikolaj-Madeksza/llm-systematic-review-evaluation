"""Current omission, verification-denominator and session-level results."""

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "03_analysis/results/current"
dataset = json.loads(gzip.decompress((ROOT / "02_data/dataset.json.gz").read_bytes()))
fields = pd.read_csv(OUTPUT_DIR / "primary_scored_fields.csv.gz", low_memory=False)
weights = np.load(OUTPUT_DIR / "bootstrap_weights.npz")["report"]
ids = sorted(fields.study_id.unique())
corrections = []
for task in ["data", "rob"]:
    for vis in ["visible", "hidden"]:
        z = fields[(fields.task == task) & (fields.explicit_flag_visibility == vis)]
        for universe in [
            "All target fields",
            "Presented target fields",
            "Omitted target fields",
        ]:
            x = (
                z
                if universe == "All target fields"
                else z[z.original_row_present.eq(universe == "Presented target fields")]
            )
            oe = x.original_error.astype(int)
            re = x.reviewed_error.astype(int)
            corrected = oe.eq(1) & re.eq(0)
            introduced = oe.eq(0) & re.eq(1)
            assert re.sum() == oe.sum() - corrected.sum() + introduced.sum()
            t = (
                pd.DataFrame(
                    {"study": x.study_id, "num": corrected.astype(int), "den": oe}
                )
                .groupby("study")[["num", "den"]]
                .sum()
                .reindex(ids, fill_value=0)
            )
            den = weights @ t.den.to_numpy()
            draw = np.divide(
                weights @ t.num.to_numpy(),
                den,
                out=np.full(len(weights), np.nan),
                where=den > 0,
            )
            valid = draw[np.isfinite(draw)]
            corrections.append(
                dict(
                    task=task,
                    visibility=vis,
                    universe=universe,
                    n_fields=len(x),
                    original_errors=int(oe.sum()),
                    returned_errors=int(re.sum()),
                    corrected=int(corrected.sum()),
                    introduced=int(introduced.sum()),
                    correction_rate=corrected.sum() / oe.sum() if oe.sum() else None,
                    ci_low=float(np.quantile(valid, 0.025))
                    if len(valid) >= 9500
                    else None,
                    ci_high=float(np.quantile(valid, 0.975))
                    if len(valid) >= 9500
                    else None,
                    n_valid=len(valid),
                    n_sessions=x.session_id.nunique(),
                )
            )
pd.DataFrame(corrections).to_csv(
    OUTPUT_DIR / "correction_denominator_audit.csv", index=False
)
sessions = []
ss = {s["session_id"]: s for s in dataset["sessions"]}
for sid, x in fields.groupby("session_id"):
    s = ss[sid]
    sessions.append(
        dict(
            session_id=sid,
            study_id=s["study_id"],
            task=s["task"],
            model=s["model"],
            reviewer=s["reviewer"],
            explicit_flag_visibility=s["uncertainty_visibility"],
            review_order=s["review_order"],
            n=len(x),
            delta=float((x.reviewed_error - x.original_error).mean()),
        )
    )
pd.DataFrame(sessions).to_csv(OUTPUT_DIR / "net_change_sessions.csv", index=False)
q = pd.read_csv(OUTPUT_DIR / "visibility_quality_contrasts.csv")
q[q.metric == "net_verification_change"].to_csv(
    OUTPUT_DIR / "net_verification_change_contrasts.csv", index=False
)
refs = {x["target_id"]: x for x in dataset["reference_rows"]}
scope = json.loads((ROOT / "02_data/rules/prompt_scope.json").read_text())
miss = fields[(fields.task == "data") & ~fields.original_row_present]
rows = []
for tid, x in miss.groupby("target_id"):
    ref = refs[tid]["reference_row_json"]
    m = sorted(x.model.unique())
    rows.append(
        dict(
            target_id=tid,
            study_id=ref["study_id"],
            outcome=ref["outcome"],
            outcome_variant=ref.get("outcome_variant"),
            arm_id=ref.get("arm_id"),
            vitd=ref["vitd"],
            dose_IU_day_equivalent=ref["dose_IU_day_equivalent"],
            cointervention=ref["cointervention"],
            week=ref["week"],
            value_type=ref["value_type"],
            omitted_by="; ".join(m),
            gpt_field_errors=int(x[x.model == "gpt"].original_error.sum()),
            claude_field_errors=int(x[x.model == "claude"].original_error.sum()),
            source=refs[tid]["source_locator"],
            scope_cell=scope["targets"][tid]["workbook_cell"],
        )
    )
pd.DataFrame(rows).to_csv(OUTPUT_DIR / "omitted_rows.csv", index=False)
summary = {
    "distinct_omitted_rows": len(rows),
    "reports": len({r["study_id"] for r in rows}),
    "models": {
        m: {
            "omitted_rows": miss[miss.model == m].target_id.nunique(),
            "omitted_field_errors": int(miss[miss.model == m].original_error.sum()),
        }
        for m in ["gpt", "claude"]
    },
}
assert all(r["gpt_field_errors"] + r["claude_field_errors"] > 0 for r in rows)
(OUTPUT_DIR / "omission_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
