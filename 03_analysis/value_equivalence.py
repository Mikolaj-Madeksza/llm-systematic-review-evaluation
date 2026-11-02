"""Compare values using source-reviewed equivalence rules."""

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_VERSION = "source_review_equivalence_2026-11-01"
SUPPORT_FIELDS = ("support", "step1_support", "step2_support")
UNIT_GROUPS = [
    ["mg/dL", "mg/dl"],
    ["ng/mL", "ng/ml"],
    ["nmol/L", "nmol/l", "nmol L-1"],
    ["mmol/L", "mmol/l", "mmol L-1"],
    ["mU L^-1 min", "mU . L-1 . min", "mU.L-1.min", "mU z L-1 z min"],
    ["mL/min/m2", "ml/min/m2", "mlmin-1m-2"],
    ["mg/kg/min", "mg kg-1 min-1", "mgkg-1min-1", "mg x kg-1 x min-1"],
    ["uU/mL/mmol/L", "uU/mL per mmol/L"],
    ["mg/kg*min", "mg/kg x min"],
]
DOSE_GROUPS = [
    [7143, 7142.857, 7142.857142857143],
    [3571, 3571.43, 3571.428571, 3571.4285714285716, 3571.428571428572],
    [2857, 2857.142857],
    [2143, 2142.857143],
]
PERCENT_GROUPS = [[6.7, 6.67], [22.2, 22.22], [14.4, 14.44]]
PRECISION = json.loads((ROOT / "02_data/rules/timepoint_policy.json").read_text())[
    "reverted_precision_aliases"
]
CANDIDATE_WEEK_FORMAT_GROUPS = {
    "oosterwerff_2014": [{16, 17.332, 17.333}],
    "javed_2019": [{12, 13, 12.999}],
    "ardabili_2012": [{8, 8.666}],
    "von_hurst_2010": [{12, 12.999, 13}],
}


def lexical(v):
    if not isinstance(v, str):
        return v
    return " ".join(
        unicodedata.normalize("NFKC", v).replace("−", "-").replace("–", "-").split()
    ).strip()


def groups_equal(a, b, groups):
    return any(a in group and b in group for group in groups)


def unit_key(value):
    """Normalize typography only; retain prefixes, scales and exponent signs."""
    if not isinstance(value, str):
        return value
    value = lexical(value).replace("µ", "u").replace("μ", "u")
    value = re.sub("\\bper\\b", "/", value)
    value = re.sub("(?<!mo)l(?=$|[^A-Za-z])", "L", value)
    return re.sub("\\s+", "", value).replace("^", "")


def unit_equal(left, right):
    a, b = (unit_key(left), unit_key(right))
    if a == b:
        return True
    if a is None or b is None:
        return False
    return groups_equal(a, b, [[unit_key(x) for x in group] for group in UNIT_GROUPS])


def time_groups(study_id):
    groups = [set(x) for x in CANDIDATE_WEEK_FORMAT_GROUPS.get(study_id, [])]
    for key, value in PRECISION.get(study_id, {}).items():
        group = {float(key), value}
        overlaps = [g for g in groups if g & group]
        for g in overlaps:
            group.update(g)
            groups.remove(g)
        groups.append(group)
    return groups


def comparison(field, left, right, study_id=None, accepted_values=None):
    """Return (equivalent, reason); not-scored fields are handled by the caller."""
    if left == right:
        return (True, "literal_match")
    if accepted_values and left in accepted_values and (right in accepted_values):
        return (True, "equivalent_source_reviewed_representation")
    if field == "unit" and accepted_values:
        if any(unit_equal(left, x) for x in accepted_values) and any(
            unit_equal(right, x) for x in accepted_values
        ):
            return (True, "equivalent_source_reviewed_unit_notation")
    if left is None or right is None:
        return (False, "substantive_value_difference")
    a, b = (lexical(left), lexical(right))
    if field == "unit":
        if unit_equal(a, b):
            return (True, "equivalent_unit_notation")
        return (False, "substantive_unit_difference")
    if field == "week" and groups_equal(left, right, time_groups(study_id)):
        return (True, "equivalent_timepoint_precision")
    if field == "dose_IU_day_equivalent" and groups_equal(left, right, DOSE_GROUPS):
        return (True, "equivalent_daily_dose_rounding")
    if field == "pct_not_analyzed" and groups_equal(left, right, PERCENT_GROUPS):
        return (True, "equivalent_percentage_rounding")
    if field in ["step1", "step2"] and isinstance(a, str) and isinstance(b, str):

        def rating(x):
            return {"peobably low": "probably low", "probaly low": "probably low"}.get(
                x.casefold(), x.casefold()
            )

        if rating(a) == rating(b):
            return (True, "equivalent_rating_spelling")
    if field == "outcomes_assessed" and isinstance(a, str) and isinstance(b, str):

        def scope(x):
            return sorted(t.strip().casefold() for t in x.split(","))

        if scope(a) == scope(b):
            return (True, "equivalent_outcome_scope_order")
    if (
        field in ["analysis_population", "reported_statistic", "value_type", "outcome"]
        and isinstance(a, str)
        and isinstance(b, str)
    ):
        if a.casefold() == b.casefold():
            return (True, "equivalent_metadata_format")
    return (False, "substantive_value_difference")


def record_comparison(
    field, submitted, reference, study_id, status=None, alternatives=None
):
    """Compare a complete row representation, including its unit."""
    status = status or {}
    for rep in (alternatives or {}).get("representations", []):
        applicable = all(
            (
                unit_equal(submitted.get(k), v)
                if k == "unit"
                else submitted.get(k) == v
                for k, v in rep["when"].items()
            )
        )
        applicable = (
            applicable
            and all(
                submitted.get(k) is not None for k in rep.get("nonblank_fields", [])
            )
            and all(submitted.get(k) is None for k in rep.get("blank_fields", []))
        )
        if applicable and field in rep["values"]:
            ok, rule = comparison(
                field, submitted.get(field), rep["values"][field], study_id
            )
            return (
                ok,
                "equivalent_source_published_row_representation" if ok else rule,
            )
    return comparison(
        field,
        submitted.get(field),
        reference.get(field),
        study_id,
        status.get("accepted_values"),
    )


def whole_rationale(row, prefix=""):
    """Combine distinct nonblank rationale fields."""
    parts = []
    for field in SUPPORT_FIELDS:
        value = row.get(prefix + field)
        if value and value not in parts:
            parts.append(value)
    return "\n".join(parts) or None
