"""Compile study-specific extraction scope from the prompting metadata workbook."""

import csv
import hashlib
import json
import os
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "02_data"
OUTPUT = Path(os.environ.get("SLR_DATA_OUTPUT", str(DATA)))
(OUTPUT / "rules").mkdir(parents=True, exist_ok=True)
BOOK = DATA / "inputs/metadata_reference_standard.xlsx"
SHEET = "1. Study Metadata"


def main():
    ws = openpyxl.load_workbook(BOOK, data_only=True)[SHEET]
    studies = {}
    for row in ws.iter_rows(min_row=2):
        if not row[0].value:
            continue
        sid = str(row[0].value).strip()
        assert sid not in studies
        studies[sid] = {
            "row": row[0].row,
            "outcomes": sorted(
                {
                    v.strip()
                    for c in row[9:13]
                    for v in str(c.value or "").split(";")
                    if v.strip()
                }
            ),
            "reported_names": row[13].value or "",
            "notes": row[14].value or "",
            "excluded_groups": row[25].value or "",
        }
    reference_standard = json.loads(
        (DATA / "reference/reference_standard.json").read_text()
    )
    decisions = {}
    inventory = []
    variants = {
        "angellotti_2018": {
            "fasting": (
                "ISR total",
                "Total insulin secretion rate is the specified measure.",
            )
        },
        "kampmann_2014": {
            "total_AUC_1_10min": (
                "Incremental AUC insulin1–10 min",
                "Incremental insulin AUC is the specified measure.",
            )
        },
        "rasouli_2021": {
            v: ("use insulin-based indices", "Insulin-based indices are specified.")
            for v in ["DI_C_peptide", "HOMA2_B_C_peptide", "C_peptide_index"]
        },
        "von_hurst_2010": {
            "HOMA1_IR": ("HOMA2-IR", "HOMA2-IR is the specified measure.")
        },
        "wallace_2019": {
            "HOMA1_IR": ("HOMA2-IR", "HOMA2-IR is the specified measure."),
            "HOMA1_B": ("HOMA2-B", "HOMA2-B is the specified measure."),
        },
        "yeow_2015": {
            "IGI_global_Cpeptide": (
                "IGI60",
                "IGI60 is the specified insulinogenic index.",
            )
        },
    }
    for sid, study in sorted(reference_standard.items()):
        m = studies[sid]
        rn = m["row"]
        for i, r in enumerate(study["data"]):
            tid = f"{sid}:data:{i + 1:03d}"
            allowed = r["outcome"] in m["outcomes"]
            cell = f"J{rn}:M{rn}"
            reason = (
                "Outcome is listed and no study-specific subtype or arm exclusion applies."
                if allowed
                else "Outcome is not requested in the study-specific outcome list."
            )
            if sid == "raja_khan_2014" and r["outcome"] == "isi_0_120":
                assert "Insulin sensitivity index0,120" in m["reported_names"]
                allowed = True
                cell = f"N{rn}"
                reason = "The named source measure ISI 0,120 is explicitly requested; retain its source-correct code."
            if sid == "yeow_2015" and r["outcome"] == "first_phase_ins":
                assert "BIGTT-AIR" in m["reported_names"]
                allowed = True
                cell = f"N{rn}"
                reason = "BIGTT-AIR is explicitly listed as first-phase insulin in the reported outcome names."
            excluded_arm = (
                sid == "dall_2020"
                and r.get("vitd") == 1
                and (r.get("cointervention") == 1)
                or (sid == "guo_2022" and r.get("arm_id") == "corn_oil_control")
                or (sid == "mostafai_2018" and r.get("arm_id") == "oral_vitamin_D")
                or (sid == "nikooyeh_2011" and r.get("arm_id") == "DCY")
            )
            if excluded_arm:
                assert m["excluded_groups"]
                allowed = False
                cell = f"Z{rn}"
                reason = (
                    "The study arm is explicitly excluded from extraction: "
                    + m["excluded_groups"]
                    + "."
                )
            variant = variants.get(sid, {}).get(r.get("outcome_variant"))
            if variant:
                assert variant[0] in m["reported_names"]
                allowed = False
                cell = f"N{rn}"
                reason = variant[1]
            if sid == "molani_gol_2025" and r["outcome"] in ["homa_ir", "quicki"]:
                assert "exclude from methodological paper" in m["notes"]
                allowed = False
                cell = f"O{rn}"
                reason = "The workbook excludes HOMA-IR and QUICKI from the methodological study."
            if sid == "rasouli_2021" and r["outcome"] == "serum_25ohd":
                assert "DROP" in m["notes"]
                allowed = False
                cell = f"O{rn}"
                reason = "The workbook excludes vitamin D status for this report."
            if sid == "anyanwu_2016" and r["outcome"] == "homa_b":
                allowed = False
                cell = f"O{rn}"
                reason = "The workbook excludes figure-only HOMA-B from the methodological study."
            decision = {
                "eligible": allowed,
                "workbook_cell": f"'{SHEET}'!{cell}",
                "reason": reason,
            }
            decisions[tid] = decision
            inventory.append(
                {
                    "target_id": tid,
                    "study_id": sid,
                    "outcome": r["outcome"],
                    "outcome_variant": r.get("outcome_variant"),
                    "arm_id": r.get("arm_id"),
                    "week": r.get("week"),
                    **decision,
                }
            )
    assert len(reference_standard) == 96 and len(decisions) == 2272
    payload = {
        "reference": "inputs/metadata_reference_standard.xlsx",
        "sha256": hashlib.sha256(BOOK.read_bytes()).hexdigest(),
        "sheet": SHEET,
        "studies": studies,
        "targets": decisions,
        "interpretation": {
            "nimitphong_2015": "Combined D2/D3 outcome rows follow the source reporting. Separately reported 25(OH)D values remain separate; no unreported pooled values are calculated.",
            "dutta_2014": "Nonrandomized vitamin-D-sufficient group C is outside the mapped extraction reference.",
            "outcome_names": "Explicit source-measure names in column N resolve codes and subtypes.",
        },
    }
    (OUTPUT / "rules/prompt_scope.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )
    with (OUTPUT / "rules/prompt_scope.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as f:
        w = csv.DictWriter(f, fieldnames=list(inventory[0]))
        w.writeheader()
        w.writerows(inventory)
    print(
        json.dumps(
            {
                "reports": len(reference_standard),
                "targets_checked": len(decisions),
                "in_scope": sum(x["eligible"] for x in decisions.values()),
                "out_of_scope": sum(not x["eligible"] for x in decisions.values()),
            }
        )
    )


if __name__ == "__main__":
    main()
